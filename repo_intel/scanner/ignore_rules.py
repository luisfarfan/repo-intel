from __future__ import annotations

from pathlib import Path


IGNORED_DIRS = {
    ".agents",
    ".angular",
    ".astro",
    ".cache",
    ".claude",
    ".claire",
    ".cursor",
    ".git",
    ".kiro",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".qodo",
    ".repo-intel",
    ".ruff_cache",
    ".turbo",
    ".vscode",
    ".venv",
    "__pycache__",
    "build",
    "cdk.out",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "playwright-report",
    "repo-intelligence-cli",
    "scratch",
    "target",
    "test-results",
    "vendor",
    "workspace",
}

IGNORED_FILE_SUFFIXES = {
    ".lock",
    ".log",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".icns",
    ".svg",
    ".pdf",
    ".zip",
}


def is_ignored_dir(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def is_ignored_file(path: Path) -> bool:
    return path.suffix.lower() in IGNORED_FILE_SUFFIXES
