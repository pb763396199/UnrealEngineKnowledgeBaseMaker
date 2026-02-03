# ue5kb-dev-guide

UE5 Knowledge Base Maker 项目专属开发指导 Skill。为 Claude Code 和其他 AI 助手提供全面的架构理解、开发工作流和最佳实践指导。

---

## Skill 概述

**用途**: 综合指导（开发工作流 + 架构理解）

**适用场景**:
- 复杂的功能开发需要深入理解架构
- 代码重构需要评估影响范围
- 性能优化需要了解系统设计
- 调试复杂问题需要系统级诊断

**使用方式**: 在 Claude Code 中输入 `/ue5kb-dev-guide`

---

## Part 1: Architecture Understanding

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Layer (cli.py)                       │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ Engine Mode  │              │ Plugin Mode  │                │
│  └──────────────┘              └──────────────┘                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Builder Layer                              │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │GlobalIndexBuilder│    │PluginIndexBuilder│                   │
│  └──────────────────┘    └──────────────────┘                   │
│  ┌──────────────────────────────────────────┐                   │
│  │      ModuleGraphBuilder                  │                   │
│  └──────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Parser Layer                              │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │ BuildCSParser    │    │  CPPParser       │                   │
│  └──────────────────┘    └──────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage Layer                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────────────┐                 │
│  │ SQLite  │  │ Pickle  │  │   NetworkX       │                 │
│  │ index.db│  │ *.pkl   │  │   Graphs         │                 │
│  └─────────┘  └─────────┘  └──────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Query Optimization Layer                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │LayeredQuery  │  │ResultCache   │  │TokenBudget   │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline 架构 (v2.5.0)

```
┌─────────────────────────────────────────────────────────────────┐
│                   PipelineCoordinator                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ State Mgmt   │  │ Stage Orchest│  │ Progress     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Pipeline Stages                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Discover  │→ │ Extract  │→ │ Analyze  │→ │  Build   │→        │
│  │  Stage   │  │  Stage   │  │  Stage   │  │  Stage   │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                 │                 │
│                                    ┌──────────▼──────────┐       │
│                                    │    Generate Stage   │       │
│                                    └─────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Analyzers Framework (Phase 2)                 │
│  ┌──────────────────┐              ┌──────────────────┐           │
│  │  CallAnalyzer    │              │ ExampleExtractor │           │
│  │  (调用关系分析)    │              │  (示例提取)       │           │
│  └──────────────────┘              └──────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline 数据流

```
UE5 引擎/插件源码
    ↓
[Stage 1: Discover] 发现所有 .Build.cs 文件
    → module_list: [{name, path, category}, ...]
    ↓
[Stage 2: Extract] 解析模块元数据
    → Parse Build.cs (依赖关系)
    → Parse C++ 头文件 (类/函数)
    → module_metadata: {dependencies, classes, functions}
    ↓
[Stage 3: Analyze] 分析代码关系 (Phase 2)
    → CallAnalyzer (函数调用关系)
    → ExampleExtractor (使用示例)
    → enhanced_metadata: {call_graphs, examples}
    ↓
