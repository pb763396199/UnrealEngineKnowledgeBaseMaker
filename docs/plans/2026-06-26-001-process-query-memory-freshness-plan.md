---
title: 查询记忆与业务链新鲜度执行计划
purpose: plan
status: active
date: 2026-06-26
language: zh-CN
type: process
origin: user-request
---

# 查询记忆与业务链新鲜度执行计划

## Objective

把当前知识库工具从“单次静态查询”升级为“可复用历史查询路径 + 当前源码新鲜度校验 + 多轮静态补查”的业务探索流程。

核心原则：

- 历史查询路径只能复用路线，不能复用事实。
- 历史查询 Memory 是插件或引擎级共享资产，不按 branch/variant 分库；branch、variant、commit、dirty、fingerprint 是 provenance 和 freshness 分析维度。
- 最终事实必须来自当前 KB、当前源码 hash、当前 symbol 解析和当前源码切片。
- 新鲜度判断尽量用确定性算法完成。
- LLM 只参与查询规划、缺口判断和结果组织，不参与 freshness 裁决。

## Selected Role

`ue-master`

拆分角色：

| 子任务 | 主角色 | 说明 |
|---|---|---|
| 方案落盘与目标拆解 | UE Master | 本文件 |
| 查询记忆 schema 与命令实现 | UE Worker | 修改工具代码 |
| Freshness 验证设计与测试 | UE Validator | 验证算法判定 |
| ManyThing 差异复核 | UE Research | 只读对照 |
| 文档和 Skill 使用说明 | UE Knowledge Curator | 更新 README、QUICK_START、Skill 模板 |
| 最终审查 | UE Reviewer | 防止记忆污染、过时事实复用 |

## Scope

本计划只解决查询记忆和 freshness 机制，不实现 RAG、embedding、向量搜索或运行时 LLM 检索。

### In Scope

- 新增查询记忆数据库或扩展 `query_audit.db`。
- 记录可复用的查询路径、命令序列、证据文件、symbol、结果摘要和 hash。
- 纯算法 freshness 校验。
- 历史路径 replay 和 diff。
- Skill/README/QUICK_START 中增加“先查历史路径、再校验、再重跑当前事实”的流程。
- 测试覆盖文件 hash、symbol 漂移、查询结果漂移、edge/frontier 漂移。

### Out of Scope

- 不存储自然语言业务结论作为事实。
- 不让 LLM 判断 hash 是否新鲜。
- 不把历史路径直接当成当前答案。
- 不新增 RAG、embedding、vector search。
- 不把 AesWorld/BuildingLayer 专用业务术语写入通用模板。

## Freshness Definition

Freshness 分为五层。

| 层级 | 名称 | 判断对象 | 判定方式 | AI 是否参与 |
|---|---|---|---|---|
| L0 | KB 新鲜度 | KB 是否对应当前 source root | `preflight`、variant、commit、dirty、source fingerprint | 否 |
| L1 | 文件新鲜度 | 历史证据文件是否变化 | 文件 hash、大小、mtime 辅助 | 否 |
| L2 | Symbol 新鲜度 | 历史 symbol 是否仍指向同一对象 | symbol id、签名 hash、文件锚点、行号重定位 | 否 |
| L3 | 查询结果新鲜度 | 历史命令重跑结果是否等价 | 规范化 JSON hash、关键字段 hash | 否 |
| L4 | 业务路径新鲜度 | 当前 node/edge/frontier 是否覆盖历史路径 | edge set hash、node set hash、frontier diff、unresolved/truncated 状态 | 算法为主，AI 只做下一步规划 |

## Data Model

新增或扩展 SQLite 表：

### `query_memory_patterns`

| 字段 | 说明 |
|---|---|
| `id` | memory id |
| `intent` | 例如 `explain_business_flow` |
| `seed` | 用户或工具解析出的入口 |
| `skill_name` | Skill 名称 |
| `source_root` | 源码根目录 |
| `branch_name` | 记录路线时的分支名，只作追溯/分析，不作分库边界 |
| `variant_id` | KB variant |
| `commit_id` | 记录时 commit |
| `dirty` | 记录时 dirty 状态 |
| `source_fingerprint` | 源码整体指纹 |
| `rules_version` | 项目约定规则版本，未实现时为空 |
| `command_sequence_hash` | 命令序列 hash |
| `created_at` | 创建时间 |
| `last_validated_at` | 最近校验时间 |
| `status` | `active / stale / superseded / blocked` |

### `query_memory_steps`

| 字段 | 说明 |
|---|---|
| `memory_id` | 关联 pattern |
| `step_index` | 步骤顺序 |
| `command` | Skill 命令 |
| `args_summary` | 参数摘要 |
| `result_hash` | 完整结果规范化 hash |
| `important_fields_hash` | 关键字段 hash |
| `result_count` | 结果数量 |
| `error` | 记录时错误 |

### `query_memory_evidence`

| 字段 | 说明 |
|---|---|
| `memory_id` | 关联 pattern |
| `file` | 证据文件 |
| `file_hash` | 文件 hash |
| `line_start` / `line_end` | 原始范围 |
| `anchor_text_hash` | 锚点文本 hash |
| `symbol` | 相关 symbol |
| `symbol_id` | 稳定 symbol id |
| `symbol_signature_hash` | 签名 hash |

