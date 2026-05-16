from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from repo_intel.application.answer_engine import (
    build_answer_context,
    build_retrieval_plan,
    classify_question,
    merge_candidates,
    retrieve_lexical_candidates,
    write_answer_plan_debug,
)
from repo_intel.core.config import load_config, resolve_workspace_path, write_default_config
from repo_intel.domain.models import (
    EmbeddingRecord,
    IngestionRunRecord,
    RepositoryRecord,
    SddDocumentRecord,
    SemanticChunkRecord,
)
from repo_intel.sdd.chunking import chunk_document
from repo_intel.sdd.discovery import discover_repositories, discover_sdd_documents
from repo_intel.storage.sqlite import KnowledgeStore, utcnow


class SddKnowledgeService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.config = load_config(self.workspace)
        self.store = KnowledgeStore(resolve_workspace_path(self.workspace, self.config.storage.sqlite_path))

    def init(self) -> Path:
        path = write_default_config(self.workspace)
        self.store.init_schema()
        resolve_workspace_path(self.workspace, self.config.storage.chroma_path).mkdir(
            parents=True,
            exist_ok=True,
        )
        (self.workspace / ".repo-intel" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.workspace / ".repo-intel" / "exports").mkdir(parents=True, exist_ok=True)
        return path

    def scan(self, persist: bool = True) -> tuple[list[RepositoryRecord], list[SddDocumentRecord]]:
        repositories = discover_repositories(self.workspace, self.config)
        documents = discover_sdd_documents(self.workspace, self.config, repositories)
        if persist:
            self.store.upsert_scan(repositories, documents)
            self.write_artifacts(repositories, documents, [])
        return repositories, documents

    def ingest(self) -> IngestionRunRecord:
        self.init()
        run = IngestionRunRecord(
            id=f"run:{uuid.uuid4()}",
            workspace=str(self.workspace),
            started_at=utcnow(),
        )
        self.store.create_run(run)
        errors: list[str] = []
        embeddings_count = 0

        repositories, documents = self.scan(persist=True)
        repo_by_id = {repo.id: repo for repo in repositories}
        chunks: list[SemanticChunkRecord] = []
        for document in documents:
            repo = repo_by_id.get(document.repository_id)
            if not repo:
                continue
            chunks.extend(chunk_document(self.config, repo, document))
        self.store.replace_chunks(chunks)

        from repo_intel.enrichers.ollama_embeddings import OllamaEmbeddingClient
        from repo_intel.storage.vector import ChromaKnowledgeIndex

        embedder = OllamaEmbeddingClient(
            base_url=self.config.embeddings.base_url,
            model=self.config.embeddings.model,
        )
        vector_index = ChromaKnowledgeIndex(
            resolve_workspace_path(self.workspace, self.config.storage.chroma_path),
            self.config.storage.collection,
        )

        batch_size = 16
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            try:
                embeddings = embedder.embed_batch([chunk.text for chunk in batch])
                vector_index.upsert_chunks(batch, embeddings)
                for chunk in batch:
                    self.store.upsert_embedding(
                        EmbeddingRecord(
                            id=f"embedding:{chunk.id}:{self.config.embeddings.model}",
                            chunk_id=chunk.id,
                            provider=self.config.embeddings.provider,
                            model=self.config.embeddings.model,
                            vector_store_id=chunk.id,
                            indexed_at=utcnow(),
                        )
                    )
                embeddings_count += len(batch)
            except Exception as exc:
                errors.append(f"Embedding batch {start}-{start + len(batch)} failed: {exc}")
                break

        run.finished_at = utcnow()
        run.repos_count = len(repositories)
        run.docs_count = len(documents)
        run.chunks_count = len(chunks)
        run.embeddings_count = embeddings_count
        run.errors = errors
        self.store.finish_run(run)
        self.write_artifacts(repositories, documents, chunks)
        return run

    def query(self, question: str, limit: int = 8) -> list[dict]:
        from repo_intel.enrichers.ollama_embeddings import OllamaEmbeddingClient
        from repo_intel.storage.vector import ChromaKnowledgeIndex

        embedder = OllamaEmbeddingClient(
            base_url=self.config.embeddings.base_url,
            model=self.config.embeddings.model,
        )
        vector_index = ChromaKnowledgeIndex(
            resolve_workspace_path(self.workspace, self.config.storage.chroma_path),
            self.config.storage.collection,
        )
        result = vector_index.query(embedder.embed(question), n_results=limit)
        rows: list[dict] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for idx, chunk_id in enumerate(ids):
            rows.append(
                {
                    "id": chunk_id,
                    "text": docs[idx] if idx < len(docs) else "",
                    "metadata": metadatas[idx] if idx < len(metadatas) else {},
                    "distance": distances[idx] if idx < len(distances) else None,
                }
            )
        return rows

    def ask(self, question: str, limit: int | None = None) -> dict:
        from repo_intel.enrichers.ollama_chat import OllamaChatClient

        intent = classify_question(question)
        plan = build_retrieval_plan(intent, limit, self.config.llm.context_chunks)
        semantic_candidates = self.query(question, limit=plan.candidate_limit)
        lexical_candidates = retrieve_lexical_candidates(
            self.workspace,
            question,
            limit=plan.lexical_limit,
        )
        candidates = merge_candidates(semantic_candidates, lexical_candidates)
        results = build_answer_context(self.workspace, question, candidates, plan)
        write_answer_plan_debug(
            self.workspace,
            question,
            plan,
            candidates,
            results,
            semantic_candidates=semantic_candidates,
            lexical_candidates=lexical_candidates,
        )
        prompt = build_answer_prompt(
            project_name=self.config.project_name,
            question=question,
            results=results,
        )
        client = OllamaChatClient(
            base_url=self.config.llm.base_url,
            model=self.config.llm.model,
            temperature=self.config.llm.temperature,
            num_predict=self.config.llm.num_predict,
        )
        return {
            "answer": sanitize_answer(client.generate(prompt)),
            "sources": format_sources(results),
            "intent": intent.name,
        }

    def brief(self, refresh_scan: bool = False) -> Path:
        from repo_intel.enrichers.openrouter_chat import OpenRouterChatClient

        if refresh_scan:
            repositories, documents = self.scan(persist=True)
        else:
            repositories, documents = self.scan(persist=False)

        context = build_brief_context(repositories, documents, self.config.brief.max_input_chars)
        prompt = build_brief_prompt(self.config.project_name, context)
        client = OpenRouterChatClient(
            model=self.config.brief.model,
            api_key_env=self.config.brief.api_key_env,
            site_url=self.config.brief.site_url,
            app_name=self.config.brief.app_name,
            temperature=self.config.brief.temperature,
            max_tokens=self.config.brief.max_output_tokens,
        )
        brief_text = client.generate(prompt)

        brief_dir = self.workspace / ".repo-intel" / "briefs"
        brief_dir.mkdir(parents=True, exist_ok=True)
        output_path = brief_dir / "project-brief.md"
        output_path.write_text(brief_text.rstrip() + "\n", encoding="utf-8")
        return output_path

    def status(self) -> dict:
        return {
            "workspace": str(self.workspace),
            "config": self.config.model_dump(),
            "counts": self.store.counts(),
            "latest_run": (
                self.store.latest_run().model_dump(mode="json") if self.store.latest_run() else None
            ),
        }

    def export(self) -> Path:
        chunks = self.store.all_chunks()
        export_dir = self.workspace / ".repo-intel" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        json_path = export_dir / "sdd_chunks.jsonl"
        md_path = export_dir / "sdd_context_bundle.md"

        with json_path.open("w", encoding="utf-8") as file:
            for chunk in chunks:
                file.write(chunk.model_dump_json() + "\n")

        lines = ["# SDD Context Bundle", ""]
        for chunk in chunks:
            metadata = chunk.metadata
            lines.extend(
                [
                    f"## {metadata.get('repo', 'unknown')} / {metadata.get('path', '')}",
                    "",
                    f"- Section: {metadata.get('section', '')}",
                    f"- Type: {metadata.get('doc_type', '')}",
                    f"- Branch: {metadata.get('branch', '')}",
                    f"- Commit: {metadata.get('last_modified_commit', '')}",
                    "",
                    chunk.text,
                    "",
                ]
            )
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return export_dir

    def reset(self) -> None:
        sqlite_path = resolve_workspace_path(self.workspace, self.config.storage.sqlite_path)
        chroma_path = resolve_workspace_path(self.workspace, self.config.storage.chroma_path)
        if sqlite_path.exists():
            sqlite_path.unlink()
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        self.init()

    def write_artifacts(
        self,
        repositories: list[RepositoryRecord],
        documents: list[SddDocumentRecord],
        chunks: list[SemanticChunkRecord],
    ) -> None:
        artifact_dir = self.workspace / ".repo-intel" / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "repositories.json").write_text(
            json.dumps([repo.model_dump(mode="json") for repo in repositories], indent=2),
            encoding="utf-8",
        )
        (artifact_dir / "documents.json").write_text(
            json.dumps([doc.model_dump(mode="json") for doc in documents], indent=2),
            encoding="utf-8",
        )
        if chunks:
            (artifact_dir / "chunks.json").write_text(
                json.dumps([chunk.model_dump(mode="json") for chunk in chunks], indent=2),
                encoding="utf-8",
            )


