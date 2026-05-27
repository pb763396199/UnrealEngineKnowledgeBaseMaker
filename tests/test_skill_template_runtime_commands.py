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
