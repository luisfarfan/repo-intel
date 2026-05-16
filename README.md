# repo-intel

SDD-only engineering knowledge platform for multi-repository AI-native projects.

The CLI reads AI/SDD documentation maintained by each repository. It does not inspect or parse source code for ingestion.

## Quick Start

```bash
uv sync
uv tool install --editable . --with "notebooklm-py[browser]"
repo-intel setup --non-interactive
repo-intel workspace add proxima /Users/lucho/projects/me/proxima
repo-intel init proxima
repo-intel scan proxima
repo-intel ingest proxima
repo-intel query proxima "checkout architecture"
repo-intel ask proxima "Como funciona checkout?"
repo-intel obsidian sync proxima
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

repo-intel setup
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

repo-intel obsidian init <target>
repo-intel obsidian sync <target>
repo-intel obsidian status <target>
repo-intel obsidian watch <target>

repo-intel notebooklm login
repo-intel notebooklm generate-sources <target>
repo-intel notebooklm init <target>
repo-intel notebooklm sync <target>
repo-intel notebooklm status <target>
```

`target` can be either a registered workspace name or a filesystem path.

## Local Models

Before `ingest` or `query`, make sure Ollama is running and the embedding model exists:

```bash
ollama pull nomic-embed-text
```

By default the CLI expects Ollama at:

```text
http://localhost:11434
```

Override this globally:

```bash
repo-intel config set embeddings.base_url http://192.168.1.12:11434
repo-intel config set llm.base_url http://192.168.1.12:11434
repo-intel config set embeddings.model nomic-embed-text:latest
repo-intel config set llm.model qwen2.5:3b
```

Or override per workspace in `.repo-intel/config.toml`.

Configuration precedence:

```text
built-in defaults
  < ~/.repo-intel/config.toml
  < <workspace>/.repo-intel/config.toml
  < REPO_INTEL_* environment variables
```

Useful validation:

```bash
repo-intel config show
repo-intel config show --workspace proxima
repo-intel config doctor
repo-intel config doctor --workspace proxima
```

## OpenRouter

OpenRouter is optional and used only by features configured for it, such as richer brief generation.

```bash
repo-intel config env set OPENROUTER_API_KEY sk-...
```

Secrets are stored locally in:

```text
~/.repo-intel/.env
```

## NotebookLM Sync

NotebookLM support is optional and uses the unofficial `notebooklm-py` CLI as an upload adapter.
`repo-intel` remains the source of truth; NotebookLM receives generated Markdown bundles only.

Install the optional uploader:

```bash
uv sync --extra notebooklm
uv run playwright install chromium
uv run notebooklm login
```

Then generate and upload optimized sources:

```bash
uv run repo-intel notebooklm generate-sources proxima
uv run repo-intel notebooklm init proxima
uv run repo-intel notebooklm sync proxima
```

Local NotebookLM state is stored per workspace:

```text
.repo-intel/notebooklm/
  manifest.json
  sources/
```
