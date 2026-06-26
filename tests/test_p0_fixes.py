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

    def test_register_promotes_temp_variant_without_copy_source_leftover(self, tmp_path):
        """register 应直接提升 variants 下的临时构建目录，避免保留第二份 KB。"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_promote"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir(parents=True)
        _make_registry(skill_dir / "registry.db", str(variants_dir))

        temp_kb = variants_dir / "_build_tmp_init"
        (temp_kb / "global_index").mkdir(parents=True)
        (temp_kb / "global_index" / "index.db").write_bytes(b"db")

        source_dir = tmp_path / "engine_src"
        source_dir.mkdir()

        import unittest.mock as mock
        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = "abcdef1234567890"
        mock_vcs.get_type.return_value = "git"
        mock_vcs.is_dirty.return_value = False
        mock_vcs.get_worktree_fingerprint.return_value = None

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = BranchManager(skill_dir).register(
                branch="default",
                source=str(source_dir),
                kb_path=str(temp_kb),
                force=True,
            )

        assert result.get("status") == "ok", result
        final_kb = Path(result["kb_path"])
        assert final_kb == variants_dir / "abcdef1"
        assert (final_kb / "global_index" / "index.db").exists()
        assert not temp_kb.exists()


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


class TestCanonicalSkillStoreDefaults:
    def test_init_engine_mode_defaults_kb_under_agents_skill_store(self, tmp_path, monkeypatch):
        """CLI init 默认应构建到共享 skill store 的 variants 临时目录。"""
        from ue5_kb import cli as cli_module

        engine = tmp_path / "UE_5.5"
        build_dir = engine / "Engine" / "Build"
        build_dir.mkdir(parents=True)
        (build_dir / "Build.version").write_text(
            json.dumps({"MajorVersion": 5, "MinorVersion": 5, "PatchVersion": 4}),
            encoding="utf-8",
        )

        skill_root = tmp_path / "skills"
        monkeypatch.setenv("UE5_KB_SKILL_ROOT", str(skill_root))
        captured = {}

        class FakeCoordinator:
            def __init__(self, base_path, kb_path=None, **kwargs):
                captured["base_path"] = Path(base_path)
                captured["kb_path"] = Path(kb_path)

            def run_all(self, **kwargs):
                captured["kwargs"] = kwargs
                return {
                    "generate": {
                        "skill_path": str(skill_root / "ue5kb-5.5.4"),
                        "kb_path": str(skill_root / "ue5kb-5.5.4" / "variants" / "abcdef1"),
                    }
                }

        monkeypatch.setattr("ue5_kb.pipeline.coordinator.PipelineCoordinator", FakeCoordinator)

        cli_module.init_engine_mode(
            engine,
            kb_path=None,
            skill_path=None,
            skill_root=None,
            skill_name=None,
            force=False,
            stage=None,
            workers=1,
            verbose=False,
        )

        assert captured["kb_path"] == skill_root / "ue5kb-5.5.4" / "variants" / "_build_tmp_init"
        assert captured["kb_path"] != engine / "KnowledgeBase"
        assert captured["kwargs"]["skill_path"] == str(skill_root / "ue5kb-5.5.4")

    def test_init_plugin_mode_defaults_kb_under_agents_skill_store(self, tmp_path, monkeypatch):
        """插件模式 init 默认也应构建到共享 skill store。"""
        from ue5_kb import cli as cli_module

        plugin = tmp_path / "Plugins" / "MyPlugin"
        plugin.mkdir(parents=True)
        (plugin / "MyPlugin.uplugin").write_text(
            json.dumps({"VersionName": "1.2.3"}),
            encoding="utf-8",
        )

        skill_root = tmp_path / "skills"
        monkeypatch.setenv("UE5_KB_SKILL_ROOT", str(skill_root))
        captured = {}

        class FakeCoordinator:
            def __init__(self, base_path, is_plugin=False, plugin_name=None, kb_path=None, **kwargs):
                captured["base_path"] = Path(base_path)
                captured["is_plugin"] = is_plugin
                captured["plugin_name"] = plugin_name
                captured["kb_path"] = Path(kb_path)

            def run_all(self, **kwargs):
                captured["kwargs"] = kwargs
                return {
                    "generate": {
                        "skill_path": str(skill_root / "MyPlugin-kb"),
                        "kb_path": str(skill_root / "MyPlugin-kb" / "variants" / "abcdef1"),
                    }
                }

        monkeypatch.setattr("ue5_kb.pipeline.coordinator.PipelineCoordinator", FakeCoordinator)

        cli_module.init_plugin_mode(
            plugin,
            kb_path=None,
            skill_path=None,
            skill_root=None,
            skill_name=None,
            force=False,
            stage=None,
            workers=1,
            verbose=False,
        )

        assert captured["is_plugin"] is True
        assert captured["plugin_name"] == "MyPlugin"
        assert captured["kb_path"] == skill_root / "MyPlugin-kb" / "variants" / "_build_tmp_init"
        assert captured["kb_path"] != plugin / "KnowledgeBase"
        assert captured["kwargs"]["skill_path"] == str(skill_root / "MyPlugin-kb")

    def test_generate_stage_moves_pipeline_state_to_promoted_kb_path(self, tmp_path):
        """generate 返回最终 KB 后，PipelineCoordinator 状态应写入最终目录。"""
        from ue5_kb.pipeline.coordinator import PipelineCoordinator

        base_path = tmp_path / "source"
        base_path.mkdir()
        temp_kb = tmp_path / "skill" / "variants" / "_build_tmp_init"
        final_kb = tmp_path / "skill" / "variants" / "abcdef1"
        temp_kb.mkdir(parents=True)
        final_kb.mkdir(parents=True)

        class FakeGenerateStage:
            stage_name = "generate"

            def is_completed(self):
                return False

            def run(self, **kwargs):
                return {
                    "skill_name": "Fake-kb",
                    "skill_path": str(tmp_path / "skill"),
                    "kb_path": str(final_kb),
                }

        coord = PipelineCoordinator(base_path, kb_path=temp_kb)
        coord.stages["generate"] = FakeGenerateStage()

        result = coord.run_stage("generate", force=True)

        assert result["kb_path"] == str(final_kb)
        assert (final_kb / ".pipeline_state").exists()
        assert not (temp_kb / ".pipeline_state").exists()

    def test_project_resolver_scans_agents_skill_root_by_default(self, tmp_path, monkeypatch):
        """uproject resolver 默认扫描 canonical .agents-style skill root。"""
        from ue5_kb.project_resolver import scan_kb_skills

        skill_root = tmp_path / "agents" / "skills"
        skill = skill_root / "ue5kb-5.5.4"
        skill.mkdir(parents=True)
        (skill / "skill.md").write_text("# skill", encoding="utf-8")
        (skill / "impl.py").write_text("", encoding="utf-8")
        monkeypatch.setenv("UE5_KB_SKILL_ROOT", str(skill_root))

        assert scan_kb_skills() == {"5.5.4": skill}

    def test_skill_name_validation_rejects_path_escape_and_yaml_breakers(self, tmp_path):
        """skill_name 进入路径和 adapter frontmatter 前必须被约束为单一路径段。"""
        from ue5_kb.skill_store import get_skill_path, install_provider_adapters, validate_skill_name

        assert validate_skill_name("AesWorld-kb") == "AesWorld-kb"
        assert validate_skill_name("ue5kb-5.5.4") == "ue5kb-5.5.4"

        invalid_names = [
            "..",
            "AesWorld/KB",
            r"AesWorld\KB",
            "AesWorld..KB",
            "AesWorld\nKB",
            "AesWorld:KB",
        ]
        for name in invalid_names:
            with pytest.raises(ValueError):
                get_skill_path(name, tmp_path / "skills")
            with pytest.raises(ValueError):
                install_provider_adapters(name, tmp_path / "skills" / "AesWorld-kb")

    def test_legacy_optimized_index_query_is_static_command_only(self):
        """optimized_index 的旧 query 入口不得继续暴露自然语言解析承诺。"""
        source = Path("ue5_kb/core/optimized_index.py").read_text(encoding="utf-8")
        assert "自然语言查询接口" not in source
        assert "自然语言问题" not in source
        assert "MassEntity 架构" not in source
        assert "unsupported_static_query" in source
        assert "module:<name>" in source

    def test_branch_update_all_help_defaults_to_agents_skill_store(self):
        """branch update-all 不能带项目专用默认路径，也不能退回 provider 私有 .claude 目录。"""
        from click.testing import CliRunner
        from ue5_kb.cli import cli

        result = CliRunner().invoke(cli, ["branch", "update-all", "--help"])

        assert result.exit_code == 0
        assert ".agents" in result.output
        assert "<SkillName>-kb" in result.output
        assert "AesWorld-kb" not in result.output
        assert ".claude" not in result.output

    def test_update_without_registry_does_not_fallback_to_source_knowledgebase(self, tmp_path, monkeypatch):
        """update 默认路径解析失败时必须显式失败，不能写回 source/KnowledgeBase。"""
        from click.testing import CliRunner
        from ue5_kb.cli import cli

        plugin = tmp_path / "Plugins" / "MyPlugin"
        plugin.mkdir(parents=True)
        (plugin / "MyPlugin.uplugin").write_text(json.dumps({"VersionName": "1.0"}), encoding="utf-8")
        monkeypatch.setenv("UE5_KB_SKILL_ROOT", str(tmp_path / "skills"))

        def fail_update_stage(*args, **kwargs):
            raise AssertionError("UpdateStage should not be created when registry resolution fails")

        monkeypatch.setattr("ue5_kb.pipeline.update.UpdateStage", fail_update_stage)

        result = CliRunner().invoke(cli, ["update", "--plugin-path", str(plugin), "--check"])

        assert result.exit_code == 0
        assert "无法从 canonical Skill registry 解析 KB 路径" in result.output
        assert "不会写入源码树 KnowledgeBase" in result.output
        assert "--kb-path" in result.output
        assert not (plugin / "KnowledgeBase").exists()

    def test_pipeline_run_defaults_kb_under_agents_skill_store(self, tmp_path, monkeypatch):
        """pipeline run 入口也必须默认写入共享 skill store，而不是 Engine/KnowledgeBase。"""
        from click.testing import CliRunner
        from ue5_kb.cli import cli

        engine = tmp_path / "UE_5.5"
        build_dir = engine / "Engine" / "Build"
        build_dir.mkdir(parents=True)
        (build_dir / "Build.version").write_text(
            '{"MajorVersion":5,"MinorVersion":5,"PatchVersion":4}',
            encoding="utf-8",
        )
        skill_root = tmp_path / "agents" / "skills"
        monkeypatch.setenv("UE5_KB_SKILL_ROOT", str(skill_root))

        captured = {}

        class FakeCoordinator:
            def __init__(self, base_path, kb_path=None, **kwargs):
                captured["base_path"] = Path(base_path)
                captured["kb_path"] = Path(kb_path)

            def run_all(self, **kwargs):
                captured["kwargs"] = kwargs
                return {
                    "generate": {
                        "skill_name": kwargs["skill_name"],
                        "skill_path": kwargs["skill_path"],
                        "kb_path": str(skill_root / "ue5kb-5.5.4" / "variants" / "abcdef1"),
                    }
                }

        monkeypatch.setattr("ue5_kb.pipeline.coordinator.PipelineCoordinator", FakeCoordinator)

        result = CliRunner().invoke(cli, ["pipeline", "run", "--engine-path", str(engine)])

        assert result.exit_code == 0
        assert captured["kb_path"] == skill_root / "ue5kb-5.5.4" / "variants" / "_build_tmp_pipeline"
        assert captured["kb_path"] != engine / "KnowledgeBase"
        assert captured["kwargs"]["skill_name"] == "ue5kb-5.5.4"
        assert captured["kwargs"]["skill_path"] == str(skill_root / "ue5kb-5.5.4")

    def test_force_adapter_reuses_existing_resolved_link(self, tmp_path, monkeypatch):
        """force 安装 adapter 时，已指向 canonical skill 的 junction/link 不应被备份。"""
        import ue5_kb.skill_store as skill_store

        source = tmp_path / "canonical"
        destination = tmp_path / "provider" / "Skill"
        source.mkdir()
        destination.mkdir(parents=True)

        original_resolve = Path.resolve

        def fake_resolve(path_self, *args, **kwargs):
            if path_self == destination:
                return original_resolve(source, *args, **kwargs)
            return original_resolve(path_self, *args, **kwargs)

        def fail_backup(path):
            raise AssertionError(f"should not backup existing resolved adapter: {path}")

        monkeypatch.setattr(Path, "resolve", fake_resolve)
        monkeypatch.setattr(skill_store, "_backup_existing_path", fail_backup)

        result = skill_store.create_directory_link(source, destination, force=True)

        assert result == {"status": "ok", "action": "exists", "path": str(destination)}

    def test_force_directory_link_restores_backup_when_link_creation_fails(self, tmp_path, monkeypatch):
        """force 安装目录 adapter 失败时，必须恢复原 provider 目录。"""
        import ue5_kb.skill_store as skill_store

        source = tmp_path / "canonical"
        destination = tmp_path / "provider" / "Skill"
        source.mkdir()
        destination.mkdir(parents=True)
        marker = destination / "original.txt"
        marker.write_text("keep me", encoding="utf-8")

        def fail_symlink(*args, **kwargs):
            raise OSError("symlink disabled")

        class FailedProcess:
            returncode = 1
            stderr = "junction disabled"
            stdout = ""

        monkeypatch.setattr(skill_store.os, "symlink", fail_symlink)
        monkeypatch.setattr(skill_store.subprocess, "run", lambda *args, **kwargs: FailedProcess())

        result = skill_store.create_directory_link(source, destination, force=True)

        assert result["status"] == "skipped"
        assert result["reason"].startswith("link_failed")
        assert result["restored"] == "True"
        assert destination.exists()
        assert (destination / "original.txt").read_text(encoding="utf-8") == "keep me"

    def test_force_file_adapter_restores_backup_when_write_fails(self, tmp_path, monkeypatch):
        """force 写入文件 adapter 失败时，必须恢复原文件。"""
        import ue5_kb.skill_store as skill_store

        target = tmp_path / "provider" / "Skill.md"
        target.parent.mkdir(parents=True)
        target.write_text("original", encoding="utf-8")

        original_write_text = Path.write_text

        def fail_replacement_write(path_self, *args, **kwargs):
            if path_self.name == ".Skill.md.tmp":
                raise OSError("disk full")
            return original_write_text(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_replacement_write)

        result = skill_store.write_text_if_safe(target, "replacement", force=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "write_failed"
        assert result["restored"] == "True"
        assert target.read_text(encoding="utf-8") == "original"

    def test_force_file_adapter_restores_backup_after_partial_replace_failure(self, tmp_path, monkeypatch):
        """原子替换阶段失败且目标出现半写文件时，也必须恢复原 adapter。"""
        import ue5_kb.skill_store as skill_store

        target = tmp_path / "provider" / "Skill.md"
        target.parent.mkdir(parents=True)
        target.write_text("original", encoding="utf-8")

        original_replace = Path.replace

        def fail_replace_with_partial(path_self, target_path, *args, **kwargs):
            if path_self.name == ".Skill.md.tmp":
                Path(target_path).write_text("partial", encoding="utf-8")
                raise OSError("replace interrupted")
            return original_replace(path_self, target_path, *args, **kwargs)

        monkeypatch.setattr(Path, "replace", fail_replace_with_partial)

        result = skill_store.write_text_if_safe(target, "replacement", force=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "write_failed"
        assert result["restored"] == "True"
        assert target.read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# Phase 0 新增测试
# ---------------------------------------------------------------------------

class TestLayeredQuerySQLiteFirst:
    """LayeredQuery._load_class_info 优先从 SQLite 返回，不扫 pkl"""

    def test_load_class_info_from_sqlite(self, tmp_path):
        from ue5_kb.core.class_index import ClassIndex
        from ue5_kb.query.layered_query import LayeredQueryInterface

        # 构造最小 kb_path 结构
        gi_dir = tmp_path / "global_index"
        gi_dir.mkdir(parents=True)
        db_path = gi_dir / "class_index.db"

        cls_idx = ClassIndex(str(db_path))
        cls_idx.add_class({
            'name': 'AMyTestActor',
            'module': 'TestModule',
            'namespace': '',
            'parent_classes': ['AActor'],
            'interfaces': [],
            'file_path': '/Engine/Source/MyActor.h',
            'line_number': 10,
            'is_uclass': True,
            'is_struct': False,
            'is_interface': False,
            'is_blueprintable': True,
            'method_count': 3,
            'property_count': 2,
        })
        cls_idx.close()

        lq = LayeredQueryInterface(str(tmp_path))
        info = lq._load_class_info('AMyTestActor')

        assert info is not None, "应从 SQLite 返回结果"
        assert info['name'] == 'AMyTestActor'
        assert info['module'] == 'TestModule'
        assert info['is_uclass'] is True
        assert info['is_blueprint'] is True  # is_blueprintable 映射到 is_blueprint
        assert info['parent_classes'] == ['AActor']

    def test_load_class_info_fallback_on_missing_db(self, tmp_path):
        """db 不存在时不抛异常，回退返回 None（没有 pkl）"""
        from ue5_kb.query.layered_query import LayeredQueryInterface

        lq = LayeredQueryInterface(str(tmp_path))
        info = lq._load_class_info('SomeNonExistentClass')
        assert info is None


class TestClassIndexFTS:
    """ClassIndex FTS5 full-text search"""

    def test_search_fts_finds_written_class(self, tmp_path):
        import pytest
        from ue5_kb.core.class_index import ClassIndex

        cls_idx = ClassIndex(str(tmp_path / "class_index.db"))

        if not cls_idx._fts_enabled:
            cls_idx.close()
            pytest.skip("FTS5 not available in this SQLite build")

        cls_idx.add_class({
            'name': 'AWeaponComponent',
            'module': 'CombatModule',
            'namespace': '',
            'parent_classes': ['UActorComponent'],
            'interfaces': [],
            'file_path': '/Game/Combat/WeaponComponent.h',
            'line_number': 5,
            'is_uclass': True,
            'is_struct': False,
            'is_interface': False,
            'is_blueprintable': False,
            'method_count': 1,
            'property_count': 0,
        })

        results = cls_idx.search_fts('AWeaponComponent')
        cls_idx.close()

        assert len(results) >= 1
        assert results[0]['name'] == 'AWeaponComponent'

    def test_search_fts_empty_when_fts_disabled(self, tmp_path):
        from ue5_kb.core.class_index import ClassIndex

        cls_idx = ClassIndex(str(tmp_path / "class_index.db"))
        cls_idx._fts_enabled = False  # 强制禁用
        results = cls_idx.search_fts('anything')
        cls_idx.close()
        assert results == []


class TestFunctionIndexStatistics:
    """FunctionIndex.get_statistics 包含 short_name_count / unknown_signature_count"""

    def test_statistics_contain_new_fields(self, tmp_path):
        from ue5_kb.core.function_index import FunctionIndex

        func_idx = FunctionIndex(str(tmp_path / "function_index.db"))
        # 插入一个短名函数
        func_idx.add_function({
            'name': 'fx',          # len <= 2，计入 short_name_count
            'module': 'M',
            'class_name': 'C',
            'return_type': 'void',
            'parameters': [],
            'signature': 'void fx(unknown int param)',  # 含 'unknown '
            'file_path': '',
            'line_number': 0,
            'impl_file_path': '',
            'impl_line_number': 0,
            'is_virtual': False,
            'is_const': False,
            'is_static': False,
            'is_override': False,
            'is_blueprint_callable': False,
            'ufunction_specifiers': {},
        })
        func_idx.add_function({
            'name': 'DoSomethingLonger',
            'module': 'M',
            'class_name': 'C',
            'return_type': 'bool',
            'parameters': [],
            'signature': 'bool DoSomethingLonger()',
            'file_path': '',
            'line_number': 1,
            'impl_file_path': '',
            'impl_line_number': 0,
            'is_virtual': False,
            'is_const': False,
            'is_static': False,
            'is_override': False,
            'is_blueprint_callable': False,
            'ufunction_specifiers': {},
        })
        func_idx.commit()
        stats = func_idx.get_statistics()
        func_idx.close()

        assert 'short_name_count' in stats
        assert 'unknown_signature_count' in stats
        assert stats['short_name_count'] == 1      # 'fx' 计入
        assert stats['unknown_signature_count'] == 1  # 签名含 'unknown '
        assert stats['total_functions'] == 2


class TestBuildStageQualityGates:
    """BuildStage._check_quality_gates 在空索引下返回 quality_passed=False"""

    def test_quality_gates_empty_indices(self, tmp_path):
        from ue5_kb.pipeline.build import BuildStage
        from ue5_kb.core.config import Config

        kb_path = tmp_path / "KnowledgeBase"
        (kb_path / "global_index").mkdir(parents=True)

        stage = BuildStage(tmp_path, kb_path=kb_path)
        config = Config(base_path=str(kb_path))

        quality = stage._check_quality_gates(config)

        assert 'quality_passed' in quality
        assert 'symbol_reference_count' in quality
        assert quality['quality_passed'] is False   # 空索引必然未通过
        assert quality['class_count'] == 0
        assert quality['function_count'] == 0
        assert quality['symbol_reference_count'] == 0

    def test_quality_gates_with_data_passes_count_checks(self, tmp_path):
        from ue5_kb.pipeline.build import BuildStage
        from ue5_kb.core.config import Config
        from ue5_kb.core.class_index import ClassIndex
        from ue5_kb.core.function_index import FunctionIndex

        kb_path = tmp_path / "KnowledgeBase"
        gi = kb_path / "global_index"
        gi.mkdir(parents=True)

        # 写入一个类
        cls_idx = ClassIndex(str(gi / "class_index.db"))
        cls_idx.add_class({
            'name': 'ATestClass', 'module': 'M', 'namespace': '',
            'parent_classes': [], 'interfaces': [],
            'file_path': 'A.h', 'line_number': 1,
            'is_uclass': True, 'is_struct': False,
            'is_interface': False, 'is_blueprintable': False,
            'method_count': 0, 'property_count': 0,
        })
        cls_idx.close()

        # 写入一个函数
        func_idx = FunctionIndex(str(gi / "function_index.db"))
        func_idx.add_function({
            'name': 'DoWork', 'module': 'M', 'class_name': 'ATestClass',
            'return_type': 'void', 'parameters': [],
            'signature': 'void DoWork()',
            'file_path': '', 'line_number': 0,
            'impl_file_path': '', 'impl_line_number': 0,
            'is_virtual': False, 'is_const': False, 'is_static': False,
            'is_override': False, 'is_blueprint_callable': False,
            'ufunction_specifiers': {},
        })
        func_idx.commit()
        func_idx.close()

        stage = BuildStage(tmp_path, kb_path=kb_path)
        config = Config(base_path=str(kb_path))
        quality = stage._check_quality_gates(config)

        assert quality['class_count'] == 1
        assert quality['function_count'] == 1
        # symbol_reference_count 仍为 0，所以 quality_passed 依然 False
        assert quality['symbol_reference_count'] == 0
        assert quality['quality_passed'] is False


# ---------------------------------------------------------------------------
# 新增测试: SymbolReferenceIndex source_root 支持
# ---------------------------------------------------------------------------

class TestSymbolReferenceIndexSourceRoot:
    """验证 build_from_indices 通过 source_root 正确解析相对路径读取函数体"""

    def _make_function_db(self, db_path: Path, impl_rel_posix: str, impl_line: int) -> None:
        """构造最小 function_index.db，含一个有 impl_file_path 的 Caller 和一个无 impl 的 Callee"""
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS function_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                class_name TEXT,
                module TEXT,
                file_path TEXT,
                line_number INTEGER,
                impl_file_path TEXT,
                impl_line_number INTEGER,
                return_type TEXT,
                parameters TEXT,
                signature TEXT,
                is_virtual INTEGER DEFAULT 0,
                is_const INTEGER DEFAULT 0,
                is_static INTEGER DEFAULT 0,
                is_override INTEGER DEFAULT 0,
                is_blueprint_callable INTEGER DEFAULT 0,
                ufunction_specifiers TEXT DEFAULT '{}'
            );
        """)
        # Caller: 有 impl，impl_file_path 是相对 POSIX 路径
        conn.execute(
            "INSERT INTO function_index (name, class_name, module, file_path, line_number,"
            " impl_file_path, impl_line_number, return_type, parameters, signature)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Caller", "Foo", "TestModule", "Source/Foo.h", 10,
             impl_rel_posix, impl_line, "void", "[]", "void Foo::Caller()"),
        )
        # Callee: 只声明，无 impl
        conn.execute(
            "INSERT INTO function_index (name, class_name, module, file_path, line_number,"
            " impl_file_path, impl_line_number, return_type, parameters, signature)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Callee", "Foo", "TestModule", "Source/Foo.h", 20,
             "", 0, "void", "[]", "void Foo::Callee()"),
        )
        conn.commit()
        conn.close()

    def test_build_with_source_root_resolves_relative_impl_path(self, tmp_path):
        """构造 source_root + 相对路径 impl_file_path，断言 rows_inserted>0 且 occurrence_file 为相对路径"""
        from ue5_kb.core.symbol_reference_index import SymbolReferenceIndex

        # 构造源码文件: source_root/Source/Foo.cpp
        source_root = tmp_path / "plugin_src"
        cpp_dir = source_root / "Source"
        cpp_dir.mkdir(parents=True)
        cpp_file = cpp_dir / "Foo.cpp"
        cpp_file.write_text(
            "void Foo::Caller()\n"
            "{\n"
            "    Callee();\n"
            "}\n",
            encoding="utf-8",
        )

        # 相对 POSIX 路径（DB 中存储格式）
        impl_rel_posix = "Source/Foo.cpp"

        # 构造 function_index.db（impl_line=1，对应函数定义首行）
        gi_dir = tmp_path / "global_index"
        gi_dir.mkdir()
        fi_db = gi_dir / "function_index.db"
        ci_db = gi_dir / "class_index.db"
        # class_index 可为空
        sqlite3.connect(str(ci_db)).close()

        self._make_function_db(fi_db, impl_rel_posix, impl_line=1)

        sr_db = str(gi_dir / "symbol_reference_index.db")
        idx = SymbolReferenceIndex(sr_db)
        try:
            stats = idx.build_from_indices(
                str(fi_db), str(ci_db), source_root=source_root
            )
            callees = idx.query_callees("Caller", "Foo")
        finally:
            idx.close()

        assert stats["rows_inserted"] > 0, f"应插入引用记录，但 rows_inserted={stats['rows_inserted']}"
        assert stats["callers_skipped"] == 0, f"不应跳过 caller，但 callers_skipped={stats['callers_skipped']}"
        callee_names = [r["target_symbol"] for r in callees]
        assert "Callee" in callee_names, f"query_callees 应返回 Callee，实际: {callee_names}"
        # occurrence_file 应保持相对路径（不是绝对路径）
        for row in callees:
            occ = row["occurrence_file"]
            assert not Path(occ).is_absolute(), f"occurrence_file 应为相对路径，实际: {occ!r}"

    def test_function_body_cache_reuses_same_impl_file_scan(self, tmp_path):
        """同一个 impl_file 的多个函数体切片不应重复读取或扫描整文件。"""
        from ue5_kb.core.symbol_reference_index import _SourceFileFunctionBodyCache

        source_root = tmp_path / "plugin_src"
        cpp_dir = source_root / "Source"
        cpp_dir.mkdir(parents=True)
        (cpp_dir / "Foo.cpp").write_text(
            "void Foo::First()\n"
            "{\n"
            "    Second();\n"
            "}\n"
            "\n"
            "void Foo::Second()\n"
            "{\n"
            "}\n",
            encoding="utf-8",
        )

        cache = _SourceFileFunctionBodyCache(source_root=source_root)
        first_body, first_start = cache.slice_function_body("Source/Foo.cpp", 1)
        second_body, second_start = cache.slice_function_body("Source/Foo.cpp", 6)

        assert first_body is not None
        assert second_body is not None
        assert first_start == 2
        assert second_start == 7
        assert cache.file_read_count == 1
        assert cache.function_scan_count == 1

    def test_build_without_source_root_skips_missing_file(self, tmp_path):
        """不传 source_root，cwd 下无对应文件时，caller 应被跳过（rows_inserted=0）"""
        import os
        from ue5_kb.core.symbol_reference_index import SymbolReferenceIndex

        gi_dir = tmp_path / "global_index"
        gi_dir.mkdir()
        fi_db = gi_dir / "function_index.db"
        ci_db = gi_dir / "class_index.db"
        sqlite3.connect(str(ci_db)).close()

        # impl_file_path 指向一个不存在的相对路径
        self._make_function_db(fi_db, "Source/NonExistent.cpp", impl_line=1)

        sr_db = str(gi_dir / "symbol_reference_index.db")
        # 切换到不含该文件的目录，确保 open(relative) 失败
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            idx = SymbolReferenceIndex(sr_db)
            try:
                stats = idx.build_from_indices(str(fi_db), str(ci_db))
            finally:
                idx.close()
        finally:
            os.chdir(orig_cwd)

        assert stats["rows_inserted"] == 0
        assert stats["callers_skipped"] > 0
