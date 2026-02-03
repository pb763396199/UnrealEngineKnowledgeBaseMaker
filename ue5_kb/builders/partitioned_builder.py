"""
UE5 知识库系统 - 分区构建器

基于 Multi-Agent Context Partitioning 模式的大规模构建支持
"""

from pathlib import Path
from typing import Dict, Any, List
import json
from datetime import datetime


class PartitionConfig:
    """分区配置"""

    # 预定义的分区策略
    PARTITIONS = {
        'runtime': {
            'pattern': 'Engine/Source/Runtime/**',
            'priority': 1,
            'description': 'Runtime 核心模块（约700+个）'
        },
        'editor': {
            'pattern': 'Engine/Source/Editor/**',
            'priority': 2,
            'description': 'Editor 编辑器模块（约600+个）'
        },
        'plugins': {
            'pattern': 'Engine/Plugins/**',
            'priority': 3,
            'description': 'Plugins 插件模块（约900+个）'
        },
        'developer': {
            'pattern': 'Engine/Source/Developer/**',
            'priority': 4,
            'description': 'Developer 开发工具模块'
        },
        'platforms': {
            'pattern': 'Engine/Platforms/**',
            'priority': 5,
            'description': 'Platforms 平台特定模块'
        },
        'programs': {
            'pattern': 'Engine/Source/Programs/**',
            'priority': 6,
            'description': 'Programs 独立程序模块'
        }
    }


