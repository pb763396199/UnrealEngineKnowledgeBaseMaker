"""
Pipeline 阶段 2: Extract (提取依赖)

解析 .Build.cs 文件，提取模块依赖关系
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import PipelineStage
from ..parsers.buildcs_parser import BuildCsParser
from ..core.manifest import FileInfo, ModuleManifest, Hasher
from datetime import datetime
import os
import json


class ExtractStage(PipelineStage):
    """
    提取阶段

    解析每个模块的 .Build.cs 文件，提取依赖关系
    """

    @property
    def stage_name(self) -> str:
        return "extract"

    def get_output_path(self) -> Path:
        # Extract 阶段的输出是目录（包含多个文件）
        return self.stage_dir

    def is_completed(self) -> bool:
        # 检查 extract/ 目录是否存在且有 summary.json
        summary_file = self.stage_dir / "summary.json"
        return summary_file.exists()

    def run(self, parallel: int = 1, **kwargs) -> Dict[str, Any]:
        """
        提取所有模块的依赖关系

        Args:
            parallel: 并行度（0=自动检测，1=串行，>1=并行）

        Returns:
            包含提取统计的结果
        """
        # 加载 discover 阶段的结果
        discover_result = self.load_previous_stage_result('discover', 'modules.json')
        if not discover_result:
            raise RuntimeError("Discover 阶段未完成，请先运行 discover")

        modules = discover_result['modules']

        # 确定并行度
        if parallel == 0:  # auto
            parallel = os.cpu_count() or 4

        # 如果并行度 > 1，使用并行模式
        if parallel > 1:
            from .extract_parallel import ParallelExtractStage
            from rich.console import Console

            console = Console()
            console.print(f"[cyan]使用并行模式: {parallel} workers[/cyan]")

            parallel_stage = ParallelExtractStage(self.base_path, num_workers=parallel)
            return parallel_stage.run(modules)

        # 否则使用原有的串行逻辑
        return self._run_serial(modules)

    def _run_serial(self, modules: List[Dict]) -> Dict[str, Any]:
        """串行运行提取（原有逻辑）"""
        print(f"[Extract] 提取 {len(modules)} 个模块的依赖...")

        parser = BuildCsParser()
        success_count = 0
        failed_modules = []

        for i, module in enumerate(modules):
            if (i + 1) % 100 == 0:
                print(f"  进度: {i + 1}/{len(modules)}")

            try:
                # 解析 .Build.cs 文件
                dependencies = parser.parse_file(module['absolute_path'])

                # 保存到单独的文件
                self._save_module_dependencies(module['name'], dependencies, module)

                success_count += 1

            except Exception as e:
                print(f"  警告: 解析 {module['name']} 失败: {e}")
                failed_modules.append({
                    'name': module['name'],
                    'error': str(e)
                })

        result = {
            'total_modules': len(modules),
            'success_count': success_count,
            'failed_count': len(failed_modules),
            'failed_modules': failed_modules
        }

        # 保存摘要
        self.save_result(result, "summary.json")

        print(f"[Extract] 完成！成功: {success_count}, 失败: {len(failed_modules)}")

        # 输出失败的模块列表
        if failed_modules:
            print(f"  失败模块列表:")
            for failed in failed_modules:
                print(f"    - {failed['name']}: {failed['error']}")

        return result

    def _save_module_dependencies(
        self,
        module_name: str,
        dependencies: Dict[str, Any],
        module_info: Dict[str, str]
    ) -> None:
        """
        保存单个模块的依赖信息（v2.13.0: 同时创建模块清单）

        Args:
            module_name: 模块名
            dependencies: 依赖字典
            module_info: 模块信息
        """
        module_dir = self.stage_dir / module_name
        module_dir.mkdir(parents=True, exist_ok=True)

        output_file = module_dir / "dependencies.json"

        # 合并模块信息和依赖
        full_data = {
            'module': module_name,
            'category': module_info['category'],
            'path': module_info['path'],
            'dependencies': dependencies
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)

        # v2.13.0: 创建模块清单
        self._create_module_manifest(module_name, module_info, module_dir)

    def _create_module_manifest(
        self,
        module_name: str,
        module_info: Dict[str, str],
        module_dir: Path
    ) -> None:
        """
        创建模块清单文件（v2.13.0 新增）

        Args:
            module_name: 模块名
            module_info: 模块信息
            module_dir: 模块目录
        """
        build_cs_path = Path(module_info['absolute_path'])
        source_dir = build_cs_path.parent

        # 收集所有源文件
        source_files = []
        file_info_dict = {}

        for ext in ['*.h', '*.cpp', '*.inl']:
            for source_file in source_dir.rglob(ext):
                rel_path = str(source_file.relative_to(self.base_path))
                stat = source_file.stat()
                file_hash = Hasher.compute_sha256(source_file)

                file_info_dict[rel_path] = FileInfo(
                    path=rel_path,
                    sha256=file_hash,
                    size=stat.st_size,
                    mtime=stat.st_mtime
                )
                source_files.append(source_file)

        # 计算模块哈希
        module_hash = Hasher.compute_module_hash(build_cs_path, source_files)

        # 获取工具版本
        from ..core.config import Config
        config = Config(self.base_path / "KnowledgeBase")
        tool_version = config.get('project.version', '2.13.0')

        # 创建模块清单
        manifest = ModuleManifest(
            module_name=module_name,
            build_cs_path=module_info['path'],
            category=module_info['category'],
            files=file_info_dict,
            module_hash=module_hash,
            indexed_at=datetime.now().isoformat(),
            parser_version=tool_version
        )

        # 保存模块清单
        manifest_file = module_dir / "module_manifest.json"
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)
