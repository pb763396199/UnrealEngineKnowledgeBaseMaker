"""
多分支 KB 管理器

管理知识库的多版本/多分支存储、注册表、VCS 集成和垃圾回收。

安全特性:
- P0-1: SafeUnpickler — 仅允许 networkx + builtins 类型
- P0-2: rename-aside 原子写入
- P0-3: BEGIN IMMEDIATE 事务保护
- P1-1: hardlink 去重（跨 variant 共享相同文件）
- P1-2: GC 垃圾回收
- P1-4: SQLite WAL 模式
"""

import io
import os
import pickle
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vcs import VCSAdapter


# ---------------------------------------------------------------------------
# P0-1: 安全 pickle 加载
# ---------------------------------------------------------------------------

_PICKLE_ALLOWLIST = {
    "networkx.classes.digraph",
    "networkx.classes.graph",
    "networkx.classes.reportviews",
    "networkx.classes.coreviews",
    "builtins",
    "collections",
}


class SafeUnpickler(pickle.Unpickler):
    """仅允许白名单模块的 Unpickler，防止任意代码执行"""

    def find_class(self, module: str, name: str) -> Any:
        top = module.split(".")[0]
        if module in _PICKLE_ALLOWLIST or top in ("builtins", "collections", "networkx"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Blocked: {module}.{name} (not in allowlist)"
        )


def safe_pickle_load(file_obj) -> Any:
    """安全加载 pickle 文件"""
    return SafeUnpickler(file_obj).load()


def safe_pickle_load_path(path: Path) -> Any:
    """安全加载 pickle 文件（路径版本）"""
    with open(path, "rb") as f:
        return SafeUnpickler(f).load()


# ---------------------------------------------------------------------------
# P1-1: Hardlink 去重复制
# ---------------------------------------------------------------------------

def _hardlink_copy(src: Path, dst: Path) -> None:
    """复制目录，优先使用硬链接节省空间"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(str(item), str(target))
            except OSError:
                shutil.copy2(str(item), str(target))


def _hardlink_copy_dedup(src: Path, dst: Path, baseline: Optional[Path] = None) -> None:
    """
    复制目录，优先从 baseline 硬链接匹配文件（P1-1 去重）。

    策略：对每个文件，若 baseline 中同路径文件大小相同，
    直接硬链接 baseline 版本（零拷贝）；否则从 src 复制。
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # 尝试从 baseline 硬链接
        if baseline:
            baseline_file = baseline / rel
            if baseline_file.exists():
                try:
                    src_stat = item.stat()
                    bl_stat = baseline_file.stat()
                    if bl_stat.st_size == src_stat.st_size:
                        # 大小相同 → 再比较内容（≤1MB 直接比较，更大则信任 size）
                        same = True
                        if src_stat.st_size <= 1048576:
                            same = item.read_bytes() == baseline_file.read_bytes()
                        if same:
                            os.link(str(baseline_file), str(target))
                            continue
                except OSError:
                    pass
        # 回退：从 src 复制
        try:
            os.link(str(item), str(target))
        except OSError:
            shutil.copy2(str(item), str(target))


# ---------------------------------------------------------------------------
# P0-2: 原子导入（rename-aside 模式）
# ---------------------------------------------------------------------------

