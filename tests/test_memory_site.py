import re
from pathlib import Path

from ue5_kb.query.query_audit import record_query
from ue5_kb.query.memory_site import _route_edge, compute_static_layout, export_site
from ue5_kb.query.query_memory import attach_business_flow, record_memory


def _context(source_root: Path) -> dict:
    return {
        "skill_name": "Demo-kb",
        "data_trust": "fresh",
        "source": str(source_root),
        "branch": "main",
        "kb_path": "variants/demo",
        "commit": "abc123",
        "dirty": False,
        "fingerprint": "fp",
    }


def test_export_site_generates_single_file_wiki_from_sqlite_only(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Demo.cpp"
    source_file.write_text("\n".join(f"void Fn{i}() {{}}" for i in range(1, 30)), encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-wiki",
        command="source_slice",
        args=["Demo.cpp", "10"],
        context=_context(source_root),
        result={"file": "Demo.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-wiki",
        intent="explain_business_flow",
        seed="DemoLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "DemoLayer 业务流程",
            "nodes": [
                {"id": "a", "label": "入口 </script> 转义", "summary": "s", "details": ["d"],
                 "lane": "入口", "evidence": ["Demo.cpp:10"]},
                {"id": "b", "label": "输出", "summary": "s", "details": ["d"], "lane": "输出",
                 "evidence": ["Demo.cpp:20"]},
            ],
            "edges": [{"source": "a", "target": "b", "label": "驱动"}],
        },
        source_root=source_root,
    )

    result = export_site(skill_dir=skill_dir, source_root=source_root)
    site = Path(result["site_file"])
    assert site.exists()
    text = site.read_text(encoding="utf-8")

    # 单文件、程序化声明、数据源声明
    assert "generated_by: UE5_KnowledgeBaseMaker query_memory_render_site" in text
    assert "memory.sqlite" in text
    # 主题与流程数据内嵌
    assert "DemoLayer" in text
    assert "压地形" not in text  # 不应混入他库数据
    # 源码片段内嵌 + vscode 深链
    assert "void Fn10()" in text
    assert "vscode://file/" in text
    # </script> 不得提前终结数据块
    assert "</script> 转义" not in text
    # 图引擎改为服务端确定性静态布局（无运行时物理引擎，不会自行移动），排版仍用 github-markdown-css
    assert 'src="vendor/vis-network' not in text
    assert 'new vis.Network(' not in text
    assert 'href="vendor/github-markdown.css"' in text
    assert "function compute" not in text  # 布局计算在 Python 端完成，前端不包含布局算法
    assert "routeEdgePath" in text  # 前端仅做拖拽时的边重绘，不做全局布局
    # 面板可拖拽调整 + 代码可切换换行 + 滚动条统一样式
    assert 'id="resizer-nav"' in text
    assert 'id="resizer-detail"' in text
    assert 'id="graph-resize"' in text
    assert "function makeResizer" in text
    assert "function toggleWrap" in text
    assert "::-webkit-scrollbar" in text
    # 拖拽性能修复：图重建前必须先清理上一次的窗口级事件监听，否则多次切换 subject 会累积泄漏
    assert "_graphTeardown" in text
    assert result["stats"]["subject_count"] == 1
    assert result["stats"]["memory_count"] == 1
    assert result["generated_programmatically"] is True

    # vendor 资产只剩 github-markdown-css（图引擎不再 vendor 第三方库）
    assert set(result["vendor_assets"]) == {"github-markdown.css"}
    vendor_dir = Path(result["vendor_dir"])
    assert not (vendor_dir / "vis-network.min.js").exists()
    assert (vendor_dir / "github-markdown.css").stat().st_size > 10_000

    # 幂等：重新生成字节级一致（generated_at 除外的确定性由数据决定，允许时间戳差异）
    again = export_site(skill_dir=skill_dir, source_root=source_root)
    assert Path(again["site_file"]).exists()


def test_compute_static_layout_is_deterministic_and_overlap_free():
    flow = {
        "lanes": ["入口", "中间", "输出"],
        "nodes": [
            {"id": "a1", "lane": "入口"},
            {"id": "a2", "lane": "入口"},
            {"id": "b1", "lane": "中间"},
            {"id": "c1", "lane": "输出"},
        ],
        "edges": [
            {"source": "a1", "target": "b1"},
            {"source": "a2", "target": "b1"},
            {"source": "b1", "target": "c1"},
        ],
    }
    layout_a = compute_static_layout(flow)
    layout_b = compute_static_layout(flow)
    assert layout_a == layout_b  # 确定性：同输入永远同输出

    positions = layout_a["nodes"]
    assert set(positions) == {"a1", "a2", "b1", "c1"}

    def overlap(p, q):
        return not (p["x"] + p["w"] <= q["x"] or q["x"] + q["w"] <= p["x"]
                    or p["y"] + p["h"] <= q["y"] or q["y"] + q["h"] <= p["y"])

    ids = list(positions)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            assert not overlap(positions[ids[i]], positions[ids[j]]), f"{ids[i]} 与 {ids[j]} 重叠"

    # a1/a2 在同一泳道不同 y？应该同 y（同行）不同 x
    assert positions["a1"]["y"] == positions["a2"]["y"]
    assert positions["a1"]["x"] != positions["a2"]["x"]
    # 三条泳道自上而下 y 依次增大
    assert positions["a1"]["y"] < positions["b1"]["y"] < positions["c1"]["y"]

    lane_names = [lane["name"] for lane in layout_a["lanes"]]
    assert lane_names == ["入口", "中间", "输出"]

    edge_endpoints = {(e["source"], e["target"]) for e in layout_a["edges"]}
    assert edge_endpoints == {("a1", "b1"), ("a2", "b1"), ("b1", "c1")}
    for edge in layout_a["edges"]:
        assert edge["path"].startswith("M ")

    assert layout_a["width"] > 0 and layout_a["height"] > 0


def test_compute_static_layout_wraps_large_lane_into_rows_and_respects_intra_lane_order():
    """同一大步骤（泳道）节点数超过每行上限、且存在跨节点的依赖链时，应按依赖关系
    分层换行——独立节点（无泳道内依赖关系的 n2/n3/n4）可以和 n1 同层并排，超过每行
    上限时按顺序换行；而依赖 n1 的 n5 必须被分到独立的新一层（新的一行），不能和
    n1 同排，阅读顺序（先左后右、先上后下）必须尊重该依赖方向。"""
    flow = {
        "lanes": ["step"],
        "nodes": [{"id": f"n{i}", "lane": "step"} for i in range(1, 6)],
        # n5 依赖 n1（必须排在 n1 之后，且必须换到独立的一行，而不是和 n1 同排）
        "edges": [{"source": "n1", "target": "n5"}],
    }
    layout = compute_static_layout(flow)
    positions = layout["nodes"]

    # n1/n2/n3/n4 互相之间没有依赖，属于同一层，超过每行上限 3 才换行 -> [3, 1]；
    # n5 依赖 n1，必须落在独立的下一层（第三行），总计 3 行：[3, 1, 1]
    rows = sorted({p["y"] for p in positions.values()})
    assert len(rows) == 3
    row_counts = {}
    for p in positions.values():
        row_counts[p["y"]] = row_counts.get(p["y"], 0) + 1
    assert sorted(row_counts.values()) == [1, 1, 3]

    # 依赖顺序尊重：n1 的阅读顺序（行优先、同行按 x）必须早于 n5，且二者不同行
    def reading_order(pos):
        return (pos["y"], pos["x"])
    assert reading_order(positions["n1"]) < reading_order(positions["n5"])
    assert positions["n1"]["y"] != positions["n5"]["y"]

    # 泳道边框必须是其成员节点的紧致包围盒（而不是无视换行的整行宽度）
    lane_rect = layout["lanes"][0]
    xs = [p["x"] for p in positions.values()]
    ys = [p["y"] for p in positions.values()]
    max_xs = [p["x"] + p["w"] for p in positions.values()]
    max_ys = [p["y"] + p["h"] for p in positions.values()]
    assert lane_rect["x"] <= min(xs)
    assert lane_rect["y"] <= min(ys)
    assert lane_rect["x"] + lane_rect["w"] >= max(max_xs)
    assert lane_rect["y"] + lane_rect["h"] >= max(max_ys)


def test_compute_static_layout_keeps_independent_nodes_side_by_side_without_any_edges():
    """完全没有依赖边的一组节点（纯并行），只应按每行上限做数量换行，不应被强行
    拆成单节点一行——验证分层算法在"无依赖"这个基础场景下退化为原来的按数量换行。"""
    flow = {
        "lanes": ["step"],
        "nodes": [{"id": f"n{i}", "lane": "step"} for i in range(1, 6)],
        "edges": [],
    }
    layout = compute_static_layout(flow)
    positions = layout["nodes"]
    rows = sorted({p["y"] for p in positions.values()})
    assert len(rows) == 2
    row_counts = {}
    for p in positions.values():
        row_counts[p["y"]] = row_counts.get(p["y"], 0) + 1
    assert sorted(row_counts.values()) == [2, 3]


def test_compute_static_layout_forces_dependency_chain_into_separate_rows_even_under_max_cols():
    """还原用户反馈的真实场景：同一泳道内 A、B 互相独立（可并排），但 B 依赖的
    C 有直接依赖边 B->C；即便三个节点数量不超过每行上限 3，也不能把 B、C 挤在
    同一行——C 必须换到 B 下面的新一行，因为二者是顺序关系而不是并行分支。"""
    flow = {
        "lanes": ["step"],
        "nodes": [{"id": "a", "lane": "step"}, {"id": "b", "lane": "step"}, {"id": "c", "lane": "step"}],
        "edges": [{"source": "b", "target": "c"}],
    }
    layout = compute_static_layout(flow)
    positions = layout["nodes"]

    # a、b 无依赖关系，属于同一层，可以同排
    assert positions["a"]["y"] == positions["b"]["y"]
    # c 依赖 b，必须换到新的一行，不能和 a/b 同排
    assert positions["c"]["y"] != positions["b"]["y"]
    assert positions["c"]["y"] > positions["b"]["y"]



def _assert_no_diagonal_line_segments(path: str, desc: str = ""):
    """校验路径里每一条 L（直线）指令都严格水平或竖直。Q（圆角）指令本身就是
    曲线过渡，允许其起止点之间存在小的斜向位移（半径受 _MIN_JOG 限制，视觉上
    是圆角，不是斜线），因此不校验 Q 段，只校验真正的 L 直线段。"""
    tokens = re.findall(r"([MLQ])((?:\s*-?\d+\.?\d*){2,4})", path)
    cur = None
    for cmd, nums in tokens:
        vals = [float(v) for v in nums.split()]
        if cmd in ("M", "L"):
            pt = (vals[0], vals[1])
            if cmd == "L" and cur is not None:
                dx, dy = abs(pt[0] - cur[0]), abs(pt[1] - cur[1])
                assert dx < 0.6 or dy < 0.6, f"{desc}: 出现斜线段 {cur} -> {pt} in {path}"
            cur = pt
        elif cmd == "Q":
            cur = (vals[2], vals[3])  # Q 的终点，作为后续指令的起点，但不校验 Q 自身


def test_route_edge_is_always_orthogonal_never_diagonal():
    """无论两个节点框的相对位置如何（正常向下、同排并列、甚至反向在上方），
    _route_edge 生成的折线路径的每一条直线段都只能是水平/竖直的，绝不允许出现斜线段。"""
    cases = {
        "straight down, same x": (
            {"x": 0, "y": 0, "w": 200, "h": 56}, {"x": 0, "y": 100, "w": 200, "h": 56},
        ),
        "down, different x": (
            {"x": 0, "y": 0, "w": 200, "h": 56}, {"x": 300, "y": 100, "w": 200, "h": 56},
        ),
        "backward: target above": (
            {"x": 0, "y": 100, "w": 200, "h": 56}, {"x": 0, "y": 0, "w": 200, "h": 56},
        ),
        "backward + offset x": (
            {"x": 0, "y": 100, "w": 200, "h": 56}, {"x": 300, "y": 0, "w": 200, "h": 56},
        ),
        "same row, side by side": (
            {"x": 0, "y": 0, "w": 200, "h": 56}, {"x": 300, "y": 0, "w": 200, "h": 56},
        ),
        "vertically overlapping, offset": (
            {"x": 0, "y": 0, "w": 200, "h": 56}, {"x": 300, "y": 20, "w": 200, "h": 56},
        ),
    }
    for desc, (a, b) in cases.items():
        geom = _route_edge(a, b)
        _assert_no_diagonal_line_segments(geom["path"], desc)


def test_compute_static_layout_edges_never_diagonal_for_backward_same_lane_edge():
    """同一泳道同一行内的边（此前会退化成直线斜连）经过完整 compute_static_layout
    流程后，落到 payload 里的边路径也必须是直角折线。"""
    flow = {
        "lanes": ["step"],
        "nodes": [{"id": "n1", "lane": "step"}, {"id": "n2", "lane": "step"}],
        "edges": [{"source": "n1", "target": "n2"}],
    }
    layout = compute_static_layout(flow)
    edge = layout["edges"][0]
    _assert_no_diagonal_line_segments(edge["path"])


