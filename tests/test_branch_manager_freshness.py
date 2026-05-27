import sqlite3
import unittest.mock as mock
from pathlib import Path


def _make_active_registry(skill_dir: Path, source: Path, *, commit: str, dirty: int, fingerprint: str) -> None:
    from ue5_kb.branch_manager import BranchManager

    mgr = BranchManager(skill_dir)
    mgr._init_registry()
    conn = sqlite3.connect(str(skill_dir / "registry.db"))
    conn.execute(
        """
        INSERT INTO versions
        (commit_id, kb_dir, build_status, source_path, dirty, worktree_fingerprint)
        VALUES (?, 'abc1234', 'complete', ?, ?, ?)
        """,
        (commit, str(source), dirty, fingerprint),
    )
    conn.execute(
        "INSERT INTO branches (name, commit_id, status, vcs_type) VALUES ('DEV', ?, 'active', 'git')",
        (commit,),
    )
    conn.execute("INSERT OR REPLACE INTO config VALUES ('active_branch', 'DEV')")
    conn.commit()
    conn.close()


def _mock_vcs(commit: str, dirty: bool, fingerprint: str):
    vcs = mock.MagicMock()
    vcs.get_head_id.return_value = commit
    vcs.is_dirty.return_value = dirty
    vcs.get_worktree_fingerprint.return_value = fingerprint
    return vcs


def test_check_freshness_reports_commit_changed_stale_reason(tmp_path):
    from ue5_kb.branch_manager import BranchManager

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    source = tmp_path / "plugin"
    source.mkdir()
    _make_active_registry(skill_dir, source, commit="aaaa1111", dirty=0, fingerprint="samefinger")

    mgr = BranchManager(skill_dir)
    with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=_mock_vcs("bbbb2222", False, "samefinger")):
        result = mgr.check_freshness(str(source))

    assert result["fresh"] is False
    assert result["stale_reason"] == "commit_changed"
    assert result["expected_fingerprint"] == "samefinger"
    assert result["actual_fingerprint"] == "samefinger"


def test_check_freshness_reports_dirty_changed_stale_reason(tmp_path):
    from ue5_kb.branch_manager import BranchManager

    skill_dir = tmp_path / "skill_dirty"
    skill_dir.mkdir()
    source = tmp_path / "plugin_dirty"
    source.mkdir()
    _make_active_registry(skill_dir, source, commit="aaaa1111", dirty=0, fingerprint="cleanfinger")

    mgr = BranchManager(skill_dir)
    with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=_mock_vcs("aaaa1111", True, "cleanfinger")):
        result = mgr.check_freshness(str(source))

    assert result["fresh"] is False
    assert result["stale_reason"] == "dirty_changed"


def test_check_freshness_reports_fingerprint_changed_stale_reason(tmp_path):
    from ue5_kb.branch_manager import BranchManager

    skill_dir = tmp_path / "skill_fingerprint"
    skill_dir.mkdir()
    source = tmp_path / "plugin_fingerprint"
    source.mkdir()
    _make_active_registry(skill_dir, source, commit="aaaa1111", dirty=1, fingerprint="oldfingerprint")

    mgr = BranchManager(skill_dir)
    with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=_mock_vcs("aaaa1111", True, "newfingerprint")):
        result = mgr.check_freshness(str(source))

    assert result["fresh"] is False
    assert result["stale_reason"] == "fingerprint_changed"
    assert result["expected_fingerprint"] == "oldfingerpri"
    assert result["actual_fingerprint"] == "newfingerpri"


def test_check_freshness_reports_source_mismatch_stale_reason(tmp_path):
    from ue5_kb.branch_manager import BranchManager

    skill_dir = tmp_path / "skill_source"
    skill_dir.mkdir()
    registered_source = tmp_path / "registered"
    current_source = tmp_path / "current"
    registered_source.mkdir()
    current_source.mkdir()
    _make_active_registry(skill_dir, registered_source, commit="aaaa1111", dirty=0, fingerprint="samefinger")

    mgr = BranchManager(skill_dir)
    with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=_mock_vcs("aaaa1111", False, "samefinger")):
        result = mgr.check_freshness(str(current_source))

    assert result["fresh"] is False
    assert result["stale_reason"] == "source_mismatch"
    assert result["source_mismatch"] is True


def test_check_freshness_treats_unknown_timestamp_commit_as_fresh_for_non_git(tmp_path):
    from ue5_kb.branch_manager import BranchManager

    skill_dir = tmp_path / "skill_unknown"
    skill_dir.mkdir()
    source = tmp_path / "plugin_unknown"
    source.mkdir()
    _make_active_registry(skill_dir, source, commit="unknown_123456", dirty=0, fingerprint="samefinger")

    mgr = BranchManager(skill_dir)
    with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=_mock_vcs("unknown", False, "samefinger")):
        result = mgr.check_freshness(str(source))

    assert result["fresh"] is True
    assert result["stale_reason"] is None


def test_check_freshness_reports_non_git_source_change_stale(tmp_path):
    from ue5_kb.branch_manager import BranchManager
    from ue5_kb.vcs import VCSAdapter

    skill_dir = tmp_path / "skill_non_git"
    skill_dir.mkdir()
    source = tmp_path / "plugin_non_git"
    source_file = source / "Source" / "MyModule" / "Private" / "Foo.cpp"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("void Before() {}\n", encoding="utf-8")

    vcs = VCSAdapter.detect(str(source))
    assert vcs.get_type() == "none"
    original_fingerprint = vcs.get_worktree_fingerprint()
    assert original_fingerprint
    _make_active_registry(skill_dir, source, commit="unknown_123456", dirty=0, fingerprint=original_fingerprint)

    source_file.write_text("void Before() {}\nvoid After() {}\n", encoding="utf-8")
    result = BranchManager(skill_dir).check_freshness(str(source))

    assert result["fresh"] is False
    assert result["stale_reason"] == "fingerprint_changed"
    assert result["expected_fingerprint"] == original_fingerprint[:12]
    assert result["actual_fingerprint"] != result["expected_fingerprint"]


def test_check_freshness_ignores_history_changes_for_non_git(tmp_path):
    from ue5_kb.branch_manager import BranchManager
    from ue5_kb.vcs import VCSAdapter

    skill_dir = tmp_path / "skill_non_git_history"
    skill_dir.mkdir()
    source = tmp_path / "plugin_non_git_history"
    source_file = source / "Source" / "MyModule" / "Private" / "Foo.cpp"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("void RealSource() {}\n", encoding="utf-8")

    vcs = VCSAdapter.detect(str(source))
    assert vcs.get_type() == "none"
    original_fingerprint = vcs.get_worktree_fingerprint()
    assert original_fingerprint
    _make_active_registry(skill_dir, source, commit="unknown_123456", dirty=0, fingerprint=original_fingerprint)

    history_file = source / ".history" / "Source" / "MyModule" / "Private" / "Foo_20260526191300.cpp"
    history_file.parent.mkdir(parents=True)
    history_file.write_text("void HistoryOnlyChange() {}\n", encoding="utf-8")
    history_file.write_text("void HistoryOnlyChangeAgain() {}\n", encoding="utf-8")
    result = BranchManager(skill_dir).check_freshness(str(source))

    assert result["fresh"] is True
    assert result["stale_reason"] is None
    assert result["expected_fingerprint"] == original_fingerprint[:12]
    assert result["actual_fingerprint"] == original_fingerprint[:12]
