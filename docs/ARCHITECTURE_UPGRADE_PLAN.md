# UE5 Knowledge Base Maker - 架构升级计划

> 基于 Agent Skills for Context Engineering 的架构优化方案

## 执行摘要

当前系统已实现基础的 context optimization（分层查询、observation masking、token budget），但架构上存在以下可优化点：

1. **Pipeline 架构不够清晰** - 构建流程耦合度高，难以独立迭代
2. **文件系统作为状态机未充分利用** - 缺少阶段性检查点和幂等性设计
3. **Context 优化未完全集成** - 现有的 layered_query 等模块未集成到生成的 Skill 中
4. **缺少 Multi-Agent 分区** - 大型引擎扫描时可能遇到 context 限制
5. **工具设计可简化** - 过多专用查询函数，应考虑架构精简

---

## 优化方向 1: Pipeline 架构重构

### 当前问题

当前的 `GlobalIndexBuilder.build_all()` 是单体流程：
```python
def build_all():
    scan_all_build_cs_files()    # 扫描
    build_dependency_graph()      # 构建依赖
    save()                        # 保存
    build_all_module_graphs()     # 构建代码图谱
```

问题：
- 所有阶段耦合在一个函数中
- 中间结果未持久化，无法独立重跑某个阶段
- 调试困难，必须重跑整个流程

### 优化方案：五阶段 Pipeline

参考 Context Engineering 的 **Pipeline Architecture** 模式：

```
acquire → prepare → process → parse → render
```

**应用到 UE5-KB：**

```
discover → extract → analyze → build → generate
```

#### 阶段 1: Discover (发现模块)

**输入**: 引擎/插件根路径
**输出**: `data/discovery/{engine_version}/modules.json`

```json
{
  "modules": [
    {
      "name": "Core",
      "path": "Engine/Source/Runtime/Core/Core.Build.cs",
      "category": "Runtime"
    }
  ],
  "discovered_at": "2026-02-02T10:00:00Z",
  "total_count": 1757
}
```

**特征**:
- 纯文件系统操作，确定性
- 可独立重跑：`ue5kb discover --engine-path ...`
- 输出文件存在 = 阶段完成

#### 阶段 2: Extract (提取依赖)

**输入**: `modules.json`
**输出**: `data/extract/{module_name}/dependencies.json`

每个模块一个文件：
```json
{
  "module": "Core",
  "public_deps": ["TraceLog"],
  "private_deps": [],
  "parsed_at": "2026-02-02T10:01:00Z"
}
```

**特征**:
- 并行化友好（每个模块独立）
- 失败隔离（单个模块失败不影响其他）
- 可增量更新（仅重新解析修改的 .Build.cs）

#### 阶段 3: Analyze (分析代码结构)

**输入**: `data/extract/{module_name}/dependencies.json`
**输出**: `data/analyze/{module_name}/code_graph.json`

提取类、函数、继承关系：
```json
{
  "module": "Core",
  "classes": [
    {
      "name": "UObject",
      "parent": "UObjectBase",
      "methods": ["BeginDestroy", "FinishDestroy"],
      "file": "UObject.h",
      "line": 234
    }
  ],
  "analyzed_at": "2026-02-02T10:05:00Z"
}
```

**特征**:
- **最昂贵的阶段**（C++ 解析）
- 独立于其他模块，可并行
- 输出可缓存，修改后只重新分析变更的模块

#### 阶段 4: Build (构建索引)

**输入**: `data/analyze/` 所有模块
**输出**: `KnowledgeBase/global_index/`, `KnowledgeBase/module_graphs/`

将 JSON 转换为优化的存储格式（SQLite + Pickle）

**特征**:
- 确定性（给定相同输入，输出相同）
- 快速（仅数据转换和序列化）
- 可验证（检查生成的文件完整性）

#### 阶段 5: Generate (生成 Skill)

**输入**: `KnowledgeBase/`
**输出**: `~/.claude/skills/ue5kb-{version}/`

从模板生成 Skill 文件

**特征**:
- 最快的阶段
- 可独立重新生成 Skill（测试不同模板）
- 无副作用

### 实施方案

**新增 CLI 命令：**

