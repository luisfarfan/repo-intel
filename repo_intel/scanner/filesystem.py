from __future__ import annotations

from pathlib import Path

from repo_intel.scanner.ignore_rules import IGNORED_DIRS, is_ignored_file


def iter_files(root: Path, max_depth: int | None = None) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []

    def walk(path: Path, depth: int) -> None:
        if max_depth is not None and depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in IGNORED_DIRS:
                    continue
                walk(entry, depth + 1)
            elif entry.is_file() and not is_ignored_file(entry):
                files.append(entry)

    walk(root, 0)
    return files

