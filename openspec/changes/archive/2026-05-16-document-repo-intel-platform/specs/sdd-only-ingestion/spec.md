## ADDED Requirements

### Requirement: Documentation-only discovery
The system SHALL discover repositories in a workspace and ingest only allowlisted SDD/AI documentation files.

#### Scenario: Allowed documentation is discovered
- **WHEN** the user runs `repo-intel scan <target>` for a workspace
- **THEN** the system reports repositories and SDD/AI documents from configured include patterns.

#### Scenario: Source implementation files are excluded
- **WHEN** the workspace contains source, test, build, vendor, virtualenv, or generated folders
- **THEN** the system MUST exclude those files from SDD ingestion.

### Requirement: Deterministic metadata and chunking
The system SHALL parse allowed documents deterministically into document records and semantic chunks with metadata.

#### Scenario: Ingestion stores chunk metadata
- **WHEN** the user runs `repo-intel ingest <target>`
- **THEN** SQLite contains repositories, documents, chunks, ingestion runs, and embedding records for the workspace.

### Requirement: Local vector projection
The system SHALL create embeddings through the configured embedding provider and store vectors in the workspace Chroma collection.

#### Scenario: Chroma is indexed from chunks
- **WHEN** embeddings are generated successfully for semantic chunks
- **THEN** the workspace Chroma store contains vector records keyed to chunk identifiers.
