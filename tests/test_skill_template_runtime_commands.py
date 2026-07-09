from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _render_impl_template(path: str) -> str:
    content = _read(path)
    variables = {
        "ENGINE_VERSION": "5.3",
        "KB_VERSION": "2.13.0",
        "TOOL_VERSION": "test",
        "CREATED_AT": "2026-01-01T00:00:00",
        "LAST_UPDATED": "2026-01-01T00:00:00",
        "KB_PATH": "C:\\Temp\\KnowledgeBase",
        "SKILL_PATH": "C:\\Temp\\Skill",
        "PLUGIN_NAME": "SmokePlugin",
        "PLUGIN_VERSION": "1.0",
    }
    for key, value in variables.items():
        content = content.replace(f"{{{key}}}", value)
    return content.replace("{{", "{").replace("}}", "}")


def _load_rendered_impl_namespace(template: str, tmp_path: Path) -> dict:
    kb_path = tmp_path / "KnowledgeBase"
    skill_path = tmp_path / "Skill"
    source_root = tmp_path / "SourceRoot"
    (kb_path / "global_index").mkdir(parents=True)
    skill_path.mkdir()
    source_root.mkdir()

    rendered = _render_impl_template(template).replace("C:\\Temp\\KnowledgeBase", str(kb_path))
    rendered = rendered.replace("C:\\Temp\\Skill", str(skill_path))
    namespace = {"__file__": str(skill_path / "impl.py"), "__name__": "rendered_skill_test"}
    exec(compile(rendered, template.replace(".template", ""), "exec"), namespace)
    namespace["SOURCE_ROOT"] = source_root
    namespace["KB_PATH"] = kb_path
    return namespace


