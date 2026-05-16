from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repo_intel.core.config import AppConfig, resolve_workspace_path
from repo_intel.obsidian.models import ObsidianSourceState


STOPWORDS = {
    "the",
    "and",
    "para",
    "con",
    "una",
    "uno",
    "los",
    "las",
    "del",
    "por",
    "que",
    "docs",
    "repo",
    "proxima",
    "frontend",
    "backend",
}

CANONICAL_TOPICS = {
    "checkout": "Checkout",
    "pos": "POS Offline",
    "offline": "POS Offline",
    "builder": "Builder",
    "storefront": "Storefront",
    "redis": "Redis Streams",
    "streams": "Redis Streams",
    "billing": "Billing",
    "facturacion": "Facturacion",
    "facturación": "Facturacion",
    "inventory": "Inventory",
    "inventario": "Inventory",
    "analytics": "Analytics",
    "fulfillment": "Fulfillment",
    "auth": "Auth",
    "commerce": "Commerce",
    "catalog": "Catalog",
    "cms": "CMS",
    "infrastructure": "Infrastructure",
    "infra": "Infrastructure",
}


def load_obsidian_source(workspace: Path, config: AppConfig) -> ObsidianSourceState:
    db_path = resolve_workspace_path(workspace, config.storage.sqlite_path)
    if not db_path.exists():
        raise FileNotFoundError(f"repo-intel SQLite DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        repositories = [dict(row) for row in conn.execute("select * from repositories")]
        documents = [dict(row) for row in conn.execute("select * from sdd_documents")]
        chunks = [dict(row) for row in conn.execute("select * from semantic_chunks")]
        runs = [
            dict(row)
            for row in conn.execute("select * from ingestion_runs order by started_at desc limit 20")
        ]

    repositories = [decode_json_fields(repo, ["sdd_roots_json"]) for repo in repositories]
    documents = [decode_json_fields(doc, ["tags_json", "git_json"]) for doc in documents]
    chunks = [decode_json_fields(chunk, ["heading_path_json", "metadata_json"]) for chunk in chunks]
    runs = [decode_json_fields(run, ["errors_json"]) for run in runs]

    brief_path = workspace / ".repo-intel" / "briefs" / "project-brief.md"
    project_brief = brief_path.read_text(encoding="utf-8", errors="ignore") if brief_path.exists() else None
    artifacts = read_file_manifest(workspace / ".repo-intel" / "artifacts", ["*.json"])
    exports = read_file_manifest(workspace / ".repo-intel" / "exports", ["*.md", "*.jsonl"])
    last_answer_plan = read_json_file(workspace / ".repo-intel" / "artifacts" / "last-answer-plan.json")
    topics = build_topics(chunks)

    return ObsidianSourceState(
        workspace=str(workspace),
        project_name=config.project_name,
        synced_at=datetime.now(timezone.utc),
        repositories=repositories,
        documents=documents,
        chunks=chunks,
        runs=runs,
        project_brief=project_brief,
        topics=topics,
        artifacts=artifacts,
        exports=exports,
        last_answer_plan=last_answer_plan,
    )


def decode_json_fields(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    decoded = dict(row)
    for field in fields:
        value = decoded.pop(field, None)
        decoded[field.removesuffix("_json")] = json.loads(value) if value else None
    return decoded


def read_file_manifest(root: Path, patterns: list[str]) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    files: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "relative_path": str(path.relative_to(root.parent.parent)),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
    return sorted(files, key=lambda item: item["name"])


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_topics(chunks: list[dict[str, Any]], limit: int = 36) -> list[dict[str, Any]]:
    topic_repos: dict[str, set[str]] = defaultdict(set)
    topic_sources: dict[str, list[dict[str, str]]] = defaultdict(list)
    counts: Counter[str] = Counter()

    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        repo = metadata.get("repo", "")
        path = metadata.get("path", "")
        section = metadata.get("section", "") or chunk.get("section", "")
        text = " ".join([path, section, " ".join(chunk.get("heading_path") or [])])
        topics = extract_topics(text)
        for topic in topics:
            counts[topic] += 1
            topic_repos[topic].add(repo)
            if len(topic_sources[topic]) < 12:
                topic_sources[topic].append(
                    {
                        "repo": repo,
                        "path": path,
                        "section": section,
                        "doc_type": metadata.get("doc_type", ""),
                    }
                )

    return [
        {
            "name": topic,
            "count": count,
            "repos": sorted(topic_repos[topic]),
            "sources": topic_sources[topic],
        }
        for topic, count in counts.most_common(limit)
    ]


def extract_topics(text: str) -> set[str]:
    lowered = text.lower()
    topics = set()
    for needle, label in CANONICAL_TOPICS.items():
        if needle in lowered:
            topics.add(label)

    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", lowered):
        if word in STOPWORDS:
            continue
        if len(topics) >= 4:
            break
        topics.add(title_topic(word))
    return topics


def title_topic(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-"))
