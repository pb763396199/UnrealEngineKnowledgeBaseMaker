"""
Pipeline 阶段 1: Discover (发现模块)

扫描引擎目录，发现所有 .Build.cs 文件
"""

from pathlib import Path
from typing import Dict, Any, List
import re
from .base import PipelineStage


class DiscoverStage(PipelineStage):
    """
    发现阶段

    扫描 Engine 目录，查找所有 .Build.cs 文件
    """

    @property
    def stage_name(self) -> str:
        return "discover"

    def get_output_path(self) -> Path:
        return self.stage_dir / "modules.json"

    def run(self, **kwargs) -> Dict[str, Any]:
        """
        发现所有模块

        Returns:
            包含模块列表的结果
        """
        print(f"[Discover] 扫描模块...")

        # 检测模式：检查是否存在 Engine 子目录
        engine_dir = self.base_path / "Engine"
        if engine_dir.exists():
            # 引擎模式
            search_dir = engine_dir
            print(f"[Discover] 检测到引擎模式")
        else:
            # 插件模式：直接在 base_path 下搜索
            search_dir = self.base_path
            print(f"[Discover] 检测到插件模式")

        if not search_dir.exists():
            raise FileNotFoundError(f"目录不存在: {search_dir}")

        # 查找所有 .Build.cs 文件
        modules = self._discover_modules(search_dir)

        result = {
            'modules': modules,
            'total_count': len(modules),
            'categories': self._count_by_category(modules)
        }

        # 保存结果
        self.save_result(result, "modules.json")

        # 格式化输出分类统计
        print(f"[Discover] 完成！发现 {len(modules)} 个模块")
        print(f"  分类统计:")
        for category, count in sorted(result['categories'].items()):
            print(f"    {category}: {count}")

        return result

    def _discover_modules(self, engine_dir: Path) -> List[Dict[str, str]]:
        """
        递归查找所有 .Build.cs 文件

        Args:
            engine_dir: 引擎目录

        Returns:
            模块列表
        """
        modules = []

        for build_cs in engine_dir.rglob('**/*.Build.cs'):
            # 提取模块名
            module_name = build_cs.stem.replace('.Build', '')

            # 推断分类
            category = self._infer_category(build_cs)

            modules.append({
                'name': module_name,
                'path': str(build_cs.relative_to(self.base_path)),
                'category': category,
                'absolute_path': str(build_cs)
            })

        return sorted(modules, key=lambda m: m['name'])

    def _infer_category(self, build_cs_path: Path) -> str:
        """
        从路径推断模块分类

        Args:
            build_cs_path: .Build.cs 文件路径

        Returns:
            分类标签
        """
        path_str = str(build_cs_path)

        if '/Source/Runtime/' in path_str or '\\Source\\Runtime\\' in path_str:
            return 'Runtime'
        elif '/Source/Editor/' in path_str or '\\Source\\Editor\\' in path_str:
            return 'Editor'
        elif '/Source/Developer/' in path_str or '\\Source\\Developer\\' in path_str:
            return 'Developer'
        elif '/Source/Programs/' in path_str or '\\Source\\Programs\\' in path_str:
            return 'Programs'
        elif '/Plugins/' in path_str or '\\Plugins\\' in path_str:
            # 提取插件类型和名称
            return self._extract_plugin_category(path_str)
        elif '/Platforms/' in path_str or '\\Platforms\\' in path_str:
            # 提取平台名称
            return self._extract_platform_category(path_str)
        else:
            return 'Unknown'

    def _extract_plugin_category(self, path_str: str) -> str:
        """提取插件分类（Plugins.Type.Name）"""
        # 匹配 Plugins/{Type}/{Name}
        pattern = r'[/\\]Plugins[/\\]([^/\\]+)[/\\]([^/\\]+)'
        match = re.search(pattern, path_str)
        if match:
            plugin_type = match.group(1)
            plugin_name = match.group(2)
            return f'Plugins.{plugin_type}.{plugin_name}'
        return 'Plugins.Unknown'

    def _extract_platform_category(self, path_str: str) -> str:
        """提取平台分类（Platforms.PlatformName）"""
        pattern = r'[/\\]Platforms[/\\]([^/\\]+)'
        match = re.search(pattern, path_str)
        if match:
            platform = match.group(1)
            return f'Platforms.{platform}'
        return 'Platforms.Unknown'

    def _count_by_category(self, modules: List[Dict[str, str]]) -> Dict[str, int]:
        """按分类统计模块数量"""
        counts = {}
        for module in modules:
            category = module['category']
            counts[category] = counts.get(category, 0) + 1
        return counts
