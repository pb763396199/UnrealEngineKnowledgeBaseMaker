"""
P1 修复最小测试

覆盖：
a. AnalyzeStage 传给 CppParser 的 file_path 是相对 POSIX 路径
b. BranchManager register/update/reuse 成功后 active_branch 更新为目标 branch
c. BuildStage._load_graph_file 使用 safe_pickle_load（拒绝恶意 pickle）
"""

import json
import pickle
import sqlite3
import unittest.mock as mock
from pathlib import Path
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# 辅助
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


def _get_active_branch(registry_db: Path) -> Optional[str]:
    conn = sqlite3.connect(str(registry_db))
    row = conn.execute(
        "SELECT value FROM config WHERE key = 'active_branch'"
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 测试 a: AnalyzeStage 传给 CppParser 的 path 是相对 POSIX 路径
# ---------------------------------------------------------------------------

class TestAnalyzeStageRelativePaths:

    def test_serial_passes_relative_posix_path(self, tmp_path):
        """串行模式：parser 收到的 file_path 应是相对 base_path 的 POSIX 路径"""
        from ue5_kb.pipeline.analyze import AnalyzeStage

        base_path = tmp_path / "engine"
        base_path.mkdir()
        module_dir = base_path / "Source" / "Runtime" / "MyMod"
        module_dir.mkdir(parents=True)
        src_file = module_dir / "MyClass.h"
        src_file.write_text("class AMyActor {};", encoding="utf-8")

        stage = AnalyzeStage(base_path)

        captured_paths = []

        class CapturingParser:
            def extract_classes(self, content, file_path):
                captured_paths.append(("class", file_path))
                return []

            def extract_functions(self, content, file_path):
                captured_paths.append(("func", file_path))
                return []

            def extract_enums(self, content, file_path):
                captured_paths.append(("enum", file_path))
                return []

        stage._analyze_module(
            module_name="MyMod",
            source_files=[src_file],
            parser=CapturingParser(),
            verbose=False,
            use_incremental=False,
        )

        assert len(captured_paths) > 0, "Parser 没有被调用"
        expected = src_file.relative_to(base_path).as_posix()
        for kind, path in captured_paths:
            assert not Path(path).is_absolute(), \
                f"{kind} file_path 不应是绝对路径: {path!r}"
            assert "\\" not in path, \
                f"{kind} file_path 不应含反斜杠: {path!r}"
            assert path == expected, \
                f"{kind} file_path={path!r}, expected={expected!r}"

    def test_parallel_worker_passes_relative_posix_path(self, tmp_path):
        """并行 worker：parser 收到的 file_path 和 impl_file_path 应是相对 POSIX 路径"""
        from ue5_kb.pipeline import analyze_parallel

        base_path = tmp_path / "engine"
        module_dir = base_path / "Source" / "Runtime" / "ParallelMod"
        module_dir.mkdir(parents=True)
        src_file = module_dir / "ParallelThing.cpp"
        src_file.write_text("void FParallelThing::DoWork() {}", encoding="utf-8")

        captured_paths = []

        class CapturingParser:
            def extract_classes(self, content, file_path):
                captured_paths.append(("class", file_path))
                return []

            def extract_functions(self, content, file_path):
                captured_paths.append(("func", file_path))
                return [{
                    "name": "DoWork",
                    "class_name": "FParallelThing",
                    "file_path": file_path,
                    "impl_file_path": file_path,
                }]

            def extract_enums(self, content, file_path):
                captured_paths.append(("enum", file_path))
                return []

        args = (
            "ParallelMod",
            str(module_dir),
            str(tmp_path / "kb" / "data" / "analyze"),
            0,
            False,
            str(base_path),
        )

        with mock.patch.object(analyze_parallel, "CppParser", return_value=CapturingParser()):
            result = analyze_parallel._analyze_module_worker(args)

        assert result.get("status") == "success", result
        expected = src_file.relative_to(base_path).as_posix()
        for kind, path in captured_paths:
            assert not Path(path).is_absolute(), f"{kind} file_path 不应是绝对路径: {path!r}"
            assert "\\" not in path, f"{kind} file_path 不应含反斜杠: {path!r}"
            assert path == expected
        output_file = tmp_path / "kb" / "data" / "analyze" / "ParallelMod" / "code_graph.json"
        output_data = json.loads(output_file.read_text(encoding="utf-8"))
        assert output_data["functions"][0]["file_path"] == expected
        assert output_data["functions"][0]["impl_file_path"] == expected


class TestIndexPathNormalization:

    def test_discover_module_path_is_relative_posix(self, tmp_path):
        """DiscoverStage 写入的模块 path 应是相对 POSIX 路径"""
        from ue5_kb.pipeline.discover import DiscoverStage

        base_path = tmp_path / "plugin"
        module_dir = base_path / "Source" / "MyModule"
        module_dir.mkdir(parents=True)
        build_cs = module_dir / "MyModule.Build.cs"
        build_cs.write_text("public class MyModule {}", encoding="utf-8")

        stage = DiscoverStage(base_path)
        modules = stage._scan_directory(base_path / "Source")

        assert modules[0]["path"] == "Source/MyModule/MyModule.Build.cs"
        assert modules[0]["absolute_path"] == "Source/MyModule/MyModule.Build.cs"
        assert "\\" not in modules[0]["path"]
        assert "\\" not in modules[0]["absolute_path"]
        assert not Path(modules[0]["path"]).is_absolute()
        assert not Path(modules[0]["absolute_path"]).is_absolute()

    def test_stage_result_metadata_does_not_store_absolute_source_path(self, tmp_path):
        """PipelineStage.save_result 的 metadata 不应写入源绝对路径"""
        from ue5_kb.pipeline.discover import DiscoverStage

        base_path = tmp_path / "plugin"
        base_path.mkdir()
        kb_path = tmp_path / "kb"
        stage = DiscoverStage(base_path, kb_path=kb_path)

        stage.save_result({"ok": True}, "result.json")

        saved = json.loads((kb_path / "data" / "discover" / "result.json").read_text(encoding="utf-8"))
        assert saved["_metadata"]["base_path"] == "plugin"
        assert str(base_path) not in json.dumps(saved)

    def test_config_file_persists_relative_paths(self, tmp_path):
        """config.yaml 不应写入 KB 根目录的机器绝对路径"""
        from ue5_kb.core.config import Config

        kb_path = tmp_path / "kb"
        config = Config(base_path=str(kb_path))
        config.save()

        config_text = (kb_path / "config.yaml").read_text(encoding="utf-8")
        assert "base_path: ." in config_text
        assert str(kb_path) not in config_text
        assert Path(config.storage_base_path).is_absolute()
        assert Path(config.global_index_path).is_absolute()

    def test_pipeline_state_summary_uses_path_labels(self, tmp_path):
        """.pipeline_state 的摘要不应写入本机绝对路径"""
        from ue5_kb.pipeline.state import PipelineState

        base_path = tmp_path / "plugin"
        kb_path = tmp_path / "variants" / "abc123"
        skill_path = tmp_path / "skills" / "AesWorld-kb"

        state = PipelineState(base_path, kb_path=kb_path)
        state.mark_completed(
            "build",
            {
                "kb_path": str(kb_path),
                "skill_path": str(skill_path),
                "total_count": 1,
            },
        )

        state_text = (kb_path / ".pipeline_state").read_text(encoding="utf-8")
        assert str(tmp_path) not in state_text
        assert "abc123" in state_text
        assert "AesWorld-kb" in state_text

    def test_build_summary_uses_kb_path_label(self, tmp_path, monkeypatch):
        """build_summary.json 不应写入构建临时目录绝对路径"""
        from ue5_kb.pipeline.build import BuildStage

        class DummyGlobalIndex:
            def get_statistics(self):
                return {"total_modules": 0}

        base_path = tmp_path / "plugin"
        base_path.mkdir()
        kb_path = tmp_path / "variants" / "abc123"
        stage = BuildStage(base_path, kb_path=kb_path)

        monkeypatch.setattr(stage, "_create_config", lambda path: object())
        monkeypatch.setattr(stage, "_build_global_index", lambda config: DummyGlobalIndex())
        monkeypatch.setattr(stage, "_build_module_graphs", lambda path: 0)
        monkeypatch.setattr(stage, "_build_fast_indices", lambda config: None)
        monkeypatch.setattr(stage, "_save_kb_manifest", lambda path, stats: None)

        result = stage._run_serial()

        summary = json.loads((kb_path / "data" / "build" / "build_summary.json").read_text(encoding="utf-8"))
        assert result["kb_path"] == "abc123"
        assert summary["kb_path"] == "abc123"
        assert str(kb_path) not in json.dumps(summary)

    def test_extract_manifest_accepts_relative_source_path(self, tmp_path):
        """ExtractStage 应能用相对 absolute_path 还原源路径，manifest 文件路径保持 POSIX"""
        from ue5_kb.pipeline.extract import ExtractStage

        base_path = tmp_path / "plugin"
        module_dir = base_path / "Source" / "MyModule"
        module_dir.mkdir(parents=True)
        build_cs = module_dir / "MyModule.Build.cs"
        build_cs.write_text("public class MyModule {}", encoding="utf-8")
        source_file = module_dir / "MyClass.h"
        source_file.write_text("class FMyClass {};", encoding="utf-8")
        kb_path = tmp_path / "kb"
        output_dir = kb_path / "data" / "extract" / "MyModule"
        output_dir.mkdir(parents=True)

        stage = ExtractStage(base_path, kb_path=kb_path)
        stage._create_module_manifest(
            "MyModule",
            {
                "path": "Source/MyModule/MyModule.Build.cs",
                "absolute_path": "Source/MyModule/MyModule.Build.cs",
                "category": "Runtime",
            },
            output_dir,
        )

        manifest = json.loads((output_dir / "module_manifest.json").read_text(encoding="utf-8"))
        assert manifest["build_cs_path"] == "Source/MyModule/MyModule.Build.cs"
        assert "Source/MyModule/MyClass.h" in manifest["files"]
        assert manifest["files"]["Source/MyModule/MyClass.h"]["path"] == "Source/MyModule/MyClass.h"
        assert str(base_path) not in json.dumps(manifest)

    def test_build_sqlite_module_path_is_relative_posix(self, tmp_path):
        """BuildStage 同步 modules.path 时应兜底转成 POSIX"""
        from ue5_kb.core.config import Config
        from ue5_kb.core.global_index import GlobalIndex
        from ue5_kb.pipeline.build import BuildStage

        base_path = tmp_path / "plugin"
        base_path.mkdir()
        kb_path = tmp_path / "kb"
        config = Config(base_path=str(kb_path))
        global_index = GlobalIndex(config)
        global_index.add_module("MyModule", {
            "name": "MyModule",
            "path": "Source\\MyModule\\MyModule.Build.cs",
            "category": "Runtime",
            "dependencies": [],
        })

        stage = BuildStage(base_path, kb_path=kb_path)
        stage._sync_to_sqlite(global_index, config)

        conn = sqlite3.connect(str(kb_path / "global_index" / "index.db"))
        row = conn.execute("SELECT path FROM modules WHERE name = 'MyModule'").fetchone()
        conn.close()

        assert row[0] == "Source/MyModule/MyModule.Build.cs"
        assert "\\" not in row[0]
        assert not Path(row[0]).is_absolute()

    def test_kb_manifest_metadata_does_not_store_absolute_source_path(self, tmp_path):
        """KB manifest/metadata 不应写入源项目绝对路径"""
        from ue5_kb.pipeline.build import BuildStage

        base_path = tmp_path / "plugin"
        base_path.mkdir()
        kb_path = tmp_path / "kb"
        (kb_path / "global_index").mkdir(parents=True)

        stage = BuildStage(base_path, kb_path=kb_path)
        stage._save_kb_manifest(kb_path, {"total_modules": 0})

        manifest = json.loads((kb_path / ".kb_manifest.json").read_text(encoding="utf-8"))
        assert manifest["engine_path"] == "plugin"
        assert str(base_path) not in json.dumps(manifest)

        conn = sqlite3.connect(str(kb_path / "global_index" / "index.db"))
        metadata = dict(conn.execute("SELECT key, value FROM metadata"))
        conn.close()

        assert metadata["engine_path"] == "plugin"
        assert str(base_path) not in json.dumps(metadata)


# ---------------------------------------------------------------------------
# 测试 b: BranchManager active_branch 语义
# ---------------------------------------------------------------------------

class TestBranchManagerActiveBranch:

    def _make_complete_kb(self, store: Path, kb_dir: str) -> Path:
        kb_path = store / kb_dir
        kb_path.mkdir(parents=True, exist_ok=True)
        (kb_path / "dummy.txt").write_text("dummy")
        return kb_path

    def _setup_registry_with_existing_kb(self, tmp_path):
        """创建带已完整 KB 的 registry，模拟 commit 已存在场景"""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        commit_id = "abc1234567890000"
        kb_dir = "abc1234"
        self._make_complete_kb(variants_dir, kb_dir)

        conn = sqlite3.connect(str(registry_db))
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status) VALUES (?, ?, 'complete')",
            (commit_id, kb_dir),
        )
        # 预先设置 active_branch 为 OTHER 分支
        conn.execute(
            "INSERT OR REPLACE INTO config VALUES ('active_branch', 'other_branch')"
        )
        conn.commit()
        conn.close()
        return skill_dir, registry_db, variants_dir, commit_id

    def test_register_reuse_updates_active_branch(self, tmp_path):
        """register 复用路径：即使 active_branch 已存在，也应更新为当前 branch"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir, registry_db, variants_dir, commit_id = \
            self._setup_registry_with_existing_kb(tmp_path)

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "Dummy.uplugin").write_text("{}")
        fake_kb = source_dir / "KnowledgeBase"
        fake_kb.mkdir()

        mgr = BranchManager(skill_dir)

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = commit_id
        mock_vcs.get_type.return_value = "git"

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr.register(
                branch="new_branch",
                source=str(source_dir),
                kb_path=str(fake_kb),
            )

        assert result.get("status") == "ok", f"register 失败: {result}"
        assert result.get("reused") is True
        active = _get_active_branch(registry_db)
        assert active == "new_branch", \
            f"active_branch 应为 'new_branch'，实际为 {active!r}"

    def test_register_new_import_updates_active_branch(self, tmp_path):
        """register 新导入路径：active_branch 应更新为新 branch（覆盖原有）"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill2"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        # 预先设置 active_branch 为 old
        conn = sqlite3.connect(str(registry_db))
        conn.execute("INSERT OR REPLACE INTO config VALUES ('active_branch', 'old_branch')")
        conn.commit()
        conn.close()

        source_dir = tmp_path / "src2"
        source_dir.mkdir()
        (source_dir / "Dummy.uplugin").write_text("{}")
        fake_kb = source_dir / "KnowledgeBase"
        fake_kb.mkdir()
        (fake_kb / "global_index").mkdir()

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = "freshcommit0001"
        mock_vcs.get_type.return_value = "git"

        mgr = BranchManager(skill_dir)

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr.register(
                branch="feature_x",
                source=str(source_dir),
                kb_path=str(fake_kb),
            )

        assert result.get("status") == "ok", f"register 失败: {result}"
        active = _get_active_branch(registry_db)
        assert active == "feature_x", \
            f"active_branch 应为 'feature_x'，实际为 {active!r}"

    def test_update_reuse_updates_active_branch(self, tmp_path):
        """update 复用路径：即使 active_branch 已有值，也应更新为当前 branch"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir, registry_db, variants_dir, commit_id = \
            self._setup_registry_with_existing_kb(tmp_path)

        source_dir = tmp_path / "src3"
        source_dir.mkdir()
        (source_dir / "MyPlugin.uplugin").write_text("{}")

        mgr = BranchManager(skill_dir)

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = commit_id
        mock_vcs.get_type.return_value = "git"
        mock_vcs.is_dirty.return_value = False

        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr.update(
                branch="update_branch",
                source=str(source_dir),
                force=False,
            )

        assert result.get("status") == "ok", f"update 失败: {result}"
        assert result.get("reused") is True
        active = _get_active_branch(registry_db)
        assert active == "update_branch", \
            f"active_branch 应为 'update_branch'，实际为 {active!r}"


# ---------------------------------------------------------------------------
# 测试 c: BuildStage._load_graph_file 使用 safe pickle
# ---------------------------------------------------------------------------

class TestBuildStageLoadGraphFileSafePickle:

    def test_rejects_malicious_pickle(self, tmp_path):
        """_load_graph_file 应拒绝含危险类型的 pickle 文件"""
        from ue5_kb.pipeline.build import BuildStage

        stage = BuildStage(tmp_path)

        # 构造恶意 pickle：使用 os.system（在 builtins deny-list 或非白名单模块）
        class _Evil:
            def __reduce__(self):
                import os
                return (os.system, ("echo pwned",))

        evil_data = pickle.dumps({"graph": _Evil()})
        evil_file = tmp_path / "evil_module.pkl"
        evil_file.write_bytes(evil_data)

        result = stage._load_graph_file(evil_file)
        # 应返回 None（加载失败被 except 捕获）而不是执行恶意代码
        assert result is None, \
            f"_load_graph_file 应对恶意 pickle 返回 None，实际返回: {result}"

    def test_loads_safe_networkx_graph(self, tmp_path):
        """_load_graph_file 应正确加载合法的 networkx 图谱"""
        import networkx as nx
        from ue5_kb.pipeline.build import BuildStage

        stage = BuildStage(tmp_path)

        # 构造合法图谱
        g = nx.DiGraph()
        g.add_node("MyClass", type="class", name="MyClass")
        data = {"graph": g}

        graph_file = tmp_path / "MyModule.pkl"
        with open(graph_file, "wb") as f:
            pickle.dump(data, f)

        result = stage._load_graph_file(graph_file)
        assert result is not None, "_load_graph_file 不应对合法 pickle 返回 None"
        module_name, graph = result
        assert module_name == "MyModule"
        assert "MyClass" in graph.nodes

    def test_uses_safe_pickle_load(self, tmp_path):
        """_load_graph_file 使用 safe_pickle_load：合法图谱能正确加载"""
        import networkx as nx
        from ue5_kb.pipeline.build import BuildStage

        stage = BuildStage(tmp_path)

        g = nx.DiGraph()
        g.add_node("NodeA")
        data = {"graph": g}
        graph_file = tmp_path / "TestMod.pkl"
        with open(graph_file, "wb") as f:
            pickle.dump(data, f)

        # 用 safe_pickle_load 的副作用验证：调用 branch_manager.safe_pickle_load
        import ue5_kb.branch_manager as bm_mod
        original_safe = bm_mod.safe_pickle_load
        call_record = []

        def tracking_safe(f):
            call_record.append(True)
            return original_safe(f)

        with mock.patch.object(bm_mod, "safe_pickle_load", tracking_safe):
            result = stage._load_graph_file(graph_file)

        assert result is not None, "合法 pickle 应能加载"
        # tracking_safe 被调用 → _load_graph_file 用的是 safe_pickle_load
        assert len(call_record) == 1, \
            "safe_pickle_load 应被调用一次"


# ---------------------------------------------------------------------------
# P2 回归测试 d: analyze cache 文件名使用 POSIX 平铺格式
# ---------------------------------------------------------------------------

class TestAnalyzeCacheWindowsPath:
    """
    验证 analyze 阶段的增量缓存在 Windows 路径下不产生嵌套目录：
    - manifest 的 rel_path key 是 POSIX 格式（无反斜杠）
    - 写入的 cache 文件名是 POSIX 格式 replace('/', '_')（平铺，不含反斜杠）
    """

    def test_cache_filename_uses_posix_flat_name(self, tmp_path):
        """cache 文件名应使用 POSIX 平铺格式，不包含反斜杠导致的子目录"""
        from ue5_kb.pipeline.analyze import AnalyzeStage
        from ue5_kb.core.manifest import ModuleManifest, FileInfo, Hasher

        base_path = tmp_path / "engine"
        module_dir = base_path / "Source" / "Runtime" / "CacheMod"
        module_dir.mkdir(parents=True)
        src_file = module_dir / "Cached.h"
        src_file.write_text("class ACached {};", encoding="utf-8")

        stage = AnalyzeStage(base_path)

        # 构造 manifest：key 用 POSIX 路径，hash 与实际文件一致（触发缓存命中）
        posix_rel = src_file.relative_to(base_path).as_posix()
        real_hash = Hasher.compute_sha256(src_file)

        manifest = ModuleManifest(
            module_name="CacheMod",
            build_cs_path="Source/Runtime/CacheMod/CacheMod.Build.cs",
            category="Runtime",
        )
        manifest.files[posix_rel] = FileInfo(path=posix_rel, sha256=real_hash, size=0, mtime=0.0)

        # 预写一份有效 cache 文件（平铺名）
        module_cache_dir = stage.stage_dir / "CacheMod"
        module_cache_dir.mkdir(parents=True, exist_ok=True)
        flat_name = posix_rel.replace('/', '_')
        cache_file = module_cache_dir / f"cache_{flat_name}.json"
        cache_file.write_text(
            json.dumps({"classes": [{"name": "ACached"}], "functions": [], "enums": []}),
            encoding="utf-8",
        )

        # 写入 manifest
        manifest_file = stage.stage_dir / "CacheMod" / "module_manifest.json"
        manifest_file.write_text(
            json.dumps(manifest.to_dict()), encoding="utf-8"
        )

        class DummyParser:
            def extract_classes(self, content, fp): return []
            def extract_functions(self, content, fp): return []
            def extract_enums(self, content, fp): return []

        result = stage._analyze_module(
            module_name="CacheMod",
            source_files=[src_file],
            parser=DummyParser(),
            verbose=False,
            use_incremental=True,
        )

        # 命中缓存：解析文件数为 0，跳过数为 1
        assert result["skipped_file_count"] == 1, \
            "hash 未变更时应命中缓存，skipped=1"
        assert result["parsed_file_count"] == 0, \
            "hash 未变更时应跳过解析，parsed=0"
        # 缓存文件路径：平铺名，不应产生额外子目录
        assert "\\" not in flat_name, f"平铺文件名不应含反斜杠: {flat_name!r}"
        assert cache_file.exists(), f"预写 cache 文件应存在: {cache_file}"

    def test_manifest_key_has_no_backslash(self, tmp_path):
        """manifest 中的 rel_path key 在 POSIX 化后不含反斜杠"""
        from ue5_kb.core.manifest import Hasher

        base_path = tmp_path / "engine"
        src_file = base_path / "Source" / "Runtime" / "Mod" / "Foo.h"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("class AFoo{};")

        posix_rel = src_file.relative_to(base_path).as_posix()
        assert "\\" not in posix_rel, \
            f"POSIX rel_path 不应含反斜杠: {posix_rel!r}"
        assert "/" in posix_rel, \
            f"POSIX rel_path 应含正斜杠: {posix_rel!r}"
        flat = posix_rel.replace('/', '_')
        assert "\\" not in flat, \
            f"平铺 cache 名不应含反斜杠: {flat!r}"


# ---------------------------------------------------------------------------
# P2 回归测试 e: LayeredQueryInterface source_root 参数
# ---------------------------------------------------------------------------

class TestLayeredQuerySourceRoot:
    """
    验证 LayeredQueryInterface(kb_path, source_root=...) 能从外置源码目录读取源码，
    且不传 source_root 时不从 variants.parent 误读源码。
    """

    def _make_class_index_db(self, db_path: Path, class_name: str, file_path: str) -> None:
        """创建最小 class_index.db，写入一条类记录"""
        from ue5_kb.core.class_index import ClassIndex
        idx = ClassIndex(str(db_path))
        idx.add_class({
            "name": class_name,
            "module": "TestMod",
            "file_path": file_path,
            "line_number": 1,
        })
        idx.close()

    def test_with_source_root_reads_source(self, tmp_path):
        """提供 source_root 时，_load_source_code 应从 source_root 下正确定位文件"""
        from ue5_kb.query.layered_query import LayeredQueryInterface

        # kb_path 放在 variants/hash 子目录（模拟外置 skill）
        kb_path = tmp_path / "skill" / "variants" / "abc1234" / "KnowledgeBase"
        global_index_dir = kb_path / "global_index"
        global_index_dir.mkdir(parents=True)

        # source_root 是独立的插件目录
        source_root = tmp_path / "plugin_src"
        source_root.mkdir()
        src_file = source_root / "Source" / "Foo.h"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("class AFoo {};", encoding="utf-8")

        # DB 中存储 POSIX 相对路径
        db_path = global_index_dir / "class_index.db"
        self._make_class_index_db(db_path, "AFoo", "Source/Foo.h")

        lqi = LayeredQueryInterface(str(kb_path), source_root=source_root)
        source = lqi._load_source_code("AFoo")

        assert "AFoo" in source, \
            f"应读取到源码内容，实际: {source!r}"
        assert "// 源文件不存在" not in source, \
            f"source_root 正确时不应返回文件不存在: {source!r}"

    def test_without_source_root_does_not_find_source(self, tmp_path):
        """不提供 source_root 时，相对路径从 kb_path.parent 解析，应找不到独立插件的源文件"""
        from ue5_kb.query.layered_query import LayeredQueryInterface

        kb_path = tmp_path / "skill" / "variants" / "abc1234" / "KnowledgeBase"
        global_index_dir = kb_path / "global_index"
        global_index_dir.mkdir(parents=True)

        # 源文件放在与 kb_path 不相关的独立目录
        source_root = tmp_path / "unrelated_plugin"
        source_root.mkdir()
        (source_root / "Source").mkdir()
        (source_root / "Source" / "Bar.h").write_text("class ABar {};")

        db_path = global_index_dir / "class_index.db"
        self._make_class_index_db(db_path, "ABar", "Source/Bar.h")

        lqi = LayeredQueryInterface(str(kb_path))  # 不传 source_root
        source = lqi._load_source_code("ABar")

        # kb_path.parent / "Source/Bar.h" 不存在（源文件在独立目录），应返回不存在提示
        assert "ABar" not in source, \
            f"不传 source_root 时不应读到独立插件的源码，实际: {source!r}"

    def test_source_root_handles_windows_backslash_in_db(self, tmp_path):
        """DB 中存储 Windows 反斜杠路径时，source_root 解析应仍能找到文件"""
        from ue5_kb.query.layered_query import LayeredQueryInterface

        kb_path = tmp_path / "kb"
        (kb_path / "global_index").mkdir(parents=True)
        source_root = tmp_path / "plugin"
        source_root.mkdir()
        (source_root / "Source").mkdir()
        (source_root / "Source" / "Baz.h").write_text("class ABaz {};")

        db_path = kb_path / "global_index" / "class_index.db"
        # 模拟 DB 里存了 Windows 反斜杠路径
        self._make_class_index_db(db_path, "ABaz", "Source\\Baz.h")

        lqi = LayeredQueryInterface(str(kb_path), source_root=source_root)
        source = lqi._load_source_code("ABaz")

        assert "ABaz" in source, \
            f"DB 中反斜杠路径应被规范化后正确找到源文件，实际: {source!r}"


# ---------------------------------------------------------------------------
# P2 回归测试 f: engine impl.py.template 文本验证
# ---------------------------------------------------------------------------

class TestEngineImplTemplate:
    """验证 templates/impl.py.template 对齐 plugin 模板，使用 BranchManager"""

    def _read_template(self) -> str:
        from pathlib import Path
        tpl = Path(__file__).parent.parent / "templates" / "impl.py.template"
        return tpl.read_text(encoding="utf-8")

    def test_contains_branch_manager_import(self):
        """模板应包含 BranchManager 导入"""
        content = self._read_template()
        assert "BranchManager" in content, \
            "impl.py.template 应导入 BranchManager"

    def test_contains_resolve_kb_path_with_variant(self):
        """模板 _resolve_kb_path 应接受 variant 参数并委托 BranchManager"""
        content = self._read_template()
        assert "resolve_kb_path(variant" in content, \
            "impl.py.template _resolve_kb_path 应委托 branch_mgr.resolve_kb_path(variant)"

    def test_no_inline_sql_commit_id(self):
        """模板不应包含手写 SELECT commit_id FROM branches 等内联 SQL"""
        content = self._read_template()
        assert "SELECT commit_id FROM branches" not in content, \
            "impl.py.template 不应有 'SELECT commit_id FROM branches' 内联 SQL（应委托 BranchManager）"

    def test_no_duplicate_safe_unpickler(self):
        """模板不应定义重复的 SafeUnpickler 类（应从 branch_manager 导入）"""
        content = self._read_template()
        assert "class SafeUnpickler" not in content, \
            "impl.py.template 不应定义 SafeUnpickler（应从 ue5_kb.branch_manager 导入 safe_pickle_load）"

    def test_fallback_kb_path_present(self):
        """模板应保留 _FALLBACK_KB_PATH 向后兼容"""
        content = self._read_template()
        assert "_FALLBACK_KB_PATH" in content, \
            "impl.py.template 应保留 _FALLBACK_KB_PATH 回退路径"


# ---------------------------------------------------------------------------
# 测试 g: BranchManager.resolve_source_path
# ---------------------------------------------------------------------------

class TestBranchManagerResolveSourcePath:

    def _make_registry_with_source(
        self, skill_dir: Path, branch: str, commit_id: str, source_path: str
    ) -> None:
        """构造带 source_path 的 registry/versions/branches/config"""
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir(parents=True, exist_ok=True)
        db_path = skill_dir / "registry.db"
        _make_registry(db_path, str(variants_dir))

        conn = sqlite3.connect(str(db_path))
        kb_dir = commit_id[:7]
        (variants_dir / kb_dir).mkdir(exist_ok=True)
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status, source_path) VALUES (?, ?, 'complete', ?)",
            (commit_id, kb_dir, source_path),
        )
        conn.execute(
            "INSERT INTO branches (name, commit_id, status, vcs_type) VALUES (?, ?, 'active', 'git')",
            (branch, commit_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)", (branch,)
        )
        conn.commit()
        conn.close()

    def test_active_branch_returns_source_path(self, tmp_path):
        """resolve_source_path(None) 应返回 active branch 对应的 source_path"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill"
        source_root = tmp_path / "plugin_src"
        self._make_registry_with_source(
            skill_dir, "main", "abc1234567890", str(source_root)
        )

        mgr = BranchManager(skill_dir)
        result = mgr.resolve_source_path()

        assert result == source_root, \
            f"resolve_source_path() 应返回 {source_root}，实际: {result}"

    def test_variant_branch_returns_source_path(self, tmp_path):
        """resolve_source_path(variant) 应返回指定分支的 source_path"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill2"
        source_a = tmp_path / "plugin_a"
        source_b = tmp_path / "plugin_b"

        self._make_registry_with_source(
            skill_dir, "branch_a", "aaaa111122220000", str(source_a)
        )

        # 再插一条 branch_b
        conn = sqlite3.connect(str(skill_dir / "registry.db"))
        variants_dir = skill_dir / "variants"
        kb_dir_b = "bbbb111"
        (variants_dir / kb_dir_b).mkdir(exist_ok=True)
        conn.execute(
            "INSERT INTO versions (commit_id, kb_dir, build_status, source_path) VALUES (?, ?, 'complete', ?)",
            ("bbbb1111222200000", kb_dir_b, str(source_b)),
        )
        conn.execute(
            "INSERT INTO branches (name, commit_id, status, vcs_type) VALUES (?, ?, 'active', 'git')",
            ("branch_b", "bbbb1111222200000"),
        )
        conn.commit()
        conn.close()

        mgr = BranchManager(skill_dir)
        result_b = mgr.resolve_source_path("branch_b")
        result_a = mgr.resolve_source_path("branch_a")

        assert result_b == source_b, \
            f"variant=branch_b 应返回 {source_b}，实际: {result_b}"
        assert result_a == source_a, \
            f"variant=branch_a 应返回 {source_a}，实际: {result_a}"

    def test_empty_source_path_returns_none(self, tmp_path):
        """source_path 为空字符串时应返回 None"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill3"
        self._make_registry_with_source(
            skill_dir, "main", "cccc1234567890ab", ""
        )

        mgr = BranchManager(skill_dir)
        result = mgr.resolve_source_path()

        assert result is None, \
            f"source_path 为空时 resolve_source_path() 应返回 None，实际: {result}"

    def test_registry_missing_raises(self, tmp_path):
        """registry.db 不存在时应 raise FileNotFoundError"""
        from ue5_kb.branch_manager import BranchManager
        import pytest

        skill_dir = tmp_path / "skill4"
        skill_dir.mkdir()

        mgr = BranchManager(skill_dir)
        with pytest.raises(FileNotFoundError):
            mgr.resolve_source_path()


