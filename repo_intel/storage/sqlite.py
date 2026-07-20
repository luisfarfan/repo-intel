from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from repo_intel.domain.models import (
    AskCacheRecord,
    DocumentVersionRecord,
    EmbeddingRecord,
    GitDocumentMetadata,
    IngestionRunRecord,
    RepositoryRecord,
    SddDocumentRecord,
    SemanticChunkRecord,
)


class Base(DeclarativeBase):
    pass


class RepositoryRow(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str | None] = mapped_column(String)
    git_status: Mapped[str] = mapped_column(String, nullable=False)
    sdd_roots_json: Mapped[str] = mapped_column(Text, nullable=False)


class SddDocumentRow(Base):
    __tablename__ = "sdd_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("repositories.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    repo_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    # The hash that ingest actually chunked and wrote to the index. `content_hash` is
    # discovery metadata and any command may advance it; `indexed_hash` may only be
    # advanced by ingest, after chunks are committed. The incremental gate compares
    # against THIS column, so a plain `scan` can never convince ingest that a document
    # is already indexed when its text was never chunked.
    indexed_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    git_json: Mapped[str] = mapped_column(Text, nullable=False)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("sdd_documents.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String)
    timestamp: Mapped[str | None] = mapped_column(String)
    commit_message: Mapped[str | None] = mapped_column(Text)


class SemanticChunkRow(Base):
    __tablename__ = "semantic_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("sdd_documents.id"), nullable=False)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("repositories.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path_json: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)


