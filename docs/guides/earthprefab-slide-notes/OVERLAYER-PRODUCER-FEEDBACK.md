---
title: 第 6 页 Overlayer 反向影响 Producer · 内容底稿
status: draft
language: zh-CN
updated: 2026-06-16
purpose: 重写 aesworld-pcg-agent-presentation 第 6 页（Overlayer 反向影响 MarkerProducer）的内容底稿，先 MD 核对后改 slide
slide_target: F:\ShanghaiP4\neon\Plugins\AesWorld\docs\guides\aesworld-pcg-agent-presentation\slides\06-producer-feedback.html
sources:
  - UE Research 直读最新源码（F:\ShanghaiP4\neon\Plugins\AesWorld，branch neon，commit a69bc21）
  - 主控亲自核证（KB preflight=fresh@a69bc21 + 直读 5 个核心源文件确认两族 SubmitOverlayer 差异、Subsystem API、InvalidateMarker_Internal 注释）
evidence_files:
  - Source/AesMarkerSystem/Public/Prefab/EarthMarkerProducerFragmentsSubsystem.h
  - Source/AesMarkerSystem/Private/Prefab/EarthTextureOverlayerFragment.cpp
  - Source/AesMarkerSystem/Private/Prefab/EarthEntityOverlayerFragment.cpp
  - Source/AesMarkerSystem/Private/Core/AesMarkerProducer.hpp
  - Source/AesMarkerSystem/Private/Core/AesMarkerDependent.hpp
---

# 第 6 页 · Overlayer 反向影响 Producer 内容底稿

> 这页要讲清一件反直觉的事：**不是只有「Producer 生成 Prefab」这条单向路；编辑器里摆出来 / 算法生成出来的 Overlayer Prefab，能反过来注入并失效 MarkerProducer 的产物。** 所有事实以**最新真实代码**为准（neon @ a69bc21，已直读源码核证）。

---

## 0 · 当前页面的问题

现版第 6 页只有一句「Prefab/Overlayer 会反向影响 Producer」+ 一张四节点环形图 + 4 张糊卡片（Overlayer Fragment / Fragments Subsystem / Invalidate Producer / Producer DAG）。问题：

- **完全没讲 Overlayer 体系本身**——有几族？texture 和 entity 的区别是什么？只字未提。
- **机制是错/糊的**：环形图把它画成「Subsystem → Invalidate Producer → DAG」一条线，但真实代码里 **Subsystem 根本没有 Invalidate 方法**（它只是数据仓），失效逻辑在 Fragment 自己身上。
- **「Producer DAG」是误导**：真正驱动失效传播的是**运行时 marker 粒度的 Dependent 引用图**；那张 producer 粒度的 `FAesMarkerProducerGraph` 只在 Debugger 编译下用于离线可视化，**不参与运行时失效**。
- 没讲清「**注入 / 失效 / 重建**」三者是解耦的，更没讲重建是 **pull（按需）** 而非 push。

---

## 1 · 一句话主张（Hero）

**Overlayer 不直接改 marker，而是「注册 + 失效」——让 MarkerProducer 在下一次按需重建时自己把叠加内容拉回去。**

副标题：编辑出的 Overlayer Prefab 把作用范围换算成受影响 tile，注册进 ProducerFragmentsSubsystem，再沿依赖图递归失效相关 marker；真正的重建交给 LOD 系统每帧 pull，刻意避免 push 式并发重建风暴。

---

## 2 · Overlayer 体系是什么（先建立认知，再讲反向链）

Overlayer 是 EarthPrefab 框架派生出的一套**「叠加层」Prefab**，分两大支，各自的 Actor / Prefab / Algorithm / Fragment 四件套独立成链：

### 两大族（一句话区分）

| 族 | 几何输入 | 影响对象 | 典型用途 |
|---|---|---|---|
| **贴图族 Texture**（栅格） | `UEarthBoxComponent`（轴对齐盒） | 栅格 / 纹理类 marker | DOM 影像叠加、DEM 高程改写、Mask 贴图 |
| **实体族 Entity**（矢量） | `UEarthSplineComponent`（折线） | 矢量 / 地形类 marker | 水域 mask、地形改造、矢量几何叠加 |

### 完整谱系（四件套各自独立继承）

