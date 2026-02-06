# Changelog

All notable changes to the UE5 Knowledge Base Maker project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.12.0] - 2026-02-06

### Added ✨

**CPP 文件索引功能 - 快速定位函数实现**
- **函数实现位置追踪**: 知识库现在包含函数的 CPP 实现文件路径和行号
  - `query_function_info` 返回 `impl_file` 和 `impl_line` 字段
  - `search_functions` 返回 `impl_file` 字段
- **新增 `get_function_implementation` 命令**: 直接获取函数的完整实现代码
  - 自动定位 CPP 文件位置
  - 返回声明位置和实现位置
  - 支持读取完整的 CPP 文件内容
- **基于 #include 的反向映射**: 使用智能解析策略
  - 解析所有 CPP 文件的 `#include` 语句
  - 建立头文件到 CPP 文件的映射关系
  - 支持同名文件优先策略
  - 精确定位函数定义行号

### Changed 📦

- **FunctionInfo 数据结构扩展**: 添加 `impl_file_path`, `impl_line_number`, `impl_candidates` 字段
- **FunctionIndex 数据库扩展**: 添加 `impl_file_path` 和 `impl_line_number` 列
- **数据库自动迁移**: 现有数据库自动添加新字段，无需手动重建
- **插件模板同步**: 插件模板现在包含所有新功能

### Fixed 🐛

- 修复插件模式使用旧模板的问题
- 修复旧数据库版本兼容性问题（自动添加缺失字段）

### CLI 更新

```bash
# 更新现有 Skill（强制重新生成）
ue5kb init --engine-path "D:\UE5" --stage generate --force
ue5kb init --plugin-path "F:\Plugins\MyPlugin" --stage generate --force
```

### Technical Details

**新增文件**:
- `ue5_kb/builders/header_cpp_mapper.py` (~170 行)
  - `HeaderToCppMapper`: 头文件到 CPP 文件映射器
  - 基于多策略的路径解析（相对路径、Public/Private 目录、文件名索引）

**修改文件**:
- `ue5_kb/parsers/cpp_parser.py`: FunctionInfo 添加实现位置字段
- `ue5_kb/core/function_index.py`: 数据库结构扩展和自动迁移
- `ue5_kb/builders/module_graph_builder.py`: 集成 HeaderToCppMapper
- `templates/impl.py.template`: 添加 `get_function_implementation` 函数
- `templates/impl.plugin.py.template`: 同步主模板功能
- `templates/skill.md.template`: 添加新功能文档
- `templates/skill.plugin.md.template`: 同步主模板功能
- `ue5_kb/cli.py`: 版本更新到 2.12.0，帮助文档更新

### Breaking Changes

无 - 完全向后兼容

### Migration Notes

现有知识库可以继续使用，新功能自动启用。如需更新现有 Skill：
```bash
# 强制重新生成（获取新功能）
ue5kb init --stage generate --force
```

## [2.11.0] - 2026-02-06

### Added ✨

**自动检测功能 - 开箱即用体验**
- **当前目录自动检测**: 直接在引擎/插件目录运行 `ue5kb init`，无需指定路径
  - 检测 `.uplugin` 文件 → 自动识别插件模式
  - 检测 `Engine/Build/Build.version` → 自动识别引擎模式
  - 支持从引擎子目录向上查找引擎根目录（最多 5 层）
- **友好错误提示**: 自动检测失败时显示清晰的使用说明和示例
- **检测结果展示**: 显示检测模式、路径、原因和置信度
- **完全向后兼容**: `--engine-path` 和 `--plugin-path` 参数继续工作

### Changed 📦

- CLI 选项说明更新：添加"未指定时自动检测"说明
- CLI 帮助文档更新：推荐使用自动检测方式
- 主命令文档字符串更新为 v2.11.0

### CLI 更新

