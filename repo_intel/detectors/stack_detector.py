from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from repo_intel.core.models import Evidence, StackSignal


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_package_name(path: Path) -> str | None:
    package_json = path / "package.json"
    if not package_json.exists():
        return None
    data = read_json_file(package_json)
    name = data.get("name")
    return name if isinstance(name, str) else None


def detect_workspace_type(path: Path) -> str | None:
    if (path / "pnpm-workspace.yaml").exists():
        return "pnpm-workspace"
    if (path / "nx.json").exists():
        return "nx"
    if (path / "turbo.json").exists():
        return "turborepo"
    package_json = path / "package.json"
    if package_json.exists():
        data = read_json_file(package_json)
        if "workspaces" in data:
            return "npm-workspaces"
    return None


def detect_stacks(path: Path) -> list[StackSignal]:
    signals: dict[str, StackSignal] = {}

    def add(name: str, confidence: float, source: str, reason: str) -> None:
        existing = signals.get(name)
        evidence = Evidence(source=source, reason=reason)
        if existing:
            existing.confidence = max(existing.confidence, confidence)
            existing.evidence.append(evidence)
        else:
            signals[name] = StackSignal(name=name, confidence=confidence, evidence=[evidence])

    package_json = path / "package.json"
    if package_json.exists():
        add("Node.js", 0.85, str(package_json), "package.json exists")
        package = read_json_file(package_json)
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            value = package.get(key)
            if isinstance(value, dict):
                deps.update(value)
        dep_names = set(deps)

        dependency_stacks = {
            "Angular": ["@angular/core", "@angular/cli"],
            "React": ["react", "react-dom"],
            "Astro": ["astro"],
            "NestJS": ["@nestjs/core"],
            "Next.js": ["next"],
            "Vite": ["vite"],
            "TypeScript": ["typescript"],
            "AWS CDK": ["aws-cdk-lib", "aws-cdk"],
            "Playwright": ["@playwright/test", "playwright"],
            "Tailwind CSS": ["tailwindcss"],
        }
        for stack, needles in dependency_stacks.items():
            for needle in needles:
                if needle in dep_names:
                    add(stack, 0.95, str(package_json), f"dependency {needle} found")
                    break

        scripts = package.get("scripts")
        if isinstance(scripts, dict):
            joined = " ".join(str(value).lower() for value in scripts.values())
            if "serverless" in joined:
                add("Serverless", 0.75, str(package_json), "serverless command found in scripts")

    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        add("Python", 0.9, str(pyproject), "pyproject.toml exists")
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project = data.get("project", {}) if isinstance(data, dict) else {}
        deps = project.get("dependencies", []) if isinstance(project, dict) else []
        deps_text = " ".join(str(dep).lower() for dep in deps)
        if "fastapi" in deps_text:
            add("FastAPI", 0.95, str(pyproject), "FastAPI dependency found")
        if "langchain" in deps_text or "llama-index" in deps_text:
            add("AI Services", 0.8, str(pyproject), "AI framework dependency found")

    if (path / "requirements.txt").exists():
        add("Python", 0.75, str(path / "requirements.txt"), "requirements.txt exists")

    if (path / "Dockerfile").exists() or list(path.glob("docker-compose*.yml")):
        add("Docker", 0.9, str(path), "Dockerfile or docker-compose file found")

    if (path / "angular.json").exists():
        add("Angular", 0.98, str(path / "angular.json"), "angular.json exists")

    if (path / "src-tauri").is_dir() or (path / "Cargo.toml").exists():
        add("Rust", 0.8, str(path), "Cargo or src-tauri found")
        if (path / "src-tauri").is_dir():
            add("Tauri", 0.98, str(path / "src-tauri"), "src-tauri directory exists")

    if list(path.glob("*.tf")) or (path / "terraform").exists():
        add("Terraform", 0.9, str(path), "Terraform files found")

    workspace = detect_workspace_type(path)
    if workspace:
        add(workspace, 0.95, str(path), "workspace marker found")

    return sorted(signals.values(), key=lambda item: (-item.confidence, item.name))

