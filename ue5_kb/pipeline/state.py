"""
Pipeline 状态管理

管理 .pipeline_state 文件
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
from datetime import datetime


class PipelineState:
    """
    Pipeline 状态管理器

    管理 .pipeline_state 文件
    """

    def __init__(self, base_path: Path):
        """
        初始化状态管理器

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        # 将状态文件放在 KnowledgeBase 目录下统一管理
        self.state_file = self.base_path / "KnowledgeBase" / ".pipeline_state"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """加载状态文件"""
        if not self.state_file.exists():
            return self._create_initial_state()

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 加载状态文件失败: {e}，创建新状态")
            return self._create_initial_state()

    def _create_initial_state(self) -> Dict[str, Any]:
        """创建初始状态"""
        return {
            'version': '2.0',
            'created_at': datetime.now().isoformat(),
            'stages': {}
        }

    def _save_state(self) -> None:
        """保存状态文件"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def mark_completed(self, stage_name: str, result: Dict[str, Any]) -> None:
        """
        标记阶段完成

        Args:
            stage_name: 阶段名称
            result: 阶段结果
        """
        self.state['stages'][stage_name] = {
            'completed': True,
            'completed_at': datetime.now().isoformat(),
            'result_summary': self._extract_summary(result)
        }
        self._save_state()

    def mark_failed(self, stage_name: str, error: str) -> None:
        """
        标记阶段失败

        Args:
            stage_name: 阶段名称
            error: 错误信息
        """
        self.state['stages'][stage_name] = {
            'completed': False,
            'failed_at': datetime.now().isoformat(),
            'error': error
        }
        self._save_state()

    def get_stage_state(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """
        获取阶段状态

        Args:
            stage_name: 阶段名称

        Returns:
            阶段状态，如果不存在则返回 None
        """
        return self.state['stages'].get(stage_name)

    def clear_stage(self, stage_name: str) -> None:
        """
        清除阶段状态

        Args:
            stage_name: 阶段名称
        """
        if stage_name in self.state['stages']:
            del self.state['stages'][stage_name]
            self._save_state()

    def is_completed(self, stage_name: str) -> bool:
        """
        检查阶段是否完成

        Args:
            stage_name: 阶段名称

        Returns:
            True 如果阶段已完成
        """
        stage_state = self.get_stage_state(stage_name)
        if not stage_state:
            return False
        return stage_state.get('completed', False)

    def _extract_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """提取结果摘要（避免存储过大的数据）"""
        summary = {}

        # 提取关键指标
        for key in ['total_count', 'success_count', 'failed_count', 'modules_processed',
                    'total_modules', 'analyzed_count', 'total_classes', 'total_functions',
                    'kb_path', 'skill_name', 'skill_path']:
            if key in result:
                summary[key] = result[key]

        return summary

    def get_all_states(self) -> Dict[str, Any]:
        """获取所有阶段的状态"""
        return self.state
