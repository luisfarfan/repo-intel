from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from repo_intel.obsidian.models import ObsidianSourceState


def render_all(state: ObsidianSourceState, generated_root: str) -> dict[Path, str]:
    files: dict[Path, str] = {}
    root = Path(generated_root)
    project_dir = root / "01 Projects" / state.project_name

    files[Path("Home.md")] = render_home(state, generated_root)
    files[root / "00 Dashboards" / "Engineering Dashboard.md"] = render_engineering_dashboard(state)
    files[root / "00 Dashboards" / "Recent Activity.md"] = render_recent_activity(state)
    files[root / "00 Dashboards" / "Semantic Hotspots.md"] = render_semantic_hotspots(state)
    files[root / "00 Dashboards" / "Architecture Evolution.md"] = render_architecture_evolution(state)
    files[root / "00 Dashboards" / "AI Workflow Memory.md"] = render_ai_workflow_memory(state)

    files[project_dir / "Project Brief.md"] = render_project_brief(state)
    files[project_dir / "Project Index.md"] = render_project_index(state)
    files[project_dir / "Repository Map.md"] = render_repository_map(state)

    for repo in state.repositories:
        files[root / "02 Repositories" / f"{safe_filename(repo['name'])}.md"] = render_repository_page(
            state, repo
        )

    files[root / "03 Architecture" / "Architecture Map.md"] = render_architecture_map(state)
    files[root / "03 Architecture" / "Cross Repo Relationships.md"] = render_cross_repo_relationships(
        state
    )
    files[root / "03 Architecture" / "Infrastructure Map.md"] = render_infrastructure_map(state)

    files[root / "04 Decisions" / "ADR Index.md"] = render_adr_index(state)
    files[root / "04 Decisions" / "Decision Timeline.md"] = render_decision_timeline(state)

    for topic in state.topics:
        files[root / "05 Topics" / f"{safe_filename(topic['name'])}.md"] = render_topic_page(
            state, topic
        )

    files[root / "06 AI Workflows" / "Prompt Memory.md"] = render_prompt_memory(state)
    files[root / "06 AI Workflows" / "Ask History.md"] = render_ask_history(state)
    files[root / "06 AI Workflows" / "Active Work.md"] = render_active_work(state)

    files[root / "99 System" / "Sync Status.md"] = render_sync_status(state)
    files[root / "99 System" / "Source Manifest.md"] = render_source_manifest(state)
    files[root / "99 System" / "Generation Log.md"] = render_generation_log(state)
    return files


def frontmatter(state: ObsidianSourceState, note_type: str, **extra: Any) -> str:
    values = {
        "generated_by": "repo-intel",
        "source": "sqlite",
        "project": state.project_name,
        "type": note_type,
        "last_synced": state.synced_at.isoformat(),
        **extra,
    }
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            escaped = str(value).replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def render_home(state: ObsidianSourceState, generated_root: str) -> str:
    return frontmatter(state, "home") + "\n".join(
        [
            f"# {state.project_name} Engineering Brain",
            "",
            "## Start Here",
            f"- [[{generated_root}/00 Dashboards/Engineering Dashboard|Engineering Dashboard]]",
            f"- [[{generated_root}/01 Projects/{state.project_name}/Project Brief|Project Brief]]",
            f"- [[{generated_root}/01 Projects/{state.project_name}/Repository Map|Repository Map]]",
            f"- [[{generated_root}/03 Architecture/Architecture Map|Architecture Map]]",
            f"- [[{generated_root}/04 Decisions/ADR Index|ADR Index]]",
            f"- [[{generated_root}/05 Topics/Checkout|Checkout]]",
            "",
            "This vault is generated from repo-intel machine memory. Edit source SDD docs, then run `repo-intel ingest` and `repo-intel obsidian sync`.",
        ]
    )


