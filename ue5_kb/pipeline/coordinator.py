"""
Pipeline 协调器

管理 Pipeline 的执行流程
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import json
import re
from .discover import DiscoverStage
from .extract import ExtractStage
from .analyze import AnalyzeStage
from .build import BuildStage
from .generate import GenerateStage
from .state import PipelineState
from ..utils.stage_timer import StageTimer
from rich.console import Console


class PipelineCoordinator:
    """
    Pipeline 协调器

    管理 Pipeline 各阶段的执行
    """

    STAGES = ['discover', 'extract', 'analyze', 'build', 'generate']

    def __init__(self, base_path: Path, is_plugin: bool = False, plugin_name: str = None):
        """
        初始化协调器

        Args:
            base_path: 引擎/插件根目录
            is_plugin: 是否为插件模式
            plugin_name: 插件名称（插件模式下使用）
        """
        self.base_path = Path(base_path)
        self.state = PipelineState(base_path)
        self.is_plugin = is_plugin
        self.plugin_name = plugin_name
        self.console = Console()

        # v2.13.0: 检测引擎/插件版本
        self.engine_version = self._detect_version()
        self.tool_version = self._get_tool_version()

        # v2.13.0: 加载现有 manifest（用于增量更新）
        from ..core.manifest import KBManifest
        self.manifest = KBManifest.load(self.base_path / "KnowledgeBase")

        # 初始化阶段计时器
        self.timer = StageTimer()

        # 初始化各阶段
        self.stages = {
            'discover': DiscoverStage(base_path),
            'extract': ExtractStage(base_path),
            'analyze': AnalyzeStage(base_path),
            'build': BuildStage(base_path),
            'generate': GenerateStage(base_path, is_plugin=is_plugin, plugin_name=plugin_name)
        }

    def run_all(self, force: bool = False, parallel: int = 0, **kwargs) -> Dict[str, Any]:
        """
        运行完整 Pipeline

        Args:
            force: 是否强制重新运行已完成的阶段
            parallel: 并行度（0=自动检测）
            **kwargs: 传递给各阶段的参数

        Returns:
            包含所有阶段结果的字典
        """
        # 自动检测并行度
        if parallel == 0:
            parallel = os.cpu_count() or 4

        # 启动 Pipeline 计时
        self.timer.start_pipeline()

        results = {}

        for stage_name in self.STAGES:
            try:
                # 获取该阶段的总任务数
                total_items = self._get_stage_total_items(stage_name)

                # 启动阶段计时
                self.timer.start_stage(stage_name, total_items)

                result = self.run_stage(stage_name, force=force, parallel=parallel, **kwargs)
                results[stage_name] = result

                # 记录完成数量和错误
                processed = self._get_processed_count(result)
                errors = self._get_error_count(result)

                # 结束阶段计时
                self.timer.end_stage(stage_name, processed, errors)

                # 显示阶段耗时
                if not result.get('skipped'):
                    elapsed = self.timer.get_stage_metrics(stage_name).elapsed
                    self.console.print(f"[cyan]✓ {stage_name} 完成 ({elapsed:.2f}s)[/cyan]")

            except Exception as e:
                self.console.print(f"\n[red][Pipeline] 错误: 阶段 '{stage_name}' 失败[/red]")
                self.console.print(f"  {e}")
                results[stage_name] = {'error': str(e)}
                # 阶段失败时停止后续阶段
                break

        # 结束 Pipeline 计时
        self.timer.end_pipeline()

        # 显示性能摘要
        self._display_performance_summary()

        return results

    def run_stage(self, stage_name: str, force: bool = False, **kwargs) -> Dict[str, Any]:
        """
        运行特定阶段

        Args:
            stage_name: 阶段名称
            force: 是否强制重新运行
            **kwargs: 传递给阶段的参数

        Returns:
            阶段结果
        """
        if stage_name not in self.stages:
            raise ValueError(f"未知的阶段: {stage_name}. 可用阶段: {', '.join(self.STAGES)}")

        stage = self.stages[stage_name]

        # 检查是否已完成
        if stage.is_completed() and not force:
            print(f"[Pipeline] 阶段 '{stage_name}' 已完成，跳过")
            print(f"  (使用 --force 强制重新运行)")
            return {'skipped': True, 'reason': 'already completed'}

        # 运行阶段
        print(f"\n[Pipeline] ========== 运行阶段: {stage_name} ==========")

        try:
            result = stage.run(**kwargs)

            # 更新状态
            self.state.mark_completed(stage_name, result)

            return result

        except Exception as e:
            print(f"[Pipeline] 阶段 '{stage_name}' 失败: {e}")
            self.state.mark_failed(stage_name, str(e))
            raise

    def get_status(self) -> Dict[str, Any]:
        """
        获取 Pipeline 状态

        Returns:
            包含各阶段状态的字典
        """
        status = {
            'base_path': str(self.base_path),
            'stages': {}
        }

        for stage_name in self.STAGES:
            stage = self.stages[stage_name]
            stage_state = self.state.get_stage_state(stage_name)

            status['stages'][stage_name] = {
                'completed': stage.is_completed(),
                'state': stage_state or {}
            }

        return status

    def clean_stage(self, stage_name: str) -> None:
        """
        清除特定阶段的输出

        Args:
            stage_name: 阶段名称
        """
        if stage_name not in self.stages:
            raise ValueError(f"未知的阶段: {stage_name}")

        stage = self.stages[stage_name]
        stage.clean()

        # 清除状态
        self.state.clear_stage(stage_name)

        print(f"[Pipeline] 已清除阶段: {stage_name}")

    def clean_all(self) -> None:
        """清除所有阶段的输出"""
        for stage_name in self.STAGES:
            try:
                self.clean_stage(stage_name)
            except Exception as e:
                print(f"  警告: 清除阶段 {stage_name} 失败: {e}")

    def validate_dependencies(self, stage_name: str) -> bool:
        """
        验证阶段的依赖是否满足

        Args:
            stage_name: 阶段名称

        Returns:
            True 如果所有依赖都满足
        """
        dependencies = {
            'discover': [],
            'extract': ['discover'],
            'analyze': ['discover', 'extract'],
            'build': ['discover', 'extract', 'analyze'],
            'generate': ['build']
        }

        required_stages = dependencies.get(stage_name, [])

        for required in required_stages:
            if not self.stages[required].is_completed():
                print(f"[Pipeline] 警告: 阶段 '{stage_name}' 依赖 '{required}'，但后者未完成")
                return False

        return True

    def _get_stage_total_items(self, stage_name: str) -> int:
        """获取阶段总任务数"""
        if stage_name == 'discover':
            # 预估模块数
            return 1757
        elif stage_name in ['extract', 'analyze']:
            discover_result = self.stages['discover'].load_result('modules.json')
            if discover_result:
                return len(discover_result.get('modules', []))
        elif stage_name == 'build':
            analyze_result = self.stages['analyze'].load_result('summary.json')
            if analyze_result:
                return analyze_result.get('analyzed_count', 0)
        return 0

    def _get_processed_count(self, result: Dict) -> int:
        """从结果中提取处理数量"""
        for key in ['analyzed_count', 'success_count', 'total_count', 'modules_processed', 'module_graphs_created']:
            if key in result:
                return result[key]
        return 0

    def _get_error_count(self, result: Dict) -> int:
        """从结果中提取错误数量"""
        return result.get('failed_count', 0)

    def _display_performance_summary(self) -> None:
        """显示性能摘要"""
        self.console.print(f"\n{self.timer.format_summary()}")

    # ========================================================================
    # v2.13.0: 版本检测方法
    # ========================================================================

    def _detect_version(self) -> str:
        """检测引擎或插件版本"""
        if self.is_plugin:
            return self._detect_plugin_version()
        return self._detect_engine_version()

    def _detect_engine_version(self) -> str:
        """从 Engine/Build/Build.version 读取版本"""
        build_version = self.base_path / "Engine" / "Build" / "Build.version"
        if build_version.exists():
            try:
                with open(build_version, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    major = data.get('MajorVersion', 5)
                    minor = data.get('MinorVersion', 0)
                    patch = data.get('PatchVersion', 0)
                    return f"{major}.{minor}.{patch}"
            except Exception:
                pass

        # 从目录名提取
        dir_name = self.base_path.name
        match = re.search(r'(\d+)[._](\d+)(?:[._](\d+))?', dir_name)
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3) or '0'
            return f"{major}.{minor}.{patch}"

        return "unknown"

    def _detect_plugin_version(self) -> str:
        """从 .uplugin 文件读取版本"""
        uplugin_files = list(self.base_path.glob("*.uplugin"))
        if uplugin_files:
            try:
                with open(uplugin_files[0], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 优先使用 VersionName
                    version = data.get('VersionName', '')
                    if version:
                        return version
                    # 其次使用 Version
                    version = data.get('Version', '')
                    if version:
                        return str(version)
            except Exception:
                pass

        # 从目录名推测
        dir_name = self.base_path.name
        match = re.search(r'[-_](\d+)[._](\d+)(?:[._](\d+))?', dir_name)
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3) or '0'
            return f"{major}.{minor}.{patch}"

        return "1.0"

    def _get_tool_version(self) -> str:
        """获取工具版本"""
        try:
            from importlib.metadata import version
            return version("ue5-kb")
        except Exception:
            return "2.14.0"
