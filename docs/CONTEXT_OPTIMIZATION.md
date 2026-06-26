# Context Optimization 使用指南

本文档描述当前静态命令查询的上下文控制约定。历史版本曾使用分层接口和隐藏引用缓存来做渐进披露；当前默认 Skill runtime 改为显式命令，不把自由文本、生成式路由或隐藏引用当作查询接口。

## 核心原则

1. **先预检**：所有源码问答前先执行 `preflight`，确认 KB 与源码 commit、dirty 状态和索引完整性。
2. **显式命令**：调用方把用户意图映射为确定性命令，例如 `query_class_info`、`query_function_info`、`source_slice`、`search_files`、`resolve_seed`。
3. **渐进披露**：先取结构化摘要，再按文件和行号调用 `source_slice` 获取源码上下文。
4. **有界输出**：命令必须带 limit 或 max_output_chars，避免一次性返回大段无关内容。
5. **证据锚点**：报告里引用 `file`、`line`、`relation_type`、`resolution_state`、`evidence_hash` 等静态字段。

## 推荐流程

```powershell
py "<skill>\impl.py" preflight
py "<skill>\impl.py" resolve_seed AActor 10
py "<skill>\impl.py" query_class_info AActor
py "<skill>\impl.py" source_slice Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h 234 context 8 40 12000
```

对于调用关系或 UE 业务链探索：

```powershell
py "<skill>\impl.py" resolve_seed FMyFeatureFragment 10
py "<skill>\impl.py" symbol_evidence_bundle FMyFeatureFragment 20 all
py "<skill>\impl.py" query_static_closure FeatureLayer 3 80 all
py "<skill>\impl.py" query_flow FMyFeatureFragment both call,type_reference 2 50 all
py "<skill>\impl.py" query_audit --limit 20
```

## 输出控制

- 摘要层：优先使用 `query_class_info`、`query_function_info`、`resolve_seed`。
- 证据层：使用 `symbol_evidence_bundle`、`symbol_reference_report`、`query_flow`。
- 源码层：只对已定位的文件行号调用 `source_slice`。
- 大结果：调小 `limit`，或按 module/class/function 分多次静态查询。

## 禁止事项

- 不要把自由文本问题直接传给 `impl.py`。
- 不要依赖隐藏引用、完整结果缓存或隐式状态作为查询契约。
- 不要在 KB 工具内做 LLM、RAG、embedding、vector 相似度或自然语言意图识别。
- 不要复制 `variants/`；所有 provider adapter 都应指向 `~/.agents/skills/<skill-name>` 下的 canonical Skill。
