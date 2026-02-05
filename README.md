# UE5 Knowledge Base Maker

> 通用工具：为 UE5 引擎和插件生成知识库和 Claude Skill

## 功能特性

### 🎯 双模式支持（v2.1.0 新增）

- **引擎模式** - 为整个 UE5 引擎生成知识库（1757+ 模块）
- **插件模式** - 为单个插件生成独立知识库（轻量、高效）

### 核心功能

- 🔧 **通用工具** - 支持任何 UE5 引擎版本（5.0, 5.1, 5.2, 5.3, 5.4+）
- 📊 **知识库生成** - 自动扫描源码，构建模块索引和代码图谱
- 🔌 **完整覆盖** - 扫描 Engine/Source、Engine/Plugins、Engine/Platforms
- 🤖 **Skill 生成** - 自动生成 Claude Code Skill（模块级+代码级查询）
- ⚙️ **灵活配置** - 命令行引导式配置，无需环境变量
- 🚀 **高性能** - SQLite 存储，36x 性能提升
- 🎯 **自动检测** - 自动检测引擎/插件版本

### 快速索引系统（v2.7.0 新增）⚡

- **ClassIndex** - 类的快速索引，查询时间从 ~5s 降至 <10ms（**500x 提升**）
- **FunctionIndex 增强** - 函数模糊搜索，查询时间从 ~8s 降至 <10ms（**800x 提升**）
- **查询降级机制** - 精确查询失败时自动提示模糊搜索，**防止 LLM 幻觉**
- **fallback_command** - 错误返回包含降级命令，LLM 自动执行下一步操作

### 模块图谱增强（v2.6.0 新增）⭐

- **多重继承解析** - 完整解析类继承链，支持 `class A : public B, public IInterface`
- **接口识别** - 自动识别接口类（I 开头），填充 `interfaces` 字段
- **命名空间检测** - 支持嵌套命名空间，记录完整路径如 `UE::Core`
- **类属性解析** - 解析 UPROPERTY 声明，包含属性名称、类型和标记
- **类方法解析** - 块级解析类体，提取成员函数方法签名
- **完整继承列表** - `parent_classes` 字段存储所有父类和接口

## 安装

```bash
cd J:/UE5_KnowledgeBaseMaker
pip install -e .
```

## 使用方法

### 模式 1: 引擎模式（扫描整个引擎）

为整个 UE5 引擎生成知识库，包含所有引擎模块、插件和平台模块。

```bash
# 交互式引导
ue5kb init

# 直接指定引擎路径
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 自定义输出路径
ue5kb init --engine-path "D:\UE5.1" --kb-path "J:/MyUE5KB"
```

**生成结果**:
```
D:\Unreal Engine\UnrealEngine51_500\
└── KnowledgeBase\              # 知识库（统一目录）
    ├── .pipeline_state         # Pipeline 状态文件
    ├── data/                   # 工作数据目录
    │   ├── discover/
    │   ├── extract/
    │   ├── analyze/
    │   ├── build/
    │   └── generate/
    ├── global_index/           # 全局索引
    └── module_graphs/          # 模块图谱

C:\Users\{user}\.claude\skills\
└── ue5kb-5.1.500\              # Claude Skill
    ├── skill.md
    └── impl.py
```

### 并行处理系统（v2.10.0 新增）⚡

- **多进程并行**: Extract 和 Analyze 阶段使用多进程并行处理
  - Extract: 3-4x 性能提升
  - Analyze: 4-8x 性能提升（最耗时阶段）
  - Build: 混合模式（ThreadPoolExecutor + 串行 SQLite）
- **多进度条显示**: 实时显示总进度和每个 worker 的状态
- **性能监控**: 各阶段耗时统计、速度指标、ETA 计算
- **Checkpoint 机制**: Analyze 阶段支持中断恢复

```bash
# 自动检测并行度（推荐）
ue5kb init --engine-path "D:\UE5" -j 0

# 指定 8 个 worker
ue5kb init --engine-path "D:\UE5" --workers 8
ue5kb init --engine-path "D:\UE5" -j 4

# 串行模式（调试用）
ue5kb init --engine-path "D:\UE5" --workers 1
```

**性能对比**（8 核 CPU）：
| 阶段 | 修改前 | 修改后 | 提升 |
|------|--------|--------|------|
| Extract | ~30s | ~8s | **3.8x** |
| Analyze | ~600s | ~80-120s | **5-7x** |
| 总耗时 | ~665s | ~113-153s | **4.3-5.9x** |

### 模式 2: 插件模式（扫描单个插件）⭐