```
[Actor]  AEarthPrefabActor
  ├─ AEarthTextureOverlayer      （持 Box，栅格族基类）
  │    ├─ AEarthDomOverlayer        （正射影像）
  │    └─ AEarthDemOverlayer        （数字高程，带 GPU 高度重映射 shader）
  └─ AEarthEntityOverlayer       （持 Spline，矢量族基类）
       └─ AEarthWaterEntityOverlayer（水域：轮廓→地形改造 + 水体 mask）

[Fragment]  FEarthOutputFragment   ← 注意：是 Output 片段（算法的产物）
  ├─ FEarthTextureOverlayerFragment
  │    ├─ FEarthDomOverlayerFragment
  │    └─ FEarthDemOverlayerFragment
  └─ FEarthEntityOverlayerFragment
       └─ FEarthWaterEntityOverlayerFragment
```

> 证据：`AEarthTextureOverlayer : public AEarthPrefabActor`、`AEarthEntityOverlayer : public AEarthPrefabActor`（EarthTextureOverlayerCommon.h / EarthEntityOverlayerCommon.h）；`AEarthDemOverlayer / AEarthDomOverlayer : public AEarthTextureOverlayer`；`AEarthWaterEntityOverlayer : public AEarthEntityOverlayer`。Actor / Prefab struct / Algorithm / Fragment 四条链刻意**不平行**（解耦），细节见 §6 附录。

### Fragment 里保存了什么（反向影响靠这几个字段）

每个 OutputFragment 都带着「我要影响谁、影响哪里」的元数据：

- `ProducerName`（FName）— 我属于哪个生产者
- `InvalidateProducerNames`（TArray\<FName\>）— **我变化时要让哪些生产者失效**
- `FeatureID` — 我的唯一身份（增删 / 去重的 key）
- `Tiles`（TSet\<FString\> QuadKey）— 算法换算出的**受影响地块集**
- 贴图族额外带：`Texture` / `BlendType` / `SamplerType` / `AlphaStrength` + GPU 参数（`FEarthTextureOverlayerParameters`）；DEM 再加高度重映射 `InputHeightRange`/`OutputHeightRange`
- 实体族额外带：`LLAVertices`（经纬高顶点）/ `bClosedLoop`；水域再加 `Params`（多轮廓 + 地形改造参数，与 `FCGLWaterInfo` 对齐）

---

## 3 · 反向影响 Producer 的三段式链路（页面主体）

> 这是整页的核心。一句话：**Overlayer 推（Push）注册 + 推失效，Producer 拉（Pull）读取重建。** 两者通过 `ProducerName` 字符串解耦，Overlayer 完全不持有 Producer 实例。

### ① 提交 / 注册（Push 数据进中枢）

编辑器里摆放 / 移动 / 编辑一个 Overlayer Actor → 它的 PrefabAlgorithm 跑一遍，把作用区域换算成受影响 tile 集 → 产出的 OutputFragment 在实例化（`CreateObject_Internal`）时，把自己注册进中枢 `UEarthMarkerProducerFragmentsSubsystem`：

```cpp
// EarthEntityOverlayerFragment.cpp / EarthTextureOverlayerFragment.cpp（两族同构）
ProducerFragmentsSubsystem->AddProducerFragment(
    EarthActor.Get(), ProducerName, FeatureID.GetFeatureID(), Tiles, this->Clone(), &PreviousTiles);
```

中枢按 **四级索引**存档（OwnerActor + ProducerName + FeatureID + TileId）：

```cpp
// 外层 key：(EarthActor + ProducerName) 一格，多 Earth 隔离
TMap<FAesProducerFragmentOwnerKey, FEarthMarkerProducerFragments> OwnerToTileFragments;  // FRWLock 保护

struct FEarthMarkerProducerFragments {            // 三向索引（实际 3 个 TMap）
    TMap<int64,   FEarthFragmentPtr> FeatureIdToFragment;  // FeatureID → fragment 本体
    TMap<int64,   TSet<FString>>     FeatureIdToTileIds;   // FeatureID → 它覆盖的 tile
    TMap<FString, TSet<int64>>       TileIdToFeatureIds;   // TileId → 该 tile 上的 feature（反查）
};
```

> **关键否定事实**：中枢只是**数据仓**——它**没有任何 Invalidate / MarkDirty 方法，也没有 Tick override**，增删全部同步完成。失效逻辑不在它身上。（直读 EarthMarkerProducerFragmentsSubsystem.h 核证）

