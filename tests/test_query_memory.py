import sqlite3
from pathlib import Path

from ue5_kb.query.query_audit import record_query
from ue5_kb.query.query_memory import (
    attach_business_flow,
    diff_memory,
    list_negative_hints,
    list_subjects,
    record_memory,
    render_memory,
    replay_memory,
    snapshot_memory,
    search_memory,
    validate_memory,
)


def _context(source_root: Path, **overrides) -> dict:
    context = {
        "skill_name": "Demo-kb",
        "data_trust": "fresh",
        "source": str(source_root),
        "branch": "main",
        "kb_path": "variants/demo",
        "commit": "abc123",
        "dirty": False,
        "fingerprint": "fingerprint-demo",
    }
    context.update(overrides)
    return context


def test_query_memory_records_route_without_source_body_and_validates_fresh(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    source_file.write_text("void Feature() {\n  CallTarget();\n}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-feature",
        command="resolve_seed",
        args=["Feature", "20"],
        context=_context(source_root),
        result={"seed": "Feature", "resolution_state": "function", "candidate_count": 1},
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-feature",
        command="source_slice",
        args=["Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "content": "SOURCE_BODY_SHOULD_NOT_BE_STORED"},
    )

    def runner(command, args):
        if command == "resolve_seed":
            return {"seed": args[0], "resolution_state": "function", "candidate_count": 1}
        if command == "source_slice":
            return {"file": args[0], "line_start": int(args[1]), "found_count": 1, "content": "CURRENT_BODY"}
        raise AssertionError(command)

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-feature",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert recorded["schema"] == "query-memory-record/v1"
    assert recorded["step_count"] == 2
    assert recorded["evidence_count"] == 1
    assert recorded["stores_business_facts"] is False

    found = search_memory(skill_dir=skill_dir, keyword="Feature", intent="explain_business_flow")
    assert found["found_count"] == 3
    assert found["pattern_count"] == 1
    assert found["audit_trace_count"] == 1
    assert found["evidence_match_count"] == 1
    assert found["evidence_matches"][0]["reusable_as"] == "evidence_anchor"
    assert found["facts_reused"] is False

    memory_id = recorded["memory_id"]
    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=memory_id,
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    assert validation["overall"] == "fresh"
    assert validation["reusable_as"] == "route_and_evidence"
    assert validation["facts_reused"] is False

    replay = replay_memory(skill_dir=skill_dir, memory_id=memory_id, command_runner=runner)
    assert replay["step_count"] == 2
    assert all(step["status"] == "same" for step in replay["steps"])

    all_bytes = (skill_dir / "memory" / "memory.sqlite").read_bytes()
    assert b"SOURCE_BODY_SHOULD_NOT_BE_STORED" not in all_bytes
    assert b"CURRENT_BODY" not in all_bytes


def test_query_memory_replay_hash_is_invariant_to_environment_meta(tmp_path):
    """回归：_meta/_audit 是环境元数据（cwd 解析、freshness 快照），
    不得参与 result hash，否则换个 cwd 调用 validate 会全量误报 changed。"""
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    (source_root / "Feature.cpp").write_text("void Feature() {}\n", encoding="utf-8")

    payload = {"seed": "Feature", "resolution_state": "function", "candidate_count": 1}
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-meta",
        command="resolve_seed",
        args=["Feature"],
        context=_context(source_root),
        result={
            **payload,
            "_meta": {"current_source": "C:/cwd-a", "freshness": {"fresh": True}},
            # 大体量嵌套子结果：内部 _meta 也必须被剔除而不是被 str() 截断带进哈希
            "seed_resolution": {
                "_meta": {"current_source": "C:/cwd-a"},
                "candidates": [{"symbol": f"Sym{i}", "note": "x" * 50} for i in range(80)],
            },
        },
    )

    def runner_with_other_meta(command, args):
        assert command == "resolve_seed"
        return {
            **payload,
            "_meta": {"current_source": "D:/cwd-b", "freshness": {"fresh": True, "extra": 1}},
            "_audit": {"trace_id": "x"},
            "seed_resolution": {
                "_meta": {"current_source": "D:/cwd-b"},
                "candidates": [{"symbol": f"Sym{i}", "note": "x" * 50} for i in range(80)],
            },
        }

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-meta",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner_with_other_meta,
    )
    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner_with_other_meta,
    )
    assert validation["freshness"]["commands"] == "same"
    assert validation["overall"] == "fresh"


