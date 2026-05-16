from __future__ import annotations

from pathlib import Path


def repo_intel_home() -> Path:
    return Path.home() / ".repo-intel"


def ensure_repo_intel_home() -> Path:
    home = repo_intel_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    config_path = home / "config.toml"
    if not config_path.exists():
        config_path.write_text(
            "\n".join(
                [
                    "# repo-intel global configuration",
                    "# Workspace-specific memory remains inside each workspace .repo-intel folder.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return home


def workspaces_registry_path() -> Path:
    return repo_intel_home() / "workspaces.json"
