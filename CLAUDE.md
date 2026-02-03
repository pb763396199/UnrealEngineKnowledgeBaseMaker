# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**UE5 Knowledge Base Maker** (v2.5.0) is a universal tool that generates knowledge bases and Claude Skills for Unreal Engine 5 codebases.

**Two Modes**:
- **Engine Mode**: Scans entire UE5 engine (1757+ modules)
- **Plugin Mode**: Scans individual UE5 plugins

**What it does**: Parses `.Build.cs` files → extracts module dependencies → scans C++ code → generates Claude Skills for AI-assisted code exploration.

---

## Development Commands

### Installation
```bash
pip install -e .
pip install -e . --force-reinstall --no-deps  # After code changes
```

### CLI Usage
```bash
# Engine mode
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# Plugin mode
ue5kb init --plugin-path "F:\MyProject\Plugins\MyPlugin"

# Direct execution (debugging)
python -m ue5_kb.cli init --engine-path "..."
```

### Code Formatting
```bash
black ue5_kb/  # 120 line length
```

---

## Architecture (v2.5.0 - Pipeline System)

### Pipeline Stages

```
[1] Discover  → Find .Build.cs files → module_list
      ↓
[2] Extract   → Parse metadata → dependencies, classes, functions
      ↓
[3] Analyze   → Code relationships → call graphs, examples (Phase 2)
      ↓
[4] Build     → SQLite + Pickle → indices
      ↓
[5] Generate  → Claude Skills
```

### Pipeline Components

| Component | File | Purpose |
|-----------|------|---------|
| **PipelineCoordinator** | `pipeline/coordinator.py` | Orchestrates pipeline, manages state |
| **DiscoverStage** | `pipeline/discover.py` | Discovers all .Build.cs files |
| **ExtractStage** | `pipeline/extract.py` | Parses Build.cs and C++ headers |
| **AnalyzeStage** | `pipeline/analyze.py` | Calls analyzers (call graphs, examples) |
| **BuildStage** | `pipeline/build.py` | Builds SQLite and Pickle indices |
| **GenerateStage** | `pipeline/generate.py` | Generates Claude Skills |
| **PartitionedBuilder** | `builders/partitioned_builder.py` | Multi-agent partitioned builds for large engines |

### Using the Pipeline

```python
from ue5_kb.pipeline.coordinator import PipelineCoordinator

coordinator = PipelineCoordinator(engine_path)

# Run complete pipeline
results = coordinator.run_all()

# Run specific stage
result = coordinator.run_stage('extract', force=True)

# Check state
state = coordinator.state
print(state.completed_stages)  # ['discover', 'extract', ...]
```

### Phase 2: Analyzers Framework

| Analyzer | File | Purpose |
|----------|------|---------|
| **CallAnalyzer** | `analyzers/call_analyzer.py` | Function call relationships |
| **ExampleExtractor** | `analyzers/example_extractor.py` | Usage examples from code |

### Query System (`ue5_kb/query/`)

| Module | File | Purpose |
|--------|------|---------|
| **LayeredQueryInterface** | `layered_query.py` | Progressive disclosure queries (summary → details → source) |
| **ResultCache** | `result_cache.py` | LRU caching and observation masking |
| **TokenBudget** | `token_budget.py` | Token budget tracking per category |

---

## Storage & Output

### Knowledge Base Structure
```
{Engine}/
├── data/                     # Pipeline working data
│   ├── discover/             # modules.json (found modules)
│   ├── extract/              # per-module dependencies
│   ├── analyze/              # per-module code graphs
│   ├── build/                # build outputs
│   └── generate/             # skill_generated.txt
├── .pipeline_state           # Pipeline state (hidden file)
└── KnowledgeBase/            # Final outputs
    ├── global_index/
    │   ├── index.db              # SQLite: fast queries
    │   ├── global_index.pkl      # Pickle: complete data
    │   └── global_index.json     # JSON: human-readable
    └── module_graphs/
        ├── Core.pkl              # Per-module code graphs
        ├── Engine.pkl
        └── ... (1757+ files)
```

