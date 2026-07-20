from __future__ import annotations

import hashlib
import re
from pathlib import Path

from repo_intel.core.config import AppConfig
from repo_intel.domain.models import RepositoryRecord, SddDocumentRecord, SemanticChunkRecord
from repo_intel.sdd.markdown import MarkdownSection, parse_markdown_sections


# IMPORTANT — changing anything in this module does NOT invalidate the index on its own.
# Incremental ingest decides what to rebuild from each document's sha256, so if the source
# files have not changed, a new chunking strategy is silently never applied: `ingest` will
# report "0 changed, 0 rebuilt" and retrieval keeps using the old chunk boundaries. After
# touching the constants or the splitter, you MUST run `repo-intel ingest <target> --full`.
# (A chunker fingerprint stored alongside the index would make this automatic — see the
# known-issues section of the README.)
#
# Ceiling for a single embedded chunk. Was 4200, which is far too permissive: one vector
# has to represent everything in the chunk, so a heterogeneous section averages out into a
# vector that matches nothing specific. Measured on the real corpus: the AGENTS.md section
# "Convenciones de código" (1749 chars: async repos + exception prefixes + Pydantic
# validators + Alembic revision-id rules) scored 0.684 against a query about Alembic
# revision ids, while the 702-char fragment carrying only that rule scored 0.783 — enough
# to move it from "absent from the results" to top-hit. 1200 sits just above the p95 of the
# existing corpus (1134), so well-scoped sections are untouched and only the grab-bag ones
# get split.
MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 200
# Floor for the whole-document fallback below. Lower than MIN_CHUNK_CHARS on purpose:
# rejecting a section of a rich document is cheap, but rejecting a document outright
# means it is in no index at all, so the bar to keep it should be lower, not the same.
MIN_WHOLE_DOC_CHARS = 80


def chunk_document(
    config: AppConfig,
    repository: RepositoryRecord,
    document: SddDocumentRecord,
) -> list[SemanticChunkRecord]:
    content = Path(document.path).read_text(encoding="utf-8", errors="ignore")
    sections = parse_markdown_sections(content)

    def build(text: str, heading_path: list[str], title: str, part_index: int):
        content_hash = sha256_text(text)
        return SemanticChunkRecord(
            id=stable_chunk_id(document.id, heading_path, part_index, content_hash),
            document_id=document.id,
            repository_id=repository.id,
            text=text,
            heading_path=heading_path,
            section=title,
            token_estimate=estimate_tokens(text),
            content_hash=content_hash,
            metadata={
                "project": config.project_name,
                "repo": repository.name,
                "repo_id": repository.id,
                "doc_type": document.doc_type,
                "path": document.repo_relative_path,
                "workspace_path": document.relative_path,
                "section": title,
                "heading_path": " > ".join(heading_path),
                "tags": ",".join(document.tags),
                "branch": document.git.branch or "",
                "commit_hash": document.git.commit_hash or "",
                "last_modified_commit": document.git.last_modified_commit or "",
                "author": document.git.author or "",
                "timestamp": document.git.timestamp or "",
            },
        )

    chunks: list[SemanticChunkRecord] = []
    for section in sections:
        for part_index, text in enumerate(split_large_section(section)):
            if len(text.strip()) < MIN_CHUNK_CHARS and len(sections) > 1:
                continue
            chunks.append(build(text, section.heading_path, section.title, part_index))

    # The per-section floor drops boilerplate ("## Status: draft"), which is what it is
    # for -- but when EVERY section is under the floor it drops the whole document, and
    # the document then sits in the corpus with zero chunks: counted in `status`,
    # unreachable by retrieval, and not reported anywhere. Terse openspec specs land here
    # exactly because they are well written: a handful of short "The system SHALL ..."
    # requirements with no filler. Eight live specs were invisible this way. Index the
    # whole document instead of losing it.
    if not chunks and len(content.strip()) >= MIN_WHOLE_DOC_CHARS:
        chunks.append(build(content.strip(), [document.title], document.title, 0))

    return chunks


_TOP_LEVEL_BULLET = re.compile(r"^(?:[-*+] |\d+[.)] )")


def _split_blocks(text: str) -> list[str]:
    """Split a section into packable blocks.

    Blank lines are the obvious boundary, but the guardrail docs in this corpus are written
    as one long bullet list under a single heading — each bullet a different rule, no blank
    lines between them. Splitting on "\\n\\n" alone leaves that whole list as one block, so it
    gets embedded as one vector and no individual rule is retrievable. A top-level list
    marker at column 0 is therefore also a boundary; indented continuation lines stay with
    their bullet, so a multi-line rule is never cut in half.
    """
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            joined = "\n".join(current).strip()
            if joined:
                blocks.append(joined)
            current.clear()

    for line in text.split("\n"):
        if not line.strip():
            flush()
            continue
        if current and _TOP_LEVEL_BULLET.match(line):
            flush()
        current.append(line)
    flush()
    return blocks


def split_large_section(section: MarkdownSection) -> list[str]:
    text = section.text.strip()
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    paragraphs = _split_blocks(text)
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

