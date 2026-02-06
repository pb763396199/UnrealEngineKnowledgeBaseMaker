# Spec Delta: CLI Interface - Auto-Detection

## ADDED Requirements

### Requirement: Auto-Detection from Current Working Directory
The CLI SHALL automatically detect whether the current working directory is a UE5 engine or plugin when no explicit path is provided.

#### Scenario: Auto-detect plugin directory
- **GIVEN** user is in a UE5 plugin directory (contains .uplugin file)
- **WHEN** user runs `ue5kb init` without any path arguments
- **THEN** the tool SHALL detect plugin mode
- **AND** SHALL use the current directory as the plugin path
- **AND** SHALL display detection results to the user

#### Scenario: Auto-detect engine root directory
- **GIVEN** user is in a UE5 engine root directory (contains Engine/Build/Build.version)
- **WHEN** user runs `ue5kb init` without any path arguments
- **THEN** the tool SHALL detect engine mode
- **AND** SHALL use the current directory as the engine path
- **AND** SHALL display detection results to the user

#### Scenario: Auto-detect from engine subdirectory
- **GIVEN** user is in a subdirectory of a UE5 engine (e.g., Engine/Source)
- **WHEN** user runs `ue5kb init` without any path arguments
- **THEN** the tool SHALL detect engine mode by traversing parent directories
- **AND** SHALL use the detected engine root path
- **AND** SHALL display detection results indicating subdirectory detection

#### Scenario: Auto-detection failure
- **GIVEN** user is in a directory that is neither a UE5 engine nor plugin
- **WHEN** user runs `ue5kb init` without any path arguments
- **THEN** the tool SHALL display a clear error message
- **AND** SHALL provide examples of how to manually specify paths
- **AND** SHALL NOT proceed with initialization

#### Scenario: Explicit path parameter overrides auto-detection
- **GIVEN** user is in any directory
- **WHEN** user runs `ue5kb init --engine-path "path/to/engine"` or `--plugin-path "path/to/plugin"`
- **THEN** the tool SHALL skip auto-detection
- **AND** SHALL use the explicitly provided path

#### Scenario: Parent directory traversal limit
- **GIVEN** user is in a deeply nested directory
- **WHEN** the tool searches parent directories for engine markers
- **THEN** the tool SHALL limit traversal to 5 directory levels
- **AND** SHALL report detection failure if engine is not found within limit

### Requirement: Detection Priority
The auto-detection SHALL follow a specific priority order to determine the mode.

#### Scenario: Plugin takes priority over engine
- **GIVEN** a directory contains both .uplugin file and Engine/Build/Build.version
- **WHEN** auto-detection runs
- **THEN** the tool SHALL prefer plugin mode
- **AND** SHALL report "high confidence" for the detection

### Requirement: Backward Compatibility
The auto-detection feature SHALL NOT break existing functionality.

#### Scenario: Explicit parameters still work
- **GIVEN** user provides `--engine-path` or `--plugin-path`
- **WHEN** the init command runs
- **THEN** auto-detection SHALL be skipped
- **AND** the provided path SHALL be used

#### Scenario: Both parameters still rejected
- **GIVEN** user provides both `--engine-path` and `--plugin-path`
- **WHEN** the init command runs
- **THEN** the tool SHALL display an error
- **AND** SHALL NOT perform auto-detection

---

# Implementation Notes

## Detection Algorithm

```
1. Check current directory for *.uplugin files
   → Found: Return plugin mode (high confidence)

2. Check current directory for Engine/Build/Build.version
   → Found: Return engine mode (high confidence)

3. Check parent directories (up to 5 levels) for Engine/Build/Build.version
   → Found: Return engine_subdir mode (medium confidence)

4. Nothing found
   → Return unknown mode (low confidence)
```

## Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `ue5_kb/utils/auto_detect.py` | NEW | Detection logic module |
| `ue5_kb/cli.py` | MODIFIED | Update init command (lines 68-71, 142-157) |
| `ue5_kb/utils/__init__.py` | MODIFIED | Add exports |

## Testing Commands

```bash
# Plugin detection
cd /path/to/Plugin && ue5kb init

# Engine detection
cd /path/to/UE5 && ue5kb init

# Subdirectory detection
cd /path/to/UE5/Engine/Source && ue5kb init

# Explicit path (override)
cd /random/path && ue5kb init --engine-path /path/to/UE5
```
