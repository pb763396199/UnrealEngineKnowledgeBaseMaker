# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**UE5 Knowledge Base Maker** is a universal tool that generates knowledge bases and Claude Skills for Unreal Engine 5 codebases. It supports two modes:
- **Engine Mode**: Scans entire UE5 engine (1757+ modules including Source, Plugins, Platforms)
- **Plugin Mode**: Scans individual UE5 plugins for focused analysis

The tool parses `.Build.cs` files to extract module dependencies, scans C++ source code to build class/function graphs, and generates Claude Code Skills that enable AI-assisted code exploration.

## Development Commands

### Installation
```bash
# Install in editable mode
pip install -e .

# Reinstall after code changes
pip install -e . --force-reinstall --no-deps
```

### Running the CLI
```bash
# Show help
ue5kb --help
ue5kb init --help

# Engine mode - scan entire UE5 engine
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# Plugin mode - scan single plugin
ue5kb init --plugin-path "F:\MyProject\Plugins\MyPlugin"

# With custom output paths
ue5kb init --engine-path "D:\UE5.1" --kb-path "J:/CustomKB" --skill-path "J:/Skills"

# Direct module execution (for debugging)
python -m ue5_kb.cli init --engine-path "D:\Unreal Engine\UnrealEngine51_500"
```

### Testing
```bash
# Test version detection
python test_init.py

# Test full initialization flow
python test_full_init.py

# Test BuildCS parser
python test_scan_buildcs.py
```

### Code Formatting
```bash
# Format code (Black configured for 120 line length)
black ue5_kb/
```

## Architecture

### Data Flow

```
UE5 Engine/Plugin Source Code
    ↓
[1] BuildCS Parser → Parse .Build.cs files
    ↓
[2] Global Index Builder → Module metadata, dependencies, stats
    ↓ (saved to SQLite + Pickle)
Global Index (global_index/)
    ↓
[3] Module Graph Builder → Parse C++ files for each module
    ↓ (saved to individual Pickle files)
Module Graphs (module_graphs/*.pkl)
    ↓
[4] Skill Generator → Create Claude Code Skill
    ↓
Claude Skill (~/.claude/skills/ue5kb-{version}/)
```

### Core Components

**1. CLI Layer (`cli.py`)**
- Entry point for all commands
- Handles dual-mode routing (engine vs plugin)
- Auto-detects engine/plugin version from Build.version or .uplugin files
- Generates skill files from templates

**2. Parsers (`parsers/`)**
- `buildcs_parser.py`: Extracts dependencies from `.Build.cs` files using regex
- `cpp_parser.py`: Extracts classes, functions, inheritance from C++ headers/source

**3. Builders (`builders/`)**
- `global_index_builder.py`: Scans all modules, builds dependency graph (Engine mode)
- `plugin_index_builder.py`: Scans plugin modules (Plugin mode)
- `module_graph_builder.py`: Builds detailed code graphs per module (classes, functions, inheritance)

**4. Core (`core/`)**
- `config.py`: Configuration management with dynamic base_path support
- `global_index.py`: In-memory global module index with NetworkX dependency graph
- `optimized_index.py`: SQLite-backed storage (36x faster than pickle-only)
- `module_graph.py`: Per-module code relationship graph (classes, methods, inheritance)
- `function_index.py`: SQLite function index with parameter parsing for fast queries

**5. Query Layer (`query/`)** - Context Optimization
- `layered_query.py`: Three-tier query system (summary/details/source) for token efficiency
- `result_cache.py`: Observation masking for large results (stores full results, returns summaries)
- `token_budget.py`: Explicit token budget tracking and optimization triggers

**6. Analyzers (`analyzers/`)**
- `call_analyzer.py`: Analyzes function call patterns
- `example_extractor.py`: Extracts usage examples from code

### Storage Architecture

**Global Index** (`global_index/`)
```
index.db              # SQLite: module metadata, fast queries
global_index.pkl      # Pickle: complete data structure (fallback)
global_index.json     # JSON: human-readable export
```

**Module Graphs** (`module_graphs/`)
```
Core.pkl              # Pickle: class/function graph for Core module
Engine.pkl            # Pickle: class/function graph for Engine module
... (1757+ files)     # One per module
```

**Config** (`config.yaml`)
- Created automatically on first run
- Stores base_path, build settings, module categories

### Module Classification

Engine modules are auto-categorized from path:
- `Runtime`, `Editor`, `Developer`, `Programs` - from `Engine/Source/{Category}/`
- `Plugins.{Type}.{Name}` - from `Engine/Plugins/{Type}/{Name}/`
- `Platforms.{OS}` - from `Engine/Platforms/{OS}/`
- `Plugin.{Name}` - for standalone plugin mode

### Generated Skill Structure

