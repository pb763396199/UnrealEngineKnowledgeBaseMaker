---
title: 第 7 页 BudgetSubsystem 注册架构 · 内容底稿
status: draft
language: zh-CN
updated: 2026-06-16
purpose: 优化 aesworld-pcg-agent-presentation 第 7 页（BudgetSubsystem）内容底稿，先 MD 调整后改 slide
slide_target: F:\ShanghaiP4\neon\Plugins\AesWorld\docs\guides\aesworld-pcg-agent-presentation\slides\07-budget-subsystem.html
sources:
  - 最新代码核对（UE Research 直读 Source/AesRenderResource，commit a69bc21；主控 KB CLI 抽查互证）
  - KB 核实：FAesRenderResourceTile(AesRenderResourceBudgetSubsystem.h:34, FGCObject, 54 方法)、HandleGeoreferenceUpdatedTyped 存在
---

# 第 7 页 · BudgetSubsystem 注册架构内容底稿

> 这页要在一屏内讲清：OutputCollection 等生成物如何经 `UAesRenderResourceBudgetSubsystem` 变成**可控的注册节奏**——队列/缓存如何系统性控制注册、注销、可见性切换，以及 georeference rebasing 触发的坐标变换如何处理。所有事实以**最新代码**为准（commit a69bc21）。

---

## 0 · 当前页面的问题

现版第 7 页是 4 个泳道（RegisterRequests / Active Tiles / Cache Tiles / Unregister）+ 几个写死的小标签，**与真实代码脱节**：

- 没讲「预算」到底预算什么（其实是每帧批次数/实例数/时间片）。
- 没讲线程安全的 MPSC 提交、分帧截断、单 tile 跨帧续注册。
- 没讲 tile 生命周期状态机（ERegisterMode）。
- **完全没讲 georeference rebasing 的坐标变换处理**（用户最在意的点）。

---

## 1 · 一句话主张（Hero）

**BudgetSubsystem：把海量生成物变成「每帧可控、可缓存、可重定位」的注册节奏。**

副标题：`UAesRenderResourceBudgetSubsystem`（`UTickableWorldSubsystem`，AesRenderResource 模块）—— 后台无锁提交，GameThread 每帧按预算分帧注册，视野复用走 LRU，origin rebase 走分帧坐标重算。

---

## 2 · 真实身份与「预算」语义

- **类**：`UAesRenderResourceBudgetSubsystem : UTickableWorldSubsystem`（每帧 `Tick`）。
- **预算 = 每帧注册工作量**，由 `UAesRenderResourceSettings`（DeveloperSettings）三选一计量：
  - `BatchAmount`（默认）— `MaxBatchAmount = 16` 批/帧
  - `InstanceAmount` — `MaxInstanceAmount = 8192` 实例/帧
  - `TimeAmount` — `MaxBatchExecutionTimeInSeconds = 0.005`（5ms/帧）
- 开关：`bUseFramingRegister`（分帧）、`bUseDistancePriority`（距离优先）、`CacheSize`（LRU 容量，**默认 0**）、`TransformDrainPerTick = 256`（rebase 坐标每帧刷新上限）。

---

## 3 · 每帧 Tick 的 6 步流水（页面主体上半）

```
Tick(DeltaTime):
 ① ProcessRegisterRequests       排空注册/注销队列 → 入 active/cache，构建本帧 SanitizedTiles
 ② ProcessHighPriorityTransforms georef rebase high pass（无预算，同帧排空）
 ③ ProcessLowPriorityTransforms  georef rebase low pass（按 256/帧 分帧续传）
 ④ SortBudgetRegister            视锥 + 距离排序（近的先注册）
 ⑤ ExecuteBudgetRegister         按 MaxBatchAmount 分帧截断注册，单 tile 跨帧续
 ⑥ FinishBudgetRegister          全部 child 完成 → Payload 置 Finished
```

---

## 4 · 队列 / 缓存全景（页面主体核心图）

> 真实成员，全部是 `UAesRenderResourceBudgetSubsystem` 私有容器。

