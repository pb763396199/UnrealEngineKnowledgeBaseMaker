"""
Pipeline 阶段 3: Analyze (分析代码)

解析 C++ 源文件，提取类、函数、继承关系
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import PipelineStage
from ..parsers.cpp_parser import CppParser
import json


class AnalyzeStage(PipelineStage):
    """
    分析阶段

    扫描每个模块的源文件，提取代码结构
    """

    @property
    def stage_name(self) -> str:
        return "analyze"

    def get_output_path(self) -> Path:
        return self.stage_dir

    def is_completed(self) -> bool:
        # 检查是否有 summary.json
        summary_file = self.stage_dir / "summary.json"
        return summary_file.exists()

    def run(self, parallel: int = 1, verbose: bool = False, **kwargs) -> Dict[str, Any]:
        """
        分析所有模块的代码结构

        Args:
            parallel: 并行度（暂未实现）
            verbose: 是否显示详细输出

        Returns:
            包含分析统计的结果
        """
        # 加载 discover 和 extract 的结果
        discover_result = self.load_previous_stage_result('discover', 'modules.json')
        if not discover_result:
            raise RuntimeError("Discover 阶段未完成")

        modules = discover_result['modules']

        print(f"[Analyze] 分析 {len(modules)} 个模块的代码结构...")
        print(f"  (这是最耗时的阶段，请耐心等待)")

        parser = CppParser()
        success_count = 0
        failed_modules = []
        total_classes = 0
        total_functions = 0
        all_failed_files = []  # 收集所有失败文件

        for i, module in enumerate(modules):
            # 每个模块都显示进度（改进用户体验）
            print(f"  [{i+1}/{len(modules)}] 正在分析: {module['name']}...")

            try:
                # 获取模块目录
                build_cs_path = Path(module['absolute_path'])
                module_dir = build_cs_path.parent

                # 扫描源文件
                source_files = self._find_source_files(module_dir)

                if not source_files:
                    # 没有源文件，跳过
                    continue

                # 解析源文件（传递 verbose 参数）
                code_graph = self._analyze_module(module['name'], source_files, parser, verbose)

                # 保存结果
                self._save_code_graph(module['name'], code_graph)

                success_count += 1
                total_classes += len(code_graph.get('classes', []))
                total_functions += len(code_graph.get('functions', []))

                # 收集失败文件
                if code_graph.get('failed_files'):
                    all_failed_files.extend(code_graph['failed_files'])

            except Exception as e:
                # 分析失败不应该中断整个流程
                failed_modules.append({
                    'name': module['name'],
                    'error': str(e)
                })

        result = {
            'total_modules': len(modules),
            'analyzed_count': success_count,
            'failed_count': len(failed_modules),
            'total_classes': total_classes,
            'total_functions': total_functions,
            'failed_modules': failed_modules[:10],  # 只保存前10个失败的模块
            'failed_files_sample': all_failed_files[:20]  # 保存前20个失败文件
        }

        # 保存摘要
        self.save_result(result, "summary.json")

        print(f"[Analyze] 完成！")
        print(f"  成功: {success_count}/{len(modules)}")
        print(f"  类: {total_classes}")
        print(f"  函数: {total_functions}")

        # 输出失败的模块列表
        if failed_modules:
            print(f"  失败模块列表:")
            for failed in failed_modules:
                print(f"    - {failed['name']}: {failed['error']}")

        return result

    def _find_source_files(self, module_dir: Path) -> List[Path]:
        """
        查找模块的源文件

        Args:
            module_dir: 模块目录

        Returns:
            源文件列表
        """
        source_files = []

        # 查找 .h 和 .cpp 文件
        for ext in ['*.h', '*.cpp']:
            source_files.extend(module_dir.rglob(ext))

        return source_files

    def _analyze_module(
        self,
        module_name: str,
        source_files: List[Path],
        parser: CppParser,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        分析单个模块

        Args:
            module_name: 模块名
            source_files: 源文件列表
            parser: C++ 解析器
            verbose: 是否显示详细输出

        Returns:
            代码图谱
        """
        classes = []
        functions = []
        failed_files = []

        for file_idx, source_file in enumerate(source_files):
            # 文件级进度（仅当文件数量较多时）
            if len(source_files) > 10 and (file_idx + 1) % 10 == 0:
                print(f"    文件进度: {file_idx + 1}/{len(source_files)}")

            # verbose 模式显示每个文件
            if verbose:
                print(f"      解析: {source_file.name}")

            try:
                # 解析文件
                with open(source_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 提取类
                file_classes = parser.extract_classes(content, str(source_file))
                classes.extend(file_classes)

                # 提取函数
                file_functions = parser.extract_functions(content, str(source_file))
                functions.extend(file_functions)

            except Exception as e:
                # 记录文件解析失败（不再静默忽略）
                print(f"    [警告] 文件解析失败: {source_file.name}")
                print(f"      错误: {e}")
                failed_files.append({
                    'file': str(source_file),
                    'error': str(e),
                    'error_type': type(e).__name__
                })

        return {
            'module': module_name,
            'source_file_count': len(source_files),
            'classes': classes,
            'functions': functions,
            'failed_files': failed_files[:10]  # 只保存前10个失败文件
        }

    def _save_code_graph(self, module_name: str, code_graph: Dict[str, Any]) -> None:
        """
        保存代码图谱

        Args:
            module_name: 模块名
            code_graph: 代码图谱
        """
        module_dir = self.stage_dir / module_name
        module_dir.mkdir(parents=True, exist_ok=True)

        output_file = module_dir / "code_graph.json"

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(code_graph, f, indent=2, ensure_ascii=False)
