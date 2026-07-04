"""Memory Wiki：从 memory.sqlite 程序化生成整库人类可读交互查看器。

设计原则（与 MD 渲染层一致）：
1. 唯一数据源是 memory/memory.sqlite，页面不允许出现数据库之外的信息。
2. 纯代码生成，AI 不参与渲染；删除后可随时重新生成，输出确定性。
3. 渐进式披露：业务地图 -> 主题泳道板 -> 节点侧栏 -> 证据片段 + vscode:// 深链。
4. 哈希/ID 等机器数据全部折叠进"技术详情"，默认不打扰人。
5. 单页面交互站（index.html + vendor/），依赖业界成熟开源库并离线 vendor（vis-network 图引擎 + github-markdown-css 排版），
   不接 CDN、不需 npm/构建步骤，双击即开。详见仓库根目录 wiki_vendor/VENDOR.md。

图引擎选型（专家组评审）：vis-network（dbt docs 同款方案）—分层自动布局消重叠 + 原生拖拽，
单文件集成无需构建。cytoscape.js+dagre 为候选道; React Flow / Facebook astryx 因强依赖 React 构建链不适用。

形态对标 dbt docs：构建产物 -> 静态交互站（DAG + 详情侧栏 + 搜索）。
"""

from __future__ import annotations

import html
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .query_memory import _connect

SNIPPET_RADIUS = 6
# 与 templates/ 同级（ue5_kb/query/memory_site.py 向上三级到仓库根），与 generate.py 定位 templates 目录的约定一致
VENDOR_DIR = Path(__file__).parent.parent.parent / "wiki_vendor"
VENDOR_ASSETS = ("vis-network.min.js", "github-markdown.css")


def _read_snippet(source_root: Optional[Path], file_value: str, line_number: int) -> Optional[Dict[str, Any]]:
    """读取证据锚点 ±SNIPPET_RADIUS 行源码片段（生成时嵌入，离线可看）。"""
    if not source_root or not file_value:
        return None
    path = Path(source_root) / file_value
    try:
        if not path.is_file():
            return None
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    line = max(1, int(line_number or 1))
    start = max(1, line - SNIPPET_RADIUS)
    end = min(len(lines), line + SNIPPET_RADIUS)
    return {
        "start": start,
        "focus": line,
        "lines": lines[start - 1 : end],
    }


def _vscode_url(source_root: Optional[Path], file_value: str, line_number: int) -> Optional[str]:
    if not source_root or not file_value:
        return None
    absolute = (Path(source_root) / file_value).resolve()
    return "vscode://file/" + str(absolute).replace("\\", "/") + f":{int(line_number or 1)}"


def _latest_published_flow(conn: sqlite3.Connection, subject_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT flow_json, graph_hash, created_at FROM business_flow_annotations
        WHERE subject_id=? AND status='published'
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (subject_id,),
    ).fetchone()
    if not row:
        return None
    try:
        flow = json.loads(row[0])
    except Exception:
        return None
    flow["_graph_hash"] = row[1]
    flow["_created_at"] = row[2]
    return flow


