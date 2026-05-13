"""
P0 修复最小测试

覆盖：
1. PipelineCoordinator kb_path 外置路径支持
2. BranchManager.register 同 commit 复用
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 辅助：创建最小 registry.db
# ---------------------------------------------------------------------------

def _make_registry(db_path: Path, kb_store: str) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            name TEXT PRIMARY KEY,
            commit_id TEXT,
            status TEXT DEFAULT 'active',
            vcs_type TEXT,
            description TEXT DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS versions (
            commit_id TEXT PRIMARY KEY,
            kb_dir TEXT NOT NULL,
            built_at TEXT,
            file_count INTEGER DEFAULT 0,
            build_status TEXT DEFAULT 'building',
            source_path TEXT
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.execute("INSERT OR REPLACE INTO config VALUES ('kb_store', ?)", (kb_store,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 测试 1: PipelineCoordinator 接受并使用外置 kb_path
# ---------------------------------------------------------------------------

class TestPipelineCoordinatorKbPath:
    def test_default_kb_path_is_base_subdir(self, tmp_path):
        """未指定 kb_path 时，默认为 base_path/KnowledgeBase"""
        from ue5_kb.pipeline.coordinator import PipelineCoordinator

        coord = PipelineCoordinator(tmp_path)
        assert coord.kb_path == tmp_path / "KnowledgeBase"

    def test_custom_kb_path_used(self, tmp_path):
        """指定 kb_path 时，coordinator 及各 stage 均使用该路径"""
        from ue5_kb.pipeline.coordinator import PipelineCoordinator

        custom_kb = tmp_path / "custom_kb"
        coord = PipelineCoordinator(tmp_path, kb_path=custom_kb)

        assert coord.kb_path == custom_kb
        # state_file 应在 custom_kb 下
        assert coord.state.state_file.parent == custom_kb
        # 各 stage 的 data_dir 应在 custom_kb/data
        for stage in coord.stages.values():
            assert stage.data_dir == custom_kb / "data", \
                f"stage {stage.stage_name}.data_dir={stage.data_dir} != {custom_kb / 'data'}"

    def test_build_stage_get_output_path(self, tmp_path):
        """BuildStage.get_output_path 应返回 _kb_root"""
        from ue5_kb.pipeline.build import BuildStage

        custom_kb = tmp_path / "external_kb"
        stage = BuildStage(tmp_path, kb_path=custom_kb)
        assert stage.get_output_path() == custom_kb

    def test_parallel_build_stage_uses_kb_path(self, tmp_path):
        """ParallelBuildStage.__init__ 应接受 kb_path"""
        from ue5_kb.pipeline.build_parallel import ParallelBuildStage

        custom_kb = tmp_path / "parallel_kb"
        stage = ParallelBuildStage(tmp_path, num_workers=2, kb_path=custom_kb)
        assert stage.kb_path == custom_kb
        assert stage.data_dir == custom_kb / "data"

    def test_extract_manifest_uses_external_kb_config_root(self, tmp_path):
        """ExtractStage 创建模块 manifest 时，不应把外置 KB 目录当 config 文件打开"""
        from ue5_kb.pipeline.extract import ExtractStage

        base_path = tmp_path / "plugin"
        module_dir = base_path / "Source" / "MyModule"
        module_dir.mkdir(parents=True)
        build_cs = module_dir / "MyModule.Build.cs"
        build_cs.write_text("public class MyModule {}", encoding="utf-8")
        (module_dir / "MyClass.h").write_text("class FMyClass {};", encoding="utf-8")

        custom_kb = tmp_path / "external_kb"
        stage = ExtractStage(base_path, kb_path=custom_kb)
        output_dir = custom_kb / "data" / "extract" / "MyModule"
        output_dir.mkdir(parents=True)

        stage._create_module_manifest(
            "MyModule",
            {
                "path": "Source/MyModule/MyModule.Build.cs",
                "absolute_path": str(build_cs),
                "category": "Runtime",
            },
            output_dir,
        )

        assert (output_dir / "module_manifest.json").exists()
        assert (custom_kb / "config.yaml").exists()

    def test_build_manifest_uses_external_kb_config_root(self, tmp_path):
        """BuildStage 保存 KB manifest 时，Config 应以外置 KB 为 base_path"""
        from ue5_kb.pipeline.build import BuildStage

        base_path = tmp_path / "plugin"
        base_path.mkdir()
        custom_kb = tmp_path / "external_kb"
        (custom_kb / "global_index").mkdir(parents=True)

        stage = BuildStage(base_path, kb_path=custom_kb)
        stage._save_kb_manifest(custom_kb, {"total_modules": 0})

        assert (custom_kb / "config.yaml").exists()
        assert (custom_kb / ".kb_manifest.json").exists()


# ---------------------------------------------------------------------------
# 测试 2: BranchManager.register 同 commit 复用
# ---------------------------------------------------------------------------

class TestBranchManagerRegisterReuse:
    def _make_complete_kb(self, store: Path, kb_dir: str) -> Path:
        """在 variants store 中创建一个假的完整 KB"""
        kb_path = store / kb_dir
        kb_path.mkdir(parents=True, exist_ok=True)
        (kb_path / "dummy.txt").write_text("dummy")
        return kb_path

    def test_register_reuse_same_commit(self, tmp_path):
        """相同 commit_id 且 KB 目录存在时，register 应复用并返回 reused=True"""
        from ue5_kb.branch_manager import BranchManager, _db_connect

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()

        _make_registry(registry_db, str(variants_dir))

        # 预先插入一个完整版本记录
        commit_id = "abcdef1234567890"
        kb_dir = "abcdef1"
        self._make_complete_kb(variants_dir, kb_dir)

        conn = _db_connect(registry_db)
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status) VALUES (?, ?, 'complete')",
            (commit_id, kb_dir),
        )
        conn.commit()
        conn.close()

        # 创建假 source 目录（register 用于 VCS 检测）
        source_dir = tmp_path / "plugin_src"
        source_dir.mkdir()
        (source_dir / "Dummy.uplugin").write_text("{}")

        # 创建假 KB（register 需要 kb_source 存在，但因 reuse 应跳过导入）
        fake_kb = source_dir / "KnowledgeBase"
        fake_kb.mkdir()
        (fake_kb / "global_index").mkdir()

        mgr = BranchManager(skill_dir)

        # 需要绕过 VCS 检测直接插入 commit_id
        # 直接往 registry 中写 branches，模拟 vcs 返回相同 commit_id
        conn2 = _db_connect(registry_db)
        conn2.execute(
            "INSERT OR REPLACE INTO branches (name, commit_id, status, vcs_type, updated_at)"
            " VALUES ('other_branch', ?, 'active', 'none', datetime('now'))",
            (commit_id,),
        )
        conn2.commit()
        conn2.close()

        # 手动 patch vcs to return known commit
        import unittest.mock as mock
        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = commit_id
        mock_vcs.get_type.return_value = "git"

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr.register(
                branch="new_branch",
                source=str(source_dir),
                kb_path=str(fake_kb),
            )

        assert result.get("status") == "ok", f"Expected ok, got: {result}"
        assert result.get("reused") is True, f"Expected reused=True, got: {result}"

    def test_register_no_reuse_when_dir_missing(self, tmp_path):
        """commit_id 存在但 KB 目录缺失时，应按正常新导入处理（reused=False）"""
        from ue5_kb.branch_manager import BranchManager, _db_connect

        skill_dir = tmp_path / "skill2"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()

        _make_registry(registry_db, str(variants_dir))

        commit_id = "deadbeef12345678"
        kb_dir = "deadbee"
        # 注意：不创建实际目录，模拟目录缺失的情况

        conn = _db_connect(registry_db)
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status) VALUES (?, ?, 'complete')",
            (commit_id, kb_dir),
        )
        conn.commit()
        conn.close()

        source_dir = tmp_path / "plugin_src2"
        source_dir.mkdir()
        (source_dir / "Dummy.uplugin").write_text("{}")

        # 提供一个合法的 KB 目录供导入
        fake_kb = source_dir / "KnowledgeBase"
        (fake_kb / "global_index").mkdir(parents=True)
        (fake_kb / "global_index" / "index.db").write_bytes(b"")

        import unittest.mock as mock
        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = commit_id
        mock_vcs.get_type.return_value = "git"

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr_obj = BranchManager(skill_dir)
            result = mgr_obj.register(
                branch="fresh_branch",
                source=str(source_dir),
                kb_path=str(fake_kb),
            )

        # 应该不是 reused（目录缺失走新导入路径）
        assert result.get("reused") is not True, f"Should not reuse when dir missing: {result}"


class TestBranchManagerUpdateReuse:
    def test_force_update_replaces_existing_kb_dir_without_source_pollution(self, tmp_path):
        """force update 同 commit 应复用原 kb_dir，并把构建输出写到 variants 临时目录"""
        from ue5_kb.branch_manager import BranchManager, _db_connect

        skill_dir = tmp_path / "skill_update"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        commit_id = "abcdef1234567890"
        kb_dir = "abcdef1"
        existing_variant = variants_dir / kb_dir
        existing_variant.mkdir()
        (existing_variant / "old.txt").write_text("old")

        conn = _db_connect(registry_db)
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status) VALUES (?, ?, 'complete')",
            (commit_id, kb_dir),
        )
        conn.execute(
            "INSERT INTO branches (name, commit_id, status, vcs_type, updated_at)"
            " VALUES ('DEV', ?, 'active', 'git', datetime('now'))",
            (commit_id,),
        )
        conn.execute("INSERT OR REPLACE INTO config VALUES ('active_branch', 'old_branch')")
        conn.commit()
        conn.close()

        source_dir = tmp_path / "plugin_src"
        source_dir.mkdir()
        (source_dir / "Dummy.uplugin").write_text("{}")

        import unittest.mock as mock
        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = commit_id
        mock_vcs.get_type.return_value = "git"
        mock_vcs.is_dirty.return_value = False

        build_outputs = []

        def fake_build(plugin_root, kb_output, incremental=False):
            build_outputs.append(Path(kb_output))
            assert Path(plugin_root) == source_dir
            assert Path(kb_output).parent == variants_dir
            assert Path(kb_output).name.startswith("_build_tmp_")
            Path(kb_output).mkdir(parents=True)
            (Path(kb_output) / "new.txt").write_text("new")
            return {"status": "ok"}

        mgr = BranchManager(skill_dir)
        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs), \
             mock.patch.object(BranchManager, "_build_kb", side_effect=fake_build):
            result = mgr.update("DEV", str(source_dir), force=True)

        assert result.get("status") == "ok", result
        assert result.get("kb_dir") == kb_dir
        assert len(build_outputs) == 1
        assert not (source_dir / "KnowledgeBase").exists()
        assert not build_outputs[0].exists(), "临时构建目录应在导入成功后清理"
        assert (variants_dir / kb_dir / "new.txt").exists()
        assert not (variants_dir / kb_dir / "old.txt").exists()
        variant_dirs = [p.name for p in variants_dir.iterdir() if p.is_dir()]
        assert variant_dirs == [kb_dir]
        conn = sqlite3.connect(str(registry_db))
        active = conn.execute(
            "SELECT value FROM config WHERE key = 'active_branch'"
        ).fetchone()
        conn.close()
        assert active == ("DEV",)
