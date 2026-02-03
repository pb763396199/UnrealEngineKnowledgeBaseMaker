"""
Pipeline 阶段 2: Extract (提取依赖)

解析 .Build.cs 文件，提取模块依赖关系
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import PipelineStage
from ..parsers.buildcs_parser import BuildCsParser


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

    def run(self, **kwargs) -> Dict[str, Any]:
        """
        提取所有模块的依赖关系

        Returns:
            包含提取统计的结果
        """
        # 加载 discover 阶段的结果
        discover_result = self.load_previous_stage_result('discover', 'modules.json')
        if not discover_result:
            raise RuntimeError("Discover 阶段未完成，请先运行 discover")

        modules = discover_result['modules']

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
        保存单个模块的依赖信息

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

        import json
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)
