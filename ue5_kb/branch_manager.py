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

import hashlib
import io
import os
import pickle
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vcs import VCSAdapter


# ---------------------------------------------------------------------------
# P0-1: 安全 pickle 加载
# ---------------------------------------------------------------------------

# 白名单：仅允许 networkx 序列化所需的安全类型
_PICKLE_MODULE_ALLOWLIST = {
    "networkx.classes.digraph",
    "networkx.classes.graph",
    "networkx.classes.reportviews",
    "networkx.classes.coreviews",
    "collections",
}

# builtins 仅允许数据容器类型，禁止 eval/exec/getattr/__import__ 等
_PICKLE_BUILTINS_ALLOW = {
    "set", "frozenset", "list", "dict", "tuple", "bytes", "bytearray",
    "True", "False", "None", "int", "float", "complex", "str", "slice",
    "range", "type",
}

_PICKLE_BUILTINS_DENY = {
    "eval", "exec", "getattr", "setattr", "delattr", "__import__",
    "compile", "execfile", "open", "input", "breakpoint",
    "globals", "locals", "vars",
}


class SafeUnpickler(pickle.Unpickler):
    """仅允许白名单模块的 Unpickler，防止任意代码执行"""

    def find_class(self, module: str, name: str) -> Any:
        top = module.split(".")[0]

        # builtins: 显式枚举安全类型
        if module == "builtins":
            if name in _PICKLE_BUILTINS_DENY:
                raise pickle.UnpicklingError(
                    f"Blocked dangerous builtin: builtins.{name}"
                )
            if name in _PICKLE_BUILTINS_ALLOW:
                return super().find_class(module, name)
            raise pickle.UnpicklingError(
                f"Blocked unknown builtin: builtins.{name}"
            )

        # networkx + collections: 允许整个包
        if module in _PICKLE_MODULE_ALLOWLIST or top in ("collections", "networkx"):
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