class EmbeddingRow(Base):
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String, ForeignKey("semantic_chunks.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    vector_store_id: Mapped[str] = mapped_column(String, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PendingVectorDeletionRow(Base):
    """Chunk ids deleted from SQLite whose vectors are not yet pruned from Chroma.

    Written in the same transaction that deletes the chunk rows. Once the chunk row is
    gone, SQLite can no longer recompute the id, so a failed `delete_chunks` would
    otherwise strand the vector in Chroma forever and retrieval would keep citing text
    that exists in no document. This queue survives the failure and is drained by the
    next ingest.
    """

    __tablename__ = "pending_vector_deletions"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngestionRunRow(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repos_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embeddings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_json: Mapped[str] = mapped_column(Text, nullable=False)


class AskCacheRow(Base):
    __tablename__ = "ask_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    selected_chunk_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    model_provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    context_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


@dataclass(frozen=True)
class ScanDiff:
    """What a scan changed relative to what was already indexed."""

    changed_document_ids: set[str]
    removed_document_ids: set[str]

    @property
    def is_empty(self) -> bool:
        return not self.changed_document_ids and not self.removed_document_ids


def chunked(values: list[str], size: int = 400) -> list[list[str]]:
    """Split ids for `IN (...)` clauses; SQLite caps bound parameters per statement."""
    return [values[start : start + size] for start in range(0, len(values), size)]


class KnowledgeStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate_indexed_hash()

    def _migrate_indexed_hash(self) -> None:
        """Add `sdd_documents.indexed_hash` to databases created before it existed.

        `create_all` only creates missing tables, never missing columns. The backfill is
        deliberately conservative: a document that already has chunk rows is treated as
        indexed at its current hash (preserving the existing index), while a document
        with zero chunks stays NULL and is therefore re-chunked on the next ingest.
        That repairs, in place, exactly the documents an earlier `scan` had poisoned.
        """
        with self.engine.begin() as connection:
            columns = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(sdd_documents)")
            }
            if "indexed_hash" in columns:
                return
            connection.exec_driver_sql("ALTER TABLE sdd_documents ADD COLUMN indexed_hash VARCHAR")
            connection.exec_driver_sql(
                "UPDATE sdd_documents SET indexed_hash = content_hash "
                "WHERE id IN (SELECT DISTINCT document_id FROM semantic_chunks)"
            )

    def upsert_scan(
        self,
        repositories: list[RepositoryRecord],
        documents: list[SddDocumentRecord],
    ) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            session.query(EmbeddingRow).delete()
            session.query(SemanticChunkRow).delete()
            session.query(DocumentVersionRow).delete()
            session.query(SddDocumentRow).delete()
            session.query(RepositoryRow).delete()
            for repo in repositories:
                session.merge(repo_to_row(repo))
            for doc in documents:
                session.merge(doc_to_row(doc))
                version = DocumentVersionRecord(
                    id=f"version:{doc.id}:{doc.content_hash[:16]}",
                    document_id=doc.id,
                    content_hash=doc.content_hash,
                    commit_hash=doc.git.last_modified_commit or doc.git.commit_hash,
                    author=doc.git.author,
                    timestamp=doc.git.timestamp,
                    commit_message=doc.git.commit_message,
                )
                session.merge(version_to_row(version))

    def sync_scan(
        self,
        repositories: list[RepositoryRecord],
        documents: list[SddDocumentRecord],
        force: bool = False,
    ) -> ScanDiff:
        """Persist a scan *without* destroying the existing index.

        This is the incremental counterpart to `upsert_scan`. It writes only rows for
        documents whose content hash actually moved, prunes documents/repos that
        disappeared, and — critically — never touches `embeddings` or `semantic_chunks`
        for untouched documents. Chunk/embedding lifecycle for the affected documents
        is handled by `replace_document_chunks`, which the caller runs next.

        `force=True` marks every discovered document as changed (full rebuild) while
        keeping the same non-destructive code path.
        """
        self.init_schema()
        document_ids = {doc.id for doc in documents}
        repository_ids = {repo.id for repo in repositories}

        with self.Session.begin() as session:
            previous_indexed = {
                doc_id: indexed_hash
                for doc_id, indexed_hash in session.query(
                    SddDocumentRow.id, SddDocumentRow.indexed_hash
                ).all()
            }
            previous_repos = {row[0] for row in session.query(RepositoryRow.id).all()}

            removed_documents = set(previous_indexed) - document_ids
            # Gate on indexed_hash, never content_hash: only ingest advances the former,
            # so a discovery-only `scan` cannot mark a document as done.
            changed_documents = {
                doc.id
                for doc in documents
                if force or previous_indexed.get(doc.id) != doc.content_hash
            }

            for repo in repositories:
                session.merge(repo_to_row(repo))

            for doc in documents:
                if doc.id not in changed_documents:
                    continue
                row = doc_to_row(doc)
                # doc_to_row knows nothing about indexing state; carry the stored value
                # forward so merging discovery metadata never implies "indexed".
                row.indexed_hash = previous_indexed.get(doc.id)
                session.merge(row)
                session.merge(
                    version_to_row(
                        DocumentVersionRecord(
                            id=f"version:{doc.id}:{doc.content_hash[:16]}",
                            document_id=doc.id,
                            content_hash=doc.content_hash,
                            commit_hash=doc.git.last_modified_commit or doc.git.commit_hash,
                            author=doc.git.author,
                            timestamp=doc.git.timestamp,
                            commit_message=doc.git.commit_message,
                        )
                    )
                )

            for batch in chunked(sorted(removed_documents)):
                session.query(DocumentVersionRow).filter(
                    DocumentVersionRow.document_id.in_(batch)
                ).delete(synchronize_session=False)
                session.query(SddDocumentRow).filter(SddDocumentRow.id.in_(batch)).delete(
                    synchronize_session=False
                )

            for batch in chunked(sorted(previous_repos - repository_ids)):
                session.query(RepositoryRow).filter(RepositoryRow.id.in_(batch)).delete(
                    synchronize_session=False
                )

        return ScanDiff(
            changed_document_ids=changed_documents,
            removed_document_ids=removed_documents,
        )

    def replace_document_chunks(
        self,
        document_ids: set[str],
        chunks: list[SemanticChunkRecord],
    ) -> set[str]:
        """Re-chunk exactly `document_ids`; leave every other document's index intact.

        Deletes the chunks (and their embeddings) belonging to `document_ids`, then
        inserts `chunks`. Returns the chunk ids that are genuinely gone — i.e. deleted
        and *not* re-created — so the caller can prune them from the vector store.
        Chunk ids are content-addressed, so an edit that leaves a section untouched
        re-creates the same id and that section is never re-embedded.
        """
        self.init_schema()
        if not document_ids and not chunks:
            return set()

        surviving = {chunk.id for chunk in chunks}
        with self.Session.begin() as session:
            existing: set[str] = set()
            for batch in chunked(sorted(document_ids)):
                rows = (
                    session.query(SemanticChunkRow.id)
                    .filter(SemanticChunkRow.document_id.in_(batch))
                    .all()
                )
                existing.update(row[0] for row in rows)

            # Delete only the chunks this document no longer produces. Deleting all of
            # them and re-inserting would drop the embedding rows of sections that did
            # not change, so editing one heading of a long spec would re-embed the whole
            # file instead of the one section that actually moved.
            stale = existing - surviving
            for batch in chunked(sorted(stale)):
                session.query(EmbeddingRow).filter(EmbeddingRow.chunk_id.in_(batch)).delete(
                    synchronize_session=False
                )
                session.query(SemanticChunkRow).filter(SemanticChunkRow.id.in_(batch)).delete(
                    synchronize_session=False
                )

            # Queue the prune in the SAME transaction that drops the chunk rows. After
            # this commit SQLite has no memory of these ids, so anything that defers the
            # queueing until after a successful Chroma call can lose them permanently.
            now = utcnow()
            for chunk_id in stale:
                session.merge(PendingVectorDeletionRow(chunk_id=chunk_id, queued_at=now))

            for chunk in chunks:
                session.merge(chunk_to_row(chunk))

        return stale

    def mark_documents_indexed(self, hashes_by_document_id: dict[str, str]) -> None:
        """Record that these documents are chunked into the index at these hashes.

        Called by ingest only, and only once the chunk rows are committed. This is the
        write that closes the incremental gate opened by `sync_scan`.
        """
        if not hashes_by_document_id:
            return
        self.init_schema()
        with self.Session.begin() as session:
            for document_id, content_hash in hashes_by_document_id.items():
                session.query(SddDocumentRow).filter(SddDocumentRow.id == document_id).update(
                    {SddDocumentRow.indexed_hash: content_hash},
                    synchronize_session=False,
                )

    def pending_vector_deletions(self) -> list[str]:
        self.init_schema()
        with self.Session() as session:
            return [row[0] for row in session.query(PendingVectorDeletionRow.chunk_id).all()]

    def clear_pending_vector_deletions(self, chunk_ids: list[str]) -> None:
        """Drop queue entries only after the vector store confirms the delete."""
        if not chunk_ids:
            return
        self.init_schema()
        with self.Session.begin() as session:
            for batch in chunked(sorted(chunk_ids)):
                session.query(PendingVectorDeletionRow).filter(
                    PendingVectorDeletionRow.chunk_id.in_(batch)
                ).delete(synchronize_session=False)

    def chunks_missing_embeddings(self, model: str) -> list[SemanticChunkRecord]:
        """Every chunk in the corpus with no embedding row for `model`.

        The retry set must come from the store, not from the current run's chunk list.
        A document whose embedding batch failed is unchanged on the next scan, so it
        contributes no chunks and a run-scoped retry set can never reach it — its text
        would stay unreachable by retrieval forever. Asking the store instead makes
        every ingest self-healing.
        """
        self.init_schema()
        with self.Session() as session:
            embedded = {
                row[0]
                for row in session.query(EmbeddingRow.chunk_id)
                .filter(EmbeddingRow.model == model)
                .all()
            }
            rows = session.query(SemanticChunkRow).all()
        return [chunk_from_row(row) for row in rows if row.id not in embedded]

    def replace_chunks(self, chunks: list[SemanticChunkRecord]) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            for chunk in chunks:
                session.merge(chunk_to_row(chunk))

    def upsert_embedding(self, embedding: EmbeddingRecord) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            session.merge(embedding_to_row(embedding))

    def embedded_chunk_ids(self, model: str) -> set[str]:
        """Chunk ids already embedded with `model`.

        Chunk ids are content-addressed (see `stable_chunk_id`: the text's sha256 is
        part of the id), so a hit here means *that exact text* is already in the vector
        index. Editing a doc yields new chunk ids, which therefore miss and get
        re-embedded. This is what makes ingest both resumable after an interruption and
        incremental on re-run -- previously every run re-embedded all 7848 chunks from
        scratch (~90 min), so any interruption lost the entire pass.
        """
        self.init_schema()
        with self.Session() as session:
            rows = session.query(EmbeddingRow.chunk_id).filter(EmbeddingRow.model == model).all()
        return {row[0] for row in rows}

    def create_run(self, run: IngestionRunRecord) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            session.merge(run_to_row(run))

    def finish_run(self, run: IngestionRunRecord) -> None:
        self.create_run(run)

    def counts(self) -> dict[str, int]:
        self.init_schema()
        with self.Session() as session:
            return {
                "repositories": session.query(RepositoryRow).count(),
                "documents": session.query(SddDocumentRow).count(),
                "chunks": session.query(SemanticChunkRow).count(),
                "embeddings": session.query(EmbeddingRow).count(),
                "ingestion_runs": session.query(IngestionRunRow).count(),
                "ask_cache": session.query(AskCacheRow).count(),
            }

    def latest_run(self) -> IngestionRunRecord | None:
        self.init_schema()
        with self.Session() as session:
            row = session.scalars(
                select(IngestionRunRow).order_by(IngestionRunRow.started_at.desc()).limit(1)
            ).first()
            return run_from_row(row) if row else None

    def all_chunks(self) -> list[SemanticChunkRecord]:
        self.init_schema()
        with self.Session() as session:
            rows = session.scalars(select(SemanticChunkRow)).all()
            return [chunk_from_row(row) for row in rows]

    def all_repositories(self) -> list[RepositoryRecord]:
        self.init_schema()
        with self.Session() as session:
            rows = session.scalars(select(RepositoryRow).order_by(RepositoryRow.name)).all()
            return [repo_from_row(row) for row in rows]

    def all_documents(self) -> list[SddDocumentRecord]:
        self.init_schema()
        with self.Session() as session:
            rows = session.scalars(select(SddDocumentRow).order_by(SddDocumentRow.relative_path)).all()
            return [doc_from_row(row) for row in rows]

    def knowledge_fingerprint(self) -> str:
        self.init_schema()
        with self.Session() as session:
            latest = session.scalars(
                select(IngestionRunRow).order_by(IngestionRunRow.started_at.desc()).limit(1)
            ).first()
            payload = {
                "latest_run": latest.id if latest else None,
                "latest_finished_at": latest.finished_at.isoformat() if latest and latest.finished_at else None,
                "repositories": session.query(RepositoryRow).count(),
                "documents": session.query(SddDocumentRow).count(),
                "chunks": session.query(SemanticChunkRow).count(),
                "embeddings": session.query(EmbeddingRow).count(),
                "chunk_hashes": [
                    row[0]
                    for row in session.query(SemanticChunkRow.content_hash)
                    .order_by(SemanticChunkRow.id)
                    .all()
                ],
            }
        return hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()

    def get_ask_cache(
        self,
        normalized_question: str,
        knowledge_fingerprint: str,
        model_provider: str,
        model: str,
        context_chunks: int,
    ) -> AskCacheRecord | None:
        self.init_schema()
        with self.Session() as session:
            row = session.scalars(
                select(AskCacheRow)
                .where(AskCacheRow.normalized_question == normalized_question)
                .where(AskCacheRow.knowledge_fingerprint == knowledge_fingerprint)
                .where(AskCacheRow.model_provider == model_provider)
                .where(AskCacheRow.model == model)
                .where(AskCacheRow.context_chunks == context_chunks)
                .order_by(AskCacheRow.created_at.desc())
                .limit(1)
            ).first()
            return ask_cache_from_row(row) if row else None

    def put_ask_cache(self, record: AskCacheRecord) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            session.merge(ask_cache_to_row(record))

    def touch_ask_cache(self, cache_id: str) -> AskCacheRecord | None:
        self.init_schema()
        with self.Session.begin() as session:
            row = session.get(AskCacheRow, cache_id)
            if not row:
                return None
            row.last_hit_at = utcnow()
            row.hit_count += 1
            session.merge(row)
            return ask_cache_from_row(row)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str):
    return json.loads(value) if value else None