```bash
# 运行完整 pipeline（等同于当前的 init）
ue5kb pipeline run --engine-path "D:/UE5"

# 运行特定阶段
ue5kb pipeline discover --engine-path "D:/UE5"
ue5kb pipeline extract
ue5kb pipeline analyze --parallel 8
ue5kb pipeline build
ue5kb pipeline generate

# 检查 pipeline 状态
ue5kb pipeline status

# 清理特定阶段（重跑）
ue5kb pipeline clean analyze
```

**目录结构：**

```
D:\Unreal Engine\UnrealEngine51_500\
├── data/                       # Pipeline 中间数据（新增）
│   ├── discovery/
│   │   └── modules.json
│   ├── extract/
│   │   ├── Core/
│   │   │   └── dependencies.json
│   │   └── Engine/
│   │       └── dependencies.json
│   └── analyze/
│       ├── Core/
│       │   └── code_graph.json
│       └── Engine/
│           └── code_graph.json
├── KnowledgeBase/              # 最终输出（保持不变）
│   ├── global_index/
│   └── module_graphs/
└── .pipeline_state             # Pipeline 状态文件（新增）
```

**状态文件示例：**

```json
{
  "engine_version": "5.1.500",
  "stages": {
    "discover": {
      "completed": true,
      "completed_at": "2026-02-02T10:00:00Z",
      "output": "data/discovery/modules.json"
    },
    "extract": {
      "completed": true,
      "completed_at": "2026-02-02T10:10:00Z",
      "modules_processed": 1757,
      "failed_modules": []
    },
    "analyze": {
      "completed": false,
      "modules_processed": 856,
      "modules_total": 1757
    }
  }
}
```

**优势：**

1. **调试友好**: 每个阶段的输出都是可读的 JSON
2. **增量构建**: 修改代码后只需重跑受影响的阶段
3. **并行化**: Extract 和 Analyze 阶段可高度并行
4. **容错性**: 单个模块失败不影响其他模块
5. **可视化**: 可以生成进度报告和失败日志

---

## 优化方向 2: 完整集成 Context Optimization

### 当前问题

Context optimization 模块已实现（`query/layered_query.py`, `result_cache.py`, `token_budget.py`），但：

1. **未集成到生成的 Skill** - `impl.py.template` 仍使用旧的直接查询方式
2. **未完全实现** - `LayeredQueryInterface._load_class_info()` 是占位符
3. **缺少使用文档** - 用户不知道如何使用分层查询

### 优化方案

#### 2.1 更新 Skill 模板

**当前 `impl.py.template` 结构：**

```python
def query_class_info(class_name: str) -> Dict:
    # 直接查询，返回完整信息（~1000 tokens）
    ...
```

**优化后结构：**

```python
# 导入 Context Optimization 模块
from ue5_kb.query.layered_query import LayeredQueryInterface
from ue5_kb.query.result_cache import get_result_cache
from ue5_kb.query.token_budget import get_token_budget, ContextCategory

# 初始化
_layered_query = LayeredQueryInterface(str(KB_PATH))
_result_cache = get_result_cache()
_token_budget = get_token_budget()

def query_class_info(class_name: str, detail_level: str = 'summary') -> Dict:
    """
    查询类信息（Context 优化版）

    Args:
        class_name: 类名
        detail_level: 详情级别 ('summary' | 'details' | 'source')

    Returns:
        分层的查询结果

    Token 使用:
        - summary: ~200 tokens (推荐)
        - details: ~1000 tokens
        - source: ~5000 tokens
    """
    result = _layered_query.query_class(class_name, detail_level)

    # 记录 Token 使用
    tokens = _estimate_tokens(result)
    _token_budget.allocate(ContextCategory.QUERY_RESULTS, tokens)

    return result

def query_function_info(function_name: str, detail_level: str = 'summary') -> Dict:
    """查询函数信息（Context 优化版）"""
    result = _layered_query.query_function(function_name, detail_level)

    # 应用 Observation Masking（如果结果过大）
    if isinstance(result.get('matches'), list) and len(result['matches']) > 5:
        result = _result_cache.mask_large_result(result['matches'])

    return result

def get_token_budget_stats() -> Dict:
    """获取 Token 预算统计（调试用）"""
    return _token_budget.get_statistics()
```

#### 2.2 完善 LayeredQueryInterface

**当前占位符实现需要补全：**

```python
def _load_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
    """加载类信息（占位符，实际会调用现有接口）"""
    # TODO: 集成现有的 query_class_info
    return None
```

**完善后：**

