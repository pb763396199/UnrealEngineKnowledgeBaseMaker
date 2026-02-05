"""
Checkpoint 管理器

支持保存已完成任务的 checkpoint，支持从 checkpoint 恢复
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import json
from datetime import datetime


class CheckpointManager:
    """
    Checkpoint 管理器

    支持：
    - 保存已完成任务的 checkpoint
    - 从 checkpoint 恢复
    - 清理过期 checkpoint

    示例：
        manager = CheckpointManager(stage_dir, "analyze")
        completed = manager.get_completed_tasks()
        # ... 跳过已完成的任务 ...
        manager.save_completed("Module1", {"classes": 10, "functions": 50})
    """

    def __init__(self, stage_dir: Path, stage_name: str):
        """
        初始化 Checkpoint 管理器

        Args:
            stage_dir: 阶段工作目录
            stage_name: 阶段名称
        """
        self.stage_dir = Path(stage_dir)
        self.stage_name = stage_name
        self.checkpoint_file = self.stage_dir / f".{stage_name}_checkpoint"

    def load(self) -> Dict[str, Any]:
        """
        加载 checkpoint

        Returns:
            Checkpoint 数据字典
        """
        if not self.checkpoint_file.exists():
            return {
                "completed": [],
                "failed": [],
                "created_at": None,
                "updated_at": None,
            }

        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "completed": [],
                "failed": [],
                "created_at": None,
                "updated_at": None,
            }

    def save_completed(self, task_id: str, result: Dict[str, Any]) -> None:
        """
        保存已完成的任务

        Args:
            task_id: 任务 ID（通常是模块名）
            result: 任务结果摘要
        """
        checkpoint = self.load()

        if checkpoint["created_at"] is None:
            checkpoint["created_at"] = datetime.now().isoformat()

        checkpoint["updated_at"] = datetime.now().isoformat()

        # 避免重复
        if task_id not in checkpoint["completed"]:
            checkpoint["completed"].append(task_id)

        # 保存任务结果摘要
        if "results" not in checkpoint:
            checkpoint["results"] = {}

        checkpoint["results"][task_id] = {
            "status": "success",
            "completed_at": datetime.now().isoformat(),
            "summary": {
                "classes": result.get("classes_count", 0),
                "functions": result.get("functions_count", 0),
                "files": result.get("files_count", 0),
            },
        }

        self._save(checkpoint)

    def save_failed(self, task_id: str, error: str, error_type: str) -> None:
        """
        保存失败的任务

        Args:
            task_id: 任务 ID
            error: 错误信息
            error_type: 错误类型
        """
        checkpoint = self.load()

        if checkpoint["created_at"] is None:
            checkpoint["created_at"] = datetime.now().isoformat()

        checkpoint["updated_at"] = datetime.now().isoformat()

        if task_id not in checkpoint["failed"]:
            checkpoint["failed"].append(task_id)

        if "results" not in checkpoint:
            checkpoint["results"] = {}

        checkpoint["results"][task_id] = {
            "status": "failed",
            "failed_at": datetime.now().isoformat(),
            "error": error,
            "error_type": error_type,
        }

        self._save(checkpoint)

    def _save(self, checkpoint: Dict[str, Any]) -> None:
        """保存 checkpoint 到文件"""
        self.stage_dir.mkdir(parents=True, exist_ok=True)

        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)

    def get_completed_tasks(self) -> set:
        """
        获取已完成的任务集合

        Returns:
            已完成任务 ID 的集合
        """
        checkpoint = self.load()
        return set(checkpoint.get("completed", []))

    def get_failed_tasks(self) -> List[Dict[str, str]]:
        """
        获取失败的任务列表

        Returns:
            失败任务列表，每个元素包含 task_id, error, error_type
        """
        checkpoint = self.load()
        failed = checkpoint.get("failed", [])
        results = checkpoint.get("results", {})

        return [
            {
                "task_id": task_id,
                "error": results[task_id].get("error", "Unknown"),
                "error_type": results[task_id].get("error_type", "Exception"),
            }
            for task_id in failed
        ]

    def clear(self) -> None:
        """清除 checkpoint"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