### ② 失效 / 传播（Push 失效信号，沿依赖图递归）

注册的同一步，Fragment 调用自己的 `SubmitOverlayer`，依据 `InvalidateProducerNames`，找到目标 Producer 并触发失效。**两族失效粒度不同**，这是设计精髓：

**贴图族（粗粒度，整体清空）** — EarthTextureOverlayerFragment.cpp:296

```cpp
void FEarthTextureOverlayerFragment::SubmitOverlayer() const {
    for (const auto& Name : InvalidateProducerNames)
        if (auto Producer = SharedMarkerSystem->FindMarkerProducer(Name))
            StaticCastSharedPtr<FAesMarkerProducer>(Producer)->InvalidateMarkers_Internal();  // 清空整个 producer 缓存
}
```

**实体族（细粒度，tile + 依赖图递归）** — EarthEntityOverlayerFragment.cpp:51（**最该上屏的一段**）

```cpp
void FEarthEntityOverlayerFragment::SubmitOverlayer(const TSet<FString>& InAffectedTiles) const {
    for (const auto& Name : InvalidateProducerNames) {
        auto MarkerProducer = StaticCastSharedPtr<FAesMarkerProducer>(SharedMarkerSystem->FindMarkerProducer(Name));

        // (a) Tile 纵向展开：每个 QuadKey 的【所有祖先 level】都纳入（低 level 聚合了高 level 数据）
        TSet<FAesMarkerInfo> AffectedMarkerIds;
        for (const FString& QuadKey : InAffectedTiles)
            for (int Level = 1; Level <= QuadKey.Len(); ++Level)
                AffectedMarkerIds.Add(FAesMarkerInfo(QuadKey.Left(Level)));

        // (b) 沿 Dependent 引用图【递归】失效（连带比 tile level 更细的子 tile 15/16/17…）
        for (const FAesMarkerInfo& MarkerId : AffectedMarkerIds)
            if (auto Dep = MarkerProducer->FindMarkerDependent(MarkerId))
                Dep->VisitSelfAndReferencers([&](const auto& In){ In.InvalidateMarker(); });
    }
}
```

失效有**两个方向**叠加，缺一不可：
- **纵向（向祖先）**：`QuadKey.Left(1..Len)` 把所有上级 tile 也标失效。
- **递归（向下游引用者）**：`VisitSelfAndReferencers` 先访问自身，再对「谁引用我」逐个递归（AesMarkerDependent.hpp），让所有下游 / 子 tile marker 连带失效。这条引用边由 marker 创建时的 `Depend()` 双向登记。

> **移动场景的坑（值得一提）**：`CreateObject_Internal` 里 `AffectedTiles = 旧 tile ∪ 新 tile`——否则把 overlayer 拖走后，旧位置的叠加残留不消。

### ③ 重建（Pull，按需，不并发重算）

失效**只打 dirty 标记，绝不主动重算**。真正的重建交给 LOD / Streaming 系统每帧 pull —— AesMarkerProducer.hpp:90 的注释把设计意图写得很清楚：

```cpp
bool TAesMarkerProducer<...>::InvalidateMarker_Internal(const InMarkerIdType& InMarkerId) {
    if (!MarkerCache->InvalidateMarker(ProducerName, InMarkerId)) {     // cache miss
        MarkerCache->GetMarker(ProducerName, InMarkerId, nullptr);      // 不在场则建一个
        return true;
    }
    // cache hit：marker 已被 Invalidate() 打 dirty（CancelRequestUpToDate + MarkDirty）
    // 【刻意不在此 RequestUpToDate】—— LOD 系统每帧靠 IsResidentDataDirty() 检测后，
    // 自行 RequestRefresh → RequestToRefreshResidentData → GetMarker → RequestUpToDate，按依赖顺序重建。
    // 若在此强制重算 → 所有 producer 并发重建，上游未就绪时下游 DoCreateMarker_Concurrent 必 FAILED，无限重试。
    return false;
}
```

**为什么是 pull 不是 push**：push 式失效即重算会引发并发重建风暴——上游数据没准备好时，下游创建任务必然失败并无限重试。pull 模型让重建天然按依赖顺序、只重建真正可见（resident）的 tile。

