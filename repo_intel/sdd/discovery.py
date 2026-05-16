from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Iterable

from repo_intel.core.config import AppConfig
from repo_intel.domain.models import RepositoryRecord, SddDocumentRecord
from repo_intel.sdd.git_metadata import GitMetadataProvider


REPO_MARKERS = {
    ".git",
    "AI_INDEX.md",
    "AGENT_START_HERE.md",
    "README.md",
    "docs",
}

PRUNE_DIRS = {
    ".agents",
    ".claude",
    ".git",
    ".repo-intel",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "repo-intelligence-cli",
    "workspace",
}


def discover_repositories(workspace: Path, config: AppConfig) -> list[RepositoryRecord]:
    workspace = workspace.resolve()
    repositories: list[RepositoryRecord] = []

    for candidate in iter_candidate_dirs(workspace, max_depth=3):
        if not is_repository_candidate(candidate, workspace):
            continue
        rel = candidate.relative_to(workspace).as_posix()
        if rel == ".":
            rel = ""
        git_provider = GitMetadataProvider(candidate)
        sdd_roots = detect_sdd_roots(candidate)
        repositories.append(
            RepositoryRecord(
                id=stable_id("repo", rel or workspace.name),
                name=candidate.name,
                path=str(candidate),
                relative_path=rel,
                branch=git_provider.branch(),
                git_status=git_provider.status(),
                sdd_roots=sdd_roots,
            )
        )

    return sorted(dedupe_repositories(repositories), key=lambda repo: repo.relative_path)


def discover_sdd_documents(
    workspace: Path,
    config: AppConfig,
    repositories: list[RepositoryRecord],
) -> list[SddDocumentRecord]:
    workspace = workspace.resolve()
    documents: list[SddDocumentRecord] = []
    for repo in repositories:
        repo_path = Path(repo.path)
        git_provider = GitMetadataProvider(repo_path)
        for path in iter_sdd_files(repo_path, config):
            relative = path.relative_to(workspace).as_posix()
            repo_relative = path.relative_to(repo_path).as_posix()
            content = read_text(path)
            content_hash = sha256_text(content)
            git_meta = git_provider.document_metadata(path)
            doc_type, tags = classify_doc(repo_relative)
            documents.append(
                SddDocumentRecord(
                    id=stable_id("doc", f"{repo.id}:{repo_relative}"),
                    repository_id=repo.id,
                    path=str(path),
                    relative_path=relative,
                    repo_relative_path=repo_relative,
                    title=extract_title(content, path),
                    doc_type=doc_type,
                    content_hash=content_hash,
                    size_bytes=path.stat().st_size,
                    tags=tags,
                    git=git_meta,
                )
            )
    return sorted(dedupe_documents(documents), key=lambda doc: doc.relative_path)


def iter_candidate_dirs(root: Path, max_depth: int) -> Iterable[Path]:
    root = root.resolve()

    def walk(path: Path, depth: int) -> Iterable[Path]:
        if depth > max_depth:
            return
        yield path
        try:
            children = sorted(path.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in PRUNE_DIRS:
                continue
            yield from walk(child, depth + 1)

    yield from walk(root, 0)


def is_repository_candidate(path: Path, workspace: Path) -> bool:
    names = {item.name for item in safe_iterdir(path)}
    if ".git" in names:
        return True
    # PROXIMA has at least one project folder without .git. Treat only workspace children
    # as synthetic repositories when they expose SDD entrypoints.
    try:
        depth = len(path.relative_to(workspace).parts)
    except ValueError:
        depth = 99
    return depth == 1 and bool(names & REPO_MARKERS)


def detect_sdd_roots(repo_path: Path) -> list[str]:
    roots = []
    for name in ("docs", "docs_facturacion"):
        if (repo_path / name).is_dir():
            roots.append(name)
    for name in ("AI_INDEX.md", "AGENT_START_HERE.md", "CURSOR_HANDOFF.md"):
        if (repo_path / name).is_file():
            roots.append(name)
    return roots


def iter_sdd_files(repo_path: Path, config: AppConfig) -> Iterable[Path]:
    seen: set[Path] = set()
    for pattern in config.docs.include:
        for path in repo_path.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            rel = path.relative_to(repo_path).as_posix()
            if is_excluded(rel, config.docs.exclude):
                continue
            seen.add(resolved)
            yield path


def is_included(relative_path: str, patterns: list[str]) -> bool:
    return any(match_path(relative_path, pattern) for pattern in patterns)


def is_excluded(relative_path: str, patterns: list[str]) -> bool:
    return any(match_path(relative_path, pattern) for pattern in patterns)


def match_path(relative_path: str, pattern: str) -> bool:
    path = Path(relative_path)
    if path.match(pattern):
        return True
    return fnmatch.fnmatch(relative_path, pattern)


def classify_doc(repo_relative_path: str) -> tuple[str, list[str]]:
    rel = repo_relative_path.lower()
    name = Path(rel).name
    if name in {"ai_index.md"}:
        return "ai-index", ["ai", "index", "sdd"]
    if name in {"agent_start_here.md", "agents.md", "claude.md"}:
        return "agent-guide", ["ai", "agent", "sdd"]
    if "handoff" in rel:
        return "handoff", ["ai", "handoff", "sdd"]
    if "adr" in rel or "/adrs/" in rel:
        return "adr", ["architecture", "decision", "sdd"]
    if "architecture" in rel or "arquitectura" in rel:
        return "architecture", ["architecture", "sdd"]
    if "contract" in rel or "api" in rel:
        return "api-contract", ["api", "sdd"]
    if "spec" in rel or "requirements" in rel or "reqs" in rel:
        return "sdd-spec", ["spec", "sdd"]
    if "roadmap" in rel or "plan" in rel or "tasks" in rel:
        return "roadmap", ["planning", "sdd"]
    if "test_cases" in rel or "/roles/" in rel or "qa" in rel:
        return "qa", ["qa", "sdd"]
    if name == "readme.md":
        return "readme", ["overview", "sdd"]
    if "design" in rel or "ux" in rel:
        return "design", ["design", "sdd"]
    if "product" in rel:
        return "product", ["product", "sdd"]
    return "sdd-doc", ["sdd"]


def extract_title(content: str, path: Path) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem.replace("-", " ").replace("_", " ").title()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def dedupe_repositories(repos: list[RepositoryRecord]) -> list[RepositoryRecord]:
    deduped: dict[str, RepositoryRecord] = {}
    for repo in repos:
        deduped[repo.path] = repo
    return list(deduped.values())


def dedupe_documents(docs: list[SddDocumentRecord]) -> list[SddDocumentRecord]:
    deduped: dict[str, SddDocumentRecord] = {}
    for doc in docs:
        deduped[doc.path] = doc
    return list(deduped.values())