### `query_memory_graph`

| 字段 | 说明 |
|---|---|
| `memory_id` | 关联 pattern |
| `node_set_hash` | 节点集合 hash |
| `edge_set_hash` | 边集合 hash |
| `frontier_hash` | frontier hash |
| `node_count` / `edge_count` / `frontier_count` | 判断 expanded/changed 的集合规模 |
| `unresolved_count` | unresolved 数 |
| `truncated` | 是否截断 |

## Commands

| 命令 | 作用 | 新鲜度裁决方式 |
|---|---|---|
| `query_memory_record <trace_id> <intent> <seed>` | 把一次查询记录为可复用路线 | 记录当前 hash 和结果摘要 |
| `query_memory_search <keyword> [intent]` | 搜历史路线 | 只返回候选，不判事实 |
| `query_memory_validate <memory_id>` | 校验历史路线是否过时 | 纯算法 |
| `query_memory_replay <memory_id>` | 在当前 KB 上重跑命令序列 | 纯算法执行 |
| `query_memory_diff <memory_id>` | 对比当前结果和历史结果 | 纯算法 |
| `query_memory_promote <trace_id> <intent> <seed>` | 把当前更完整路线升级为推荐路线 | 需通过 validate |

## Freshness States

| 状态 | 含义 | 是否可复用 |
|---|---|---|
| `fresh` | KB、文件、symbol、查询结果和图结构一致 | 可复用路线，也应重跑关键证据 |
| `equivalent` | 行号或位置变了，但 symbol 和 anchor 可重定位 | 可复用路线，必须重新取源码切片 |
| `expanded` | 当前发现了新增边、入口、分支或 frontier | 旧路线不完整，必须继续补查 |
| `changed` | 查询结果或关键证据变化 | 只能当候选路线 |
| `broken` | 文件/symbol 缺失或命令失败 | 不可复用 |
| `unknown` | 缺少校验数据 | 不可作为事实来源 |

## Query Loop

```text
1. preflight
2. query_memory_search <seed> explain_business_flow
3. query_memory_validate <memory_id>
4. fresh/equivalent: query_memory_replay
5. expanded/changed: replay 后继续查新增 frontier
6. broken/unknown: 从 resolve_seed 重新开始
7. 用 source_slice / get_function_implementation 取当前源码证据
8. LLM 根据当前证据组织解释，并列出未覆盖缺口
9. query_memory_record 或 query_memory_promote 保存更好的路线
```

## Acceptance Criteria

- 历史 memory 不能绕过 `preflight`。
- 历史 memory 不能按 branch/variant 分库；跨分支使用时，branch/variant/commit 差异只进入 provenance，不能单独导致路线不可用。
- 历史 memory 不保存自然语言业务结论作为事实。
- 文件 hash 变化时，`query_memory_validate` 不能返回 `fresh`。
- symbol 签名变化时，必须返回 `changed` 或 `broken`。
- 查询重跑新增边时，必须返回 `expanded`。
- `expanded`、`changed`、`broken`、`unknown` 状态不能用于最终事实复用。
- Skill 文档必须明确：事实来自当前查询结果，历史只提供路线。
- 测试必须覆盖文件 hash、symbol、query result、edge/frontier 四类漂移。

## Risks

| 风险 | 缓解 |
|---|---|
| 历史路线被误当答案 | schema 禁止保存自然语言事实，Skill 文档强制重跑当前证据 |
| 过度依赖 LLM 判断 freshness | freshness 命令只输出算法结果，LLM 不能覆盖 |
| 路径 hash 太敏感导致频繁失效 | 区分 `fresh`、`equivalent`、`expanded`、`changed` |
| 记录源码正文导致空间和泄漏 | 只存 hash、路径、锚点摘要和结果摘要 |
| AesWorld 术语污染通用模板 | 测试扫描通用模板禁止真实项目专名 |

## To-do List

1. 设计并实现 query memory SQLite schema。
2. 为 query audit 增加 trace 到 memory pattern 的提升流程。
3. 实现 `query_memory_record`。
4. 实现 `query_memory_search`。
5. 实现 `query_memory_validate`。
6. 实现 `query_memory_replay`。
7. 实现 `query_memory_diff`。
8. 实现 `query_memory_promote`。
9. 补充文件 hash、symbol hash、query result hash、edge/frontier hash 工具函数。
10. 更新 Skill 模板，加入“先查历史路线、校验、重跑当前事实”的流程。
11. 更新 README 和 QUICK_START。
12. 增加单元测试和真实 AesWorldKB smoke。
13. 最终审查：确认无 LLM/RAG/vector/embedding 查询引擎，且历史 memory 不作为事实缓存。

## Assumptions

- 当前工具继续以 SQLite 和静态索引为核心。
- LLM 只在 Codex/Agent 层进行规划和总结，不进入 `impl.py` 命令执行路径。
- 历史路径复用优先解决“少走弯路”，不是替代当前源码查询。