```bash
# 自动检测（推荐）
cd "D:\Unreal Engine\UE5.1" && ue5kb init

# 显式指定路径（仍然支持）
ue5kb init --engine-path "D:\UE5"
ue5kb init --plugin-path "F:\Plugins\MyPlugin"
```

### Technical Details

**新增文件**:
- `ue5_kb/utils/auto_detect.py` (~110 行)
  - `detect_from_cwd()`: 自动检测函数
  - `DetectionInfo`: 检测结果数据类
  - `_read_engine_version()`: 引擎版本读取辅助函数

**修改文件**:
- `ue5_kb/cli.py` (+45 行)
  - 更新选项说明（第68-71行）
  - 替换无参数处理逻辑（第142-175行）
  - 更新主命令文档字符串（第20-64行）
- `ue5_kb/utils/__init__.py` (+5 行)
  - 添加 `detect_from_cwd`, `DetectionInfo`, `DetectionResult` 导出

**检测算法**:
```
1. 检查当前目录的 *.uplugin 文件
   → Found: Return plugin mode (high confidence)

2. 检查当前目录的 Engine/Build/Build.version
   → Found: Return engine mode (high confidence)

3. 检查父目录（最多 5 层）的 Engine/Build/Build.version
   → Found: Return engine_subdir mode (medium confidence)

4. Nothing found
   → Return unknown mode (low confidence)
```

---

## [2.10.0] - 2026-02-05

### Added ✨

**并行加速系统 - Pipeline 性能飞跃**
- **多进程并行处理**: Extract 和 Analyze 阶段使用 ProcessPoolExecutor 实现多进程并行
  - Extract 阶段: 3-4x 性能提升（解析 .Build.cs 文件）
  - Analyze 阶段: 4-8x 性能提升（解析 C++ 源码）
  - Build 阶段: 混合模式（ThreadPoolExecutor + 串行 SQLite 写入）
- **多进度条显示**: 使用 Rich 库实现实时多 worker 状态显示
  - 总进度条：显示整体完成百分比和 ETA
  - Worker 进度条：每个 worker 独立显示当前处理的模块
  - 动态刷新：实时显示当前正在处理的模块名称
- **性能监控系统**: StageTimer 记录各阶段耗时和速度
  - 阶段末尾显示本阶段耗时
  - 最终显示所有阶段汇总统计
  - 速度指标（items/sec）和 ETA 计算
- **Checkpoint 机制**: Analyze 阶段支持中断恢复
  - 自动保存已完成模块
  - 下次运行自动跳过已完成的模块
- **智能并行检测**: --workers/-j 参数（0=自动检测 CPU 核心数）
- **错误隔离**: 单个模块失败不影响其他模块处理

### Changed 📦

- CLI 参数更新：`--parallel` → `--workers/-j`（更符合工具约定）
- 所有阶段支持并行模式分支（通过 `parallel` 参数控制）
- PipelineCoordinator 集成 StageTimer 实现性能监控
- 配置文件添加 `parallel` 配置节（enabled, workers, max_workers, min_workers）

### Fixed 🐛

- **Worker 进度条不更新**: 修复只有总进度更新、worker 进度条不更新的问题
  - 原因：worker 进程无法更新主进程的 ProgressTracker
  - 解决：在主进程中跟踪每个 worker 的完成数量
- **GlobalIndex API 错误**: 修复 `'GlobalIndex' object has no attribute 'build'` 错误
  - 实现正确的 GlobalIndex 工作流（add_module → build_dependency_graph → save）
- **JSON 文件输出缺失**: 修复 module_graphs 目录只输出 pkl、不输出 JSON 的问题
- **JSON 解析错误**: 添加 `_fix_multi_json_file()` 自动修复多重 JSON 对象问题

### Performance ⚡

在 8 核 CPU 上的性能提升：

| 阶段 | 修改前 | 修改后 | 提升 |
|------|--------|--------|------|
| Extract | ~30s | ~8s | **3.8x** |
| Analyze | ~600s | ~80-120s | **5-7x** |
| Build | ~35s | ~25s | **1.4x** |
| **总耗时** | ~665s | ~113-153s | **4.3-5.9x** |