Skills are created at `~/.claude/skills/{skill-name}/`:
```
skill.md         # Skill definition (when to use, capabilities)
impl.py          # Implementation with query functions:
                 # - query_module_dependencies()
                 # - search_modules()
                 # - query_class_info() / query_class_hierarchy()
                 # - query_function_info()
                 # - search_classes()
```

The `impl.py` hardcodes the KB_PATH pointing to the knowledge base location.

## Key Design Patterns

### Path Handling
- All internal paths use `pathlib.Path` for cross-platform compatibility
- `.rglob('**/*.Build.cs')` used for recursive module discovery
- Windows path separators handled automatically

### Module Discovery Strategy
1. Recursively find all `.Build.cs` files using Path.rglob()
2. Extract module name from filename (remove `.Build.cs` suffix)
3. Infer category from file path (Engine/Source/Runtime → "Runtime")
4. Parse dependencies using regex patterns
5. Build NetworkX graph of module relationships

### Performance Optimizations
- **SQLite Storage**: 36x faster queries vs pickle-only
- **LRU Cache**: Hot data queries < 1ms
- **Module Graph Caching**: Loaded on-demand, cached in memory
- **Context Optimization** (v2.2+):
  - Layered queries reduce token usage by 80-85%
  - Observation masking for large results (e.g., 100 results → 5 sample + ref_id)
  - Token budget tracking prevents context overflow

### Dual-Mode Support
- Engine mode: Scans `Engine/Source/`, `Engine/Plugins/`, `Engine/Platforms/`
- Plugin mode: Scans `Plugin/Source/**`, reads `.uplugin` for metadata
- Shared builders and parsers with mode-specific configuration

## Context Optimization System

Based on Context Engineering principles (see `docs/CONTEXT_OPTIMIZATION.md`):

**Problem**: Raw queries can return 1000+ tokens for class info, causing context bloat.

**Solution**: Three-tier progressive disclosure:
1. **Summary** (~200 tokens): Key info + ref_id
2. **Details** (~1000 tokens): Full data using ref_id
3. **Source** (~5000 tokens): Raw C++ code

**Observation Masking**: Large result sets (e.g., 100 functions) return first 5 + ref_id, reducing tokens by 87%.

**Token Budget**: Explicit budget per category (system prompt, tools, results, history) with automatic optimization triggers.

## Important Technical Notes

### Version Detection Priority
1. `Engine/Build/Build.version` JSON file (most accurate)
2. Directory name parsing (e.g., `UnrealEngine51_500` → "5.1.500")
3. `.uplugin` file for plugins (VersionName or Version field)

### BuildCS Parsing Limitations
- Uses regex, not full C# parser
- Handles most common dependency patterns
- May miss complex conditional dependencies

### C++ Parsing Limitations
- Regex-based, not full C++ parser (no Clang AST)
- Focuses on class definitions, inheritance, method signatures
- May miss template specializations or macro-heavy code

### Skill Generation
- Templates in `templates/skill.md.template` and `templates/impl.py.template`
- Skill name format: `ue5kb-{version}` (engine) or `{plugin-name}-kb-{version}` (plugin)
- KB_PATH is hardcoded in generated impl.py (not dynamic lookup)

## Common Development Workflows

### Adding a New Query Function
1. Add function to `ue5_kb/core/global_index.py` or `module_graph.py`
2. Update `templates/impl.py.template` to expose it in the Skill
3. Test with existing knowledge base
4. Regenerate skill: `ue5kb init --engine-path ...`

### Updating Parser Logic
1. Modify `parsers/buildcs_parser.py` or `cpp_parser.py`
2. Test with `test_scan_buildcs.py` or specific test case
3. Rebuild knowledge base to see changes
4. Consider backward compatibility with existing pickles

### Debugging Knowledge Base Issues
1. Check `config.yaml` in KB directory for correct paths
2. Verify `.db` and `.pkl` files exist in `global_index/`
3. Use Python REPL to load GlobalIndex directly:
   ```python
   from ue5_kb.core.config import Config
   from ue5_kb.core.global_index import GlobalIndex
   cfg = Config(base_path="D:/UE5Engine/KnowledgeBase")
   idx = GlobalIndex(cfg)
   idx.load()
   print(idx.get_statistics())
   ```

### Supporting New UE5 Versions
- No code changes needed (version-agnostic design)
- Just run `ue5kb init --engine-path` with new engine path
- Tool auto-detects version and creates independent KB + Skill

## Dependencies

Core runtime:
- `pyyaml>=6.0` - Config file parsing
- `networkx>=3.0` - Dependency graph storage
- `click>=8.1.0` - CLI framework
- `rich>=13.0.0` - Terminal UI (console, prompts, tables)

Optional dev:
- `pytest>=7.0` - Testing
- `black>=23.0` - Code formatting
- `mypy>=1.0` - Type checking

## Python Version Support

- **Required**: Python 3.9+
- **Tested on**: 3.9, 3.10, 3.11, 3.12
- Uses `pathlib` (3.4+), f-strings (3.6+), type hints (3.9+ for modern syntax)