---

## 4 · 一图讲清（建议替换现版环形图）

```
          编辑/生成 Overlayer Actor（Box 或 Spline）
                        │  PrefabAlgorithm 跑一遍
                        ▼
        OutputFragment（带 ProducerName / InvalidateProducerNames / Tiles / FeatureID）
                        │
        ┌───────────────┴────────────────┐
        ▼ ① Push 注册                      ▼ ② Push 失效（SubmitOverlayer）
  ProducerFragmentsSubsystem          沿 InvalidateProducerNames 找 Producer
  （数据仓，四级索引                    ├─ 贴图族：InvalidateMarkers_Internal（整体清空）
   Owner+Producer+Feature+Tile）       └─ 实体族：tile 祖先展开 + Dependent 图递归 InvalidateMarker
        │                                          │
        │                                          ▼ 只打 dirty，不重算
        │                              ③ LOD 系统每帧 IsResidentDataDirty() → Pull
        └──────────► MarkerProducer 重建该 tile 时 GetProducerTypedFragments<T>() 拉回 fragment，叠加进产物
```

四个角色（替换现版 4 卡）：
1. **Overlayer OutputFragment** — 携带「影响谁 / 影响哪 / 我是谁」的叠加数据片段。
2. **ProducerFragmentsSubsystem** — 纯数据仓，四级索引，**只存不失效**。
3. **SubmitOverlayer（失效枢纽）** — 贴图族整体失效 vs 实体族依赖图递归失效。
4. **Pull 重建** — LOD 每帧检测 dirty，按需、按依赖顺序拉回 fragment 重算。

---

## 5 · 这页要传达的 3 条「魅力点」（底部栏）

1. **解耦**：Overlayer 不持有 Producer，全靠 `ProducerName` 字符串牵线；注册 / 失效 / 重建三段彻底分离。
2. **依赖图驱动**：失效沿运行时 marker 粒度的 Dependent 引用图递归传播（纵向到祖先 + 横向到下游），不是拍脑袋全量刷。
3. **Pull 不 Push**：失效只打标记，重建交 LOD 按需拉取，从架构上规避并发重建风暴。

---

## 6 · 附录 · 易被讲错 / 需要谨慎的点

- **「Producer DAG」别误用**：存在两套图。运行时真正驱动失效的是 `TAesMarkerDependent` 的 `Dependencies`/`Referencers`（marker 粒度，`Depend()` 双向登记）。另一套 `FAesMarkerProducerGraph`（producer 粒度，`ProducerEdges`+`PayloadRoots`）**仅 `WITH_EARTH_DEBUGGER` 编译**，用于 AesWorldProfiling 的 JSON 导出 / 可视化，**不参与运行时失效**。演示讲传播请用前者。
- **中枢 property_count**：KB 索引标 `FEarthMarkerProducerFragments` property_count=4，**实际源码是 3 个 TMap**，以源码为准。
- **Subsystem 的 Tick**：它继承 `UTickableWorldSubsystem`，但头 / 源均**无 `Tick` override**（仅 override `GetStatId`/`Deinitialize`），不做任何延迟 / 批量 invalidate。
- **采样器枚举**：Fragment 侧是 `EEarthOverlayerSamplerType`，EarthMisc 的 Settings 侧是 `EEarthSamplerType`，两个同义枚举并存（历史原因，无需在 slide 展开）。
- **未深挖（如需进一步上屏可追加研究）**：① DEM 高程 fragment 经 `FEarthDemOverlayerVS/PS` 最终如何写入地形；② `FMarker::Invalidate()` 函数体本身（其语义来自 `InvalidateMarker_Internal` 的权威注释）；③ 四件套继承链为何刻意不平行的设计动机。

---

## 7 · 待你确认的几处取舍

1. 这页**信息密度明显高于原版**（原版几乎是空壳）。是否要在一屏内全塞，还是聚焦「三段式链路 + 两族区分」，把谱系树和附录收进备注？
2. **两族失效粒度差异**（贴图整体清空 vs 实体依赖图递归）是这页最硬的技术点，但也最细——要不要上屏，还是只讲统一的「注册 + 失效 + pull 重建」？
3. 是否保留并强调那条**「pull 不 push、规避并发重建风暴」**的设计 insight（我认为这是最有价值的一句）？
