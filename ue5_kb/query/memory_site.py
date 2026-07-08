"""Memory Wiki：从 memory.sqlite 程序化生成整库人类可读交互查看器。

设计原则（与 MD 渲染层一致）：
1. 唯一数据源是 memory/memory.sqlite，页面不允许出现数据库之外的信息。
2. 纯代码生成，AI 不参与渲染；删除后可随时重新生成，输出确定性。
3. 渐进式披露：业务地图 -> 主题泳道板 -> 节点侧栏 -> 证据片段 + vscode:// 深链。
4. 哈希/ID 等机器数据全部折叠进"技术详情"，默认不打扰人。
5. 单页面交互站（index.html + vendor/），仅 github-markdown-css 排版 + dockview-core 窗口
   引擎离线 vendor，不接 CDN、不需 npm/构建步骤，双击即开。详见仓库根目录 wiki_vendor/VENDOR.md。

图引擎选型（实战迭代结论）：初版用 vis-network 运行时物理引擎，实机反馈"一直在动来动去"不可接受。
参考 F:\\AiProject\\DecisionReview 项目多轮真实用户迭代：力导向物理图被反复否定，最终收敛到 Archify
的 architecture 渲染风格——服务端一次性计算好的静态 SVG（矩形节点 + 泳道分组框 + 直角走线），
加载后完全不动，只有用户主动拖拽才会移动。本模块用纯 Python 复刻这一布局算法（不引入
Node/Archify 依赖，见 compute_static_layout），前端仅负责渲染与交互，不再跑任何运行时布局/物理模拟。

窗口系统选型（2026-07-08）：早期版本用纯 CSS 的 .panel/.panel-header 静态组件模拟 Unreal Editor
停靠窗口的"边框+标题栏"观感，但那只是视觉皮肤，无法拖动/停靠/自由调整布局。参考同团队
F:\\ShanghaiP4\\neon\\Plugins\\EarthPrefabStudio（旨在用 web 复刻 Unreal Editor 的项目）选定的
依赖，改用其核心引擎 dockview-core：framework-agnostic、零依赖、纯 vanilla TS，UMD 构建可直接
<script> 引入（暴露 window['dockview-core'] 全局对象），不需要 React/构建工具链，业务流程图、
路线记忆、演进史、技术详情、节点详情等全部是真正独立、可拖拽停靠、可调整布局的窗口。见
compute_static_layout 之后的 renderFlowGraph/dockview 相关 JS 与 wiki_vendor/VENDOR.md。
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
VENDOR_ASSETS = ("github-markdown.css", "dockview-core.min.js", "dockview.css")


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
# 行间距(_LAYOUT_ROW_GAP)必须大于"折线拐点+文字标签"所需的最小空间，否则跨行的边
# 标签会紧贴甚至被上下节点框遮住（同一泳道内按依赖关系换行后，这种跨行边非常常见）。
_LAYOUT_COL_GAP, _LAYOUT_ROW_GAP, _LAYOUT_LANE_GAP, _LAYOUT_LANE_PAD, _LAYOUT_LABEL_H, _LAYOUT_MARGIN = 24, 40, 46, 14, 20, 24
_LAYOUT_MAX_COLS = 3  # 同一泳道内节点按依赖顺序换行排布，而不是强行挤成一整行


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
    for lane in lanes:
        by_lane[lane] = _apply_intra_lane_order(by_lane.get(lane, []), edges)
    return by_lane


def _apply_intra_lane_order(lane_ids: List[str], edges: List[Dict[str, Any]]) -> List[str]:
    """同一泳道内若存在直接依赖边 A->B，保证 A 在阅读顺序（先左后右、先上后下）上排在 B 前面。"""
    id_set = set(lane_ids)
    order = list(lane_ids)
    local_edges = [(e.get("source"), e.get("target")) for e in edges
                   if e.get("source") in id_set and e.get("target") in id_set and e.get("source") != e.get("target")]
    if not local_edges:
        return order
    for _ in range(len(order)):
        index = {node_id: i for i, node_id in enumerate(order)}
        violation = next(((s, t) for s, t in local_edges if index[s] > index[t]), None)
        if not violation:
            break
        s, t = violation
        order.remove(t)
        order.insert(index[s], t)
    return order


def _wrap_into_rows(ids: List[str], max_cols: int, edges: List[Dict[str, Any]]) -> List[List[str]]:
    """把同一泳道内的节点分行：优先按泳道内部的依赖关系分层——有直接/间接依赖
    链条的节点必须换行、纵向排布成先后顺序；同一层内彼此没有依赖关系的节点才视为
    并行分支，允许左右并排（超过 max_cols 时再按顺序换行）。不再是无视依赖关系、
    单纯按每 N 个强行切一行的做法（那样会把有先后顺序的节点误排成同一行，看起来
    像并行分支，误导阅读流程逻辑）。
    """
    if not ids:
        return []
    id_set = set(ids)
    local_edges = [(e.get("source"), e.get("target")) for e in edges
                   if e.get("source") in id_set and e.get("target") in id_set and e.get("source") != e.get("target")]

    # 最长路径分层：没有泳道内前驱的节点层号为 0，每条依赖边把目标节点的层号
    # 抬高到至少比源节点多 1；反复松弛直到收敛（节点数量级很小，迭代上限很安全）。
    rank = {node_id: 0 for node_id in ids}
    for _ in range(len(ids) + 1):
        changed = False
        for s, t in local_edges:
            if rank[s] + 1 > rank[t]:
                rank[t] = rank[s] + 1
                changed = True
        if not changed:
            break

    # 按层分组，层内保持传入的阅读顺序（barycenter + 依赖排序已确定的先后关系）。
    max_rank = max(rank.values()) if rank else 0
    layered: List[List[str]] = [[] for _ in range(max_rank + 1)]
    for node_id in ids:
        layered[rank[node_id]].append(node_id)

    cols = max(1, max_cols)
    rows: List[List[str]] = []
    for layer in layered:
        if not layer:
            continue
        for i in range(0, len(layer), cols):
            rows.append(layer[i:i + cols])
    return rows


_MIN_JOG = 14.0  # 折线拐点与两端端点之间至少留出的距离，保证圆角与箭头有地方画


def _elbow_vertical(x1: float, y1: float, x2: float, y2: float, r: float) -> Any:
    """竖直方向的直角折线：从 (x1,y1) 竖直出发，中途横向拐一次，竖直进入 (x2,y2)。"""
    if abs(x1 - x2) < 1:
        return f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}", (x1 + x2) / 2, (y1 + y2) / 2 - 4
    mid = (y1 + y2) / 2
    rr = min(r, max(2.0, abs(y2 - y1) / 2 - _MIN_JOG))
    sign = 1 if x2 > x1 else -1
    path = (
        f"M {x1:.1f} {y1:.1f} L {x1:.1f} {mid - rr:.1f} "
        f"Q {x1:.1f} {mid:.1f} {x1 + sign * rr:.1f} {mid:.1f} "
        f"L {x2 - sign * rr:.1f} {mid:.1f} "
        f"Q {x2:.1f} {mid:.1f} {x2:.1f} {mid + rr:.1f} "
        f"L {x2:.1f} {y2:.1f}"
    )
    return path, (x1 + x2) / 2, mid - 4


def _elbow_horizontal(x1: float, y1: float, x2: float, y2: float, r: float) -> Any:
    """水平方向的直角折线：从 (x1,y1) 横向出发，中途竖向拐一次，横向进入 (x2,y2)。"""
    if abs(y1 - y2) < 1:
        return f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}", (x1 + x2) / 2, (y1 + y2) / 2 - 4
    mid = (x1 + x2) / 2
    rr = min(r, max(2.0, abs(x2 - x1) / 2 - _MIN_JOG))
    sign = 1 if y2 > y1 else -1
    path = (
        f"M {x1:.1f} {y1:.1f} L {mid - rr:.1f} {y1:.1f} "
        f"Q {mid:.1f} {y1:.1f} {mid:.1f} {y1 + sign * rr:.1f} "
        f"L {mid:.1f} {y2 - sign * rr:.1f} "
        f"Q {mid:.1f} {y2:.1f} {mid + rr:.1f} {y2:.1f} "
        f"L {x2:.1f} {y2:.1f}"
    )
    return path, mid, (y1 + y2) / 2 - 4


def _route_edge(a: Dict[str, float], b: Dict[str, float], corner_r: float = 10.0) -> Dict[str, Any]:
    """始终返回直角折线路径（不出现斜线）。按目标相对源的位置分三种情形：

    - 目标严格在下方：从源底部出、从目标顶部入，竖直折线（原来唯一支持的情形）。
    - 目标严格在上方（逆向/回边）：从源顶部出、从目标底部入，同样走竖直折线。
    - 两者纵向有重叠（同排/侧向边）：从source/target彼此靠近的左右两侧出入，走水平折线。
    以前"目标在上方或同排"时会退化成一条斜线直连，这里统一改为始终走直角折线。
    """
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    a_cx, a_cy = ax + aw / 2, ay + ah / 2
    b_cx, b_cy = bx + bw / 2, by + bh / 2

    if by >= ay + ah:
        path, lx, ly = _elbow_vertical(a_cx, ay + ah, b_cx, by, corner_r)
    elif by + bh <= ay:
        path, lx, ly = _elbow_vertical(a_cx, ay, b_cx, by + bh, corner_r)
    else:
        if bx >= ax + aw:
            x1, y1, x2, y2 = ax + aw, a_cy, bx, b_cy
        elif bx + bw <= ax:
            x1, y1, x2, y2 = ax, a_cy, bx + bw, b_cy
        else:
            x1, y1, x2, y2 = a_cx, a_cy, b_cx, b_cy
        path, lx, ly = _elbow_horizontal(x1, y1, x2, y2, corner_r)
    return {"path": path, "lx": lx, "ly": ly}


def compute_static_layout(flow: Dict[str, Any]) -> Dict[str, Any]:
    """纯函数、确定性计算：给定 flow(lanes/nodes/edges) 返回节点坐标、泳道边框、直角走线路径。

    不依赖 DOM 测量、不依赖物理模拟，同样的输入永远得到同样的输出（可单测）。
    泳道内节点按依赖顺序换行排布（而非强行挤成一整行），泳道边框是其成员节点的
    紧致包围盒（而非预先固定的整行宽度），与前端拖拽时的动态包围盒更新语义一致。
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
    rows_by_lane = {lane: _wrap_into_rows(order.get(lane, []), _LAYOUT_MAX_COLS, edges) for lane in lanes}
    row_widths = {
        lane: max((len(row) * NODE_W + max(0, len(row) - 1) * _LAYOUT_COL_GAP for row in rows), default=NODE_W)
        for lane, rows in rows_by_lane.items()
    }
    max_width = max(row_widths.values()) if row_widths else NODE_W
    canvas_width = max_width + 2 * (_LAYOUT_MARGIN + _LAYOUT_LANE_PAD)

    positions: Dict[str, Dict[str, float]] = {}
    lane_rects: List[Dict[str, Any]] = []
    y = float(_LAYOUT_MARGIN)
    for lane in lanes:
        rows = rows_by_lane.get(lane, [])
        row_w = row_widths.get(lane, NODE_W)
        row_left = _LAYOUT_MARGIN + _LAYOUT_LANE_PAD + (max_width - row_w) / 2
        content_top = y + _LAYOUT_LABEL_H + _LAYOUT_LANE_PAD
        for row_idx, row in enumerate(rows):
            node_y = content_top + row_idx * (NODE_H + _LAYOUT_ROW_GAP)
            for col_idx, node_id in enumerate(row):
                positions[node_id] = {"x": row_left + col_idx * (NODE_W + _LAYOUT_COL_GAP), "y": node_y, "w": NODE_W, "h": NODE_H}
        row_count = max(1, len(rows))
        band_h = _LAYOUT_LABEL_H + row_count * NODE_H + max(0, row_count - 1) * _LAYOUT_ROW_GAP + 2 * _LAYOUT_LANE_PAD
        lane_rects.append({"name": lane, "x": float(_LAYOUT_MARGIN), "y": y, "w": canvas_width - 2 * _LAYOUT_MARGIN, "h": band_h})
        y += band_h + _LAYOUT_LANE_GAP
    canvas_height = y - _LAYOUT_LANE_GAP + _LAYOUT_MARGIN

    edge_paths: List[Dict[str, Any]] = []
    for edge in edges:
        a = positions.get(edge.get("source"))
        b = positions.get(edge.get("target"))
        if not a or not b:
            continue
        geom = _route_edge(a, b)
        edge_paths.append({
            "source": edge.get("source"),
            "target": edge.get("target"),
            "path": geom["path"],
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
window_engine: dockview-core (vendor/dockview-core.min.js + vendor/dockview.css, MIT, 离线 vendor,
  framework-agnostic UMD，对齐 Unreal Editor 停靠窗口：所有窗口可自由拖拽/停靠/调整布局)
-->
<link rel="stylesheet" href="vendor/github-markdown.css">
<link rel="stylesheet" href="vendor/dockview.css">
<script src="vendor/dockview-core.min.js"></script>
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
nav{width:250px;min-width:160px;max-width:480px;background:var(--panel);border-right:1px solid var(--line);overflow-y:auto;padding:10px;flex:none}
nav h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:12px 8px 4px}
nav a{display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;color:var(--text);text-decoration:none;font-size:13px}
nav a:hover,nav a.active{background:var(--card)}
.badge{width:8px;height:8px;border-radius:50%;flex:none}
.b-active,.b-fresh,.b-published{background:var(--ok)}
.b-changed,.b-unknown,.b-candidate{background:var(--warn)}
.b-broken,.b-failed{background:var(--bad)}
.resizer{flex:none;background:var(--line);position:relative;z-index:5}
.resizer:hover,.resizer.active{background:var(--accent)}
.resizer-x{width:5px;cursor:col-resize}
.resizer-y{height:5px;cursor:row-resize}
/* dockview 容器：真正的可拖拽/停靠/自由调整布局的窗口系统（dockview-core，对齐 Unreal
   Editor 停靠窗口）。不再用自写 .resizer 手动拖拽高/宽——dockview 自带拖拽分割条。 */
#dock-container{flex:1;min-width:0;min-height:0;position:relative}
.dockview-theme-abyss{--dv-background-color:#12141a;--dv-group-view-background-color:#171a22;
  --dv-tabs-and-actions-container-background-color:#1b1e27;--dv-activegroup-visiblepanel-tab-background-color:#171a22;
  --dv-activegroup-hiddenpanel-tab-background-color:#1b1e27;--dv-inactivegroup-visiblepanel-tab-background-color:#1b1e27;
  --dv-inactivegroup-hiddenpanel-tab-background-color:#1b1e27;--dv-tab-divider-color:#3a4055;
  --dv-separator-border:#3a4055;--dv-paneview-active-outline-color:#5b9dff;
  --dv-activegroup-visiblepanel-tab-color:#e6e9f2;--dv-activegroup-hiddenpanel-tab-color:#9aa3b8;
  --dv-inactivegroup-visiblepanel-tab-color:#9aa3b8;--dv-inactivegroup-hiddenpanel-tab-color:#7d8399;
  --dv-drag-over-background-color:rgba(91,157,255,.12);--dv-drag-over-border-color:#5b9dff;
  font-family:"Segoe UI",system-ui,sans-serif;font-size:13px}
.dock-html{padding:12px;height:100%;overflow:auto;box-sizing:border-box}
.dock-html.markdown-body{background:transparent}
/* 滚动条统一样式（Firefox + WebKit）：nav 是应用外壳侧栏，.dock-html 是面板内容区，
   pre.snippet 是代码片段自己的横向滚动条。dockview 自身的分组/标签区域滚动条用其
   自带主题样式，不在这里覆盖。 */
nav,.dock-html,pre.snippet{scrollbar-width:thin;scrollbar-color:var(--line) var(--panel)}
nav::-webkit-scrollbar,.dock-html::-webkit-scrollbar,pre.snippet::-webkit-scrollbar{width:9px;height:9px}
nav::-webkit-scrollbar-track,.dock-html::-webkit-scrollbar-track,pre.snippet::-webkit-scrollbar-track{background:var(--panel)}
nav::-webkit-scrollbar-thumb,.dock-html::-webkit-scrollbar-thumb,pre.snippet::-webkit-scrollbar-thumb{background:var(--line);border-radius:5px;border:2px solid var(--panel)}
nav::-webkit-scrollbar-thumb:hover,.dock-html::-webkit-scrollbar-thumb:hover,pre.snippet::-webkit-scrollbar-thumb:hover{background:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;cursor:pointer}
.card:hover{border-color:var(--accent)}
.card h3{font-size:14px;margin-bottom:4px}
.card .sub{color:var(--dim);font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.chip{background:var(--chip);border-radius:10px;padding:1px 8px;font-size:11px;color:var(--dim)}
/* 业务流程图面板内部布局：工具栏 + 图满铺区域 + 图例，高度跟随 dockview 面板自适应。 */
.dock-graph{height:100%;display:flex;flex-direction:column}
.graph-toolbar{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line);background:var(--panel);flex:none}
.graph-toolbar button{background:var(--chip);color:var(--text);border:1px solid var(--line);border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer}
.graph-toolbar button:hover{border-color:var(--accent)}
.graph-toolbar .hint{margin-left:auto;color:var(--dim);font-size:11px}
.graph-mount{flex:1;min-height:0;cursor:grab;user-select:none}
.graph-mount svg text{user-select:none}
.graph-mount:active{cursor:grabbing}
.graph-mount svg{display:block;width:100%;height:100%}
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
.edge-label-bg{fill:#10141f;fill-opacity:.92;pointer-events:none}
.edge-label{font-size:10px;fill:#9aa3b8;font-family:"Segoe UI",sans-serif;text-anchor:middle}
.edge-label.dashed{fill:#e5b458}
#legend{display:flex;flex-wrap:wrap;gap:10px;padding:8px 10px;font-size:11px;color:var(--dim);border-top:1px solid var(--line);flex:none}
#legend .sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle}
/* markdown-body 默认跟随系统浅/深色偏好；页面自身固定深色，此处强制复用官方 dark 变量不跟系统切换 */
.markdown-body{
  color-scheme:dark;background:transparent;font-size:13px;
  --fgColor-accent:#4493f8;--bgColor-default:#161b22;--bgColor-muted:#151b23;--bgColor-neutral-muted:#656c7633;
  --borderColor-accent-emphasis:#1f6feb;--borderColor-default:#3d444d;--borderColor-muted:#3d444db3;
  --fgColor-default:#e6e9f2;--fgColor-muted:#9198a1;--fgColor-danger:#f85149;--fgColor-success:#3fb950;
}
.markdown-body table{width:100%;display:table}
.evidence-card{margin-bottom:14px}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{color:var(--dim);background:var(--panel)}
pre.snippet{background:#0d0f14;border:1px solid var(--line);border-radius:6px;padding:8px;font:12px/1.5 Consolas,monospace;overflow-x:auto;margin:0;white-space:pre}
pre.snippet.wrap{white-space:pre-wrap;word-break:break-all;overflow-x:hidden}
pre.snippet .focus{background:#2b3a55;display:block}
pre.snippet .ln{color:#525b73;user-select:none;display:inline-block;width:44px}
pre.snippet .tok-keyword{color:#c586c0}
pre.snippet .tok-type{color:#4ec9b0}
pre.snippet .tok-string{color:#ce9178}
pre.snippet .tok-number{color:#b5cea8}
pre.snippet .tok-comment{color:#6a9955;font-style:italic}
pre.snippet .tok-preproc{color:#e5b458}
pre.snippet .tok-macro{color:#dcdcaa}
.snippet-wrap{margin:6px 0}
.snippet-toolbar{display:flex;justify-content:flex-end;margin-bottom:4px}
.wrap-toggle{font-size:11px;padding:2px 8px}
.btn{display:inline-block;background:var(--accent);color:#fff;border-radius:5px;padding:3px 10px;font-size:12px;text-decoration:none;margin:2px 4px 2px 0}
.btn.ghost{background:var(--chip);color:var(--dim)}
details.tech{margin-top:10px;color:var(--dim);font-size:12px}
details.tech summary{cursor:pointer}
details.tech code{word-break:break-all}
.dock-html h2{font-size:15px;margin-bottom:6px}
.dock-html h4{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin:14px 0 6px}
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
  <div class="resizer resizer-x" id="resizer-nav" title="拖动调整侧栏宽度"></div>
  <div id="dock-container" class="dockview-theme-abyss"></div>
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

// 站内导航统一走 navigateTo()，用 history.pushState 而不是 location.hash / <a href> 默认跳转：
// 某些外部预览容器（如浏览器扩展、嵌入式 webview）会把 hash 变化当成一次"真正的导航"
// 处理并整页刷新/开新页，pushState 是唯一在所有宿主环境下都不会触发导航语义的方式。
function navigateTo(hash) {
  if (location.hash.slice(1) !== hash) {
    history.pushState(null, '', '#' + hash);
  }
  route();
}
function navRender() {
  const subj = DATA.subjects.map(s =>
    `<a href="#subject/${esc(s.id)}" data-route="subject/${esc(s.id)}" onclick="event.preventDefault();navigateTo('subject/${esc(s.id)}')">${badge(s.status)}${esc(s.name)}</a>`).join('');
  const pat = DATA.patterns.map(p =>
    `<a href="#pattern/${esc(p.id)}" data-route="pattern/${esc(p.id)}" onclick="event.preventDefault();navigateTo('pattern/${esc(p.id)}')">${badge(p.status)}${esc(p.name)}</a>`).join('');
  $('#nav').innerHTML = `
    <a href="#map" data-route="map" onclick="event.preventDefault();navigateTo('map')">🗺️ 业务地图</a>
    <h2>业务主题 (${DATA.subjects.length})</h2>${subj}
    <h2>业务模式 (${DATA.patterns.length})</h2>${pat}
    <h2>其他</h2>
    <a href="#hints" data-route="hints" onclick="event.preventDefault();navigateTo('hints')">⚠️ 避坑记录 (${DATA.negative_hints.length})</a>`;
}

// 轻量级 C++ / HLSL 语法高亮：不引入外部高亮库（保持单文件 wiki 的自包含设计），
// 用一个简单的逐行 token 正则识别注释/字符串/预处理指令/数字/关键字/UE 命名类型，
// 足够覆盖引擎源码片段的可读性需求。按行独立处理（不跨行），换行由外层按行渲染，
// 因此正则里不需要处理多行的块注释延续（极少见，且不影响正确性/安全性，只是
// 换行位置上的注释着色不会跨行延续）。
const CPP_KEYWORDS = new Set(['alignas','alignof','and','asm','auto','bitand','bitor','bool','break','case','catch','char','char8_t','char16_t','char32_t','class','compl','concept','const','consteval','constexpr','constinit','const_cast','continue','co_await','co_return','co_yield','decltype','default','delete','do','double','dynamic_cast','else','enum','explicit','export','extern','false','final','float','for','friend','goto','if','inline','int','long','mutable','namespace','new','noexcept','nullptr','operator','override','private','protected','public','register','reinterpret_cast','requires','return','short','signed','sizeof','static','static_assert','static_cast','struct','switch','template','this','thread_local','throw','true','try','typedef','typeid','typename','union','unsigned','using','virtual','void','volatile','wchar_t','while',
  'technique','technique10','technique11','pass','cbuffer','tbuffer','uniform','groupshared','numthreads','row_major','column_major','packoffset','discard','in','out','inout',
  'float','float1','float2','float3','float4','float1x1','float2x2','float3x3','float4x4','half','half2','half3','half4','double2','double3','double4',
  'int1','int2','int3','int4','uint','uint1','uint2','uint3','uint4','bool1','bool2','bool3','bool4','matrix','vector',
  'Texture1D','Texture2D','Texture3D','TextureCube','Texture1DArray','Texture2DArray','TextureCubeArray','Texture2DMS',
  'RWTexture1D','RWTexture2D','RWTexture3D','RWStructuredBuffer','StructuredBuffer','AppendStructuredBuffer','ConsumeStructuredBuffer',
  'ByteAddressBuffer','RWByteAddressBuffer','SamplerState','SamplerComparisonState']);
const UE_MACROS = new Set(['UPROPERTY','UFUNCTION','UCLASS','USTRUCT','UENUM','UINTERFACE','UMETA','GENERATED_BODY','GENERATED_UCLASS_BODY','GENERATED_USTRUCT_BODY','GENERATED_IINTERFACE_BODY','TEXT','LOCTEXT','NSLOCTEXT','check','checkf','checkSlow','ensure','ensureMsgf','ensureAlways','verify','verifyf','UE_LOG',
  'SV_Target','SV_Position','SV_DispatchThreadID','SV_GroupID','SV_GroupThreadID','SV_GroupIndex','SV_VertexID','SV_InstanceID','SV_IsFrontFace','SV_Depth']);
const UE_TYPE_RE = /^[FUAEIT][A-Z]\\w*$/;
const CODE_TOKEN_RE = /(\\/\\/.*)|("[^"]*"?)|('[^']*'?)|(#\\w+)|(\\d[\\w.]*)|([A-Za-z_]\\w*)/g;
function highlightLine(line) {
  let out = '';
  let last = 0;
  let m;
  CODE_TOKEN_RE.lastIndex = 0;
  while ((m = CODE_TOKEN_RE.exec(line))) {
    if (m.index > last) out += esc(line.slice(last, m.index));
    if (m[1] !== undefined) out += `<span class="tok-comment">${esc(m[1])}</span>`;
    else if (m[2] !== undefined) out += `<span class="tok-string">${esc(m[2])}</span>`;
    else if (m[3] !== undefined) out += `<span class="tok-string">${esc(m[3])}</span>`;
    else if (m[4] !== undefined) out += `<span class="tok-preproc">${esc(m[4])}</span>`;
    else if (m[5] !== undefined) out += `<span class="tok-number">${esc(m[5])}</span>`;
    else if (m[6] !== undefined) {
      const word = m[6];
      let cls = null;
      if (CPP_KEYWORDS.has(word)) cls = 'tok-keyword';
      else if (UE_MACROS.has(word)) cls = 'tok-macro';
      else if (UE_TYPE_RE.test(word)) cls = 'tok-type';
      out += cls ? `<span class="${cls}">${esc(word)}</span>` : esc(word);
    }
    last = CODE_TOKEN_RE.lastIndex;
  }
  if (last < line.length) out += esc(line.slice(last));
  return out;
}

let _snippetSeq = 0;
function snippetHtml(sn) {
  if (!sn) return '<div class="chip">源码片段不可用（生成时未能读取源文件）</div>';
  const body = sn.lines.map((line, i) => {
    const no = sn.start + i;
    const text = `<span class="ln">${no}</span>${highlightLine(line)}`;
    return no === sn.focus ? `<span class="focus">${text}</span>` : text;
  }).join('\\n');
  const id = 'snip-' + (++_snippetSeq);
  return `<div class="snippet-wrap">
    <div class="snippet-toolbar"><button class="btn ghost wrap-toggle" type="button" onclick="toggleWrap('${id}', this)">⤸ 自动换行</button></div>
    <pre class="snippet" id="${id}">${body}</pre>
  </div>`;
}
function toggleWrap(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  const wrapped = el.classList.toggle('wrap');
  btn.textContent = wrapped ? '⤸ 取消换行' : '⤸ 自动换行';
}

function evidenceHtml(ev) {
  const open = ev.vscode ? `<a class="btn" href="${esc(ev.vscode)}">在 VS Code 打开</a>` : '';
  return `<div class="evidence-card">
    <div><code>${esc(ev.ref || (ev.file + ':' + ev.line))}</code> ${open}</div>
    ${snippetHtml(ev.snippet)}</div>`;
}

// 静态分层布局（坐标由 Python compute_static_layout 一次性算好，随数据下发）。
// 前端只画图 + 响应交互，加载后完全静止，不存在任何自动布局/物理模拟/持续动画。
// 下面这套折线路由逻辑必须与 Python 端 _route_edge/_elbow_vertical/_elbow_horizontal
// 保持一致：任何情形都要走直角折线，不能退化成斜线直连。
function elbowVertical(x1, y1, x2, y2, r) {
  if (Math.abs(x1 - x2) < 1) return { path: `M ${x1} ${y1} L ${x2} ${y2}`, lx: (x1 + x2) / 2, ly: (y1 + y2) / 2 - 4 };
  const mid = (y1 + y2) / 2;
  const rr = Math.min(r, Math.max(2, Math.abs(y2 - y1) / 2 - 14));
  const sign = x2 > x1 ? 1 : -1;
  const path = `M ${x1} ${y1} L ${x1} ${mid - rr} Q ${x1} ${mid} ${x1 + sign * rr} ${mid} `
    + `L ${x2 - sign * rr} ${mid} Q ${x2} ${mid} ${x2} ${mid + rr} L ${x2} ${y2}`;
  return { path, lx: (x1 + x2) / 2, ly: mid - 4 };
}
function elbowHorizontal(x1, y1, x2, y2, r) {
  if (Math.abs(y1 - y2) < 1) return { path: `M ${x1} ${y1} L ${x2} ${y2}`, lx: (x1 + x2) / 2, ly: (y1 + y2) / 2 - 4 };
  const mid = (x1 + x2) / 2;
  const rr = Math.min(r, Math.max(2, Math.abs(x2 - x1) / 2 - 14));
  const sign = y2 > y1 ? 1 : -1;
  const path = `M ${x1} ${y1} L ${mid - rr} ${y1} Q ${mid} ${y1} ${mid} ${y1 + sign * rr} `
    + `L ${mid} ${y2 - sign * rr} Q ${mid} ${y2} ${mid + rr} ${y2} L ${x2} ${y2}`;
  return { path, lx: mid, ly: (y1 + y2) / 2 - 4 };
}
function routeEdgePath(a, b, r) {
  r = r || 10;
  const aCx = a.x + a.w / 2, aCy = a.y + a.h / 2;
  const bCx = b.x + b.w / 2, bCy = b.y + b.h / 2;
  if (b.y >= a.y + a.h) {
    return elbowVertical(aCx, a.y + a.h, bCx, b.y, r);
  }
  if (b.y + b.h <= a.y) {
    return elbowVertical(aCx, a.y, bCx, b.y + b.h, r);
  }
  let x1, y1, x2, y2;
  if (b.x >= a.x + a.w) { x1 = a.x + a.w; y1 = aCy; x2 = b.x; y2 = bCy; }
  else if (b.x + b.w <= a.x) { x1 = a.x; y1 = aCy; x2 = b.x + b.w; y2 = bCy; }
  else { x1 = aCx; y1 = aCy; x2 = bCx; y2 = bCy; }
  return elbowHorizontal(x1, y1, x2, y2, r);
}

let _graphTeardown = null;

function renderFlowGraph(container, flow) {
  if (_graphTeardown) { _graphTeardown(); _graphTeardown = null; }
  const layout = flow.layout;
  if (!layout) { container.innerHTML = '<div class="chip">缺少静态布局数据</div>'; return null; }
  if (!flow._layoutSnapshot) flow._layoutSnapshot = JSON.parse(JSON.stringify(layout));
  const lanes = flow.lanes || [];
  const nodeMap = {};
  (flow.nodes || []).forEach(n => { nodeMap[n.id] = n; });

  const defs = `<marker id="arr-solid" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#5b9dff"/></marker>
    <marker id="arr-dashed" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#e5b458"/></marker>`;
  const laneSvg = (layout.lanes || []).map(l => `
    <rect class="lane-rect" data-lane="${esc(l.name)}" x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="8" stroke="${laneColor(lanes, l.name)}" stroke-dasharray="6,5" stroke-width="1"></rect>
    <text class="lane-label" data-lane="${esc(l.name)}" x="${l.x + 10}" y="${l.y + 14}" fill="${laneColor(lanes, l.name)}">${esc(l.name)}</text>`).join('');
  const edgeSvg = (layout.edges || []).map(e => {
    const dashed = !!e.condition;
    const label = e.condition || e.label;
    const a = layout.nodes[e.source], b = layout.nodes[e.target];
    const geom = a && b ? routeEdgePath(a, b) : { path: e.path, lx: 0, ly: 0 };
    // 标签背景矩形（edge-label-bg）先于文字放置：折线拐点常常离节点框很近，
    // 没有底色的话文字会被节点框"吃掉"看不清；实际尺寸在渲染后用 getBBox 量出来填。
    return `<g class="flow-edge-group" data-from="${esc(e.source)}" data-to="${esc(e.target)}">`
      + `<path class="flow-edge${dashed ? ' dashed' : ''}" d="${geom.path}" marker-end="url(#${dashed ? 'arr-dashed' : 'arr-solid'})"></path>`
      + (label
        ? `<rect class="edge-label-bg" x="0" y="0" width="0" height="0" rx="3"></rect>`
          + `<text class="edge-label${dashed ? ' dashed' : ''}" x="${geom.lx.toFixed(1)}" y="${geom.ly.toFixed(1)}">${esc(label)}</text>`
        : '')
      + `</g>`;
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
  // 用实际渲染出来的文字包围盒（getBBox，字符串阶段没法精确算宽度，中英文宽度也不一样）
  // 回填标签背景矩形的尺寸，保证背景刚好贴合文字，不管标签离节点框多近都能看清。
  const refreshLabelBg = textEl => {
    const bg = textEl.previousElementSibling;
    if (!bg || !bg.classList.contains('edge-label-bg')) return;
    const bbox = textEl.getBBox();
    bg.setAttribute('x', (bbox.x - 4).toFixed(1));
    bg.setAttribute('y', (bbox.y - 2).toFixed(1));
    bg.setAttribute('width', (bbox.width + 8).toFixed(1));
    bg.setAttribute('height', (bbox.height + 4).toFixed(1));
  };
  container.querySelectorAll('text.edge-label').forEach(refreshLabelBg);
  let view = { x: 0, y: 0, w: layout.width, h: layout.height };
  const applyView = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
  // SVG 没有设置 preserveAspectRatio，默认是 "xMidYMid meet"：当容器宽高比和
  // viewBox 宽高比不一致时（这里几乎总是如此——业务流程图通常又窄又长，容器却是
  // 宽而矮），浏览器会按"更紧的那根轴"统一缩放并居中，另一根轴上会有留白
  // （letterbox）。之前直接用 `view.w / rect.width` 当缩放系数，在宽度不是约束轴
  // 的情况下完全算错（经实测偏差可达约 10 倍），导致拖拽/滚轮缩放的位移量和鼠标
  // 实际移动的距离对不上，表现为"不跟手、很沉重"。这里统一算出真实的渲染缩放
  // 比例（px/单位）和留白偏移量，所有坐标换算都必须走这个函数，不能再直接拿
  // rect.width/rect.height 当缩放系数用。
  const svgMetrics = () => {
    const rect = svg.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const pxPerUnit = Math.min(rect.width / view.w, rect.height / view.h);
    const renderedW = view.w * pxPerUnit, renderedH = view.h * pxPerUnit;
    return {
      rect,
      pxPerUnit,
      unitsPerPx: 1 / pxPerUnit,
      offsetX: rect.left + (rect.width - renderedW) / 2,
      offsetY: rect.top + (rect.height - renderedH) / 2,
    };
  };

  // 泳道边框跟随其成员节点当前位置动态收缩/扩张（初始值已由 Python 端算好，
  // 拖拽节点后这里重新计算包围盒，而不是让边框停留在旧的静态位置）。
  const LANE_PAD = 14, LABEL_H = 20;
  // 节点/泳道之间必须保留的最小间距：既是"挤开"求解的阈值，也是 edge/label 的最小可绘制留白。
  const NODE_PAD = 20, LANE_MIN_GAP = 18;
  const laneOrder = flow.lanes || [];
  const laneMembers = {};
  const nodeLaneOf = {};
  (flow.nodes || []).forEach(n => {
    (laneMembers[n.lane] || (laneMembers[n.lane] = [])).push(n.id);
    nodeLaneOf[n.id] = n.lane;
  });
  // 一次拖拽只做有限次"一次性推挤求解"，不是持续物理模拟，不会抖动；泳道级联推挤
  // 最坏情况下需要沿泳道链条传播 laneOrder.length 步，节点级推挤同理，按数量放宽轮次上限。
  const MAX_RESOLVE_PASSES = Math.max(16, laneOrder.length * 2, (flow.nodes || []).length);

  // 建立"节点 id -> 与它相连的边分组元素"索引：拖拽推挤可能牵动很多节点，需要
  // 批量刷新这些节点各自关联的边，而不仅仅是被直接拖拽的那一个节点。
  const edgeGroupsByNode = {};
  container.querySelectorAll('.flow-edge-group').forEach(g => {
    const from = g.dataset.from, to = g.dataset.to;
    (edgeGroupsByNode[from] || (edgeGroupsByNode[from] = [])).push(g);
    (edgeGroupsByNode[to] || (edgeGroupsByNode[to] = [])).push(g);
  });

  const laneBBox = laneName => {
    const ids = laneMembers[laneName];
    if (!ids || !ids.length) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const id of ids) {
      const p = flow.layout.nodes[id];
      if (!p) continue;
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + p.w); maxY = Math.max(maxY, p.y + p.h);
    }
    if (minX === Infinity) return null;
    return { x: minX - LANE_PAD, y: minY - LABEL_H - LANE_PAD, w: (maxX - minX) + LANE_PAD * 2, h: (maxY - minY) + LABEL_H + LANE_PAD * 2 };
  };
  const updateLaneBounds = laneName => {
    const bbox = laneBBox(laneName);
    if (!bbox) return;
    const rectEl = container.querySelector(`.lane-rect[data-lane="${cssEsc(laneName)}"]`);
    const labelEl = container.querySelector(`.lane-label[data-lane="${cssEsc(laneName)}"]`);
    if (rectEl) { rectEl.setAttribute('x', bbox.x); rectEl.setAttribute('y', bbox.y); rectEl.setAttribute('width', bbox.w); rectEl.setAttribute('height', bbox.h); }
    if (labelEl) { labelEl.setAttribute('x', bbox.x + 10); labelEl.setAttribute('y', bbox.y + 14); }
  };
  // 两个矩形若重叠（含 pad 间距），返回需要施加在 other 身上的最小推开位移，沿
  // 重叠量较小的那根轴推开（标准 AABB 最小平移向量思路）；不重叠则返回 null。
  const resolveOverlap = (mover, other, pad) => {
    const pcx = mover.x + mover.w / 2, pcy = mover.y + mover.h / 2;
    const qcx = other.x + other.w / 2, qcy = other.y + other.h / 2;
    const overlapX = (mover.w + other.w) / 2 + pad - Math.abs(pcx - qcx);
    const overlapY = (mover.h + other.h) / 2 + pad - Math.abs(pcy - qcy);
    if (overlapX <= 0 || overlapY <= 0) return null;
    return overlapX < overlapY
      ? { dx: qcx >= pcx ? overlapX : -overlapX, dy: 0 }
      : { dx: 0, dy: qcy >= pcy ? overlapY : -overlapY };
  };
  // 正在被拖拽的这一批节点（单个节点拖拽时只有它自己；整条泳道拖拽时是它全部
  // 成员）永远自由移动、严格跟手，不被推挤/钳制；与它们冲突的其他节点/泳道会被
  // "挤开"——泳道扩张侵犯到相邻泳道时，直接把相邻泳道的所有成员整体移开，而不是
  // 限制扩张的一方，这正是用户要的"泳道内节点撑大 bounds 时，其它泳道跟着让开"。
  // 这是有限次的一次性位置求解（每次 mousemove 独立计算，不依赖上一帧速度/弹簧），
  // 不是持续物理模拟，因此不会有 vis-network 那种抖动、一直在动的问题。
  const resolveCollisions = freeIds => {
    const changed = new Set(freeIds);
    const shiftLane = (laneName, dy) => {
      (laneMembers[laneName] || []).forEach(id => {
        const p = flow.layout.nodes[id];
        flow.layout.nodes[id] = { x: p.x, y: p.y + dy, w: p.w, h: p.h };
        changed.add(id);
      });
    };
    for (let pass = 0; pass < MAX_RESOLVE_PASSES; pass++) {
      let touched = false;
      const ids = Object.keys(flow.layout.nodes);
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const idA = ids[i], idB = ids[j];
          const aFree = freeIds.has(idA), bFree = freeIds.has(idB);
          if (aFree && bFree) continue; // 同一批被拖拽的节点（比如同一条泳道内部）不互相推挤
          // 两者都不是本次拖拽主体时，固定推开后者，保证结果确定、不会来回震荡；
          // 只要有一方是本次拖拽主体，就以它为参照物推开另一方（主体永不被推）。
          const mover = aFree ? idA : (bFree ? idB : idA);
          const other = mover === idA ? idB : idA;
          const push = resolveOverlap(flow.layout.nodes[mover], flow.layout.nodes[other], NODE_PAD);
          if (push) {
            const o = flow.layout.nodes[other];
            flow.layout.nodes[other] = { x: o.x + push.dx, y: o.y + push.dy, w: o.w, h: o.h };
            changed.add(other);
            touched = true;
          }
        }
      }
      // 泳道级联推挤：相邻两条泳道的动态包围盒若挨得太近，把其中一条整体移开消除
      // 重叠。谁是"本次拖拽主体所在的泳道"就固定不动，推开对面那一条；如果两条都
      // 不是拖拽主体（级联传递到更远的泳道），默认推下面那条，规则确定、不会震荡。
      for (let li = 0; li < laneOrder.length - 1; li++) {
        const laneA = laneOrder[li], laneB = laneOrder[li + 1];
        const bboxA = laneBBox(laneA), bboxB = laneBBox(laneB);
        if (!bboxA || !bboxB) continue;
        const gap = bboxB.y - (bboxA.y + bboxA.h);
        if (gap >= LANE_MIN_GAP) continue;
        const need = LANE_MIN_GAP - gap;
        const aFree = (laneMembers[laneA] || []).some(id => freeIds.has(id));
        const bFree = (laneMembers[laneB] || []).some(id => freeIds.has(id));
        if (bFree && !aFree) {
          shiftLane(laneA, -need);
        } else {
          shiftLane(laneB, need);
        }
        touched = true;
      }
      if (!touched) break;
    }
    return changed;
  };
  // 把 changed 集合里所有节点的最新位置写回 DOM：节点本身的 transform、它关联的
  // 每一条边的折线路径与标签背景、以及它所在泳道的动态边框，一次性批量刷新。
  const applyChanges = (changed, draggedEl, draggedId) => {
    const dirtyEdgeGroups = new Set();
    const dirtyLanes = new Set();
    changed.forEach(id => {
      const p = flow.layout.nodes[id];
      const nodeEl = (id === draggedId && draggedEl) ? draggedEl : container.querySelector(`.flow-node[data-id="${cssEsc(id)}"]`);
      if (nodeEl && p) nodeEl.setAttribute('transform', `translate(${p.x},${p.y})`);
      (edgeGroupsByNode[id] || []).forEach(g => dirtyEdgeGroups.add(g));
      if (nodeLaneOf[id]) dirtyLanes.add(nodeLaneOf[id]);
    });
    dirtyEdgeGroups.forEach(g => {
      const a = flow.layout.nodes[g.dataset.from], b = flow.layout.nodes[g.dataset.to];
      if (!a || !b) return;
      const geom = routeEdgePath(a, b);
      const path = g.querySelector('path.flow-edge');
      const label = g.querySelector('text.edge-label');
      if (path) path.setAttribute('d', geom.path);
      if (label) {
        label.setAttribute('x', geom.lx.toFixed(1));
        label.setAttribute('y', geom.ly.toFixed(1));
        refreshLabelBg(label);
      }
    });
    dirtyLanes.forEach(updateLaneBounds);
  };


  const onWheel = ev => {
    ev.preventDefault();
    const m = svgMetrics();
    if (!m) return;
    const cx = view.x + (ev.clientX - m.offsetX) * m.unitsPerPx;
    const cy = view.y + (ev.clientY - m.offsetY) * m.unitsPerPx;
    const factor = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
    view.x = cx - (cx - view.x) * factor;
    view.y = cy - (cy - view.y) * factor;
    view.w *= factor; view.h *= factor;
    applyView();
  };
  svg.addEventListener('wheel', onWheel, { passive: false });

  // 拖拽状态：直接同步更新 DOM（不经 requestAnimationFrame）：实测 rAF 合帧在部分
  // 环境下（后台/非焦点标签页、自动化测试）可能被浏览器节流甚至不触发，导致拖拽
  // 视觉更新滞后或丢帧；直接更新在节点数量级（几十个）下足够快，且响应最即时。
  let dragNode = null, dragLane = null, dragMoved = false, panState = null;
  const onMouseDown = ev => {
    if (ev.button !== 0) return;
    // 必须阻止默认行为，否则浏览器会在拖拽画布/节点时触发原生文字选中/框选（实测复现）。
    ev.preventDefault();
    const nodeEl = ev.target.closest ? ev.target.closest('.flow-node') : null;
    const laneEl = !nodeEl && ev.target.closest ? ev.target.closest('.lane-rect,.lane-label') : null;
    const m = svgMetrics();
    if (!m) return; // 容器尚未布局完成时尺寸可能为 0，避免缩放系数变 Infinity 污染坐标
    const scale = m.unitsPerPx;
    document.body.style.userSelect = 'none';
    if (nodeEl) {
      const id = nodeEl.dataset.id;
      dragNode = { id, el: nodeEl, startX: ev.clientX, startY: ev.clientY, scale, base: { ...flow.layout.nodes[id] } };
      dragMoved = false;
    } else if (laneEl) {
      // 拖动泳道边框/标题本身：整条泳道的所有成员节点整体平移，严格跟手，同样会
      // 把扩张路径上冲突的其他节点/相邻泳道挤开。
      const laneName = laneEl.dataset.lane;
      const ids = laneMembers[laneName] || [];
      const bases = {};
      ids.forEach(id => { bases[id] = { ...flow.layout.nodes[id] }; });
      dragLane = { name: laneName, ids, startX: ev.clientX, startY: ev.clientY, scale, bases };
      dragMoved = false;
    } else {
      panState = { startX: ev.clientX, startY: ev.clientY, ox: view.x, oy: view.y, scale };
    }
  };
  const onMouseMove = ev => {
    if (dragNode) {
      const dx0 = ev.clientX - dragNode.startX, dy0 = ev.clientY - dragNode.startY;
      if (!dragMoved && (Math.abs(dx0) > 2 || Math.abs(dy0) > 2)) dragMoved = true;
      if (!dragMoved) return;
      const dx = dx0 * dragNode.scale, dy = dy0 * dragNode.scale;
      const moved = { x: dragNode.base.x + dx, y: dragNode.base.y + dy, w: dragNode.base.w, h: dragNode.base.h };
      // 被拖拽节点严格按鼠标位移量 1:1 移动，不做任何钳制/阻挡（本身完全跟手）；
      // resolveCollisions 会把与它冲突的其他节点/泳道"挤开"，applyChanges 统一把
      // 受影响的节点/边/泳道刷新到 DOM。
      flow.layout.nodes[dragNode.id] = moved;
      const changed = resolveCollisions(new Set([dragNode.id]));
      applyChanges(changed, dragNode.el, dragNode.id);
    } else if (dragLane) {
      const dx0 = ev.clientX - dragLane.startX, dy0 = ev.clientY - dragLane.startY;
      if (!dragMoved && (Math.abs(dx0) > 2 || Math.abs(dy0) > 2)) dragMoved = true;
      if (!dragMoved) return;
      const dx = dx0 * dragLane.scale, dy = dy0 * dragLane.scale;
      // 整条泳道的所有成员严格按同一个位移量整体平移，保持彼此相对位置不变、严格跟手。
      dragLane.ids.forEach(id => {
        const b = dragLane.bases[id];
        flow.layout.nodes[id] = { x: b.x + dx, y: b.y + dy, w: b.w, h: b.h };
      });
      const changed = resolveCollisions(new Set(dragLane.ids));
      applyChanges(changed, null, null);
    } else if (panState) {
      const dx = (ev.clientX - panState.startX) * panState.scale;
      const dy = (ev.clientY - panState.startY) * panState.scale;
      view.x = panState.ox - dx; view.y = panState.oy - dy;
      applyView();
    }
  };
  const onMouseUp = () => {
    document.body.style.userSelect = '';
    if (dragNode) {
      if (!dragMoved) nodeDetail(flow, dragNode.id);
      dragNode = null;
    }
    dragLane = null;
    panState = null;
  };
  svg.addEventListener('mousedown', onMouseDown);
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  _graphTeardown = () => {
    svg.removeEventListener('wheel', onWheel);
    svg.removeEventListener('mousedown', onMouseDown);
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  };
  applyView();
  return {
    fit: () => { view = { x: 0, y: 0, w: layout.width, h: layout.height }; applyView(); },
    reset: () => { flow.layout = JSON.parse(JSON.stringify(flow._layoutSnapshot)); return renderFlowGraph(container, flow); },
  };
}

// 真正的可拖拽/停靠/自由调整布局的窗口系统（dockview-core），对齐 Unreal Editor 停靠窗口：
// 业务流程图、路线记忆、演进史、技术详情、节点详情等都是独立的 dockview 面板，用户可以
// 自由拖动改变停靠位置、拖拽分隔条调整大小、把面板拖成标签页或浮动窗口。
// 只注册两种"组件类型"：'html-panel'（通用，内容就是一段 innerHTML，覆盖除图以外的所有
// 面板）和 'graph-panel'（业务流程图专用，需要挂载 renderFlowGraph 并绑定工具栏按钮）。
let _dock = null;
function ensureDock() {
  if (_dock) return _dock;
  const DV = window['dockview-core'];
  _dock = new DV.DockviewComponent(document.getElementById('dock-container'), {
    createComponent: options => {
      if (options.name === 'graph-panel') {
        const el = document.createElement('div');
        el.className = 'dock-graph';
        return {
          element: el,
          init: params => {
            const flow = params.params.flow;
            const lanes = flow.lanes || [];
            const legend = lanes.map(l => `<span><span class="sw" style="background:${laneColor(lanes, l)}"></span>${esc(l)}</span>`).join('');
            el.innerHTML = `<div class="graph-toolbar">
                <button class="btn-fit" type="button">适应窗口</button>
                <button class="btn-reset" type="button">重置布局</button>
                <span class="hint">点节点看证据 / 滚轮缩放 / 拖动空白处平移 / 拖动节点或泳道手动微调（服务端一次性静态分层布局，加载后不会自动移动）</span>
              </div>
              <div class="graph-mount"></div>
              <div id="legend">${legend}</div>`;
            let graph = renderFlowGraph(el.querySelector('.graph-mount'), flow);
            const bindToolbar = g => {
              el.querySelector('.btn-fit').onclick = () => g.fit();
              el.querySelector('.btn-reset').onclick = () => { graph = g.reset(); bindToolbar(graph); };
            };
            if (graph) bindToolbar(graph);
          },
        };
      }
      // 'html-panel'：通用面板，内容是一段现成的 innerHTML 字符串，params.cls 可选附加
      // class（比如 markdown-body），update() 支持外部刷新内容（节点详情面板复用同一个）。
      const el = document.createElement('div');
      el.className = 'dock-html';
      return {
        element: el,
        init: params => {
          if (params.params && params.params.cls) el.classList.add(params.params.cls);
          el.innerHTML = (params.params && params.params.html) || '';
        },
        update: event => {
          if (event.params && 'html' in event.params) el.innerHTML = event.params.html;
        },
      };
    },
  });
  return _dock;
}

function subjectView(s) {
  const dv = ensureDock();
  dv.clear();
  // dockview 面板的 title 只接受纯文本（它自己的默认 tab 渲染器会把传入内容按文本转义显示，
  // 不会解析 HTML），状态徽标这类 HTML 只能放进面板正文，不能放在 title 里。
  //
  // 之前把总览/路线记忆/演进史/技术详情拆成 4 个独立 dockview 面板，但这几块内容本身都很
  // 单薄（总览就一个徽标 + 几个 chip，技术详情就三五行哈希），拆成"可以自由拖拽停靠"的独立
  // 窗口反而是空占地方、没有实际收益——真正需要独立窗口能力（可大可小、可拖拽调整）的只有
  // Graph（信息密度高、需要大量空间交互）和节点详情（动态产生、内容因节点而异）。这里改为
  // 把总览/路线记忆/演进史/技术详情合并进同一个"信息"面板（面板本身依然是 dockview 面板，
  // 一样可以整体拖拽/停靠/调整大小，只是内部不再无意义地再拆细）。
  const memHtml = `<h3>路线记忆（${s.memories.length} 次查询累积）</h3>
    <table><tr><th></th><th>意图</th><th>步数</th><th>记录时间</th><th>最近校验</th></tr>` +
    s.memories.map(m => `<tr><td>${badge(m.status)}</td><td>${esc(m.intent)}</td><td>${m.step_count}</td>
      <td>${fmtTime(m.created_at)}</td><td>${fmtTime(m.last_validated_at)}</td></tr>`).join('') + '</table>';
  const evoHtml = s.evolution.length
    ? `<h3>演进史</h3><ul class="timeline">` + s.evolution.map(ev =>
        `<li>${fmtTime(ev.created_at)} · ${ev.kind === 'flow' ? '流程附注' : '快照'} ${badge(ev.status)} ${esc(ev.status)}</li>`).join('') + '</ul>'
    : '';
  const techHtml = `<details class="tech"><summary>技术详情（机器数据）</summary>
    <p>subject_id: <code>${esc(s.id)}</code></p>
    ${s.memories.map(m => `<p>memory <code>${esc(m.id)}</code> @ ${esc(m.branch || '')} ${esc(m.commit || '')}</p>`).join('')}
  </details>`;
  const infoHtml = `<p>${badge(s.status)} ${esc(s.status)}</p>
    <div class="chips">${(s.aliases || []).map(a => `<span class="chip">${esc(a)}</span>`).join('')}</div>
    ${memHtml}${evoHtml}${techHtml}`;
  dv.addPanel({ id: 'info', component: 'html-panel', title: s.name, params: { html: infoHtml, cls: 'markdown-body' } });
  if (s.flow) {
    dv.addPanel({ id: 'graph', component: 'graph-panel', title: '业务流程图', params: { flow: s.flow },
      position: { direction: 'right', referencePanel: 'info' } });
  } else {
    dv.addPanel({ id: 'graph', component: 'html-panel', title: '业务流程图',
      params: { html: '<div class="chip">尚无通过质量门禁的流程附注</div>' },
      position: { direction: 'right', referencePanel: 'info' } });
  }
}

function nodeDetail(flow, nodeId) {
  const n = (flow.nodes || []).find(x => x.id === nodeId);
  if (!n) return;
  const evs = (n.evidence_view && n.evidence_view.length) ? n.evidence_view
    : (n.evidence || []).map(ref => ({ ref }));
  const html = `<h2>${esc(n.label)}</h2>
    <p>${esc(n.summary || '')}</p>
    ${(n.details || []).map(d => `<p class="sub">· ${esc(d)}</p>`).join('')}
    <h4>源码证据（${evs.length}）</h4>
    ${evs.map(evidenceHtml).join('')}
    <details class="tech"><summary>技术详情</summary>
      ${(n.evidence_anchors || []).map(a => `<p><code>${esc(a.reference)}</code><br>anchor: <code>${esc(a.anchor_hash)}</code></p>`).join('') || '<p>无锚点哈希</p>'}
    </details>`;
  const dv = ensureDock();
  const title = `节点：${n.label}`;
  // 注意：这里用 dv.panels.find(...) 而不是 dv.getPanel(id)——实测 getPanel 在这个
  // 版本里对刚创建不久的面板会返回 undefined（即便该 id 确实存在于 dv.panels 里），
  // 直接在面板数组里按 id 查找更可靠，避免"panel already exists"报错。
  const existing = dv.panels.find(p => p.id === 'node-detail');
  if (existing) {
    existing.api.setTitle(title);
    existing.update({ params: { html } });
    existing.focus();
  } else {
    const graphPanel = dv.panels.find(p => p.id === 'graph');
    dv.addPanel({ id: 'node-detail', component: 'html-panel', title, params: { html },
      position: graphPanel ? { direction: 'right', referencePanel: 'graph' } : undefined });
  }
  document.querySelectorAll('.flow-node.sel').forEach(g => g.classList.remove('sel'));
  const g = document.querySelector(`.flow-node[data-id="${cssEsc(nodeId)}"]`);
  if (g) g.classList.add('sel');
}
function closeDetail() {
  const dv = ensureDock();
  const p = dv.panels.find(x => x.id === 'node-detail');
  if (p) dv.removePanel(p);
  document.querySelectorAll('.flow-node.sel').forEach(g => g.classList.remove('sel'));
}

function mapView() {
  const dv = ensureDock();
  dv.clear();
  const cards = DATA.subjects.map(s => {
    const rel = (s.relations || []).map(r => `<span class="chip">${esc(r.type)} → ${esc(nameOf(r.target))}</span>`).join('');
    return `<div class="card" onclick="navigateTo('subject/${esc(s.id)}')">
      <h3>${badge(s.status)} ${esc(s.name)}</h3>
      <div class="sub">路线 ${s.memories.length} · 证据 ${s.evidence.length} · ${s.flow ? '✅ 有业务流程图' : '尚无流程图'}</div>
      <div class="chips">${rel}</div></div>`;
  }).join('');
  const pats = DATA.patterns.map(p => `<div class="card" onclick="navigateTo('pattern/${esc(p.id)}')">
      <h3>${badge(p.status)} ${esc(p.name)}</h3>
      <div class="sub">阶段 ${p.stages.length} · 支撑主题 ${p.members.length}</div></div>`).join('');
  dv.addPanel({ id: 'map-subjects', component: 'html-panel', title: '业务主题地图', params: { html: `<div class="grid">${cards}</div>` } });
  dv.addPanel({ id: 'map-patterns', component: 'html-panel', title: '业务模式（跨主题归纳）',
    params: { html: `<div class="grid">${pats || '<span class="chip">暂无</span>'}</div>` },
    position: { direction: 'below', referencePanel: 'map-subjects' } });
}

function patternView(p) {
  const dv = ensureDock();
  dv.clear();
  // 同 subjectView：总览/阶段/技术详情内容都比较单薄，合并进一个"信息"面板，不必再拆细；
  // 支撑主题是一组卡片、内容量独立且可能较多，保留为单独面板。
  const stagesHtml = `<h3>阶段</h3><table><tr><th>#</th><th>阶段</th><th>状态</th></tr>
    ${p.stages.map(st => `<tr><td>${st.index}</td><td>${esc(st.name)}</td><td>${badge(st.status)} ${esc(st.status)}</td></tr>`).join('')}</table>`;
  const techHtml = `<details class="tech"><summary>技术详情</summary><p>pattern_id: <code>${esc(p.id)}</code></p></details>`;
  const infoHtml = `<p>${badge(p.status)} ${esc(p.status)}</p>${stagesHtml}${techHtml}`;
  dv.addPanel({ id: 'info', component: 'html-panel', title: p.name, params: { html: infoHtml, cls: 'markdown-body' } });
  const membersHtml = `<div class="grid">
    ${p.members.map(id => `<div class="card" onclick="navigateTo('subject/${esc(id)}')"><h3>${esc(nameOf(id))}</h3></div>`).join('') || '<span class="chip">暂无</span>'}</div>`;
  dv.addPanel({ id: 'members', component: 'html-panel', title: '支撑主题', params: { html: membersHtml },
    position: { direction: 'right', referencePanel: 'info' } });
}

function hintsView() {
  const dv = ensureDock();
  dv.clear();
  const html = `<table><tr><th>命令</th><th>参数</th><th>失败类型</th><th>错误摘要</th><th>时间</th></tr>
    ${DATA.negative_hints.map(h => `<tr><td><code>${esc(h.command)}</code></td><td><code>${esc(h.args || '')}</code></td>
      <td>${esc(h.failure_type)}</td><td>${esc(h.error || '')}</td><td>${fmtTime(h.created_at)}</td></tr>`).join('')}</table>`;
  dv.addPanel({ id: 'hints', component: 'html-panel', title: '避坑记录（失败被自动隔离，不污染成功路线）', params: { html, cls: 'markdown-body' } });
}

function nameOf(subjectId) {
  const s = DATA.subjects.find(x => x.id === subjectId);
  return s ? s.name : subjectId;
}
function current() {
  const [kind, id] = (location.hash.slice(1) || 'map').split('/');
  return kind === 'subject' ? DATA.subjects.find(s => s.id === id) : null;
}

// 通用面板拖拽分隔条：axis='x' 左右拖动改宽度，axis='y' 上下拖动改高度。
// sign=1 表示朝正方向拖动增大尺寸（如左侧栏右边界、图表下边界）；
// sign=-1 表示朝负方向拖动增大尺寸（如右侧详情栏的左边界）。
function makeResizer(handle, axis, sign, { getSize, setSize, min, max }) {
  if (!handle) return;
  let startPos = 0, startSize = 0;
  const onMove = ev => {
    const pos = axis === 'x' ? ev.clientX : ev.clientY;
    const delta = (pos - startPos) * sign;
    setSize(Math.min(max, Math.max(min, startSize + delta)));
  };
  const onUp = () => {
    handle.classList.remove('active');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
  };
  handle.addEventListener('mousedown', ev => {
    ev.preventDefault();
    startPos = axis === 'x' ? ev.clientX : ev.clientY;
    startSize = getSize();
    handle.classList.add('active');
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  });
}

function route() {
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
  if (hit) navigateTo('subject/' + hit.id);
});

// nav 侧栏在 dockview 容器之外，是固定的"应用外壳"（类似 Unreal Editor 顶部菜单/工具栏），
// 不是可变内容窗口，沿用简单的自写拖拽分隔条即可；dockview 内部所有面板自带拖拽分割条，
// 不需要（也不应该）再额外套一层手动 resizer。
makeResizer($('#resizer-nav'), 'x', 1, {
  getSize: () => $('#nav').getBoundingClientRect().width,
  setSize: w => { $('#nav').style.width = w + 'px'; },
  min: 160, max: 480,
});

$('#meta').textContent = `生成于 ${fmtTime(DATA.generated_at)} · 主题 ${DATA.stats.subject_count} · 路线 ${DATA.stats.memory_count} · 证据 ${DATA.stats.evidence_count} · 数据源 memory.sqlite（本页面为程序化生成产物）`;
// popstate 处理浏览器前进/后退（pushState 产生的历史记录）；hashchange 作为兜底
// （例如用户直接编辑地址栏 # 片段），二者都指向同一个 route() 不会重复触发副作用。
window.addEventListener('popstate', route);
window.addEventListener('hashchange', route);
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