# ---------------------------------------------------------------------------
# 测试 h: 两个 impl template 的文本校验
# ---------------------------------------------------------------------------

class TestImplTemplateSourceRootText:
    """验证两个 impl 模板都包含 source path 相关代码，且修复了 os.path.exists(impl_file) 问题"""

    def _read_engine_template(self) -> str:
        from pathlib import Path
        tpl = Path(__file__).parent.parent / "templates" / "impl.py.template"
        return tpl.read_text(encoding="utf-8")

    def _read_plugin_template(self) -> str:
        from pathlib import Path
        tpl = Path(__file__).parent.parent / "templates" / "impl.plugin.py.template"
        return tpl.read_text(encoding="utf-8")

    def test_engine_template_has_resolve_source_path(self):
        content = self._read_engine_template()
        assert "resolve_source_path" in content, \
            "impl.py.template 应包含 resolve_source_path 调用"

    def test_engine_template_has_source_root(self):
        content = self._read_engine_template()
        assert "SOURCE_ROOT" in content, \
            "impl.py.template 应包含 SOURCE_ROOT"

    def test_engine_template_has_resolve_source_file(self):
        content = self._read_engine_template()
        assert "_resolve_source_file" in content, \
            "impl.py.template 应包含 _resolve_source_file"

    def test_engine_template_no_os_path_exists_impl_file(self):
        content = self._read_engine_template()
        assert "os.path.exists(impl_file)" not in content, \
            "impl.py.template get_function_implementation 不应再直接用 os.path.exists(impl_file)"

    def test_plugin_template_has_resolve_source_path(self):
        content = self._read_plugin_template()
        assert "resolve_source_path" in content, \
            "impl.plugin.py.template 应包含 resolve_source_path 调用"

    def test_plugin_template_has_source_root(self):
        content = self._read_plugin_template()
        assert "SOURCE_ROOT" in content, \
            "impl.plugin.py.template 应包含 SOURCE_ROOT"

    def test_plugin_template_has_resolve_source_file(self):
        content = self._read_plugin_template()
        assert "_resolve_source_file" in content, \
            "impl.plugin.py.template 应包含 _resolve_source_file"

    def test_plugin_template_no_os_path_exists_impl_file(self):
        content = self._read_plugin_template()
        assert "os.path.exists(impl_file)" not in content, \
            "impl.plugin.py.template get_function_implementation 不应再直接用 os.path.exists(impl_file)"