```python
def _load_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
    """加载类信息（真实实现）"""
    # 1. 从 global_index 查找模块
    config = Config(str(self.kb_path / "config.yaml"))
    global_index = GlobalIndex(config)

    module_name = self._find_module_for_class(class_name, global_index)
    if not module_name:
        return None

    # 2. 加载 module_graph
    graph_file = self.kb_path / "module_graphs" / f"{module_name}.pkl"
    if not graph_file.exists():
        return None

    with open(graph_file, 'rb') as f:
        data = pickle.load(f)
        graph = data.get('graph')

    # 3. 提取类信息
    class_node = f"class_{class_name}"
    if class_node not in graph.nodes:
        return None

    node_data = graph.nodes[class_node]

    # 4. 查找父类和方法
    parent_classes = [
        graph.nodes[pred]['name']
        for pred in graph.predecessors(class_node)
        if pred.startswith('class_')
    ]

    methods = [
        graph.nodes[succ]['name']
        for succ in graph.successors(class_node)
        if succ.startswith('method_')
    ]

    return {
        'module': module_name,
        'parent_classes': parent_classes,
        'methods': methods,
        'file': node_data.get('file'),
        'line': node_data.get('line'),
        'is_uclass': node_data.get('is_uclass', False),
        'is_blueprint': node_data.get('is_blueprint', False)
    }
```

#### 2.3 添加 Token 预算监控

**Skill 添加监控命令：**

```python
def monitor_token_usage():
    """监控 Token 使用情况"""
    stats = _token_budget.get_statistics()

    print("Token 预算使用情况：")
    print("-" * 50)
    for category, data in stats.items():
        if category != "total":
            status = "⚠️" if data['needs_optimization'] else "✓"
            print(f"{status} {category}: {data['usage']}/{data['budget']} ({data['utilization']})")

    print("-" * 50)
    print(f"总计: {stats['total']['usage']}/{stats['total']['budget']} ({stats['total']['utilization']})")

    return stats
```

---

## 优化方向 3: Context Partitioning（多 Agent 分区）

### 当前问题

扫描大型引擎（1757+ 模块）时：
- 单个 Agent 需要处理所有模块的 context
- 可能遇到 context 限制（即使使用 SQLite 优化）
- 失败时需要重跑整个流程

### 优化方案：Sub-Agent 分区

**设计原则（来自 Context Engineering）:**

> "The most aggressive form of context optimization is partitioning work across sub-agents with isolated contexts. Each sub-agent operates in a clean context focused on its subtask."

**应用到 UE5-KB：按模块分类分区**

```
主 Agent (Coordinator)
    ├─→ Sub-Agent 1: Runtime 模块 (712 个)
    ├─→ Sub-Agent 2: Editor 模块 (600+ 个)
    ├─→ Sub-Agent 3: Plugins 模块 (991 个)
    └─→ Sub-Agent 4: Platforms 模块 (54 个)
```

**实施方案：**

```python
class PartitionedIndexBuilder:
    """
    分区索引构建器

    将大型引擎扫描任务分配给多个 sub-agent
    """

    PARTITIONS = {
        'runtime': {'pattern': 'Engine/Source/Runtime/**', 'priority': 1},
        'editor': {'pattern': 'Engine/Source/Editor/**', 'priority': 2},
        'plugins': {'pattern': 'Engine/Plugins/**', 'priority': 3},
        'platforms': {'pattern': 'Engine/Platforms/**', 'priority': 4}
    }

    def build_partitioned(self, engine_path: Path) -> Dict[str, Any]:
        """使用分区构建"""
        results = {}

        for partition_name, config in self.PARTITIONS.items():
            print(f"启动 Sub-Agent: {partition_name}")

            # 每个 partition 在独立的 context 中处理
            result = self._process_partition(
                engine_path,
                pattern=config['pattern'],
                partition_name=partition_name
            )

            results[partition_name] = result

            # 保存中间结果
            self._save_partition_result(partition_name, result)

        # 合并所有 partition 的结果
        merged = self._merge_results(results)

        return merged

    def _process_partition(
        self,
        engine_path: Path,
        pattern: str,
        partition_name: str
    ) -> Dict[str, Any]:
        """
        处理单个分区（在独立 context 中）

        这个函数可以被 Task tool 调用，创建独立的 sub-agent
        """
        # 扫描该分区的模块
        modules = self._discover_modules(engine_path, pattern)

        # 提取依赖
        dependencies = self._extract_dependencies(modules)

        # 构建子图
        sub_graph = self._build_sub_graph(dependencies)

        return {
            'partition': partition_name,
            'modules': modules,
            'module_count': len(modules),
            'sub_graph': sub_graph,
            'processed_at': datetime.now().isoformat()
        }

    def _merge_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并所有 partition 的结果

        这一步在 coordinator agent 的 context 中进行
        """
        merged_modules = {}
        merged_graph = nx.DiGraph()

        for partition_name, result in results.items():
            # 合并模块列表
            merged_modules.update(result['modules'])

            # 合并依赖图
            merged_graph = nx.compose(merged_graph, result['sub_graph'])

        return {
            'total_modules': len(merged_modules),
            'total_edges': merged_graph.number_of_edges(),
            'partitions': list(results.keys()),
            'merged_at': datetime.now().isoformat()
        }
```