def test_query_memory_attach_flow_rejects_fabricated_evidence(tmp_path):
    """程序化证据校验：AI 无法用假 file:line 混过质量门禁。"""
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    (source_root / "Real.cpp").write_text("\n".join(f"line{i}" for i in range(1, 21)), encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-ev",
        command="source_slice",
        args=["Real.cpp", "5"],
        context=_context(source_root),
        result={"file": "Real.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-ev",
        intent="explain_business_flow",
        seed="EvidenceGate",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    # 假文件与越界行号都必须被拒
    rejected = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "假证据流程",
            "nodes": [
                {"id": "a", "label": "真实节点", "summary": "s", "details": ["d"], "evidence": ["Real.cpp:5"]},
                {"id": "b", "label": "假文件节点", "summary": "s", "details": ["d"], "evidence": ["Fake.cpp:1"]},
                {"id": "c", "label": "越界行号节点", "summary": "s", "details": ["d"], "evidence": ["Real.cpp:999"]},
            ],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
        },
        source_root=source_root,
    )
    assert rejected["publication_status"] == "candidate"
    assert rejected["quality"]["status"] == "evidence_validation_failed"
    reasons = {item["reason"] for item in rejected["evidence_validation"]["invalid"]}
    assert reasons == {"file_not_found", "line_out_of_range"}

    # 全真实证据可正常通过校验（不因校验器误伤）
    accepted = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "真证据流程",
            "nodes": [
                {"id": "a", "label": "节点A", "summary": "s", "details": ["d"], "evidence": ["Real.cpp:5"]},
                {"id": "b", "label": "节点B", "summary": "s", "details": ["d"], "evidence": ["Real.cpp:10 | 注释"]},
            ],
            "edges": [{"source": "a", "target": "b"}],
        },
        source_root=source_root,
    )
    assert accepted["evidence_validation"]["all_valid"] is True
    # 校验通过的锚点必须带 anchor_hash 入库
    import json as _json
    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        flow_json = conn.execute(
            "SELECT flow_json FROM business_flow_annotations WHERE id=?", (accepted["annotation_id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    stored = _json.loads(flow_json)
    anchors = [a for node in stored["nodes"] for a in node.get("evidence_anchors", [])]
    assert len(anchors) == 2
    assert all(a["anchor_hash"] for a in anchors)


def test_query_memory_search_surfaces_unrecorded_audit_trace_fragments(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-building",
        command="resolve_seed",
        args=["BuildingLayer", "20"],
        context=_context(source_root),
        result={"seed": "BuildingLayer", "candidate_count": 1},
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-building",
        command="source_slice",
        args=["Source/AesEarth/Private/AesBuilding/AesBuildingPayload/AesBuildingLayer.cpp", "6"],
        context=_context(source_root),
        result={"file": "AesBuildingLayer.cpp", "found_count": 1},
    )

    found = search_memory(skill_dir=skill_dir, keyword="BuildingLayer", intent="explain_business_flow")

    assert found["found_count"] == 1
    assert found["pattern_count"] == 0
    assert found["audit_trace_count"] == 1
    assert found["negative_audit_trace_count"] == 0
    trace = found["audit_traces"][0]
    assert trace["kind"] == "audit_trace"
    assert trace["trace_id"] == "trace-building"
    assert trace["reusable_as"] == "route_fragment"
    assert "query_memory_record trace-building <intent> <seed>" == trace["record_command"]
    assert trace["facts_reused"] is False


def test_query_memory_records_failures_as_negative_hints_without_poisoning_route(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    source_file.write_text("void Feature() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-mixed",
        command="source_slice",
        args=["Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "found_count": 1},
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-mixed",
        command="query_class_info",
        args=["MissingFeature"],
        context=_context(source_root),
        result={"error": "not found", "_audit": {"trace_id": "recording-trace"}},
    )

    def runner(command, args):
        if command == "source_slice":
            return {"file": args[0], "line_start": int(args[1]), "found_count": 1}
        assert command == "query_class_info"
        return {
            "error": "not found",
            "fallback_command": "search_classes MissingFeature",
            "hint": "use fuzzy search",
            "_audit": {"trace_id": "replay-trace"},
        }

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-mixed",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert recorded["step_count"] == 1
    assert recorded["negative_hint_count"] == 1
    assert validation["overall"] == "fresh"
    assert validation["freshness"]["commands"] == "same"
    assert validation["replay"][0]["command"] == "source_slice"

    hints = list_negative_hints(skill_dir=skill_dir, keyword="MissingFeature")
    assert hints["found_count"] == 1
    assert hints["negative_hints"][0]["failure_type"] == "semantic_miss"
    assert hints["participates_in_main_graph"] is False


def test_query_memory_rejects_all_failure_trace_as_promoted_memory(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-all-failure",
        command="query_class_info",
        args=["MissingFeature"],
        context=_context(source_root),
        result={"error": "not found"},
    )

    def runner(command, args):
        return {"error": "not found"}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-all-failure",
        intent="explain_business_flow",
        seed="MissingFeature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert recorded["recorded"] is False
    assert recorded["error"] == "no successful route steps"
    assert recorded["negative_hint_count"] == 1
    found = search_memory(skill_dir=skill_dir, keyword="MissingFeature", intent="explain_business_flow")
    assert found["pattern_count"] == 0
    assert found["audit_trace_count"] == 0
    assert found["negative_audit_trace_count"] == 1
    assert found["negative_audit_traces"][0]["reusable_as"] == "negative_hint_candidate"
    assert "record_command" not in found["negative_audit_traces"][0]


def test_query_memory_file_hash_change_marks_route_changed(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    source_file.write_text("void Feature() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-change",
        command="source_slice",
        args=["Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-change",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    source_file.write_text("void Feature() { Changed(); }\n", encoding="utf-8")

    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    assert validation["overall"] == "changed"
    assert validation["freshness"]["files"] == "changed"
    assert validation["reusable_as"] == "route_only"

    diff = diff_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    assert diff["overall"] == "changed"
    assert diff["changed_evidence"][0]["file"] == "Feature.cpp"


def test_query_memory_provenance_drift_does_not_block_cross_branch_route_reuse(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    other_root = tmp_path / "OtherSource"
    source_root.mkdir()
    other_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-runtime",
        command="resolve_seed",
        args=["Feature", "20"],
        context=_context(source_root),
        result={"seed": "Feature", "candidate_count": 1},
    )

    def runner(command, args):
        return {"seed": args[0], "candidate_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-runtime",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(other_root, branch="feature", kb_path="variants/other", commit="def456", dirty=True, fingerprint="other-fingerprint"),
        source_root=other_root,
        command_runner=runner,
    )

    assert validation["overall"] == "fresh"
    assert validation["freshness"]["kb"] == "same"
    assert validation["reusable_as"] == "route_and_evidence"
    assert validation["reasons"] == []
    assert validation["provenance"]["affects_reusability"] is False
    assert set(validation["provenance"]["diffs"]) == {
        "source_root_changed",
        "branch_name_changed",
        "variant_id_changed",
        "commit_id_changed",
        "dirty_state_changed",
        "source_fingerprint_changed",
    }


def test_query_memory_file_hash_change_with_same_anchor_is_equivalent(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    lines = [f"line {index}" for index in range(1, 41)]
    source_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-equivalent",
        command="source_slice",
        args=["Feature.cpp", "10"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "line_start": 10},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1])}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-equivalent",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    lines[30] = "changed far away"
    source_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert validation["overall"] == "equivalent"
    assert validation["freshness"]["files"] == "equivalent"
    assert validation["reusable_as"] == "route_only"


def test_query_memory_graph_expansion_marks_expanded(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-graph",
        command="query_flow",
        args=["Feature", "both"],
        context=_context(source_root),
        result={"edges": [{"source": "A", "target": "B", "edge_type": "call"}]},
    )

    expanded = False

    def runner(command, args):
        edges = [{"source": "A", "target": "B", "edge_type": "call"}]
        if expanded:
            edges.append({"source": "B", "target": "C", "edge_type": "call"})
        return {"edges": edges}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-graph",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    expanded = True

    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert validation["overall"] == "expanded"
    assert validation["freshness"]["business_path"] == "expanded"
    assert validation["reusable_as"] == "route_only"


def test_query_memory_subject_snapshot_and_obsidian_render_are_generated_views(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Source" / "DemoModule" / "Private" / "Feature.cpp"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("void FeatureLayer() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-subject",
        command="source_slice",
        args=["Source/DemoModule/Private/Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Source/DemoModule/Private/Feature.cpp", "found_count": 1},
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-subject",
        command="query_flow",
        args=["FeatureLayer", "both"],
        context=_context(source_root),
        result={"edges": [{"source": "FeatureLayer", "target": "FeatureProducer", "edge_type": "register"}]},
    )

    def runner(command, args):
        if command == "source_slice":
            return {"file": args[0], "line_start": int(args[1]), "found_count": 1}
        return {"edges": [{"source": "FeatureLayer", "target": "FeatureProducer", "edge_type": "register"}]}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-subject",
        intent="explain_business_flow",
        seed="FeatureLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    subjects = list_subjects(skill_dir=skill_dir, keyword="FeatureLayer")
    assert subjects["found_count"] == 1
    assert subjects["subjects"][0]["id"] == recorded["subject_id"]

    snapshot = snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=recorded["subject_id"])
    assert snapshot["snapshot_is_authoritative"] is True
    assert snapshot["edge_count"] == 1
    assert snapshot["commit_id"] == "abc123"

    rendered = render_memory(skill_dir=skill_dir, target="FeatureLayer")
    assert rendered["rendered_count"] == 1
    assert rendered["markdown_is_authoritative"] is False
    md = Path(rendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert "```mermaid" in md
    assert "markdown_is_authoritative: false" in md
    assert "FeatureLayer" in md
    assert "## 新鲜度" in md
    assert "## 快照" in md
    assert snapshot["snapshot_id"] in md
    assert "| 文件 | 行号 | 模块 | 符号 | 文件哈希 |" in md
    assert "本文件由 `memory/memory.sqlite` 程序化生成" in md
    assert "DemoModule" in md

    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        module_member = conn.execute(
            """
            SELECT member_id FROM business_subject_members
            WHERE subject_id=? AND member_kind='module'
            """,
            (recorded["subject_id"],),
        ).fetchone()
    finally:
            conn.close()
    assert module_member == ("DemoModule",)


def test_query_memory_render_prefers_attached_business_flow_over_static_graph(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    source_file.write_text("void Feature() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-flow",
        command="query_flow",
        args=["FeatureLayer", "both"],
        context=_context(source_root),
        result={
            "edges": [
                {"source": "RegisterEverything", "target": "CreateOtherLayer", "edge_type": "call"},
                {"source": "RegisterEverything", "target": "CreateFeatureLayer", "edge_type": "call"},
            ],
        },
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-flow",
        command="source_slice",
        args=["Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "found_count": 1},
    )

    def runner(command, args):
        if command == "query_flow":
            return {
                "edges": [
                    {"source": "RegisterEverything", "target": "CreateOtherLayer", "edge_type": "call"},
                    {"source": "RegisterEverything", "target": "CreateFeatureLayer", "edge_type": "call"},
                ],
            }
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-flow",
        intent="explain_business_flow",
        seed="FeatureLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    attached = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "FeatureLayer 业务流程",
            "nodes": [
                {"id": "entry", "label": "创建 Layer", "summary": "从模块入口创建业务层。"},
                {
                    "id": "manager",
                    "label": "组装 Manager | Producer]",
                    "summary": "注册数据层和 producer。" + "长说明" * 300,
                    "evidence": ["Feature.cpp:1 | symbol"],
                },
                {"id": "output", "label": "生成输出", "summary": "根据业务设置生成最终输出。"},
            ],
            "edges": [
                {"source": "entry", "target": "manager", "label": "持有"},
                {"source": "manager", "target": "output", "label": "驱动", "condition": "A | B && TArray<Foo>]"},
            ],
        },
    )

    assert attached["stores_business_flow"] is True
    assert attached["quality"]["status"] == "below_quality_baseline"
    assert attached["publication_status"] == "candidate"
    rendered = render_memory(skill_dir=skill_dir, target="FeatureLayer")
    md = Path(rendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert "## 质量评分" in md
    assert "## 业务流程" in md
    assert "## 节点证据" in md
    assert "尚未保存通过质量基线的业务流程附注" in md
    assert "创建 Layer" not in md.split("## 证据", 1)[0]
    assert "组装 Manager | Producer]" not in md.split("## 证据", 1)[0]
    assert "组装 Manager ¦ Producer)" not in md
    assert "A ¦ B && TArray<Foo>)" not in md
    assert "Feature.cpp:1 &#124; symbol" not in md
    assert "生成输出" not in md.split("## 证据", 1)[0]
    assert "CreateOtherLayer" in md.split("## 证据", 1)[0]
    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        flow_json = conn.execute("SELECT flow_json FROM business_flow_annotations").fetchone()[0]
    finally:
        conn.close()
    assert isinstance(__import__("json").loads(flow_json)["nodes"], list)
    assert __import__("json").loads(flow_json)["schema"] == "business-flow/v2"


def test_query_memory_high_quality_business_flow_scores_above_manual_baseline(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Road.cpp"
    source_file.write_text("void RoadLayer() {}\n", encoding="utf-8")
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-road",
        command="source_slice",
        args=["Road.cpp", "1"],
        context=_context(source_root),
        result={"file": "Road.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-road",
        intent="explain_business_flow",
        seed="RoadLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    lanes = ["入口调度", "LOD策略", "Payload管理", "原始数据", "GeoSource", "派生数据", "终端输出", "缓存过滤"]
    terms = [
        "FAesRoadLayer",
        "FAesRoadPayloadManager",
        "RoadDataMarkerProducer",
        "RoadWaterDataMarkerProducer",
        "RoadGeoSourceMarkerProducer",
        "JunctionGeoSourceMarkerProducer",
        "RoadSplineGraphMarkerProducer",
        "RoadMaskMarkerProducer",
        "bUseEarthPrefab",
        "FAesRoadBuilderMarkerProducer",
        "FAesEarthRoadMarkerProducer",
        "CreateRoadBuilder",
        "CreateEarthRoadBuilder",
        "Cache",
        "Terraforming",
        "RasterMask",
        "FAesRoadPayload",
    ]
    nodes = [
        {
            "id": f"n{index}",
            "label": f"{term} | Producer]" if index == 1 else term,
            "lane": lanes[index % len(lanes)],
            "summary": f"{term} 是 RoadLayer 业务链的一环。",
            "details": [f"{term} 有明确输入、输出和源码证据。"],
            "evidence": ["Road.cpp:1 | symbol" if index == 1 else "Road.cpp:1"],
        }
        for index, term in enumerate(terms, start=1)
    ]
    edges = [
        {"source": f"n{index}", "target": f"n{index + 1}", "label": "驱动"}
        for index in range(1, len(nodes))
    ]
    edges.extend(
        [
            {"source": "n9", "target": "n10", "label": "false", "condition": "bUseEarthPrefab=false | TArray<Foo>]"},
            {"source": "n9", "target": "n11", "label": "true", "condition": "bUseEarthPrefab=true"},
        ]
    )
    attached = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "RoadLayer 业务流程",
            "quality_baseline": {
                "minimum_score": 98,
                "status_on_pass": "exceeds_manual_roadlayer_baseline",
                "status_on_fail": "below_manual_roadlayer_baseline",
                "required_terms": terms,
            },
            "lanes": lanes,
            "nodes": nodes,
            "edges": edges,
        },
    )
    assert attached["quality"]["score"] >= 98
    assert attached["quality"]["status"] == "exceeds_manual_roadlayer_baseline"
    assert attached["publication_status"] == "published"
    rendered = render_memory(skill_dir=skill_dir, target="RoadLayer")
    md = Path(rendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert 'subgraph lane1["入口调度"]' in md
    assert "FAesRoadLayer ¦ Producer)" in md
    assert "bUseEarthPrefab=false ¦ TArray<Foo>)" in md
    assert "Road.cpp:1 &#124; symbol" in md
    assert "节点证据" in md
    assert "exceeds_manual_roadlayer_baseline" in md
    candidate = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "RoadLayer 薄流程",
            "nodes": [{"id": "thin", "label": "薄流程", "summary": "不应覆盖 published。"}],
            "edges": [],
        },
    )
    assert candidate["publication_status"] == "candidate"
    rerendered = render_memory(skill_dir=skill_dir, target="RoadLayer")
    rerendered_md = Path(rerendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert "薄流程" not in rerendered_md.split("## 证据", 1)[0]
    assert "exceeds_manual_roadlayer_baseline" in rerendered_md


def test_query_memory_pattern_snapshot_render_and_provenance_aggregate_multiple_subjects(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    first_file = source_root / "Source" / "DemoModule" / "Private" / "First.cpp"
    second_file = source_root / "Source" / "DemoModule" / "Private" / "Second.cpp"
    first_file.parent.mkdir(parents=True)
    first_file.write_text("void FirstLayer() {}\n", encoding="utf-8")
    second_file.write_text("void SecondLayer() {}\n", encoding="utf-8")

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = []
    for trace_id, seed, rel_file, commit in (
        ("trace-first", "FirstLayer", "Source/DemoModule/Private/First.cpp", "commit-a"),
        ("trace-second", "SecondLayer", "Source/DemoModule/Private/Second.cpp", "commit-b"),
    ):
            record_query(
                skill_dir=skill_dir,
                trace_id=trace_id,
                command="source_slice",
                args=[rel_file, "1"],
                context=_context(source_root, commit=commit, branch="DEV"),
                result={"file": rel_file, "found_count": 1},
            )
            recorded.append(
                record_memory(
                    skill_dir=skill_dir,
                    trace_id=trace_id,
                    intent="explain_business_flow",
                    seed=seed,
                    context=_context(source_root, commit=commit, branch="DEV"),
                    source_root=source_root,
                    command_runner=runner,
                )
        )

    pattern_id = recorded[0]["pattern_id"]
    assert recorded[1]["pattern_id"] == pattern_id

    snapshot = snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=pattern_id)
    assert snapshot["pattern_id"] == pattern_id
    assert snapshot["subject_id"] is None
    assert snapshot["provenance_count"] == 2
    assert snapshot["commit_id"] == "commit-a,commit-b"
    assert snapshot["evidence_count"] == 2

    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        pattern_status = conn.execute("SELECT status FROM business_patterns WHERE id=?", (pattern_id,)).fetchone()
        member_count = conn.execute("SELECT COUNT(DISTINCT subject_id) FROM business_pattern_members WHERE pattern_id=?", (pattern_id,)).fetchone()
        stage_names = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT stage_name FROM business_pattern_evidence WHERE pattern_id=?",
                (pattern_id,),
            ).fetchall()
        }
        snapshot_members = {
            row[0]
            for row in conn.execute(
                "SELECT memory_id FROM memory_snapshot_members WHERE snapshot_id=?",
                (snapshot["snapshot_id"],),
            ).fetchall()
        }
    finally:
        conn.close()
    assert pattern_status == ("active",)
    assert member_count == (2,)
    assert stage_names == {"source_slice"}
    assert snapshot_members == {item["memory_id"] for item in snapshot["provenance"]}

    legacy_path = skill_dir / "memory" / "obsidian" / "patterns" / "explain_business_flow.md"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("stale english pattern", encoding="utf-8")
    rendered = render_memory(skill_dir=skill_dir, target=pattern_id)
    assert rendered["rendered_count"] == 1
    md = Path(rendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert Path(rendered["rendered_files"][0]).name == "业务流程解释模式.md"
    assert not legacy_path.exists()
    assert "# 业务流程解释模式" in md
    assert "## 模式质量" in md
    assert "状态：`低价值模式`" in md
    assert "只能当线索" in md
    assert "```mermaid" in md
    assert "查询阶段" in md
    assert "回源读取代码片段" in md
    assert "## 阶段" in md
    assert "## 业务主题" in md
    assert "FirstLayer" in md
    assert "SecondLayer" in md
    assert "commit-a" in md
    assert "commit-b" in md


def test_query_memory_pattern_starts_as_candidate_until_multiple_subjects_support_it(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Source" / "DemoModule" / "Private" / "Only.cpp"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("void OnlyLayer() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-only",
        command="source_slice",
        args=["Source/DemoModule/Private/Only.cpp", "1"],
        context=_context(source_root),
        result={"file": "Source/DemoModule/Private/Only.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-only",
        intent="explain_business_flow",
        seed="OnlyLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        status = conn.execute("SELECT status FROM business_patterns WHERE id=?", (recorded["pattern_id"],)).fetchone()
        member_count = conn.execute(
            "SELECT COUNT(DISTINCT subject_id) FROM business_pattern_members WHERE pattern_id=?",
            (recorded["pattern_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert status == ("candidate",)
    assert member_count == (1,)

    rendered = render_memory(skill_dir=skill_dir, target=recorded["pattern_id"])
    md = Path(rendered["rendered_files"][0]).read_text(encoding="utf-8")
    assert "状态：`候选模式`" in md
    assert "暂不建议直接复用" in md


def test_query_memory_render_graph_views_for_subject(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source_file = source_root / "Feature.cpp"
    source_file.write_text("void FeatureLayer() {}\n", encoding="utf-8")

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-graph-views",
        command="source_slice",
        args=["Feature.cpp", "1"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "found_count": 1},
    )
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-graph-views",
        command="source_slice",
        args=["Feature.cpp", "2"],
        context=_context(source_root),
        result={"file": "Feature.cpp", "found_count": 1},
    )

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-graph-views",
        intent="explain_business_flow",
        seed="FeatureLayer",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=recorded["subject_id"])
    attached = attach_business_flow(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        flow={
            "title": "FeatureLayer 业务流程",
            "quality_baseline": {"minimum_score": 1},
            "lanes": ["入口"],
            "nodes": [
                {
                    "id": "entry",
                    "label": "FeatureLayer 入口",
                    "lane": "入口",
                    "summary": "入口节点。",
                    "details": ["用于 business view。"],
                    "evidence": ["Feature.cpp:1"],
                }
            ],
            "edges": [],
        },
    )
    assert attached["publication_status"] == "published"

    expectations = {
        "business": ["入口 (1 节点)", "业务视图"],
        "evidence": ["Feature.cpp", "证据视图"],
        "query-path": ["回源读取代码片段 x2", "压缩后步骤", "查询路径视图"],
        "evolution": ["流程附注", "快照", "演进视图"],
    }
    for view, snippets in expectations.items():
        rendered = render_memory(skill_dir=skill_dir, target="FeatureLayer", view=view)
        assert rendered["view"] == view
        assert rendered["rendered_count"] == 1
        path = Path(rendered["rendered_files"][0])
        assert path.parent.name == view
        md = path.read_text(encoding="utf-8")
        assert "query-memory-graph-view/v1" in md
        assert "```mermaid" in md
        for snippet in snippets:
            assert snippet in md

    invalid = render_memory(skill_dir=skill_dir, target="FeatureLayer", view="bad-view")
    assert invalid["error"] == "unknown view: bad-view"


def test_query_memory_validate_detects_node_set_hash_drift(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-node-drift",
        command="query_flow",
        args=["Feature", "both"],
        context=_context(source_root),
        result={"edges": [{"source": "A", "target": "B", "edge_type": "call"}]},
    )

    def runner(command, args):
        return {"edges": [{"source": "A", "target": "B", "edge_type": "call"}]}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-node-drift",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        conn.execute(
            "UPDATE query_memory_graph SET node_set_hash=?, node_set_json=? WHERE memory_id=?",
            ("stale-node-hash", '["A"]', recorded["memory_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert validation["overall"] == "expanded"
    assert validation["freshness"]["business_path"] == "expanded"
    assert "node_set_changed" in validation["reasons"]


def test_query_memory_diff_persists_history_diff(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-diff",
        command="query_flow",
        args=["Feature", "both"],
        context=_context(source_root),
        result={"edges": [{"source": "A", "target": "B", "edge_type": "call"}]},
    )

    replacement = False

    def runner(command, args):
        target = "C" if replacement else "B"
        return {"edges": [{"source": "A", "target": target, "edge_type": "call"}]}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-diff",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    snapshot = snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=recorded["subject_id"])
    replacement = True

    diff = diff_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert diff["overall"] == "changed"
    assert diff["base_snapshot_id"] == snapshot["snapshot_id"]
    assert diff["head_snapshot_id"]
    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        row = conn.execute("SELECT base_snapshot_id, head_snapshot_id, diff_json FROM memory_diffs WHERE id=?", (diff["diff_id"],)).fetchone()
    finally:
        conn.close()
    assert row[0] == snapshot["snapshot_id"]
    assert row[1] == diff["head_snapshot_id"]
    assert "edge_set_changed" in row[2]


def test_query_memory_diff_preserves_pattern_snapshot_scope(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()
    first_file = source_root / "Source" / "DemoModule" / "Private" / "First.cpp"
    second_file = source_root / "Source" / "DemoModule" / "Private" / "Second.cpp"
    first_file.parent.mkdir(parents=True)
    first_file.write_text("void FirstLayer() {}\n", encoding="utf-8")
    second_file.write_text("void SecondLayer() {}\n", encoding="utf-8")

    def runner(command, args):
        return {"file": args[0], "line_start": int(args[1]), "found_count": 1}

    records = []
    for trace_id, seed, rel_file in (
        ("trace-pattern-diff-a", "FirstLayer", "Source/DemoModule/Private/First.cpp"),
        ("trace-pattern-diff-b", "SecondLayer", "Source/DemoModule/Private/Second.cpp"),
    ):
        record_query(
            skill_dir=skill_dir,
            trace_id=trace_id,
            command="source_slice",
            args=[rel_file, "1"],
            context=_context(source_root),
            result={"file": rel_file, "found_count": 1},
        )
        records.append(
            record_memory(
                skill_dir=skill_dir,
                trace_id=trace_id,
                intent="explain_business_flow",
                seed=seed,
                context=_context(source_root),
                source_root=source_root,
                command_runner=runner,
            )
        )

    pattern_snapshot = snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=records[0]["pattern_id"])
    diff = diff_memory(
        skill_dir=skill_dir,
        memory_id=records[0]["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    conn = sqlite3.connect(str(skill_dir / "memory" / "memory.sqlite"))
    try:
        row = conn.execute(
            "SELECT base_snapshot_id, head_snapshot_id FROM memory_diffs WHERE id=?",
            (diff["diff_id"],),
        ).fetchone()
        head_scope = conn.execute(
            "SELECT subject_id, pattern_id FROM memory_snapshots WHERE id=?",
            (diff["head_snapshot_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert row == (pattern_snapshot["snapshot_id"], diff["head_snapshot_id"])
    assert head_scope == (None, records[0]["pattern_id"])


def test_query_memory_same_size_graph_replacement_marks_changed(tmp_path):
    skill_dir = tmp_path / "Skill"
    source_root = tmp_path / "Source"
    source_root.mkdir()

    record_query(
        skill_dir=skill_dir,
        trace_id="trace-graph-replace",
        command="query_flow",
        args=["Feature", "both"],
        context=_context(source_root),
        result={"edges": [{"source": "A", "target": "B", "edge_type": "call"}]},
    )

    replacement = False

    def runner(command, args):
        target = "C" if replacement else "B"
        return {"edges": [{"source": "A", "target": target, "edge_type": "call"}]}

    recorded = record_memory(
        skill_dir=skill_dir,
        trace_id="trace-graph-replace",
        intent="explain_business_flow",
        seed="Feature",
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )
    replacement = True

    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=recorded["memory_id"],
        context=_context(source_root),
        source_root=source_root,
        command_runner=runner,
    )

    assert validation["overall"] == "changed"
    assert validation["freshness"]["business_path"] == "changed"
    assert validation["reusable_as"] == "route_only"
