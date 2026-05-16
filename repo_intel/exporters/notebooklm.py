from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from repo_intel.core.models import DocumentInfo, Relationship, RepoInfo


def export_notebooklm(
    root: Path,
    repos: list[RepoInfo],
    docs: list[DocumentInfo],
    relationships: list[Relationship],
) -> Path:
    export_dir = root / ".repo-intel" / "exports" / "notebooklm"
    export_dir.mkdir(parents=True, exist_ok=True)

    write(export_dir / "00-index.md", render_index(repos, docs))
    write(export_dir / "01-project-overview.md", render_project_overview(root, repos, docs))
    write(export_dir / "02-repositories.md", render_repositories(repos, docs))
    write(export_dir / "03-documents.md", render_documents(docs))
    write(export_dir / "04-architecture-map.md", render_architecture_map(repos, relationships))
    write(export_dir / "05-ai-context-pack.md", render_ai_context_pack(repos, docs))
    return export_dir


def write(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_index(repos: list[RepoInfo], docs: list[DocumentInfo]) -> str:
    doc_types = Counter(doc.doc_type for doc in docs)
    stacks = Counter(stack.name for repo in repos for stack in repo.stacks)
    lines = [
        "# Repository Intelligence Index",
        "",
        f"- Repositories detected: {len(repos)}",
        f"- Documents detected: {len(docs)}",
        f"- Documentation types: {format_counter(doc_types)}",
        f"- Stacks detected: {format_counter(stacks)}",
        "",
        "## Files",
        "",
        "- `01-project-overview.md`",
        "- `02-repositories.md`",
        "- `03-documents.md`",
        "- `04-architecture-map.md`",
        "- `05-ai-context-pack.md`",
    ]
    return "\n".join(lines)


def render_project_overview(root: Path, repos: list[RepoInfo], docs: list[DocumentInfo]) -> str:
    domains = Counter(domain for repo in repos for domain in repo.domains)
    lines = [
        "# Project Overview",
        "",
        f"Root: `{root}`",
        "",
        "## Repository Groups",
        "",
    ]
    for repo in repos:
        stack_names = ", ".join(stack.name for stack in repo.stacks) or "unknown"
        domain_names = ", ".join(repo.domains) or "unclassified"
        repo_docs = [doc for doc in docs if doc.repo_id == repo.id]
        lines.append(f"- **{repo.name}**: {stack_names}; domains: {domain_names}; docs: {len(repo_docs)}")

    lines.extend(["", "## Domain Signals", ""])
    if domains:
        for domain, count in domains.most_common():
            lines.append(f"- {domain}: {count} repo(s)")
    else:
        lines.append("- No domain signals detected.")
    return "\n".join(lines)


def render_repositories(repos: list[RepoInfo], docs: list[DocumentInfo]) -> str:
    docs_by_repo = defaultdict(list)
    for doc in docs:
        docs_by_repo[doc.repo_id].append(doc)

    lines = ["# Repositories", ""]
    for repo in repos:
        lines.extend(
            [
                f"## {repo.name}",
                "",
                f"- Path: `{repo.relative_path or '.'}`",
                f"- Git repo: `{repo.is_git_repo}`",
                f"- Monorepo/workspace: `{repo.workspace_type or 'no'}`",
                f"- Package name: `{repo.package_name or 'n/a'}`",
                f"- Domains: {', '.join(repo.domains) or 'unclassified'}",
                f"- Stacks: {', '.join(stack.name for stack in repo.stacks) or 'unknown'}",
                "",
                "### Key Documents",
                "",
            ]
        )
        key_docs = sorted(docs_by_repo.get(repo.id, []), key=lambda doc: (-doc.confidence, doc.relative_path))[:15]
        if key_docs:
            for doc in key_docs:
                lines.append(f"- `{doc.relative_path}` ({doc.doc_type}, confidence {doc.confidence:.2f})")
        else:
            lines.append("- No documents detected.")
        lines.append("")
    return "\n".join(lines)


def render_documents(docs: list[DocumentInfo]) -> str:
    lines = ["# Documents", ""]
    grouped: dict[str, list[DocumentInfo]] = defaultdict(list)
    for doc in docs:
        grouped[doc.doc_type].append(doc)
    for doc_type in sorted(grouped):
        lines.extend([f"## {doc_type}", ""])
        for doc in sorted(grouped[doc_type], key=lambda item: item.relative_path):
            tags = f" tags: {', '.join(doc.tags)}" if doc.tags else ""
            lines.append(f"- `{doc.relative_path}` - {doc.title} ({doc.confidence:.2f}){tags}")
        lines.append("")
    return "\n".join(lines)


def render_architecture_map(repos: list[RepoInfo], relationships: list[Relationship]) -> str:
    repo_names = {repo.id: repo.name for repo in repos}
    lines = ["# Architecture Map", "", "## Repository Relationships", ""]
    repo_relationships = [
        rel
        for rel in relationships
        if rel.source in repo_names and rel.target in repo_names and rel.kind != "has_document"
    ]
    if not repo_relationships:
        lines.append("- No repository relationships inferred.")
        return "\n".join(lines)

    for rel in sorted(repo_relationships, key=lambda item: (-item.confidence, item.kind)):
        lines.append(
            f"- **{repo_names[rel.source]}** -> **{repo_names[rel.target]}**: "
            f"{rel.kind} ({rel.confidence:.2f})"
        )
    return "\n".join(lines)


def render_ai_context_pack(repos: list[RepoInfo], docs: list[DocumentInfo]) -> str:
    priority_types = {
        "ai-index",
        "agent-guide",
        "handoff",
        "architecture",
        "api-contract",
        "sdd-spec",
        "product",
        "roadmap",
    }
    lines = [
        "# AI Context Pack",
        "",
        "This file lists the highest-priority context sources for AI-assisted development.",
        "",
    ]
    for repo in repos:
        repo_docs = [
            doc
            for doc in docs
            if doc.repo_id == repo.id and (doc.doc_type in priority_types or doc.confidence >= 0.9)
        ]
        if not repo_docs:
            continue
        lines.extend([f"## {repo.name}", ""])
        for doc in sorted(repo_docs, key=lambda item: (-item.confidence, item.relative_path))[:20]:
            lines.append(f"- `{doc.relative_path}` ({doc.doc_type})")
        lines.append("")
    return "\n".join(lines)


def format_counter(counter: Counter) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in counter.most_common())

