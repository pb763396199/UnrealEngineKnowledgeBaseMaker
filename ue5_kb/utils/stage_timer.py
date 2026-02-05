"""
Pipeline 阶段计时器

跟踪每个阶段的执行时间、处理速度和错误统计
"""

from typing import Dict, Optional
from dataclasses import dataclass, field
import time


@dataclass
class StageMetrics:
    """阶段指标"""

    stage_name: str
    start_time: float
    end_time: Optional[float] = None
    items_processed: int = 0
    items_total: int = 0
    errors: int = 0

    @property
    def elapsed(self) -> float:
        """已用时间（秒）"""
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    @property
    def progress_pct(self) -> float:
        """进度百分比"""
        if self.items_total == 0:
            return 0.0
        return (self.items_processed / self.items_total) * 100

    @property
    def speed(self) -> float:
        """处理速度（项/秒）"""
        if self.elapsed == 0:
            return 0.0
        return self.items_processed / self.elapsed


class StageTimer:
    """
    Pipeline 阶段计时器

    跟踪每个阶段的：
    - 开始/结束时间
    - 处理速度
    - 总耗时

    示例：
        timer = StageTimer()
        timer.start_pipeline()
        timer.start_stage("analyze", total_items=1000)
        # ... do work ...
        timer.end_stage("analyze", items_processed=950, errors=5)
        timer.end_pipeline()
        summary = timer.get_summary()
    """

    def __init__(self):
        self._stages: Dict[str, StageMetrics] = {}
        self._pipeline_start: Optional[float] = None
        self._pipeline_end: Optional[float] = None

    def start_pipeline(self) -> None:
        """开始整个 Pipeline"""
        self._pipeline_start = time.time()

    def end_pipeline(self) -> None:
        """结束整个 Pipeline"""
        self._pipeline_end = time.time()

    def start_stage(self, stage_name: str, total_items: int = 0) -> None:
        """
        开始一个阶段

        Args:
            stage_name: 阶段名称
            total_items: 总任务数（用于计算进度）
        """
        self._stages[stage_name] = StageMetrics(
            stage_name=stage_name,
            start_time=time.time(),
            items_total=total_items,
        )

    def end_stage(
        self,
        stage_name: str,
        items_processed: int = 0,
        errors: int = 0,
    ) -> None:
        """
        结束一个阶段

        Args:
            stage_name: 阶段名称
            items_processed: 已处理的项目数
            errors: 错误数量
        """
        if stage_name not in self._stages:
            return

        stage = self._stages[stage_name]
        stage.end_time = time.time()
        stage.items_processed = items_processed
        stage.errors = errors

    def get_stage_metrics(self, stage_name: str) -> Optional[StageMetrics]:
        """
        获取阶段指标

        Args:
            stage_name: 阶段名称

        Returns:
            阶段指标，如果阶段不存在则返回 None
        """
        return self._stages.get(stage_name)

    def get_summary(self) -> Dict[str, any]:
        """
        获取所有阶段摘要

        Returns:
            包含所有阶段统计的字典
        """
        summary: Dict[str, any] = {
            "stages": {},
            "total_elapsed": 0.0,
        }

        for name, metrics in self._stages.items():
            summary["stages"][name] = {
                "elapsed": metrics.elapsed,
                "items_processed": metrics.items_processed,
                "items_total": metrics.items_total,
                "speed": metrics.speed,
                "errors": metrics.errors,
                "progress_pct": metrics.progress_pct,
            }
            summary["total_elapsed"] += metrics.elapsed

        if self._pipeline_start and self._pipeline_end:
            summary["pipeline_elapsed"] = (
                self._pipeline_end - self._pipeline_start
            )
        else:
            summary["pipeline_elapsed"] = summary["total_elapsed"]

        return summary

    def format_summary(self) -> str:
        """
        格式化摘要为可读字符串

        Returns:
            格式化的性能摘要
        """
        lines = []
        lines.append("=" * 60)
        lines.append("Pipeline Performance Summary")
        lines.append("=" * 60)

        for name, metrics in self._stages.items():
            lines.append(f"\n{name.upper()}:")
            lines.append(f"  Elapsed:     {metrics.elapsed:.2f}s")
            lines.append(
                f"  Processed:   {metrics.items_processed}/{metrics.items_total}"
            )
            lines.append(f"  Speed:       {metrics.speed:.2f} items/sec")
            if metrics.errors > 0:
                lines.append(f"  Errors:      {metrics.errors}")

        summary = self.get_summary()
        lines.append(f"\n{'=' * 60}")
        lines.append(
            f"Total Pipeline Time: {summary['pipeline_elapsed']:.2f}s"
        )
        lines.append("=" * 60)

        return "\n".join(lines)