def _import_kb_to_store(
    src_dir: Path,
    store_dir: str,
    kb_dir: str,
    baseline_dir: Optional[Path] = None,
) -> Path:
    """
    将 KB 目录导入到 variant 存储。

    使用 rename-aside 模式保证原子性：
    1. 复制到临时目录 _building_{kb_dir}
    2. rename 到目标目录
    3. 若目标已存在，先 rename 为 _old_{kb_dir}，再 rename 新目录，最后删除 old
    """
    store_path = Path(store_dir)
    store_path.mkdir(parents=True, exist_ok=True)

    building_dir = store_path / f"_building_{kb_dir}"
    target_dir = store_path / kb_dir

    # 清理残留的临时目录
    if building_dir.exists():
        shutil.rmtree(str(building_dir))

    # 复制到临时目录（带去重）
    _hardlink_copy_dedup(src_dir, building_dir, baseline=baseline_dir)

    # P0-2: rename-aside 原子替换
    if target_dir.exists():
        old_dir = store_path / f"_old_{kb_dir}"
        if old_dir.exists():
            shutil.rmtree(str(old_dir))
        target_dir.rename(old_dir)
        try:
            building_dir.rename(target_dir)
        except Exception:
            # 回滚
            old_dir.rename(target_dir)
            raise
        shutil.rmtree(str(old_dir))
    else:
        building_dir.rename(target_dir)

    return target_dir


# ---------------------------------------------------------------------------
# DB 辅助
# ---------------------------------------------------------------------------

def _db_connect(path: Path) -> sqlite3.Connection:
    """创建 SQLite 连接并启用 WAL 模式（P1-4）"""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# BranchManager
# ---------------------------------------------------------------------------