def _collect_payload(conn: sqlite3.Connection, source_root: Optional[Path]) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    subjects: List[Dict[str, Any]] = []
    for subject in conn.execute("SELECT * FROM business_subjects ORDER BY display_name").fetchall():
        subject_id = subject["id"]
        aliases = [row["alias"] for row in conn.execute(
            "SELECT alias FROM business_subject_aliases WHERE subject_id=? ORDER BY alias", (subject_id,)).fetchall()]
        memory_ids = [row["member_id"] for row in conn.execute(
            "SELECT DISTINCT member_id FROM business_subject_members WHERE subject_id=? AND member_kind='trace_route'",
            (subject_id,)).fetchall()]
        memories = []
        evidence_map: Dict[str, Dict[str, Any]] = {}
        for memory_id in memory_ids:
            pattern = conn.execute("SELECT * FROM query_memory_patterns WHERE id=?", (memory_id,)).fetchone()
            if not pattern:
                continue
            step_count = conn.execute(
                "SELECT COUNT(*) FROM query_memory_steps WHERE memory_id=?", (memory_id,)).fetchone()[0]
            steps = [
                {"command": row["command"], "args": row["args_summary"], "count": row["result_count"]}
                for row in conn.execute(
                    "SELECT command, args_summary, result_count FROM query_memory_steps WHERE memory_id=? ORDER BY step_index",
                    (memory_id,)).fetchall()
            ]
            memories.append({
                "id": memory_id,
                "intent": pattern["intent"],
                "seed": pattern["seed"],
                "status": pattern["status"],
                "branch": pattern["branch_name"],
                "commit": pattern["commit_id"],
                "created_at": pattern["created_at"],
                "last_validated_at": pattern["last_validated_at"],
                "step_count": step_count,
                "steps": steps,
            })
            for row in conn.execute(
                "SELECT file, line_start, symbol, module, file_hash FROM query_memory_evidence WHERE memory_id=?",
                (memory_id,)).fetchall():
                key = f"{row['file']}:{row['line_start']}"
                if key in evidence_map:
                    continue
                snippet = _read_snippet(source_root, row["file"], row["line_start"] or 1)
                evidence_map[key] = {
                    "file": row["file"],
                    "line": row["line_start"],
                    "symbol": row["symbol"],
                    "module": row["module"],
                    "file_hash": row["file_hash"],
                    "snippet": snippet,
                    "vscode": _vscode_url(source_root, row["file"], row["line_start"] or 1),
                }
        flow = _latest_published_flow(conn, subject_id)
        if flow and source_root:
            # 为 flow 节点证据补片段与深链（同一证据只嵌一次）
            for node in flow.get("nodes", []):
                enriched = []
                for ref in node.get("evidence", []):
                    core = str(ref).split("|", 1)[0].strip()
                    path_part, _, line_part = core.rpartition(":")
                    line_no = int(line_part) if line_part.isdigit() else 1
                    enriched.append({
                        "ref": ref,
                        "snippet": _read_snippet(source_root, path_part, line_no),
                        "vscode": _vscode_url(source_root, path_part, line_no),
                    })
                node["evidence_view"] = enriched
        relations = [
            {"target": row["target_subject_id"], "type": row["relation_type"], "status": row["status"]}
            for row in conn.execute(
                "SELECT target_subject_id, relation_type, status FROM business_subject_relations WHERE source_subject_id=?",
                (subject_id,)).fetchall()
        ]
        evolution = [
            {"kind": "flow", "id": row["id"], "status": row["status"], "created_at": row["created_at"]}
            for row in conn.execute(
                "SELECT id, status, created_at FROM business_flow_annotations WHERE subject_id=? ORDER BY created_at",
                (subject_id,)).fetchall()
        ] + [
            {"kind": "snapshot", "id": row["id"], "status": "archived", "created_at": row["created_at"]}
            for row in conn.execute(
                "SELECT id, created_at FROM memory_snapshots WHERE subject_id=? ORDER BY created_at",
                (subject_id,)).fetchall()
        ]
        evolution.sort(key=lambda item: item["created_at"])
        subjects.append({
            "id": subject_id,
            "name": subject["display_name"],
            "status": subject["status"],
            "primary_symbol": subject["primary_symbol"],
            "updated_at": subject["updated_at"],
            "aliases": aliases,
            "memories": memories,
            "evidence": sorted(evidence_map.values(), key=lambda item: (item["file"], item["line"] or 0)),
            "flow": flow,
            "relations": relations,
            "evolution": evolution,
        })

    patterns = []
    for pattern in conn.execute("SELECT * FROM business_patterns ORDER BY name").fetchall():
        stages = [
            {"name": row["stage_name"], "index": row["stage_index"], "status": row["status"]}
            for row in conn.execute(
                "SELECT stage_name, stage_index, status FROM business_pattern_stages WHERE pattern_id=? ORDER BY stage_index",
                (pattern["id"],)).fetchall()
        ]
        members = [row["subject_id"] for row in conn.execute(
            "SELECT DISTINCT subject_id FROM business_pattern_members WHERE pattern_id=?", (pattern["id"],)).fetchall()]
        patterns.append({
            "id": pattern["id"],
            "name": pattern["name"],
            "status": pattern["status"],
            "stages": stages,
            "members": members,
        })

    hints = [
        {
            "command": row["command"],
            "args": row["args_summary"],
            "failure_type": row["failure_type"],
            "error": row["error_summary"],
            "created_at": row["created_at"],
        }
        for row in conn.execute(
            "SELECT command, args_summary, failure_type, error_summary, created_at FROM negative_hints ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    ]

    return {
        "generated_at": int(time.time()),
        "source_root": str(source_root) if source_root else None,
        "subjects": subjects,
        "patterns": patterns,
        "negative_hints": hints,
        "stats": {
            "subject_count": len(subjects),
            "pattern_count": len(patterns),
            "memory_count": sum(len(s["memories"]) for s in subjects),
            "evidence_count": sum(len(s["evidence"]) for s in subjects),
            "hint_count": len(hints),
        },
    }


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory Wiki - 业务知识查看器</title>
<!--
generated_by: UE5_KnowledgeBaseMaker query_memory_render_site
data_source: memory/memory.sqlite
markdown_is_authoritative: false
本文件为程序化生成产物，可随时删除并重新生成；事实以 sqlite + validate/replay 为准。
graph_engine: vis-network (vendor/vis-network.min.js, MIT/Apache-2.0, 离线 vendor)
typography: github-markdown-css (vendor/github-markdown.css, MIT, 离线 vendor)
-->
<link rel="stylesheet" href="vendor/github-markdown.css">
<style>
:root{--bg:#12141a;--panel:#1b1e27;--card:#232735;--line:#3a4055;--text:#e6e9f2;--dim:#9aa3b8;
--accent:#5b9dff;--ok:#3fbf7f;--warn:#e5b458;--bad:#e0626b;--chip:#2c3143;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.6 "Segoe UI",system-ui,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{display:flex;align-items:center;gap:16px;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line)}
header h1{font-size:16px;font-weight:600}
header .meta{color:var(--dim);font-size:12px}
#search{margin-left:auto;background:var(--card);border:1px solid var(--line);color:var(--text);padding:6px 12px;border-radius:6px;width:280px}
main{flex:1;display:flex;min-height:0}
nav{width:250px;background:var(--panel);border-right:1px solid var(--line);overflow-y:auto;padding:10px}
nav h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:12px 8px 4px}
nav a{display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;color:var(--text);text-decoration:none;font-size:13px}
nav a:hover,nav a.active{background:var(--card)}
.badge{width:8px;height:8px;border-radius:50%;flex:none}
.b-active,.b-fresh,.b-published{background:var(--ok)}
.b-changed,.b-unknown,.b-candidate{background:var(--warn)}
.b-broken,.b-failed{background:var(--bad)}
#content{flex:1;overflow:auto;padding:18px;position:relative}
#detail{width:0;transition:width .15s;background:var(--panel);border-left:1px solid var(--line);overflow-y:auto;flex:none}
#detail.open{width:460px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;cursor:pointer}
.card:hover{border-color:var(--accent)}
.card h3{font-size:14px;margin-bottom:4px}
.card .sub{color:var(--dim);font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.chip{background:var(--chip);border-radius:10px;padding:1px 8px;font-size:11px;color:var(--dim)}
#graph-wrap{border:1px solid var(--line);border-radius:8px;background:#0d0f14;margin-bottom:6px;overflow:hidden}
.graph-toolbar{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line);background:var(--panel)}
.graph-toolbar button{background:var(--chip);color:var(--text);border:1px solid var(--line);border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer}
.graph-toolbar button:hover{border-color:var(--accent)}
.graph-toolbar .hint{margin-left:auto;color:var(--dim);font-size:11px}
#graph{height:540px}
#legend{display:flex;flex-wrap:wrap;gap:10px;padding:8px 10px;font-size:11px;color:var(--dim);border-top:1px solid var(--line)}
#legend .sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle}
/* markdown-body 默认跟随系统浅/深色偏好；页面自身固定深色，此处强制复用官方 dark 变量不跟系统切换 */
.markdown-body{
  color-scheme:dark;background:transparent;font-size:13px;
  --fgColor-accent:#4493f8;--bgColor-default:#161b22;--bgColor-muted:#151b23;--bgColor-neutral-muted:#656c7633;
  --borderColor-accent-emphasis:#1f6feb;--borderColor-default:#3d444d;--borderColor-muted:#3d444db3;
  --fgColor-default:#e6e9f2;--fgColor-muted:#9198a1;--fgColor-danger:#f85149;--fgColor-success:#3fb950;
}
.markdown-body table{width:100%;display:table}
.section{margin-bottom:20px}
.section>h2{font-size:15px;margin-bottom:10px;border-left:3px solid var(--accent);padding-left:8px}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{color:var(--dim);background:var(--panel)}
pre.snippet{background:#0d0f14;border:1px solid var(--line);border-radius:6px;padding:8px;font:12px/1.5 Consolas,monospace;overflow-x:auto;margin:6px 0}
pre.snippet .focus{background:#2b3a55;display:block}
pre.snippet .ln{color:#525b73;user-select:none;display:inline-block;width:44px}
.btn{display:inline-block;background:var(--accent);color:#fff;border-radius:5px;padding:3px 10px;font-size:12px;text-decoration:none;margin:2px 4px 2px 0}
.btn.ghost{background:var(--chip);color:var(--dim)}
details.tech{margin-top:10px;color:var(--dim);font-size:12px}
details.tech summary{cursor:pointer}
details.tech code{word-break:break-all}
#detail h2{font-size:15px;margin-bottom:6px}
#detail .close{float:right;cursor:pointer;color:var(--dim);font-size:18px}
#detail h4{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin:14px 0 6px}
.timeline{list-style:none}
.timeline li{padding:4px 0 4px 16px;border-left:2px solid var(--line);position:relative;font-size:12px}
.timeline li::before{content:'';position:absolute;left:-5px;top:10px;width:8px;height:8px;border-radius:50%;background:var(--accent)}
.hidden{display:none}
.hl{outline:2px solid var(--warn)}
</style>
</head>
<body>
<header>
  <h1>Memory Wiki</h1>
  <span class="meta" id="meta"></span>
  <input id="search" placeholder="搜索业务 / 别名 / 符号 / 文件… (回车跳转)">
</header>
<main>
  <nav id="nav"></nav>
  <div id="content"></div>
  <aside id="detail"></aside>
</main>
<script id="data" type="application/json">__DATA__</script>
<script src="vendor/vis-network.min.js"></script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const $ = (sel, el) => (el || document).querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN') : '—';
const badge = st => `<span class="badge b-${esc(st || 'unknown')}"></span>`;
const LANE_PALETTE = ['#5b9dff','#3fbf7f','#e5b458','#e0626b','#a56bf0','#38b6c9','#f08a5d','#7ac2ff','#c792ea','#8bd450'];
let currentNetwork = null;
function laneColor(lanes, lane) {
  const idx = Math.max(0, lanes.indexOf(lane));
  return LANE_PALETTE[idx % LANE_PALETTE.length];
}

function navRender() {
  const subj = DATA.subjects.map(s =>
    `<a href="#subject/${esc(s.id)}" data-route="subject/${esc(s.id)}">${badge(s.status)}${esc(s.name)}</a>`).join('');
  const pat = DATA.patterns.map(p =>
    `<a href="#pattern/${esc(p.id)}" data-route="pattern/${esc(p.id)}">${badge(p.status)}${esc(p.name)}</a>`).join('');
  $('#nav').innerHTML = `
    <a href="#map" data-route="map">🗺️ 业务地图</a>
    <h2>业务主题 (${DATA.subjects.length})</h2>${subj}
    <h2>业务模式 (${DATA.patterns.length})</h2>${pat}
    <h2>其他</h2>
    <a href="#hints" data-route="hints">⚠️ 避坑记录 (${DATA.negative_hints.length})</a>`;
}

function snippetHtml(sn) {
  if (!sn) return '<div class="chip">源码片段不可用（生成时未能读取源文件）</div>';
  return '<pre class="snippet">' + sn.lines.map((line, i) => {
    const no = sn.start + i;
    const body = `<span class="ln">${no}</span>${esc(line)}`;
    return no === sn.focus ? `<span class="focus">${body}</span>` : body;
  }).join('\\n') + '</pre>';
}

function evidenceHtml(ev) {
  const open = ev.vscode ? `<a class="btn" href="${esc(ev.vscode)}">在 VS Code 打开</a>` : '';
  return `<div class="section">
    <div><code>${esc(ev.ref || (ev.file + ':' + ev.line))}</code> ${open}</div>
    ${snippetHtml(ev.snippet)}</div>`;
}

function renderFlowGraph(container, flow) {
  if (currentNetwork) { currentNetwork.destroy(); currentNetwork = null; }
  const lanes = flow.lanes || [];
  const nodes = (flow.nodes || []).map(n => ({
    id: n.id,
    label: n.label.length > 26 ? n.label.slice(0, 25) + '…' : n.label,
    title: n.summary || '',
    level: Math.max(0, lanes.indexOf(n.lane)),
    shape: 'box',
    margin: 10,
    widthConstraint: { maximum: 220 },
    color: { background: '#232735', border: laneColor(lanes, n.lane), highlight: { background: '#2c3143', border: '#5b9dff' } },
    font: { color: '#e6e9f2', size: 12, face: 'Segoe UI, sans-serif' },
    borderWidth: 2,
    shapeProperties: { borderRadius: 6 },
  }));
  const edges = (flow.edges || []).map(e => ({
    from: e.source, to: e.target,
    label: e.condition || e.label || '',
    dashes: !!e.condition,
    arrows: 'to',
    color: { color: e.condition ? '#e5b458' : '#3a4055', highlight: '#5b9dff' },
    font: { color: '#9aa3b8', size: 10, strokeWidth: 0, align: 'top' },
    smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.45 },
  }));
  const network = new vis.Network(container, { nodes, edges }, {
    layout: { hierarchical: {
      enabled: true, direction: 'UD', sortMethod: 'directed',
      levelSeparation: 130, nodeSpacing: 150, treeSpacing: 200,
      blockShifting: true, edgeMinimization: true,
    } },
    physics: { hierarchicalRepulsion: { nodeDistance: 140, springLength: 130 }, stabilization: { iterations: 300 } },
    interaction: { hover: true, dragNodes: true, dragView: true, zoomView: true, tooltipDelay: 150 },
  });
  network.once('stabilizationIterationsDone', () => {
    // 先用 hierarchical 得到无重叠的初始泳道排列，稳定后关闭 physics 与 hierarchical，
    // 节点保持当前位置不跳变，但从此可在 x/y 两个方向自由拖拽（实测验证：关闭 hierarchical 前只能沿同一层水平拖动）。
    network.setOptions({ physics: false, layout: { hierarchical: false } });
  });
  network.on('click', params => {
    if (params.nodes.length) nodeDetail(flow, params.nodes[0]);
    else closeDetail();
  });
  currentNetwork = network;
  return network;
}

function subjectView(s) {
  let body = `<div class="section"><h2>${esc(s.name)} ${badge(s.status)}</h2>
    <div class="chips">${(s.aliases || []).map(a => `<span class="chip">${esc(a)}</span>`).join('')}</div></div>`;
  if (s.flow) {
    const lanes = s.flow.lanes || [];
    const legend = lanes.map(l => `<span><span class="sw" style="background:${laneColor(lanes, l)}"></span>${esc(l)}</span>`).join('');
    body += `<div class="section"><h2>业务流程（可拖拽 / 滞轮缩放 / 点节点看证据）</h2>
      <div id="graph-wrap">
        <div class="graph-toolbar">
          <button id="btn-fit" type="button">适应窗口</button>
          <button id="btn-restack" type="button">重新布局</button>
          <span class="hint">vis-network 自动分层，节点不重叠且可自由拖动</span>
        </div>
        <div id="graph"></div>
        <div id="legend">${legend}</div>
      </div>
    </div>`;
  } else {
    body += `<div class="section"><h2>业务流程</h2><div class="chip">尚无通过质量门禁的流程附注</div></div>`;
  }
  body += `<div class="section markdown-body"><h2>路线记忆（${s.memories.length} 次查询累积）</h2>
    <table><tr><th></th><th>意图</th><th>步数</th><th>记录时间</th><th>最近校验</th></tr>` +
    s.memories.map(m => `<tr><td>${badge(m.status)}</td><td>${esc(m.intent)}</td><td>${m.step_count}</td>
      <td>${fmtTime(m.created_at)}</td><td>${fmtTime(m.last_validated_at)}</td></tr>`).join('') + '</table></div>';
  if (s.evolution.length) {
    body += `<div class="section"><h2>演进史</h2><ul class="timeline">` + s.evolution.map(ev =>
      `<li>${fmtTime(ev.created_at)} · ${ev.kind === 'flow' ? '流程附注' : '快照'} ${badge(ev.status)} ${esc(ev.status)}</li>`).join('') + '</ul></div>';
  }
  body += `<details class="tech"><summary>技术详情（机器数据）</summary>
    <p>subject_id: <code>${esc(s.id)}</code></p>
    ${s.memories.map(m => `<p>memory <code>${esc(m.id)}</code> @ ${esc(m.branch || '')} ${esc(m.commit || '')}</p>`).join('')}
  </details>`;
  $('#content').innerHTML = body;
  if (s.flow) {
    const network = renderFlowGraph($('#graph'), s.flow);
    $('#btn-fit').onclick = () => network.fit({ animation: true });
    $('#btn-restack').onclick = () => {
      // 重新跑一次 hierarchical 分层，结束后再关闭 physics/hierarchical，恢复自由拖拽
      network.setOptions({
        physics: { hierarchicalRepulsion: { nodeDistance: 140, springLength: 130 }, stabilization: { iterations: 300 } },
        layout: { hierarchical: { enabled: true, direction: 'UD', sortMethod: 'directed', levelSeparation: 130, nodeSpacing: 150, treeSpacing: 200 } },
      });
      network.once('stabilizationIterationsDone', () => network.setOptions({ physics: false, layout: { hierarchical: false } }));
      network.stabilize();
    };
  }
}

function nodeDetail(flow, nodeId) {
  const n = (flow.nodes || []).find(x => x.id === nodeId);
  if (!n) return;
  const evs = (n.evidence_view && n.evidence_view.length) ? n.evidence_view
    : (n.evidence || []).map(ref => ({ ref }));
  $('#detail').innerHTML = `<span class="close" onclick="closeDetail()">✕</span>
    <h2>${esc(n.label)}</h2>
    <p>${esc(n.summary || '')}</p>
    ${(n.details || []).map(d => `<p class="sub">· ${esc(d)}</p>`).join('')}
    <h4>源码证据（${evs.length}）</h4>
    ${evs.map(evidenceHtml).join('')}
    <details class="tech"><summary>技术详情</summary>
      ${(n.evidence_anchors || []).map(a => `<p><code>${esc(a.reference)}</code><br>anchor: <code>${esc(a.anchor_hash)}</code></p>`).join('') || '<p>无锚点哈希</p>'}
    </details>`;
  $('#detail').classList.add('open');
  if (currentNetwork) currentNetwork.selectNodes([nodeId]);
}
function closeDetail() {
  $('#detail').classList.remove('open');
  $('#detail').innerHTML = '';
  if (currentNetwork) currentNetwork.unselectAll();
}

function mapView() {
  const cards = DATA.subjects.map(s => {
    const rel = (s.relations || []).map(r => `<span class="chip">${esc(r.type)} → ${esc(nameOf(r.target))}</span>`).join('');
    return `<div class="card" onclick="location.hash='subject/${esc(s.id)}'">
      <h3>${badge(s.status)} ${esc(s.name)}</h3>
      <div class="sub">路线 ${s.memories.length} · 证据 ${s.evidence.length} · ${s.flow ? '✅ 有业务流程图' : '尚无流程图'}</div>
      <div class="chips">${rel}</div></div>`;
  }).join('');
  const pats = DATA.patterns.map(p => `<div class="card" onclick="location.hash='pattern/${esc(p.id)}'">
      <h3>${badge(p.status)} ${esc(p.name)}</h3>
      <div class="sub">阶段 ${p.stages.length} · 支撑主题 ${p.members.length}</div></div>`).join('');
  $('#content').innerHTML = `
    <div class="section"><h2>业务主题地图</h2><div class="grid">${cards}</div></div>
    <div class="section"><h2>业务模式（跨主题归纳）</h2><div class="grid">${pats || '<span class="chip">暂无</span>'}</div></div>`;
}

function patternView(p) {
  $('#content').innerHTML = `<div class="section"><h2>${esc(p.name)} ${badge(p.status)}</h2></div>
    <div class="section markdown-body"><h2>阶段</h2><table><tr><th>#</th><th>阶段</th><th>状态</th></tr>
    ${p.stages.map(st => `<tr><td>${st.index}</td><td>${esc(st.name)}</td><td>${badge(st.status)} ${esc(st.status)}</td></tr>`).join('')}</table></div>
    <div class="section"><h2>支撑主题</h2><div class="grid">
    ${p.members.map(id => `<div class="card" onclick="location.hash='subject/${esc(id)}'"><h3>${esc(nameOf(id))}</h3></div>`).join('') || '<span class="chip">暂无</span>'}</div></div>
    <details class="tech"><summary>技术详情</summary><p>pattern_id: <code>${esc(p.id)}</code></p></details>`;
}

function hintsView() {
  $('#content').innerHTML = `<div class="section markdown-body"><h2>避坑记录（失败被自动隔离，不污染成功路线）</h2>
    <table><tr><th>命令</th><th>参数</th><th>失败类型</th><th>错误摘要</th><th>时间</th></tr>
    ${DATA.negative_hints.map(h => `<tr><td><code>${esc(h.command)}</code></td><td><code>${esc(h.args || '')}</code></td>
      <td>${esc(h.failure_type)}</td><td>${esc(h.error || '')}</td><td>${fmtTime(h.created_at)}</td></tr>`).join('')}</table></div>`;
}

function nameOf(subjectId) {
  const s = DATA.subjects.find(x => x.id === subjectId);
  return s ? s.name : subjectId;
}
function current() {
  const [kind, id] = (location.hash.slice(1) || 'map').split('/');
  return kind === 'subject' ? DATA.subjects.find(s => s.id === id) : null;
}

function route() {
  closeDetail();
  const hash = location.hash.slice(1) || 'map';
  const [kind, id] = hash.split('/');
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.dataset.route === hash));
  if (kind === 'subject') { const s = DATA.subjects.find(x => x.id === id); if (s) return subjectView(s); }
  if (kind === 'pattern') { const p = DATA.patterns.find(x => x.id === id); if (p) return patternView(p); }
  if (kind === 'hints') return hintsView();
  mapView();
}

$('#search').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim().toLowerCase();
  if (!q) return;
  const hit = DATA.subjects.find(s =>
    s.name.toLowerCase().includes(q) ||
    (s.aliases || []).some(a => a.toLowerCase().includes(q)) ||
    (s.evidence || []).some(ev => (ev.file || '').toLowerCase().includes(q) || (ev.symbol || '').toLowerCase().includes(q)) ||
    ((s.flow && s.flow.nodes) || []).some(n => (n.label || '').toLowerCase().includes(q)));
  if (hit) location.hash = 'subject/' + hit.id;
});

$('#meta').textContent = `生成于 ${fmtTime(DATA.generated_at)} · 主题 ${DATA.stats.subject_count} · 路线 ${DATA.stats.memory_count} · 证据 ${DATA.stats.evidence_count} · 数据源 memory.sqlite（本页面为程序化生成产物）`;
window.addEventListener('hashchange', route);
window.addEventListener('resize', () => { if (currentNetwork) currentNetwork.fit(); });
navRender();
route();
</script>
</body>
</html>
"""


def export_site(*, skill_dir: Path, source_root: Optional[Path] = None) -> Dict[str, Any]:
    """从 memory.sqlite 程序化生成单文件交互 wiki 到 memory/wiki/index.html。"""
    conn = _connect(skill_dir)
    try:
        payload = _collect_payload(conn, source_root)
    finally:
        conn.close()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 防止内容中的 </script> 提前终结数据块
    data_json = data_json.replace("</", "<\\/")
    page = _PAGE_TEMPLATE.replace("__DATA__", data_json)
    out_dir = Path(skill_dir) / "memory" / "wiki"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.html"
    out_file.write_text(page, encoding="utf-8")
    vendor_out = out_dir / "vendor"
    vendor_out.mkdir(parents=True, exist_ok=True)
    vendor_copied = []
    for name in VENDOR_ASSETS:
        source = VENDOR_DIR / name
        if source.is_file():
            shutil.copy2(source, vendor_out / name)
            vendor_copied.append(name)
    return {
        "schema": "query-memory-render-site/v1",
        "site_file": str(out_file),
        "size_bytes": out_file.stat().st_size,
        "vendor_dir": str(vendor_out),
        "vendor_assets": vendor_copied,
        "stats": payload["stats"],
        "generated_programmatically": True,
        "markdown_is_authoritative": False,
    }
