# Change: Fix Query Fallback - Prevent LLM Hallucination When Knowledge Base Query Fails

## ID
fix-query-fallback

## Status
IMPLEMENTED

## Created
2026-02-04

## Why

当前工具创建的知识库和 Skill 有严重的缺陷：当无法从知识库中检索到信息时，大语言模型会乱回答（基于训练数据/幻觉）而不是使用工具进行模糊搜索。

**根本原因**:
1. **Skill Prompt 引导不足** - 没有明确指示 LLM 在查询失败时的降级策略
2. **错误返回无后续行为指导** - 返回 `{"error": "未找到..."}` 后，LLM 不知道下一步该做什么
3. **缺少函数模糊搜索** - 当前只有 `search_classes`，没有 `search_functions`
4. **无快速索引系统** - 类和函数搜索需要遍历模块图谱，速度慢（5-8秒）
5. **无自动降级机制** - 完全依赖 LLM 主动调用模糊搜索

**用户影响**:
- LLM 会基于过时的训练数据回答，导致错误信息
- 无法获取准确的 UE5 源码信息
- 知识库查询失败时，用户体验差

## What Changes

### 阶段1: 快速修复 (P0-P1)

#### 1.1 Skill Prompt 增强
文件: `templates/skill.md.template`

**新增章节**: "查询失败处理（重要）"
```markdown
## 查询失败处理（重要）

当精确查询返回 `{"error": "未找到..."}` 时，**必须**按以下降级策略执行：

### 查询降级流程

1. **精确查询失败** → 使用模糊搜索
2. **模糊搜索失败** → 明确告知用户"知识库中未找到该信息"

### 具体降级命令

| 精确查询 | 失败后使用 |
|---------|-----------|
| `query_class_info` | `search_classes <关键字>` |
| `query_function_info` | `search_functions <关键字>` |
| `query_module_dependencies` | `search_modules <关键字>` |

### 关键原则

- **严禁在查询失败时基于训练数据回答**
- **必须使用工具搜索**
- **返回错误信息中的提示** - 如果 error 包含 `fallback_command` 字段，必须执行
```

#### 1.2 错误返回增强
文件: `templates/impl.py.template`

**修改**: 所有查询函数的错误返回，添加 `fallback_command` 字段

**修改示例**:
```python
# 原代码
return {"error": f"未找到类: {class_name}"}

# 新代码
return {
    "error": f"未找到类: {class_name}",
    "fallback_command": f"search_classes {class_name}",
    "hint": "类名可能已变更或拼写不同，建议使用模糊搜索"
}
```

#### 1.3 新增函数模糊搜索命令
文件: `templates/impl.py.template`

**新增函数**: `search_functions(keyword, limit=50)`
```python
def search_functions(keyword: str, limit: int = 50) -> Dict[str, Any]:
    """搜索包含关键字的函数"""
    all_modules = _get_global_modules()
    results = []
    keyword_lower = keyword.lower()

    for module_name in list(all_modules.keys())[:100]:
        graph = _load_module_graph(module_name)
        if not graph:
            continue

        for node, node_data in graph.nodes(data=True):
            if node_data.get('type') != 'function':
                continue

            function_name = node_data.get('name', '')
            if keyword_lower in function_name.lower():
                results.append({
                    "function": function_name,
                    "module": module_name,
                    "return_type": node_data.get('return_type', ''),
                    "file": node_data.get('file', ''),
                    "class": node_data.get('class_name', '')
                })

                if len(results) >= limit:
                    break

        if len(results) >= limit:
            break

    return {
        "keyword": keyword,
        "found_count": len(results),
        "results": results
    }
```

