# Changelog

All notable changes to the UE5 Knowledge Base Maker project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Unified module scanning - now recursively searches all .Build.cs files in Engine directory
- Automatic category detection from .Build.cs file path
- Support for Engine/Platforms modules in addition to Source and Plugins
- Platform modules tagged with `Platforms.{PlatformName}` category
- Module graph building for all discovered modules (1757+ modules)
- Enhanced Skill generation with code-level query capabilities
- Skill template system (templates/skill.md.template, impl.py.template)
- Code-level query functions: query_class_info, query_class_hierarchy, search_classes, etc.
- Module graph caching for performance optimization

### Changed
- Simplified scanning logic - single pass search for all .Build.cs files using Path.rglob()
- Removed complex directory traversal in favor of file-based discovery
- More reliable module discovery that handles any directory structure
- Skill generation now uses external template files for easier customization
- Enhanced impl.py with module graph caching and code-level queries

### Fixed
- All modules now discovered regardless of directory nesting
- Plugin modules with non-standard structures are now found
- Platform modules (Windows, Linux, Android, etc.) are now included
- Windows path separator compatibility using pathlib.Path.rglob()
- Module graphs are now properly generated for all modules
- Skill now fully utilizes both global_index and module_graphs data

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
