from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from repo_intel.domain.models import (
    DocumentVersionRecord,
    EmbeddingRecord,
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


class KnowledgeStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)

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

    def replace_chunks(self, chunks: list[SemanticChunkRecord]) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            for chunk in chunks:
                session.merge(chunk_to_row(chunk))

    def upsert_embedding(self, embedding: EmbeddingRecord) -> None:
        self.init_schema()
        with self.Session.begin() as session:
            session.merge(embedding_to_row(embedding))

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
