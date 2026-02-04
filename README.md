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
└── KnowledgeBase\              # 知识库（1757 个模块）
    ├── global_index/           # 全局索引
    └── module_graphs/          # 模块图谱

C:\Users\{user}\.claude\skills\
└── ue5kb-5.1.500\              # Claude Skill
    ├── skill.md
    └── impl.py
```

### 模式 2: 插件模式（扫描单个插件）⭐ NEW

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
└── KnowledgeBase\              # 插件知识库
    ├── global_index/
    └── module_graphs/

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
| **生成时间** | ~30-60 分钟 | ~1-5 分钟 |
| **适用场景** | 引擎源码查询、全局依赖分析 | 插件开发、插件源码查询 |

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
{引擎根目录}/KnowledgeBase/
├── global_index/          # 全局模块索引
│   ├── index.db          # SQLite 数据库
│   └── global_index.pkl  # Pickle 索引
└── module_graphs/         # 模块知识图谱
    ├── Core.pkl
    ├── Engine.pkl
    └── ... (1,345+ 个引擎模块 + 插件模块)
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
