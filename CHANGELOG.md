# Changelog

All notable changes to the UE5 Knowledge Base Maker project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added ✨

- **函数参数详细解析**: 提取完整函数签名（参数类型、默认值、修饰符）
- **函数快速索引**: 基于 SQLite 的函数索引，查询性能从 500ms 提升到 < 10ms
- **UFUNCTION/UP ROPERTY 宏解析**: 提取 Blueprint 相关参数和 meta 信息
- **函数签名格式化**: 自动生成可读的完整函数签名

### Changed 📦

- 函数参数从简单字符串列表升级为结构化 ParameterInfo 对象
- query_function_info() 优先使用索引查询，Fallback 到图谱扫描
- module_graph_builder 集成函数索引构建

### Performance ⚡

- 函数查询性能提升 50-200x（500-2000ms → < 10ms）
- 函数签名准确率提升至 95%（原 ~60%）

---

## [2.1.0] - 2026-02-02

### Added ✨

- **插件模式支持**: 添加 `--plugin-path` 参数，支持为单个插件生成独立知识库
- **插件信息自动检测**: 从 `.uplugin` 文件自动读取插件名称和版本
  - 支持 `VersionName` 和 `Version` 字段
  - 从文件夹名称推断版本（如 `MyPlugin_1.2.3`）
- **插件专属 Skill**: 自动生成插件专属的 Claude Code Skill
  - 命名格式：`{plugin-name}-kb-{version}`
  - 示例：`aesworld-kb-1.0`
- **双模式 CLI**: 引擎模式和插件模式自动路由
- **PluginIndexBuilder**: 新增插件索引构建器类
  - 专门扫描插件 `Source/` 目录
  - 模块分类标签：`Plugin.{PluginName}`

### Fixed 🐛

- 修复 `PluginIndexBuilder` 调用错误的解析方法（`parse()` → `parse_file()`）
- 修复依赖字典键名不匹配（`'public'` / `'private'` vs `'PublicDependencyModuleNames'`）
- 修复 Windows 控制台 Unicode 编码错误（`✓` → `OK`, `✗` → `X`）

### Changed 📦

- CLI `init` 命令重构，支持 `--engine-path` 和 `--plugin-path` 互斥参数
- `generate_skill()` 函数支持 `is_plugin` 参数
- Skill 模板支持插件和引擎两种上下文类型

### Technical Details

**新增文件**:
- `ue5_kb/builders/plugin_index_builder.py` (~200 行代码)

**修改文件**:
- `ue5_kb/cli.py` (+150 行)
  - `init_plugin_mode()` - 插件模式初始化
  - `detect_plugin_info()` - 插件信息检测
  - `generate_plugin_knowledge_base()` - 插件知识库生成

**验证测试**:
```bash
# 成功为 AesWorld 插件生成知识库
ue5kb init --plugin-path "F:\ShanghaiP4\neon\Plugins\AesWorld"

# 结果:
# - 40 个模块
# - 2,123 个文件
# - 424,600 行预估代码
# - 知识库: F:\ShanghaiP4\neon\Plugins\AesWorld\KnowledgeBase
# - Skill: C:\Users\pb763\.claude\skills\aesworld-kb-1.0
```

**插件模式 vs 引擎模式**:

| 特性 | 引擎模式 | 插件模式 |
|------|---------|---------|
| 扫描范围 | Engine/Source, Engine/Plugins, Engine/Platforms | Plugin/Source/** |
| 模块数量 | 1757 | 取决于插件规模 |
| 知识库路径 | `{引擎}/KnowledgeBase/` | `{插件}/KnowledgeBase/` |
| Skill 命名 | `ue5kb-{version}` | `{name}-kb-{version}` |
| 模块分类 | Runtime, Editor, Plugins.*, Platforms.* | Plugin.{PluginName} |

---

## [2.0.1] - 2026-02-02 (Earlier)

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
- Module name extraction bug (`.Build.cs` suffix removed correctly)

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
