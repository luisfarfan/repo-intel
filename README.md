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
DECISIONS.md
docs/*.md
docs/**/*.md
**/docs/*.md
docs_*/**/*.md
openspec/**/*.md
```

> **Pattern gotcha.** Matching falls back to `fnmatch`, whose `*` crosses `/`. That
> makes `docs/**/*.md` recursive, but it still requires at least one intermediate
> directory — so a flat `docs/api-conventions.md` matched *nothing*. `docs/*.md` and
> `**/docs/*.md` are both needed. Verify a new pattern before trusting it:
>
> ```bash
> python -c "from repo_intel.sdd.discovery import match_path; print(match_path('docs/a.md','docs/**/*.md'))"
> ```

### Scoping the corpus

Two knobs keep retrieval relevant rather than merely large:

- **`repos = [...]`** (top level of `config.toml`) is an explicit allowlist. An empty
  list means "index everything found", which is the back-compatible default. Naming the
  active repos keeps deprecated ones out of the embedding space.
- **`openspec/changes/archive/**` is excluded by default.** In the PROXIMA workspace the
  archive is ~70% of all openspec markdown, and it is superseded history that is
  near-duplicate of the living specs — indexing it lets obsolete text outrank current
  truth. This is safe because archiving *promotes* content into `openspec/specs/`, so the
  surviving knowledge stays indexed. Drop the exclude line if you specifically want
  historical recall.

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
repo-intel config set llm.provider cliproxy
repo-intel config set llm.base_url http://127.0.0.1:8317/v1
repo-intel config set llm.model gemini-3-flash
```

Store secrets (values go to `~/.repo-intel/.env`, never to `config.toml` — see
[LLM providers](#llm-providers)):

```bash
repo-intel config env set CLIPROXY_API_KEY <key>
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

## Auto-Update (incremental reindex)

An index nobody refreshes is an index nobody trusts. `ingest` is therefore
**incremental by default** and cheap enough to run from a git hook.

### What makes it cheap

Three gates, cheapest first. Each one only lets through what the previous one could not
rule out:

| Gate | Skips | Why it is safe |
|------|-------|----------------|
| **Document hash** | git metadata lookup | A doc whose sha256 is unchanged reuses its stored git metadata. Hashing is microseconds; `git log -1 -- <path>` per doc dominated scan time. |
| **Scan diff** | re-chunking + rewrites | Only documents whose content hash moved (or that vanished) are re-chunked. Everything else is left alone in SQLite. |
| **Chunk id** | embedding calls | Chunk ids are content-addressed (`sha256(text)` is part of the id), so an unchanged *section* keeps its id and its vector. Editing one heading of a long spec re-embeds that section only. |

Deleted or rewritten chunks are pruned from Chroma too, so retrieval never cites text
that no longer exists in any document.

Measured on the PROXIMA workspace (10 repos, 933 docs, 7,848 chunks):

| Scenario | Documents changed | Embeddings created | Wall time |
|---|---|---|---|
| Nothing changed | 0 | 0 | **~13 s** |
| One new document | 1 | 1 | **~14 s** |
| One section edited in a 3-section doc | 1 | **1** (not 3) | ~14 s |
| Document deleted | 0 (1 removed) | 0 | ~13 s |
| `--full` rebuild | 933 | 7,848 | ~6.5 min |

```bash
repo-intel ingest <workspace>          # incremental (default)
repo-intel ingest <workspace> --full   # force a complete rebuild
repo-intel ingest <workspace> --quiet  # one-line summary, for hooks
```

`ingest` is also **resumable**: an interrupted run keeps every embedding it already
wrote, so relaunching continues where it stopped instead of starting over.

> **Do not persist a scan with `upsert_scan`.** That method truncates
> `semantic_chunks` and `embeddings`. `scan()` and `ingest()` both use `sync_scan`,
> which diffs instead of wiping. Calling `upsert_scan` before the "already embedded"
> check is what silently forced a full re-embed on every single run.

### Wiring it to a trigger

In the PROXIMA workspace the reindex is driven automatically; see
`proxima-engineering/docs/repo-intel-auto-update.md`. Summary:

- **post-commit hook** (primary) — fires when a commit touches indexed docs
  (`openspec/**`, `docs/**`, `*SPEC*.md`, …). Runs detached, so `git commit` returns
  immediately, and can never fail a commit. Archiving an OpenSpec change is a `git mv`
  out of `openspec/changes/<name>/`, which the hook detects as vacated live paths.
- **hourly launchd sweep** (backstop) — catches `git pull`, edits outside git, repos
  where the hook was never installed, and passes that failed while Ollama was down.
- A `mkdir` mutex serialises runs; a request arriving mid-pass is **coalesced** into a
  follow-up round rather than dropped.
- Every run appends to `<workspace>/.repo-intel/reindex.log`.

## MCP server (Claude Code / Cursor)

`repo-intel-mcp` exposes the answer engine over MCP, so an agent can query the docs without
shelling out. Three tools:

| Tool | Cost | Use it for |
|---|---|---|
| `search_docs(query, k)` | free, no LLM | raw chunks + file paths — when you want to read the source yourself |
| `ask_docs(question)` | one LLM call, cached | a synthesised, cited answer |
| `knowledge_status()` | free | index freshness (counts + last ingestion run) |

Register it:

```json
{
  "mcpServers": {
    "repo-intel": {
      "command": "/Users/lucho/projects/me/proxima/repo-intelligence-cli/.venv/bin/repo-intel-mcp",
      "cwd": "/Users/lucho/projects/me/proxima"
    }
  }
}
```

**`cwd` is mandatory, not cosmetic.** The server resolves the workspace from the current working
directory. Start it anywhere else and it will look for a `.repo-intel/` that isn't there and serve
an empty index — with no obvious error. On startup it prints the workspace it resolved to stderr
(`[repo-intel-mcp] serving workspace: ...`); check that line first when results look empty.

If `repo-intel-mcp` is missing from `.venv/bin/`, the console script was declared after the venv
was created — re-sync with `uv sync`. Verify without a client:

```bash
cd /Users/lucho/projects/me/proxima
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  | ./repo-intelligence-cli/.venv/bin/repo-intel-mcp
```

The API key is read the same way as the CLI (`CLIPROXY_API_KEY`, see **LLM providers**) — the MCP
server inherits it from `~/.repo-intel/.env`, so there is nothing to configure per client.

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

## LLM providers

Chat (`ask`, `brief`) and embeddings (`ingest`) are configured **independently**. They
routinely live on different hosts: embeddings stay local for cost and privacy, while
chat goes to a gateway.

`[llm] provider` selects the chat backend:

| provider | endpoint | notes |
|---|---|---|
| `ollama` | `{base_url}/api/generate` | Ollama's native API. `base_url` has **no** `/v1`. |
| `cliproxy` | `{base_url}/chat/completions` | OpenAI-compatible. `base_url` **must** end in `/v1`. |
| `openrouter` | `{base_url}/chat/completions` | OpenAI-compatible, hosted. |

Anything else fails loudly at startup rather than silently falling back to Ollama.

### PROXIMA setup (cliproxy chat + local Ollama embeddings)

```bash
repo-intel setup --preset proxima
```

That preset writes:

```toml
[embeddings]
provider = "ollama"
model    = "nomic-embed-text:latest"
base_url = "http://127.0.0.1:11434"   # local, free, private -- do NOT move to a gateway

[llm]
provider    = "cliproxy"
model       = "gemini-3-flash"
base_url    = "http://127.0.0.1:8317/v1"
api_key_env = "CLIPROXY_API_KEY"       # the NAME of the variable, never the value
```

### Setting the API key

**The key is never written to `config.toml` and never committed.** `config.toml` stores
only `api_key_env` — the *name* of the environment variable. The value is resolved from
the environment at call time and lives in `~/.repo-intel/.env` (created `chmod 600`):

```bash
repo-intel config env set CLIPROXY_API_KEY <key>   # writes ~/.repo-intel/.env, mode 600
repo-intel config env list                          # values are masked
```

For a one-off shell session, exporting works just as well:

```bash
export CLIPROXY_API_KEY=<key>
```

For the PROXIMA workspace the key is the first entry of `api-keys` in
`~/projects/make-montages/config/cliproxy/config.yaml`.

This is enforced in code, not by discipline: `render_config()` calls
`assert_no_inline_secrets()` and refuses to serialize any field matching
`(api_key|secret|token|password)` that does not end in `_env`.

Verify the whole chain — endpoint reachable, key present, model offered:

```bash
repo-intel config doctor --workspace proxima
```

```text
│ ollama          │ ok │ http://127.0.0.1:11434 (2 model(s))    │
│ embedding_model │ ok │ nomic-embed-text:latest                │
│ llm_provider    │ ok │ cliproxy -> http://127.0.0.1:8317/v1   │
│ llm_api_key     │ ok │ CLIPROXY_API_KEY is set                │
│ llm_endpoint    │ ok │ http://127.0.0.1:8317/v1 (34 model(s)) │
│ llm_model       │ ok │ gemini-3-flash                         │
```

### OpenRouter (briefs)

`[brief]` has its own provider and can differ from `[llm]`. Set
`brief.provider = "cliproxy"` to reuse the local gateway, or keep OpenRouter:

```bash
repo-intel config env set OPENROUTER_API_KEY sk-...
repo-intel brief my-project
```

If the primary brief provider fails, `brief.fallback_provider` / `fallback_model` are
retried once before the command aborts.

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
