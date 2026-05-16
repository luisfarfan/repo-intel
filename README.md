# repo-intel

Local-first engineering memory for AI-native, multi-repository projects.

`repo-intel` turns the SDD/AI documentation that already lives in your repositories into a searchable, queryable, and exportable engineering knowledge base. It is built for teams using AI-assisted development, spec-driven documentation, multi-repo systems, and local LLM workflows.

It does **not** analyze implementation source code. The source of truth is documentation: architecture docs, product docs, specs, ADRs, API contracts, AI handoff files, and `docs/**/*.md`.

## Why This Exists

AI-native projects move fast. Architecture decisions, prompts, specs, and handoffs are often spread across many repositories. Generic RAG tools can index everything, but they usually lack project boundaries, git-aware metadata, deterministic document discovery, and developer-friendly workflows.

`repo-intel` is the machine-memory layer for that documentation:

```text
SDD / AI docs
  -> deterministic discovery
  -> Markdown parsing
  -> semantic chunks
  -> SQLite metadata
  -> Ollama embeddings
  -> ChromaDB
  -> ask / query / export / Obsidian / NotebookLM
```

## Core Principles

- **SDD-only:** ingest documentation, not source implementation.
- **Deterministic-first:** filesystem discovery, parsing, metadata, chunking, and filtering are code-driven.
- **Local-first:** each workspace owns its own SQLite, Chroma, artifacts, exports, and generated vaults.
- **Multi-workspace:** register aliases like `proxima`, `client-a`, or `research-lab`.
- **LLM-optional where possible:** LLMs answer and summarize; they do not own ingestion.
- **Integration-friendly:** export to Obsidian, NotebookLM, JSONL, Markdown, and future MCP/RAG layers.

## Features

| Area | What repo-intel does |
| --- | --- |
| Workspace registry | Manage named workspaces globally with `repo-intel workspace ...` |
| SDD discovery | Find allowed AI/SDD Markdown docs across multi-repo workspaces |
| Git metadata | Attach branch, commit, author, timestamp, and commit message to documents |
| Semantic indexing | Chunk docs by structure and index embeddings into ChromaDB |
| Ask engine | Answer questions with citations, hybrid retrieval, and safe cache |
| Configuration | Global setup wizard, workspace overrides, env overrides, diagnostics |
| Obsidian | Generate a human-facing cognitive vault from repo-intel memory |
| NotebookLM | Generate optimized Markdown bundles and optionally sync via `notebooklm-py` |
| OpenSpec | Track platform capabilities with spec-driven documentation |

## Installation

Install from a local clone:

```bash
git clone git@github.com:luisfarfan/repo-intel.git
cd repo-intel
uv sync
uv tool install --editable .
```

Validate:

```bash
repo-intel --help
```

Optional NotebookLM support:

```bash
uv tool install "notebooklm-py[browser]"
playwright install chromium
```

## 5-Minute Quickstart

1. Configure the CLI:

```bash
repo-intel setup
```

For a non-interactive minimal setup:

```bash
repo-intel setup --preset minimal --non-interactive
```

2. Make sure Ollama has the default local models:

```bash
ollama pull nomic-embed-text
ollama pull phi3:mini
```

3. Register a workspace:

```bash
repo-intel workspace add my-project /path/to/workspace
```

4. Ingest documentation:

```bash
repo-intel init my-project
repo-intel scan my-project
repo-intel ingest my-project
```

5. Ask questions:

```bash
repo-intel ask my-project "How does authentication work?"
repo-intel query my-project "checkout architecture"
```

## What Gets Ingested

By default, repo-intel looks for documentation such as:

```text
AI_INDEX.md
AGENT_START_HERE.md
CURSOR_HANDOFF.md
CLAUDE.md
README.md
PRODUCT.md
DESIGN.md
*SPEC*.md
*ARCHITECTURE*.md
*CONTRACT*.md
docs/**/*.md
docs_*/**/*.md
```

It excludes implementation and generated folders such as:

```text
src/
app/
lib/
tests/
migrations/
scripts/
node_modules/
dist/
build/
.venv/
.agents/
.claude/
```

The include/exclude rules are configurable per workspace in:

```text
<workspace>/.repo-intel/config.toml
```

## Storage Model

Workspace data is isolated:

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

