# human-sync-integrations Specification

## Purpose
Define how repo-intel projects its local knowledge into human-facing tools such as Obsidian, NotebookLM, and export bundles.
## Requirements
### Requirement: Obsidian cognitive layer
The system SHALL generate an Obsidian vault from existing repo-intel SQLite/artifact state without rescanning source repositories.

#### Scenario: Obsidian sync generates vault pages
- **WHEN** the user runs `repo-intel obsidian sync <target>`
- **THEN** the system writes dashboards, repository pages, topic pages, architecture maps, and system status pages into the configured vault.

### Requirement: NotebookLM source bundles
The system SHALL generate optimized Markdown bundles for NotebookLM from indexed repo-intel knowledge.

#### Scenario: NotebookLM source generation
- **WHEN** the user runs `repo-intel notebooklm generate-sources <target>`
- **THEN** the system writes project, repository, architecture, topic, and per-repository Markdown sources under the workspace NotebookLM source directory.

### Requirement: Optional NotebookLM upload
The system SHALL treat NotebookLM upload as an optional adapter over generated sources.

#### Scenario: NotebookLM CLI is unavailable
- **WHEN** NotebookLM sync is requested but the `notebooklm` CLI is not installed
- **THEN** the system reports the missing optional dependency without affecting core repo-intel memory.

### Requirement: Export bundles
The system SHALL export indexed SDD chunks as reusable Markdown and JSONL bundles for external tools.

#### Scenario: Export command writes bundles
- **WHEN** the user runs `repo-intel export <target>`
- **THEN** the workspace exports directory contains machine-readable and human-readable SDD context bundles.
