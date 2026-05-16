from __future__ import annotations

import hashlib
import re
from pathlib import Path

from repo_intel.core.models import DocumentInfo, Evidence, RepoInfo
from repo_intel.scanner.filesystem import iter_files


DOC_EXTENSIONS = {".md", ".mdx", ".rst"}
IMPORTANT_DOC_NAMES = {
    "agents.md",
    "agent_start_here.md",
    "ai_context.md",
    "ai_index.md",
    "architecture.md",
    "claude.md",
    "cursor_handoff.md",
    "design.md",
    "product.md",
    "readme.md",
}


def discover_docs(root: Path, repos: list[RepoInfo]) -> list[DocumentInfo]:
    root = root.resolve()
    repo_paths = [(repo, Path(repo.path).resolve()) for repo in repos]
    docs: list[DocumentInfo] = []

    for path in iter_files(root):
        if not is_document(path):
            continue
        repo = find_owner_repo(path, repo_paths)
        relative = path.relative_to(root).as_posix()
        doc_type, confidence, tags, evidence = classify_doc(path)
        docs.append(
            DocumentInfo(
                id=doc_id_for(relative),
                repo_id=repo.id if repo else None,
                path=str(path),
                relative_path=relative,
                title=extract_title(path),
                doc_type=doc_type,
                confidence=confidence,
                tags=tags,
                evidence=evidence,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )

    return sorted(docs, key=lambda item: (item.repo_id or "", item.doc_type, item.relative_path))


def is_document(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in DOC_EXTENSIONS:
        return True
    return name in IMPORTANT_DOC_NAMES


def find_owner_repo(path: Path, repo_paths: list[tuple[RepoInfo, Path]]) -> RepoInfo | None:
    owners = []
    for repo, repo_path in repo_paths:
        try:
            path.relative_to(repo_path)
            owners.append((len(repo_path.parts), repo))
        except ValueError:
            continue
    if not owners:
        return None
    return sorted(owners, reverse=True, key=lambda item: item[0])[0][1]


def doc_id_for(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:10]
    return f"doc:{relative_path}:{digest}"


def classify_doc(path: Path) -> tuple[str, float, list[str], list[Evidence]]:
    name = path.name.lower()
    relative = path.as_posix().lower()
    text_head = read_head(path).lower()
    joined = f"{relative}\n{text_head}"
    evidence: list[Evidence] = []

    filename_rules = {
        "agents.md": ("agent-guide", 0.99, ["ai", "agent"]),
        "agent_start_here.md": ("agent-guide", 0.99, ["ai", "agent"]),
        "claude.md": ("agent-guide", 0.99, ["ai", "agent"]),
        "cursor_handoff.md": ("handoff", 0.99, ["ai", "handoff"]),
        "ai_context.md": ("ai-index", 0.99, ["ai", "index"]),
        "ai_index.md": ("ai-index", 0.99, ["ai", "index"]),
        "readme.md": ("readme", 0.9, ["overview"]),
        "product.md": ("product", 0.95, ["product"]),
        "design.md": ("design", 0.95, ["design"]),
    }
    if name in filename_rules:
        doc_type, confidence, tags = filename_rules[name]
        evidence.append(Evidence(source=str(path), reason=f"matched filename rule: {name}"))
        return doc_type, confidence, tags, evidence

    path_rules = [
        ("roadmap", 0.93, ["/10-roadmap/", "/11-roadmap/", "/roadmap/"], ["planning"]),
        ("adr", 0.93, ["/03-adrs/", "/adrs/", "adr-"], ["architecture", "decision"]),
        ("integration", 0.9, ["/05-integration/", "/integration/"], ["integration"]),
        ("api-contract", 0.9, ["/04-api/", "api-contract", "api_contract", "api-surface"], ["api"]),
        ("sdd-spec", 0.88, ["/04-features/", "/features/", "spec"], ["sdd", "spec"]),
        ("architecture", 0.88, ["/01-architecture/", "/02-architecture/", "/architecture/"], ["architecture"]),
        ("overview", 0.84, ["/00-overview/"], ["overview"]),
        ("qa", 0.88, ["/test_cases/", "/app-map/", "/roles/"], ["qa"]),
        ("deploy", 0.86, ["/deploy/"], ["infra"]),
    ]
    for doc_type, confidence, needles, tags in path_rules:
        if any(needle in relative for needle in needles):
            evidence.append(Evidence(source=str(path), reason=f"matched path rule: {doc_type}"))
            return doc_type, confidence, sorted(set(tags)), evidence

    rules = [
        ("handoff", 0.96, ["handoff"], ["ai", "handoff"]),
        ("ai-index", 0.96, ["ai_index", "ai context"], ["ai", "index"]),
        ("agent-guide", 0.94, ["agent start", "claude"], ["ai", "agent"]),
        ("api-contract", 0.9, ["api_contract", "api surface", "api_surfaces", "contract"], ["api"]),
        ("architecture", 0.9, ["architecture", "arquitectura"], ["architecture"]),
        ("sdd-spec", 0.88, ["spec", "requirements", "reqs"], ["sdd", "spec"]),
        ("roadmap", 0.88, ["roadmap", "plan", "tasks"], ["planning"]),
        ("product", 0.86, ["product.md", "product"], ["product"]),
        ("design", 0.86, ["design", "ux"], ["design"]),
        ("qa", 0.86, ["test case", "qa", "app-map", "role"], ["qa"]),
        ("deploy", 0.84, ["deploy", "docker", "github_actions", "first_deploy"], ["infra"]),
        ("readme", 0.82, ["readme.md"], ["overview"]),
        ("integration", 0.82, ["integration", "sync", "runtime", "offline"], ["integration"]),
    ]

    for doc_type, confidence, needles, tags in rules:
        if any(needle in joined for needle in needles):
            evidence.append(Evidence(source=str(path), reason=f"matched {doc_type} rule"))
            return doc_type, confidence, sorted(set(tags)), evidence

    if name.endswith(".md"):
        evidence.append(Evidence(source=str(path), reason="markdown document found"))
        return "markdown", 0.6, [], evidence

    evidence.append(Evidence(source=str(path), reason="text document found"))
    return "document", 0.5, [], evidence


def extract_title(path: Path) -> str:
    head = read_head(path, chars=2048)
    for line in head.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return re.sub(r"^#+\s*", "", stripped).strip() or path.stem
    return path.stem.replace("-", " ").replace("_", " ").title()


def read_head(path: Path, chars: int = 4096) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:chars]
    except OSError:
        return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()
