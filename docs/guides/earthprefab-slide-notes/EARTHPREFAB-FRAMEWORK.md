---
title: 第 4 页 EarthPrefab 框架 · 内容底稿
status: draft
language: zh-CN
updated: 2026-06-16
purpose: 优化 aesworld-pcg-agent-presentation 第 4 页（EarthPrefab 框架）的内容底稿，先 MD 调整后改 slide
slide_target: F:\ShanghaiP4\neon\Plugins\AesWorld\docs\guides\aesworld-pcg-agent-presentation\slides\04-earthprefab-ecs.html
sources:
  - 7 份 2025-03 设计 PDF（PrefabFramework / EarthFragment / EarthPrefab / EarthAlgorithm / PrefabAsset / EarthPrefabActor / 架构图）
  - 最新代码核对（UE Research 直读 F:\ShanghaiP4\neon\Plugins\AesWorld\Source\EarthPrefab，commit a69bc21）
---

# 第 4 页 · EarthPrefab 框架内容底稿

> 这页要在一屏内讲清 EarthPrefab 这套「类 ECS 程序化生成框架」的**四大支柱 + 核心价值**，并纠正旧讲稿过于精简的问题。所有事实以**最新代码**为准（已对照 2025-03 设计文档修正）。

---

## 0 · 当前页面的问题

现版第 4 页只有：一句「类 ECS 生成语言」+ 三张小卡片（数据片段/实体数据/算法系统）+ 一张中心放射图。问题：

- 只点了名字，没讲**每根支柱是什么、解决什么**。
- 没体现这套框架的**核心价值与魅力**（数据-逻辑解耦、类型安全动态组合、声明式可插拔算法、GIS 专项词汇表、低门槛共创闭环）。
- 没有「数据 → 算法 → 资产 → 创造器」的**流转关系**。

---

## 1 · 一句话主张（Hero）

**EarthPrefab：把 GIS 数据变成可生成、可组合、可持久化的「数字地球乐高」。**

副标题：一套类 ECS 的程序化生成框架——数据、逻辑、资产、创作四层正交，无中央 Entity Manager，蓝图/原生双通路低门槛共创。

---

## 2 · 四大支柱（页面主体，左→右一条生产线）

> 对照架构图：**数据层（Fragment + Prefab）→ 逻辑层（Algorithm）→ 资产与工具层（PrefabAsset + Actor）**。

### ① EarthFragment — 数据片段（纯数据，类 Component）
- 基类 `FEarthFragment`：`Init / Validate / GetFragmentType / Clone / CalculateHash`。**纯数据、不含逻辑**。
- **6 大类型**（`EEarthFragmentType` 位掩码枚举，代码坐实）：
  - **Entity 实体** — GIS 要素核心属性（建筑/立面/屋顶/道路/地块/路网…）
  - **Spatial 空间** — 几何与布局（点/样条/Box/ZoneShape，对接矢量/点云/栅格）
  - **Property 属性** — 可下传子资产的次要属性（材质/颜色/Bounds/Tag）
  - **Output 输出** — 最终产物（StaticMesh / InstancedStaticMesh / DynamicMesh / Actor / Collision）
  - **External 外部** — 外部注入的控制指令/数据源标识（Seed / Transform / Rebuild）
  - **Extension 扩展** — 第三方/自研扩展（自研 ShapeGrammar 形态语法）
- 一句话：**GIS 数据的丰富「词汇表」**——一族原生片段，覆盖建筑/道路/地形改造/护岸/形态语法。

### ② EarthPrefab — 预制体数据（类 Entity 容器）
- 容器本体 `FEarthDataBase`：`TArray<FInstancedStruct> Fragments` + `TMap<FName, FEarthFragmentStructInfo> TypeMap`。
- **O(1) 类型查找 + 类型安全模板访问**：`GetFragment<T>` / `AddFragment<T>` / `RemoveFragment` / `ContainsFragment`，运行时任意增删片段而不破坏类型边界。
- 继承/模板片段共享：`FEarthFragmentCache`（父缓存 + 模板缓存）。
- 一句话：**像搭积木一样自由拼装片段**，无继承爆炸、无中央管理器。

### ③ EarthAlgorithm — 算法（ECS 系统层 / 框架的「大脑」）
- 基类 `UEarthPrefabAlgorithm`（`Abstract, Blueprintable`）：声明式 `ConfigureRequirements` + `AddRequirement<T>` 声明所需片段。
- **逐实体执行**：`EntityLoop / EntityLoopBody` 自动校验 `RequiredFragments`，输出经 `FEarthOutputCollection.Merge` 合并；输入经 `FEarthInputCollection`。
- **数据-逻辑彻底解耦**：算法是无状态 UObject，只处理片段数据，不依赖具体实体类型。
- **可插拔算法族**（按特性原生铺开，非旧文档的「仅 PCG/RPK 扩展」）：KB 核证 `UEarthPrefabAlgorithm` 共 **30 个原生子类**，覆盖 Building / Facade(+Mesh) / FlatRoof / HipRoof / Plot / GridLayout / Cluster / Road / RoadNet / RoadJunction / RoadModeler(+Junction / JunctionMarking / Lane) / JunctionSurface / InstanceSpline / Terraforming / Embankment / ChannelIsland / EntityOverlayer / WaterEntityOverlayer / Texture·Dem·Dom Extractor·Overlayer 等（分布在 EarthPrefab + AesEarth 模块）。
- **超出原设计的新能力**：`Guess` 猜测器（反推预制体匹配）、`ExecuteParallel` 并行执行（批 512）、`ExecuteWithPrefabShared` 共享执行。
- 一句话：**声明依赖、即插即用、可并行的「算法乐高」**，蓝图无需编程也能组合生成规则。

