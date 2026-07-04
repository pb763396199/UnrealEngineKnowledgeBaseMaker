from pathlib import Path

from ue5_kb.query.query_audit import record_query
from ue5_kb.query.memory_site import export_site
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
    # 图引擎/排版改为成熟开源库离线 vendor，而非手写 SVG/纯自定义 CSS
    assert 'src="vendor/vis-network.min.js"' in text
    assert 'href="vendor/github-markdown.css"' in text
    assert "new vis.Network(" in text
    assert result["stats"]["subject_count"] == 1
    assert result["stats"]["memory_count"] == 1
    assert result["generated_programmatically"] is True

    # vendor 资产随生成物一起落盘（离线可用，不依赖 CDN）
    assert set(result["vendor_assets"]) == {"vis-network.min.js", "github-markdown.css"}
    vendor_dir = Path(result["vendor_dir"])
    assert (vendor_dir / "vis-network.min.js").stat().st_size > 100_000
    assert (vendor_dir / "github-markdown.css").stat().st_size > 10_000

    # 幂等：重新生成字节级一致（generated_at 除外的确定性由数据决定，允许时间戳差异）
    again = export_site(skill_dir=skill_dir, source_root=source_root)
    assert Path(again["site_file"]).exists()
    assert (Path(again["vendor_dir"]) / "vis-network.min.js").exists()
