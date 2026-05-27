"""
VCS (Version Control System) 适配器

支持 Git 仓库的 commit 检测和状态查询。
"""

import subprocess
import hashlib
import os
from pathlib import Path
from typing import Iterable, List, Optional


SOURCE_FINGERPRINT_SUFFIXES = (".h", ".hpp", ".cpp", ".inl", ".ush", ".usf")
SOURCE_FINGERPRINT_NAMES = (".uplugin", ".uproject")
SOURCE_FINGERPRINT_BUILD_SUFFIX = ".Build.cs"
SOURCE_FINGERPRINT_SKIP_DIRS = {
    ".git",
    ".history",
    ".hg",
    ".svn",
    ".vs",
    ".idea",
    "__pycache__",
    "Binaries",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
    "Temp",
    "Generated",
}
SOURCE_FINGERPRINT_SKIP_DIRS_NORM = {name.lower() for name in SOURCE_FINGERPRINT_SKIP_DIRS}


def _decode_z_paths(raw: bytes) -> List[str]:
    return [
        part.decode("utf-8", errors="surrogateescape")
        for part in raw.split(b"\0")
        if part
    ]


class VCSAdapter:
    """版本控制系统适配器"""

    def __init__(self, repo_path: str, vcs_type: str = "git"):
        self._path = repo_path
        self._type = vcs_type

    @staticmethod
    def detect(path: str) -> "VCSAdapter":
        """自动检测 VCS 类型并返回适配器"""
        p = Path(path)
        # 向上查找 .git 目录
        for parent in [p] + list(p.parents):
            if (parent / ".git").exists():
                return VCSAdapter(str(parent), "git")
        # 未检测到 VCS，返回 null adapter
        return VCSAdapter(str(p), "none")

    def get_type(self) -> str:
        return self._type

    def get_head_id(self) -> str:
        """获取当前 HEAD commit ID"""
        if self._type == "none":
            return "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def is_dirty(self) -> bool:
        """检查工作区是否有未提交变更"""
        if self._type == "none":
            return False
        try:
            tracked, untracked = self._git_source_dirty_paths()
            return bool(tracked or untracked)
        except Exception:
            return False

    def get_worktree_fingerprint(self) -> Optional[str]:
        """返回工作区源码指纹；Git clean 返回 None，非 Git 返回源码树指纹。"""
        if self._type == "none":
            return self._get_source_tree_fingerprint()
        try:
            tracked_paths, untracked_paths = self._git_source_dirty_paths()
            if not tracked_paths and not untracked_paths:
                return None

            h = hashlib.sha256()
            h.update(b"source-status-v1\0")
            for rel in tracked_paths:
                h.update(rel.encode("utf-8", errors="surrogateescape"))
                h.update(b"\0")

            if tracked_paths:
                diff = subprocess.run(
                    ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", *tracked_paths],
                    cwd=self._path,
                    capture_output=True,
                    timeout=30,
                )
                if diff.returncode != 0:
                    return None
                h.update(b"\ndiff\0")
                h.update(diff.stdout)

            h.update(b"\nuntracked\0")
            for rel in untracked_paths:
                path = Path(self._path) / rel
                if not path.is_file():
                    continue
                h.update(rel.encode("utf-8", errors="surrogateescape"))
                h.update(b"\0")
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(1048576)
                        if not chunk:
                            break
                        h.update(chunk)
                h.update(b"\0")
            return h.hexdigest()
        except Exception:
            return None

    def _get_source_tree_fingerprint(self) -> Optional[str]:
        root = Path(self._path)
        if not root.exists():
            return None

        h = hashlib.sha256()
        h.update(b"source-tree-v1\0")
        try:
            for current_dir, dirs, files in os.walk(root):
                dirs[:] = sorted(
                    dirname for dirname in dirs if dirname.lower() not in SOURCE_FINGERPRINT_SKIP_DIRS_NORM
                )
                current_path = Path(current_dir)
                for filename in sorted(files):
                    path = current_path / filename
                    if not self._is_source_fingerprint_file(path):
                        continue
                    try:
                        stat = path.stat()
                        relative = path.relative_to(root).as_posix()
                    except OSError:
                        continue
                    h.update(relative.encode("utf-8", errors="surrogateescape"))
                    h.update(b"\0")
                    h.update(str(stat.st_size).encode("ascii"))
                    h.update(b"\0")
                    h.update(str(stat.st_mtime_ns).encode("ascii"))
                    h.update(b"\0")
            return h.hexdigest()
        except Exception:
            return None

    @staticmethod
    def _is_source_fingerprint_file(path: Path) -> bool:
        return (
            path.name.endswith(SOURCE_FINGERPRINT_BUILD_SUFFIX)
            or path.suffix in SOURCE_FINGERPRINT_SUFFIXES
            or path.suffix in SOURCE_FINGERPRINT_NAMES
        )

    @classmethod
    def _is_source_fingerprint_relative_path(cls, rel_path: str) -> bool:
        parts = [part for part in rel_path.replace("\\", "/").split("/") if part]
        if not parts:
            return False
        if any(part.lower() in SOURCE_FINGERPRINT_SKIP_DIRS_NORM for part in parts[:-1]):
            return False
        return cls._is_source_fingerprint_file(Path(parts[-1]))

    def _git_source_dirty_paths(self) -> tuple[List[str], List[str]]:
        tracked = subprocess.run(
            ["git", "diff", "--name-only", "-z", "--no-ext-diff", "HEAD"],
            cwd=self._path,
            capture_output=True,
            timeout=10,
        )
        if tracked.returncode != 0:
            return [], []

        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=self._path,
            capture_output=True,
            timeout=10,
        )
        if untracked.returncode != 0:
            return [], []

        tracked_paths = self._filter_source_paths(_decode_z_paths(tracked.stdout))
        untracked_paths = self._filter_source_paths(_decode_z_paths(untracked.stdout))
        return tracked_paths, untracked_paths

    @classmethod
    def _filter_source_paths(cls, paths: Iterable[str]) -> List[str]:
        return sorted({path for path in paths if cls._is_source_fingerprint_relative_path(path)})

    def get_branch_name(self) -> Optional[str]:
        """获取当前分支名"""
        if self._type == "none":
            return None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None