[Stage 4: Build] 构建索引
    → SQLite (index.db)
    → Pickle (module_graphs/*.pkl)
    → Pipeline State (.pipeline_state)
    ↓
[Stage 5: Generate] 生成 Skills
    → Skill 模板渲染
    → ~/.claude/skills/ue5kb-{version}/
```

### 模块关系图（Pipeline 架构）

```
cli.py
  └── PipelineCoordinator (统一入口)
        ├── DiscoverStage
        │     └── BuildCS 文件发现 (.Build.cs)
        ├── ExtractStage
        │     ├── BuildCSParser (依赖关系)
        │     └── CPPParser (类/函数提取)
        ├── AnalyzeStage
        │     ├── CallAnalyzer (调用关系分析)
        │     └── ExampleExtractor (示例提取)
        ├── BuildStage
        │     ├── GlobalIndexBuilder (SQLite 索引)
        │     └── ModuleGraphBuilder (图谱)
        └── GenerateStage
              └── Skill 模板渲染

Core (单例缓存)
  ├── Config (路径和版本配置)
  ├── GlobalIndex (全局索引接口)
  ├── ModuleGraph (模块图谱接口)
  └── OptimizedIndex (SQLite 优化索引)

Pipeline (状态管理)
  ├── PipelineState (状态持久化)
  ├── PipelineStage (基类)
  └── Stage Results (阶段结果)

Query (Context Optimization)
  ├── LayeredQueryInterface (分层查询)
  ├── ResultCache (结果缓存和屏蔽)
  └── TokenBudget (Token 预算管理)

Analyzers (Phase 2)
  ├── CallAnalyzer (函数调用分析)
  └── ExampleExtractor (示例提取)
```

### 数据流详解

#### 引擎模式数据流

```
Engine/Source/**/*.Build.cs
    ↓
BuildCSParser.parse_file()
    ↓ 提取模块信息
    {
        "name": "Core",
        "dependencies": ["TraceLog"],
        "category": "Runtime",
        "file_path": "..."
    }
    ↓
GlobalIndexBuilder.build()
    ↓
1. 创建 SQLite 数据库 (index.db)
2. 构建依赖关系图 (NetworkX)
3. 生成全局索引 (global_index.pkl)
    ↓
ModuleGraphBuilder.build()
    ↓
1. 扫描 C++ 头文件
2. 解析类、函数、继承关系
3. 生成模块图谱 (*.pkl)
    ↓
Skill 生成
    ↓
templates/*.template → ~/.claude/skills/ue5kb-{version}/
```

#### 插件模式数据流

```
Plugin/Source/**/*.Build.cs
    ↓
BuildCSParser.parse_file()
    ↓
PluginIndexBuilder.build()
    ↓ (与引擎模式类似，但范围限定在插件内)
    ↓
templates/*.template → ~/.claude/skills/{name}-kb-{version}/
```

---

## Part 2: Core Modules Deep Dive

### ue5_kb/cli.py

**职责**: CLI 命令定义和处理

**关键函数**:

| 函数 | 职责 |
|------|------|
| `cli()` | 主入口，定义命令组 |
| `init()` | 初始化命令，路由到引擎/插件模式 |
| `init_engine_mode()` | 引擎模式处理逻辑 |
| `init_plugin_mode()` | 插件模式处理逻辑 |
| `detect_engine_version()` | 从 Build.version 检测引擎版本 |
| `detect_plugin_info()` | 从 .uplugin 检测插件信息 |
| `generate_skill()` | 从模板生成 Claude Skill |

**关键设计模式**:

1. **命令模式**: 使用 Click 装饰器定义命令
2. **策略模式**: 根据 `--engine-path` 或 `--plugin-path` 选择不同策略

### ue5_kb/core/config.py

**职责**: 配置管理

**关键类**: `Config`

```python
class Config:
    base_path: Path          # 知识库根路径
    engine_version: str      # 引擎版本
    index_db_path: Path      # SQLite 数据库路径
    module_graphs_dir: Path  # 模块图谱目录
```

**使用方式**:

```python
from ue5_kb.core.config import get_config

config = get_config(engine_path)
# config 是单例，全局共享
```

### ue5_kb/core/global_index.py

**职责**: 全局索引接口

**关键类**: `GlobalIndex`

```python
class GlobalIndex:
    def get_module_info(module_name: str) -> dict
    def get_module_dependencies(module_name: str) -> list
    def search_modules(keyword: str) -> list
    def get_statistics() -> dict
```

**性能优化**:

- 使用 SQLite 缓存热数据
- LRU Cache 缓存查询结果 (<1ms)

### ue5_kb/core/module_graph.py

**职责**: 模块图谱接口

**关键类**: `ModuleGraph`

```python
class ModuleGraph:
    def get_class_info(class_name: str) -> dict
    def get_class_hierarchy(class_name: str) -> list
    def get_module_classes(module_name: str) -> list
    def search_classes(keyword: str) -> list
```

**数据结构**:

```python
{
    "module_name": "Core",
    "classes": {
        "UObject": {
            "parent_classes": ["UObjectBase", "UObjectBaseUtility"],
            "methods": ["GetName", "StaticClass", ...],
            "properties": [...],
            "file_path": "...",
            "line_number": 123
        },
        ...
    }
}
```

### ue5_kb/builders/global_index_builder.py

**职责**: 引擎索引构建

**关键类**: `GlobalIndexBuilder`

```python
class GlobalIndexBuilder:
    def build() -> None
    def _scan_build_files() -> list[Path]
    def _determine_category(build_file: Path) -> str
```

**扫描策略**:

```
Engine/
├── Source/
│   ├── Runtime/     → category: "Runtime"
│   ├── Editor/      → category: "Editor"
│   ├── Developer/   → category: "Developer"
│   └── Programs/    → category: "Programs"
├── Plugins/         → category: "Plugins.{Type}.{Name}"
└── Platforms/       → category: "Platforms.{Platform}"
```

### ue5_kb/builders/plugin_index_builder.py

**职责**: 插件索引构建

**关键区别**:

- 扫描范围限定在 `Plugin/Source/**/*.Build.cs`
- 模块分类标签: `Plugin.{PluginName}`
- 知识库存储在插件根目录

### ue5_kb/parsers/buildcs_parser.py

**职责**: Build.cs 文件解析

**关键类**: `BuildCSParser`

```python
class BuildCSParser:
    def parse_file(file_path: Path) -> dict
    def _extract_dependencies(content: str) -> dict
    def _extract_module_info(content: str) -> dict
```

**提取字段**:

```python
{
    "name": "Core",
    "dependencies": {
        "public": ["TraceLog"],
        "private": []
    },
    "references": [],
    "include_path": "...",
    "category": "Runtime"
}
```

### ue5_kb/parsers/cpp_parser.py

**职责**: C++ 代码解析

**关键类**: `CPPParser`

```python
class CPPParser:
    def parse_module(module_path: Path) -> dict
    def _extract_classes(content: str) -> dict
    def _extract_functions(content: str) -> list
    def _extract_inheritance(content: str) -> list
```

**正则表达式模式**:

```python
CLASS_PATTERN = r'class\s+(\w+)\s*:\s*public\s+(\w+)'
FUNCTION_PATTERN = r'(\w+)\s*\([^)]*\)\s*(?:const)?\s*(?:override)?\s*;'
```

### ue5_kb/core/function_index.py

**职责**: 函数搜索索引

**关键类**: `FunctionIndex`

```python
class FunctionIndex:
    def search_functions(keyword: str) -> list
    def get_functions_by_module(module_name: str) -> list
    def get_function_signatures(class_name: str) -> list
```

**用途**: 提供快速函数名搜索和模块内函数列表查询

### ue5_kb/builders/partitioned_builder.py

**职责**: 多代理分区构建

**关键类**: `PartitionedBuilder`

**用途**: 大型引擎的分布式构建，将模块分配给多个工作节点并行处理

**工作流程**:
1. 分析模块依赖图
2. 将模块分配到不同分区
3. 每个分区独立构建
4. 合并分区结果

### ue5_kb/query/layered_query.py

**职责**: 分层查询接口（渐进式披露）

**关键类**: `LayeredQueryInterface`

**查询层级**:
- **Summary** (~200 tokens): 关键信息 + ref_id
- **Details** (~1000 tokens): 完整数据（通过 ref_id）
- **Source** (~5000 tokens): 原始 C++ 代码

### ue5_kb/query/result_cache.py

**职责**: 结果缓存和观察屏蔽

**关键类**: `ResultCache`

**功能**:
- LRU 缓存热点查询结果
- Observation Masking：大型结果返回前 5 项 + ref_id
- Token 使用量减少 80-85%

### ue5_kb/query/token_budget.py

**职责**: Token 预算管理

**关键类**: `TokenBudget`

**预算类别**:
- `QUERY_RESULTS`: 查询结果
- `CODE_EXAMPLES`: 代码示例
- `CONTEXT_INFO`: 上下文信息

---

## Part 3: Development Workflow

### 功能开发流程

```
需求分析
    ↓
阅读 CLAUDE.md 了解基本流程
    ↓
使用 Explore agent 探索相关代码
    ↓
检查 openspec/ 是否需要创建 proposal
    ↓
设计实现方案
    ↓
编写代码（在 tests/ 中编写测试）
    ↓
运行测试循环
    ↓
更新 CHANGELOG.md
    ↓
询问用户是否需要更新版本号/README.md
    ↓
更新 CLI 帮助文档（如果重大功能）
    ↓
提交代码
```

### 代码模式

#### Builder 模式

```python
from ue5_kb.core.config import get_config
from ue5_kb.parsers.buildcs_parser import BuildCSParser

class CustomBuilder:
    def __init__(self, base_path: Path):
        self.config = get_config(base_path)
        self.parser = BuildCSParser()

    def build(self) -> None:
        """构建索引的主入口"""
        # 1. 扫描文件
        files = self._scan_files()
        # 2. 解析内容
        data = [self.parser.parse_file(f) for f in files]
        # 3. 存储结果
        self._store(data)

    def _scan_files(self) -> list[Path]:
        """扫描需要处理的文件"""
        raise NotImplementedError

    def _store(self, data: list) -> None:
        """存储处理结果"""
        raise NotImplementedError
```

#### Parser 模式

```python
class CustomParser:
    def parse_file(self, file_path: Path) -> dict:
        """解析文件的主入口"""
        content = file_path.read_text(encoding='utf-8')
        return self._extract_info(content)

    def _extract_info(self, content: str) -> dict:
        """从内容中提取信息"""
        # 使用正则表达式或其他方法
        raise NotImplementedError
```

### 测试策略

#### 单元测试模式

```python
import pytest
from pathlib import Path
from ue5_kb.parsers.buildcs_parser import BuildCSParser

def test_buildcs_parser():
    """测试 Build.cs 解析器"""
    parser = BuildCSParser()

    # 测试正常文件
    test_file = Path("tests/fixtures/Core.Build.cs")
    result = parser.parse_file(test_file)

    assert result["name"] == "Core"
    assert "TraceLog" in result["dependencies"]["public"]

def test_buildcs_parser_empty_file():
    """测试空文件处理"""
    parser = BuildCSParser()
    test_file = Path("tests/fixtures/empty.Build.cs")

    result = parser.parse_file(test_file)
    assert result is None or result == {}
```

#### 集成测试模式

```python
def test_full_build_integration():
    """测试完整的构建流程"""
    from ue5_kb.builders.global_index_builder import GlobalIndexBuilder
    from pathlib import Path

    test_engine = Path("tests/fixtures/test_engine")
    builder = GlobalIndexBuilder(test_engine)

    builder.build()

    # 验证结果
    assert builder.config.index_db_path.exists()
    stats = builder.get_statistics()
    assert stats["total_modules"] > 0
```

### 调试指南

#### 日志记录

```python
import logging

logger = logging.getLogger(__name__)

def build(self):
    logger.info(f"开始构建索引: {self.config.base_path}")
    files = self._scan_files()
    logger.info(f"找到 {len(files)} 个 .Build.cs 文件")

    for file in files:
        try:
            result = self.parser.parse_file(file)
            logger.debug(f"解析成功: {file.name}")
        except Exception as e:
            logger.error(f"解析失败: {file}, 错误: {e}")
```

#### 常见问题诊断

| 症状 | 可能原因 | 诊断方法 |
|------|----------|----------|
| ModuleNotFoundError | 包未安装 | `pip list | grep ue5-kb` |
| 解析失败 | 正则表达式不匹配 | 添加日志查看原始内容 |
| 性能下降 | 缓存未启用 | 检查 `get_config()` 调用 |
| 测试失败 | 测试数据过期 | 运行 `pytest --cache-clear` |

---

## Part 4: Best Practices

### 代码风格

```python
# 类型注解
def parse_file(file_path: Path) -> dict | None:
    """解析 .Build.cs 文件

    Args:
        file_path: 文件路径

    Returns:
        包含模块信息的字典，解析失败返回 None
    """
    pass

# 命名约定
class GlobalIndexBuilder:      # PascalCase for classes
def scan_files() -> list:      # snake_case for functions
MODULE_NAME = "Core"           # UPPER_CASE for constants

# 文档字符串
"""单行摘要

更详细的描述（可选）

Args:
    arg1: 参数1说明

Returns:
    返回值说明

Raises:
    ValueError: 错误说明
"""
```

### 错误处理

```python
def safe_parse(file_path: Path) -> dict | None:
    """安全解析，返回 None 而非抛出异常"""
    try:
        return parser.parse_file(file_path)
    except FileNotFoundError:
        logger.warning(f"文件不存在: {file_path}")
        return None
    except Exception as e:
        logger.error(f"解析失败: {file_path}, 错误: {e}")
        return None

def parse_with_retry(file_path: Path, max_retries: int = 3) -> dict:
    """带重试的解析"""
    for attempt in range(max_retries):
        try:
            return parser.parse_file(file_path)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"重试 {attempt + 1}/{max_retries}")
            time.sleep(1)
