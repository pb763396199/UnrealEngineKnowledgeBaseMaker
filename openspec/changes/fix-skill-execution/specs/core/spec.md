## ADDED Requirements

### Requirement: CLI Query Interface
The generated Skill SHALL provide a command-line interface for querying the knowledge base.

#### Scenario: Query class info via CLI
- **GIVEN** a generated Skill with impl.py
- **WHEN** user runs `python impl.py query_class_info AActor`
- **THEN** it SHALL output valid JSON with class information

#### Scenario: Query module dependencies via CLI
- **GIVEN** a generated Skill with impl.py
- **WHEN** user runs `python impl.py query_module_dependencies Core`
- **THEN** it SHALL output valid JSON with dependency information

#### Scenario: Error handling
- **GIVEN** a generated Skill with impl.py
- **WHEN** user runs `python impl.py query_class_info NonExistentClass`
- **THEN** it SHALL output JSON with an `error` field

#### Scenario: Missing arguments
- **GIVEN** a generated Skill with impl.py
- **WHEN** user runs `python impl.py query_class_info` (without class name)
- **THEN** it SHALL print usage message to stderr and exit with code 1

### Requirement: Skill Documentation
The generated Skill SHALL provide clear instructions on how to use the CLI interface.

#### Scenario: Skill activation
- **GIVEN** a generated Skill with skill.md
- **WHEN** Claude Code reads the skill.md
- **THEN** it SHALL understand to use `python impl.py <command>` for queries
- **AND** it SHALL NOT use Glob/Grep for code queries

#### Scenario: Command reference
- **GIVEN** a generated Skill with skill.md
- **WHEN** viewing the available commands section
- **THEN** all supported CLI commands SHALL be documented with usage examples