def render_engineering_dashboard(state: ObsidianSourceState) -> str:
    doc_types = Counter(doc["doc_type"] for doc in state.documents)
    latest = state.runs[0] if state.runs else {}
    lines = [
        frontmatter(state, "dashboard") + "# Engineering Dashboard",
        "",
        "## Knowledge Base",
        f"- Repositories: **{len(state.repositories)}**",
        f"- SDD documents: **{len(state.documents)}**",
        f"- Semantic chunks: **{len(state.chunks)}**",
        f"- Latest ingestion: `{latest.get('finished_at', 'n/a')}`",
        "",
        "## Primary Navigation",
        "- [[Project Brief]]",
        "- [[Repository Map]]",
        "- [[Architecture Map]]",
        "- [[ADR Index]]",
        "- [[Semantic Hotspots]]",
        "",
        "## Document Types",
    ]
    lines.extend(f"- {name}: {count}" for name, count in doc_types.most_common(12))
    return "\n".join(lines)


def render_recent_activity(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "dashboard") + "# Recent Activity", ""]
    for run in state.runs[:10]:
        lines.append(
            f"- `{run.get('finished_at')}`: {run.get('repos_count')} repos, {run.get('docs_count')} docs, {run.get('chunks_count')} chunks, {run.get('embeddings_count')} embeddings"
        )
    return "\n".join(lines)


def render_semantic_hotspots(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "dashboard") + "# Semantic Hotspots", ""]
    for topic in state.topics[:20]:
        lines.append(f"- [[{topic['name']}]]: {topic['count']} chunks across {len(topic['repos'])} repos")
    return "\n".join(lines)


def render_architecture_evolution(state: ObsidianSourceState) -> str:
    arch_docs = [doc for doc in state.documents if doc["doc_type"] in {"architecture", "adr"}]
    lines = [frontmatter(state, "dashboard") + "# Architecture Evolution", ""]
    for doc in arch_docs[:80]:
        git = doc.get("git") or {}
        lines.append(f"- `{git.get('timestamp', '')}` [[{doc['title']}]] — {doc['relative_path']}")
    return "\n".join(lines)


def render_ai_workflow_memory(state: ObsidianSourceState) -> str:
    return frontmatter(state, "dashboard") + "\n".join(
        [
            "# AI Workflow Memory",
            "",
            "## Generated Workflow",
            "- AI tools update SDD docs in source repositories.",
            "- `repo-intel ingest` updates machine memory.",
            "- `repo-intel obsidian sync` updates this cognitive layer.",
            "",
            "## Key Pages",
            "- [[Prompt Memory]]",
            "- [[Ask History]]",
            "- [[Active Work]]",
        ]
    )


def render_project_brief(state: ObsidianSourceState) -> str:
    body = state.project_brief or "# Project Brief\n\nNo project brief generated yet. Run `repo-intel brief`."
    return frontmatter(state, "project") + body


def render_project_index(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "project") + f"# {state.project_name} Project Index", ""]
    lines.append("## Repositories")
    for repo in state.repositories:
        lines.append(f"- [[{repo['name']}]]")
    lines.append("\n## Topics")
    for topic in state.topics:
        lines.append(f"- [[{topic['name']}]]")
    return "\n".join(lines)


def render_repository_map(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "project") + "# Repository Map", "", "```mermaid", "graph TD"]
    for repo in state.repositories:
        lines.append(f"  project[{state.project_name}] --> {node_id(repo['name'])}[{repo['name']}]")
    lines.append("```")
    return "\n".join(lines)


