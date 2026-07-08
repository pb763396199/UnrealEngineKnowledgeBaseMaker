# Wiki Vendor Assets

`memory_site.py` 生成的整库交互 wiki 依赖以下第三方前端库，以离线 vendor 方式打包，
生成时复制到 `memory/wiki/vendor/`，页面运行时零 CDN/网络依赖。

| 文件 | 库 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- | --- |
| `github-markdown.css` | [github-markdown-css](https://github.com/sindresorhus/github-markdown-css) | 5.9.0 | MIT | 文档正文排版（标题/表格/代码块），与 GitHub Wiki/Markdown 渲染视觉一致 |
| `dockview-core.min.js` / `dockview.css` | [dockview-core](https://github.com/mathuo/dockview) | 6.6.1 | MIT | 真正的可拖拽/停靠/自由调整布局的窗口系统（对齐 Unreal Editor 停靠窗口范式），framework-agnostic UMD 构建，不依赖 React |

图引擎（业务流程图）**不再 vendor 第三方库**，改为 `memory_site.py` 内 `compute_static_layout()`
纯 Python 实现的确定性静态分层布局，随数据一次性算好坐标，前端只画静态 SVG，不跑任何
运行时物理模拟/自动布局。详见下方"图引擎选型历史"。

## 更新方式（github-markdown-css）

```powershell
$tmp = "$env:TEMP\wikivendor"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null; cd $tmp; npm init -y | Out-Null
npm install github-markdown-css@<version>
Copy-Item "$tmp\node_modules\github-markdown-css\github-markdown.css" <repo>\wiki_vendor\
```

## 更新方式（dockview-core）

```powershell
$tmp = "$env:TEMP\wikivendor"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null; cd $tmp; npm init -y | Out-Null
npm install dockview-core@<version>
Copy-Item "$tmp\node_modules\dockview-core\dist\dockview-core.min.noStyle.js" <repo>\wiki_vendor\dockview-core.min.js
Copy-Item "$tmp\node_modules\dockview-core\dist\styles\dockview.css" <repo>\wiki_vendor\dockview.css
```

用 `.min.noStyle.js`（不含内联样式的纯逻辑构建）+ 单独的 `dockview.css`，而不是
`dockview-core.min.js`（样式内联版），是为了让我们自己的深色主题 CSS 变量覆盖能正常生效、
避免内联样式的优先级冲突。

## 窗口系统选型（2026-07-08）

用户明确要求"完全遵循 Unreal Editor 的完整框架：所有窗口都可以独立拖动、自由摆放
layout 和尺寸调整"，并指向 `F:\ShanghaiP4\neon\Plugins\EarthPrefabStudio`（同团队之前
尝试用 web 复刻 Unreal Editor 的项目）作为参考——该项目的 `package.json` 依赖列表里选定
了 `dockview`（React 封装）。往下追踪其核心引擎 `dockview-core`：**framework-agnostic，
零依赖，纯 vanilla TypeScript**，通过 UMD 构建可直接 `<script>` 标签引入、暴露
`window['dockview-core']` 全局对象，完全不需要 React/构建工具链，与本工具"纯 Python
单命令生成静态产物、零构建"的架构完全兼容。

在此之前的方案（`.panel`/`.panel-header` 静态 CSS 组件，仅在视觉上模拟"停靠窗口"的
边框+标题栏）无法满足"自由拖动/停靠/调整布局"这一核心需求——那只是视觉皮肤，不是真正
的窗口管理器。`dockview-core` 提供完整的窗口管理能力：拖拽改变停靠位置、分组标签页、
浮动窗口、任意方向的 split 布局调整，是这次真正要采用的方案。

## 图引擎选型历史（专家组评审 + 实战迭代教训）


**2026-07-04 首次评审**：入选 vis-network（dbt docs 同款方案，物理引擎自动消重叠 + 原生拖拽）；
候选未入选 cytoscape.js + cytoscape-dagre；不适用 React Flow / Facebook `astryx`（均要求
React + 构建工具链，与本工具"纯 Python 单命令生成静态产物、零构建"架构冲突）。

**2026-07-04 实战反馈后修正**：vis-network 接入后实机反馈"图一直在动来动去"，即便关闭
physics 稳定后仍有初始阶段可见的多秒物理收敛动画，体验不专业。回查 `F:\AiProject\DecisionReview`
项目（同类"决策树/业务流程可视化"需求，历经数十轮真实用户反馈）的完整迭代历史：该项目同样
从力导向物理图起步，被反复否定，最终收敛到 **Archify 的 architecture 渲染风格**——服务端
一次性计算好的**纯静态 SVG**（矩形节点 + 泳道分组框 + 直角走线 + 拖拽仅做手动微调，不触发
任何重排）。该项目的 `output-guidelines.md` 明确写明中央图应为"Archify architecture style
or a faithful architecture-style fallback"，即允许不依赖 Archify/Node，只需忠实复刻其静态
布局视觉即可。

据此移除 vis-network vendor（644KB 运行时物理引擎），改为 `compute_static_layout()`
纯 Python 确定性分层布局（barycenter 排序减少交叉 + 固定坐标 + 直角走线路径预计算），
前端零布局算法、零物理模拟，只负责渲染与"点击查看详情 / 滚轮缩放 / 拖动单节点手动调整"
三类交互，且拖动一个节点不会牵动其余节点重排。