class PartitionedBuilder:
    """
    分区构建器

    将大型引擎扫描任务分配给多个独立的 partition
    每个 partition 在隔离的 context 中处理
    """

    def __init__(self, engine_path: Path):
        """
        初始化分区构建器

        Args:
            engine_path: 引擎根目录
        """
        self.engine_path = Path(engine_path)
        self.partitions_dir = self.engine_path / "data" / "partitions"
        self.partitions_dir.mkdir(parents=True, exist_ok=True)

    def build_partitioned(
        self,
        partitions: List[str] = None,
        parallel: bool = False
    ) -> Dict[str, Any]:
        """
        使用分区模式构建

        Args:
            partitions: 要处理的分区列表（None = 全部）
            parallel: 是否并行处理（暂未实现）

        Returns:
            构建结果
        """
        if partitions is None:
            partitions = list(PartitionConfig.PARTITIONS.keys())

        print(f"[PartitionedBuilder] 分区构建模式")
        print(f"  分区数: {len(partitions)}")

        results = {}

        for partition_name in partitions:
            if partition_name not in PartitionConfig.PARTITIONS:
                print(f"  警告: 未知的分区 '{partition_name}'，跳过")
                continue

            print(f"\n[Partition: {partition_name}] 开始处理...")

            try:
                result = self._process_partition(partition_name)
                results[partition_name] = result

                print(f"[Partition: {partition_name}] 完成！")
                print(f"  模块数: {result.get('module_count', 0)}")

            except Exception as e:
                print(f"[Partition: {partition_name}] 失败: {e}")
                results[partition_name] = {'error': str(e)}

        # 合并所有 partition 的结果
        merged = self._merge_results(results)

        return {
            'partitions': results,
            'merged': merged,
            'total_partitions': len(partitions),
            'successful_partitions': len([r for r in results.values() if 'error' not in r])
        }

    def _process_partition(self, partition_name: str) -> Dict[str, Any]:
        """
        处理单个分区

        这个函数可以被 Task tool 调用，创建独立的 sub-agent

        Args:
            partition_name: 分区名称

        Returns:
            分区处理结果
        """
        config = PartitionConfig.PARTITIONS[partition_name]

        # 1. 发现该分区的模块
        modules = self._discover_partition_modules(partition_name, config['pattern'])

        if not modules:
            return {
                'partition': partition_name,
                'module_count': 0,
                'modules': [],
                'note': '该分区没有模块'
            }

        # 2. 提取依赖
        dependencies = self._extract_partition_dependencies(modules)

        # 3. 保存分区结果
        result = {
            'partition': partition_name,
            'pattern': config['pattern'],
            'description': config['description'],
            'module_count': len(modules),
            'modules': modules,
            'dependencies': dependencies,
            'processed_at': datetime.now().isoformat()
        }

        # 保存到文件
        self._save_partition_result(partition_name, result)

        return result

    def _discover_partition_modules(self, partition_name: str, pattern: str) -> List[Dict[str, str]]:
        """
        发现分区内的模块

        Args:
            partition_name: 分区名称
            pattern: 文件模式

        Returns:
            模块列表
        """
        from ..pipeline.discover import DiscoverStage

        # 使用 discover 阶段的逻辑
        discover = DiscoverStage(self.engine_path)

        # 扫描所有模块
        all_modules_result = discover.load_result('modules.json')
        if not all_modules_result:
            # 如果 discover 阶段未运行，先运行它
            all_modules_result = discover.run()

        all_modules = all_modules_result.get('modules', [])

        # 过滤出属于该分区的模块
        partition_modules = []

        # 根据 category 过滤
        category_map = {
            'runtime': 'Runtime',
            'editor': 'Editor',
            'developer': 'Developer',
            'programs': 'Programs',
            'plugins': 'Plugins',  # 以 Plugins. 开头
            'platforms': 'Platforms'  # 以 Platforms. 开头
        }

        target_category = category_map.get(partition_name)

        for module in all_modules:
            category = module.get('category', '')

            if partition_name in ['plugins', 'platforms']:
                # 这两个是前缀匹配
                if category.startswith(target_category + '.'):
                    partition_modules.append(module)
            else:
                # 其他是精确匹配
                if category == target_category:
                    partition_modules.append(module)

        return partition_modules

    def _extract_partition_dependencies(self, modules: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        提取分区模块的依赖关系

        Args:
            modules: 模块列表

        Returns:
            依赖关系字典
        """
        from ..parsers.buildcs_parser import BuildCsParser

        parser = BuildCsParser()
        dependencies = {}

        for module in modules:
            try:
                # 解析 .Build.cs 文件
                deps = parser.parse_file(module['absolute_path'])
                dependencies[module['name']] = deps
            except Exception as e:
                print(f"    警告: 解析 {module['name']} 失败: {e}")
                dependencies[module['name']] = {}

        return dependencies

    def _save_partition_result(self, partition_name: str, result: Dict[str, Any]) -> None:
        """
        保存分区结果

        Args:
            partition_name: 分区名称
            result: 结果数据
        """
        output_file = self.partitions_dir / f"{partition_name}.json"

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"    保存结果: {output_file}")

    def _merge_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并所有 partition 的结果

        Args:
            results: 各分区的结果

        Returns:
            合并后的统计数据
        """
        total_modules = 0
        all_categories = set()

        for partition_name, result in results.items():
            if 'error' in result:
                continue

            total_modules += result.get('module_count', 0)

            for module in result.get('modules', []):
                all_categories.add(module.get('category'))

        return {
            'total_modules': total_modules,
            'total_categories': len(all_categories),
            'categories': sorted(list(all_categories)),
            'merged_at': datetime.now().isoformat()
        }

    def get_partition_status(self) -> Dict[str, Any]:
        """
        获取分区状态

        Returns:
            各分区的完成状态
        """
        status = {}

        for partition_name in PartitionConfig.PARTITIONS.keys():
            result_file = self.partitions_dir / f"{partition_name}.json"
            status[partition_name] = {
                'completed': result_file.exists(),
                'result_file': str(result_file) if result_file.exists() else None
            }

        return status

    def clean_partition(self, partition_name: str) -> None:
        """
        清除特定分区的结果

        Args:
            partition_name: 分区名称
        """
        result_file = self.partitions_dir / f"{partition_name}.json"
        if result_file.exists():
            result_file.unlink()
            print(f"已清除分区: {partition_name}")
        else:
            print(f"分区 {partition_name} 没有结果文件")
