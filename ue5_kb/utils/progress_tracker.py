"""
多进度条跟踪器

使用 rich.progress 实现多 worker 并行进度显示
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
import time

from rich.progress import (
    Progress,
    TaskID,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    SpinnerColumn,
)
from rich.console import Console
from rich.live import Live


@dataclass
class WorkerStatus:
    """Worker 状态"""

    worker_id: int
    current_task: str = ""
    completed: int = 0
    total: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def progress(self) -> float:
        if self.total == 0:
            return 0.0
        return self.completed / self.total


@dataclass
class ErrorRecord:
    """错误记录"""

    module: str
    error: str
    error_type: str
    timestamp: datetime = field(default_factory=datetime.now)


class ProgressTracker:
    """
    多进度条跟踪器

    特性：
    - 支持多个 worker 的独立进度条
    - 总进度汇总
    - 错误收集和展示
    - 速度统计和 ETA 计算

    示例：
        tracker = ProgressTracker("analyze", total_items=100, num_workers=4)
        tracker.start()
        tracker.update_worker(0, "Module1", 10, 50)
        tracker.increment_total()
        stats = tracker.stop()
    """

    def __init__(
        self,
        stage_name: str,
        total_items: int,
        num_workers: int,
        console: Optional[Console] = None,
    ):
        self.stage_name = stage_name
        self.total_items = total_items
        self.num_workers = num_workers
        self.console = console or Console()

        # 线程安全
        self._lock = Lock()

        # 进度跟踪
        self._completed_items = 0
        self._workers: Dict[int, WorkerStatus] = {}
        self._errors: List[ErrorRecord] = []

        # Rich Progress 对象
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
        )

        # 任务 ID
        self._total_task_id: Optional[TaskID] = None
        self._worker_task_ids: Dict[int, TaskID] = {}

        # 性能统计
        self._start_time = time.time()
        self._last_update_time = time.time()
        self._last_completed_count = 0

    def start(self) -> None:
        """启动进度条"""
        self._progress.start()

        # 添加总进度任务
        self._total_task_id = self._progress.add_task(
            f"[bold cyan]Total Progress[/bold cyan]",
            total=self.total_items,
        )

        # 添加每个 worker 的进度条
        for i in range(self.num_workers):
            worker_id = self._progress.add_task(
                f"[dim]Worker {i + 1}[/dim]: [yellow]Initializing...[/yellow]",
                total=100,  # 百分比
            )
            self._worker_task_ids[i] = worker_id
            self._workers[i] = WorkerStatus(worker_id=i)

    def update_worker(
        self,
        worker_id: int,
        current_task: str,
        completed: int,
        total: int,
    ) -> None:
        """
        更新 worker 状态

        Args:
            worker_id: Worker ID (0-indexed)
            current_task: 当前任务名称（如模块名、文件名）
            completed: 已完成数
            total: 总数
        """
        with self._lock:
            if worker_id not in self._workers:
                return

            worker = self._workers[worker_id]
            worker.current_task = current_task
            worker.completed = completed
            worker.total = total

            # 更新进度条
            if worker_id in self._worker_task_ids:
                task_id = self._worker_task_ids[worker_id]
                progress_pct = int(worker.progress * 100)
                self._progress.update(
                    task_id,
                    completed=progress_pct,
                    description=f"[dim]Worker {worker_id + 1}[/dim]: [yellow]{current_task}[/yellow]",
                )

    def increment_total(self, count: int = 1) -> None:
        """增加总进度"""
        with self._lock:
            self._completed_items += count
            if self._total_task_id is not None:
                self._progress.update(
                    self._total_task_id,
                    completed=self._completed_items,
                )

    def add_error(
        self,
        module: str,
        error: str,
        error_type: str = "Exception",
    ) -> None:
        """记录错误"""
        with self._lock:
            self._errors.append(
                ErrorRecord(module=module, error=error, error_type=error_type)
            )

    def get_speed_stats(self) -> Dict[str, float]:
        """获取速度统计"""
        elapsed = time.time() - self._start_time
        speed = self._completed_items / elapsed if elapsed > 0 else 0

        # 计算剩余时间
        if self._completed_items > 0 and speed > 0:
            remaining_items = self.total_items - self._completed_items
            eta = remaining_items / speed
        else:
            eta = 0

        return {
            "elapsed": elapsed,
            "speed": speed,  # items/sec
            "eta": eta,
            "completed": self._completed_items,
            "total": self.total_items,
            "progress_pct": (
                (self._completed_items / self.total_items * 100)
                if self.total_items > 0
                else 0
            ),
        }

    def stop(self) -> Dict[str, Any]:
        """
        停止进度条并返回最终统计

        Returns:
            包含统计信息的字典
        """
        self._progress.stop()

        stats = self.get_speed_stats()
        stats["errors"] = [
            {"module": e.module, "error": e.error, "error_type": e.error_type}
            for e in self._errors
        ]
        stats["error_count"] = len(self._errors)

        return stats
