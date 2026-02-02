"""
UE5 知识库系统 - 模块图谱构建器

负责构建单个模块的详细代码知识图谱
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import traceback

from ..core.config import Config
from ..core.module_graph import ModuleGraph
from ..parsers.cpp_parser import CppParser


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

        # 收集所有函数信息（用于批量插入）
        all_functions = []

        # 扫描所有源文件
        file_count = 0
        for root, dirs, files in os.walk(module_path):
            # 跳过特定目录
            dirs[:] = [d for d in dirs if d not in ['Intermediate', 'Saved', 'Binaries', 'Private']]

            for file in files:
                if file.endswith(('.h', '.cpp')):
                    file_path = os.path.join(root, file)
                    func_infos = self._parse_source_file(graph, file_path, module_path)
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

    def _parse_source_file(self, graph: ModuleGraph, file_path: str, module_path: str) -> List[Dict[str, Any]]:
        """
        解析源文件并添加到图谱

        Args:
            graph: 模块图谱
            file_path: 源文件路径
            module_path: 模块路径

        Returns:
            提取的函数信息列表（用于函数索引）
        """
        func_infos_for_index = []

        try:
            # 解析文件
            classes, functions = self.parser.parse_file(file_path)

            # 添加文件节点
            rel_path = os.path.relpath(file_path module_path)
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
                    line_number=func_info.line_number
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