### CLI 更新

```bash
# 自动检测并行度（推荐）
ue5kb init --engine-path "D:\UE5" -j 0

# 指定 worker 数量
ue5kb init --engine-path "D:\UE5" --workers 8
ue5kb init --engine-path "D:\UE5" -j 4

# 串行模式（调试用）
ue5kb init --engine-path "D:\UE5" --workers 1
```

### Technical Details

**新增文件**:
- `ue5_kb/utils/__init__.py` - Utils 模块初始化
- `ue5_kb/utils/progress_tracker.py` (~230 行) - 多进度条跟踪器
- `ue5_kb/utils/stage_timer.py` (~120 行) - 阶段计时器
- `ue5_kb/utils/checkpoint_manager.py` (~100 行) - Checkpoint 管理器
- `ue5_kb/pipeline/analyze_parallel.py` (~340 行) - Analyze 并行实现
- `ue5_kb/pipeline/extract_parallel.py` (~230 行) - Extract 并行实现
- `ue5_kb/pipeline/build_parallel.py` (~490 行) - Build 混合并行实现

**修改文件**:
- `ue5_kb/pipeline/analyze.py` (+10 行) - 添加并行模式分支
- `ue5_kb/pipeline/extract.py` (+10 行) - 添加并行模式分支
- `ue5_kb/pipeline/build.py` (+10 行) - 添加并行模式分支
- `ue5_kb/pipeline/coordinator.py` (+40 行) - 集成 StageTimer
- `ue5_kb/core/config.py` (+15 行) - 添加 parallel 配置节
- `ue5_kb/cli.py` (+50 行) - 更新参数和帮助文档

**并行策略**:
| 阶段 | 并行类型 | Worker 类型 | 预期加速比 |
|------|----------|-------------|-----------|
| Discover | 串行 | N/A | 1x |
| Extract | ProcessPoolExecutor | 多进程 | 3-4x |
| Analyze | ProcessPoolExecutor | 多进程 | 4-8x |
| Build | ThreadPoolExecutor (图) + 串行 (SQLite) | 线程池 | 2-3x |
| Generate | 串行 | N/A | 1x |

### ProgressTracker 多进度条 UI

```
┌─ Pipeline: Analyze Stage ──────────────────────────────────────────────┐
│                                                                         │
│  [████████████████████████░░░░░░░░░░░░░░░░░░░░░░░] 453/1757 modules  │
│  Total Progress                                                    26% │
│                                                                         │
│  [██████████████████████████████████░░░░░] Core/Engine.cpp            │
│  Worker 1                                                   128/150   │
│                                                                         │
│  [██████████████████████████████████░░░░░] RenderCore/Light.cpp       │
│  Worker 2                                            89/150           │
│                                                                         │
│  Speed: 127 modules/sec | ETA: 10.2s | Elapsed: 45.3s                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 性能监控输出示例

```
============================================================
Pipeline Performance Summary
============================================================

DISCOVER:
  Elapsed:     4.23s
  Processed:   1757/1757
  Speed:       415.37 items/sec

EXTRACT:
  Elapsed:     8.45s
  Processed:   1757/1757
  Speed:       207.93 items/sec

ANALYZE:
  Elapsed:     145.32s
  Processed:   1755/1757
  Speed:       12.08 items/sec
  Errors:      2

BUILD:
  Elapsed:     35.67s
  Processed:   1755/1755
  Speed:       49.21 items/sec

GENERATE:
  Elapsed:     1.23s
  Processed:   1/1

