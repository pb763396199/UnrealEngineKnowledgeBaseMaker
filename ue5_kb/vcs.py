"""
VCS (Version Control System) 适配器

支持 Git 仓库的 commit 检测和状态查询。
"""

import subprocess
from pathlib import Path
from typing import Optional


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
