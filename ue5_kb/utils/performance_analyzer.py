"""
性能分析和瓶颈识别工具 (v2.15.0)

用于分析 UE5 知识库构建过程的性能瓶颈
"""

import time
import os
import psutil
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel


@dataclass
class StageMetrics:
    """阶段性能指标"""
    stage_name: str
    elapsed: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    memory_usage_mb: float = 0.0
    cpu_percent: float = 0.0
    io_reads_mb: float = 0.0
    io_writes_mb: float = 0.0
    items_processed: int = 0
    throughput: float = 0.0  # items/sec

    @property
    def elapsed_formatted(self) -> str:
        """格式化耗时"""
        if self.elapsed < 1:
            return f"{self.elapsed * 1000:.2f}ms"
        elif self.elapsed < 60:
            return f"{self.elapsed:.2f}s"
        else:
            mins = int(self.elapsed // 60)
            secs = self.elapsed % 60
            return f"{mins}m {secs:.1f}s"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stage_name': self.stage_name,
            'elapsed': self.elapsed,
            'elapsed_formatted': self.elapsed_formatted,
            'memory_usage_mb': self.memory_usage_mb,
            'cpu_percent': self.cpu_percent,
            'io_reads_mb': self.io_reads_mb,
            'io_writes_mb': self.io_writes_mb,
            'items_processed': self.items_processed,
            'throughput': self.throughput
        }


