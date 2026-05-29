from pathlib import Path


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


def test_engine_and_plugin_impl_templates_include_runtime_commands():
    for template in ("templates/impl.py.template", "templates/impl.plugin.py.template"):
        content = _read(template)
        assert "def preflight" in content
        assert "def source_slice" in content
        assert "def search_files" in content
        assert "def query_audit" in content
        assert "--trace-id" in content
        assert "--allow-stale" in content
        assert "--no-audit" in content
        assert "UE5KB_NO_AUDIT" in content
        assert "query_audit.db" in content
        assert "ue5_kb.query.runtime_context" in content
        assert "ue5_kb.query.source_slice" in content
        assert "ue5_kb.core.files_fts_index" in content
        assert "_UNRESOLVED_KB_PATH" in content
        assert "kb_resolution_failed" in content
        assert "_stale_gate_result" in content
        assert "ambiguous_function_implementation" in content
        assert "signature_hint" in content


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
    assert '"preflight", "query_audit", "status", "check_freshness", "get_kb_info"' in content


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
        assert "--trace-id" in content


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