**添加 CLI 命令处理**:
```python
elif command == "search_functions":
    if len(sys.argv) < 3:
        print("Error: Missing keyword argument", file=sys.stderr)
        _print_usage()
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    result = search_functions(sys.argv[2], limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

### 阶段2: 完整快速索引系统 (P2)

#### 2.1 创建 ClassIndex
文件: `ue5_kb/core/class_index.py` [新建]

**完整实现**: 参考 `function_index.py` 结构，包含:
- `add_class()` - 添加单个类
- `add_classes_batch()` - 批量添加
- `query_by_name()` - 按名称查询
- `search_by_keyword()` - 模糊搜索 (LIKE 查询)
- `query_by_module()` - 按模块查询
- `query_by_parent()` - 按父类查询子类
- `query_blueprintable()` - 查询 Blueprintable 类

#### 2.2 增强 FunctionIndex
文件: `ue5_kb/core/function_index.py`

**新增方法**:
```python
def search_by_keyword(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按关键字模糊搜索函数"""
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT * FROM function_index
        WHERE name LIKE ?
        ORDER BY is_blueprint_callable DESC, name ASC
        LIMIT ?
    """, (f'%{keyword}%', limit))
    return [self._row_to_dict(row) for row in cursor.fetchall()]
```

#### 2.3 在 BuildStage 构建索引
文件: `ue5_kb/pipeline/build.py`

**新增方法**: `_build_fast_indices(config)`
```python
def _build_fast_indices(self, config: Config) -> None:
    """构建快速索引（ClassIndex 和 FunctionIndex）"""
    from ..core.class_index import ClassIndex
    from ..core.function_index import FunctionIndex

    print(f"  构建快速索引...")

    class_idx = ClassIndex(str(config.global_index_path / "class_index.db"))
    func_idx = FunctionIndex(str(config.global_index_path / "function_index.db"))

    # 遍历所有模块图谱，收集类和函数信息
    graphs_dir = Path(config.module_graphs_path)

    classes_batch = []
    functions_batch = []

    for graph_file in graphs_dir.glob("*.pkl"):
        # ... 收集数据 ...

        # 批量提交（每 1000 条）
        if len(classes_batch) >= 1000:
            class_idx.add_classes_batch(classes_batch)
            classes_batch.clear()

    # 提交剩余数据
    class_idx.commit()
    func_idx.commit()
```

**在 `run()` 方法中调用**:
```python
# 4. 构建快速索引
self._build_fast_indices(config)
```

### 阶段3: 性能优化 (P3)

#### 3.1 更新 impl.py.template 使用索引
文件: `templates/impl.py.template`

**新增全局变量**:
```python
# 快速索引缓存
_class_index_cache = None
_function_index_cache = None
```

**新增辅助函数**:
```python
def _get_class_index():
    """获取类索引"""
    global _class_index_cache
    if _class_index_cache is None:
        from ue5_kb.core.class_index import ClassIndex
        db_path = KB_PATH / "global_index" / "class_index.db"
        if db_path.exists():
            _class_index_cache = ClassIndex(str(db_path))
    return _class_index_cache

def _get_function_index():
    """获取函数索引"""
    global _function_index_cache
    if _function_index_cache is None:
        from ue5_kb.core.function_index import FunctionIndex
        db_path = KB_PATH / "global_index" / "function_index.db"
        if db_path.exists():
            _function_index_cache = FunctionIndex(str(db_path))
    return _function_index_cache
```

**修改 `search_classes` 使用索引**:
```python
def search_classes(keyword: str, limit: int = 50) -> Dict[str, Any]:
    """搜索包含关键字的类"""
    class_idx = _get_class_index()

    if class_idx:
        # 使用索引搜索（快速 < 10ms）
        results = class_idx.search_by_keyword(keyword, limit)
        return {
            "keyword": keyword,
            "found_count": len(results),
            "results": results
        }
    else:
        # 回退到遍历搜索（慢速 ~5s）
        # ... 原有代码 ...
```

**修改 `search_functions` 使用索引**:
```python
def search_functions(keyword: str, limit: int = 50) -> Dict[str, Any]:
    """搜索包含关键字的函数"""
    func_idx = _get_function_index()

    if func_idx:
        # 使用索引搜索（快速 < 10ms）
        results = func_idx.search_by_keyword(keyword, limit)
        return {
            "keyword": keyword,
            "found_count": len(results),
            "results": results
        }
    else:
        # 回退到遍历搜索（慢速 ~8s）
        # ... 原有代码 ...
