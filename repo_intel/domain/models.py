from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GitDocumentMetadata(BaseModel):
    branch: str | None = None
    commit_hash: str | None = None
    last_modified_commit: str | None = None
    author: str | None = None
    timestamp: str | None = None
    commit_message: str | None = None


class RepositoryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    path: str
    relative_path: str
    branch: str | None = None
    git_status: str = "unknown"
    sdd_roots: list[str] = Field(default_factory=list)


class SddDocumentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    path: str
    relative_path: str
    repo_relative_path: str
    title: str
    doc_type: str
    content_hash: str
    size_bytes: int
    tags: list[str] = Field(default_factory=list)
    git: GitDocumentMetadata = Field(default_factory=GitDocumentMetadata)


class DocumentVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    content_hash: str
    commit_hash: str | None = None
    author: str | None = None
    timestamp: str | None = None
    commit_message: str | None = None


class SemanticChunkRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    repository_id: str
    text: str
    heading_path: list[str] = Field(default_factory=list)
    section: str | None = None
    token_estimate: int = 0
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_id: str
    provider: str
    model: str
    vector_store_id: str
    indexed_at: datetime


class IngestionRunRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace: str
    started_at: datetime
    finished_at: datetime | None = None
    repos_count: int = 0
    docs_count: int = 0
    chunks_count: int = 0
    embeddings_count: int = 0
    errors: list[str] = Field(default_factory=list)