def repo_to_row(repo: RepositoryRecord) -> RepositoryRow:
    return RepositoryRow(
        id=repo.id,
        name=repo.name,
        path=repo.path,
        relative_path=repo.relative_path,
        branch=repo.branch,
        git_status=repo.git_status,
        sdd_roots_json=dumps(repo.sdd_roots),
    )


def doc_to_row(doc: SddDocumentRecord) -> SddDocumentRow:
    return SddDocumentRow(
        id=doc.id,
        repository_id=doc.repository_id,
        path=doc.path,
        relative_path=doc.relative_path,
        repo_relative_path=doc.repo_relative_path,
        title=doc.title,
        doc_type=doc.doc_type,
        content_hash=doc.content_hash,
        size_bytes=doc.size_bytes,
        tags_json=dumps(doc.tags),
        git_json=doc.git.model_dump_json(),
    )


def repo_from_row(row: RepositoryRow) -> RepositoryRecord:
    return RepositoryRecord(
        id=row.id,
        name=row.name,
        path=row.path,
        relative_path=row.relative_path,
        branch=row.branch,
        git_status=row.git_status,
        sdd_roots=loads(row.sdd_roots_json) or [],
    )


def doc_from_row(row: SddDocumentRow) -> SddDocumentRecord:
    return SddDocumentRecord(
        id=row.id,
        repository_id=row.repository_id,
        path=row.path,
        relative_path=row.relative_path,
        repo_relative_path=row.repo_relative_path,
        title=row.title,
        doc_type=row.doc_type,
        content_hash=row.content_hash,
        size_bytes=row.size_bytes,
        tags=loads(row.tags_json) or [],
        git=GitDocumentMetadata.model_validate_json(row.git_json),
    )