Global CLI state is intentionally small:

```text
~/.repo-intel/
  config.toml       # global defaults
  .env              # local secrets
  workspaces.json   # named workspace registry
  logs/
```

Configuration precedence:

```text
built-in defaults
  < ~/.repo-intel/config.toml
  < <workspace>/.repo-intel/config.toml
  < REPO_INTEL_* environment variables
```

## Setup and Configuration

Run the wizard:

```bash
repo-intel setup
```

Available presets:

```bash
repo-intel setup --preset local
repo-intel setup --preset remote-ollama
repo-intel setup --preset minimal
repo-intel setup --preset proxima
```

Use a remote Ollama server:

```bash
repo-intel setup \
  --preset remote-ollama \
  --ollama-url http://YOUR_OLLAMA_HOST:11434 \
  --embedding-model nomic-embed-text \
  --llm-model phi3:mini \
  --non-interactive
```

Inspect and validate configuration:

```bash
repo-intel config show
repo-intel config doctor
repo-intel config show --workspace my-project
repo-intel config doctor --workspace my-project
```

Set values manually:

```bash
repo-intel config set embeddings.base_url http://localhost:11434
repo-intel config set embeddings.model nomic-embed-text
repo-intel config set llm.base_url http://localhost:11434
repo-intel config set llm.model phi3:mini
```

Store optional secrets:

```bash
repo-intel config env set OPENROUTER_API_KEY sk-...
repo-intel config env list
```

## Daily Workflow

```bash
# See registered workspaces
repo-intel workspace list

# Refresh the local knowledge base
repo-intel ingest my-project

# Ask with sourced answers
repo-intel ask my-project "What changed in the billing architecture?"

# Inspect raw retrieval
repo-intel query my-project "Redis Streams"

# Generate portable bundles
repo-intel export my-project

# Generate/update human-facing surfaces
repo-intel obsidian sync my-project
repo-intel notebooklm generate-sources my-project
```

## Answer Engine

`repo-intel ask` is the human-facing answer command. It:

- classifies the question intent
- retrieves semantic candidates from ChromaDB
- adds lexical/document-based candidates
- boosts overview, architecture, ADR, API contract, and SDD documents when relevant
- injects the project brief for broad overview questions
- produces a concise answer with sources
- caches repeated answers when the indexed knowledge and model settings are unchanged

Use `repo-intel query` when you want raw retrieval output instead of a synthesized answer.

## Obsidian

Generate an Obsidian vault from indexed repo-intel memory:

```bash
repo-intel obsidian init my-project
repo-intel obsidian sync my-project
```

Open this folder in Obsidian with **Open folder as vault**:

```text
<workspace>/.repo-intel/obsidian-vault
```

The generated vault includes dashboards, repository pages, topic maps, architecture maps, decision indexes, and sync status pages.

## NotebookLM

NotebookLM support is optional and uses the unofficial [`notebooklm-py`](https://github.com/teng-lin/notebooklm-py) CLI as an upload adapter. NotebookLM is a projection, not the source of truth.

Authenticate:

```bash
repo-intel notebooklm login
repo-intel notebooklm auth-check my-project
```

Generate local sources:

```bash
repo-intel notebooklm generate-sources my-project
```

Create or sync the notebook:

```bash
repo-intel notebooklm init my-project
repo-intel notebooklm sync my-project
```

Local NotebookLM state:

```text
<workspace>/.repo-intel/notebooklm/
  manifest.json
  sources/
```

## OpenRouter

OpenRouter is optional. It is currently useful for richer project briefs.

```bash
repo-intel config env set OPENROUTER_API_KEY sk-...
repo-intel brief my-project
```

The key is stored locally in:

```text
~/.repo-intel/.env
```

## Commands

```bash
repo-intel setup

repo-intel workspace add <name> <path>
repo-intel workspace list
repo-intel workspace show <name>
repo-intel workspace status <name>
repo-intel workspace remove <name>

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

`target` can be a registered workspace alias or a filesystem path.

## OpenSpec

This repository uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven planning.

Canonical specs:

```text
openspec/specs/
```

Validate:

```bash
openspec validate --all --strict --no-interactive
```

## Development

```bash
uv sync
uv run ruff check .
uv run python -m compileall repo_intel
openspec validate --all --strict --no-interactive
```
