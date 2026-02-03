"""
UE5 知识库系统 - Pipeline 模块

五阶段 Pipeline 架构：
1. discover - 发现所有模块
2. extract - 提取模块依赖
3. analyze - 分析代码结构
4. build - 构建索引
5. generate - 生成 Skill
"""

from .base import PipelineStage
from .coordinator import PipelineCoordinator
from .state import PipelineState

__all__ = [
    'PipelineStage',
    'PipelineCoordinator',
    'PipelineState',
]