def version_to_row(version: DocumentVersionRecord) -> DocumentVersionRow:
    return DocumentVersionRow(
        id=version.id,
        document_id=version.document_id,
        content_hash=version.content_hash,
        commit_hash=version.commit_hash,
        author=version.author,
        timestamp=version.timestamp,
        commit_message=version.commit_message,
    )


def chunk_to_row(chunk: SemanticChunkRecord) -> SemanticChunkRow:
    return SemanticChunkRow(
        id=chunk.id,
        document_id=chunk.document_id,
        repository_id=chunk.repository_id,
        text=chunk.text,
        heading_path_json=dumps(chunk.heading_path),
        section=chunk.section,
        token_estimate=chunk.token_estimate,
        content_hash=chunk.content_hash,
        metadata_json=dumps(chunk.metadata),
    )


def embedding_to_row(embedding: EmbeddingRecord) -> EmbeddingRow:
    return EmbeddingRow(
        id=embedding.id,
        chunk_id=embedding.chunk_id,
        provider=embedding.provider,
        model=embedding.model,
        vector_store_id=embedding.vector_store_id,
        indexed_at=embedding.indexed_at,
    )


def run_to_row(run: IngestionRunRecord) -> IngestionRunRow:
    return IngestionRunRow(
        id=run.id,
        workspace=run.workspace,
        started_at=run.started_at,
        finished_at=run.finished_at,
        repos_count=run.repos_count,
        docs_count=run.docs_count,
        chunks_count=run.chunks_count,
        embeddings_count=run.embeddings_count,
        errors_json=dumps(run.errors),
    )