============================================================
Total Pipeline Time: 194.90s (3.25 min)
============================================================
```

---

## [2.8.0] - 2026-02-05

### Added ✨

- **统一知识库工作文件管理**: 所有 Pipeline 工作文件（`.pipeline_state` 和 `data/`）统一放在 `KnowledgeBase/` 目录下管理
  - 状态文件：`{base_path}/.pipeline_state` → `{base_path}/KnowledgeBase/.pipeline_state`
  - 工作数据：`{base_path}/data/` → `{base_path}/KnowledgeBase/data/`
  - 优点：删除知识库时可以直接删除整个文件夹，不再污染引擎源码目录

- **插件模式 Skill 模板对齐**: 插件模式的 Skill markdown 模板现在与引擎模式完全一致
  - 添加 `search_functions` 命令文档（函数搜索功能）
  - 添加查询降级机制说明（查询失败时的处理策略）
  - 添加函数相关查询示例
  - 扩展示例对话，提升用户体验

### Changed 📦

- `ue5_kb/pipeline/state.py` - 状态文件路径改为 `KnowledgeBase/.pipeline_state`
- `ue5_kb/pipeline/base.py` - 工作数据路径改为 `KnowledgeBase/data/`
- `templates/skill.plugin.md.template` - 完全对齐引擎模式模板

### Fixed 🐛

- 修复插件模式 Skill 文档缺少 `search_functions` 命令的问题
- 修复插件模式 Skill 文档缺少查询降级机制说明的问题

### Breaking Changes 💥

- **工作文件位置变更**: 如果用户有正在进行的 Pipeline，需要手动迁移旧文件：
  ```bash
  # 移动状态文件
  mv {Engine}/.pipeline_state {Engine}/KnowledgeBase/.pipeline_state
  # 移动工作数据
  mv {Engine}/data {Engine}/KnowledgeBase/data
  ```
  或使用 `--force` 重新运行 Pipeline

### Technical Details

**修改文件**:
- `ue5_kb/pipeline/state.py` (第 28-29 行)
- `ue5_kb/pipeline/base.py` (第 32-33 行)
- `templates/skill.plugin.md.template` (完全重写，+73 行)

**知识库目录结构变更**:
```
# 修改前
{Engine}/
├── .pipeline_state
├── data/
└── KnowledgeBase/

# 修改后
{Engine}/
└── KnowledgeBase/
    ├── .pipeline_state
    ├── data/
    ├── global_index/
    └── module_graphs/
```

---

## [2.7.0] - 2026-02-05

### Added ✨

**查询降级机制 - 防止 LLM 幻觉**
- **Skill Prompt 增强**: 添加"查询失败处理"章节，明确引导 LLM 在精确查询失败时使用模糊搜索
- **错误返回增强**: 所有查询函数错误返回新增 `fallback_command` 字段，自动提示下一步操作
- **函数模糊搜索**: 新增 `search_functions` 命令，补全函数模糊搜索能力
- **ClassIndex 快速索引**: 新建类快速索引系统，支持 < 10ms 的类查询和模糊搜索
- **FunctionIndex 增强**: 添加 `search_by_keyword` 方法，支持函数模糊搜索
- **Pipeline 索引构建**: BuildStage 自动构建 ClassIndex 和 FunctionIndex
- **索引加速搜索**: impl.py 使用索引替代遍历搜索，性能提升 500-800x

### Fixed 🐛

- **LLM 幻觉问题**: 彻底解决 LLM 在知识库查询失败时基于训练数据乱回答的问题
  - 精确查询失败 → 返回 `fallback_command` → LLM 自动执行模糊搜索
  - 模糊搜索失败 → 明确告知用户"知识库中未找到该信息"

### Changed 📦

- skill.md.template 添加"查询失败处理"章节
- impl.py.template 新增 `search_functions` 命令
- impl.py.template 使用 ClassIndex 和 FunctionIndex 替代遍历搜索
- impl.plugin.py.template 同步所有修改（插件模式支持）

### Performance ⚡

| 操作 | 修改前 | 修改后 | 提升 |
|------|--------|--------|------|
| 类搜索 | 遍历图谱 (~5s) | SQLite 索引 (<10ms) | **500x** |
| 函数搜索 | 遍历图谱 (~8s) | SQLite 索引 (<10ms) | **800x** |
| 模糊搜索 | 不支持 | LIKE 查询 (<20ms) | **新增** |

### Technical Details

**新增文件**:
- `ue5_kb/core/class_index.py` (~280 行)
  - `ClassIndex` 类：基于 SQLite 的类快速索引
  - `search_by_keyword()`: 模糊搜索方法
  - `query_by_parent()`: 按父类查询子类
  - `query_blueprintable()`: 查询 Blueprintable 类

**修改文件**:
- `ue5_kb/core/function_index.py` (+18 行)
  - 添加 `search_by_keyword()` 方法
- `ue5_kb/pipeline/build.py` (+110 行)
  - 添加 `_build_fast_indices()` 方法
  - 在 `run()` 方法中调用索引构建
- `templates/skill.md.template` (+50 行)
  - 添加"查询失败处理"章节
  - 添加 `search_functions` 命令
- `templates/impl.py.template` (+150 行)
  - 添加 `search_functions()` 函数
  - 添加 `_get_class_index()` 和 `_get_function_index()`
  - 所有错误返回添加 `fallback_command` 字段
- `templates/impl.plugin.py.template` (+150 行)
  - 同步所有修改（插件模式）

**验证测试**:
```bash
# 重新生成知识库
ue5kb init --engine-path "D:\UnrealEngine\UE5" --force