# ---------------------------------------------------------------------------
# 测试 i: BranchManager update prune + update_all
# ---------------------------------------------------------------------------

class TestBranchManagerUpdatePruneAndUpdateAll:

    def _insert_version_and_branch(
        self,
        registry_db: Path,
        variants_dir: Path,
        branch: str,
        commit_id: str,
        source_path: Optional[str],
        kb_dir: Optional[str] = None,
    ) -> str:
        if kb_dir is None:
            kb_dir = commit_id[:7]
        kb_path = variants_dir / kb_dir
        kb_path.mkdir(parents=True, exist_ok=True)
        (kb_path / "dummy.txt").write_text(f"{branch}-{commit_id}", encoding="utf-8")

        conn = sqlite3.connect(str(registry_db))
        conn.execute(
            "INSERT OR REPLACE INTO versions (commit_id, kb_dir, build_status, source_path) VALUES (?, ?, 'complete', ?)",
            (commit_id, kb_dir, source_path),
        )
        conn.execute(
            "INSERT OR REPLACE INTO branches (name, commit_id, status, vcs_type, updated_at) VALUES (?, ?, 'active', 'git', datetime('now'))",
            (branch, commit_id),
        )
        conn.commit()
        conn.close()
        return kb_dir

    def test_update_new_commit_prunes_previous_branch_version(self, tmp_path):
        """同 branch 更新到新 commit 且旧 commit 无引用时，清理旧 version 与目录"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_prune"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        old_commit = "1111111abcdef00"
        new_commit = "2222222abcdef00"
        old_kb_dir = self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "DEV",
            old_commit,
            source_path=str(tmp_path / "plugin_src"),
            kb_dir="oldkb01",
        )

        source_dir = tmp_path / "plugin_src"
        source_dir.mkdir(parents=True)
        (source_dir / "MyPlugin.uplugin").write_text("{}", encoding="utf-8")

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = new_commit
        mock_vcs.get_type.return_value = "git"
        mock_vcs.is_dirty.return_value = False

        def fake_build(plugin_root, kb_output, incremental=False):
            Path(kb_output).mkdir(parents=True, exist_ok=True)
            (Path(kb_output) / "new.txt").write_text("new", encoding="utf-8")
            return {"status": "ok"}

        mgr = BranchManager(skill_dir)
        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs), \
             mock.patch.object(BranchManager, "_build_kb", side_effect=fake_build):
            result = mgr.update("DEV", str(source_dir), force=False)

        assert result.get("status") == "ok", result
        assert result.get("previous_commit") == old_commit[:7]
        assert result.get("pruned_old_version", {}).get("pruned") is True

        conn = sqlite3.connect(str(registry_db))
        dev_row = conn.execute("SELECT commit_id FROM branches WHERE name='DEV'").fetchone()
        old_version = conn.execute("SELECT kb_dir FROM versions WHERE commit_id=?", (old_commit,)).fetchone()
        new_version = conn.execute("SELECT kb_dir FROM versions WHERE commit_id=?", (new_commit,)).fetchone()
        conn.close()

        assert dev_row == (new_commit,)
        assert old_version is None
        assert new_version is not None
        assert not (variants_dir / old_kb_dir).exists()

    def test_update_new_commit_keeps_previous_when_referenced_by_other_branch(self, tmp_path):
        """旧 commit 被其他 branch 引用时，更新后不得删除旧 version/目录"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_keep"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        old_commit = "3333333abcdef00"
        new_commit = "4444444abcdef00"
        old_kb_dir = self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "DEV",
            old_commit,
            source_path=str(tmp_path / "plugin_src2"),
            kb_dir="shared01",
        )
        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "OTHER",
            old_commit,
            source_path=str(tmp_path / "plugin_src2"),
            kb_dir=old_kb_dir,
        )

        source_dir = tmp_path / "plugin_src2"
        source_dir.mkdir(parents=True)
        (source_dir / "MyPlugin.uplugin").write_text("{}", encoding="utf-8")

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = new_commit
        mock_vcs.get_type.return_value = "git"
        mock_vcs.is_dirty.return_value = False

        def fake_build(plugin_root, kb_output, incremental=False):
            Path(kb_output).mkdir(parents=True, exist_ok=True)
            (Path(kb_output) / "new.txt").write_text("new", encoding="utf-8")
            return {"status": "ok"}

        mgr = BranchManager(skill_dir)
        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs), \
             mock.patch.object(BranchManager, "_build_kb", side_effect=fake_build):
            result = mgr.update("DEV", str(source_dir), force=False)

        assert result.get("status") == "ok", result
        assert result.get("pruned_old_version", {}).get("pruned") is False
        assert result.get("pruned_old_version", {}).get("reason") == "still_referenced"

        conn = sqlite3.connect(str(registry_db))
        old_version = conn.execute("SELECT kb_dir FROM versions WHERE commit_id=?", (old_commit,)).fetchone()
        other_row = conn.execute("SELECT commit_id FROM branches WHERE name='OTHER'").fetchone()
        conn.close()

        assert old_version == (old_kb_dir,)
        assert other_row == (old_commit,)
        assert (variants_dir / old_kb_dir).exists()

    def test_update_all_dry_run_reports_stale_branch(self, tmp_path):
        """dry_run 时，registry commit 与源码 commit 不同应标记为 stale"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_dryrun"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        source_dir = tmp_path / "plugin_src3"
        source_dir.mkdir(parents=True)
        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "DEV",
            "5555555abcdef00",
            source_path=str(source_dir),
            kb_dir="dryrun1",
        )

        mock_vcs = mock.MagicMock()
        mock_vcs.get_head_id.return_value = "6666666abcdef00"
        mock_vcs.is_dirty.return_value = False

        mgr = BranchManager(skill_dir)
        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", return_value=mock_vcs):
            result = mgr.update_all(dry_run=True)

        assert result.get("status") == "ok", result
        row = next(r for r in result["results"] if r["branch"] == "DEV")
        assert row["status"] == "stale"
        assert row["needs_update"] is True

    def test_update_all_preserves_active_branch(self, tmp_path):
        """批量更新多个分支后，应恢复调用前的 active_branch"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_preserve_active"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        source_a = tmp_path / "plugin_a"
        source_b = tmp_path / "plugin_b"
        source_a.mkdir(parents=True)
        source_b.mkdir(parents=True)
        (source_a / "MyPlugin.uplugin").write_text("{}", encoding="utf-8")
        (source_b / "MyPlugin.uplugin").write_text("{}", encoding="utf-8")

        old_a = "aaaaaaa11111111"
        old_b = "bbbbbbb11111111"
        new_a = "aaaaaaa22222222"
        new_b = "bbbbbbb22222222"

        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "BRANCH_A",
            old_a,
            source_path=str(source_a),
            kb_dir="a_old",
        )
        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "BRANCH_Z",
            old_b,
            source_path=str(source_b),
            kb_dir="z_old",
        )

        # 预设 active 分支为 BRANCH_A（更新后应恢复）
        conn = sqlite3.connect(str(registry_db))
        conn.execute(
            "INSERT OR REPLACE INTO config VALUES ('active_branch', 'BRANCH_A')"
        )
        conn.commit()
        conn.close()

        def fake_build(plugin_root, kb_output, incremental=False):
            Path(kb_output).mkdir(parents=True, exist_ok=True)
            (Path(kb_output) / "new.txt").write_text("new", encoding="utf-8")
            return {"status": "ok"}

        def detect_side_effect(source_path):
            obj = mock.MagicMock()
            if str(source_path) == str(source_a):
                obj.get_head_id.return_value = new_a
            elif str(source_path) == str(source_b):
                obj.get_head_id.return_value = new_b
            else:
                obj.get_head_id.return_value = "unknown"
            obj.get_type.return_value = "git"
            obj.is_dirty.return_value = False
            return obj

        mgr = BranchManager(skill_dir)
        with mock.patch("ue5_kb.branch_manager.VCSAdapter.detect", side_effect=detect_side_effect), \
             mock.patch.object(BranchManager, "_build_kb", side_effect=fake_build):
            result = mgr.update_all(dry_run=False, force=False)

        assert result.get("status") == "ok", result
        assert result.get("updated") == 2, result

        conn = sqlite3.connect(str(registry_db))
        active = conn.execute(
            "SELECT value FROM config WHERE key='active_branch'"
        ).fetchone()
        conn.close()

        assert active == ("BRANCH_A",), \
            f"update_all 后 active_branch 应恢复为 BRANCH_A，实际: {active}"

    def test_update_all_skips_missing_source_path(self, tmp_path):
        """source_path 缺失/不存在时应跳过并返回原因"""
        from ue5_kb.branch_manager import BranchManager

        skill_dir = tmp_path / "skill_missing_src"
        skill_dir.mkdir()
        registry_db = skill_dir / "registry.db"
        variants_dir = skill_dir / "variants"
        variants_dir.mkdir()
        _make_registry(registry_db, str(variants_dir))

        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "NO_SRC",
            "7777777abcdef00",
            source_path=None,
            kb_dir="nosrc01",
        )
        self._insert_version_and_branch(
            registry_db,
            variants_dir,
            "BAD_SRC",
            "8888888abcdef00",
            source_path=str(tmp_path / "does_not_exist"),
            kb_dir="badsrc1",
        )

        mgr = BranchManager(skill_dir)
        result = mgr.update_all(dry_run=True)

        assert result.get("status") == "ok", result
        no_src = next(r for r in result["results"] if r["branch"] == "NO_SRC")
        bad_src = next(r for r in result["results"] if r["branch"] == "BAD_SRC")
        assert no_src["status"] == "missing_source"
        assert no_src["reason"] == "source_path_missing"
        assert bad_src["status"] == "missing_source"
        assert bad_src["reason"] == "source_path_not_found"

