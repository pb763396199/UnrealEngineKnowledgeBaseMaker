# UE5 Knowledge Base Maker

> 通用工具：为任何版本的 UE5 引擎生成知识库和 Claude Skill

## 功能特性

- 🔧 **通用工具** - 支持任何 UE5 引擎版本（5.0, 5.1, 5.2, 5.3, 5.4+）
- 📊 **知识库生成** - 自动扫描引擎源码和插件，构建模块索引和知识图谱
- 🔌 **完整覆盖** - 同时扫描 Engine/Source 和 Engine/Plugins 中的所有模块
- 🤖 **Skill 生成** - 自动生成对应的 Claude Code Skill
- ⚙️ **灵活配置** - 命令行引导式配置，无需环境变量
- 🚀 **高性能** - SQLite 存储，36x 性能提升 vs pickle
- 🎯 **自动检测** - 从 Build.version 文件自动检测引擎版本

## 安装

```bash
cd J:/UE5_KnowledgeBaseMaker
pip install -e .
```

## 使用方法

### 快速开始

```bash
# 为 UE5.1.500 生成知识库和 Skill
ue5kb init

# 交互式引导：
# UE5 引擎路径: D:\Unreal Engine\UnrealEngine51_500
# → 自动检测版本: 5.1.500
# → 知识库保存: D:\Unreal Engine\UnrealEngine51_500\KnowledgeBase\
# → Skill 保存: C:\Users\pb763\.claude\skills\ue5kb-5.1.500\
```

### 命令行参数

```bash
# 直接指定参数
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine5.3"

# 自定义知识库路径
ue5kb init --engine-path "D:\UE5.1" --kb-path "J:/MyUE5KB"

# 自定义 Skill 路径
ue5kb init --engine-path "D:\UE5.1" --skill-path "C:/Users/pb763/.claude/skills/my-ue5-skill"

# 查看状态
ue5kb status
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

每个插件模块会被标记为 `Plugins.{PluginType}.{PluginName}` 分类，例如：
- `Plugins.Editor.ContentBrowser.ContentBrowserAssetDataSource`
- `Plugins.AI.ModelMass.ModelMass`
- `Plugins.Martketplace.BlueprintAssist_5_1.BlueprintAssist`

**插件结构支持**：
- 标准结构: `Plugin/Source/ModuleName/ModuleName.Build.cs`
- 直接结构: `Plugin/ModuleName/ModuleName.Build.cs` (较少见)

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
