"""
UE5 知识库系统 - 全局索引构建器

负责扫描整个 UE5 引擎源码，构建全局模块索引
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


class GlobalIndexBuilder:
    """
    全局模块索引构建器

    功能:
    - 扫描所有模块目录
    - 解析 .Build.cs 文件
    - 提取模块依赖关系
    - 统计文件数量和代码行数
    - 保存检查点以支持恢复
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
        构建所有模块的全局索引

        Args:
            resume: 是否从检查点恢复

        Returns:
            构建好的全局索引
        """
        print("=" * 60)
        print("UE5 知识库系统 - 全局索引构建")
        print("=" * 60)
        print(f"引擎路径: {self.config.engine_path}")
        print(f"存储路径: {self.config.storage_base_path}")
        print(f"恢复模式: {resume}")
        print("-" * 60)

        # 统一扫描: 直接搜索所有 .Build.cs 文件
        engine_path = os.path.join(self.config.engine_path, "Engine")
        if os.path.exists(engine_path):
            print("\n扫描 Engine 目录下所有模块...")
            print("  搜索范围: Source/, Plugins/, Platforms/")
            self._scan_all_build_cs_files(engine_path)
        else:
            print(f"错误: 引擎路径不存在: {engine_path}")
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
        verification = self.global_index.verify_coverage()

        print("\n" + "=" * 60)
        print("构建完成!")
        print("=" * 60)
        print(f"总模块数: {stats['total_modules']}")
        print(f"总文件数: {stats['total_files']}")
        print(f"预估代码行数: {stats['total_estimated_lines']}")
        print(f"覆盖率: {verification['coverage_percent']:.2f}%")
        print(f"验证通过: {verification['verification_passed']}")

        # 按分类统计
        print("\n模块分类统计:")
        for category, count in sorted(stats['categories'].items()):
            print(f"  {category}: {count} 个模块")

        return self.global_index

    def _scan_all_build_cs_files(self, engine_path: str) -> None:
        """
        扫描 Engine 目录下所有 .Build.cs 文件
        根据 .Build.cs 文件路径自动推导分类

        Args:
            engine_path: Engine 目录路径
        """
        from pathlib import Path

        engine_path = Path(engine_path)
        build_cs_files = []

        # 递归搜索所有 .Build.cs 文件
        # 搜索范围: Source/, Plugins/, Platforms/
        for root_dir in ['Source', 'Plugins', 'Platforms']:
            target_path = engine_path / root_dir
            if not target_path.exists():
                continue

            # 使用 rglob 递归搜索
            for build_cs in target_path.rglob('*.Build.cs'):
                build_cs_files.append(str(build_cs))

        print(f"  找到 {len(build_cs_files)} 个 .Build.cs 文件")

        # 处理每个 .Build.cs 文件
        for build_cs_path in build_cs_files:
            try:
                # 从路径推导分类和模块名
                category, module_name = self._parse_build_cs_path(build_cs_path, engine_path)

                if module_name:
                    self._process_module(module_name, build_cs_path, category)

                    # 每处理 N 个模块保存一次检查点
                    if self.processed_count % self.config.checkpoint_interval == 0:
                        self._save_checkpoint()

            except Exception as e:
                print(f"  警告: 处理 {build_cs_path} 时出错: {e}")

    def _parse_build_cs_path(self, build_cs_path: str, engine_path: Path) -> tuple:
        """
        从 .Build.cs 文件路径推导分类和模块名

        Args:
            build_cs_path: .Build.cs 文件路径
            engine_path: Engine 目录路径

        Returns:
            (category, module_name) 元组
        """
        from pathlib import Path

        build_cs = Path(build_cs_path)
        rel_path = build_cs.relative_to(engine_path)

        # 提取模块名 (文件名去掉 .Build.cs 后缀)
        module_name = build_cs.stem  # 例如: "Core" from "Core.Build.cs"

        # 根据路径结构推导分类
        parts = list(rel_path.parts)

        if parts[0] == 'Source':
            # Engine/Source/{Category}/{Module}/{Module}.Build.cs
            if len(parts) >= 3:
                category = parts[1]  # Runtime, Editor, Developer, Programs
                return category, module_name

        elif parts[0] == 'Plugins':
            # Engine/Plugins/{PluginType}/{PluginName}/.../{Module}.Build.cs
            if len(parts) >= 3:
                plugin_type = parts[1]   # Editor, Runtime, Martketplace, etc.
                plugin_name = parts[2]   # BlueprintAssist_5.1, etc.
                category = f"Plugins.{plugin_type}.{plugin_name}"
                return category, module_name

        elif parts[0] == 'Platforms':
            # Engine/Platforms/{PlatformName}/.../{Module}.Build.cs
            category = f"Platforms.{parts[1]}" if len(parts) >= 2 else "Platforms"
            return category, module_name

        # 默认分类
        return "Unknown", module_name

    def _scan_category(self, category_path: str, category: str) -> None:
        """
        扫描指定分类下的所有模块

        Args:
            category_path: 分类路径
            category: 分类名称
        """
        try:
            entries = os.listdir(category_path)
        except Exception as e:
            print(f"警告: 无法读取目录 {category_path}: {e}")
            return

        for entry in entries:
            entry_path = os.path.join(category_path, entry)

            # 跳过非目录
            if not os.path.isdir(entry_path):
                continue

            # 查找 .Build.cs 文件
            build_cs = BuildCsParser.find_module_build_cs(entry_path)

            if build_cs and os.path.exists(build_cs):
                self._process_module(entry, build_cs, category)

            # 每处理 N 个模块保存一次检查点
            if self.processed_count % self.config.checkpoint_interval == 0:
                self._save_checkpoint()

    def _process_module(self, module_name: str, build_cs_path: str, category: str) -> None:
        """
        处理单个模块

        Args:
            module_name: 模块名称
            build_cs_path: .Build.cs 文件路径
            category: 模块分类
        """
        try:
            # 解析依赖 - parse_file 返回字典
            dep_dict = self.parser.parse_file(build_cs_path)

            # 统计文件
            module_path = os.path.dirname(build_cs_path)
            file_count, estimated_lines = self._count_module_files(module_path)

            # 提取主要类（可选，需要更深入的解析）
            main_classes = []  # 暂时留空

            # 从字典中提取所有依赖
            all_deps = []
            for dep_list in dep_dict.values():
                all_deps.extend(dep_list)
            all_deps = sorted(set(all_deps))

            module_info = {
                'name': module_name,
                'path': module_path,
                'category': category,
                'dependencies': all_deps,
                'public_dependencies': dep_dict.get('public', []),
                'private_dependencies': dep_dict.get('private', []),
                'dynamic_dependencies': dep_dict.get('dynamic', []),
                'weak_dependencies': dep_dict.get('weak', []),
                'circular_dependencies': dep_dict.get('circular', []),
                'file_count': file_count,
                'estimated_lines': estimated_lines,
                'main_classes': main_classes,
                'build_cs_path': build_cs_path
            }

            self.global_index.add_module(module_name, module_info)
            self.processed_count += 1

            if self.processed_count % 50 == 0 or self.processed_count <= 10:
                print(f"  已处理: {self.processed_count} 个模块 - 当前: {module_name}")

        except Exception as e:
            print(f"警告: 处理模块 {module_name} 时出错: {e}")
            traceback.print_exc()

    def _count_module_files(self, module_path: str) -> tuple:
        """
        统计模块文件数量和预估代码行数

        Args:
            module_path: 模块路径

        Returns:
            (文件数量, 预估代码行数)
        """
        file_count = 0
        line_count = 0

        for root, dirs, files in os.walk(module_path):
            # 跳过特定目录
            dirs[:] = [d for d in dirs if d not in ['Intermediate', 'Saved', 'Binaries']]

            for file in files:
                if file.endswith(('.h', '.cpp', '.hxx', '.cxx', '.cc', '.inl')):
                    file_count += 1
                    file_path = os.path.join(root, file)

                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            line_count += sum(1 for _ in f)
                    except Exception:
                        pass

        return file_count, line_count

    def _save_checkpoint(self) -> None:
        """保存检查点"""
        checkpoint_file = os.path.join(
            self.config.checkpoints_path,
            f"global_index_checkpoint_{self.processed_count}.json"
        )
        os.makedirs(self.config.checkpoints_path, exist_ok=True)

        # 保存当前状态
        import json
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump({
                'processed_count': self.processed_count,
                'timestamp': datetime.now().isoformat()
            }, f, indent=2)

        # 同时保存完整索引
        self.global_index.save()

        print(f"  [检查点] 已处理 {self.processed_count} 个模块")

    def build_core_modules_only(self) -> GlobalIndex:
        """
        仅构建核心模块的索引（用于快速测试）

        Returns:
            构建好的全局索引（仅包含核心模块）
        """
        print("构建核心模块索引...")

        engine_path = Path(os.path.join(self.config.engine_path, "Engine"))
        source_path = engine_path / "Source"

        if not source_path.exists():
            print("  警告: Engine/Source 目录不存在")
            return self.global_index

        for module_name in self.config.core_modules:
            # 使用 rglob 搜索匹配的 .Build.cs 文件
            for build_cs in source_path.rglob(f"{module_name}.Build.cs"):
                # 推导分类
                category, _ = self._parse_build_cs_path(str(build_cs), engine_path)
                self._process_module(module_name, str(build_cs), category)
                break

        self.global_index.build_dependency_graph()
        self.global_index.save()

        return self.global_index

    def _build_all_module_graphs(self) -> None:
        """
        构建所有模块的知识图谱

        为全局索引中的每个模块创建详细的知识图谱文件
        """
        from .module_graph_builder import ModuleGraphBuilder

        graph_builder = ModuleGraphBuilder(self.config)
        all_modules = self.global_index.get_all_modules()

        total = len(all_modules)
        print(f"开始构建 {total} 个模块的知识图谱...")

        for i, (module_name, module_info) in enumerate(all_modules.items(), 1):
            try:
                # 检查是否已经存在图谱文件
                graph_file = os.path.join(
                    self.config.module_graphs_path,
                    f"{module_name}.pkl"
                )

                if os.path.exists(graph_file):
                    # 跳过已存在的图谱
                    continue

                # 构建模块图谱
                graph = graph_builder.build_module_graph(module_name, module_info['path'])

                stats = graph.get_statistics()
                if i % 100 == 0 or i <= 10:
                    print(f"  [{i}/{total}] {module_name}: {stats['total_nodes']} 节点, {stats['total_edges']} 边")

            except Exception as e:
                print(f"  警告: 构建模块 {module_name} 图谱时出错: {e}")

        print(f"知识图谱构建完成!")

    def __repr__(self) -> str:
        return f"GlobalIndexBuilder(processed={self.processed_count}, config={self.config})"


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="UE5 全局索引构建器")
    parser.add_argument("--config",
                        help="配置文件路径")
    parser.add_argument("--base-path",
                        help="知识库基础路径（用于生成配置文件）")
    parser.add_argument("--core-only", action="store_true",
                        help="仅构建核心模块")
    parser.add_argument("--no-resume", action="store_true",
                        help="不从检查点恢复")

    args = parser.parse_args()

    # 加载配置
    if args.config:
        config = Config(args.config)
    elif args.base_path:
        config = Config(base_path=args.base_path)
    else:
        parser.error("必须指定 --config 或 --base-path 参数")

    # 创建构建器
    builder = GlobalIndexBuilder(config)

    # 构建索引
    if args.core_only:
        global_index = builder.build_core_modules_only()
    else:
        global_index = builder.build_all(resume=not args.no_resume)

    # 输出验证结果
    verification = global_index.verify_coverage()
    print("\n验证结果:")
    print(f"  覆盖率: {verification['coverage_percent']:.2f}%")
    print(f"  验证通过: {verification['verification_passed']}")

    if verification['missing_core_modules']:
        print(f"  缺失核心模块: {verification['missing_core_modules']}")


if __name__ == "__main__":
    main()
