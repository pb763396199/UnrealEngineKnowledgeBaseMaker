"""
Pipeline 阶段 2: Extract 并行实现

使用多进程并行提取模块依赖关系
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Any, List, Tuple
from pathlib import Path
import os
import json

from ..parsers.buildcs_parser import BuildCsParser
from ..utils.progress_tracker import ProgressTracker
from rich.console import Console


def _extract_module_worker(args: Tuple) -> Dict[str, Any]:
    """
    Worker 函数：提取单个模块的依赖

    Args:
        args: (module_name, build_cs_path, stage_dir, module_info)

    Returns:
        提取结果
    """
    module_name, build_cs_path, stage_dir, module_info = args

    try:
        parser = BuildCsParser()
        dependencies = parser.parse_file(build_cs_path)

        # 保存结果
        module_dir = Path(stage_dir) / module_name
        module_dir.mkdir(parents=True, exist_ok=True)

        output_file = module_dir / "dependencies.json"

        full_data = {
            "module": module_name,
            "category": module_info["category"],
            "path": module_info["path"],
            "dependencies": dependencies,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)

        return {
            "module": module_name,
            "status": "success",
        }

    except Exception as e:
        return {
            "module": module_name,
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }


class ParallelExtractStage:
    """并行提取阶段"""

    def __init__(self, base_path: Path, num_workers: int = None):
        """
        初始化并行提取阶段

        Args:
            base_path: 引擎/插件根目录
            num_workers: 并行 worker 数量（None = 自动检测）
        """
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "KnowledgeBase" / "data"
        self.stage_dir = self.data_dir / "extract"
        self.stage_dir.mkdir(parents=True, exist_ok=True)

        if num_workers is None:
            num_workers = os.cpu_count() or 4

        self.num_workers = num_workers

    def run(
        self,
        modules: List[Dict[str, Any]],
        force: bool = False,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """
        并行运行提取阶段

        Args:
            modules: 模块列表
            force: 是否强制重新运行
            verbose: 是否显示详细输出

        Returns:
            提取统计结果
        """
        console = Console()

        # 准备任务
        tasks = [
            (
                m["name"],
                m["absolute_path"],
                str(self.stage_dir),
                m,
                i % self.num_workers,  # 添加 worker_id
            )
            for i, m in enumerate(modules)
        ]

        # 创建进度跟踪器
        tracker = ProgressTracker(
            stage_name="extract",
            total_items=len(tasks),
            num_workers=self.num_workers,
            console=console,
        )

        tracker.start()

        results = []
        failed_modules = []

        # 跟踪每个 worker 的完成数量
        worker_completed = {i: 0 for i in range(self.num_workers)}
        worker_total = {i: len([t for t in tasks if t[4] == i]) for i in range(self.num_workers)}

        # 首次更新所有 worker 状态
        for i in range(self.num_workers):
            tracker.update_worker(i, "Initializing...", 0, worker_total[i])

        # 使用进程池并行处理
        with ProcessPoolExecutor(max_workers=self.num_workers) as executor:
            # 存储 (module_name, worker_id)
            future_to_info = {
                executor.submit(_extract_module_worker, task[:4]): (task[0], task[4])
                for task in tasks
            }

            for future in as_completed(future_to_info):
                module_name, worker_id = future_to_info[future]

                try:
                    result = future.result()
                    results.append(result)

                    if result["status"] == "success":
                        worker_completed[worker_id] += 1
                        tracker.increment_total()

                        # 更新 worker 进度条
                        tracker.update_worker(
                            worker_id,
                            module_name,
                            worker_completed[worker_id],
                            worker_total[worker_id]
                        )
                    else:
                        worker_completed[worker_id] += 1
                        failed_modules.append(
                            {
                                "name": module_name,
                                "error": result["error"],
                                "error_type": result["error_type"],
                            }
                        )
                        tracker.add_error(
                            module_name, result["error"], result["error_type"]
                        )
                        tracker.increment_total()

                        # 更新 worker 进度条
                        tracker.update_worker(
                            worker_id,
                            f"Error: {module_name}",
                            worker_completed[worker_id],
                            worker_total[worker_id]
                        )

                except Exception as e:
                    worker_completed[worker_id] += 1
                    failed_modules.append(
                        {
                            "name": module_name,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        }
                    )
                    tracker.add_error(module_name, str(e), type(e).__name__)
                    tracker.increment_total()

                    # 更新 worker 进度条
                    tracker.update_worker(
                        worker_id,
                        f"Error: {module_name}",
                        worker_completed[worker_id],
                        worker_total[worker_id]
                    )

        # 停止进度条并获取统计
        stats = tracker.stop()

        summary = {
            "total_modules": len(modules),
            "success_count": len(results) - len(failed_modules),
            "failed_count": len(failed_modules),
            "failed_modules": failed_modules,
            "elapsed_time": stats["elapsed"],
        }

        self._save_summary(summary)

        # 显示统计信息
        console.print(f"\n[green]Extract 阶段完成！[/green]")
        console.print(
            f"  成功: {summary['success_count']}/{len(modules)}"
        )
        console.print(f"  耗时: {stats['elapsed']:.2f}s")

        return summary

    def _save_summary(self, summary: Dict[str, Any]) -> None:
        """保存摘要"""
        summary_file = self.stage_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
