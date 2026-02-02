"""
UE5 知识库系统 - 插件索引构建器

负责扫描单个 UE5 插件源码，构建插件模块索引
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import traceback

from ..core.config import Config
from ..core.global_index import GlobalIndex
from ..parsers.buildcs_parser import BuildCsParser


class PluginIndexBuilder:
    """
    插件模块索引构建器

    功能:
    - 扫描插件目录下的所有模块
    - 解析 .Build.cs 文件
    - 提取模块依赖关系
    - 统计文件数量和代码行数
    """

    def __init__(self, config: Config):
        """
        初始化构建器

        Args:
            config: 配置对象
        """
        self.config = config
        self.global_index = GlobalIndex(config)
        self.parser = BuildCsParser()
        self.processed_count = 0

    def build_all(self, resume: bool = True) -> GlobalIndex:
        """
        构建插件的全局索引

        Args:
            resume: 是否从检查点恢复

        Returns:
            构建好的全局索引
        """
        plugin_path = self.config.get('project.plugin_path')
        plugin_name = self.config.get('project.plugin_name', 'Unknown')

        print("=" * 60)
        print(f"UE5 插件知识库 - {plugin_name}")
        print("=" * 60)
        print(f"插件路径: {plugin_path}")
        print(f"存储路径: {self.config.storage_base_path}")
        print(f"恢复模式: {resume}")
        print("-" * 60)

        # 扫描插件目录
        if os.path.exists(plugin_path):
            print(f"\n扫描插件目录: {plugin_path}")
            self._scan_plugin_build_cs_files(plugin_path)
        else:
            print(f"错误: 插件路径不存在: {plugin_path}")
            return self.global_index

        # 构建依赖图
        print("\n" + "-" * 60)
        print("构建模块依赖关系图...")
        self.global_index.build_dependency_graph()

        # 保存索引
        print("保存全局索引...")
        self.global_index.save()

        # 构建所有模块的详细图谱
        print("\n" + "-" * 60)
        print("构建所有模块的知识图谱...")
        self._build_all_module_graphs()

        # 输出统计
        stats = self.global_index.get_statistics()

        print("\n" + "=" * 60)
        print("构建完成!")
        print("=" * 60)
        print(f"总模块数: {stats['total_modules']}")
        print(f"总文件数: {stats['total_files']}")
        print(f"预估代码行数: {stats['total_estimated_lines']}")

        # 按分类统计
        print("\n模块分类统计:")
        for category, count in sorted(stats['categories'].items()):
            print(f"  {category}: {count}")

        return self.global_index

    def _scan_plugin_build_cs_files(self, plugin_path: str) -> None:
        """
        扫描插件目录下的所有 .Build.cs 文件

        Args:
            plugin_path: 插件根路径
        """
        plugin_path_obj = Path(plugin_path)

        # 查找插件 Source 目录
        source_path = plugin_path_obj / "Source"
        if not source_path.exists():
            print(f"警告: 插件 Source 目录不存在: {source_path}")
            return

        # 递归搜索所有 .Build.cs 文件
        build_cs_files = []
        for build_cs in source_path.rglob('*.Build.cs'):
            build_cs_files.append(str(build_cs))

        print(f"找到 {len(build_cs_files)} 个模块")

        # 处理每个模块
        for i, build_cs_path in enumerate(build_cs_files, 1):
            try:
                module_info = self._parse_build_cs_path(build_cs_path)
                if module_info:
                    self.global_index.add_module(module_info['name'], module_info)
                    print(f"  [{i}/{len(build_cs_files)}] {module_info['name']} ({module_info['category']})")
            except Exception as e:
                print(f"  [错误] 解析失败: {build_cs_path}")
                print(f"    {e}")
                traceback.print_exc()

    def _parse_build_cs_path(self, build_cs_path: str) -> Optional[Dict[str, Any]]:
        """
        从 .Build.cs 文件路径解析模块信息

        Args:
            build_cs_path: .Build.cs 文件路径

        Returns:
            模块信息字典
        """
        build_cs = Path(build_cs_path)
        module_dir = build_cs.parent

        # 提取模块名称 (去除 .Build.cs 后缀)
        file_name = build_cs.name
        module_name = file_name.replace('.Build.cs', '').replace('.build.cs', '')

        # 推导分类 - 插件模块统一归类为 Plugin
        plugin_name = self.config.get('project.plugin_name', 'Unknown')
        category = f"Plugin.{plugin_name}"

        # 解析 Build.cs 获取依赖
        dependencies = []
        public_dependencies = []
        private_dependencies = []

        try:
            parsed_data = self.parser.parse_file(str(build_cs))
            public_dependencies = parsed_data.get('public', [])
            private_dependencies = parsed_data.get('private', [])
            # 合并所有依赖
            dependencies = list(set(public_dependencies + private_dependencies))
        except Exception as e:
            print(f"  警告: 解析 {build_cs.name} 失败: {e}")

        # 统计文件数量
        file_count = 0
        estimated_lines = 0

        # 查找 Public 和 Private 目录
        for subdir in ['Public', 'Private', 'Classes']:
            subdir_path = module_dir / subdir
            if subdir_path.exists():
                for root, dirs, files in os.walk(subdir_path):
                    for file in files:
                        if file.endswith(('.h', '.cpp', '.inl')):
                            file_count += 1
                            # 假设每个文件平均 200 行
                            estimated_lines += 200

        return {
            'name': module_name,
            'path': str(module_dir),
            'build_cs': str(build_cs),
            'category': category,
            'dependencies': dependencies,
            'public_dependencies': public_dependencies,
            'private_dependencies': private_dependencies,
            'file_count': file_count,
            'estimated_lines': estimated_lines,
            'indexed_at': datetime.now().isoformat()
        }

    def _build_all_module_graphs(self) -> None:
        """构建所有模块的详细知识图谱"""
        from .module_graph_builder import ModuleGraphBuilder

        graph_builder = ModuleGraphBuilder(self.config)
        all_modules = self.global_index.get_all_modules()

        total = len(all_modules)
        print(f"需要构建 {total} 个模块的知识图谱")

        for i, (module_name, module_info) in enumerate(all_modules.items(), 1):
            try:
                print(f"  [{i}/{total}] 构建 {module_name} 的图谱...")
                graph = graph_builder.build_module_graph(
                    module_name,
                    module_info['path']
                )

                if graph:
                    stats = graph.get_statistics()
                    print(f"    → {stats['total_nodes']} 个节点, {stats['total_edges']} 条边")

            except Exception as e:
                print(f"  [错误] 构建 {module_name} 失败: {e}")
                traceback.print_exc()
