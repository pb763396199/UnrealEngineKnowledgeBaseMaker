"""
Pipeline 协调器

管理 Pipeline 的执行流程
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .discover import DiscoverStage
from .extract import ExtractStage
from .analyze import AnalyzeStage
from .build import BuildStage
from .generate import GenerateStage
from .state import PipelineState


class PipelineCoordinator:
    """
    Pipeline 协调器

    管理 Pipeline 各阶段的执行
    """

    STAGES = ['discover', 'extract', 'analyze', 'build', 'generate']

    def __init__(self, base_path: Path):
        """
        初始化协调器

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        self.state = PipelineState(base_path)

        # 初始化各阶段
        self.stages = {
            'discover': DiscoverStage(base_path),
            'extract': ExtractStage(base_path),
            'analyze': AnalyzeStage(base_path),
            'build': BuildStage(base_path),
            'generate': GenerateStage(base_path)
        }

    def run_all(self, force: bool = False, **kwargs) -> Dict[str, Any]:
        """
        运行完整 Pipeline

        Args:
            force: 是否强制重新运行已完成的阶段
            **kwargs: 传递给各阶段的参数

        Returns:
            包含所有阶段结果的字典
        """
        results = {}

        for stage_name in self.STAGES:
            try:
                result = self.run_stage(stage_name, force=force, **kwargs)
                results[stage_name] = result
            except Exception as e:
                print(f"\n[Pipeline] 错误: 阶段 '{stage_name}' 失败")
                print(f"  {e}")
                results[stage_name] = {'error': str(e)}
                # 阶段失败时停止后续阶段
                break

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
