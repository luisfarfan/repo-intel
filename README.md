# repo-intel

`repo-intel` is a local-first CLI for turning AI/SDD documentation from multi-repository workspaces into a queryable engineering knowledge base.

It is intentionally **SDD-only**: it reads structured engineering documentation such as `AI_INDEX.md`, `AGENT_START_HERE.md`, `README.md`, `PRODUCT.md`, specs, architecture docs, and `docs/**/*.md`. It does not inspect or parse source implementation files for ingestion.

## What It Does

- Discovers repositories inside a workspace.
- Finds allowed SDD/AI documentation files.
- Extracts document and git metadata.
- Parses Markdown by heading/section.
- Creates semantic chunks.
- Stores metadata in per-workspace SQLite.
- Indexes embeddings into per-workspace ChromaDB.
- Answers questions with sourced SDD context.
- Caches repeated answers safely.
- Generates Obsidian dashboards and maps.
- Generates optional NotebookLM source bundles.

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
  notebooklm/
```

Global CLI configuration lives in:

```text
~/.repo-intel/
  config.toml
  .env
  workspaces.json
```

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Ollama for local embeddings and local answers
- Optional: OpenRouter for richer project briefs
- Optional: Obsidian for the generated vault
- Optional: `notebooklm-py` for NotebookLM upload

## Installation

For local development from a clone:

```bash
git clone git@github.com:luisfarfan/repo-intel.git
cd repo-intel
uv sync
uv tool install --editable .
```

If you want optional NotebookLM upload support, install the uploader CLI too:

```bash
uv tool install "notebooklm-py[browser]"
playwright install chromium
```

Validate the CLI:

```bash
repo-intel --help
repo-intel setup --help
```

## Initial Setup

Run the setup wizard:

```bash
repo-intel setup
```

For a minimal non-interactive setup:

```bash
repo-intel setup --preset minimal --non-interactive
```

Default portable settings use local Ollama:

```text
http://localhost:11434
```

For a remote Ollama server:

```bash
repo-intel setup \
  --preset remote-ollama \
  --ollama-url http://YOUR_OLLAMA_HOST:11434 \
  --embedding-model nomic-embed-text \
  --llm-model phi3:mini \
  --non-interactive
```

Check configuration and service connectivity:

```bash
repo-intel config show
repo-intel config doctor
```

Configuration precedence:

```text
built-in defaults
  < ~/.repo-intel/config.toml
  < <workspace>/.repo-intel/config.toml
  < REPO_INTEL_* environment variables
```

## Local Models

Install an embedding model in Ollama:

```bash
ollama pull nomic-embed-text
```

Install a small local chat model:

```bash
ollama pull phi3:mini
```

You can update global defaults at any time:

```bash
repo-intel config set embeddings.base_url http://localhost:11434
repo-intel config set embeddings.model nomic-embed-text
repo-intel config set llm.base_url http://localhost:11434
repo-intel config set llm.model phi3:mini
```

## Basic Workflow

Register a workspace:

```bash
repo-intel workspace add my-project /path/to/workspace
```

Initialize and ingest:

```bash
repo-intel init my-project
repo-intel scan my-project
repo-intel ingest my-project
```

Ask questions:

```bash
repo-intel query my-project "checkout architecture"
repo-intel ask my-project "How does checkout work?"
```

Generate exports:

```bash
repo-intel export my-project
repo-intel brief my-project
```

## Commands

```bash
repo-intel setup

repo-intel workspace add <name> <path>
repo-intel workspace list
repo-intel workspace status <name>

repo-intel config show
repo-intel config doctor
repo-intel config set <key> <value>
repo-intel config get <key>
repo-intel config env set <key> <value>
repo-intel config env list

repo-intel init <target>
repo-intel scan <target>
repo-intel ingest <target>
repo-intel query <target> "question"
repo-intel ask <target> "question"
repo-intel brief <target>
repo-intel status <target>
repo-intel export <target>
repo-intel reset <target>

repo-intel obsidian init <target>
repo-intel obsidian sync <target>
repo-intel obsidian status <target>
repo-intel obsidian watch <target>

repo-intel notebooklm login
repo-intel notebooklm auth-check <target>
repo-intel notebooklm generate-sources <target>
repo-intel notebooklm init <target>
repo-intel notebooklm sync <target>
repo-intel notebooklm status <target>
```

`target` can be either a registered workspace name or a filesystem path.

## OpenRouter

OpenRouter is optional. It is used only by features configured for it, such as richer project brief generation.

Store the API key globally:

```bash
repo-intel config env set OPENROUTER_API_KEY sk-...
```

Secrets are stored locally in:

```text
~/.repo-intel/.env
```

## Obsidian

Generate an Obsidian vault from the indexed repo-intel memory:

```bash
repo-intel obsidian init my-project
repo-intel obsidian sync my-project
```

The default vault path is:

```text
/path/to/workspace/.repo-intel/obsidian-vault
```

Open that folder in Obsidian with **Open folder as vault**.

## NotebookLM

NotebookLM support is optional and uses the unofficial `notebooklm-py` CLI as an upload adapter. `repo-intel` remains the source of truth; NotebookLM receives generated Markdown bundles.

Authenticate:

```bash
repo-intel notebooklm login
repo-intel notebooklm auth-check my-project
```

Generate local NotebookLM sources:

```bash
repo-intel notebooklm generate-sources my-project
```

Create or sync the notebook:

```bash
repo-intel notebooklm init my-project
repo-intel notebooklm sync my-project
```

Local NotebookLM state is stored per workspace:

```text
.repo-intel/notebooklm/
  manifest.json
  sources/
```

## OpenSpec

This repository uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven planning.

Canonical specs live in:

```text
openspec/specs/
```

Validate them with:

```bash
openspec validate --all --strict --no-interactive
```

## Development

Run checks:

```bash
uv run ruff check .
uv run python -m compileall repo_intel
openspec validate --all --strict --no-interactive
```