def build_answer_prompt(project_name: str, question: str, results: list[dict]) -> str:
    context_blocks = []
    for index, result in enumerate(results, start=1):
        metadata = result["metadata"]
        source = (
            f"Source [{index}]: {metadata.get('repo', '')} / {metadata.get('path', '')} / "
            f"{metadata.get('section', '')} ({metadata.get('doc_type', '')})"
        )
        context_blocks.append(f"{source}\n{result['text'][:1800]}")

    context = "\n\n---\n\n".join(context_blocks)
    return f"""You are answering questions about the {project_name} engineering SDD documentation.

Use only the provided SDD context. If the answer is not present in the context, say that the indexed SDD docs do not contain enough information.

Answer in Spanish unless the user asks otherwise.
Be concise, technical, and cite sources inline using [1], [2], etc.
Do not paste raw source blocks, metadata lines, or long excerpts from the context.
Write a synthesized answer first, then mention the most relevant citations inline.
Keep the answer under 8 short bullet points or 5 short paragraphs.
Use citations like [1] or [2], but do not print source metadata such as repo, path, section, commit, or score in the answer.
Do not add a "Referencias", "Fuentes", or bibliography section; the CLI prints sources separately.

Question:
{question}

SDD context:
{context}
"""


def sanitize_answer(answer: str) -> str:
    lines = answer.strip().splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(("referencias:", "fuentes:", "bibliografia:", "bibliografía:")):
            break
        if re.match(r"^\[\d+\]\s+\S+\s+/", stripped):
            break
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def format_sources(results: list[dict]) -> list[dict]:
    sources = []
    for index, result in enumerate(results, start=1):
        metadata = result["metadata"]
        sources.append(
            {
                "index": index,
                "repo": metadata.get("repo", ""),
                "path": metadata.get("path", ""),
                "section": metadata.get("section", ""),
                "doc_type": metadata.get("doc_type", ""),
                "distance": result.get("distance"),
                "commit": metadata.get("last_modified_commit", ""),
            }
        )
    return sources


