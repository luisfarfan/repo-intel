from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Evidence:
    source: str
    reason: str


@dataclass
class StackSignal:
    name: str
    confidence: float
    method: str = "deterministic"
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class RepoInfo:
    id: str
    name: str
    path: str
    relative_path: str
    is_git_repo: bool
    is_monorepo: bool
    workspace_type: str | None = None
    package_name: str | None = None
    stacks: list[StackSignal] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentInfo:
    id: str
    repo_id: str | None
    path: str
    relative_path: str
    title: str
    doc_type: str
    confidence: float
    method: str = "deterministic"
    tags: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    sha256: str | None = None
    size_bytes: int = 0


@dataclass
class Relationship:
    source: str
    target: str
    kind: str
    confidence: float
    method: str = "deterministic"
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ProjectManifest:
    root: str
    generated_by: str
    repos: list[RepoInfo]
    docs: list[DocumentInfo]
    relationships: list[Relationship]


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return value