```

#### 3.2 插件模式同步
文件: `templates/impl.plugin.py.template`

**同步修改**: 应用与 `impl.py.template` 相同的所有修改

## Impact

### Affected specs
- 无

### Affected code
**新建文件**:
- `ue5_kb/core/class_index.py` - 类快速索引

**修改文件（模板）**:
- `templates/skill.md.template` - 添加查询失败处理章节
- `templates/impl.py.template` - 错误增强、search_functions、使用索引
- `templates/impl.plugin.py.template` - 同步修改

**修改文件（核心）**:
- `ue5_kb/core/function_index.py` - 添加 search_by_keyword
- `ue5_kb/pipeline/build.py` - 添加索引构建逻辑

### Backward compatibility
- 完全向后兼容
- 旧版本生成的知识库可以继续使用
- 新索引由 Pipeline 自动构建

### Performance impact
**性能提升**:
- 类搜索：从 ~5s → <10ms (**500x**)
- 函数搜索：从 ~8s → <10ms (**800x**)
- 模糊搜索：从不支持 → <20ms (**新增**)

**构建时间影响**:
- Pipeline 构建阶段增加约 5-10%（索引构建）
- 总体影响 < 2%

## Testing Plan

### 单元测试
1. 测试 ClassIndex 的 CRUD 操作
2. 测试 FunctionIndex 的 search_by_keyword
3. 测试错误返回包含 fallback_command

### 集成测试
```bash
# 1. 重新安装包（所有阶段）
pip install -e . --force-reinstall --no-deps

# 2. 重新生成知识库
ue5kb init --engine-path "D:\UnrealEngine\UnrealEngine" --force

# 3. 验证索引文件生成
ls KnowledgeBase/global_index/class_index.db
ls KnowledgeBase/global_index/function_index.db

# 4. 测试查询失败场景
python "~/.claude/skills/ue5kb-5.5.4/impl.py" query_function_info RHICreateTexture2D
# 预期: 返回 error + fallback_command

# 5. 测试模糊搜索
python "~/.claude/skills/ue5kb-5.5.4/impl.py" search_functions RHICreate
# 预期: 返回相关函数列表

# 6. 测试性能
time python "~/.claude/skills/ue5kb-5.5.4/impl.py" search_classes Actor
# 预期: < 100ms
```

### 验证清单
**阶段1 (快速修复)**:
- [ ] Skill 包含"查询失败处理"章节
- [ ] query_class_info 失败返回 fallback_command
- [ ] query_function_info 失败返回 fallback_command
- [ ] search_functions 命令可用
- [ ] Skill 命令列表包含 search_functions

**阶段2 (完整功能)**:
- [ ] class_index.py 文件存在
- [ ] ClassIndex.search_by_keyword 可用
- [ ] FunctionIndex.search_by_keyword 可用
- [ ] BuildStage 构建索引成功
- [ ] 索引文件生成

**阶段3 (性能优化)**:
- [ ] search_classes 使用索引 (< 100ms)
- [ ] search_functions 使用索引 (< 100ms)
- [ ] 插件模式同步完成

### 用户体验测试
```
用户: "RHICreateTexture2D 函数怎么用？"

预期行为：
1. Claude 调用 query_function_info RHICreateTexture2D
2. 返回 {"error": "未找到函数", "fallback_command": "search_functions RHICreate"}
3. Claude 自动调用 search_functions RHICreate
4. 展示相关函数: RHICreateTexture, RHICreateTexture2DArray, RHICreateTexture3D
5. 说明"知识库中未找到 RHICreateTexture2D，但找到相关函数"

禁止行为：
- Claude 基于训练数据回答错误信息
- Claude 说"我不确定"或"让我猜测"
```

## References
- 计划文件: `C:\Users\pb763\.claude\plans\parsed-scribbling-hummingbird.md`
- CLAUDE.md: 项目开发指导
- 相关 Issue: 用户报告 LLM 在知识库查询失败时乱回答