| 容器 | 类型 | 职责 |
|---|---|---|
| `RegisterRequests` | `TQueue<…, Mpsc>` | 待注册请求（后台多生产者 enqueue） |
| `UnregisterRequests` | `TQueue<…, Mpsc>` | 待注销请求 |
| `RenderResourceTiles` | `TMap<FAesLayerMarkerInfo, Tile>` | **Active**：在册/可见的 tile |
| `CacheRenderResourceTiles` | `TLruCache<…, Tile>` | **LRU 缓存**：隐藏但未销毁，可秒复活 |
| `SanitizedTiles` | `TArray<FAesLayerMarkerInfo>` | 本帧待处理（RegisterMode≠None）喂给 Sort/Execute |
| `TransformHighPriorityTiles` | `TSet<…>` | rebase high 队列（可见 tile，必须同帧重算坐标） |
| `TransformLowPriorityTiles` | `TSet<…>` | rebase low 队列（隐藏/空闲 tile，分帧续） |
| `LastAppliedGeoreferenceRevisionPerEarth` | `TMap<int32,int64>` | 按 EarthId 的 revision dedup（多 Earth 分桶） |
| `LatestGeoreferenceContextPerEarth` | `TMap<int32,Context>` | 每 Earth 最近 georef 快照（cache 复活补坐标） |

**状态流转**：
```
Add_Concurrent ─► RegisterRequests ──Tick──► Active(RenderResourceTiles)
Remove_Concurrent ─► UnregisterRequests ──Tick──► Cache(LRU)  或  析构销毁
   Active ──再次 Add 命中 cache──► 复活回 Active (CacheHit)
   Cache 满 ──插入新条目──► 淘汰最久未用 (LruEviction)
```

---

## 5 · 注册 / 注销 / 可见性切换（真实机制）

### 提交（无锁线程安全）
- `Add_Concurrent(...)` / `Remove_Concurrent(...)` 只做 `Enqueue`，用 **move 转移所有权**，**不碰 UObject** → 后台生成线程可直接调。
- 队列为 `Mpsc`（多生产者单消费者），UObject 创建（`NewObject<URenderSceneNode_Composite>`）全部延迟到 GameThread Tick。

### Tile 生命周期状态机（rebasing 是其中一条状态路径，不单独拆）

一个 tile 的「一生」就是一台状态机。BudgetSubsystem 不是 4 个孤立泳道，而是**每帧 Tick 把 tile 沿状态机推进、并在预算内截断**。状态由 `ERegisterMode` 驱动，叠加容器维度（Active / Cache / Destroyed）：

| 状态 | 触发 | 预算行为 |
|---|---|---|
| **Submit**（队列中） | 后台 `Add/Remove_Concurrent` 入 MPSC 队列 | 无锁，不占帧预算 |
| **Register** | 首次 / EditId 变 → `Process` 逐 child 注册 | 占**注册预算**（MaxBatchAmount），可跨帧续 |
| **Visible** | 注册完成（None）或从隐藏移回 `SetVisible` | 在册可见 |
| **Invisible → Cache** | 视野移走 `SetInvisible`，搬入 LRU | 仅隐藏、保留 component/CPD/Atlas |
| **Rebase（坐标重算）** | georef origin rebase，按当前状态分 high/low | 占**坐标预算**（TransformDrainPerTick），可跨帧续 |
| **Destroyed** | Cache 满淘汰 / Cache.Max==0 注销 | 析构 + 归还 Atlas slot |

> **关键认知**：rebasing 不是独立机制，而是状态机里「**坐标重算**」这条状态路径——它和注册一样**被同一套分帧预算管控**，只是用的是另一份预算（坐标预算 256/帧）。可见 tile 走 high pass（同帧排空），隐藏/缓存 tile 走 low pass（分帧续）。

**两类预算，一条流水**（这是 BudgetSubsystem 的独特之处）：
- **注册预算** `MaxBatchAmount`：控制「上屏/下屏」节奏（ExecuteBudgetRegister 截断，`ProcessPos` 跨帧续）。
- **坐标预算** `TransformDrainPerTick=256`：控制「rebase 重定位」节奏（DrainTileTransform 截断，`TransformProcessPos` 跨帧续）。
- 两者都在**同一帧 Tick** 内、对**同一批 tile**、用**同样的「排序→截断→续帧」范式**——这就是「把生成物变成可控注册节奏」的本质。

**坐标重算细节（Rebase 状态路径展开）**：
- 触发：`AAesEarth::UpdateGeoreferencingSystem` 构造不可变 `FAesGeoreferenceUpdateContext`（Old/New 系统快照 + `Revision` + `Reason`(含 OriginRebase) + `EarthId`）→ 反向 push → `HandleGeoreferenceUpdatedTyped`（反向 push 避免子系统静态依赖 AesEarth 头的 DLL 循环导入）。
- 分发：按 tile 当前 `RegisterMode` 入 high（可见，同帧排空）/ low（隐藏，分帧续）队列；EarthId + per-tile revision 双层 dedup；Landmark 图层另由 `UAesLandmarkBudgetSubsystem` 单独平移。
- 重算：`DrainTileTransform` 先 `UpdateOwnTileTransformOnly` 重算 tile 自身 transform，再按节点空间 `EAesNodeSpace` 逐 child 派生——`TileLocal`（主路径，child 持局部坐标跟随 tile）/ `WorldSpace`（fallback，OutputCollection 走此路，按 Old/New 换基逐组件重映射）。

