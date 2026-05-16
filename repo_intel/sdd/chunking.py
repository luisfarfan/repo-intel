from __future__ import annotations

import hashlib
from pathlib import Path

from repo_intel.core.config import AppConfig
from repo_intel.domain.models import RepositoryRecord, SddDocumentRecord, SemanticChunkRecord
from repo_intel.sdd.markdown import MarkdownSection, parse_markdown_sections


MAX_CHUNK_CHARS = 4200
MIN_CHUNK_CHARS = 200


def chunk_document(
    config: AppConfig,
    repository: RepositoryRecord,
    document: SddDocumentRecord,
) -> list[SemanticChunkRecord]:
    content = Path(document.path).read_text(encoding="utf-8", errors="ignore")
    sections = parse_markdown_sections(content)
    chunks: list[SemanticChunkRecord] = []
    for section_index, section in enumerate(sections):
        for part_index, text in enumerate(split_large_section(section)):
            if len(text.strip()) < MIN_CHUNK_CHARS and len(sections) > 1:
                continue
            content_hash = sha256_text(text)
            chunk_id = stable_chunk_id(document.id, section.heading_path, part_index, content_hash)
            metadata = {
                "project": config.project_name,
                "repo": repository.name,
                "repo_id": repository.id,
                "doc_type": document.doc_type,
                "path": document.repo_relative_path,
                "workspace_path": document.relative_path,
                "section": section.title,
                "heading_path": " > ".join(section.heading_path),
                "tags": ",".join(document.tags),
                "branch": document.git.branch or "",
                "commit_hash": document.git.commit_hash or "",
                "last_modified_commit": document.git.last_modified_commit or "",
                "author": document.git.author or "",
                "timestamp": document.git.timestamp or "",
            }
            chunks.append(
                SemanticChunkRecord(
                    id=chunk_id,
                    document_id=document.id,
                    repository_id=repository.id,
                    text=text,
                    heading_path=section.heading_path,
                    section=section.title,
                    token_estimate=estimate_tokens(text),
                    content_hash=content_hash,
                    metadata=metadata,
                )
            )
    return chunks


def split_large_section(section: MarkdownSection) -> list[str]:
    text = section.text.strip()
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    paragraphs = text.split("\n\n")
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if current and current_len + paragraph_len + 2 > MAX_CHUNK_CHARS:
            parts.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += paragraph_len + 2
    if current:
        parts.append("\n\n".join(current).strip())
    return parts


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_chunk_id(
    document_id: str,
    heading_path: list[str],
    part_index: int,
    content_hash: str,
) -> str:
    value = f"{document_id}:{' > '.join(heading_path)}:{part_index}:{content_hash}"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]
    return f"chunk:{digest}"