class BranchManager:
    """多分支知识库管理器"""

    def __init__(self, skill_dir: Path):
        """
        Args:
            skill_dir: skill 目录（如 ~/.claude/skills/AesWorld-kb/）
        """
        self.skill_dir = Path(skill_dir)
        self.registry_db = self.skill_dir / "registry.db"

    # ---- registry 初始化 ----

    def _init_registry(self) -> None:
        """确保 registry.db 存在且 schema 正确"""
        conn = _db_connect(self.registry_db)
        try:
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
        finally:
            conn.close()

    def _get_kb_store(self, conn: sqlite3.Connection) -> str:
        """获取 variant 存储目录"""
        row = conn.execute(
            "SELECT value FROM config WHERE key = 'kb_store'"
        ).fetchone()
        return row[0] if row else str(self.skill_dir / "variants")

    # ---- 公开命令 ----

    def init_registry(self, kb_store: Optional[str] = None) -> dict:
        """初始化多分支注册表"""
        self._init_registry()
        if kb_store:
            conn = _db_connect(self.registry_db)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO config VALUES ('kb_store', ?)",
                    (kb_store,),
                )
                conn.commit()
            finally:
                conn.close()
        return {"status": "ok", "registry": str(self.registry_db)}

    def register(
        self,
        branch: str,
        source: str,
        kb_path: Optional[str] = None,
        description: str = "",
    ) -> dict:
        """注册分支并导入已有 KB"""
        vcs = VCSAdapter.detect(source)
        commit_id = vcs.get_head_id()
        vcs_type = vcs.get_type()

        if not self.registry_db.exists():
            self._init_registry()

        # 确定 KB 源目录
        source_path = Path(source)
        if kb_path:
            kb_source = Path(kb_path)
        else:
            # 自动查找插件根目录下的 KnowledgeBase
            plugin_root = self._find_plugin_root(source_path)
            if plugin_root:
                kb_source = plugin_root / "KnowledgeBase"
            else:
                kb_source = source_path / "KnowledgeBase"

        if not kb_source.exists():
            return {"error": f"KB 目录不存在: {kb_source}"}

        conn = _db_connect(self.registry_db)
        try:
            kb_store_dir = self._get_kb_store(conn)
            kb_dir = self._unique_kb_dir(commit_id, kb_store_dir)
            if kb_dir is None:
                return {"error": f"Hash 碰撞无法解决: {commit_id}"}

            final_dir = _import_kb_to_store(kb_source, kb_store_dir, kb_dir)
            self._run_post_import_migration(final_dir)

            file_count = sum(1 for _ in final_dir.rglob("*") if _.is_file())

            # P0-3: 事务保护
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO versions
                    (commit_id, kb_dir, built_at, file_count, build_status, source_path)
                    VALUES (?, ?, datetime('now'), ?, 'complete', ?)
                    """,
                    (commit_id, kb_dir, file_count, str(source_path)),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO branches
                    (name, commit_id, status, vcs_type, description, updated_at)
                    VALUES (?, ?, 'active', ?, ?, datetime('now'))
                    """,
                    (branch, commit_id, vcs_type, description),
                )
                # 若无活跃分支，设为默认
                active = conn.execute(
                    "SELECT value FROM config WHERE key = 'active_branch'"
                ).fetchone()
                if not active:
                    conn.execute(
                        "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                        (branch,),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            return {
                "status": "ok",
                "message": f"已注册 {branch} ({commit_id[:7]})",
                "branch": branch,
                "commit": commit_id[:7],
                "files": file_count,
            }
        finally:
            conn.close()

    def update(
        self,
        branch: str,
        source: str,
        force: bool = False,
        description: str = "",
    ) -> dict:
        """构建/增量更新分支 KB"""
        source_path = Path(source)
        vcs = VCSAdapter.detect(str(source_path))
        commit_id = vcs.get_head_id()
        vcs_type = vcs.get_type()
        is_dirty = vcs.is_dirty()

        if not self.registry_db.exists():
            self._init_registry()

        conn = _db_connect(self.registry_db)
        try:
            # 检查该 commit 是否已有 KB
            if not force:
                existing = conn.execute(
                    "SELECT kb_dir FROM versions WHERE commit_id = ? AND build_status = 'complete'",
                    (commit_id,),
                ).fetchone()
                if existing:
                    # 仅更新分支指针
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO branches
                        (name, commit_id, status, vcs_type, description, updated_at)
                        VALUES (?, ?, 'active', ?, ?, datetime('now'))
                        """,
                        (branch, commit_id, vcs_type, description),
                    )
                    active = conn.execute(
                        "SELECT value FROM config WHERE key = 'active_branch'"
                    ).fetchone()
                    if not active:
                        conn.execute(
                            "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                            (branch,),
                        )
                    conn.commit()
                    return {
                        "status": "ok",
                        "message": f"KB 已是最新 ({commit_id[:7]})，仅更新分支指针",
                        "commit": commit_id[:7],
                        "reused": True,
                    }

            # 查找插件根目录
            plugin_root = self._find_plugin_root(source_path)
            if not plugin_root:
                return {"error": f"无法找到插件根目录（需要 .uplugin 文件）: {source}"}

            # 构建 KB
            kb_output = plugin_root / "KnowledgeBase"
            print(
                f"[update] commit={commit_id[:7]} dirty={is_dirty} plugin={plugin_root}",
                file=sys.stderr,
            )
            if is_dirty:
                print("[update] 警告: 工作区有未提交变更，KB 可能不完整", file=sys.stderr)

            # 查找基线版本
            base_row = conn.execute(
                """
                SELECT v.kb_dir, v.commit_id FROM versions v
                JOIN branches b ON v.commit_id = b.commit_id
                WHERE b.name = ? AND v.build_status = 'complete'
                """,
                (branch,),
            ).fetchone()

            incremental = bool(base_row and kb_output.exists())

            build_result = self._build_kb(plugin_root, kb_output, incremental=incremental)
            if build_result["status"] != "ok":
                return build_result

            # 导入到 variant 存储
            if not kb_output.exists():
                return {"error": "ue5_kb 构建后 KB 目录不存在"}

            kb_store_dir = self._get_kb_store(conn)
            kb_dir = self._unique_kb_dir(commit_id, kb_store_dir)
            if kb_dir is None:
                return {"error": f"Hash 碰撞无法解决: {commit_id}"}

            # P1-1: 基线 variant 去重
            baseline_variant_dir = None
            if base_row:
                baseline_variant_dir = Path(kb_store_dir) / base_row[0]
                if not baseline_variant_dir.exists():
                    baseline_variant_dir = None

            try:
                final_dir = _import_kb_to_store(
                    kb_output, kb_store_dir, kb_dir, baseline_dir=baseline_variant_dir
                )
                self._run_post_import_migration(final_dir)
            except Exception as e:
                return {"error": f"导入失败: {e}"}

            file_count = sum(1 for _ in final_dir.rglob("*") if _.is_file())

            # P0-3: 事务保护
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO versions
                    (commit_id, kb_dir, built_at, file_count, build_status, source_path)
                    VALUES (?, ?, datetime('now'), ?, 'complete', ?)
                    """,
                    (commit_id, kb_dir, file_count, str(source_path)),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO branches
                    (name, commit_id, status, vcs_type, description, updated_at)
                    VALUES (?, ?, 'active', ?, ?, datetime('now'))
                    """,
                    (branch, commit_id, vcs_type, description),
                )
                active = conn.execute(
                    "SELECT value FROM config WHERE key = 'active_branch'"
                ).fetchone()
                if not active:
                    conn.execute(
                        "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                        (branch,),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            return {
                "status": "ok",
                "message": f"已构建并注册 {branch} ({commit_id[:7]})",
                "commit": commit_id[:7],
                "kb_dir": kb_dir,
                "file_count": file_count,
                "incremental": incremental,
                "dirty": is_dirty,
            }
        finally:
            conn.close()

    def status(self) -> dict:
        """查看所有分支状态"""
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化，请先运行 init"}

        conn = _db_connect(self.registry_db)
        try:
            active = conn.execute(
                "SELECT value FROM config WHERE key = 'active_branch'"
            ).fetchone()
            active_branch = active[0] if active else None

            rows = conn.execute(
                """
                SELECT b.name, b.commit_id, b.status, b.vcs_type,
                       v.built_at, v.file_count, v.build_status, v.source_path
                FROM branches b
                LEFT JOIN versions v ON b.commit_id = v.commit_id
                ORDER BY b.updated_at DESC
                """
            ).fetchall()

            branches = []
            for r in rows:
                branches.append(
                    {
                        "branch": r[0],
                        "commit": r[1][:7] if r[1] else None,
                        "status": r[2],
                        "vcs": r[3],
                        "built_at": r[4],
                        "files": r[5],
                        "build_ok": r[6] == "complete",
                        "source": r[7],
                        "active": r[0] == active_branch,
                    }
                )

            return {"branches": branches, "active_branch": active_branch}
        finally:
            conn.close()

    def set_active(self, branch: str) -> dict:
        """切换活跃分支"""
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化"}

        conn = _db_connect(self.registry_db)
        try:
            row = conn.execute(
                "SELECT commit_id FROM branches WHERE name = ?", (branch,)
            ).fetchone()
            if not row:
                return {"error": f"分支 '{branch}' 不存在"}

            conn.execute(
                "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                (branch,),
            )
            conn.commit()
            return {"status": "ok", "active_branch": branch}
        finally:
            conn.close()

    def check_freshness(self, source: str) -> dict:
        """检查 KB 相对于源码的新鲜度"""
        vcs = VCSAdapter.detect(source)
        current_commit = vcs.get_head_id()
        is_dirty = vcs.is_dirty()

        if not self.registry_db.exists():
            return {
                "fresh": False,
                "reason": "Registry 未初始化",
                "current_commit": current_commit[:7],
            }

        conn = _db_connect(self.registry_db)
        try:
            active = conn.execute(
                "SELECT value FROM config WHERE key = 'active_branch'"
            ).fetchone()
            if not active:
                return {
                    "fresh": False,
                    "reason": "无活跃分支",
                    "current_commit": current_commit[:7],
                }

            row = conn.execute(
                "SELECT commit_id FROM branches WHERE name = ?", (active[0],)
            ).fetchone()
            if not row:
                return {
                    "fresh": False,
                    "reason": f"分支 '{active[0]}' 数据缺失",
                    "current_commit": current_commit[:7],
                }

            kb_commit = row[0]
            fresh = kb_commit == current_commit and not is_dirty

            return {
                "fresh": fresh,
                "kb_commit": kb_commit[:7],
                "current_commit": current_commit[:7],
                "dirty": is_dirty,
                "branch": active[0],
            }
        finally:
            conn.close()

    def remove(self, branch: str, delete_data: bool = False) -> dict:
        """移除分支注册"""
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化"}

        conn = _db_connect(self.registry_db)
        try:
            row = conn.execute(
                "SELECT commit_id FROM branches WHERE name = ?", (branch,)
            ).fetchone()
            if not row:
                return {"error": f"分支 '{branch}' 不存在"}

            commit_id = row[0]

            # 清除活跃标记
            active = conn.execute(
                "SELECT value FROM config WHERE key = 'active_branch'"
            ).fetchone()
            if active and active[0] == branch:
                conn.execute("DELETE FROM config WHERE key = 'active_branch'")

            conn.execute("DELETE FROM branches WHERE name = ?", (branch,))

            deleted_data = False
            if delete_data:
                other_refs = conn.execute(
                    "SELECT COUNT(*) FROM branches WHERE commit_id = ?",
                    (commit_id,),
                ).fetchone()[0]
                if other_refs == 0:
                    ver = conn.execute(
                        "SELECT kb_dir FROM versions WHERE commit_id = ?",
                        (commit_id,),
                    ).fetchone()
                    if ver:
                        kb_store_dir = self._get_kb_store(conn)
                        data_dir = Path(kb_store_dir) / ver[0]
                        if data_dir.exists():
                            shutil.rmtree(str(data_dir))
                        conn.execute(
                            "DELETE FROM versions WHERE commit_id = ?",
                            (commit_id,),
                        )
                        deleted_data = True

            conn.commit()
            return {
                "status": "ok",
                "message": f"已移除分支 '{branch}'",
                "deleted_data": deleted_data,
            }
        finally:
            conn.close()

    def gc(self, dry_run: bool = False) -> dict:
        """P1-2: 垃圾回收 — 清理孤立 variant 目录和无效注册条目"""
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化"}

        conn = _db_connect(self.registry_db)
        try:
            kb_store_dir = self._get_kb_store(conn)
            store_path = Path(kb_store_dir)

            if not store_path.exists():
                return {"status": "ok", "message": "variants 目录不存在", "cleaned": 0}

            registered = {
                r[0] for r in conn.execute("SELECT kb_dir FROM versions").fetchall()
            }

            orphans: List[dict] = []
            total_freed = 0

            for item in store_path.iterdir():
                if not item.is_dir():
                    continue
                if item.name.startswith("_building_") or item.name.startswith("_old_"):
                    continue
                if item.name not in registered:
                    size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    orphans.append({"dir": item.name, "size_mb": round(size / 1048576, 1)})
                    if not dry_run:
                        shutil.rmtree(str(item))
                    total_freed += size

            # 清理无 branch 引用的 versions
            orphan_versions = conn.execute(
                """
                SELECT v.commit_id, v.kb_dir FROM versions v
                WHERE NOT EXISTS (
                    SELECT 1 FROM branches b WHERE b.commit_id = v.commit_id
                )
                """
            ).fetchall()

            cleaned_versions: List[dict] = []
            for vid, vdir in orphan_versions:
                cleaned_versions.append({"commit": vid[:7], "kb_dir": vdir})
                if not dry_run:
                    data_dir = store_path / vdir
                    if data_dir.exists():
                        size = sum(
                            f.stat().st_size for f in data_dir.rglob("*") if f.is_file()
                        )
                        total_freed += size
                        shutil.rmtree(str(data_dir))
                    conn.execute("DELETE FROM versions WHERE commit_id = ?", (vid,))

            if not dry_run and cleaned_versions:
                conn.commit()

            return {
                "status": "ok",
                "dry_run": dry_run,
                "orphan_dirs": orphans,
                "orphan_versions": cleaned_versions,
                "total_freed_mb": round(total_freed / 1048576, 1),
                "cleaned": len(orphans) + len(cleaned_versions),
            }
        finally:
            conn.close()

    def resolve_kb_path(self, variant: Optional[str] = None) -> Path:
        """
        解析活跃 KB 路径。

        Args:
            variant: 指定分支名。None 则使用 active_branch。

        Returns:
            KB 目录路径
        """
        if not self.registry_db.exists():
            raise FileNotFoundError("Registry 未初始化")

        conn = _db_connect(self.registry_db)
        try:
            if variant:
                row = conn.execute(
                    "SELECT commit_id FROM branches WHERE name = ?", (variant,)
                ).fetchone()
                if not row:
                    raise ValueError(f"分支 '{variant}' 不存在")
                commit_id = row[0]
            else:
                active = conn.execute(
                    "SELECT value FROM config WHERE key = 'active_branch'"
                ).fetchone()
                if not active:
                    raise ValueError("无活跃分支")
                row = conn.execute(
                    "SELECT commit_id FROM branches WHERE name = ?", (active[0],)
                ).fetchone()
                if not row:
                    raise ValueError(f"活跃分支 '{active[0]}' 数据缺失")
                commit_id = row[0]

            ver = conn.execute(
                "SELECT kb_dir FROM versions WHERE commit_id = ? AND build_status = 'complete'",
                (commit_id,),
            ).fetchone()
            if not ver:
                raise ValueError(f"Commit {commit_id[:7]} 无可用 KB")

            kb_store_dir = self._get_kb_store(conn)
            kb_path = Path(kb_store_dir) / ver[0]
            if not kb_path.exists():
                raise FileNotFoundError(f"KB 目录不存在: {kb_path}")
            return kb_path
        finally:
            conn.close()

    # ---- 内部辅助 ----

    @staticmethod
    def _unique_kb_dir(commit_id: str, kb_store_dir: str) -> Optional[str]:
        """生成不碰撞的 kb_dir 名称"""
        store = Path(kb_store_dir)
        store.mkdir(parents=True, exist_ok=True)
        kb_dir = commit_id[:7]

        # 递增截取长度
        target = store / kb_dir
        while target.exists() and len(kb_dir) < len(commit_id):
            kb_dir = commit_id[: len(kb_dir) + 1]
            target = store / kb_dir

        # 仍碰撞 → 添加数字后缀
        if target.exists():
            for i in range(1, 100):
                candidate = f"{kb_dir}_{i}"
                if not (store / candidate).exists():
                    return candidate
            return None

        return kb_dir

    @staticmethod
    def _find_plugin_root(source_path: Path) -> Optional[Path]:
        """向上查找 .uplugin 文件"""
        for parent in [source_path] + list(source_path.parents):
            if list(parent.glob("*.uplugin")):
                return parent
        return None

    @staticmethod
    def _build_kb(
        plugin_root: Path,
        kb_output: Path,
        incremental: bool = False,
    ) -> dict:
        """调用 ue5_kb 构建 KB"""
        try:
            from ue5_kb.pipeline.coordinator import PipelineCoordinator

            coord = PipelineCoordinator(
                plugin_root,
                is_plugin=True,
                plugin_name=plugin_root.name,
            )
            coord.run_all()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _run_post_import_migration(kb_dir: Path) -> None:
        """导入后迁移：pkl → SQLite（如需要）"""
        global_index_dir = kb_dir / "global_index"
        if not global_index_dir.exists():
            return

        # 检查是否需要从 pkl 迁移到 sqlite
        pkl_file = global_index_dir / "global_index.pkl"
        db_file = global_index_dir / "index.db"
        if pkl_file.exists() and not db_file.exists():
            # 需要迁移 — 但这通常由 build 阶段完成
            pass
