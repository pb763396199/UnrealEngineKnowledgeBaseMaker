"""Memory Wiki：从 memory.sqlite 程序化生成整库人类可读交互查看器。

设计原则（与 MD 渲染层一致）：
1. 唯一数据源是 memory/memory.sqlite，页面不允许出现数据库之外的信息。
2. 纯代码生成，AI 不参与渲染；删除后可随时重新生成，输出确定性。
3. 渐进式披露：业务地图 -> 主题泳道板 -> 节点侧栏 -> 证据片段 + vscode:// 深链。
4. 哈希/ID 等机器数据全部折叠进"技术详情"，默认不打扰人。
5. 单页面交互站（index.html + vendor/），仅 github-markdown-css 排版离线 vendor，不接 CDN、
   不需 npm/构建步骤，双击即开。详见仓库根目录 wiki_vendor/VENDOR.md。

图引擎选型（实战迭代结论）：初版用 vis-network 运行时物理引擎，实机反馈"一直在动来动去"不可接受。
参考 F:\\AiProject\\DecisionReview 项目多轮真实用户迭代：力导向物理图被反复否定，最终收敛到 Archify
的 architecture 渲染风格——服务端一次性计算好的静态 SVG（矩形节点 + 泳道分组框 + 直角走线），
加载后完全不动，只有用户主动拖拽才会移动。本模块用纯 Python 复刻这一布局算法（不引入
Node/Archify 依赖，见 compute_static_layout），前端仅负责渲染与交互，不再跑任何运行时布局/物理模拟。
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
VENDOR_ASSETS = ("github-markdown.css",)


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


# --- 静态分层布局（取代运行时物理引擎） ---------------------------------------
#
# 参考 DecisionReview 项目（F:\AiProject\DecisionReview）的调研结论：多轮真实用户反馈
# 反复否定了力导向物理图（一直在动、可读性差），最终收敛到 Archify 的 architecture
# 渲染风格——服务端一次性计算好的静态 SVG（矩形节点 + 泳道分组框 + 直角走线），加载后
# 完全不动，只有用户主动拖拽才会移动。本模块用纯 Python 复刻这一布局算法（不引入
# Node/Archify 依赖），坐标在生成时一次性算好、写入数据，前端只负责渲染与响应交互。
NODE_W, NODE_H = 200, 56
_LAYOUT_COL_GAP, _LAYOUT_LANE_GAP, _LAYOUT_LANE_PAD, _LAYOUT_LABEL_H, _LAYOUT_MARGIN = 24, 46, 14, 20, 24


def _order_nodes_by_barycenter(lanes: List[str], nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """按 barycenter 启发式对每条泳道内的节点重新排序，减少跨泳道连线交叉（Sugiyama 风格两遍扫描）。"""
    by_lane: Dict[str, List[str]] = {lane: [] for lane in lanes}
    for node in nodes:
        lane = node.get("lane") if node.get("lane") in by_lane else (lanes[0] if lanes else "默认")
        by_lane.setdefault(lane, []).append(node.get("id"))
    preds: Dict[str, List[str]] = {}
    succs: Dict[str, List[str]] = {}
    for edge in edges:
        succs.setdefault(edge.get("source"), []).append(edge.get("target"))
        preds.setdefault(edge.get("target"), []).append(edge.get("source"))

    def pos_index(lane: str) -> Dict[str, int]:
        return {node_id: idx for idx, node_id in enumerate(by_lane.get(lane, []))}

    for _ in range(2):
        for i in range(1, len(lanes)):
            prev_pos = pos_index(lanes[i - 1])
            cur_pos = pos_index(lanes[i])

            def bary_down(node_id: str, _prev_pos=prev_pos, _cur_pos=cur_pos) -> float:
                refs = [_prev_pos[p] for p in preds.get(node_id, []) if p in _prev_pos]
                return (sum(refs) / len(refs)) if refs else float(_cur_pos.get(node_id, 0))

            by_lane[lanes[i]] = sorted(by_lane.get(lanes[i], []), key=bary_down)
        for i in range(len(lanes) - 2, -1, -1):
            next_pos = pos_index(lanes[i + 1])
            cur_pos = pos_index(lanes[i])

            def bary_up(node_id: str, _next_pos=next_pos, _cur_pos=cur_pos) -> float:
                refs = [_next_pos[s] for s in succs.get(node_id, []) if s in _next_pos]
                return (sum(refs) / len(refs)) if refs else float(_cur_pos.get(node_id, 0))

            by_lane[lanes[i]] = sorted(by_lane.get(lanes[i], []), key=bary_up)
    return by_lane


def compute_static_layout(flow: Dict[str, Any]) -> Dict[str, Any]:
    """纯函数、确定性计算：给定 flow(lanes/nodes/edges) 返回节点坐标、泳道边框、直角走线路径。

    不依赖 DOM 测量、不依赖物理模拟，同样的输入永远得到同样的输出（可单测）。
    """
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    lanes = list(flow.get("lanes") or [])
    if not lanes:
        seen: List[str] = []
        for node in nodes:
            lane = node.get("lane") or "默认"
            if lane not in seen:
                seen.append(lane)
        lanes = seen or ["默认"]

    order = _order_nodes_by_barycenter(lanes, nodes, edges)
    row_widths = {
        lane: len(order.get(lane, [])) * NODE_W + max(0, len(order.get(lane, [])) - 1) * _LAYOUT_COL_GAP
        for lane in lanes
    }
    max_width = max(row_widths.values()) if row_widths else NODE_W
    canvas_width = max_width + 2 * (_LAYOUT_MARGIN + _LAYOUT_LANE_PAD)

    positions: Dict[str, Dict[str, float]] = {}
    lane_rects: List[Dict[str, Any]] = []
    y = float(_LAYOUT_MARGIN)
    for lane in lanes:
        band_h = _LAYOUT_LABEL_H + NODE_H + 2 * _LAYOUT_LANE_PAD
        row_w = row_widths.get(lane, 0)
        row_left = _LAYOUT_MARGIN + _LAYOUT_LANE_PAD + (max_width - row_w) / 2
        for idx, node_id in enumerate(order.get(lane, [])):
            x = row_left + idx * (NODE_W + _LAYOUT_COL_GAP)
            node_y = y + _LAYOUT_LABEL_H + _LAYOUT_LANE_PAD
            positions[node_id] = {"x": x, "y": node_y, "w": NODE_W, "h": NODE_H}
        lane_rects.append({"name": lane, "x": float(_LAYOUT_MARGIN), "y": y, "w": canvas_width - 2 * _LAYOUT_MARGIN, "h": band_h})
        y += band_h + _LAYOUT_LANE_GAP
    canvas_height = y - _LAYOUT_LANE_GAP + _LAYOUT_MARGIN

    edge_paths: List[Dict[str, Any]] = []
    corner_r = 10.0
    for edge in edges:
        a = positions.get(edge.get("source"))
        b = positions.get(edge.get("target"))
        if not a or not b:
            continue
        x1, y1 = a["x"] + a["w"] / 2, a["y"] + a["h"]
        x2, y2 = b["x"] + b["w"] / 2, b["y"]
        if abs(x1 - x2) < 1 or y2 <= y1:
            path = f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}"
        else:
            mid = (y1 + y2) / 2
            sign = 1 if x2 > x1 else -1
            path = (
                f"M {x1:.1f} {y1:.1f} L {x1:.1f} {mid - corner_r:.1f} "
                f"Q {x1:.1f} {mid:.1f} {x1 + sign * corner_r:.1f} {mid:.1f} "
                f"L {x2 - sign * corner_r:.1f} {mid:.1f} "
                f"Q {x2:.1f} {mid:.1f} {x2:.1f} {mid + corner_r:.1f} "
                f"L {x2:.1f} {y2:.1f}"
            )
        edge_paths.append({
            "source": edge.get("source"),
            "target": edge.get("target"),
            "path": path,
            "label": edge.get("label") or "",
            "condition": edge.get("condition") or "",
        })

    return {"nodes": positions, "lanes": lane_rects, "edges": edge_paths, "width": canvas_width, "height": canvas_height}


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
        if flow:
            # 服务端一次性算好静态布局坐标；前端不再做任何自动排布，加载后不会移动
            flow["layout"] = compute_static_layout(flow)
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
graph_engine: 服务端确定性静态分层布局（纯 Python compute_static_layout，无运行时物理引擎、无 vendor 依赖）
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
#graph{height:540px;cursor:grab}
#graph:active{cursor:grabbing}
#graph svg{display:block;width:100%;height:100%}
.flow-node{cursor:grab}
.flow-node:active{cursor:grabbing}
.flow-node .node-mask{fill:#000;opacity:0.35;transform:translate(2px,3px)}
.flow-node .node-box{fill:#232735;stroke-width:1.6}
.flow-node:hover .node-box{stroke-width:2.2}
.flow-node.sel .node-box{stroke:#5b9dff;stroke-width:2.6;filter:drop-shadow(0 0 4px rgba(91,157,255,.6))}
.flow-node .node-title{fill:#e6e9f2;font-size:12px;font-weight:600;font-family:"Segoe UI",sans-serif}
.flow-node .node-sub{fill:#9aa3b8;font-size:10px;font-family:"Segoe UI",sans-serif}
.flow-node .node-badge{fill:#3fbf7f;font-size:10px;font-family:"Segoe UI",sans-serif}
.lane-rect{fill:rgba(91,157,255,0.03)}
.lane-label{font-size:10px;font-weight:600;font-family:"Segoe UI",sans-serif}
.flow-edge{stroke:#3a4055;stroke-width:1.5;fill:none}
.flow-edge.dashed{stroke:#e5b458;stroke-dasharray:5,4}
.edge-label{font-size:10px;fill:#9aa3b8;font-family:"Segoe UI",sans-serif;text-anchor:middle}
.edge-label.dashed{fill:#e5b458}
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
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const $ = (sel, el) => (el || document).querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cssEsc = s => String(s).replace(/["\\\\]/g, '\\\\$&');
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN') : '—';
const badge = st => `<span class="badge b-${esc(st || 'unknown')}"></span>`;
const LANE_PALETTE = ['#5b9dff','#3fbf7f','#e5b458','#e0626b','#a56bf0','#38b6c9','#f08a5d','#7ac2ff','#c792ea','#8bd450'];
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

// 静态分层布局（坐标由 Python compute_static_layout 一次性算好，随数据下发）。
// 前端只画图 + 响应交互，加载后完全静止，不存在任何自动布局/物理模拟/持续动画。
function routeEdgePath(a, b) {
  const x1 = a.x + a.w / 2, y1 = a.y + a.h;
  const x2 = b.x + b.w / 2, y2 = b.y;
  if (Math.abs(x1 - x2) < 1 || y2 <= y1) return `M ${x1} ${y1} L ${x2} ${y2}`;
  const mid = (y1 + y2) / 2, r = 10, sign = x2 > x1 ? 1 : -1;
  return `M ${x1} ${y1} L ${x1} ${mid - r} Q ${x1} ${mid} ${x1 + sign * r} ${mid} `
       + `L ${x2 - sign * r} ${mid} Q ${x2} ${mid} ${x2} ${mid + r} L ${x2} ${y2}`;
}

function updateConnectedEdges(container, flow, nodeId, nx, ny) {
  const moved = { x: nx, y: ny, w: flow.layout.nodes[nodeId].w, h: flow.layout.nodes[nodeId].h };
  container.querySelectorAll(`path.flow-edge[data-from="${cssEsc(nodeId)}"]`).forEach(p => {
    const b = flow.layout.nodes[p.dataset.to];
    if (b) p.setAttribute('d', routeEdgePath(moved, b));
  });
  container.querySelectorAll(`path.flow-edge[data-to="${cssEsc(nodeId)}"]`).forEach(p => {
    const a = flow.layout.nodes[p.dataset.from];
    if (a) p.setAttribute('d', routeEdgePath(a, moved));
  });
}

function renderFlowGraph(container, flow) {
  const layout = flow.layout;
  if (!layout) { container.innerHTML = '<div class="chip">缺少静态布局数据</div>'; return null; }
  if (!flow._layoutSnapshot) flow._layoutSnapshot = JSON.parse(JSON.stringify(layout));
  const lanes = flow.lanes || [];
  const nodeMap = {};
  (flow.nodes || []).forEach(n => { nodeMap[n.id] = n; });

  const defs = `<marker id="arr-solid" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#5b9dff"/></marker>
    <marker id="arr-dashed" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#e5b458"/></marker>`;
  const laneSvg = (layout.lanes || []).map(l => `
    <rect class="lane-rect" x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="8" stroke="${laneColor(lanes, l.name)}" stroke-dasharray="6,5" stroke-width="1"></rect>
    <text class="lane-label" x="${l.x + 10}" y="${l.y + 14}" fill="${laneColor(lanes, l.name)}">${esc(l.name)}</text>`).join('');
  const edgeSvg = (layout.edges || []).map(e => {
    const dashed = !!e.condition;
    const label = e.condition || e.label;
    const a = layout.nodes[e.source], b = layout.nodes[e.target];
    const lx = a && b ? (a.x + a.w / 2 + b.x + b.w / 2) / 2 : 0;
    const ly = a && b ? (a.y + a.h + b.y) / 2 - 4 : 0;
    return `<path class="flow-edge${dashed ? ' dashed' : ''}" d="${e.path}" data-from="${esc(e.source)}" data-to="${esc(e.target)}" marker-end="url(#${dashed ? 'arr-dashed' : 'arr-solid'})"></path>`
      + (label ? `<text class="edge-label${dashed ? ' dashed' : ''}" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}">${esc(label)}</text>` : '');
  }).join('');
  const nodeSvg = Object.keys(layout.nodes || {}).map(id => {
    const pos = layout.nodes[id];
    const n = nodeMap[id];
    if (!n) return '';
    const label = (n.label || '').length > 24 ? n.label.slice(0, 23) + '…' : (n.label || '');
    const sub = (n.summary || '').length > 30 ? n.summary.slice(0, 29) + '…' : (n.summary || '');
    const evCount = (n.evidence || []).length;
    return `<g class="flow-node" data-id="${esc(id)}" transform="translate(${pos.x},${pos.y})">
      <rect class="node-mask" width="${pos.w}" height="${pos.h}" rx="6"></rect>
      <rect class="node-box" width="${pos.w}" height="${pos.h}" rx="6" style="stroke:${laneColor(lanes, n.lane)}"></rect>
      <text class="node-title" x="10" y="20">${esc(label)}</text>
      <text class="node-sub" x="10" y="38">${esc(sub)}</text>
      <text class="node-badge" x="${pos.w - 10}" y="${pos.h - 10}" text-anchor="end">📎${evCount}</text>
    </g>`;
  }).join('');

  container.innerHTML = `<svg id="flow-svg" viewBox="0 0 ${layout.width} ${layout.height}">
    <defs>${defs}</defs>
    <g id="flow-viewport">${laneSvg}${edgeSvg}${nodeSvg}</g>
  </svg>`;

  const svg = container.querySelector('#flow-svg');
  let view = { x: 0, y: 0, w: layout.width, h: layout.height };
  const applyView = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);

  svg.addEventListener('wheel', ev => {
    ev.preventDefault();
    const rect = svg.getBoundingClientRect();
    const scale = view.w / rect.width;
    const cx = view.x + (ev.clientX - rect.left) * scale;
    const cy = view.y + (ev.clientY - rect.top) * scale;
    const factor = ev.deltaY > 0 ? 1.1 : 0.9;
    view.x = cx - (cx - view.x) * factor;
    view.y = cy - (cy - view.y) * factor;
    view.w *= factor; view.h *= factor;
    applyView();
  }, { passive: false });

  let dragNode = null, dragMoved = false, panState = null;
  svg.addEventListener('mousedown', ev => {
    const nodeEl = ev.target.closest ? ev.target.closest('.flow-node') : null;
    const rect = svg.getBoundingClientRect();
    const scale = view.w / rect.width;
    if (nodeEl) {
      dragNode = { id: nodeEl.dataset.id, el: nodeEl, startX: ev.clientX, startY: ev.clientY, scale };
      dragMoved = false;
    } else {
      panState = { startX: ev.clientX, startY: ev.clientY, ox: view.x, oy: view.y, scale };
    }
  });
  const onMove = ev => {
    if (dragNode) {
      const dx = (ev.clientX - dragNode.startX) * dragNode.scale;
      const dy = (ev.clientY - dragNode.startY) * dragNode.scale;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) dragMoved = true;
      const base = flow.layout.nodes[dragNode.id];
      const nx = base.x + dx, ny = base.y + dy;
      dragNode.el.setAttribute('transform', `translate(${nx},${ny})`);
      updateConnectedEdges(container, flow, dragNode.id, nx, ny);
    } else if (panState) {
      const dx = (ev.clientX - panState.startX) * panState.scale;
      const dy = (ev.clientY - panState.startY) * panState.scale;
      view.x = panState.ox - dx; view.y = panState.oy - dy;
      applyView();
    }
  };
  const onUp = ev => {
    if (dragNode) {
      if (!dragMoved) {
        nodeDetail(flow, dragNode.id);
      } else {
        const base = flow.layout.nodes[dragNode.id];
        base.x += (ev.clientX - dragNode.startX) * dragNode.scale;
        base.y += (ev.clientY - dragNode.startY) * dragNode.scale;
      }
      dragNode = null;
    }
    panState = null;
  };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  applyView();
  return {
    fit: () => { view = { x: 0, y: 0, w: layout.width, h: layout.height }; applyView(); },
    reset: () => { flow.layout = JSON.parse(JSON.stringify(flow._layoutSnapshot)); renderFlowGraph(container, flow); },
  };
}

function subjectView(s) {
  let body = `<div class="section"><h2>${esc(s.name)} ${badge(s.status)}</h2>
    <div class="chips">${(s.aliases || []).map(a => `<span class="chip">${esc(a)}</span>`).join('')}</div></div>`;
  if (s.flow) {
    const lanes = s.flow.lanes || [];
    const legend = lanes.map(l => `<span><span class="sw" style="background:${laneColor(lanes, l)}"></span>${esc(l)}</span>`).join('');
    body += `<div class="section"><h2>业务流程（静态布局，点节点看证据 / 滚轮缩放 / 拖动空白处平移 / 拖动节点手动微调）</h2>
      <div id="graph-wrap">
        <div class="graph-toolbar">
          <button id="btn-fit" type="button">适应窗口</button>
          <button id="btn-reset" type="button">重置布局</button>
          <span class="hint">服务端一次性静态分层布局，加载后不会自动移动</span>
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
    const graph = renderFlowGraph($('#graph'), s.flow);
    if (graph) {
      $('#btn-fit').onclick = () => graph.fit();
      $('#btn-reset').onclick = () => {
        const g2 = graph.reset();
        $('#btn-fit').onclick = () => g2.fit();
      };
    }
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
  document.querySelectorAll('.flow-node.sel').forEach(g => g.classList.remove('sel'));
  const g = document.querySelector(`.flow-node[data-id="${cssEsc(nodeId)}"]`);
  if (g) g.classList.add('sel');
}
function closeDetail() {
  $('#detail').classList.remove('open');
  $('#detail').innerHTML = '';
  document.querySelectorAll('.flow-node.sel').forEach(g => g.classList.remove('sel'));
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
window.addEventListener('resize', () => { const btn = $('#btn-fit'); if (btn) btn.onclick && btn.onclick(); });
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
