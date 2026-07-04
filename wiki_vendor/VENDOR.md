# Wiki Vendor Assets

`memory_site.py` 生成的整库交互 wiki 依赖以下第三方前端库，均以离线 vendor 方式打包，
生成时复制到 `memory/wiki/vendor/`，页面运行时零 CDN/网络依赖。

| 文件 | 库 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- | --- |
| `vis-network.min.js` | [vis-network](https://github.com/visjs/vis-network) (standalone/umd，含 vis-data) | 10.1.0 | Apache-2.0 OR MIT | 业务流程图节点/边渲染：自动分层布局 + 原生拖拽 + 缩放平移，无重叠 |
| `github-markdown.css` | [github-markdown-css](https://github.com/sindresorhus/github-markdown-css) | 5.9.0 | MIT | 文档正文排版（标题/表格/代码块），与 GitHub Wiki/Markdown 渲染视觉一致 |

## 更新方式

```powershell
$tmp = "$env:TEMP\wikivendor"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null; cd $tmp; npm init -y | Out-Null
npm install vis-network@<version> github-markdown-css@<version>
Copy-Item "$tmp\node_modules\vis-network\standalone\umd\vis-network.min.js" <repo>\wiki_vendor\
Copy-Item "$tmp\node_modules\github-markdown-css\github-markdown.css" <repo>\wiki_vendor\
```

选型评审（专家组结论，2026-07-04）：

- **入选**：vis-network（dbt docs 同款方案，物理引擎自动消重叠 + 原生拖拽）、github-markdown-css（GitHub 官方 Markdown 渲染样式，零 JS）。
- **候选未入选**：cytoscape.js + cytoscape-dagre（同样成熟，layout 更偏图论/生物信息学场景，作为未来备选）。
- **不适用**：React Flow (`@xyflow/react`) 与 Facebook `astryx` —— 均要求 React + 构建工具链（StyleX/bundler），
  与本工具"纯 Python 单命令生成静态产物、零构建"的架构前提冲突；若未来引入 JS 构建管线可重新评估。