### ④ PrefabAsset + EarthPrefabActor — 资产与创造器
- 资产 `UEarthPrefabAsset`（`UDataAsset`）：`ExecuteAlgorithm` + 模板继承 + 输入/输出集合 + 缩略图 + `ValidateAsset`。作为**数字资产容器 / 交换格式**，供渲染/物理/AI 等任意模块消费。
- **JSON 文本化双向同步**（代码新增，文档未载）：`EEarthPrefabSyncState`（Unlinked/Synced/ExternalNewer/InternalNewer/Conflict）+ Link/Push/Reload——可外部编辑、版本对账、运行时热重载。
- 创造器 `AEarthPrefabActor`（`AActor`）：`InputProvider + Algorithm + OutputCollection` 三件组，生命周期 `Build/Cleanup/Prepare/Execute`，实现「**改参数 → 自动生成 → 存为资产**」闭环。
- 一句话：**数字地球乐高工厂**——可视化创作 + 资产持久化 + 文本化协作。

---

## 3 · 核心价值与魅力（页面收束，4 句，均经代码坐实）

1. **数据-逻辑解耦的类 ECS 架构** — 片段(纯数据)/预制体(容器)/算法(无状态系统)/资产(持久化)四层正交，无中央 Entity Manager，对齐 UE Mass 数据导向思想。
2. **类型安全 + O(1) 动态组合** — `FInstancedStruct` 数组自由拼装 + `FName→StructInfo` 即时查找 + `GetFragment<T>` 模板访问，运行时任意增删而不破坏类型边界。
3. **声明式可插拔算法** — `ConfigureRequirements/AddRequirement<T>` 声明所需片段，`EntityLoop` 自动校验，新增蓝图/原生算法即插即用，并已支持并行与猜测器反推。
4. **GIS 专项词汇表 + 低门槛共创闭环** — 建筑/道路/地形改造/形态语法一族原生片段把「GIS 数据→可交互 3D」具体化；Actor「改参→生成→存资产」+ 模板继承 + JSON 文本化同步，蓝图/原生双通路降低创作门槛。

---

## 4 · 与 2025-03 设计文档的关键差异（写稿避坑，不一定上页面）

| 旧文档说法 | 最新代码 | 处理 |
|---|---|---|
| `TypeMap = TMap<UScriptStruct*,int32>` | `TMap<FName, FEarthFragmentStructInfo>` | 页面按代码写 |
| Fragments/TypeMap 在 `FEarthPrefabBase` | 实际在 `FEarthDataBase` | 页面按代码写 |
| 容器合并用 `CombineWith` / `CopyFragmentsData` / `GetDiffFragments` | 未找到，改用 `AppendFragments` / `ReplaceFragments` / `FragmentCache` | 不提旧 API |
| 算法仅 `UEarthPCGPrefabAlgorithm` / `UEarthRpkPrefabAlgorithm` | KB 核证：二者均不存在；`UEarthPrefabAlgorithm` 有 30 个原生子类（Building/Road/RoadModeler/Facade/Roof/Plot/GridLayout/Terraforming…） | 页面讲「30 个原生算法族」 |
| 资产 `GetCombinedPrefab` 合并 | 未找到；合并落到 `FragmentCache` | 不提旧 API |
| Actor `GenerateThumbnail()` | 无同名；以 `bRecaptureThumbnail` + `LoadThumbnail` | 弱化措辞 |
| （文档无） | 新增 Guess 猜测器 / 并行执行 / JSON 文本化同步 / 片段哈希匹配 | 作为「超出原设计」亮点 |

> KB 核证（commit a69bc21，data_trust=fresh）：`search_classes PrefabAlgorithm` 返回 30 个原生子类；`Rpk` / `PCGPrefab` / `CityEngine` 均 `found_count=0`。即旧文档的「PCG/RPK/CityEngine 扩展算法」已被原生 ShapeGrammar + RoadModeler(EarthModeler 模块)体系取代。

---

## 5 · 页面版式建议（对齐 deck.css，16:9 或参照 03 的 4:3）

- **Hero**：主张一句 + 副标题（右侧 why 块放「无中央 Entity Manager · 蓝图/原生双通路」）。
- **主体**：一条横向生产线 SVG —— **Fragment → Prefab → Algorithm → Asset/Actor** 四节点卡片，每卡片 1 行定位 + 2–3 个真实类名/能力点；Fragment 节点下挂 6 类型小标签。
- **底部**：4 句核心价值（可做 2×2 或一行四栏）。
- **footer**：`FEarthFragment · FEarthDataBase · UEarthPrefabAlgorithm · UEarthPrefabAsset` + 页码。
- 沿用上一页（KB Maker）已验证的：deck.css 复用、组件级样式内联、`../shared/slide.js` 缩放、终端直写磁盘 + cache-bust 验证。