---

## 6 · 核心价值（页面收束，均经代码坐实）

1. **一条流水、两份预算** — 注册预算（上下屏）与坐标预算（rebase 重定位）共用「排序→截断→跨帧续」范式，在同一帧 Tick 内对同一批 tile 统一调度。这是 BudgetSubsystem 区别于「直接生成就上屏」的本质。
2. **分帧削峰** — `MaxBatchAmount=16`（或 8192 实例 / 5ms）+ `ProcessPos`/`TransformProcessPos` 跨帧续，避免一帧大量 NewObject / 坐标重算造成卡顿。
3. **可见性复用而非重建** — `SetInvisible` 仅隐藏、保留 component/CPD/Atlas，移回秒级 `SetVisible`；隐藏≠销毁。
4. **LRU 缓存换显存** — 隐藏 tile 进 `TLruCache` 作热缓存，满则淘汰最久未用（注：`CacheSize` 默认 0，需项目侧开启）。
5. **无锁线程安全提交** — MPSC 队列 + move 语义，后台生成线程直接 `Add_Concurrent`，UObject 创建全延迟到 GameThread Tick。

---

## 7 · 版面重构思路（核心：以「每帧 Tick 流水」为骨架，把状态融进流水）

放弃「定式四象限/双面板」，改用**一张以帧为单位的调度图**，让「状态机」与「预算流水」合二为一：

### 主图（页面主体，占大半屏）— 「一帧之内」的调度全景

横向时间轴 = 一帧 Tick，从左到右：

```
后台线程                    ┃              GameThread · 一帧 Tick                          ┃
─────────                  ┃  ─────────────────────────────────────────────────────────  ┃
Add/Remove_Concurrent ──►  ┃  ① 排空队列   ② 坐标重算(high/low)   ③ 排序   ④ 预算注册   ⑤ 完成 ┃
  (MPSC, 无锁)              ┃     入 Active/Cache    ▲rebase状态        近优先   ▲budget gate  ┃
                           ┃                        │                          │ 满→下帧续    ┃
                           ┗━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━┛
                                                   两个 budget gate（注册16 / 坐标256）卡住溢出 → 滚到下一帧
```

下方挂一条 **tile 状态机泳道**（与流水对齐）：`Submit → Register ⇄ Visible ⇄ Invisible/Cache(LRU) → Destroy`，其中 **Rebase 是叠加在 Visible/Invisible 上的坐标重算路径**（high/low），用同一个 budget gate 图元表达「也被预算卡」。

要点：
- **预算闸（budget gate）是全图的视觉主角** —— 两个闸（注册 16 批 / 坐标 256 child），溢出的部分用「滚到下一帧」的回环箭头表达。这是这页唯一真正独特、值得占一页的东西。
- 队列/缓存（MPSC / Active TMap / LRU）作为流水操作的数据结构画在对应步骤下，不再单列泳道。
- rebase **不另开板块**，只作为状态机上的一条重算路径 + 第二个 budget gate。

### Hero
主张：「把海量生成物变成每帧可控的注册节奏」+ 右侧 why（一帧两预算 · 视野复用 · rebase 同律）。

### 底部
3–4 个数据大字报式指标：`16 批/帧` · `256 坐标/帧` · `MPSC 无锁` · `LRU 复用`，配一句话。

### footer
`UAesRenderResourceBudgetSubsystem · Tick → ProcessRegisterRequests · ExecuteBudgetRegister · DrainTileTransform`

### 实现
沿用 4:3 版式机制（`--stage-design-height:1200px` + slide.js 缩放）+ 终端直写磁盘 + cache-bust + Playwright 实测验证；主图用一张大 SVG（时间轴 + 状态泳道 + 两个 budget gate 回环），不再做并列卡片堆叠。

---

## 8 · 写稿避坑（与旧页面/旧认知的差异）

| 旧页面/旧认知 | 最新代码 | 处理 |
|---|---|---|
| 「预算」语义模糊 | 每帧批次/实例/时间三选一（默认 16 批）+ 独立坐标预算 256 | 突出「两份预算」 |
| Cache 一定生效 | `CacheSize` 默认 0 → 默认注销即销毁 | 注明「需开启」 |
| 4 个孤立泳道 | 一帧 Tick 流水 + tile 状态机合一 | 重画为调度图 |
| rebase 单独讲 | rebase 是状态机的坐标重算路径，被同一预算卡 | 融进主图，不另开板块 |
