# Changelog

All notable changes to the UE5 Knowledge Base Maker project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Plugin module scanning support - now scans Engine/Plugins directory in addition to Engine/Source
- Plugin modules are tagged with `Plugins.{PluginType}.{PluginName}` category for easy identification
- Two-phase scanning: Engine/Source modules first, then Engine/Plugins modules
- Support for Marketplace plugins (e.g., BlueprintAssist_5.1, GraphPrinter_5.1)
- Smart plugin structure detection - handles both `Plugin/Source/Module/` and `Plugin/Module/` structures

### Changed
- Updated `global_index_builder.py` to support plugin directory structure
- Enhanced module discovery to handle both engine modules and plugin modules
- Updated README.md with plugin coverage documentation
- Added `_scan_directory_for_modules()` helper method for better code organization

### Fixed
- Plugin scanning now correctly handles the nested `Source/` directory structure
- Marketplace plugins (under `Plugins/Martketplace/`) are now properly discovered

## [2.0.0] - 2026-02-02

### Added
- Universal UE5 knowledge base generator supporting any engine version
- CLI with guided configuration using Click and Rich libraries
- Automatic engine version detection from Build.version file
- Automatic Claude Skill generation with correct paths
- Multi-engine support - can generate independent knowledge bases for multiple UE5 versions
- GlobalIndexBuilder integration for scanning engine source code
- SQLite-based storage with 36x performance improvement over pickle
- LRU cache for hot data queries (<1ms response time)
- Comprehensive test suite (test_init.py, test_full_init.py)

### Changed
- Refactored from J:/ue5-kb to portable tool structure
- Removed all hardcoded paths
- Config class now supports dynamic base_path initialization
- CLI commands now use --base-path parameter instead of hardcoded config

### Fixed
- Engine version detection now correctly reads from Build.version JSON file
- All hardcoded J:/ue5-kb paths removed from:
  - core/config.py
  - core/optimized_index.py
  - builders/global_index_builder.py
  - builders/module_graph_builder.py

### Technical Details
- **Package Name**: ue5-kb
- **Version**: 2.0.0
- **Python**: 3.9+
- **Dependencies**: click, rich, pyyaml, networkx
- **Storage**: SQLite (global index), NetworkX (module graphs), Pickle (backup)

### File Structure
```
J:/UE5_KnowledgeBaseMaker/
├── ue5_kb/                    # Core package
│   ├── __init__.py
│   ├── cli.py                 # CLI entry point
│   ├── core/                  # Core modules
│   ├── parsers/               # Parsers
│   └── builders/              # Builders
├── pyproject.toml             # Python package config
├── README.md                  # Documentation
├── CHANGELOG.md               # This file
└── test_*.py                  # Test scripts
```

### Usage Example
```bash
# Install
pip install -e .

# Generate knowledge base and skill for UE5.1.500
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# Results:
# - Knowledge Base: D:\Unreal Engine\UnrealEngine51_500\KnowledgeBase\
# - Skill: C:\Users\pb763\.claude\skills\ue5kb-5.1.1\
```

### Migration from v1.0.0
If you have existing data in J:/ue5-kb, you can migrate to the new format:
```bash
# The new tool will create knowledge bases in engine directories
# Old data remains in J:/ue5-kb for reference
```

[Unreleased]: https://github.com/yourusername/ue5-knowledgebase/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/yourusername/ue5-knowledgebase/releases/tag/v2.0.0
