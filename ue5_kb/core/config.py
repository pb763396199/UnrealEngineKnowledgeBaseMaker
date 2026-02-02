"""
UE5 知识库系统 - 配置管理模块

负责加载和管理系统配置
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """配置管理器"""

    def __init__(self, config_path: Optional[str] = None, base_path: Optional[str] = None):
        """
        初始化配置

        Args:
            config_path: 配置文件路径 (可选)
            base_path: 知识库基础路径，用于生成配置文件
        """
        if config_path is None:
            # 如果没有指定配置文件，尝试从 base_path 生成
            if base_path:
                config_path = str(Path(base_path) / "config.yaml")
            else:
                # 尝试从环境变量获取
                import os
                base_path = os.environ.get('UE5_KB_PATH')
                if base_path:
                    config_path = str(Path(base_path) / "config.yaml")
                else:
                    raise ValueError(
                        "必须指定 config_path 或 base_path 参数，或设置 UE5_KB_PATH 环境变量"
                    )

        self.config_path = Path(config_path)

        # 如果配置文件不存在，创建默认配置
        if not self.config_path.exists():
            self._create_default_config(base_path)

        self._config = self._load_config()

    def _create_default_config(self, base_path: Optional[str], is_plugin: bool = False) -> None:
        """创建默认配置文件

        Args:
            base_path: 基础路径
            is_plugin: 是否为插件模式
        """
        if base_path is None:
            raise ValueError("创建默认配置需要指定 base_path")

        base_path = Path(base_path)
        base_path.mkdir(parents=True, exist_ok=True)

        # 基础配置（引擎和插件共用）
        default_config = {
            'project': {
                'name': 'UE5 Plugin Knowledge Base' if is_plugin else 'UE5 Knowledge Base',
                'version': '2.0.0',
            },
            'storage': {
                'base_path': str(base_path),
                'global_index': 'global_index',
                'module_graphs': 'module_graphs',
                'cache': 'cache',
                'logs': 'logs',
                'checkpoints': 'checkpoints',
            },
            'build': {
                'parallel_workers': 4,
                'batch_size': 100,
                'checkpoint_interval': 10,
                'resume_from_checkpoint': True,
            },
            'verification': {
                'coverage_threshold': 95.0,
            }
        }

        # 引擎模式特有的配置
        if not is_plugin:
            default_config['core_modules'] = [
                'TraceLog', 'Core', 'CoreUObject',
                'RHI', 'RenderCore', 'Renderer',
                'Engine', 'ApplicationCore'
            ]
            default_config['module_categories'] = ['Runtime', 'Editor', 'Developer', 'Programs']

        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 转换路径为绝对路径
        storage = config.get('storage', {})
        base_path = storage.get('base_path', '')

        # 确保所有路径都是绝对路径
        for key, value in storage.items():
            if key != 'base_path' and isinstance(value, str):
                full_path = os.path.join(base_path, value)
                storage[key] = os.path.abspath(full_path)

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项

        Args:
            key: 配置键，支持点分隔的路径 (如 'storage.base_path')
            default: 默认值

        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        """
        设置配置项

        Args:
            key: 配置键
            value: 配置值
        """
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def save(self) -> None:
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

    # 便捷属性访问器
    @property
    def engine_path(self) -> str:
        """引擎源码路径"""
        return self.get('project.engine_path', '')

    @property
    def engine_version(self) -> str:
        """引擎版本"""
        return self.get('project.engine_version', '')

    @property
    def storage_base_path(self) -> str:
        """存储基础路径"""
        return self.get('storage.base_path', '')

    @property
    def global_index_path(self) -> str:
        """全局索引路径"""
        return self.get('storage.global_index', '')

    @property
    def module_graphs_path(self) -> str:
        """模块图谱路径"""
        return self.get('storage.module_graphs', '')

    @property
    def cache_path(self) -> str:
        """缓存路径"""
        return self.get('storage.cache', '')

    @property
    def logs_path(self) -> str:
        """日志路径"""
        return self.get('storage.logs', '')

    @property
    def checkpoints_path(self) -> str:
        """检查点路径"""
        return self.get('storage.checkpoints', '')

    @property
    def core_modules(self) -> list:
        """核心模块列表"""
        return self.get('core_modules', [])

    @property
    def module_categories(self) -> list:
        """模块分类列表"""
        return self.get('module_categories', ['Runtime', 'Editor', 'Developer'])

    @property
    def parallel_workers(self) -> int:
        """并行工作线程数"""
        return self.get('build.parallel_workers', 4)

    @property
    def checkpoint_interval(self) -> int:
        """检查点保存间隔"""
        return self.get('build.checkpoint_interval', 10)

    @property
    def coverage_threshold(self) -> float:
        """覆盖率阈值"""
        return self.get('verification.coverage_threshold', 95.0)

    def __repr__(self) -> str:
        return f"Config(path={self.config_path}, version={self.get('project.version')})"
