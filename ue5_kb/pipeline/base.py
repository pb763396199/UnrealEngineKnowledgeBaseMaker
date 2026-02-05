"""
Pipeline 基类

所有 Pipeline 阶段的基类
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
import json
from datetime import datetime


class PipelineStage(ABC):
    """
    Pipeline 阶段基类

    每个阶段必须实现：
    - stage_name: 阶段名称
    - run(): 执行逻辑
    - is_completed(): 检查是否完成
    """

    def __init__(self, base_path: Path):
        """
        初始化阶段

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        # 将工作数据放在 KnowledgeBase 目录下统一管理
        self.data_dir = self.base_path / "KnowledgeBase" / "data"
        self.stage_dir = self.data_dir / self.stage_name

    @property
    @abstractmethod
    def stage_name(self) -> str:
        """阶段名称（discover, extract, analyze, build, generate）"""
        pass

    @abstractmethod
    def run(self, **kwargs) -> Dict[str, Any]:
        """
        执行阶段

        Returns:
            执行结果（包含统计信息）
        """
        pass

    def is_completed(self) -> bool:
        """
        检查阶段是否已完成

        Returns:
            True 如果输出文件存在
        """
        return self.get_output_path().exists()

    @abstractmethod
    def get_output_path(self) -> Path:
        """
        获取输出文件路径

        Returns:
            输出文件的路径
        """
        pass

    def clean(self) -> None:
        """清除阶段输出（用于重新运行）"""
        import shutil
        if self.stage_dir.exists():
            shutil.rmtree(self.stage_dir)

    def save_result(self, result: Dict[str, Any], filename: str = "result.json") -> None:
        """
        保存结果到文件

        Args:
            result: 结果字典
            filename: 文件名
        """
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.stage_dir / filename

        # 添加元数据
        result['_metadata'] = {
            'stage': self.stage_name,
            'completed_at': datetime.now().isoformat(),
            'base_path': str(self.base_path)
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    def load_result(self, filename: str = "result.json") -> Optional[Dict[str, Any]]:
        """
        加载之前的结果

        Args:
            filename: 文件名

        Returns:
            结果字典，如果不存在则返回 None
        """
        result_path = self.stage_dir / filename
        if not result_path.exists():
            return None

        with open(result_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_previous_stage_result(self, stage_name: str, filename: str = "result.json") -> Optional[Dict[str, Any]]:
        """
        加载前一个阶段的结果

        Args:
            stage_name: 阶段名称
            filename: 文件名

        Returns:
            结果字典，如果不存在则返回 None
        """
        stage_dir = self.data_dir / stage_name
        result_path = stage_dir / filename

        if not result_path.exists():
            return None

        with open(result_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} stage='{self.stage_name}' completed={self.is_completed()}>"
