## ADDED Requirements

### Requirement: Raw semantic query
The system SHALL expose a raw retrieval command over indexed SDD chunks.

#### Scenario: Query returns SDD chunks
- **WHEN** the user runs `repo-intel query <target> "<question>"`
- **THEN** the system prints matching chunks with repository, path, section, type, and distance metadata.

### Requirement: Human answer generation
The system SHALL answer questions using retrieved SDD context and configured local chat LLM settings.

#### Scenario: Ask cites sources
- **WHEN** the user runs `repo-intel ask <target> "<question>"`
- **THEN** the system prints a synthesized answer and a source table.

### Requirement: Hybrid answer context
The system SHALL combine semantic retrieval with deterministic lexical/document signals for answer context selection.

#### Scenario: Technical topic is sparse in embeddings
- **WHEN** relevant SDD sections are discoverable through lexical metadata or chunk text
- **THEN** the answer engine can include those sections even if semantic retrieval alone is weak.

### Requirement: Safe ask cache
The system SHALL cache completed ask answers only when the normalized question, knowledge fingerprint, model provider, model, and context settings match.

#### Scenario: Repeated ask uses cache
- **WHEN** the user repeats an equivalent ask request without changing the indexed knowledge or model settings
- **THEN** the system returns the cached answer and marks the response as cached.
