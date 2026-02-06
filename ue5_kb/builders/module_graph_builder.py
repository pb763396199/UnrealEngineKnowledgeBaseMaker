"""
UE5 知识库系统 - 模块图谱构建器

负责构建单个模块的详细代码知识图谱
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import traceback

from ..core.config import Config
from ..core.module_graph import ModuleGraph
from ..parsers.cpp_parser import CppParser
from .header_cpp_mapper import HeaderToCppMapper


class ModuleGraphBuilder:
    """
    模块知识图谱构建器

    功能:
    - 扫描模块源文件
    - 解析 C++ 代码结构
    - 提取类、函数、继承关系
    - 构建代码关系图谱
    """

    def __init__(self, config: Config):
        """
        初始化构建器

        Args:
            config: 配置对象
        """
        self.config = config
        self.parser = CppParser()

    def build_module_graph(self, module_name: str, module_path: str) -> ModuleGraph:
        """
        构建单个模块的知识图谱

        Args:
            module_name: 模块名称
            module_path: 模块路径

        Returns:
            构建好的模块图谱
        """
        graph = ModuleGraph(self.config, module_name)
        # NetworkX 图属性设置
        graph.graph.graph['module'] = module_name
        graph.graph.graph['built_at'] = datetime.now().isoformat()

        # 初始化函数索引（如果启用）
        func_index = None
        try:
            from ue5_kb.core.function_index import FunctionIndex
            func_index_path = Path(self.config.storage_base_path) / "global_index" / "function_index.db"
            func_index = FunctionIndex(str(func_index_path))
        except Exception as e:
            print(f"  警告: 无法初始化函数索引: {e}")

        # 新增：构建头文件到 cpp 文件的映射
        mapper = None
        try:
            mapper = HeaderToCppMapper(module_path)
            header_to_cpps = mapper.build_mapping()
        except Exception as e:
            print(f"  警告: 构建头文件映射失败: {e}")
            header_to_cpps = {}

        # 收集所有函数信息（用于批量插入）
        all_functions = []

        # 扫描所有源文件
        file_count = 0
        for root, dirs, files in os.walk(module_path):
            # 跳过特定目录
            dirs[:] = [d for d in dirs if d not in ['Intermediate', 'Saved', 'Binaries', 'Private']]

            for file in files:
                if file.endswith('.h'):
                    file_path = os.path.join(root, file)
                    # 获取包含此头文件的 cpp 文件列表
                    related_cpps = header_to_cpps.get(file_path, [])
                    func_infos = self._parse_source_file(
                        graph, file_path, module_path,
                        related_cpps=related_cpps
                    )
                    if func_infos and func_index:
                        all_functions.extend(func_infos)
                    file_count += 1

        # 批量添加函数到索引（性能优化）
        if func_index and all_functions:
            func_index.add_functions_batch(all_functions)
            func_index.commit()
            func_index.close()

        # 保存图谱
        graph.save()

        return graph

    def build_core_modules(self, global_index) -> Dict[str, ModuleGraph]:
        """
        构建所有核心模块的图谱

        Args:
            global_index: 全局索引对象

        Returns:
            模块名称到图谱的字典
        """
        print("=" * 60)
        print("构建核心模块知识图谱")
        print("=" * 60)

        graphs = {}
        core_modules = self.config.core_modules

        for i, module_name in enumerate(core_modules, 1):
            module_info = global_index.get_module(module_name)

            if not module_info:
                print(f"警告: 模块 {module_name} 不在全局索引中")
                continue

            print(f"[{i}/{len(core_modules)}] 构建: {module_name}")
            graph = self.build_module_graph(module_name, module_info['path'])
            graphs[module_name] = graph

            stats = graph.get_statistics()
            print(f"  节点: {stats['total_nodes']}, 边: {stats['total_edges']}")

        print("=" * 60)
        print(f"完成! 构建了 {len(graphs)} 个核心模块图谱")
        print("=" * 60)

        return graphs

    def _parse_source_file(
        self, graph: ModuleGraph, file_path: str, module_path: str,
        related_cpps: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        解析源文件并添加到图谱

        Args:
            graph: 模块图谱
            file_path: 源文件路径
            module_path: 模块路径
            related_cpps: 包含此头文件的所有 cpp 文件列表

        Returns:
            提取的函数信息列表（用于函数索引）
        """
        func_infos_for_index = []
        related_cpps = related_cpps or []

        try:
            # 解析文件
            classes, functions = self.parser.parse_file(file_path)

            # 添加文件节点
            rel_path = os.path.relpath(file_path, module_path)
            safe_path = rel_path.replace('/', '_').replace('\\', '_')
            file_id = f"file_{safe_path}"
            graph.add_node(file_id, ModuleGraph.NODE_TYPE_FILE, name=rel_path, path=file_path)

            # 添加类节点和关系
            for class_name, class_info in classes.items():
                class_id = f"class_{class_name}"

                # 添加类节点
                graph.add_node(
                    class_id,
                    ModuleGraph.NODE_TYPE_CLASS,
                    name=class_name,
                    is_uclass=class_info.is_uclass,
                    is_struct=class_info.is_struct,
                    is_interface=class_info.is_interface,
                    file_path=class_info.file_path,
                    line_number=class_info.line_number
                )

                # 文件包含类
                graph.add_edge(file_id, class_id, ModuleGraph.REL_TYPE_CONTAINS)

                # 继承关系
                if class_info.parent_class:
                    parent_id = f"class_{class_info.parent_class}"
                    graph.add_edge(class_id, parent_id, ModuleGraph.REL_TYPE_INHERITS)

                # 接口实现
                for interface in class_info.interfaces:
                    interface_id = f"class_{interface}"
                    graph.add_edge(class_id, interface_id, ModuleGraph.REL_TYPE_IMPLEMENTS)

                # 方法关系
                for method in class_info.methods:
                    method_id = f"method_{class_name}_{method}"
                    graph.add_node(method_id, ModuleGraph.NODE_TYPE_FUNCTION, name=method, class_name=class_name)
                    graph.add_edge(class_id, method_id, ModuleGraph.REL_TYPE_HAS_METHOD)

            # 添加函数节点并收集索引信息
            for func_key, func_info in functions.items():
                # 设置文件路径
                func_info.file_path = file_path

                # 如果有相关的 cpp 文件，尝试找到函数定义
                if related_cpps:
                    # 优先策略：查找同名 cpp 文件
                    basename = os.path.splitext(os.path.basename(file_path))[0]
                    same_name_cpp = None
                    for cpp in related_cpps:
                        if os.path.splitext(os.path.basename(cpp))[0] == basename:
                            same_name_cpp = cpp
                            break

                    # 设置实现文件
                    if same_name_cpp:
                        func_info.impl_file_path = same_name_cpp
                    else:
                        func_info.impl_file_path = related_cpps[0]

                    func_info.impl_candidates = related_cpps

                    # 尝试在 cpp 文件中精确定位函数定义行号
                    if func_info.impl_file_path:
                        line_num = self._find_function_definition(
                            func_info.impl_file_path,
                            func_info.name,
                            func_info.class_name
                        )
                        if line_num > 0:
                            func_info.impl_line_number = line_num

                # 跳过类方法（已在类中处理）
                if func_info.class_name:
                    continue

                func_id = f"function_{func_info.name}_{func_info.line_number}"

                # 添加到图谱
                graph.add_node(
                    func_id,
                    ModuleGraph.NODE_TYPE_FUNCTION,
                    name=func_info.name,
                    return_type=func_info.return_type,
                    parameters=func_info.parameters,
                    is_ufunction=func_info.is_ufunction,
                    is_blueprint_callable=func_info.is_blueprint_callable,
                    file_path=func_info.file_path,
                    line_number=func_info.line_number,
                    impl_file=func_info.impl_file_path,
                    impl_line=func_info.impl_line_number
                )
                graph.add_edge(file_id, func_id, ModuleGraph.REL_TYPE_CONTAINS)

                # 收集函数信息用于索引
                signature = self.parser.format_function_signature(func_info)
                func_infos_for_index.append({
                    'name': func_info.name,
                    'module': graph.module_name,
                    'class_name': func_info.class_name,
                    'return_type': func_info.return_type,
                    'parameters': [p.to_dict() for p in func_info.parameters],
                    'signature': signature,
                    'file_path': func_info.file_path,
                    'line_number': func_info.line_number,
                    'impl_file_path': func_info.impl_file_path,
                    'impl_line_number': func_info.impl_line_number,
                    'is_virtual': func_info.is_virtual,
                    'is_const': func_info.is_const,
                    'is_static': func_info.is_static,
                    'is_override': func_info.is_override,
                    'is_blueprint_callable': func_info.is_blueprint_callable,
                    'ufunction_specifiers': func_info.ufunction_specifiers
                })

        except Exception as e:
            print(f"  警告: 解析文件 {file_path} 时出错: {e}")

        return func_infos_for_index

    def _find_function_definition(self, cpp_path: str, func_name: str, class_name: str = None) -> int:
        """
        在 cpp 文件中查找函数定义的行号

        Args:
            cpp_path: CPP 文件路径
            func_name: 函数名称
            class_name: 类名称（可选）

        Returns:
            函数定义的行号，如果找不到则返回 0
        """
        try:
            with open(cpp_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # 构建函数定义模式
            if class_name:
                # 类成员函数: ReturnType ClassName::FunctionName(...)
                patterns = [
                    rf'\b\w+\s+{class_name}::\s*{func_name}\s*\(',
                    rf'\bvoid\s+{class_name}::\s*{func_name}\s*\(',
                ]
            else:
                # 普通函数: ReturnType FunctionName(...)
                patterns = [
                    rf'\b\w+\s+{func_name}\s*\(',
                    rf'\bvoid\s+{func_name}\s*\(',
                ]

            for i, line in enumerate(lines, 1):
                for pattern in patterns:
                    if re.search(pattern, line):
                        return i
        except Exception:
            pass
        return 0


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="UE5 模块图谱构建器")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--base-path", help="知识库基础路径")
    parser.add_argument("--module", help="指定模块名称")
    parser.add_argument("--path", help="指定模块路径")
    parser.add_argument("--core", action="store_true", help="构建所有核心模块")

    args = parser.parse_args()

    # 加载配置
    if args.config:
        config = Config(args.config)
    elif args.base_path:
        config = Config(base_path=args.base_path)
    else:
        parser.error("必须指定 --config 或 --base-path 参数")

    builder = ModuleGraphBuilder(config)

    if args.module and args.path:
        # 构建单个模块
        graph = builder.build_module_graph(args.module, args.path)
        print(f"构建完成: {graph}")
    elif args.core:
        # 构建核心模块
        from ..core.global_index import GlobalIndex
        global_index = GlobalIndex(config)
        graphs = builder.build_core_modules(global_index)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
