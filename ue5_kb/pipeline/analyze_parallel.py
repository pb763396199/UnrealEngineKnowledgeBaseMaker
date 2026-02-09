"""
Pipeline 阶段 3: Analyze 并行实现

使用多进程并行分析 C++ 源文件
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Any, List, Tuple
from pathlib import Path
import os
import json

from ..parsers.cpp_parser import CppParser
from ..utils.progress_tracker import ProgressTracker
from ..utils.checkpoint_manager import CheckpointManager
from rich.console import Console


def _analyze_module_worker(args: Tuple) -> Dict[str, Any]:
    """
    Worker 函数：分析单个模块（在独立进程中执行）

    这个函数在独立的进程中执行，因此需要：
    1. 接收所有必要的参数
    2. 不依赖外部状态
    3. 返回可序列化的结果

    Args:
        args: (module_name, module_dir, stage_dir, worker_id, verbose)

    Returns:
        包含分析结果的字典
    """
    module_name, module_dir, stage_dir, worker_id, verbose = args

    try:
        # 查找源文件
        source_files = []
        for ext in ["*.h", "*.cpp"]:
            source_files.extend(Path(module_dir).rglob(ext))

        if not source_files:
            return {
                "module": module_name,
                "status": "skipped",
                "reason": "no source files",
            }

        # 解析源文件
        parser = CppParser()
        classes = []
        functions = []
        enums = []
        failed_files = []

        for file_idx, source_file in enumerate(source_files):
            try:
                with open(
                    source_file, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    content = f.read()

                file_classes = parser.extract_classes(content, str(source_file))
                classes.extend(file_classes)

                file_functions = parser.extract_functions(
                    content, str(source_file)
                )
                functions.extend(file_functions)

                # v2.14.0: 提取枚举
                file_enums = parser.extract_enums(content, str(source_file))
                enums.extend(file_enums)

            except Exception as e:
                failed_files.append(
                    {
                        "file": str(source_file),
                        "error": str(e),
                        "error_type": type(e).__name__,
                    }
                )

        # 保存结果
        module_output_dir = Path(stage_dir) / module_name
        module_output_dir.mkdir(parents=True, exist_ok=True)

        code_graph = {
            "module": module_name,
            "source_file_count": len(source_files),
            "classes": classes,
            "functions": functions,
            "enums": enums,
            "failed_files": failed_files[:10],
        }

        output_file = module_output_dir / "code_graph.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(code_graph, f, indent=2, ensure_ascii=False)

        return {
            "module": module_name,
            "status": "success",
            "classes_count": len(classes),
            "functions_count": len(functions),
            "files_count": len(source_files),
            "failed_files_count": len(failed_files),
        }

    except Exception as e:
        return {
            "module": module_name,
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }


class ParallelAnalyzeStage:
    """
    并行分析阶段

    特性：
    - 进程池并行处理
    - 多进度条实时显示
    - Checkpoint 机制支持中断恢复
    - 错误隔离
    """

    def __init__(self, base_path: Path, num_workers: int = None):
        """
        初始化并行分析阶段

        Args:
            base_path: 引擎/插件根目录
            num_workers: 并行 worker 数量（None = 自动检测）
        """
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "KnowledgeBase" / "data"
        self.stage_dir = self.data_dir / "analyze"
        self.stage_dir.mkdir(parents=True, exist_ok=True)

        # 默认使用 CPU 核心数
        if num_workers is None:
            num_workers = os.cpu_count() or 4

        self.num_workers = num_workers
        self.checkpoint_manager = CheckpointManager(self.stage_dir, "analyze")

    def run(
        self,
        modules: List[Dict[str, Any]],
        force: bool = False,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """
        并行运行分析阶段

        Args:
            modules: 模块列表
            force: 是否强制重新运行
            verbose: 是否显示详细输出

        Returns:
            分析统计结果
        """
        console = Console()

        # 加载 checkpoint
        completed_modules = self.checkpoint_manager.get_completed_tasks()

        # 过滤已完成的模块
        if not force:
            modules_to_process = [
                m for m in modules if m["name"] not in completed_modules
            ]
        else:
            modules_to_process = modules

        if not modules_to_process:
            console.print("[yellow]所有模块已分析完成（从 checkpoint 恢复）[/yellow]")
            return self._load_summary()

        # 创建进度跟踪器
        tracker = ProgressTracker(
            stage_name="analyze",
            total_items=len(modules_to_process),
            num_workers=self.num_workers,
            console=console,
        )

        tracker.start()

        # 准备任务参数
        tasks = [
            (
                m["name"],
                str(Path(m["absolute_path"]).parent),
                str(self.stage_dir),
                i % self.num_workers,
                verbose,
            )
            for i, m in enumerate(modules_to_process)
        ]

        # 结果收集
        results = []
        failed_modules = []
        total_classes = 0
        total_functions = 0

        # 跟踪每个 worker 的完成数量（用于显示进度）
        worker_completed = {i: 0 for i in range(self.num_workers)}
        worker_total = {i: len([t for t in tasks if t[3] == i]) for i in range(self.num_workers)}

        # 使用进程池并行处理
        with ProcessPoolExecutor(max_workers=self.num_workers) as executor:
            # 提交所有任务 - 存储 (module_name, worker_id)
            future_to_info = {
                executor.submit(_analyze_module_worker, task): (task[0], task[3])
                for task in tasks
            }

            # 首次更新所有 worker 状态
            for i in range(self.num_workers):
                tracker.update_worker(i, "Initializing...", 0, worker_total[i])

            # 收集结果
            for future in as_completed(future_to_info):
                module_name, worker_id = future_to_info[future]

                try:
                    result = future.result()
                    results.append(result)

                    if result["status"] == "success":
                        total_classes += result["classes_count"]
                        total_functions += result["functions_count"]
                        worker_completed[worker_id] += 1
                        tracker.increment_total()

                        # 更新 worker 进度条
                        tracker.update_worker(
                            worker_id,
                            module_name,
                            worker_completed[worker_id],
                            worker_total[worker_id]
                        )

                        # 更新 checkpoint
                        self.checkpoint_manager.save_completed(module_name, result)

                    elif result["status"] == "error":
                        worker_completed[worker_id] += 1
                        failed_modules.append(
                            {
                                "name": module_name,
                                "error": result["error"],
                                "error_type": result["error_type"],
                            }
                        )
                        tracker.add_error(
                            module=module_name,
                            error=result["error"],
                            error_type=result["error_type"],
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
                    tracker.add_error(
                        module=module_name,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
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

        # 显示统计信息
        console.print(f"\n[green]Analyze 阶段完成！[/green]")
        console.print(f"  成功: {len(results) - len(failed_modules)}/{len(modules_to_process)}")
        console.print(f"  类: {total_classes}")
        console.print(f"  函数: {total_functions}")
        console.print(f"  耗时: {stats['elapsed']:.2f}s")
        console.print(f"  速度: {stats['speed']:.2f} modules/sec")

        if failed_modules:
            console.print(f"\n[yellow]失败模块 ({len(failed_modules)}):[/yellow]")
            for failed in failed_modules[:10]:
                console.print(f"  - {failed['name']}: {failed['error_type']}")

        # 保存摘要
        summary = {
            "total_modules": len(modules),
            "analyzed_count": len(results) - len(failed_modules),
            "failed_count": len(failed_modules),
            "total_classes": total_classes,
            "total_functions": total_functions,
            "failed_modules": failed_modules[:10],
            "elapsed_time": stats["elapsed"],
            "speed": stats["speed"],
        }

        self._save_summary(summary)

        return summary

    def _load_summary(self) -> Dict[str, Any]:
        """加载摘要"""
        summary_file = self.stage_dir / "summary.json"
        if not summary_file.exists():
            return {}
        with open(summary_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_summary(self, summary: Dict[str, Any]) -> None:
        """保存摘要"""
        summary_file = self.stage_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
