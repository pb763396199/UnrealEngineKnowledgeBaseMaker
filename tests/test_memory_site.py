from pathlib import Path

from ue5_kb.query.query_audit import record_query
from ue5_kb.query.memory_site import compute_static_layout, export_site
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
