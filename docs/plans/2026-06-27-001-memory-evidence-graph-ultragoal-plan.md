# Memory 证据图谱改造设计与执行计划

## 要解决的问题

当前 `query_memory` 更像“trace replay 记忆”：它会把一次查询的命令序列写入 memory。实战中 RoadLayer 查询证明了这个颗粒度有问题：一次查询里既有成功证据，也有猜错路径、失败命令和宽泛搜索；如果把整条 trace 当成功路线，`validate/replay` 会被失败步骤污染。

真正目标是：每次业务查询都沉淀为可复查、可更新、可演化的静态代码证据图谱。下次查询类似业务时，AI 能从已有证据图谱、历史路线和避坑记录出发，少走弯路，减少遗漏，但最终事实仍必须重跑当前源码证据。

## 核心原则

1. Memory 不是自然语言答案缓存。
2. Memory 的权威单位是 trace、route step、evidence anchor、graph node、graph edge、freshness，不是业务名字符串。
3. Business Subject 是组织视图和标签，不是唯一主键；同一证据可以属于多个 subject。
4. Pattern 是多个 subject 的 evidence-bound 归纳；AI 可以提出建议，但不能无证据写成事实。
5. 失败不进入主图；失败作为 `negative_hints` 隔离保存，并带失效条件。
6. Markdown / Mermaid 只是程序化生成的人类阅读产物，不是数据源。
7. 历史过时图要保留完整 JSON 快照，并另存 diff；diff 不是唯一还原源。
8. Memory 是插件或引擎级共享资产；branch、variant、commit、dirty、fingerprint 只做 provenance 和 freshness 分析。

## 目标目录

```text
memory/
  memory.sqlite
  graph/
    current/
    snapshots/
    diffs/
  obsidian/
    index.md
    business/
    patterns/
    history/
```

迁移策略：当前版本先让 `memory/memory.sqlite` 成为新的权威库；旧 `runtime/query_audit.db` 需要兼容读取或迁移，不能长期双写两套真相。

## 数据模型

### Canonical Core

- `query_runs` / `query_steps`: 全量审计日志，保留 ManyThing 式可检索历史。
- `query_memory_patterns`: promoted route，不保存自然语言业务结论。
- `query_memory_steps`: 只保存可重放路线步骤；失败步骤不能作为成功路线。
- `query_memory_evidence`: 文件、行号、symbol、hash、commit、branch、variant。
- `query_memory_graph_nodes`: 静态证据节点，例如 class、function、module、file、subsystem、data object。
- `query_memory_graph_edges`: 静态证据边，例如 call、register、create、own、produce、convert、submit、invalidate、depend。

### Subject Overlay

- `business_subjects`: 稳定 subject id、显示名、primary symbol、状态。
- `business_subject_aliases`: 别名和模糊搜索入口。
- `business_subject_members`: subject 到 evidence/node/edge/trace 的多对多关系。
- `business_subject_relations`: subject 之间的 managed_by、same_family_as、depends_on、feeds_into、uses_pattern 等关系。

### Pattern Overlay

- `business_patterns`: 业务族模式，例如 LayerImplementationPattern。
- `business_pattern_stages`: 模式阶段，例如 register、payload、producer、builder、resource。
- `business_pattern_evidence`: 每个 stage 必须能反查 evidence id。
- `business_suggestions`: AI 归纳建议，默认 pending；没有 evidence id 不得进入 accepted。

Pattern 写入主库的默认门槛：

- 至少 2 个 subject 支撑。
- 每个 stage 至少 1 个当前可验证 evidence。
- AI 文本只能作为 suggestion/note，不参与事实检索。

### Negative Hints

- `negative_hints`: 失败命令、参数、失败类型、错误摘要、source provenance、失效条件、可选 resolved_by。
- negative hint 不能参与主图遍历，不能让成功图 broken，只能作为避坑提示。

### Evolution

- `memory_snapshots`: 每个 subject/pattern 在某 commit 下的完整 JSON 快照。
- `memory_diffs`: 当前图与历史快照之间的结构化 diff。
- changed/broken/unknown 的旧图归档为历史演化资料，不能作为当前事实来源。

## 命令设计

保留现有命令：

- `query_memory_search`
- `query_memory_record`
- `query_memory_validate`
- `query_memory_replay`
- `query_memory_diff`
- `query_memory_promote`

新增或扩展命令：

- `query_memory_subjects [keyword]`: 查看 subject 视图。
- `query_memory_render [subject|pattern|all]`: 生成 Obsidian Markdown 和 Mermaid。
- `query_memory_snapshot <subject_id|pattern_id>`: 保存完整 JSON 快照。
- `query_memory_negative_hints [keyword]`: 查看隔离失败提示。

第一阶段不新增“一条命令生成完整业务逻辑”的作弊命令。业务闭环仍由当前静态查询和 evidence graph 支撑。

## 第一阶段执行切片

1. 把 memory DB 路径抽象为 `memory/memory.sqlite`，保留旧 `runtime/query_audit.db` 兼容。
2. 修改 `record_memory`：成功证据进路线和图；失败步骤进 `negative_hints`，不进入成功 route replay。
3. 增加 graph node/edge/evidence 结构化表，现有 `query_memory_graph` hash 继续保留做兼容。
4. 增加 subject overlay：从 seed、primary symbol、核心 evidence 生成或复用 subject。
5. 增加 Obsidian 渲染：从权威库生成 Markdown/Mermaid，MD 不可作为数据源。
6. 增加 snapshot/diff 最小能力：完整 JSON 快照优先，diff 只辅助阅读。
7. 更新 README、QUICK_START、Skill 模板。
8. 补单元测试和实战测试，尤其覆盖失败步骤不污染主图。

## 验收标准

- 查询日志、memory pattern、evidence graph 都写入 `memory/memory.sqlite` 或通过兼容层等价读取。
- `record_memory` 不再把失败步骤写入可重放成功路线。
- 失败步骤会生成 `negative_hints`，并带 provenance / stale condition。
- `query_memory_validate` 对成功路线不因隔离失败而 broken。
- subject 只是 evidence/node/edge 的视图；同一 evidence 可挂多个 subject。
- Obsidian Markdown 可从数据库重新生成，包含 Mermaid 图、证据表、freshness、历史快照链接。
- 没有自然语言业务结论被当作事实来源。
- 现有 `query_memory_*` 命令兼容。
- `py -m pytest tests/test_query_memory.py tests/test_query_audit.py tests/test_skill_template_runtime_commands.py -q` 通过。
- 至少一次用 AesWorldKB 实战 trace 验证：失败不会污染成功图，MD 能生成。

## 专家审查关注点

1. 是否仍会造成事实污染。
2. 是否会和旧 `runtime/query_audit.db` 形成双真相源。
3. 是否保留了 trace/symbol/file/module 等硬索引，而不是只按业务主题。
4. negative hints 是否会误导新分支或新 commit。
5. Obsidian 产物是否完全可再生成。
6. 相比 SQL-ManyThing，是否保留了低摩擦查询历史，并增加了 freshness / evidence graph 价值。
