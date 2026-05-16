# workspace-platform-config Specification

## Purpose
Define how repo-intel behaves as a portable global CLI with workspace aliases, layered configuration, secrets, and diagnostics.
## Requirements
### Requirement: Named workspace registry
The system SHALL allow users to register workspace aliases that resolve to filesystem paths.

#### Scenario: Alias target resolves
- **WHEN** a user runs a command with a registered workspace name
- **THEN** the command operates on the registered workspace path.

### Requirement: Portable global setup
The system SHALL provide a global setup command that writes portable CLI defaults without assuming private infrastructure.

#### Scenario: Minimal setup writes defaults
- **WHEN** the user runs `repo-intel setup --preset minimal --non-interactive`
- **THEN** the global config uses portable defaults such as `http://localhost:11434`.

### Requirement: Effective config precedence
The system SHALL resolve effective configuration using built-in defaults, global config, workspace config, and environment overrides in that order.

#### Scenario: Workspace config overrides global config
- **WHEN** a workspace config defines an Ollama URL
- **THEN** commands targeting that workspace use the workspace URL.

### Requirement: Configuration diagnostics
The system SHALL provide diagnostics for config files, Ollama connectivity, configured models, OpenRouter secrets, and NotebookLM CLI availability.

#### Scenario: Doctor reports service status
- **WHEN** the user runs `repo-intel config doctor --workspace <name>`
- **THEN** the system prints pass, skipped, missing, or error status for each configured dependency.