def ask_cache_to_row(record: AskCacheRecord) -> AskCacheRow:
    return AskCacheRow(
        id=record.id,
        question=record.question,
        normalized_question=record.normalized_question,
        answer=record.answer,
        intent=record.intent,
        sources_json=dumps(record.sources),
        selected_chunk_ids_json=dumps(record.selected_chunk_ids),
        knowledge_fingerprint=record.knowledge_fingerprint,
        model_provider=record.model_provider,
        model=record.model,
        context_chunks=record.context_chunks,
        created_at=record.created_at,
        last_hit_at=record.last_hit_at,
        hit_count=record.hit_count,
    )


def chunk_from_row(row: SemanticChunkRow) -> SemanticChunkRecord:
    return SemanticChunkRecord(
        id=row.id,
        document_id=row.document_id,
        repository_id=row.repository_id,
        text=row.text,
        heading_path=loads(row.heading_path_json) or [],
        section=row.section,
        token_estimate=row.token_estimate,
        content_hash=row.content_hash,
        metadata=loads(row.metadata_json) or {},
    )


def run_from_row(row: IngestionRunRow) -> IngestionRunRecord:
    return IngestionRunRecord(
        id=row.id,
        workspace=row.workspace,
        started_at=row.started_at,
        finished_at=row.finished_at,
        repos_count=row.repos_count,
        docs_count=row.docs_count,
        chunks_count=row.chunks_count,
        embeddings_count=row.embeddings_count,
        errors=loads(row.errors_json) or [],
    )


def ask_cache_from_row(row: AskCacheRow) -> AskCacheRecord:
    return AskCacheRecord(
        id=row.id,
        question=row.question,
        normalized_question=row.normalized_question,
        answer=row.answer,
        intent=row.intent,
        sources=loads(row.sources_json) or [],
        selected_chunk_ids=loads(row.selected_chunk_ids_json) or [],
        knowledge_fingerprint=row.knowledge_fingerprint,
        model_provider=row.model_provider,
        model=row.model,
        context_chunks=row.context_chunks,
        created_at=row.created_at,
        last_hit_at=row.last_hit_at,
        hit_count=row.hit_count,
    )
