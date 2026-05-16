## Context

repo-intel is a Python 3.12+ Typer CLI for SDD-only engineering knowledge. It intentionally avoids reading source implementation files and treats AI/SDD documentation as the source of truth. Each workspace owns its own `.repo-intel/` memory: SQLite metadata, Chroma vectors, artifacts, exports, briefs, Obsidian vault, and NotebookLM manifest. Global state is limited to CLI defaults, secrets, and workspace aliases under `~/.repo-intel/`.

## Goals / Non-Goals

**Goals:**
- Document the platform as reusable capabilities that future agents can reason about.
- Keep the specs aligned with the current architecture: deterministic-first ingestion, local-first memory, optional integrations.
- Preserve implementation decisions that matter for future changes.

**Non-Goals:**
- Do not redesign the CLI or storage model.
- Do not introduce a hosted service, global vector store, or source-code analysis.
- Do not make NotebookLM, OpenRouter, or Obsidian mandatory dependencies.

## Decisions

- **SDD-only source boundary:** repo-intel SHALL ingest documentation from allowlisted SDD/AI paths and exclude source/build/test/vendor folders. This keeps trust, cost, and scope predictable.
- **Workspace-isolated memory:** SQLite and Chroma remain inside each workspace. Global config provides defaults only; it does not centralize project memory.
- **Config precedence:** built-in defaults are overridden by global config, then workspace config, then `REPO_INTEL_*` environment variables. This supports portable installs and project-specific overrides.
- **Retrieval pipeline ownership:** repo-intel owns parsing, chunking, metadata, retrieval, and answer assembly. LlamaIndex remains optional future adapter territory, not a core dependency path.
- **External surfaces as projections:** Obsidian and NotebookLM consume generated repo-intel knowledge. They do not replace SQLite, Chroma, or the local ask/query flow.

## Risks / Trade-offs

- **Unofficial NotebookLM dependency** -> Keep it optional and manifest-driven so failures do not affect core query/ask.
- **Docs can drift from implementation** -> Use OpenSpec as the planning baseline and update specs when platform behavior changes.
- **Workspace configs may retain private URLs** -> Built-in defaults stay portable; private infrastructure belongs only in user/global/workspace config.

## Migration Plan

- Initialize OpenSpec for Codex.
- Add baseline change artifacts for current capabilities.
- Validate and archive the change so canonical specs exist under `openspec/specs/`.
- Future feature work should start with a new OpenSpec change.