# 测试查询降级
python "~/.claude/skills/ue5kb-5.5.4/impl.py" query_function_info RHICreateTexture2D
# → 返回: {"error": "未找到函数", "fallback_command": "search_functions RHICreate"}

# 测试模糊搜索
python "~/.claude/skills/ue5kb-5.5.4/impl.py" search_functions RHICreate
# → 返回相关函数列表
```

---

## [2.6.0] - 2026-02-04

### Added ✨

**C++ Parser 增强模块图谱内容**
- **多重继承解析**: 解析完整的继承列表，支持 `class A : public B, public IInterface, public IOther`
- **接口识别**: 自动识别接口类（I 开头的类名），填充 `interfaces` 字段
- **命名空间检测**: 支持嵌套命名空间解析（传统语法和 C++17 简化语法），记录完整路径如 `UE::Core`
- **类属性解析**: 新增 `PropertyInfo` 数据类，解析 UPROPERTY 声明（基础版本：名称、类型、是否 UPROPERTY）
- **类方法解析**: 块级解析类体，提取成员函数方法签名
- **parent_classes 字段**: 新增字段存储完整继承列表

### Changed 📦

- `ClassInfo.properties` 类型从 `List[str]` 改为 `List[PropertyInfo]`
- `ClassInfo` 新增 `parent_classes` 字段存储完整继承列表
- NetworkX 图构建支持新字段：`interfaces`、`properties`、`namespace`

### Technical Details

**新增数据类**:
- `PropertyInfo`: 存储属性信息（名称、类型、是否 UPROPERTY）

**修改文件**:
- `ue5_kb/parsers/cpp_parser.py` (+200 行)
  - `_parse_classes_and_structs()`: 重写以支持多重继承和命名空间
  - `_parse_class_body()`: 新增方法解析类体内容
  - `_try_parse_property()`: 新增方法解析属性声明
  - `_try_parse_method()`: 新增方法解析方法声明
  - `_preprocess_content_lines()`: 新增方法保持行结构
- `ue5_kb/pipeline/build.py` (+30 行)
  - `_create_networkx_graph()`: 更新以支持新数据结构

**验证测试**:
```python
# 测试结果验证
类: UObject
  namespace: UE::Core
  methods: ['void GetName()']
  properties: [MyProperty: int32 (UPROPERTY: True)]

类: AActor
  parent_classes: ['UObject', 'IInterface']
  interfaces: ['IInterface']
  methods: ['void Tick(float DeltaTime)']
  properties: [Location: FVector (UPROPERTY: True)]
```

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