def _file_md5(path: Path) -> str:
    """计算文件 MD5（1MB 分块读取）"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1048576)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


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
                        else:
                            # >1MB: 用 MD5 比较内容
                            same = _file_md5(item) == _file_md5(baseline_file)
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
# 临时目录清理
# ---------------------------------------------------------------------------

def _cleanup_stale_temp_dirs(store_dir: str) -> None:
    """清理上次中断遗留的临时目录（_build_tmp_* / _building_* / _old_*）"""
    store_path = Path(store_dir)
    if not store_path.exists():
        return
    for pattern in ("_build_tmp_*", "_building_*", "_old_*"):
        for d in store_path.glob(pattern):
            if d.is_dir():
                try:
                    shutil.rmtree(str(d))
                    print(f"  [cleanup] 清理残留临时目录: {d.name}", file=sys.stderr)
                except OSError:
                    pass  # 权限或锁定问题，跳过


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
    """创建 SQLite 连接并启用 WAL 模式（P1-4）+ busy_timeout"""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
                    source_path TEXT,
                    dirty INTEGER DEFAULT 0,
                    worktree_fingerprint TEXT
                );
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            self._migrate_registry_schema(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_registry_schema(conn: sqlite3.Connection) -> None:
        """兼容旧 registry.db，补齐 versions 的 dirty worktree 字段"""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(versions)").fetchall()
        }
        if "dirty" not in columns:
            conn.execute("ALTER TABLE versions ADD COLUMN dirty INTEGER DEFAULT 0")
        if "worktree_fingerprint" not in columns:
            conn.execute("ALTER TABLE versions ADD COLUMN worktree_fingerprint TEXT")

    def _get_kb_store(self, conn: sqlite3.Connection) -> str:
        """获取 variant 存储目录"""
        row = conn.execute(
            "SELECT value FROM config WHERE key = 'kb_store'"
        ).fetchone()
        return row[0] if row else str(self.skill_dir / "variants")

    @staticmethod
    def _short_commit(commit_id: Optional[str]) -> Optional[str]:
        """截断 commit 显示，保持返回结构可读且兼容"""
        if not commit_id:
            return None
        return commit_id[:7]

    @staticmethod
    def _short_fingerprint(fingerprint: Optional[str]) -> Optional[str]:
        """截断 worktree fingerprint，避免状态输出过长"""
        fingerprint = BranchManager._normalize_fingerprint(fingerprint)
        if not fingerprint:
            return None
        return fingerprint[:12]

    @staticmethod
    def _normalize_dirty(value: Any) -> bool:
        """SQLite/Mock 返回值统一转为 bool"""
        return bool(int(value or 0))

    @staticmethod
    def _normalize_fingerprint(fingerprint: Any) -> Optional[str]:
        """仅接受真实字符串 fingerprint，Mock/空值按 None 处理"""
        return fingerprint if isinstance(fingerprint, str) and fingerprint else None

    @staticmethod
    def _normalize_current_dirty(value: Any) -> bool:
        """VCSAdapter.is_dirty 正常返回 bool；未配置 Mock 按 clean 处理"""
        return value if isinstance(value, bool) else False

    @classmethod
    def _worktree_matches(
        cls,
        registry_dirty: Any,
        registry_fingerprint: Optional[str],
        current_dirty: bool,
        current_fingerprint: Optional[str],
    ) -> bool:
        """commit 相同时，仅 dirty 状态和 fingerprint 都一致才可复用"""
        return (
            cls._normalize_dirty(registry_dirty) == bool(current_dirty)
            and cls._normalize_fingerprint(registry_fingerprint)
            == cls._normalize_fingerprint(current_fingerprint)
        )

    @classmethod
    def _stale_reason(
        cls,
        registry_commit: Optional[str],
        current_commit: Optional[str],
        registry_dirty: Any,
        current_dirty: bool,
        registry_fingerprint: Optional[str],
        current_fingerprint: Optional[str],
    ) -> Optional[str]:
        """返回导致 registry stale 的首个明确原因"""
        if current_commit != registry_commit:
            return "commit_changed"
        if cls._normalize_dirty(registry_dirty) != bool(current_dirty):
            return "dirty_changed"
        if cls._normalize_fingerprint(registry_fingerprint) != cls._normalize_fingerprint(current_fingerprint):
            return "fingerprint_changed"
        return None

    def _prune_version_if_unreferenced(
        self,
        conn: sqlite3.Connection,
        commit_id: Optional[str],
        kb_store_dir: str,
    ) -> dict:
        """
        清理无分支引用的旧版本。

        注意：commit_id 为空或 unknown* 时跳过，避免误删未知来源版本。
        """
        if not commit_id:
            return {
                "pruned": False,
                "commit": None,
                "reason": "empty_commit",
            }

        if commit_id.startswith("unknown"):
            return {
                "pruned": False,
                "commit": self._short_commit(commit_id),
                "reason": "skip_unknown_commit",
            }

        ref_count = conn.execute(
            "SELECT COUNT(*) FROM branches WHERE commit_id = ?",
            (commit_id,),
        ).fetchone()[0]
        if ref_count > 0:
            return {
                "pruned": False,
                "commit": self._short_commit(commit_id),
                "reason": "still_referenced",
                "references": ref_count,
            }

        row = conn.execute(
            "SELECT kb_dir FROM versions WHERE commit_id = ?",
            (commit_id,),
        ).fetchone()
        if not row:
            return {
                "pruned": False,
                "commit": self._short_commit(commit_id),
                "reason": "version_not_found",
            }

        kb_dir = row[0]
        variant_dir = Path(kb_store_dir) / kb_dir

        # 先删 registry 记录，目录删除失败仅告警，不回滚成功更新。
        conn.execute("DELETE FROM versions WHERE commit_id = ?", (commit_id,))
        conn.commit()

        warning = None
        dir_deleted = False
        if variant_dir.exists():
            try:
                shutil.rmtree(str(variant_dir))
                dir_deleted = True
            except Exception as e:
                warning = f"failed_to_delete_variant_dir: {e}"
        else:
            warning = "variant_dir_not_found"

        result = {
            "pruned": True,
            "commit": self._short_commit(commit_id),
            "kb_dir": kb_dir,
            "variant_dir_deleted": dir_deleted,
        }
        if warning:
            result["warning"] = warning
        return result

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
        is_dirty = self._normalize_current_dirty(vcs.is_dirty())
        worktree_fingerprint = self._normalize_fingerprint(vcs.get_worktree_fingerprint())

        # 非 git 仓库 commit_id="unknown" 会导致 PK 碰撞，附加时间戳
        if commit_id == "unknown":
            commit_id = f"unknown_{int(time.time())}"

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

            # P0.3: 同 commit 复用检查 — 若已有完整 KB 且目录存在，仅更新分支指针
            existing = conn.execute(
                """
                SELECT kb_dir, dirty, worktree_fingerprint
                FROM versions
                WHERE commit_id = ? AND build_status = 'complete'
                """,
                (commit_id,),
            ).fetchone()
            existing_kb_dir = existing[0] if existing else None
            existing_kb_path = Path(kb_store_dir) / existing_kb_dir if existing_kb_dir else None
            if existing and self._worktree_matches(
                existing[1], existing[2], is_dirty, worktree_fingerprint
            ):
                if existing_kb_path and existing_kb_path.exists():
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO branches
                            (name, commit_id, status, vcs_type, description, updated_at)
                            VALUES (?, ?, 'active', ?, ?, datetime('now'))
                            """,
                            (branch, commit_id, vcs_type, description),
                        )
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
                        "message": f"已复用现有 KB ({commit_id[:7]})",
                        "branch": branch,
                        "commit": commit_id[:7],
                        "reused": True,
                        "dirty": is_dirty,
                        "worktree_fingerprint": self._short_fingerprint(worktree_fingerprint),
                    }
                # 目录缺失 → 按新导入处理，继续走下方逻辑

            kb_dir = (
                existing_kb_dir
                if existing_kb_path is not None and existing_kb_path.exists()
                else self._unique_kb_dir(commit_id, kb_store_dir)
            )
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
                    (commit_id, kb_dir, built_at, file_count, build_status, source_path, dirty, worktree_fingerprint)
                    VALUES (?, ?, datetime('now'), ?, 'complete', ?, ?, ?)
                    """,
                    (commit_id, kb_dir, file_count, str(source_path), int(is_dirty), worktree_fingerprint),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO branches
                    (name, commit_id, status, vcs_type, description, updated_at)
                    VALUES (?, ?, 'active', ?, ?, datetime('now'))
                    """,
                    (branch, commit_id, vcs_type, description),
                )
                # 注册成功后始终把当前分支设为活跃
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
                "dirty": is_dirty,
                "worktree_fingerprint": self._short_fingerprint(worktree_fingerprint),
            }
        finally:
            conn.close()

    def update(
        self,
        branch: str,
        source: str,
        force: bool = False,
        description: str = "",
        prune_old: bool = True,
    ) -> dict:
        """构建/增量更新分支 KB"""
        source_path = Path(source)
        vcs = VCSAdapter.detect(str(source_path))
        commit_id = vcs.get_head_id()
        vcs_type = vcs.get_type()
        is_dirty = self._normalize_current_dirty(vcs.is_dirty())
        worktree_fingerprint = self._normalize_fingerprint(vcs.get_worktree_fingerprint())

        # 非 git 仓库 commit_id="unknown" 会导致 PK 碰撞，附加时间戳
        if commit_id == "unknown":
            commit_id = f"unknown_{int(time.time())}"

        self._init_registry()

        conn = _db_connect(self.registry_db)
        try:
            previous_row = conn.execute(
                "SELECT commit_id FROM branches WHERE name = ?",
                (branch,),
            ).fetchone()
            previous_commit = previous_row[0] if previous_row else None

            # 检查该 commit 是否已有完整 KB。非 force 直接复用；force 时复用同一 kb_dir 做原子替换，避免 orphan chain。
            kb_store_dir = self._get_kb_store(conn)
            existing = conn.execute(
                """
                SELECT kb_dir, dirty, worktree_fingerprint
                FROM versions
                WHERE commit_id = ? AND build_status = 'complete'
                """,
                (commit_id,),
            ).fetchone()
            existing_kb_dir = existing[0] if existing else None
            existing_kb_path = Path(kb_store_dir) / existing_kb_dir if existing_kb_dir else None
            existing_matches = bool(
                existing
                and self._worktree_matches(existing[1], existing[2], is_dirty, worktree_fingerprint)
            )
            if existing_kb_path is not None and existing_kb_path.exists() and existing_matches and not force:
                # 仅更新分支指针
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO branches
                        (name, commit_id, status, vcs_type, description, updated_at)
                        VALUES (?, ?, 'active', ?, ?, datetime('now'))
                        """,
                        (branch, commit_id, vcs_type, description),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                        (branch,),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

                prune_result = {
                    "pruned": False,
                    "reason": "not_required",
                }
                if prune_old and previous_commit and previous_commit != commit_id:
                    try:
                        prune_result = self._prune_version_if_unreferenced(
                            conn, previous_commit, kb_store_dir
                        )
                    except Exception as e:
                        prune_result = {
                            "pruned": False,
                            "commit": self._short_commit(previous_commit),
                            "reason": "prune_failed",
                            "warning": str(e),
                        }

                return {
                    "status": "ok",
                    "message": f"KB 已是最新 ({commit_id[:7]})，仅更新分支指针",
                    "commit": commit_id[:7],
                    "reused": True,
                    "dirty": is_dirty,
                    "worktree_fingerprint": self._short_fingerprint(worktree_fingerprint),
                    "source_changed_during_build": False,
                    "previous_commit": self._short_commit(previous_commit),
                    "pruned_old_version": prune_result,
                }

            # 查找插件根目录
            plugin_root = self._find_plugin_root(source_path)
            if not plugin_root:
                return {"error": f"无法找到插件根目录（需要 .uplugin 文件）: {source}"}

            # 清理上次中断遗留的所有临时目录
            _cleanup_stale_temp_dirs(kb_store_dir)

            # 构建 KB
            # P0.2: 使用 variants store 下的临时构建目录，避免写入 plugin_root/KnowledgeBase
            safe_commit = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in commit_id[:7]
            )
            kb_build_dir = Path(kb_store_dir) / f"_build_tmp_{safe_commit}"

            # 清理上次未完成的残留构建目录
            if kb_build_dir.exists():
                shutil.rmtree(str(kb_build_dir))

            print(
                f"[update] commit={commit_id[:7]} dirty={is_dirty} plugin={plugin_root}",
                file=sys.stderr,
            )
            if is_dirty:
                print("[update] 警告: 工作区有未提交变更，KB 可能不完整", file=sys.stderr)

            # 查找基线版本（用于 hardlink 去重）
            base_row = conn.execute(
                """
                SELECT v.kb_dir, v.commit_id FROM versions v
                JOIN branches b ON v.commit_id = b.commit_id
                WHERE b.name = ? AND v.build_status = 'complete'
                """,
                (branch,),
            ).fetchone()

            # P0.2: _build_kb 直接输出到临时目录，不再写 plugin_root/KnowledgeBase
            build_result = self._build_kb(plugin_root, kb_build_dir, incremental=False)
            if build_result["status"] != "ok":
                return build_result

            if not kb_build_dir.exists():
                return {"error": "ue5_kb 构建后 KB 目录不存在"}

            kb_dir = (
                existing_kb_dir
                if existing_kb_path is not None and existing_kb_path.exists()
                else self._unique_kb_dir(commit_id, kb_store_dir)
            )
            if kb_dir is None:
                shutil.rmtree(str(kb_build_dir))
                return {"error": f"Hash 碰撞无法解决: {commit_id}"}

            # P1-1: 基线 variant 去重
            baseline_variant_dir = None
            if base_row:
                baseline_variant_dir = Path(kb_store_dir) / base_row[0]
                if not baseline_variant_dir.exists():
                    baseline_variant_dir = None

            try:
                final_dir = _import_kb_to_store(
                    kb_build_dir, kb_store_dir, kb_dir, baseline_dir=baseline_variant_dir
                )
                # 导入成功后清理临时构建目录
                if kb_build_dir.exists():
                    shutil.rmtree(str(kb_build_dir))
                self._run_post_import_migration(final_dir)
            except Exception as e:
                if kb_build_dir.exists():
                    shutil.rmtree(str(kb_build_dir))
                return {"error": f"导入失败: {e}"}

            final_vcs = VCSAdapter.detect(str(source_path))
            final_is_dirty = self._normalize_current_dirty(final_vcs.is_dirty())
            final_worktree_fingerprint = self._normalize_fingerprint(final_vcs.get_worktree_fingerprint())
            source_changed_during_build = (
                final_is_dirty != is_dirty
                or final_worktree_fingerprint != worktree_fingerprint
            )

            file_count = sum(1 for _ in final_dir.rglob("*") if _.is_file())

            # P0-3: 事务保护
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO versions
                    (commit_id, kb_dir, built_at, file_count, build_status, source_path, dirty, worktree_fingerprint)
                    VALUES (?, ?, datetime('now'), ?, 'complete', ?, ?, ?)
                    """,
                    (
                        commit_id,
                        kb_dir,
                        file_count,
                        str(source_path),
                        int(final_is_dirty),
                        final_worktree_fingerprint,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO branches
                    (name, commit_id, status, vcs_type, description, updated_at)
                    VALUES (?, ?, 'active', ?, ?, datetime('now'))
                    """,
                    (branch, commit_id, vcs_type, description),
                )
                # update 成功后始终把当前分支设为活跃
                conn.execute(
                    "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                    (branch,),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            prune_result = {
                "pruned": False,
                "reason": "not_required",
            }
            if prune_old and previous_commit and previous_commit != commit_id:
                try:
                    prune_result = self._prune_version_if_unreferenced(
                        conn, previous_commit, kb_store_dir
                    )
                except Exception as e:
                    prune_result = {
                        "pruned": False,
                        "commit": self._short_commit(previous_commit),
                        "reason": "prune_failed",
                        "warning": str(e),
                    }

            return {
                "status": "ok",
                "message": f"已构建并注册 {branch} ({commit_id[:7]})",
                "commit": commit_id[:7],
                "kb_dir": kb_dir,
                "file_count": file_count,
                "incremental": False,
                "dirty": final_is_dirty,
                "worktree_fingerprint": self._short_fingerprint(final_worktree_fingerprint),
                "source_changed_during_build": source_changed_during_build,
                "previous_commit": self._short_commit(previous_commit),
                "pruned_old_version": prune_result,
            }
        finally:
            conn.close()

    def check_updates(self, force: bool = False) -> dict:
        """检查所有已注册分支是否需要更新（不执行构建）"""
        return self.update_all(force=force, dry_run=True, prune_old=False)

    def update_all(
        self,
        force: bool = False,
        dry_run: bool = False,
        prune_old: bool = True,
    ) -> dict:
        """
        基于 registry 中 branch + versions.source_path 批量检查/更新。

        dry_run=True 时仅返回状态，不构建，不写 registry。
        """
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化，请先运行 init"}

        self._init_registry()

        conn = _db_connect(self.registry_db)
        try:
            active_row = conn.execute(
                "SELECT value FROM config WHERE key = 'active_branch'"
            ).fetchone()
            active_branch = active_row[0] if active_row else None

            rows = conn.execute(
                """
                SELECT b.name, b.commit_id, v.source_path, v.dirty, v.worktree_fingerprint
                FROM branches b
                LEFT JOIN versions v ON b.commit_id = v.commit_id
                ORDER BY b.name
                """
            ).fetchall()
        finally:
            conn.close()

        results: List[Dict[str, Any]] = []
        updated = 0
        skipped = 0
        failed = 0

        for branch_name, registry_commit, source_path, registry_dirty, registry_fingerprint in rows:
            item: Dict[str, Any] = {
                "branch": branch_name,
                "registry_commit": self._short_commit(registry_commit),
                "registry_dirty": self._normalize_dirty(registry_dirty),
                "registry_fingerprint": self._short_fingerprint(registry_fingerprint),
                "source": source_path,
                "needs_update": False,
            }

            if not source_path:
                item.update(
                    {
                        "status": "missing_source",
                        "reason": "source_path_missing",
                    }
                )
                results.append(item)
                skipped += 1
                continue

            source_dir = Path(source_path)
            if not source_dir.exists():
                item.update(
                    {
                        "status": "missing_source",
                        "reason": "source_path_not_found",
                    }
                )
                results.append(item)
                skipped += 1
                continue

            try:
                vcs = VCSAdapter.detect(source_path)
                current_commit = vcs.get_head_id()
                current_dirty = self._normalize_current_dirty(vcs.is_dirty())
                current_fingerprint = self._normalize_fingerprint(vcs.get_worktree_fingerprint())
            except Exception as e:
                item.update(
                    {
                        "status": "error",
                        "reason": str(e),
                    }
                )
                results.append(item)
                failed += 1
                continue

            if current_commit == "unknown":
                current_commit = f"unknown_{int(time.time())}"

            reason = self._stale_reason(
                registry_commit,
                current_commit,
                registry_dirty,
                current_dirty,
                registry_fingerprint,
                current_fingerprint,
            )
            needs_update = reason is not None
            item.update(
                {
                    "current_commit": self._short_commit(current_commit),
                    "current_dirty": current_dirty,
                    "current_fingerprint": self._short_fingerprint(current_fingerprint),
                    "dirty": current_dirty,
                    "needs_update": needs_update,
                }
            )
            if reason:
                item["reason"] = reason

            if dry_run:
                item["status"] = "stale" if needs_update else "current"
                results.append(item)
                continue

            if not force and not needs_update:
                item.update(
                    {
                        "status": "current",
                        "reason": "already_up_to_date",
                    }
                )
                results.append(item)
                skipped += 1
                continue

            update_result = self.update(
                branch=branch_name,
                source=source_path,
                force=force,
                prune_old=prune_old,
            )
            if update_result.get("status") == "ok":
                item.update(
                    {
                        "status": "updated",
                        "update": update_result,
                    }
                )
                updated += 1
            else:
                item.update(
                    {
                        "status": "failed",
                        "reason": update_result.get("error", "unknown_error"),
                    }
                )
                failed += 1
            results.append(item)

        # 批量更新可能会把 active_branch 改为最后一个更新分支，结束后恢复为调用前状态。
        if not dry_run and active_branch:
            conn = _db_connect(self.registry_db)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM branches WHERE name = ?",
                    (active_branch,),
                ).fetchone()
                if exists:
                    conn.execute(
                        "INSERT OR REPLACE INTO config VALUES ('active_branch', ?)",
                        (active_branch,),
                    )
                    conn.commit()
            finally:
                conn.close()

        summary = {
            "status": "ok",
            "dry_run": dry_run,
            "total": len(rows),
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }
        if dry_run:
            summary["checked"] = len(rows)
        return summary

    def status(self) -> dict:
        """查看所有分支状态"""
        if not self.registry_db.exists():
            return {"error": "Registry 未初始化，请先运行 init"}

        self._init_registry()

        conn = _db_connect(self.registry_db)
        try:
            active = conn.execute(
                "SELECT value FROM config WHERE key = 'active_branch'"
            ).fetchone()
            active_branch = active[0] if active else None

            rows = conn.execute(
                """
                SELECT b.name, b.commit_id, b.status, b.vcs_type,
                      v.built_at, v.file_count, v.build_status, v.source_path,
                      v.dirty, v.worktree_fingerprint
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
                        "dirty": self._normalize_dirty(r[8]),
                        "worktree_fingerprint": self._short_fingerprint(r[9]),
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
        is_dirty = self._normalize_current_dirty(vcs.is_dirty())
        current_fingerprint = self._normalize_fingerprint(vcs.get_worktree_fingerprint())

        if not self.registry_db.exists():
            return {
                "fresh": False,
                "reason": "Registry 未初始化",
                "current_commit": current_commit[:7],
            }

        self._init_registry()

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
            version = conn.execute(
                "SELECT dirty, worktree_fingerprint FROM versions WHERE commit_id = ?",
                (kb_commit,),
            ).fetchone()
            registry_dirty = version[0] if version else 0
            registry_fingerprint = version[1] if version else None
            fresh = self._stale_reason(
                kb_commit,
                current_commit,
                registry_dirty,
                is_dirty,
                registry_fingerprint,
                current_fingerprint,
            ) is None

            return {
                "fresh": fresh,
                "kb_commit": kb_commit[:7],
                "current_commit": current_commit[:7],
                "dirty": is_dirty,
                "registry_dirty": self._normalize_dirty(registry_dirty),
                "worktree_fingerprint": self._short_fingerprint(current_fingerprint),
                "registry_fingerprint": self._short_fingerprint(registry_fingerprint),
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

            # BEGIN IMMEDIATE 防止 register/update 并发修改
            conn.execute("BEGIN IMMEDIATE")

            registered = {
                r[0] for r in conn.execute("SELECT kb_dir FROM versions").fetchall()
            }

            orphans: List[dict] = []
            total_freed = 0

            for item in store_path.iterdir():
                if not item.is_dir():
                    continue
                # 清理超过 1 小时的残留临时目录
                if item.name.startswith("_building_") or item.name.startswith("_old_"):
                    try:
                        age = time.time() - item.stat().st_mtime
                        if age > 3600:
                            size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                            orphans.append({"dir": item.name, "size_mb": round(size / 1048576, 1), "stale": True})
                            if not dry_run:
                                shutil.rmtree(str(item))
                            total_freed += size
                    except OSError:
                        pass
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
            elif not dry_run:
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

    def resolve_source_path(self, variant: Optional[str] = None) -> Optional[Path]:
        """
        解析活跃分支的源码根目录（来自 versions.source_path）。

        Args:
            variant: 指定分支名。None 则使用 active_branch。

        Returns:
            source_path 对应的 Path；若 source_path 未设置则返回 None。
            不强制检查路径是否存在（源码工作区可能暂时不可用）。
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
                "SELECT source_path FROM versions WHERE commit_id = ? AND build_status = 'complete'",
                (commit_id,),
            ).fetchone()
            if not ver:
                raise ValueError(f"Commit {commit_id[:7]} 无可用 KB")

            source_path = ver[0]
            if not source_path:
                return None
            return Path(source_path)
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
        """调用 ue5_kb 构建 KB（仅数据阶段，不运行 generate），输出到 kb_output"""
        try:
            from ue5_kb.pipeline.coordinator import PipelineCoordinator

            # 非增量构建时清理旧数据，避免 stale DB
            if not incremental and kb_output.exists():
                import shutil as _shutil
                _shutil.rmtree(str(kb_output))

            coord = PipelineCoordinator(
                plugin_root,
                is_plugin=True,
                plugin_name=plugin_root.name,
                kb_path=kb_output,
            )
            # 仅运行数据构建阶段；generate（skill 生成）由调用方管理，避免双重导入
            force = not incremental
            for stage_name in ("discover", "extract", "analyze", "build"):
                coord.run_stage(stage_name, force=force)
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
