from __future__ import annotations

import hashlib
from pathlib import Path

from repo_intel.core.models import RepoInfo
from repo_intel.detectors.stack_detector import detect_stacks, detect_workspace_type, read_package_name
from repo_intel.scanner.ignore_rules import IGNORED_DIRS


REPO_MARKERS = {
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
}


def repo_id_for(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:10]
    name = relative_path.replace("/", "__") or "root"
    return f"repo:{name}:{digest}"


def discover_repos(root: Path, max_depth: int = 4) -> list[RepoInfo]:
    root = root.resolve()
    candidates: set[Path] = set()

    def walk(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(path.iterdir())
        except OSError:
            return

        names = {entry.name for entry in entries}
        if names & REPO_MARKERS:
            candidates.add(path)

        for entry in entries:
            if entry.is_dir() and entry.name not in IGNORED_DIRS:
                walk(entry, depth + 1)

    walk(root, 0)

    repos: list[RepoInfo] = []
    for path in sorted(candidates, key=lambda item: str(item.relative_to(root))):
        relative = path.relative_to(root).as_posix()
        if relative == ".":
            relative = ""
        workspace_type = detect_workspace_type(path)
        stacks = detect_stacks(path)
        repos.append(
            RepoInfo(
                id=repo_id_for(relative),
                name=path.name if relative else root.name,
                path=str(path),
                relative_path=relative,
                is_git_repo=(path / ".git").is_dir(),
                is_monorepo=workspace_type is not None,
                workspace_type=workspace_type,
                package_name=read_package_name(path),
                stacks=stacks,
                domains=infer_domains(path),
                metadata={},
            )
        )
    return repos


def infer_domains(path: Path) -> list[str]:
    text = " ".join(part.lower() for part in path.parts)
    domains = []
    signals = {
        "admin": ["admin"],
        "api": ["api", "backend"],
        "billing": ["billing", "facturacion", "invoice", "invoicing"],
        "builder": ["builder"],
        "commerce": ["commerce", "checkout", "storefront", "store"],
        "infra": ["infra", "deploy", "terraform", "cdk"],
        "intelligence": ["intelligence", "ai", "analytics"],
        "pos": ["pos"],
        "qa": ["qa", "test"],
        "website": ["website", "marketing"],
    }
    for domain, needles in signals.items():
        if any(needle in text for needle in needles):
            domains.append(domain)
    return domains