**CLI 支持：**

```bash
# 使用分区模式构建（适用于大型引擎）
ue5kb init --engine-path "D:/UE5" --partitioned

# 仅构建特定分区
ue5kb init --engine-path "D:/UE5" --partition runtime
```

**优势：**

1. **Context 隔离** - 每个 sub-agent 只处理一部分模块，context 更干净
2. **并行化** - 多个 partition 可以并行处理
3. **容错性** - 一个 partition 失败不影响其他
4. **增量更新** - 仅重新处理变更的 partition

---

## 优化方向 4: 工具架构精简（Architectural Reduction）

### 当前问题

生成的 Skill 包含多个专用查询函数：
- `query_module_dependencies()`
- `search_modules()`
- `query_class_info()`
- `query_class_hierarchy()`
- `query_module_classes()`
- `query_function_info()`
- `search_classes()`

**问题（来自 Context Engineering Skill）:**

> "Production evidence shows that removing specialized tools often improves performance. Vercel's d0 agent achieved 100% success rate by reducing from 17 specialized tools to 2 primitives."

### 优化方案：精简为核心查询接口

**当前：17 个专用函数**
**优化后：3 个通用接口**

```python
# 1. 通用查询接口（支持 natural language query）
def query(question: str, detail_level: str = 'summary') -> Dict:
    """
    通用查询接口（自然语言）

    Examples:
        query("Core 模块有哪些依赖？")
        query("AActor 类继承自什么？")
        query("有多少个 Runtime 模块？")

    Args:
        question: 自然语言问题
        detail_level: 'summary' | 'details' | 'source'

    Returns:
        查询结果（自动应用 context optimization）
    """
    # 使用 LLM 理解意图，路由到合适的查询
    ...

# 2. 直接访问接口（给 LLM 使用，类似 bash/SQL）
def direct_query(
    query_type: str,
    target: str,
    **filters
) -> Dict:
    """
    直接查询接口（结构化）

    Args:
        query_type: 'module' | 'class' | 'function'
        target: 查询目标（模块名、类名、函数名）
        **filters: 额外过滤条件

    Examples:
        direct_query('module', 'Core', include_dependencies=True)
        direct_query('class', 'AActor', detail_level='summary')
        direct_query('function', 'BeginPlay', in_class='AActor')
    """
    ...

# 3. 统计接口
def stats(category: Optional[str] = None) -> Dict:
    """
    获取统计信息

    Args:
        category: 可选的分类过滤（'Runtime', 'Editor', 等）
    """
    ...
```

**为什么精简更好？**

1. **减少 LLM 选择负担** - 17 个函数 vs 3 个函数
2. **更符合自然交互** - 用户问问题，不需要知道具体函数名
3. **灵活性更高** - 通用接口可以处理组合查询
4. **维护成本更低** - 核心逻辑集中，易于优化

**但何时不应该精简？**

- 如果知识库结构复杂且不一致（当前 UE5-KB 结构清晰）
- 如果需要严格的类型安全（当前是动态 Python）
- 如果模型推理能力不足（Claude Sonnet 已足够强大）

**建议：**

- 保留当前的 17 个专用函数作为 **底层实现**
- 对外暴露 3 个通用接口作为 **用户 API**
- 让 LLM 根据问题自动选择调用哪个底层函数

---

## 优化方向 5: 增量更新支持

### 当前问题

修改引擎代码后，必须重新扫描整个引擎（1757+ 模块，30-60 分钟）