def _prepare_static_graph_fixture(namespace: dict) -> None:
    from ue5_kb.core.class_index import ClassIndex
    from ue5_kb.core.function_index import FunctionIndex
    from ue5_kb.core.symbol_reference_index import SymbolReferenceIndex

    kb_path = namespace["KB_PATH"]
    source_root = namespace["SOURCE_ROOT"]
    source_file = source_root / "Source" / "Mod" / "Private" / "Thing.cpp"
    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "void FThing::Caller()\n"
        "{\n"
        "    Target();\n"
        "    FTextureFragment Fragment;\n"
        "}\n"
        "\n"
        "void FThing::Target()\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )
    feature_file = source_root / "Source" / "Mod" / "Private" / "Feature.cpp"
    feature_file.write_text(
        "void CreateFeatureLayer()\n"
        "{\n"
        "    auto Manager = MakeShared<FFeaturePayloadManager>();\n"
        "    if (Settings.bUseFeaturePrefab)\n"
        "    {\n"
        "        RegisterProducer();\n"
        "    }\n"
        "}\n"
        "\n"
        "void RegisterProducer()\n"
        "{\n"
        "    FMarkerProducer Producer;\n"
        "    AddDataLayer(Producer);\n"
        "    GetDependency();\n"
        "    LoadAsset();\n"
        "    UBudgetSubsystem* BudgetSubsystem = GetSubsystem<UBudgetSubsystem>();\n"
        "    Refresh();\n"
        "}\n"
        "\n"
        "void AddDataLayer() {}\n"
        "void GetDependency() {}\n"
        "void LoadAsset() {}\n"
        "void Refresh() {}\n",
        encoding="utf-8",
    )

    func_idx = FunctionIndex(str(kb_path / "global_index" / "function_index.db"))
    try:
        func_idx.add_functions_batch([
            {
                "name": "Caller",
                "module": "Mod",
                "class_name": "FThing",
                "return_type": "void",
                "parameters": [],
                "signature": "void FThing::Caller()",
                "file_path": "Source/Mod/Public/Thing.h",
                "line_number": 10,
                "impl_file_path": "Source/Mod/Private/Thing.cpp",
                "impl_line_number": 1,
            },
            {
                "name": "Target",
                "module": "Mod",
                "class_name": "FThing",
                "return_type": "void",
                "parameters": [],
                "signature": "void FThing::Target()",
                "file_path": "Source/Mod/Public/Thing.h",
                "line_number": 11,
                "impl_file_path": "Source/Mod/Private/Thing.cpp",
                "impl_line_number": 6,
            },
            {
                "name": "CreateFeatureLayer",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void CreateFeatureLayer()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 20,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 20,
            },
            {
                "name": "RegisterProducer",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void RegisterProducer()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 21,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 30,
            },
            {
                "name": "AddDataLayer",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void AddDataLayer()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 22,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 40,
            },
            {
                "name": "GetDependency",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void GetDependency()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 23,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 44,
            },
            {
                "name": "LoadAsset",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void LoadAsset()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 24,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 48,
            },
            {
                "name": "Refresh",
                "module": "Mod",
                "class_name": "",
                "return_type": "void",
                "parameters": [],
                "signature": "void Refresh()",
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 25,
                "impl_file_path": "Source/Mod/Private/Feature.cpp",
                "impl_line_number": 52,
            },
        ])
    finally:
        func_idx.close()

    class_idx = ClassIndex(str(kb_path / "global_index" / "class_index.db"))
    try:
        class_idx.add_classes_batch([
            {
                "name": "FTextureFragment",
                "module": "Mod",
                "namespace": "",
                "parent_classes": ["FOutputFragment"],
                "interfaces": [],
                "file_path": "Source/Mod/Public/TextureFragment.h",
                "line_number": 38,
                "is_uclass": True,
                "is_struct": True,
                "is_interface": False,
                "is_blueprintable": True,
                "method_count": 5,
                "property_count": 21,
            },
            {
                "name": "FFeatureLayer",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 60,
                "is_uclass": False,
                "is_struct": False,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
            {
                "name": "FFeaturePayloadManager",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 61,
                "is_uclass": False,
                "is_struct": False,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
            {
                "name": "FMarkerProducer",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 62,
                "is_uclass": False,
                "is_struct": False,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
            {
                "name": "FFeatureSettings",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 63,
                "is_uclass": False,
                "is_struct": True,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
            {
                "name": "UBudgetSubsystem",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 64,
                "is_uclass": True,
                "is_struct": False,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
            {
                "name": "FPlainData",
                "module": "Mod",
                "namespace": "",
                "parent_classes": [],
                "interfaces": [],
                "file_path": "Source/Mod/Public/Feature.h",
                "line_number": 65,
                "is_uclass": False,
                "is_struct": True,
                "is_interface": False,
                "is_blueprintable": False,
                "method_count": 0,
                "property_count": 0,
            },
        ])
    finally:
        class_idx.close()

    ref_idx = SymbolReferenceIndex(str(kb_path / "global_index" / "symbol_reference_index.db"))
    try:
        ref_idx._insert_batch([
            (
                "Caller", "FThing", "Mod", "Source/Mod/Public/Thing.h", 10,
                "Target", "function", "FThing", "Mod", "Source/Mod/Public/Thing.h", 11,
                "call", "Source/Mod/Private/Thing.cpp", 3, "Target();", "resolved", 1,
            ),
            (
                "Caller", "FThing", "Mod", "Source/Mod/Public/Thing.h", 10,
                "FTextureFragment", "class", "", "Mod",
                "Source/Mod/Public/TextureFragment.h", 38,
                "type_reference", "Source/Mod/Private/Thing.cpp", 4,
                "FTextureFragment Fragment;", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "FFeatureLayer", "class", "", "Mod", "Source/Mod/Public/Feature.h", 60,
                "type_reference", "Source/Mod/Private/Feature.cpp", 20,
                "return MakeShared<FFeatureLayer>(Manager);", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "FFeaturePayloadManager", "class", "", "Mod", "Source/Mod/Public/Feature.h", 61,
                "type_reference", "Source/Mod/Private/Feature.cpp", 21,
                "TSharedRef<FFeaturePayloadManager> Manager = MakeShared<FFeaturePayloadManager>();", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "FFeaturePayloadManager", "class", "", "Mod", "Source/Mod/Public/Feature.h", 61,
                "type_reference", "Source/Mod/Private/Feature.cpp", 22,
                "FFeaturePayloadManager* CurrentManager = Manager.Get();", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "FFeatureSettings", "class", "", "Mod", "Source/Mod/Public/Feature.h", 63,
                "type_reference", "Source/Mod/Private/Feature.cpp", 23,
                "if (Settings.bUseFeaturePrefab)", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "FPlainData", "class", "", "Mod", "Source/Mod/Public/Feature.h", 65,
                "type_reference", "Source/Mod/Private/Feature.cpp", 24,
                "FPlainData Plain;", "resolved", 1,
            ),
            (
                "CreateFeatureLayer", "", "Mod", "Source/Mod/Public/Feature.h", 20,
                "RegisterProducer", "function", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "call", "Source/Mod/Private/Feature.cpp", 25,
                "RegisterProducer();", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "FMarkerProducer", "class", "", "Mod", "Source/Mod/Public/Feature.h", 62,
                "type_reference", "Source/Mod/Private/Feature.cpp", 31,
                "FMarkerProducer Producer;", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "AddDataLayer", "function", "", "Mod", "Source/Mod/Public/Feature.h", 22,
                "call", "Source/Mod/Private/Feature.cpp", 32,
                "AddDataLayer(Producer);", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "GetDependency", "function", "", "Mod", "Source/Mod/Public/Feature.h", 23,
                "call", "Source/Mod/Private/Feature.cpp", 33,
                "GetDependency();", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "LoadAsset", "function", "", "Mod", "Source/Mod/Public/Feature.h", 24,
                "call", "Source/Mod/Private/Feature.cpp", 34,
                "LoadAsset();", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "UBudgetSubsystem", "class", "", "Mod", "Source/Mod/Public/Feature.h", 64,
                "type_reference", "Source/Mod/Private/Feature.cpp", 35,
                "UBudgetSubsystem* BudgetSubsystem = GetSubsystem<UBudgetSubsystem>();", "resolved", 1,
            ),
            (
                "RegisterProducer", "", "Mod", "Source/Mod/Public/Feature.h", 21,
                "Refresh", "function", "", "Mod", "Source/Mod/Public/Feature.h", 25,
                "call", "Source/Mod/Private/Feature.cpp", 36,
                "Refresh();", "resolved", 1,
            ),
        ])
    finally:
        ref_idx.close()

    namespace["_function_index_cache"] = None
    namespace["_class_index_cache"] = None
    namespace["_symbol_reference_index_cache"] = None


def _expected_evidence_hash(evidence_without_hash: dict) -> str:
    payload = json.dumps(evidence_without_hash, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_engine_and_plugin_impl_templates_include_runtime_commands():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "def preflight" in content
        assert "def source_slice" in content
        assert "def search_files" in content
        assert "def query_audit" in content
        assert "def query_audit_report" in content
        assert "def query_memory_record" in content
        assert "def query_memory_auto_capture" in content
        assert "def query_memory_search" in content
        assert "def query_memory_validate" in content
        assert "def query_memory_replay" in content
        assert "def query_memory_diff" in content
        assert "def query_memory_promote" in content
        assert "def query_memory_subjects" in content
        assert "def query_memory_negative_hints" in content
        assert "def query_memory_snapshot" in content
        assert "def query_memory_render" in content
        assert "promotion_validation" in content
        assert "query_memory_validate(memory_id)" in content
        assert "--trace-id" in content
        assert "--allow-stale" in content
        assert "--no-audit" in content
        assert "UE5KB_NO_AUDIT" in content
        assert "memory.sqlite" in content
        assert "ue5_kb.query.query_memory" in content
        assert "ue5_kb.query.runtime_context" in content
        assert "ue5_kb.query.source_slice" in content
        assert "ue5_kb.core.files_fts_index" in content
        assert "_UNRESOLVED_KB_PATH" in content
        assert "kb_resolution_failed" in content
        assert "_stale_gate_result" in content
        assert "ambiguous_function_implementation" in content
        assert "signature_hint" in content


def test_engine_template_memory_command_runner_uses_engine_run_command_signature(tmp_path):
    namespace = _load_rendered_impl_namespace("templates/impl.py.template", tmp_path)
    calls = []

    def fake_run_command(command, args, allow_stale=False):
        calls.append((command, args, allow_stale))
        return {"ok": True, "command": command}

    namespace["_run_command"] = fake_run_command
    result = namespace["_memory_command_runner"]("source_slice", ["Feature.cpp", "1"])

    assert result == {"ok": True, "command": "source_slice"}
    assert calls == [("source_slice", ["Feature.cpp", "1"], True)]


def test_rendered_impl_templates_query_memory_auto_capture_promotes_active_session(tmp_path):
    """端到端验证：不传 --trace-id 的连续查询自动归并为同一 trace，
    然后 query_memory_auto_capture() 不传任何参数也能把它沉淀为可复用路线。"""
    from ue5_kb.query.query_audit import record_query

    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        namespace = _load_rendered_impl_namespace(template, tmp_path / template.replace("/", "_"))
        skill_dir = namespace["SKILL_DIR"]

        first_trace = record_query(
            skill_dir=skill_dir,
            trace_id=None,
            command="query_class_info",
            args=["AFeatureActor"],
            context={"data_trust": "fresh"},
            result={"found_count": 1},
        )
        second_trace = record_query(
            skill_dir=skill_dir,
            trace_id=None,
            command="query_function_info",
            args=["AFeatureActor"],
            context={"data_trust": "fresh"},
            result={"found_count": 1},
        )
        assert first_trace == second_trace

        namespace["_run_command"] = lambda command, args, **kwargs: {"found_count": 1}
        captured = namespace["query_memory_auto_capture"]()

        assert captured["schema"] == "query-memory-auto-capture/v1"
        assert captured["trace_id"] == first_trace
        assert captured["seed"] == "AFeatureActor"
        assert captured["intent"] == "auto_capture"
        assert captured.get("memory_id")


def test_engine_template_does_not_advertise_read_only_without_write_commands():
    content = _read("templates/impl.py.template")
    assert "--read-only" not in content
    assert "UE5KB_READ_ONLY" not in content
    assert "preflight/update" not in content
    assert "regenerate/rebuild the engine KB" in content


def test_plugin_template_keeps_read_only_for_write_command_blocking():
    content = _read("templates/impl.plugin.py.template")
    assert "--read-only" in content
    assert "UE5KB_READ_ONLY" in content


def test_plugin_template_refreshes_runtime_paths_after_ensure_fresh():
    content = _read("templates/impl.plugin.py.template")
    assert "def _refresh_runtime_paths" in content
    assert "KB_PATH = _resolve_kb_path()" in content
    assert "SOURCE_ROOT = _resolve_source_root()" in content
    assert "_refresh_runtime_paths()" in content


def test_impl_templates_do_not_let_audit_failure_break_queries():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "except Exception:\n        return resolve_trace_id(trace_id)" in content


def test_plugin_template_read_only_blocks_write_commands_but_allows_maintenance_status():
    content = _read("templates/impl.plugin.py.template")
    assert "_write_command" in content
    assert "Command '{command}' is disabled in read-only mode" in content
    assert '"ensure_fresh", "init", "register", "update"' in content
    assert '"preflight", "query_audit", "query_audit_report", "status", "check_freshness", "get_kb_info"' in content
    stale_gate_segment = content[
        content.index("def _command_requires_fresh"):
        content.index("def _write_command")
    ]
    assert '"query_memory_search"' in stale_gate_segment
    assert "query_memory_validate" not in stale_gate_segment
    assert "query_memory_replay" not in stale_gate_segment
    write_command_segment = content[
        content.index("def _write_command"):
        content.index("def _stale_gate_result")
    ]
    assert "query_audit_report" not in write_command_segment
    assert "query_memory_record" in write_command_segment
    assert "query_memory_validate" in write_command_segment
    assert "query_memory_diff" in write_command_segment
    assert "query_memory_promote" in write_command_segment
    assert "query_memory_snapshot" in write_command_segment
    assert "query_memory_render" in write_command_segment
    assert "query_memory_subjects" not in write_command_segment
    assert "query_memory_negative_hints" not in write_command_segment
    assert "query_memory_replay" not in write_command_segment


def test_impl_templates_fail_closed_when_registry_resolution_fails():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "falling back to default" not in content
        assert "registry 存在但异常时不回退旧 KB" in content
        assert "return _UNRESOLVED_KB_PATH" in content


def test_rendered_impl_templates_compile_after_brace_replacement():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        rendered = _render_impl_template(template)
        compile(rendered, template.replace(".template", ""), "exec")


def test_engine_and_plugin_skill_templates_require_preflight_and_new_commands():
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        assert "源码问答前先执行 preflight" in content
        assert "preflight" in content
        assert "source_slice" in content
        assert "search_files" in content
        assert "query_audit" in content
        assert "query_audit_report" in content
        assert "query_memory_record" in content
        assert "query_memory_validate" in content
        assert "query_memory_replay" in content
        assert "query_memory_subjects" in content
        assert "query_memory_negative_hints" in content
        assert "query_memory_snapshot" in content
        assert "query_memory_render" in content
        assert "query_memory_render_site" in content
        assert "query_memory_auto_capture" in content
        assert "--trace-id" in content


def test_engine_and_plugin_skill_templates_document_business_flow_trigger_rules():
    """SKILL.md 必须明确写出"何时主动归纳业务流程图"的显式/隐式触发规则，
    不能让 agent 只能靠猜或每次都问用户。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        assert "何时主动归纳业务流程图" in content
        assert "显式触发" in content
        assert "隐式信号" in content
        assert "决策规则" in content
        assert "S1" in content and "S2" in content and "S3" in content
        assert "query_memory_attach_flow" in content


def test_engine_and_plugin_impl_templates_reference_business_flow_trigger_rules_in_help():
    """impl.py CLI 的 --help 输出也要提一句触发时机，不能只在 SKILL.md 里才找得到。"""
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "何时主动归纳业务流程图" in content
        assert "SKILL.md" in content


def test_skill_templates_description_covers_compile_debug_edit_review():
    """description 字段必须覆盖 compile/debug/edit/review 场景，不能只写"询问源码问题"。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        desc_line = next(
            (ln for ln in content.splitlines() if ln.startswith("description:")), None
        )
        assert desc_line is not None, f"{template}: 缺少 description 字段"
        assert "编译" in desc_line, f"{template}: description 未覆盖编译场景"
        assert "修改" in desc_line or "审查" in desc_line, f"{template}: description 未覆盖代码修改/审查场景"
        assert "调试" in desc_line, f"{template}: description 未覆盖调试场景"
        assert "KB gate" in desc_line, f"{template}: description 未写 KB gate 要求"


def test_skill_templates_when_to_use_covers_compile_and_edit_scenarios():
    """'何时使用此技能'节必须包含编译/修改/审查/调试四个场景关键词。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        assert "编译错误" in content, f"{template}: 缺少'编译错误'触发场景"
        assert "代码修改" in content, f"{template}: 缺少'代码修改'触发场景"
        assert "代码审查" in content or "审查" in content, f"{template}: 缺少'审查'触发场景"
        assert "调试" in content, f"{template}: 缺少'调试'触发场景"


def test_skill_templates_enforce_kb_gate_before_grep_read_file():
    """模板必须明确要求 KB gate 在 Glob/Grep/read_file 之前，且 miss 后才可降级。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        # 必须写 "不要先用 Glob/Grep/read_file" 或等价约束
        assert "Glob/Grep/read_file" in content, f"{template}: 未明确禁止先用 Glob/Grep/read_file"
        # 必须写 KB miss 降级条件
        assert "KB miss" in content or "明确标注" in content, (
            f"{template}: 未说明 KB miss 后才可降级"
        )
        # 必须写 KB gate 顺序
        assert "KB gate" in content, f"{template}: 缺少 KB gate 强制顺序说明"


def test_skill_templates_document_shared_store_and_provider_adapters():
    """生成的 Skill 必须说明单份 KB + 跨 Agent adapter 约定。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        assert "跨 Agent 部署约定" in content
        assert "原始 KB 只应有一份" in content
        assert "Claude Code / OpenCode" in content
        assert "Codex / VS Code Copilot" in content
        assert "不要复制 `variants/`" in content
        assert "不要手写或依赖" in content
        assert "Windows 控制台可能不是 UTF-8" in content


def test_skill_templates_document_search_files_line_anchors():
    """search_files 是静态证据入口，模板必须说明返回行号锚点。"""
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        assert "搜索源码文件全文索引，返回行号锚点" in content


def test_impl_templates_query_function_info_has_static_resolution_state():
    """query_function_info 必须使用确定性限定名解析，不引入语义问答。"""
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        segment = content[
            content.index("def _split_qualified_function_name"):
            content.index("def search_classes")
        ]
        assert "def _split_qualified_function_name" in content
        assert 'rsplit("::", 1)' in content
        assert "def _normalize_function_result" in content
        assert "def _function_resolution_state" in content
        assert "def _dedupe_function_results" in content
        assert '"resolution_state"' in content
        assert '"candidate_count"' in content
        lowered = segment.lower()
        assert "llm" not in lowered
        assert "rag" not in lowered
        assert "embedding" not in lowered


def test_impl_templates_include_static_graph_commands_without_nl_query():
    commands = [
        "symbol_reference_report",
        "symbol_evidence_bundle",
        "code_flow_index",
        "query_static_closure",
        "query_flow",
        "trace_business_flow",
        "trace_flow_path",
    ]
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        for command in commands:
            assert f"def {command}" in content
            assert f'command == "{command}"' in content
        assert "query(question)" not in content
        assert "explain_business_flow" not in content
        assert "explain_symbol_flow" not in content


def test_rendered_impl_static_graph_commands_execute_with_fixture(tmp_path):
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        namespace = _load_rendered_impl_namespace(template, tmp_path / template.replace("/", "_"))
        _prepare_static_graph_fixture(namespace)

        report = namespace["symbol_reference_report"]("Target", 10, "resolved")
        assert report["counts"] == {"callers": 1, "callees": 0, "references": 1}
        assert report["callers"][0]["resolution_state"] == "resolved"
        assert report["callers"][0]["occurrence_line"] == 3

        qualified_report = namespace["symbol_reference_report"]("FThing::Target", 10, "resolved")
        assert qualified_report["counts"] == {"callers": 1, "callees": 0, "references": 1}
        assert qualified_report["callers"][0]["target_class"] == "FThing"
        assert qualified_report["references"][0]["target_symbol"] == "Target"

        qualified_refs = namespace["query_symbol_references"]("FThing::Target", 10, "resolved")
        assert qualified_refs["found_count"] == 1
        assert qualified_refs["results"][0]["target_class"] == "FThing"

        bundle = namespace["symbol_evidence_bundle"]("Target", 10, "resolved")
        assert bundle["candidate_count"] == 1
        assert bundle["declaration_spans"] == [
            {"file": "Source/Mod/Public/Thing.h", "line": 11, "class": "FThing", "module": "Mod"}
        ]
        assert bundle["implementation_spans"] == [
            {"file": "Source/Mod/Private/Thing.cpp", "line": 6, "class": "FThing", "module": "Mod"}
        ]
        assert bundle["reference_spans"] == [
            {
                "file": "Source/Mod/Private/Thing.cpp",
                "line": 3,
                "relation_type": "call",
                "resolution_state": "resolved",
            }
        ]
        evidence = bundle["source_slices"][0]
        expected_without_hash = dict(evidence)
        evidence_hash = expected_without_hash.pop("evidence_hash")
        assert evidence_hash == _expected_evidence_hash(expected_without_hash)
        assert bundle["evidence_hashes"] == [evidence_hash]
        assert "Target();" in evidence["source_slice"]["content"]

        qualified_bundle = namespace["symbol_evidence_bundle"]("FThing::Target", 10, "resolved")
        assert qualified_bundle["candidate_count"] == 1
        assert qualified_bundle["reference_spans"] == [
            {
                "file": "Source/Mod/Private/Thing.cpp",
                "line": 3,
                "relation_type": "call",
                "resolution_state": "resolved",
            }
        ]

        flow_index = namespace["code_flow_index"](10, "resolved")
        assert flow_index["materialized"] is False
        assert flow_index["edge_count"] >= 2
        assert "symbol_reference_index.call" in {edge["rule_id"] for edge in flow_index["edges"]}

        flow = namespace["query_flow"]("Caller", "out", "call", 1, 10, "resolved")
        assert flow["edge_count"] == 1
        assert flow["edges"][0]["source"] == "FThing::Caller"
        assert flow["edges"][0]["target"] == "FThing::Target"

        path = namespace["trace_flow_path"]("Caller", "Target", 2, 10, "resolved")
        assert path["found"] is True
        assert path["depth"] == 1
        assert path["path"][0]["edge_type"] == "call"

        closure = namespace["query_static_closure"]("FeatureLayer", 3, 80, "resolved")
        assert closure["schema"] == "static-closure/v1"
        assert closure["edge_source"] == "symbol_reference_index.db"
        assert closure["semantic_edge_source"] == "derived_static_rules"
        assert closure["materialized"] is False
        assert closure["zero_reason"] is None
        assert closure["closure_status"] == "partial"
        assert closure["coverage"]["closed"] is False
        assert closure["closure_validation"]["status"] == "FAIL"
        assert closure["closure_validation"]["static_only"] is True
        assert closure["closure_validation"]["llm_used"] is False
        assert closure["closure_validation"]["rag_used"] is False
        assert closure["closure_validation"]["vector_used"] is False
        assert closure["closure_validation"]["source_slice_is_semantic_edge"] is False
        assert closure["closure_validation"]["files_fts_is_semantic_edge"] is False
        assert closure["seed_binding"] == "unique_type_candidate"
        assert closure["effective_seed_nodes"] == ["FFeatureLayer"]
        assert closure["coverage"]["static_only"] is True
        assert closure["next_static_commands"] == [
            "symbol_evidence_bundle FFeatureLayer 20 resolved",
            "query_flow FFeatureLayer both call,type_reference 3 80 resolved",
        ]
        assert closure["next_static_command_objects"][1] == {
            "command": "query_flow",
            "args": ["FFeatureLayer", "both", "call,type_reference", "3", "80", "resolved"],
            "argv": "query_flow FFeatureLayer both call,type_reference 3 80 resolved",
        }
        recommended_args = closure["next_static_command_objects"][1]["args"]
        recommended_flow = namespace["query_flow"](
            recommended_args[0],
            recommended_args[1],
            recommended_args[2],
            int(recommended_args[3]),
            int(recommended_args[4]),
            recommended_args[5],
        )
        assert "error" not in recommended_flow
        assert recommended_flow["seed"] == "FFeatureLayer"

        business_trace = namespace["trace_business_flow"]("FeatureLayer", 3, 80, "resolved", 6)
        assert business_trace["schema"] == "business-flow-trace/v1"
        assert business_trace["effective_seed"] == "FFeatureLayer"
        assert business_trace["static_only"] is True
        assert business_trace["llm_used"] is False
        assert business_trace["rag_used"] is False
        assert business_trace["vector_used"] is False
        assert business_trace["script_call_equivalent_count"] == 5 + len(business_trace["evidence_slices"])
        assert business_trace["flow_summary"]["edge_count"] > 0
        assert business_trace["automation_score"]["score_kind"] == "static_evidence_density"
        assert business_trace["automation_score"]["score_is_acceptance_gate"] is False
        assert business_trace["automation_score"]["status"] == "REVIEW_ONLY"
        assert business_trace["closure_validation"]["status"] == "REVIEW_ONLY"
        assert business_trace["closure_validation"]["materialized"] is True
        assert business_trace["closure_validation"]["materialized_scope"] == "trace_business_flow_result"
        assert business_trace["closure_validation"]["is_complete_business_proof"] is False
        assert business_trace["closure_validation"]["must_not_be_used_as_acceptance_gate"] is True
        assert business_trace["closure_validation"]["source_slice_is_semantic_edge"] is False
        assert business_trace["closure_validation"]["evidence_category_markers_are_semantic_edges"] is False
        assert business_trace["closure_validation"]["upstream_truncated"] is False
        assert business_trace["coverage"]["closed"] is False
        assert business_trace["coverage"]["closed_kind"] == "evidence_snapshot_not_business_closure"
        assert business_trace["coverage"]["is_acceptance_gate"] is False
        assert business_trace["coverage"]["formal_semantic_closure"] is False
        assert business_trace["underlying_static_closure_validation"]["status"] == "FAIL"
        assert business_trace["internal_steps"][0]["command"] == "resolve_seed"
        assert business_trace["internal_steps"][4]["command"] == "source_slice"
        assert business_trace["internal_steps"][4]["repeat"] == len(business_trace["evidence_slices"])
        assert business_trace["evidence_slices"]
        assert all(item["source_slice"] is not None for item in business_trace["evidence_slices"])
        assert "flowchart TD" in business_trace["mermaid"]
        assert any(item["symbol"] == "FFeaturePayloadManager" for item in business_trace["frontier"])

        categories = closure["coverage"]["categories"]
        for category in [
            "entry",
            "creates",
            "owns",
            "registers",
            "depends_on",
            "branches_on",
            "loads",
            "sinks_to",
            "lifecycle",
            "references_type",
        ]:
            assert categories[category] > 0, category
        semantic_types = {edge["semantic_edge_type"] for edge in closure["semantic_edges"]}
        assert "creates" in semantic_types
        assert "registers" in semantic_types
        assert any(edge["target"] == "FFeaturePayloadManager" for edge in closure["semantic_edges"])
        assert any(edge["target"] == "UBudgetSubsystem" for edge in closure["semantic_edges"])

        seed = namespace["resolve_seed"]("FTextureFragment", 10)
        assert seed["resolution_state"] == "struct"
        assert seed["candidate_count"] == 1
        assert seed["candidates"][0]["kind"] == "struct"

        type_bundle = namespace["symbol_evidence_bundle"]("FTextureFragment", 10, "resolved")
        assert type_bundle["candidate_count"] == 1
        assert type_bundle["type_spans"][0]["symbol"] == "FTextureFragment"
        assert type_bundle["declaration_spans"][0]["file"] == "Source/Mod/Public/TextureFragment.h"
        assert type_bundle["reference_spans"][0]["relation_type"] == "type_reference"

        empty_flow = namespace["query_flow"]("FTextureFragment", "both", "call", 1, 10, "resolved")
        assert empty_flow["edge_count"] == 0
        assert empty_flow["zero_reason"] == "seed_is_type_but_current_graph_has_no_type_node_edges"
        assert empty_flow["matched_seed_nodes"] == ["FTextureFragment"]

        miss_flow = namespace["query_flow"]("NoSuchSeed", "both", "call", 1, 10, "all")
        assert miss_flow["edge_count"] == 0
        assert miss_flow["zero_reason"] == "seed_not_found"


def test_trace_business_flow_fails_when_underlying_flow_hits_limit(tmp_path):
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        namespace = _load_rendered_impl_namespace(template, tmp_path / template.replace("/", "_limit"))
        _prepare_static_graph_fixture(namespace)

        business_trace = namespace["trace_business_flow"]("FeatureLayer", 3, 2, "resolved", 2)
        assert business_trace["flow_summary"]["edge_count"] == 2
        assert business_trace["closure_validation"]["status"] == "FAIL"
        assert business_trace["closure_validation"]["upstream_truncated"] is True
        assert "underlying_static_traversal_hit_limit" in business_trace["closure_validation"]["reasons"]


def test_rendered_impl_source_slice_accepts_numeric_radius_compatibility(tmp_path):
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        namespace = _load_rendered_impl_namespace(template, tmp_path / template.replace("/", "_"))
        parsed = namespace["_parse_source_slice_cli_args"]([
            "Source/Mod/Private/Thing.cpp",
            "42",
            "17",
            "90",
            "5000",
        ])
        assert parsed == ("Source/Mod/Private/Thing.cpp", 42, "context", 17, 90, 5000)

        explicit = namespace["_parse_source_slice_cli_args"]([
            "Source/Mod/Private/Thing.cpp",
            "42",
            "function",
            "9",
        ])
        assert explicit == ("Source/Mod/Private/Thing.cpp", 42, "function", 9, 200, 20000)


def test_skill_templates_document_static_graph_commands():
    commands = [
        "symbol_reference_report",
        "symbol_evidence_bundle",
        "code_flow_index",
        "query_static_closure",
        "query_flow",
        "trace_business_flow",
        "trace_flow_path",
        "query_audit_report",
        "query_memory_record",
        "query_memory_search",
        "query_memory_validate",
        "query_memory_replay",
        "query_memory_diff",
        "query_memory_promote",
        "query_memory_subjects",
        "query_memory_negative_hints",
        "query_memory_snapshot",
        "query_memory_render",
    ]
    for template in ("templates/skill.md.template", "templates/skill.plugin.md.template"):
        content = _read(template)
        for command in commands:
            assert command in content
        assert "静态" in content
        assert "formal_semantic_closure" in content
        assert "不得作为“完整业务逻辑/一查到底”的验收门" in content
        assert "query(question)" not in content


def test_generic_templates_and_docs_avoid_project_specific_examples():
    """通用模板和入门文档不能固化某个项目/插件的业务名。"""
    banned = [
        "AesWorld",
        "FEarthTexture",
        "EarthModeler",
        "RoadLayer",
    ]
    paths = [
        "templates/impl.py.template",
        "templates/impl.plugin.py.template",
        "templates/skill.md.template",
        "templates/skill.plugin.md.template",
        "README.md",
        "QUICK_START.md",
        "docs/CONTEXT_OPTIMIZATION.md",
        "ue5_kb/cli.py",
        "ue5_kb/branch_manager.py",
    ]
    for path in paths:
        content = _read(path)
        for token in banned:
            assert token not in content, f"{path} should not contain project-specific token {token}"


def test_impl_templates_expose_seed_resolution_and_query_audit_limit_rules():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "def resolve_seed" in content
        assert "def _split_qualified_symbol" in content
        assert 'command == "resolve_seed"' in content
        assert "zero_reason" in content
        assert "query_audit --limit requires a value" in content
        assert "len(args) == 1 and args[0].isdigit()" in content
        assert 'command == "query_audit_report"' in content
        assert 'command == "query_memory_record"' in content
        assert 'command == "query_memory_validate"' in content
        stale_end = content.index("def _write_command") if "def _write_command" in content else content.index("def _stale_gate_result")
        stale_gate_segment = content[
            content.index("def _command_requires_fresh"):
            stale_end
        ]
        assert '"query_memory_search"' in stale_gate_segment
        assert "query_memory_validate" not in stale_gate_segment
        assert "query_memory_replay" not in stale_gate_segment
        assert 'cli_args[0] in ("-h", "--help", "help")' in content
        assert "_print_usage(0)" in content


def test_plugin_skill_template_documents_resolution_state_not_confidence():
    content = _read("templates/skill.plugin.md.template")
    assert "[resolution_state=resolved]" in content
    assert "[confidence=resolved]" not in content
    assert "兼容旧 `confidence` 参数" in content

    impl_content = _read("templates/impl.plugin.py.template")
    assert "[resolution_state=resolved|all|ambiguous]" in impl_content
    assert "[confidence=resolved|all|ambiguous]" not in impl_content


def test_plugin_template_call_graph_outputs_resolution_state_alias():
    """调用/引用图命令保留 confidence 兼容字段，同时输出 resolution_state。"""
    content = _read("templates/impl.plugin.py.template")
    segment = content[
        content.index("def query_callees"):
        content.index("def _parse_optional_class_limit_confidence")
    ]
    assert segment.count('"confidence": confidence') == 3
    assert segment.count('"resolution_state": confidence') == 3


def test_rendered_plugin_skill_template_does_not_escape_error_json_example():
    content = _read("templates/skill.plugin.md.template")
    variables = {
        "PLUGIN_NAME": "SmokePlugin",
        "PLUGIN_VERSION": "1.0",
        "KB_VERSION": "2.13.0",
        "TOOL_VERSION": "test",
        "SKILL_PATH": "C:\\Temp\\Skill",
    }
    for key, value in variables.items():
        content = content.replace(f"{{{key}}}", value)

    assert '{{"error"' not in content
    assert "}}" not in content
    assert '`{"error": "未找到..."}`' in content
