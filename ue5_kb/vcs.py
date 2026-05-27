"""
VCS (Version Control System) 适配器

支持 Git 仓库的 commit 检测和状态查询。
"""

import subprocess
import hashlib
import os
from pathlib import Path
from typing import Optional


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
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip()) if result.returncode == 0 else False
        except Exception:
            return False

    def get_worktree_fingerprint(self) -> Optional[str]:
        """返回工作区源码指纹；Git clean 返回 None，非 Git 返回源码树指纹。"""
        if self._type == "none":
            return self._get_source_tree_fingerprint()
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain=v1", "-uall"],
                cwd=self._path,
                capture_output=True,
                timeout=10,
            )
            if status.returncode != 0 or not status.stdout.strip():
                return None

            diff = subprocess.run(
                ["git", "diff", "--binary", "HEAD", "--no-ext-diff"],
                cwd=self._path,
                capture_output=True,
                timeout=30,
            )
            if diff.returncode != 0:
                return None

            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=self._path,
                capture_output=True,
                timeout=10,
            )
            if untracked.returncode != 0:
                return None

            h = hashlib.sha256()
            h.update(b"status\0")
            h.update(status.stdout)
            h.update(b"\ndiff\0")
            h.update(diff.stdout)
            h.update(b"\nuntracked\0")
            for raw_rel in sorted(p for p in untracked.stdout.split(b"\0") if p):
                rel = raw_rel.decode("utf-8", errors="surrogateescape")
                path = Path(self._path) / rel
                if not path.is_file():
                    continue
                h.update(raw_rel)
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