### 优化方案：基于文件系统的增量更新

**设计原则：**

Pipeline 的每个阶段都是幂等的，输出基于输入的哈希值

**实施方案：**

```python
class IncrementalIndexBuilder:
    """
    增量索引构建器

    仅重新处理修改的模块
    """

    def __init__(self, engine_path: Path, kb_path: Path):
        self.engine_path = engine_path
        self.kb_path = kb_path
        self.manifest_file = kb_path / ".manifest.json"

    def build_incremental(self) -> Dict[str, Any]:
        """增量构建"""
        # 1. 加载上次的 manifest
        last_manifest = self._load_manifest()

        # 2. 扫描当前的模块和文件
        current_manifest = self._scan_current_state()

        # 3. 计算差异
        diff = self._compute_diff(last_manifest, current_manifest)

        print(f"变更统计：")
        print(f"  新增模块: {len(diff['added_modules'])}")
        print(f"  修改模块: {len(diff['modified_modules'])}")
        print(f"  删除模块: {len(diff['removed_modules'])}")

        # 4. 仅重新处理变更的模块
        if diff['modified_modules']:
            self._rebuild_modules(diff['modified_modules'])

        # 5. 更新 global_index
        self._update_global_index(diff)

        # 6. 保存新的 manifest
        self._save_manifest(current_manifest)

        return {
            'incremental': True,
            'modules_updated': len(diff['modified_modules']),
            'time_saved': self._estimate_time_saved(diff)
        }

    def _compute_diff(
        self,
        old: Dict[str, Any],
        new: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """计算差异"""
        old_modules = set(old.get('modules', {}).keys())
        new_modules = set(new.get('modules', {}).keys())

        added = new_modules - old_modules
        removed = old_modules - new_modules
        potential_modified = old_modules & new_modules

        # 检查文件哈希，找出真正修改的模块
        modified = []
        for module_name in potential_modified:
            old_hash = old['modules'][module_name]['hash']
            new_hash = new['modules'][module_name]['hash']
            if old_hash != new_hash:
                modified.append(module_name)

        return {
            'added_modules': list(added),
            'modified_modules': modified,
            'removed_modules': list(removed)
        }

    def _scan_current_state(self) -> Dict[str, Any]:
        """扫描当前状态并计算哈希"""
        manifest = {'modules': {}, 'scanned_at': datetime.now().isoformat()}

        # 扫描所有 .Build.cs 文件
        for build_cs in self.engine_path.rglob('**/*.Build.cs'):
            module_name = build_cs.stem.replace('.Build', '')

            # 计算模块的哈希（基于 .Build.cs 和所有源文件）
            module_hash = self._compute_module_hash(build_cs.parent)

            manifest['modules'][module_name] = {
                'path': str(build_cs),
                'hash': module_hash
            }

        return manifest

    def _compute_module_hash(self, module_dir: Path) -> str:
        """计算模块的哈希值"""
        import hashlib

        hasher = hashlib.sha256()

        # 包含所有源文件
        for ext in ['*.h', '*.cpp', '*.Build.cs']:
            for file in sorted(module_dir.rglob(ext)):
                with open(file, 'rb') as f:
                    hasher.update(f.read())

        return hasher.hexdigest()
```

**CLI 支持：**

```bash
# 增量更新
ue5kb update

# 强制完全重建
ue5kb update --full

# 仅更新特定模块
ue5kb update --modules Core,Engine
```

---

## 实施路线图

### 第一阶段：Pipeline 重构（高优先级）

**时间：2-3 天**

1. 实现五阶段 Pipeline 架构
2. 添加状态文件和检查点机制
3. 支持独立运行每个阶段
4. 更新 CLI 命令

**收益：**
- 调试效率提升 5-10x
- 支持增量构建
- 更好的错误处理

### 第二阶段：Context Optimization 集成（中优先级）

**时间：1-2 天**

1. 完善 `LayeredQueryInterface` 的占位符实现
2. 更新 `impl.py.template` 使用分层查询
3. 添加 Token 预算监控
4. 编写使用文档和示例

**收益：**
- Token 使用减少 70-85%
- 查询响应更快
- 更好的用户体验

### 第三阶段：分区构建支持（中优先级）

**时间：2-3 天**

1. 实现 `PartitionedIndexBuilder`
2. 支持按分类分区
3. 添加结果合并逻辑
4. 更新 CLI 支持 `--partitioned` 选项