为单个插件生成独立的知识库，适合插件开发者。

```bash
# 为插件生成知识库
ue5kb init --plugin-path "F:\MyProject\Plugins\MyPlugin"

# 自定义输出路径
ue5kb init --plugin-path "F:\MyPlugin" --kb-path "J:/PluginKB"
```

**生成结果**:
```
F:\MyProject\Plugins\MyPlugin\
└── KnowledgeBase\              # 插件知识库（统一目录）
    ├── .pipeline_state         # Pipeline 状态文件
    ├── data/                   # 工作数据目录
    ├── global_index/           # 全局索引
    └── module_graphs/          # 模块图谱

C:\Users\{user}\.claude\skills\
└── myplugin-kb-1.0\            # 插件专属 Skill
    ├── skill.md
    └── impl.py
```

### 模式对比

| 特性 | 引擎模式 | 插件模式 |
|------|---------|---------|
| **扫描范围** | Engine/Source, Engine/Plugins, Engine/Platforms | Plugin/Source/** |
| **模块数量** | 1757 个（UE5.1） | 取决于插件规模（如 AesWorld: 40 个） |
| **知识库路径** | `{引擎}/KnowledgeBase/` | `{插件}/KnowledgeBase/` |
| **Skill 命名** | `ue5kb-{version}` | `{name}-kb-{version}` |
| **模块分类** | Runtime, Editor, Plugins.*, Platforms.* | Plugin.{PluginName} |
| **生成时间** | ~30-60 分钟（串行） | ~1-5 分钟 |
| **适用场景** | 引擎源码查询、全局依赖分析 | 插件开发、插件源码查询 |
| **并行加速** | 支持（v2.10.0+） | 支持（v2.10.0+） |

### 高级选项

```bash
# 自动检测并行度（推荐）
ue5kb init --engine-path "D:\UE5" -j 0

# 指定 8 个 worker
ue5kb init --engine-path "D:\UE5" --workers 8
ue5kb init --engine-path "D:\UE5" -j 4

# 串行模式（调试用）
ue5kb init --engine-path "D:\UE5" --workers 1
```

**性能对比**（8 核 CPU）：
| 阶段 | 修改前 | 修改后 | 提升 |
|------|--------|--------|------|
| Extract | ~30s | ~8s | **3.8x** |
| Analyze | ~600s | ~80-120s | **5-7x** |
| 总耗时 | ~665s | ~113-153s | **4.3-5.9x** |

### 并行处理系统（v2.10.0 新增）⚡

- **多进程并行**: Extract 和 Analyze 阶段使用多进程并行处理
  - Extract: 3-4x 性能提升
  - Analyze: 4-8x 性能提升（最耗时阶段）
  - Build: 混合模式（ThreadPoolExecutor + 串行 SQLite）
- **多进度条显示**: 实时显示总进度和每个 worker 的状态
- **性能监控**: 各阶段耗时统计、速度指标、ETA 计算
- **Checkpoint 机制**: Analyze 阶段支持中断恢复
| **Skill 命名** | `ue5kb-{version}` | `{name}-kb-{version}` |
| **模块分类** | Runtime, Editor, Plugins.*, Platforms.* | Plugin.{PluginName} |
| **生成时间** | ~30-60 分钟 | ~1-5 分钟 | ~5-10 分钟（并行） |
| **适用场景** | 引擎源码查询、全局依赖分析 | 插件开发、插件源码查询 | 插件开发、插件源码查询 |

### 并行处理系统（v2.10.0 新增）⚡

### 高级选项

```bash
# 强制重新运行所有阶段（忽略已完成的阶段）
ue5kb init --engine-path "D:\UE5" --force

# 仅运行指定阶段
ue5kb init --engine-path "D:\UE5" --stage discover
ue5kb init --engine-path "D:\UE5" --stage build

# 并行处理（用于 analyze 阶段）
ue5kb init --engine-path "D:\UE5" --parallel 4

# 显示详细输出（用于调试）
ue5kb init --engine-path "D:\UE5" --verbose
```

**Pipeline 阶段说明**：
1. `discover` - 发现所有模块
2. `extract` - 提取模块依赖
3. `analyze` - 分析代码结构
4. `build` - 构建索引
5. `generate` - 生成 Skill

### 其他命令

```bash
# 查看版本
ue5kb --version

# 查看帮助
ue5kb --help
ue5kb init --help

# 查看状态
ue5kb status

# Pipeline 状态查看
ue5kb pipeline status --engine-path "D:\UE5"
```

## 生成的文件

### 知识库结构

```
{引擎根目录}/KnowledgeBase/      # 统一输出目录
├── .pipeline_state             # Pipeline 状态文件
├── data/                       # 工作数据目录
│   ├── discover/               # 阶段 1: 发现的模块列表
│   ├── extract/                # 阶段 2: 模块依赖信息
│   ├── analyze/                # 阶段 3: 代码分析结果
│   ├── build/                  # 阶段 4: 构建摘要
│   └── generate/               # 阶段 5: Skill 生成标记
├── global_index/               # 全局模块索引
│   ├── index.db                # SQLite 数据库
│   ├── class_index.db          # 类快速索引
│   ├── function_index.db       # 函数快速索引
│   └── global_index.pkl        # Pickle 索引
└── module_graphs/              # 模块知识图谱
    ├── Core.pkl
    ├── Engine.pkl
    └── ... (1,757+ 个模块)
```

### 模块覆盖范围

工具会自动扫描以下目录中的所有模块：

1. **Engine/Source** - 引擎核心模块
   - Runtime/ (运行时模块)
   - Editor/ (编辑器模块)
   - Developer/ (开发者工具)
   - Programs/ (独立程序)

2. **Engine/Plugins** - 引擎插件模块
   - 2D/ - 2D 相关插件
   - AI/ - AI 相关插件
   - Animation/ - 动画插件
   - Audio/ - 音频插件
   - Editor/ - 编辑器插件
   - Enterprise/ - 企业级插件
   - FX/ - 特效插件
   - Martketplace/ - Marketplace 插件 (如 BlueprintAssist_5.1)
   - 以及更多... (所有插件类型)

3. **Engine/Platforms** - 平台模块
   - Windows/, Linux®, Android®, iOS®, Mac® 等

**扫描方式**：直接递归搜索所有 `.Build.cs` 文件，然后根据路径自动推导分类标签。

每个模块的分类标签格式：
- 引擎模块: `{Category}` (如 `Runtime`, `Editor`)
- 插件模块: `Plugins.{PluginType}.{PluginName}` (如 `Plugins.Editor.ContentBrowser`)
- 平台模块: `Platforms.{PlatformName}` (如 `Platforms.Windows`)

### Skill 结构

```
C:\Users\pb763\.claude\skills\ue5kb-{version}/
├── skill.md               # Skill 定义
└── impl.py                # Skill 实现（含知识库路径）
```

## 多引擎支持

可以为同一台机器的多个引擎版本生成独立的知识库和 Skill：

```
D:\Unreal Engine\UnrealEngine51_500\
└── KnowledgeBase\          ← 知识库
C:\Users\pb763\.claude\skills\ue5kb-5.1.500\  ← Skill

D:\Unreal Engine\UnrealEngine5.3\
└── KnowledgeBase\          ← 知识库
C:\Users\pb763\.claude\skills\ue5kb-5.3\  ← Skill
```

每个 Skill 独立工作，自动指向对应的知识库！

## 使用生成的 Skill

安装后，在 Claude Code 中直接询问问题：

```
"Core 模块有哪些依赖？"
"AActor 类继承自什么？"
"列出所有 Runtime 模块"
```

## 版本要求

- Python 3.9+
- UE5 任何版本

## 技术架构

### 核心技术

- **图存储**: NetworkX (模块依赖关系图谱)
- **数据库**: SQLite (全局索引，36x 性能提升)
- **缓存**: LRU Cache (热数据 <1ms 响应)
- **CLI**: Click + Rich (引导式交互)
- **解析**: 正则表达式 (Build.cs 依赖解析)

### 目录结构

```
J:/UE5_KnowledgeBaseMaker/
├── ue5_kb/                    # 核心包
│   ├── __init__.py
│   ├── cli.py                 # CLI 入口
│   ├── core/                  # 核心模块
│   │   ├── config.py          # 配置管理
│   │   ├── global_index.py    # 全局索引
│   │   ├── module_graph.py    # 模块图谱
│   │   └── optimized_index.py # 优化索引 (SQLite)
│   ├── parsers/               # 解析器
│   │   ├── buildcs_parser.py
│   │   └── cpp_parser.py
│   └── builders/              # 构建器
│       ├── global_index_builder.py
│       └── module_graph_builder.py
├── pyproject.toml             # Python 包配置
├── README.md                  # 本文档
└── test_*.py                  # 测试脚本
```

## 版本检测

工具会自动检测引擎版本，优先级：

1. **Build.version 文件** (最准确)
   ```
   Engine/Build/Build.version:
   {
       "MajorVersion": 5,
       "MinorVersion": 1,
       "PatchVersion": 1
   }
   → 5.1.1
   ```

2. **文件夹名称** (备用)
   ```
   UnrealEngine51_500
   → 5.1.500
   ```

## 测试

```bash
# 测试版本检测
python test_init.py

# 测试完整流程
python test_full_init.py

# 测试 CLI
python -m ue5_kb.cli --help
```

## 开发

### 修改代码后

```bash
# 重新安装
pip install -e . --force-reinstall --no-deps
```

### 调试

```bash
# 直接运行 CLI
python -m ue5_kb.cli init --engine-path "D:\Unreal Engine\UnrealEngine51_500"
```

## 故障排除

### 问题: ModuleNotFoundError

```bash
# 安装依赖
pip install click rich pyyaml networkx
```

### 问题: 配置文件不存在

工具会自动创建配置文件，无需手动创建。

### 问题: 版本检测失败

检查引擎目录下是否存在 `Engine/Build/Build.version` 文件。

## 更新日志

### v2.10.0 (2026-02-05)

**并行加速系统 - Pipeline 性能飞跃**
- **多进程并行处理**: Extract 和 Analyze 阶段使用多进程并行
  - Extract 阶段: 3-4x 性能提升
  - Analyze 阶段: 4-8x 性能提升（解析 C++ 源码）
  - Build 阶段: 混合模式（ThreadPoolExecutor + 串行 SQLite）
- **多进度条显示**: 使用 Rich 库实现实时多 worker 状态显示
  - 总进度条：显示整体完成百分比和 ETA
  - Worker 进度条：每个 worker 独立显示当前处理的模块
- **性能监控系统**: StageTimer 记录各阶段耗时和速度
- **Checkpoint 机制**: Analyze 阶段支持中断恢复
- **智能并行检测**: --workers/-j 参数（0=自动检测 CPU 核心数）
- **错误隔离**: 单个模块失败不影响其他模块处理
- **总性能提升**: 4.3-5.9x（在 8 核 CPU 上）

### v2.8.0 (2026-02-05)

**统一知识库文件管理 + 插件模式 Skill 对齐**
- **统一工作文件管理**: 所有 Pipeline 工作文件（`.pipeline_state` 和 `data/`）统一放在 `KnowledgeBase/` 目录下
  - 状态文件：`{base_path}/.pipeline_state` → `{base_path}/KnowledgeBase/.pipeline_state`
  - 工作数据：`{base_path}/data/` → `{base_path}/KnowledgeBase/data/`
- **插件模式 Skill 对齐**: 插件模式的 Skill markdown 模板现在与引擎模式完全一致
  - 添加 `search_functions` 命令文档
  - 添加查询降级机制说明
  - 添加函数相关查询示例
- **更好的文件管理**: 删除知识库时可以直接删除整个 `KnowledgeBase/` 文件夹

### v2.7.0 (2026-02-05)

**查询降级机制 - 防止 LLM 幻觉**
- **快速索引系统**: ClassIndex 和 FunctionIndex，查询性能提升 500-800x
- **查询降级机制**: 精确查询失败时自动提示模糊搜索
- **防止 LLM 幻觉**: 彻底解决 LLM 在知识库查询失败时基于训练数据乱回答的问题
- **新增 search_functions**: 函数模糊搜索命令
- **Skill Prompt 增强**: 添加"查询失败处理"章节，明确引导 LLM 行为

### v2.6.0 (2026-02-04)

**C++ Parser 增强模块图谱内容**
- **多重继承解析**: 解析完整的继承列表，支持 `class A : public B, public IInterface`
- **接口识别**: 自动识别接口类（I 开头）
- **命名空间检测**: 支持嵌套命名空间
- **类属性解析**: 解析 UPROPERTY 声明
- **类方法解析**: 块级解析类体

### v2.1.0 (2026-02-02)

**插件模式支持**
- **插件模式**: 为单个插件生成独立知识库
- **双模式 CLI**: 引擎模式和插件模式自动路由
- **插件专属 Skill**: 自动生成插件专属 Claude Code Skill

### v2.0.0 (2026-02-02)

- **重构**: 从 J:/ue5-kb 重构为通用工具
- **移除**: 所有硬编码路径
- **新增**: CLI 引导式配置
- **新增**: 自动引擎版本检测
- **新增**: 自动生成 Claude Skill
- **优化**: SQLite 36x 性能提升
- **支持**: 多引擎版本独立知识库

## 许可证

MIT License
