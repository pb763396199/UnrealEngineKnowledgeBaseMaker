# Context Optimization 使用指南

> 基于 Context Engineering 理论的查询优化功能

---

## 功能概述

UE5-KB v2.2 引入了基于 Context Engineering 理论的查询优化功能，显著减少 Token 使用，提升 LLM 查询体验。

### 核心理念

1. **分层查询**：渐进式信息披露（摘要 → 详情 → 源码）
2. **Observation Masking**：屏蔽大型结果，使用引用ID
3. **Token 预算**：显式预算管理和自动优化

---

## 使用示例

### 1. 分层查询

#### Level 0: 摘要查询（~200 tokens）

```python
from ue5_kb.query.layered_query import LayeredQueryInterface

query = LayeredQueryInterface(kb_path="...")

# 查询类摘要
result = query.query_class("AActor", detail_level='summary')

# 返回（紧凑）：
{
    "name": "AActor",
    "module": "Engine",
    "parent": "UObject",
    "method_count": 45,
    "key_methods": ["BeginPlay", "Tick",  "Destroy", "GetWorld", "SetActorLocation"],
    "is_uclass": True,
    "ref_id": "ref_a3b2c1d4",
    "hint": "使用 query_class('AActor', 'details') 获取完整信息"
}
```

**Token 节省**: 原来需要返回45个方法的完整列表（~800 tokens），现在仅返回5个关键方法（~150 tokens）。

#### Level 1: 详情查询（~1000 tokens）

```python
# 使用类名或引用ID查询详情
result = query.query_class("AActor", detail_level='details')
# 或
result = query.query_class("ref_a3b2c1d4", detail_level='details')

# 返回（完整）：
{
    "name": "AActor",
    "module": "Engine",
    "parent_classes": ["UObject", "UObjectBase", "UObjectBaseUtility"],
    "interfaces": ["IGameplayTagAssetInterface"],
    "methods": [... 45个方法的完整列表 ...],
    "properties": [... 属性列表 ...],
    "file_path": "Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h",
    "line_number": 234,
    "source_ref": "ref_source_aactor"
}
```

####Level 2: 源码查询（~5000 tokens）

```python
# 使用源码引用ID
result = query.query_class("ref_source_aactor", detail_level='source')

# 返回：
{
    "class": "AActor",
    "source_code": "// 实际的C++源代码...",
    "warning": "源码内容可能很长，消耗大量 tokens"
}
```

### 2. Observation Masking（结果屏蔽）

```python
from ue5_kb.query.result_cache import ResultCache

cache = ResultCache(ttl_seconds=3600)

# 大型结果自动屏蔽
results = [... 100个函数 ...]
masked = cache.mask_large_result(results, threshold=5)

# 返回：
{
    "masked": True,
    "summary": "找到 100 个结果",
    "sample": [... 前5个 ...],
    "ref_id": "ref_8a7b6c5d",
    "tip": "使用 get_full_results('ref_8a7b6c5d') 查看完整列表"
}

# 按需获取完整结果
full_results = cache.retrieve("ref_8a7b6c5d")
```

**Token 节省**: 原来返回100个结果（~5000 tokens），现在返回摘要+5个样本（~500 tokens），节省90%。

### 3. Token 预算管理

```python
from ue5_kb.query.token_budget import TokenBudget, ContextCategory

# 获取全局预算管理器
budget = TokenBudget()

# 检查预算
if budget.allocate(ContextCategory.QUERY_RESULTS, 1500):
    # 在预算内
    return large_result
else:
    # 超出预算，自动触发优化
    # 输出警告并建议优化策略
    pass

# 查看预算统计
stats = budget.get_statistics()
print(stats)

# 输出：
{
    "query_results": {
        "budget": 2000,
        "usage": 1500,
        "utilization": "75.0%",
        "remaining": 500,
        "needs_optimization": False
    },
    "total": {
        "budget": 7000,
        "usage": 3200,
        "utilization": "45.7%",
        "remaining": 3800
    }
}
```

---

## 架构设计

### 查询流程（优化后）

```
LLM 查询: "AActor 类有哪些方法？"
      ↓
  1. 分析查询意图
      ↓
  2. 选择合适的详情层级（默认：summary）
      ↓
  3. 执行查询
      ↓
  4. 检查 Token 预算
      ↓
  5. 应用 Observation Masking（如果需要）
      ↓
  6. 返回优化结果
      ↓
LLM 收到：
  - 摘要信息（200 tokens）
  - 引用 ID（按需获取详情）
  - 提示：如何获取完整信息
```

### Token 预算分配

| 类别 | 预算 | 说明 | 可缓存 |
|------|------|------|-------|
| System Prompt | 500 tokens | 系统提示词 | ✅ 是 |
| Tool Definitions | 1000 tokens | 工具定义 | ✅ 是 |
| Query Results | 2000 tokens | 查询结果 | ❌ 否 |
| Message History | 3000 tokens | 对话历史 | ❌ 否 |
| Reserved | 500 tokens | 保留缓冲 | N/A |
| **总计** | **7000 tokens** | **工作集** | - |