def render_repository_page(state: ObsidianSourceState, repo: dict[str, Any]) -> str:
    docs = [doc for doc in state.documents if doc["repository_id"] == repo["id"]]
    chunks = [chunk for chunk in state.chunks if chunk["repository_id"] == repo["id"]]
    topics = topics_for_repo(state, repo["name"])
    lines = [
        frontmatter(
            state,
            "repository",
            repo=repo["name"],
            docs=len(docs),
            chunks=len(chunks),
            branch=repo.get("branch", ""),
        )
        + f"# {repo['name']}",
        "",
        "## Role",
        "Knowledge extracted from SDD documentation for this repository.",
        "",
        "## Status",
        f"- Branch: `{repo.get('branch') or 'n/a'}`",
        f"- Git status at ingest: `{repo.get('git_status')}`",
        f"- Documents: {len(docs)}",
        f"- Chunks: {len(chunks)}",
        "",
        "## Key Docs",
    ]
    for doc in sorted(docs, key=doc_priority)[:18]:
        lines.append(f"- {doc['repo_relative_path']} ({doc['doc_type']})")
    lines.append("\n## Related Topics")
    lines.append(" ".join(f"[[{topic}]]" for topic in topics[:12]) or "No topics detected.")
    return "\n".join(lines)


def render_architecture_map(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "architecture") + "# Architecture Map", "", "```mermaid", "graph TD"]
    repos = {repo["name"] for repo in state.repositories}
    for source, target in infer_repo_edges(repos):
        lines.append(f"  {node_id(source)}[{source}] --> {node_id(target)}[{target}]")
    lines.append("```")
    lines.append("\n## Related Pages\n- [[Cross Repo Relationships]]\n- [[Infrastructure Map]]")
    return "\n".join(lines)


def render_cross_repo_relationships(state: ObsidianSourceState) -> str:
    topic_to_repos = {topic["name"]: topic["repos"] for topic in state.topics if len(topic["repos"]) > 1}
    lines = [frontmatter(state, "architecture") + "# Cross Repo Relationships", ""]
    for topic, repos in list(topic_to_repos.items())[:30]:
        lines.append(f"- [[{topic}]]: " + ", ".join(f"[[{repo}]]" for repo in repos))
    return "\n".join(lines)


def render_infrastructure_map(state: ObsidianSourceState) -> str:
    lines = [frontmatter(state, "architecture") + "# Infrastructure Map", ""]
    for topic in state.topics:
        if topic["name"] in {"Infrastructure", "Redis Streams"}:
            lines.append(f"- [[{topic['name']}]]: " + ", ".join(f"[[{repo}]]" for repo in topic["repos"]))
    return "\n".join(lines)


def render_adr_index(state: ObsidianSourceState) -> str:
    docs = [doc for doc in state.documents if doc["doc_type"] == "adr"]
    lines = [frontmatter(state, "decision-index") + "# ADR Index", ""]
    for doc in docs:
        lines.append(f"- {doc['title']} — `{doc['relative_path']}`")
    return "\n".join(lines)


def render_decision_timeline(state: ObsidianSourceState) -> str:
    docs = [doc for doc in state.documents if doc["doc_type"] in {"adr", "architecture"}]
    lines = [frontmatter(state, "decision-timeline") + "# Decision Timeline", ""]
    for doc in sorted(docs, key=lambda item: (item.get("git") or {}).get("timestamp") or ""):
        git = doc.get("git") or {}
        lines.append(f"- `{git.get('timestamp', '')}` {doc['title']} — `{doc['relative_path']}`")
    return "\n".join(lines)


def render_topic_page(state: ObsidianSourceState, topic: dict[str, Any]) -> str:
    lines = [
        frontmatter(state, "topic", topic=topic["name"], repos=topic["repos"])
        + f"# {topic['name']}",
        "",
        "## Related Repositories",
        " ".join(f"[[{repo}]]" for repo in topic["repos"]),
        "",
        "## Source Sections",
    ]
    for source in topic["sources"]:
        lines.append(f"- {source['repo']} / {source['path']} / {source['section']}")
    return "\n".join(lines)


def render_prompt_memory(state: ObsidianSourceState) -> str:
    docs = [doc for doc in state.documents if doc["doc_type"] in {"agent-guide", "handoff"}]
    lines = [frontmatter(state, "ai-workflow") + "# Prompt Memory", ""]
    for doc in docs:
        lines.append(f"- {doc['title']} — `{doc['relative_path']}`")
    return "\n".join(lines)