def build_brief_context(
    repositories: list[RepositoryRecord],
    documents: list[SddDocumentRecord],
    max_chars: int,
) -> str:
    repo_names = {repo.id: repo.name for repo in repositories}
    priority = sorted(documents, key=brief_priority)
    blocks: list[str] = []
    size = 0
    for doc in priority:
        if brief_priority(doc)[0] >= 100:
            continue
        text = Path(doc.path).read_text(encoding="utf-8", errors="ignore")
        block = (
            f"# SOURCE repo={repo_names.get(doc.repository_id, doc.repository_id)} "
            f"path={doc.repo_relative_path} type={doc.doc_type}\n\n{text[:8000]}"
        )
        if size + len(block) > max_chars:
            break
        blocks.append(block)
        size += len(block)
    return "\n\n---\n\n".join(blocks)


def brief_priority(doc: SddDocumentRecord) -> tuple[int, str]:
    path = doc.repo_relative_path.lower()
    if path == "product.md":
        return (0, doc.relative_path)
    if path == "readme.md":
        return (1, doc.relative_path)
    if path == "ai_index.md":
        return (2, doc.relative_path)
    if path == "agent_start_here.md":
        return (3, doc.relative_path)
    if "/00-overview/" in path:
        return (4, doc.relative_path)
    if "architecture" in path or "/01-architecture/" in path:
        return (5, doc.relative_path)
    if "overview" in path:
        return (6, doc.relative_path)
    return (100, doc.relative_path)


def build_brief_prompt(project_name: str, context: str) -> str:
    return f"""Generate a human-oriented engineering/product brief for {project_name}.

Use only the provided SDD documentation context.

Write in Spanish.
Be accurate and avoid inventing capabilities.
Use this structure:

# {project_name} Project Brief

## Que es
## Para quien es
## Producto y capacidades principales
## Repositorios y responsabilidades
## Arquitectura de alto nivel
## Dominios funcionales
## Como entender el proyecto rapidamente
## Fuentes SDD usadas

SDD context:
{context}
"""