**设计目标**：
- 工作集 < 10K tokens（留出190K给推理和生成）
- KV-cache 命中率 > 70%（稳定内容优先）

---

## 对比：优化前 vs 优化后

### 示例查询：查询 AActor 类

**优化前**：
```json
{
    "name": "AActor",
    "module": "Engine",
    "parent_classes": ["UObject", "UObjectBase", "UObjectBaseUtility"],
    "interfaces": ["IGameplayTagAssetInterface"],
    "methods": [
        "BeginPlay", "Tick", "EndPlay", "Destroy", "GetWorld",
        "SetActorLocation", "GetActorLocation", "SetActorRotation",
        ... // 45个方法
    ],
    "properties": [...],  // 20个属性
    "file_path": "...",
    "line_number": 234,
    ...
}
```
**Token 使用**: ~1000 tokens

**优化后（摘要层）**：
```json
{
    "name": "AActor",
    "module": "Engine",
    "parent": "UObject",
    "method_count": 45,
    "key_methods": ["BeginPlay", "Tick", "Destroy", "GetWorld", "SetActorLocation"],
    "is_uclass": True,
    "ref_id": "ref_a3b2c1d4",
    "hint": "使用 query_class('AActor', 'details') 获取完整信息"
}
```
**Token 使用**: ~150 tokens（**节省 85%**）

### 示例查询：搜索函数

**优化前**：
```json
{
    "function_name": "LoadTexture",
    "found_count": 15,
    "results": [
        {  // 完整结果1 },
        {  // 完整结果2 },
        ... // 15个完整结果
    ]
}
```
**Token 使用**: ~3000 tokens

**优化后（Observation Masking）**：
```json
{
    "masked": True,
    "summary": "找到 15 个结果",
    "sample": [
        {  // 结果1 },
        {  // 结果2 },
        {  // 结果3 }
    ],
    "ref_id": "ref_8a7b6c5d",
    "tip": "使用 get_full_results('ref_8a7b6c5d') 查看完整列表"
}
```
**Token 使用**: ~400 tokens（**节省 87%**）

---

## 集成到 Skill

### 更新 impl.py.template

```python
# 导入 Context Optimization 模块
from ue5_kb.query.layered_query import LayeredQueryInterface
from ue5_kb.query.result_cache import get_result_cache
from ue5_kb.query.token_budget import get_token_budget, ContextCategory

# 初始化
layered_query = LayeredQueryInterface(KB_PATH)
result_cache = get_result_cache()
token_budget = get_token_budget()

# 优化后的查询函数
def query_class_info(class_name: str, detail_level: str = 'summary'):
    """查询类信息（Context 优化版）"""
    # 使用分层查询
    result = layered_query.query_class(class_name, detail_level)

    # 记录 Token 使用
    tokens = estimate_tokens(result)
    token_budget.allocate(ContextCategory.QUERY_RESULTS, tokens)

    return result

def query_function_info(function_name: str, detail_level: str = 'summary'):
    """查询函数信息（Context 优化版）"""
    result = layered_query.query_function(function_name, detail_level)

    # 应用 Observation Masking（如果结果过大）
    if isinstance(result.get('results'), list) and len(result['results']) > 5):
        result = result_cache.mask_large_result(result['results'])

    return result
```

---

## 最佳实践

### 1. 默认使用摘要层

```python
# ✅ 推荐
result = query_class("AActor", "summary")  # 仅 150 tokens

# ❌ 避免（除非确实需要）
result = query_class("AActor", "details")  # 800 tokens
```

### 2. 利用引用ID机制

```python
# 第一次查询：获取摘要
summary = query_class("AActor", "summary")
ref_id = summary['ref_id']

# 如果LLM需要更多信息，使用ref_id
details = query_class(ref_id, "details")
```

### 3. 监控 Token 预算

```python
# 定期检查预算使用
budget = get_token_budget()
stats = budget.get_statistics()

if stats['query_results']['needs_optimization']:
    # 触发优化：使用 masking 或清理缓存
    result_cache.cleanup_expired()
```

---

## 性能指标

### Token 使用对比

| 查询类型 | 优化前 | 优化后 | 节省 |
|---------|--------|--------|------|
| 类信息查询 | ~1000 tokens | ~200 tokens | 80% |
| 函数搜索（15结果） | ~3000 tokens | ~400 tokens | 87% |
| 模块依赖 | ~300 tokens | ~300 tokens | 0%（已优化） |

### 总体效果

- **平均 Token 减少**: 70-85%
- **KV-cache 友好**: 稳定的 system prompt 和工具定义
- **用户体验**: 更快的响应，更清晰的信息层次

---

## 未来扩展

- **自适应层级**: 根据查询复杂度自动选择详情层级
- **智能预加载**: 根据查询模式预测并预加载可能需要的详情
- **Context 压缩**: 自动压缩对话历史和旧的查询结果

---

## 参考资料

- [Context Optimization Skill](https://github.com/context-engineering/skills/context-optimization)
- [Observation Masking Pattern](https://arxiv.org/abs/...)
- [Token Budget Management](https://docs.anthropic.com/en/docs/build-with-claude/token-management)