def render_ask_history(state: ObsidianSourceState) -> str:
    lines = [
        frontmatter(state, "ai-workflow") + "# Ask History",
        "",
        "V1 reads the latest answer plan from `.repo-intel/artifacts/last-answer-plan.json`.",
    ]
    plan = state.last_answer_plan or {}
    if not plan:
        lines.append("\nNo answer plan has been recorded yet.")
        return "\n".join(lines)

    intent = plan.get("intent") or {}
    intent_name = intent.get("name", "unknown") if isinstance(intent, dict) else str(intent)
    lines.extend(
        [
            "",
            "## Latest Answer Plan",
            f"- Intent: `{intent_name}`",
            f"- Question: {plan.get('question', 'n/a')}",
            "",
            "## Sources",
        ]
    )
    for source in (plan.get("selected_contexts") or plan.get("selected") or [])[:12]:
        metadata = source.get("metadata") or source
        repo = metadata.get("repo", "unknown")
        path = metadata.get("path", "")
        section = metadata.get("section", "")
        score = source.get("combined_score", source.get("score", 0)) or 0
        lines.append(f"- [[{repo}]] / `{path}` / {section} (score: {score:.3f})")
    return "\n".join(lines)


def render_active_work(state: ObsidianSourceState) -> str:
    dirty = [repo for repo in state.repositories if repo.get("git_status") == "dirty"]
    lines = [frontmatter(state, "ai-workflow") + "# Active Work", ""]
    for repo in dirty:
        lines.append(f"- [[{repo['name']}]] has dirty git status at last ingest.")
    return "\n".join(lines)


def render_sync_status(state: ObsidianSourceState) -> str:
    return frontmatter(state, "system") + "\n".join(
        [
            "# Sync Status",
            "",
            f"- Last synced: `{state.synced_at.isoformat()}`",
            f"- Repositories: {len(state.repositories)}",
            f"- Documents: {len(state.documents)}",
            f"- Chunks: {len(state.chunks)}",
            f"- Runs: {len(state.runs)}",
        ]
    )


def render_source_manifest(state: ObsidianSourceState) -> str:
    lines = [
        frontmatter(state, "system") + "# Source Manifest",
        "",
        "- SQLite: `.repo-intel/knowledge.db`",
        "- Briefs: `.repo-intel/briefs/project-brief.md`",
        "",
        "## Artifacts",
    ]
    lines.extend(render_manifest_items(state.artifacts))
    lines.append("\n## Exports")
    lines.extend(render_manifest_items(state.exports))
    return "\n".join(lines)


def render_generation_log(state: ObsidianSourceState) -> str:
    return frontmatter(state, "system") + "\n".join(
        [
            "# Generation Log",
            "",
            f"- Generated at `{state.synced_at.isoformat()}` from repo-intel machine memory.",
        ]
    )


def render_manifest_items(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None found."]
    return [
        f"- `{item['relative_path']}` ({item['size']} bytes, modified `{item['modified_at']}`)"
        for item in items
    ]


def doc_priority(doc: dict[str, Any]) -> tuple[int, str]:
    order = {
        "ai-index": 0,
        "agent-guide": 1,
        "readme": 2,
        "product": 3,
        "architecture": 4,
        "api-contract": 5,
        "sdd-spec": 6,
        "adr": 7,
    }
    return (order.get(doc["doc_type"], 99), doc["relative_path"])


def topics_for_repo(state: ObsidianSourceState, repo_name: str) -> list[str]:
    return [topic["name"] for topic in state.topics if repo_name in topic["repos"]]


def infer_repo_edges(repos: set[str]) -> list[tuple[str, str]]:
    preferred = [
        ("proxima-admin", "proxima-api"),
        ("proxima-builder", "proxima-api"),
        ("proxima-website", "proxima-api"),
        ("proxima-pos", "proxima-api"),
        ("proxima-api", "proxima-intelligence"),
        ("proxima-infra", "proxima-api"),
    ]
    return [(source, target) for source, target in preferred if source in repos and target in repos]


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "-", value.strip())
    return value or "Untitled"


def node_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)
