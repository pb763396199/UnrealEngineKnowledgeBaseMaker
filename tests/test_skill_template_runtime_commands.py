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
        assert "query_audit.db" in content
        assert "ue5_kb.query.runtime_context" in content
        assert "ue5_kb.query.source_slice" in content
        assert "ue5_kb.core.files_fts_index" in content


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