```

### 性能优化

```python
from functools import lru_cache
import sqlite3

# 1. 使用 LRU 缓存
@lru_cache(maxsize=128)
def get_module_info(module_name: str) -> dict:
    """缓存热点数据"""
    return _query_from_db(module_name)

# 2. 批量操作
def batch_insert(items: list) -> None:
    """批量插入而非逐条插入"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany("INSERT ... VALUES (?, ?)", items)
        conn.commit()

# 3. 生成器处理大文件
def parse_large_file(file_path: Path):
    """逐行处理而非全部读入内存"""
    with open(file_path) as f:
        for line in f:
            yield process_line(line)
```

---

## Part 5: Integration Points

### OpenSpec Workflow

#### 创建变更提案

```bash
# 1. 检查现有规范
openspec list --specs

# 2. 创建变更目录
mkdir -p openspec/changes/add-new-feature/specs/core

# 3. 编写提案
cat > openspec/changes/add-new-feature/proposal.md << 'EOF'
# Change: Add New Feature

## Why
[描述问题或机会]

## What Changes
- [列表描述变更]

## Impact
- Affected specs: core, global-index
- Affected code: cli.py, builders/*.py
EOF

# 4. 编写 spec delta
cat > openspec/changes/add-new-feature/specs/core/spec.md << 'EOF'
## ADDED Requirements
### Requirement: New Feature
The system SHALL provide...

#### Scenario: Success case
- **WHEN** user performs action
- **THEN** expected result
EOF

# 5. 验证
openspec validate add-new-feature --strict
```

#### 归档流程

```bash
# 功能部署后
openspec archive add-new-feature --yes
```

### Context Optimization 集成

#### 分层查询实现

```python
from ue5_kb.query.layered_query import LayeredQueryInterface

class CustomQueryHandler:
    def __init__(self, kb_path: Path):
        self.query = LayeredQueryInterface(kb_path)

    def get_class_summary(self, class_name: str) -> dict:
        """获取类摘要（~200 tokens）"""
        return self.query.query_class(class_name, detail_level='summary')

    def get_class_details(self, class_name: str) -> dict:
        """获取类详情（~1000 tokens）"""
        return self.query.query_class(class_name, detail_level='details')

    def get_class_source(self, class_name: str) -> dict:
        """获取类源码（~5000 tokens）"""
        return self.query.query_class(class_name, detail_level='source')
```

#### Observation Masking

```python
from ue5_kb.query.result_cache import ResultCache

cache = ResultCache(ttl_seconds=3600)

def search_functions(keyword: str) -> dict:
    """搜索函数，自动屏蔽大型结果"""
    results = _do_search(keyword)

    if len(results) > 5:
        return cache.mask_large_result(results, threshold=5)
    return {"results": results}
```

#### Token 预算管理

```python
from ue5_kb.query.token_budget import get_token_budget, ContextCategory

budget = get_token_budget()

def query_with_budget(query: str) -> dict:
    """带预算管理的查询"""
    result = _execute_query(query)
    tokens = estimate_tokens(result)

    if budget.allocate(ContextCategory.QUERY_RESULTS, tokens):
        return result
    else:
        # 超出预算，返回摘要
        return _summarize_result(result)
```

### Skill Generation

#### 模板变量

```python
# templates/skill.md.template
# {{name}}: Skill 名称
# {{version}}: 版本号
# {{kb_path}}: 知识库路径
# {{is_plugin}}: 是否为插件模式

# 生成时
context = {
    "name": "ue5kb-5.1.500",
    "version": "5.1.500",
    "kb_path": str(kb_path),
    "is_plugin": False
}

skill_content = template.render(**context)
```

#### 自定义扩展

```python
# 在模板中添加自定义函数
def custom_query_helper(module_name: str) -> str:
    """自定义查询辅助函数"""
    index = GlobalIndex(kb_path)
    info = index.get_module_info(module_name)
    return f"模块 {module_name} 位于 {info['category']}"

# 在模板中使用
# {{ custom_query_helper('Core') }}
```

---

## Part 6: Troubleshooting

### 常见错误

#### 1. SQLite 数据库锁定

```
sqlite3.OperationalError: database is locked
```

**原因**: 多个进程同时访问数据库

**解决**:
```python
from contextlib import contextmanager

@contextmanager
def db_connection(db_path: Path):
    """独占数据库连接"""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        yield conn
    finally:
        conn.close()
```

#### 2. Pickle 版本不兼容

```
ModuleNotFoundError: Can't get module 'ue5_kb.core.xxx'
```

**原因**: Pickle 文件包含完整模块路径，重构后失效

**解决**:
```python
# 使用 JSON 作为备选
def save_with_fallback(data: dict, path: Path) -> None:
    try:
        import pickle
        with open(path.with_suffix('.pkl'), 'wb') as f:
            pickle.dump(data, f)
    except Exception:
        import json
        with open(path.with_suffix('.json'), 'w') as f:
            json.dump(data, f, default=str)
```

#### 3. Windows 路径问题

```
FileNotFoundError: [Errno 2] No such file or directory: 'D:\\path\\to\\file'
```

**原因**: 路径分隔符或转义问题

**解决**:
```python
from pathlib import Path

# ✅ 正确
path = Path(r"D:\path\to\file")
path = Path("D:/path/to/file")
path = Path("D:\\path\\to\\file")

# ❌ 错误
path = "D:\path\to\file"  # \t 被解析为制表符
```

### 性能问题

#### 1. 查询缓慢

**诊断**:
```python
import time

start = time.time()
result = query_function()
elapsed = time.time() - start
print(f"查询耗时: {elapsed:.3f}秒")
```

**优化**:
1. 启用 SQLite 索引
2. 使用 LRU 缓存
3. 批量操作

#### 2. 内存占用高

**诊断**:
```python
import psutil
import os

process = psutil.Process(os.getpid())
print(f"内存占用: {process.memory_info().rss / 1024 / 1024:.1f} MB")
```

**优化**:
1. 使用生成器而非列表
2. 及时释放大对象
3. 分批处理大文件

---

## 附录

### 相关文档

| 文档 | 路径 |
|------|------|
| CLAUDE.md | 项目根目录 |
| README.md | 项目根目录 |
| STATUS.md | 项目根目录 |
| CHANGELOG.md | 项目根目录 |
| CONTEXT_OPTIMIZATION.md | docs/ |
| AGENTS.md | openspec/ |

### 命令速查

```bash
# 开发
pip install -e . --force-reinstall --no-deps
pytest tests/ -v
python -m ue5_kb.cli --help

# OpenSpec
openspec list
openspec list --specs
openspec validate <change-id> --strict
openspec archive <change-id> --yes

# Git
git status
git diff
git log --oneline -10
```

### 获取帮助

- 查看 CLAUDE.md 获取快速参考
- 使用 `/ue5kb-dev-guide` 获取详细指导
- 阅读 openspec/AGENTS.md 了解规范流程