**收益：**
- 支持更大规模的引擎
- 并行化提升性能
- 更好的容错性

### 第四阶段：工具精简（低优先级）

**时间：1 天**

1. 实现通用查询接口
2. 保留专用函数作为底层实现
3. 添加意图识别和路由逻辑
4. A/B 测试对比效果

**收益：**
- 更简洁的 API
- 更自然的交互
- 可能提升成功率（需验证）

### 第五阶段：增量更新（低优先级）

**时间：2 天**

1. 实现 manifest 和哈希机制
2. 差异计算和选择性重建
3. 更新 CLI 支持 `update` 命令
4. 添加性能指标

**收益：**
- 更新时间从 30-60 分钟减少到 1-5 分钟
- 更好的开发体验

---

## 性能预期

### 构建时间对比

| 场景 | 当前 | Pipeline 重构 | + 分区 | + 增量 |
|------|------|--------------|-------|--------|
| 首次完整构建 | 30-60 分钟 | 30-60 分钟 | 20-40 分钟 | 20-40 分钟 |
| 修改 1 个模块后重建 | 30-60 分钟 | 5-10 分钟 | 2-5 分钟 | **1-2 分钟** |
| 调试特定阶段 | 30-60 分钟 | **<1 分钟** | <1 分钟 | <1 分钟 |

### Token 使用对比

| 查询类型 | 当前 | Context Optimization |
|---------|------|---------------------|
| 类信息查询 | ~1000 tokens | **~200 tokens (-80%)** |
| 函数搜索（15 结果） | ~3000 tokens | **~400 tokens (-87%)** |
| 模块依赖查询 | ~300 tokens | ~300 tokens (已优化) |

---

## 风险和注意事项

### 风险 1: Pipeline 重构可能引入 Bug

**缓解措施：**
- 保留原有的单体流程作为 fallback
- 添加 `--legacy` 选项使用旧流程
- 充分测试每个阶段的输出

### 风险 2: Context Optimization 可能降低准确性

**缓解措施：**
- 在 summary 层保留关键信息
- 提供简单的方式获取详细信息（ref_id）
- A/B 测试对比质量

### 风险 3: 工具精简可能降低成功率

**缓解措施：**
- 先实现通用接口，与专用函数并存
- 收集实际使用数据对比效果
- 如果效果不佳，保留专用函数

### 风险 4: 增量更新可能遗漏依赖变更

**缓解措施：**
- 哈希计算包含 .Build.cs 文件
- 提供 `--full` 选项强制完全重建
- 定期进行完全重建验证

---

## 总结

本升级计划基于 **Agent Skills for Context Engineering** 的最佳实践，针对 UE5 Knowledge Base Maker 提出了五个优化方向：

1. **Pipeline 架构重构** - 提升调试效率和增量构建能力
2. **Context Optimization 集成** - 减少 Token 使用 70-85%
3. **分区构建支持** - 支持更大规模和更好并行化
4. **工具架构精简** - 简化 API，提升用户体验
5. **增量更新支持** - 更新时间从 30-60 分钟减少到 1-2 分钟

**推荐实施顺序：**
1. Pipeline 重构（最高 ROI）
2. Context Optimization 集成（快速见效）
3. 分区构建支持（扩展能力）
4. 其他优化（根据实际需求决定）

**预期收益：**
- 开发效率提升 5-10x
- Token 使用减少 70-85%
- 支持更大规模的引擎
- 更好的用户体验

---

## 附录：参考资料

### Context Engineering 核心原则

1. **Pipeline Architecture** - 分阶段、幂等、可缓存
2. **File System as State Machine** - 文件存在 = 阶段完成
3. **Observation Masking** - 屏蔽大型输出，使用引用
4. **Context Partitioning** - Sub-agent 隔离 context
5. **Architectural Reduction** - 精简工具，提升效果

### 相关技能

- `agent-architecture:project-development` - Pipeline 设计原则
- `agent-architecture:context-optimization` - Context 优化技术
- `agent-architecture:multi-agent-patterns` - 分区模式
- `agent-architecture:tool-design` - 工具精简原则

### 案例研究

- **Karpathy's HN Time Capsule** - 5-stage pipeline, file system state
- **Vercel d0** - 17 tools → 2 tools, 80% → 100% success rate
- **Manus Context Engineering** - Multiple architectural iterations
