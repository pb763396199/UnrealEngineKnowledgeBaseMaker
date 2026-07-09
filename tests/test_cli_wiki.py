"""测试 `ue5kb wiki list` / `ue5kb wiki open` 命令。"""
from pathlib import Path

from click.testing import CliRunner

from ue5_kb.cli import cli


def _make_fake_skill(root: Path, name: str, *, with_memory: bool = False) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "impl.py").write_text("# fake impl.py\n", encoding="utf-8")
    if with_memory:
        from ue5_kb.query.query_memory import list_subjects

        # 调用一次只读查询即可触发 memory.sqlite 的创建 + schema 初始化
        list_subjects(skill_dir=skill_dir, limit=1)
    return skill_dir


def test_wiki_list_empty_root(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "list", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "没有找到任何" in result.output


def test_wiki_list_shows_skills_and_memory_status(tmp_path):
    _make_fake_skill(tmp_path, "no-memory-kb", with_memory=False)
    _make_fake_skill(tmp_path, "with-memory-kb", with_memory=True)

    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "list", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "no-memory-kb" in result.output
    assert "with-memory-kb" in result.output


def test_wiki_list_ignores_non_skill_dirs(tmp_path):
    (tmp_path / "not_a_skill").mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "list", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "not_a_skill" not in result.output
    assert "没有找到任何" in result.output


def test_wiki_open_missing_skill_reports_error(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "open", "does-not-exist", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "未找到 Skill" in result.output


def test_wiki_open_without_memory_reports_hint(tmp_path):
    _make_fake_skill(tmp_path, "empty-kb", with_memory=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "open", "empty-kb", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0
    assert "还没有任何 memory 记录" in result.output


def test_wiki_open_renders_site_without_opening_browser(tmp_path, monkeypatch):
    skill_dir = _make_fake_skill(tmp_path, "rendered-kb", with_memory=True)

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    runner = CliRunner()
    result = runner.invoke(
        cli, ["wiki", "open", "rendered-kb", "--skill-root", str(tmp_path), "--no-browser"]
    )
    assert result.exit_code == 0, result.output
    assert "--no-browser 已指定" in result.output
    assert not opened

    site_file = skill_dir / "memory" / "wiki" / "index.html"
    assert site_file.exists()
    assert "业务主题: 0" in result.output


def test_wiki_opens_browser_by_default(tmp_path, monkeypatch):
    _make_fake_skill(tmp_path, "rendered-kb2", with_memory=True)

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "open", "rendered-kb2", "--skill-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert len(opened) == 1
    assert opened[0].startswith("file:")


def test_wiki_help_documents_business_flow_trigger_rules():
    """`ue5kb wiki --help` 必须说明业务流程图不是每次查询自动产生，以及触发信号，
    这样用户不用先读 SKILL.md 就能知道 wiki 里的业务流程图从哪来。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["wiki", "--help"])
    assert result.exit_code == 0

    text = result.output
    assert "query_memory_record" in text
    assert "query_memory_attach_flow" in text
    assert "何时主动归纳业务流程图" in text or "SKILL.md" in text
    assert "证据链" in text
    assert "静态探索已闭合" in text


def test_wiki_open_warns_when_source_root_resolution_fails(tmp_path, monkeypatch):
    """resolve_source_path 抛异常时必须提示用户，不能静默把 source_root 设为 None。"""
    _make_fake_skill(tmp_path, "broken-source-kb", with_memory=True)

    def _raise(self, variant=None):
        raise RuntimeError("registry 已损坏")

    monkeypatch.setattr("ue5_kb.branch_manager.BranchManager.resolve_source_path", _raise)
    monkeypatch.setattr("webbrowser.open", lambda url: None)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["wiki", "open", "broken-source-kb", "--skill-root", str(tmp_path), "--no-browser"]
    )
    assert result.exit_code == 0, result.output
    assert "无法解析源码路径" in result.output
    assert "registry 已损坏" in result.output
