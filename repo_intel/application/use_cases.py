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
    normalize,
    rerank_results,
    retrieve_lexical_candidates,
    write_answer_plan_debug,
)
from repo_intel.core.config import load_config, resolve_workspace_path, write_default_config
from repo_intel.domain.models import (
    AskCacheRecord,
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

    def scan(
        self,
        persist: bool = True,
        full: bool = False,
    ) -> tuple[list[RepositoryRecord], list[SddDocumentRecord]]:
        repositories = discover_repositories(self.workspace, self.config)
        reuse = {} if full else {doc.id: doc for doc in self.store.all_documents()}
        documents = discover_sdd_documents(self.workspace, self.config, repositories, reuse=reuse)
        if persist:
            # sync_scan, never upsert_scan: the latter truncates chunks+embeddings, which
            # would silently discard the whole vector index on every plain `scan`.
            # Persisting here is safe for the *next* ingest because sync_scan only writes
            # discovery metadata; `indexed_hash` -- the column the incremental gate reads
            # -- is advanced by ingest alone. Scanning can therefore never mark a
            # document as indexed when its text was never chunked.
            self.store.sync_scan(repositories, documents, force=full)
            self.write_artifacts(repositories, documents, [])
        return repositories, documents

    def ingest(self, full: bool = False) -> IngestionRunRecord:
        """Index the workspace, re-embedding only what changed.

        Incremental by default. The pipeline is gated at three levels, cheapest first:
        1. git metadata is reused for files whose sha256 is unchanged (`reuse`);
        2. only changed/removed documents are re-chunked and rewritten (`ScanDiff`);
        3. only chunks with no embedding row for the active model are sent to Ollama.

        Gate 2 compares against `indexed_hash`, which only this method advances and only
        after the chunk rows are committed -- so no other command can convince ingest
        that a document is done. Gate 3 asks the store rather than filtering this run's
        chunks, which makes the pass self-healing: chunks stranded by an earlier failure
        are picked up here even though their documents are long since unchanged.

        `full=True` forces every stage to recompute, embeddings included, and is the
        recovery path for a corrupted vector store.
        """
        self.init()
        run = IngestionRunRecord(
            id=f"run:{uuid.uuid4()}",
            workspace=str(self.workspace),
            started_at=utcnow(),
            mode="full" if full else "incremental",
        )
        self.store.create_run(run)
        errors: list[str] = []
        embeddings_count = 0

        repositories = discover_repositories(self.workspace, self.config)
        reuse = {} if full else {doc.id: doc for doc in self.store.all_documents()}
        documents = discover_sdd_documents(self.workspace, self.config, repositories, reuse=reuse)
        diff = self.store.sync_scan(repositories, documents, force=full)

        repo_by_id = {repo.id: repo for repo in repositories}
        chunks: list[SemanticChunkRecord] = []
        for document in documents:
            if document.id not in diff.changed_document_ids:
                continue
            repo = repo_by_id.get(document.repository_id)
            if not repo:
                continue
            chunks.extend(chunk_document(self.config, repo, document))

        self.store.replace_document_chunks(
            diff.changed_document_ids | diff.removed_document_ids,
            chunks,
        )

        # The chunk rows are committed, so these documents are genuinely in the index at
        # this text. Only now may the incremental gate close on them.
        self.store.mark_documents_indexed(
            {
                document.id: document.content_hash
                for document in documents
                if document.id in diff.changed_document_ids
            }
        )

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

        # Drop vectors whose chunk is gone, otherwise retrieval keeps citing deleted
        # text. The queue is durable and drained here, so a Chroma outage during one run
        # is retried by the next instead of stranding the vectors forever.
        orphaned_chunk_ids = self.store.pending_vector_deletions()
        if orphaned_chunk_ids:
            try:
                vector_index.delete_chunks(sorted(orphaned_chunk_ids))
                self.store.clear_pending_vector_deletions(orphaned_chunk_ids)
            except Exception as exc:
                errors.append(
                    f"Vector prune of {len(orphaned_chunk_ids)} chunk(s) failed "
                    f"(queued for retry): {exc}"
                )

        # Ask the STORE for what still needs embedding rather than filtering this run's
        # chunks. Chunk ids are content-addressed, so unchanged text is skipped either
        # way -- but only the store-derived set also picks up chunks whose embedding
        # failed on an earlier run. Those documents are unchanged on every later scan,
        # so a run-scoped set would never revisit them and their text would be missing
        # from retrieval permanently.
        # `--full` re-embeds unconditionally. Chunk ids are content-addressed, so
        # re-chunking identical text recreates identical ids and every embedding row
        # survives -- which used to make --full a full rescan that bought nothing and
        # left no way to rebuild a corrupted or partially-written vector store.
        pending = (
            self.store.all_chunks()
            if full
            else self.store.chunks_missing_embeddings(self.config.embeddings.model)
        )

        batch_size = 16
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
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
                # Do NOT break. A single bad batch used to abort the run and silently
                # leave every later chunk unembedded (one oversized chunk cost 808 of
                # 7848 chunks, ~10% of the corpus, with only a one-line warning).
                # Skip the batch, keep indexing, and surface it in run.errors.
                errors.append(f"Embedding batch {start}-{start + len(batch)} failed: {exc}")
                continue

        totals = self.store.counts()
        run.finished_at = utcnow()
        run.repos_count = len(repositories)
        run.docs_count = len(documents)
        # Totals describe corpus coverage; the transient counters below describe this
        # run's work. A no-op incremental run must report full coverage, not zero.
        run.chunks_count = totals["chunks"]
        run.embeddings_count = totals["embeddings"]
        run.documents_changed = len(diff.changed_document_ids)
        run.documents_removed = len(diff.removed_document_ids)
        run.chunks_created = len(chunks)
        run.embeddings_created = embeddings_count
        run.errors = errors
        self.store.finish_run(run)
        self.write_artifacts(repositories, documents, self.store.all_chunks())
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
        # embed_query, not embed: the retrieval side needs nomic's "search_query: " prefix.
        # Embedding the question as if it were a stored passage collapses the score spread
        # and the ranking degrades to near-random (see ollama_embeddings for the numbers).
        result = vector_index.query(embedder.embed_query(question), n_results=limit)
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

    def search(self, question: str, limit: int = 8) -> list[dict]:
        """Hybrid retrieval: the same semantic+lexical blend `ask` feeds its LLM.

        `query` above is the pure-vector half and stays that way — `ask` composes it with the
        lexical half itself, so making `query` hybrid would merge twice. But everything else
        that retrieves (the `query` CLI command, the MCP `search_docs` tool) was calling the
        vector half directly and therefore never saw a lexical hit.

        That gap is not academic: dense retrieval on this corpus ranks a guardrail about
        Alembic revision ids below unrelated docs even when the query quotes it almost
        verbatim, while the lexical side matches the literal terms instantly. `ask` answered
        such questions correctly and `search_docs` returned nothing useful for the same
        question — the difference was entirely this missing merge.
        """
        # Build the plan off the engine's own default, NOT off `limit`. `limit` is how many
        # rows the caller wants BACK; using it as the candidate pool too means we retrieve a
        # handful and then "rerank" them, which cannot surface anything the initial fetch
        # missed. `ask` gets this right by planning from config.llm.context_chunks, and that
        # is exactly why `ask` found the Alembic guardrail while a 6-row search did not.
        # Fetch wide, rerank, then truncate.
        plan = build_retrieval_plan(classify_question(question), None, self.config.llm.context_chunks)
        semantic = self.query(question, limit=max(limit, plan.candidate_limit))
        lexical = retrieve_lexical_candidates(self.workspace, question, limit=plan.lexical_limit)
        merged = merge_candidates(semantic, lexical)
        return rerank_results(question, merged, plan)[:limit]

    def ask(self, question: str, limit: int | None = None) -> dict:
        from repo_intel.enrichers.factory import build_ask_client

        intent = classify_question(question)
        plan = build_retrieval_plan(intent, limit, self.config.llm.context_chunks)
        normalized_question = normalize(question.strip())
        knowledge_fingerprint = self.store.knowledge_fingerprint()
        cached = self.store.get_ask_cache(
            normalized_question=normalized_question,
            knowledge_fingerprint=knowledge_fingerprint,
            model_provider=self.config.llm.provider,
            model=self.config.llm.model,
            context_chunks=self.config.llm.context_chunks,
        )
        if cached:
            touched = self.store.touch_ask_cache(cached.id) or cached
            write_answer_plan_debug(
                self.workspace,
                question,
                plan,
                [],
                [],
                cache_hit=True,
                cache_id=touched.id,
            )
            return {
                "answer": touched.answer,
                "sources": touched.sources,
                "intent": touched.intent,
                "cached": True,
                "cache_id": touched.id,
            }

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
            cache_hit=False,
        )
        prompt = build_answer_prompt(
            project_name=self.config.project_name,
            question=question,
            results=results,
        )
        client = build_ask_client(self.config)
        answer = sanitize_answer(client.generate(prompt))
        sources = format_sources(results)
        cache_record = AskCacheRecord(
            id=f"ask-cache:{uuid.uuid4()}",
            question=question,
            normalized_question=normalized_question,
            answer=answer,
            intent=intent.name,
            sources=sources,
            selected_chunk_ids=[str(result.get("id", "")) for result in results],
            knowledge_fingerprint=knowledge_fingerprint,
            model_provider=self.config.llm.provider,
            model=self.config.llm.model,
            context_chunks=self.config.llm.context_chunks,
            created_at=utcnow(),
            hit_count=0,
        )
        self.store.put_ask_cache(cache_record)
        return {
            "answer": answer,
            "sources": sources,
            "intent": intent.name,
            "cached": False,
            "cache_id": cache_record.id,
        }

    def brief(self, refresh_scan: bool = False) -> Path:
        from repo_intel.enrichers.factory import build_brief_client

        if refresh_scan:
            repositories, documents = self.scan(persist=True)
        else:
            repositories, documents = self.scan(persist=False)

        context = build_brief_context(repositories, documents, self.config.brief.max_input_chars)
        prompt = build_brief_prompt(self.config.project_name, context)
        try:
            brief_text = build_brief_client(self.config).generate(prompt)
        except Exception as exc:
            # brief.fallback_provider / fallback_model were declared and serialized but
            # never read by any code path. They are honoured now: a failure of the
            # primary provider (missing key, gateway down, model unavailable) retries
            # once against the fallback instead of aborting the command.
            fallback_provider = self.config.brief.fallback_provider
            if not fallback_provider or fallback_provider == self.config.brief.provider:
                raise
            print(
                f"brief: provider {self.config.brief.provider!r} failed ({exc}); "
                f"retrying with fallback {fallback_provider!r}"
            )
            brief_text = build_brief_client(
                self.config,
                provider=fallback_provider,
                model=self.config.brief.fallback_model,
            ).generate(prompt)

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
