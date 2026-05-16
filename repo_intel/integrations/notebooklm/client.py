from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class NotebookLmCliError(RuntimeError):
    pass


class NotebookLmCli:
    def __init__(self, command: str = "notebooklm", timeout: int = 300) -> None:
        self.command = command
        self.timeout = timeout

    def ensure_available(self) -> None:
        if shutil.which(self.command) is None:
            raise NotebookLmCliError(
                f'NotebookLM CLI "{self.command}" is not installed or not in PATH.\n'
                'Install it with: pip install "notebooklm-py[browser]"\n'
                "Then run: playwright install chromium"
            )

    def login(self, browser: str | None = None) -> None:
        args = ["login"]
        if browser:
            args.extend(["--browser", browser])
        self.run(args, json_output=False)

    def auth_check(self) -> dict[str, Any]:
        return self.run(["auth", "check", "--test", "--json"], json_output=True)

    def create_notebook(self, title: str) -> str:
        data = self.run(["create", title, "--use", "--json"], json_output=True)
        notebook_id = find_value(data, {"notebook_id", "id", "active_notebook_id"})
        if not notebook_id:
            notebook = data.get("notebook") if isinstance(data, dict) else None
            if isinstance(notebook, dict):
                notebook_id = find_value(notebook, {"id", "notebook_id"})
        if not notebook_id:
            raise NotebookLmCliError(f"Could not parse created notebook id from: {data}")
        return str(notebook_id)

    def use_notebook(self, notebook_id: str) -> None:
        self.run(["use", notebook_id, "--force"], json_output=False)

    def delete_source_by_title(self, notebook_id: str, title: str) -> bool:
        result = self.run(
            ["source", "delete-by-title", title, "-n", notebook_id, "-y", "--json"],
            json_output=True,
            check=False,
        )
        return not isinstance(result, dict) or result.get("success", True) is not False

    def add_file_source(self, notebook_id: str, path: Path, title: str) -> str | None:
        data = self.run(
            [
                "source",
                "add",
                str(path),
                "-n",
                notebook_id,
                "--title",
                title,
                "--timeout",
                str(self.timeout),
                "--json",
            ],
            json_output=True,
        )
        value = find_value(data, {"source_id", "id"})
        if value:
            return str(value)
        source = data.get("source") if isinstance(data, dict) else None
        if isinstance(source, dict):
            value = find_value(source, {"source_id", "id"})
            return str(value) if value else None
        return None

    def run(self, args: list[str], json_output: bool, check: bool = True) -> Any:
        self.ensure_available()
        completed = subprocess.run(
            [self.command, *args],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if check and completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise NotebookLmCliError(message or f"{self.command} exited with {completed.returncode}")
        if not json_output:
            return completed.stdout
        text = completed.stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise NotebookLmCliError(f"Expected JSON from notebooklm CLI, got: {text[:500]}") from exc


def find_value(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key]:
                return data[key]
        for value in data.values():
            found = find_value(value, keys)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = find_value(item, keys)
            if found:
                return found
    return None

