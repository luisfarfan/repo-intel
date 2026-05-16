## Why

repo-intel has evolved from a single-workspace SDD ingestion CLI into a local engineering knowledge platform with workspace registry, retrieval, human-facing exports, and optional integrations. The project needs canonical OpenSpec documentation so future changes can be planned against explicit capabilities instead of chat history.

## What Changes

- Add OpenSpec documentation for the current repo-intel platform behavior.
- Define the core product capabilities as testable requirements.
- Capture the technical design decisions behind local-first storage, deterministic SDD ingestion, portable setup, answer caching, Obsidian, and NotebookLM sync.
- Add a completed task checklist for the documentation baseline.

## Capabilities

### New Capabilities
- `sdd-only-ingestion`: Discovers workspaces/repositories, reads only allowed SDD/AI documentation, chunks documents, and indexes knowledge locally.
- `workspace-platform-config`: Provides global CLI setup, workspace registry, configuration precedence, secrets, and diagnostics.
- `answer-retrieval-engine`: Supports raw semantic query, human answers, hybrid retrieval, source citations, and ask caching.
- `human-sync-integrations`: Exports repo-intel knowledge into human-facing surfaces such as Obsidian and NotebookLM.

### Modified Capabilities

None.

## Impact

- Adds `openspec/` project documentation and Codex OpenSpec command/skill metadata.
- Does not change runtime behavior, SQLite/Chroma storage, indexed knowledge, or workspace data.
