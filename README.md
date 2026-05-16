# repo-intel

SDD-only engineering knowledge platform for multi-repository AI-native projects.

The CLI reads AI/SDD documentation maintained by each repository. It does not inspect or parse source code for ingestion.

## Quick Start

```bash
uv sync
uv run repo-intel workspace add proxima /Users/lucho/projects/me/proxima
uv run repo-intel init proxima
uv run repo-intel scan proxima
uv run repo-intel ingest proxima
uv run repo-intel query proxima "checkout architecture"
uv run repo-intel ask proxima "Como funciona checkout?"
uv run repo-intel obsidian sync proxima
```

Workspace memory remains isolated inside each workspace:

```text
/path/to/workspace/.repo-intel/
  config.toml
  knowledge.db
  chroma/
  artifacts/
  exports/
  briefs/
  obsidian-vault/
```

Named workspaces are registered globally:

```text
~/.repo-intel/workspaces.json
```

## Commands

```bash
repo-intel workspace add <name> <path>
repo-intel workspace list
repo-intel workspace status <name>

repo-intel init <target>
repo-intel scan <target>
repo-intel ingest <target>
repo-intel query <target> "question"
repo-intel ask <target> "question"
repo-intel brief <target>
repo-intel status <target>
repo-intel export <target>

repo-intel obsidian init <target>
repo-intel obsidian sync <target>
repo-intel obsidian status <target>
repo-intel obsidian watch <target>
```

`target` can be either a registered workspace name or a filesystem path.

## Local Models

Before `ingest` or `query`, make sure Ollama is running and the embedding model exists:

```bash
ollama pull nomic-embed-text
```

By default the CLI expects Ollama at:

```text
http://192.168.1.12:11434
```

Override this per workspace in `.repo-intel/config.toml`.

## OpenRouter

OpenRouter is optional and used only by features configured for it, such as richer brief generation.

```bash
cp .env.example .env
```

Then set:

```text
OPENROUTER_API_KEY=...
```