class PerformanceAnalyzer:
    """
    性能分析器

    功能：
    - 跟踪各阶段耗时和资源使用
    - 识别性能瓶颈
    - 提供优化建议
    - 生成性能报告
    """

    def __init__(self):
        self.metrics: Dict[str, StageMetrics] = {}
        self.process = psutil.Process()
        self.console = Console()
        self.start_time = time.time()

    def start_stage(self, stage_name: str, total_items: int = 0) -> StageMetrics:
        """
        开始阶段计时

        Args:
            stage_name: 阶段名称
            total_items: 预计处理的项目数

        Returns:
            阶段指标对象
        """
        metric = StageMetrics(
            stage_name=stage_name,
            start_time=time.time()
        )
        self.metrics[stage_name] = metric
        return metric

    def end_stage(self, stage_name: str, items_processed: int = 0) -> StageMetrics:
        """
        结束阶段计时

        Args:
            stage_name: 阶段名称
            items_processed: 实际处理的项目数

        Returns:
            阶段指标对象
        """
        if stage_name not in self.metrics:
            raise ValueError(f"Stage {stage_name} not found")

        metric = self.metrics[stage_name]
        metric.end_time = time.time()
        metric.elapsed = metric.end_time - metric.start_time
        metric.items_processed = items_processed

        # 计算吞吐量
        if metric.elapsed > 0 and items_processed > 0:
            metric.throughput = items_processed / metric.elapsed

        # 采集资源使用情况
        metric.memory_usage_mb = self.process.memory_info().rss / 1024 / 1024
        metric.cpu_percent = self.process.cpu_percent()

        # I/O 统计（如果可用）
        try:
            io_counters = self.process.io_counters()
            metric.io_reads_mb = io_counters.read_bytes / 1024 / 1024
            metric.io_writes_mb = io_counters.write_bytes / 1024 / 1024
        except (AttributeError, psutil.AccessDenied):
            pass

        return metric

    def get_bottlenecks(self) -> List[Dict[str, Any]]:
        """
        识别性能瓶颈

        Returns:
            瓶颈列表，按严重程度排序
        """
        bottlenecks = []

        # 按耗时排序
        sorted_metrics = sorted(
            self.metrics.values(),
            key=lambda m: m.elapsed,
            reverse=True
        )

        # 总耗时
        total_elapsed = sum(m.elapsed for m in self.metrics.values())

        for metric in sorted_metrics:
            # 计算占比
            if total_elapsed > 0:
                percentage = (metric.elapsed / total_elapsed) * 100
            else:
                percentage = 0

            # 识别瓶颈
            if percentage > 40:
                severity = "CRITICAL"
            elif percentage > 20:
                severity = "HIGH"
            elif percentage > 10:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            bottlenecks.append({
                'stage': metric.stage_name,
                'elapsed': metric.elapsed,
                'elapsed_formatted': metric.elapsed_formatted,
                'percentage': percentage,
                'severity': severity,
                'throughput': metric.throughput,
                'memory_usage_mb': metric.memory_usage_mb,
                'recommendation': self._get_recommendation(metric)
            })

        return bottlenecks

    def _get_recommendation(self, metric: StageMetrics) -> str:
        """
        获取优化建议

        Args:
            metric: 阶段指标

        Returns:
            优化建议
        """
        stage = metric.stage_name

        if stage == 'discover':
            if metric.throughput < 100:  # modules/sec
                return "考虑使用多线程递归扫描，或限制扫描目录"
            return "性能正常"

        elif stage == 'extract':
            if metric.throughput < 50:  # modules/sec
                return "检查 Hasher 性能，确保使用 1MB 块大小"
            return "性能正常"

        elif stage == 'analyze':
            if metric.throughput < 0.5:  # modules/sec
                return "检查 CppParser 正则预编译，考虑增加并行 worker 数"
            return "性能正常"

        elif stage == 'build':
            if metric.throughput < 10:  # modules/sec
                return "确保使用批量写入和并行索引构建"
            return "性能正常"

        elif stage == 'generate':
            if metric.throughput < 100:  # operations/sec
                return "检查 Skill 模板渲染性能"
            return "性能正常"

        return "无特定建议"

    def generate_report(self) -> str:
        """
        生成性能报告

        Returns:
            Markdown 格式的报告
        """
        lines = []

        lines.append("# UE5 知识库性能分析报告")
        lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 总耗时
        total_elapsed = sum(m.elapsed for m in self.metrics.values())
        lines.append(f"\n## 总体统计")
        lines.append(f"- **总耗时**: {total_elapsed:.2f}s")
        lines.append(f"- **阶段数量**: {len(self.metrics)}")

        # 瓶颈分析
        bottlenecks = self.get_bottlenecks()

        lines.append(f"\n## 性能瓶颈分析")

        for bottleneck in bottlenecks:
            severity_emoji = {
                'CRITICAL': '🔴',
                'HIGH': '🟠',
                'MEDIUM': '🟡',
                'LOW': '🟢'
            }[bottleneck['severity']]

            lines.append(f"\n### {severity_emoji} {bottleneck['stage']}")
            lines.append(f"- **耗时**: {bottleneck['elapsed_formatted']} ({bottleneck['percentage']:.1f}%)")
            lines.append(f"- **吞吐量**: {bottleneck['throughput']:.2f} items/sec")
            lines.append(f"- **内存**: {bottleneck['memory_usage_mb']:.1f} MB")
            lines.append(f"- **优化建议**: {bottleneck['recommendation']}")

        # 详细指标表
        lines.append(f"\n## 详细性能指标")

        for metric in self.metrics.values():
            lines.append(f"\n### {metric.stage_name}")
            lines.append(f"- 耗时: {metric.elapsed_formatted}")
            lines.append(f"- 处理项目: {metric.items_processed}")
            lines.append(f"- 吞吐量: {metric.throughput:.2f} items/sec")
            lines.append(f"- 内存: {metric.memory_usage_mb:.1f} MB")
            lines.append(f"- CPU: {metric.cpu_percent:.1f}%")
            if metric.io_reads_mb > 0:
                lines.append(f"- 读取: {metric.io_reads_mb:.1f} MB")
            if metric.io_writes_mb > 0:
                lines.append(f"- 写入: {metric.io_writes_mb:.1f} MB")

        # 优化建议摘要
        lines.append(f"\n## 优化建议摘要")

        high_priority = [
            b for b in bottlenecks
            if b['severity'] in ['CRITICAL', 'HIGH']
        ]

        if high_priority:
            lines.append(f"\n### 优先处理")
            for item in high_priority:
                lines.append(f"- **{item['stage']}**: {item['recommendation']}")
        else:
            lines.append(f"\n[OK] 没有严重瓶颈，整体性能良好")

        return '\n'.join(lines)

    def print_report(self) -> None:
        """打印性能报告到控制台"""
        bottlenecks = self.get_bottlenecks()

        # 总耗时
        total_elapsed = sum(m.elapsed for m in self.metrics.values())

        self.console.print(Panel.fit(
            f"[bold]UE5 知识库性能分析[/bold]\n"
            f"总耗时: {total_elapsed:.2f}s | 阶段数: {len(self.metrics)}",
            title="总体统计"
        ))

        # 瓶颈表格
        table = Table(title="性能瓶颈分析")
        table.add_column("阶段", style="cyan")
        table.add_column("耗时", justify="right")
        table.add_column("占比", justify="right")
        table.add_column("吞吐量", justify="right")
        table.add_column("内存", justify="right")
        table.add_column("严重程度", justify="center")

        for bottleneck in bottlenecks[:5]:  # 只显示前5个
            severity_style = {
                'CRITICAL': 'red',
                'HIGH': 'orange3',
                'MEDIUM': 'yellow',
                'LOW': 'green'
            }[bottleneck['severity']]

            table.add_row(
                bottleneck['stage'],
                bottleneck['elapsed_formatted'],
                f"{bottleneck['percentage']:.1f}%",
                f"{bottleneck['throughput']:.2f}/s",
                f"{bottleneck['memory_usage_mb']:.1f}MB",
                f"[{severity_style}]{bottleneck['severity']}[/]"
            )

        self.console.print(table)

        # 优化建议
        high_priority = [
            b for b in bottlenecks
            if b['severity'] in ['CRITICAL', 'HIGH']
        ]

        if high_priority:
            self.console.print("\n[bold yellow]优化建议:[/bold yellow]")
            for item in high_priority:
                self.console.print(f"  - {item['stage']}: {item['recommendation']}")
        else:
            self.console.print("\n[green][OK] 没有严重瓶颈，整体性能良好[/green]")

    def save_report(self, output_path: Path) -> None:
        """
        保存性能报告到文件

        Args:
            output_path: 输出文件路径
        """
        report = self.generate_report()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        self.console.print(f"\n[OK] 性能报告已保存: {output_path}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_elapsed': sum(m.elapsed for m in self.metrics.values()),
            'stages': {name: metric.to_dict() for name, metric in self.metrics.items()},
            'bottlenecks': self.get_bottlenecks()
        }


# 使用示例
if __name__ == "__main__":
    analyzer = PerformanceAnalyzer()

    # 模拟 pipeline 执行
    analyzer.start_stage('discover')
    time.sleep(0.5)
    analyzer.end_stage('discover', 1757)

    analyzer.start_stage('extract')
    time.sleep(2.0)
    analyzer.end_stage('extract', 1757)

    analyzer.start_stage('analyze')
    time.sleep(10.0)
    analyzer.end_stage('analyze', 1700)

    analyzer.start_stage('build')
    time.sleep(5.0)
    analyzer.end_stage('build', 1700)

    analyzer.start_stage('generate')
    time.sleep(1.0)
    analyzer.end_stage('generate', 1)

    # 打印报告
    analyzer.print_report()

    # 保存报告
    analyzer.save_report(Path("performance_report.md"))
