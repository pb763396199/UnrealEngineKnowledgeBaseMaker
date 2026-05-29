"""
测试 VCSAdapter scope 修复：
- detect() 在子目录时正确设置 scope
- _git_source_dirty_paths() 在 scope 非 "." 时追加 -- <scope> pathspec
- 全仓库 scope (".")  时不追加 pathspec（行为兼容）
"""

import subprocess
import unittest.mock as mock
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_git_repo_with_plugin(tmp_path: Path) -> tuple[Path, Path]:
    """创建含插件子目录的 git 仓库，返回 (repo_root, plugin_dir)"""
    repo = tmp_path / "engine"
    plugin = repo / "Plugins" / "Marketplace" / "MyPlugin"
    other = repo / "Source" / "Runtime" / "Core"

    (plugin / "Source" / "MyPlugin" / "Private").mkdir(parents=True)
    (plugin / "MyPlugin.Build.cs").write_text("// build\n", encoding="utf-8")
    (plugin / "Source" / "MyPlugin" / "Private" / "MyPlugin.cpp").write_text(
        "void Init() {}\n", encoding="utf-8"
    )
    other.mkdir(parents=True)
    (other / "Core.cpp").write_text("// core\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, plugin


# ── detect() scope 提取 ───────────────────────────────────────────────────────

class TestDetectScope:
    def test_subdirectory_scope_is_relative(self, tmp_path):
        """detect() 在子目录时 scope 应为相对 repo root 的 posix 路径"""
        from ue5_kb.vcs import VCSAdapter

        repo, plugin = _make_git_repo_with_plugin(tmp_path)
        adapter = VCSAdapter.detect(str(plugin))

        assert adapter._type == "git"
        assert adapter._path == str(repo)
        expected_scope = plugin.relative_to(repo).as_posix()
        assert adapter._scope == expected_scope

    def test_repo_root_scope_is_dot(self, tmp_path):
        """detect() 在仓库根目录时 scope 应为 '.'"""
        from ue5_kb.vcs import VCSAdapter

        repo, _ = _make_git_repo_with_plugin(tmp_path)
        adapter = VCSAdapter.detect(str(repo))

        assert adapter._scope == "."

    def test_no_git_repo_scope_is_dot(self, tmp_path):
        """detect() 在非 git 目录时返回 none adapter，scope 为 '.'"""
        from ue5_kb.vcs import VCSAdapter

        adapter = VCSAdapter.detect(str(tmp_path))
        assert adapter._type == "none"
        assert adapter._scope == "."


# ── _git_source_dirty_paths() pathspec 注入 ──────────────────────────────────

class TestGitDirtyPathsScope:
    """通过 mock subprocess.run 验证 git 命令包含/不包含 pathspec"""

    def _make_adapter(self, scope: str):
        from ue5_kb.vcs import VCSAdapter
        return VCSAdapter("/fake/repo", "git", scope)

    def _run_side_effect(self, *args, **kwargs):
        """subprocess.run mock：始终返回 returncode=0，stdout=b''"""
        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = b""
        return result

    def test_subdirectory_scope_adds_pathspec_to_diff(self):
        """scope 为子目录时，git diff 命令应包含 -- <scope>"""
        scope = "Plugins/Marketplace/CesiumForUnreal"
        adapter = self._make_adapter(scope)

        with mock.patch("subprocess.run", side_effect=self._run_side_effect) as mock_run:
            adapter._git_source_dirty_paths()

        # 第一次调用是 git diff
        diff_call = mock_run.call_args_list[0]
        cmd = diff_call[0][0]
        assert "--" in cmd, "diff 命令应包含 -- 分隔符"
        assert scope in cmd, f"diff 命令应包含 scope pathspec: {scope}"

    def test_subdirectory_scope_adds_pathspec_to_ls_files(self):
        """scope 为子目录时，git ls-files 命令应包含 -- <scope>"""
        scope = "Plugins/Marketplace/CesiumForUnreal"
        adapter = self._make_adapter(scope)

        with mock.patch("subprocess.run", side_effect=self._run_side_effect) as mock_run:
            adapter._git_source_dirty_paths()

        # 第二次调用是 git ls-files
        ls_call = mock_run.call_args_list[1]
        cmd = ls_call[0][0]
        assert "--" in cmd, "ls-files 命令应包含 -- 分隔符"
        assert scope in cmd, f"ls-files 命令应包含 scope pathspec: {scope}"

    def test_root_scope_no_pathspec_in_diff(self):
        """scope 为 '.' 时，git diff 命令不应追加 pathspec"""
        adapter = self._make_adapter(".")

        with mock.patch("subprocess.run", side_effect=self._run_side_effect) as mock_run:
            adapter._git_source_dirty_paths()

        diff_call = mock_run.call_args_list[0]
        cmd = diff_call[0][0]
        # 不应出现 "--" pathspec 分隔符（HEAD 后面没有 --）
        assert "--" not in cmd, "根仓库 scope 不应追加 -- pathspec"

    def test_root_scope_no_pathspec_in_ls_files(self):
        """scope 为 '.' 时，git ls-files 命令不应追加 pathspec"""
        adapter = self._make_adapter(".")

        with mock.patch("subprocess.run", side_effect=self._run_side_effect) as mock_run:
            adapter._git_source_dirty_paths()

        ls_call = mock_run.call_args_list[1]
        cmd = ls_call[0][0]
        assert "--" not in cmd, "根仓库 scope 不应追加 -- pathspec"


# ── 真实 git 仓库集成测试 ─────────────────────────────────────────────────────

class TestGitScopeIntegration:
    """使用真实 git 仓库验证 scope 实际限制 dirty 文件可见性"""

    def test_plugin_scope_sees_only_plugin_dirty_files(self, tmp_path):
        """修改插件内文件 → scope=plugin 时 is_dirty()=True，scope=other 时 is_dirty()=False"""
        from ue5_kb.vcs import VCSAdapter

        repo, plugin = _make_git_repo_with_plugin(tmp_path)

        # 修改插件内的 cpp 文件（已追踪）
        cpp = plugin / "Source" / "MyPlugin" / "Private" / "MyPlugin.cpp"
        cpp.write_text("void Init() {} // modified\n", encoding="utf-8")

        # scope 指向插件目录 → 应看到 dirty
        adapter_plugin = VCSAdapter.detect(str(plugin))
        assert adapter_plugin._scope != ".", "scope 应为子目录"
        assert adapter_plugin.is_dirty() is True, "插件 scope 应检测到 dirty"

        # scope 指向另一目录 → 不应看到 dirty
        other_dir = repo / "Source" / "Runtime" / "Core"
        adapter_other = VCSAdapter.detect(str(other_dir))
        assert adapter_other._scope != ".", "scope 应为子目录"
        assert adapter_other.is_dirty() is False, "Core scope 不应看到插件的 dirty 文件"

    def test_plugin_scope_sees_only_plugin_untracked_files(self, tmp_path):
        """在插件内添加新文件 → scope=plugin 时 is_dirty()=True，scope=other 时 is_dirty()=False"""
        from ue5_kb.vcs import VCSAdapter

        repo, plugin = _make_git_repo_with_plugin(tmp_path)

        # 在插件内添加未追踪的新文件
        new_file = plugin / "Source" / "MyPlugin" / "Private" / "NewFeature.cpp"
        new_file.write_text("void New() {}\n", encoding="utf-8")

        adapter_plugin = VCSAdapter.detect(str(plugin))
        assert adapter_plugin.is_dirty() is True, "插件 scope 应检测到未追踪新文件"

        other_dir = repo / "Source" / "Runtime" / "Core"
        adapter_other = VCSAdapter.detect(str(other_dir))
        assert adapter_other.is_dirty() is False, "Core scope 不应看到插件的未追踪文件"

    def test_root_scope_sees_all_dirty_files(self, tmp_path):
        """scope=repo root 时应看到所有 dirty 文件（兼容行为）"""
        from ue5_kb.vcs import VCSAdapter

        repo, plugin = _make_git_repo_with_plugin(tmp_path)

        # 修改 Core 目录下的文件
        core_cpp = repo / "Source" / "Runtime" / "Core" / "Core.cpp"
        core_cpp.write_text("// modified\n", encoding="utf-8")

        adapter_root = VCSAdapter.detect(str(repo))
        assert adapter_root._scope == ".", "仓库根目录 scope 应为 '.'"
        assert adapter_root.is_dirty() is True, "根 scope 应看到所有 dirty 文件"
