from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from repo_intel.platform.home import global_env_path


def load_project_env() -> None:
    package_root = Path(__file__).resolve().parents[2]
    load_dotenv(global_env_path())
    load_dotenv(package_root / ".env")
    load_dotenv()
