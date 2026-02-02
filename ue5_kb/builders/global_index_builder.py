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

        source_path = os.path.join(self.config.engine_path, "Engine/Source")

        if not os.path.exists(source_path):
            print(f"错误: 引擎源码路径不存在: {source_path}")
            return self.global_index

        # 扫描所有分类
        for category in self.config.module_categories:
            category_path = os.path.join(source_path, category)
            if os.path.exists(category_path):
                print(f"\n扫描分类: {category}")
                self._scan_category(category_path, category)

        # 构建依赖图
        print("\n" + "-" * 60)
        print("构建模块依赖关系图...")
        self.global_index.build_dependency_graph()

        # 保存索引
        print("保存全局索引...")
        self.global_index.save()

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

        source_path = os.path.join(self.config.engine_path, "Engine/Source")

        for module_name in self.config.core_modules:
            # 在所有分类中查找模块
            for category in self.config.module_categories:
                category_path = os.path.join(source_path, category)
                module_path = os.path.join(category_path, module_name)

                if os.path.exists(module_path):
                    build_cs = BuildCsParser.find_module_build_cs(module_path)
                    if build_cs:
                        self._process_module(module_name, build_cs, category)
                        break

        self.global_index.build_dependency_graph()
        self.global_index.save()

        return self.global_index

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