### Generated Skills
```
~/.claude/skills/{skill-name}/
├── skill.md     # Skill definition
└── impl.py      # Query functions (hardcoded KB_PATH)
```

---

## Context Optimization

**Problem**: Raw queries return 1000+ tokens, causing context bloat.

**Solution**: Three-tier progressive disclosure:
1. **Summary** (~200 tokens): Key info + ref_id
2. **Details** (~1000 tokens): Full data using ref_id
3. **Source** (~5000 tokens): Raw C++ code

**Observation Masking**: Large results return first 5 + ref_id (87% token reduction).

**Token Budget**: Explicit budget tracking per category.

See `docs/CONTEXT_OPTIMIZATION.md` for details.

---

## Key Design Patterns

### Path Handling
- Use `pathlib.Path` for cross-platform compatibility
- `.rglob('**/*.Build.cs')` for recursive discovery

### Performance
- **SQLite Storage**: 36x faster than pickle-only
- **LRU Cache**: Hot data queries <1ms
- **Context Optimization**: 80-85% token reduction

### Module Classification
Auto-categorized from path:
- `Runtime`, `Editor`, `Developer`, `Programs` → `Engine/Source/{Category}/`
- `Plugins.{Type}.{Name}` → `Engine/Plugins/{Type}/{Name}/`
- `Platforms.{OS}` → `Engine/Platforms/{OS}/`
- `Plugin.{Name}` → Plugin mode

---

## Technical Notes

### Version Detection
1. `Engine/Build/Build.version` JSON (most accurate)
2. Directory name (`UnrealEngine51_500` → "5.1.500")
3. `.uplugin` file for plugins

### Parsing Limitations
- **Build.cs**: Regex-based (not full C# parser)
- **C++**: Regex-based, focuses on class/function signatures
- May miss complex templates or macro-heavy code

### Skill Generation
- Templates: `templates/skill.md.template`, `templates/impl.py.template`
- Skill format: `ue5kb-{version}` (engine) or `{plugin-name}-kb-{version}` (plugin)
- KB_PATH is hardcoded in generated impl.py

### Latest Fixes (v2.5.0)
- **C++ Parser**: Fixed regex for UE5 style (`class MYPROJECT_API AMyActor`)
- **Empty Module Graphs**: Fixed C++ parser to properly extract class info
- **Pipeline Integration**: CLI now uses PipelineCoordinator

---

## Common Workflows

### Adding a Query Function
1. Add function to `ue5_kb/core/global_index.py` or `module_graph.py`
2. Update `templates/impl.py.template`
3. Test with existing KB
4. Regenerate skill: `ue5kb init --engine-path ...`

### Debugging KB Issues
```python
from ue5_kb.core.config import Config
from ue5_kb.core.global_index import GlobalIndex

cfg = Config(base_path="D:/UE5Engine/KnowledgeBase")
idx = GlobalIndex(cfg)
idx.load()
print(idx.get_statistics())
```

### Pipeline Development
- Add stage: Inherit from `PipelineStage`, implement `execute()`
- Register in `PipelineCoordinator`
- State automatically persisted to `pipeline_state.json`

---

## Dependencies

**Core**: `pyyaml>=6.0`, `networkx>=3.0`, `click>=8.1.0`, `rich>=13.0.0`
**Dev**: `pytest>=7.0`, `black>=23.0`, `mypy>=1.0`

---

## Python Version

**Required**: 3.9+ | **Tested**: 3.9, 3.10, 3.11, 3.12

Uses `pathlib` (3.4+), f-strings (3.6+), type hints (3.9+).

---

## Getting Help

For complex tasks, use project Skill: `/ue5kb-dev-guide`

For detailed Context Optimization: `docs/CONTEXT_OPTIMIZATION.md`

For OpenSpec workflow: `openspec/AGENTS.md`
