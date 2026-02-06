"""
UE5 知识库系统 - 全局索引模块

负责构建和管理所有 UE5 模块的全局索引
"""

import os
import json
import pickle
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict

import networkx as nx

from .config import Config


class GlobalIndex:
    """
    全局模块索引

    存储所有 UE5 模块的元数据信息，包括:
    - 模块名称和路径
    - 依赖关系
    - 文件统计
    - 分类信息
    """

    def __init__(self, config: Config):
        """
        初始化全局索引

        Args:
            config: 配置对象
        """
        self.config = config
        self.index: Dict[str, Dict[str, Any]] = {}
        self.dependency_graph: Optional[nx.DiGraph] = None
        self._load()

    def _load(self) -> None:
        """加载已存在的索引"""
        index_file = os.path.join(self.config.global_index_path, "global_index.pkl")

        if os.path.exists(index_file):
            with open(index_file, 'rb') as f:
                data = pickle.load(f)
                self.index = data.get('index', {})
                self.dependency_graph = data.get('dependency_graph')

    def save(self) -> None:
        """保存索引到磁盘"""
        os.makedirs(self.config.global_index_path, exist_ok=True)

        index_file = os.path.join(self.config.global_index_path, "global_index.pkl")
        with open(index_file, 'wb') as f:
            pickle.dump({
                'index': self.index,
                'dependency_graph': self.dependency_graph,
                'last_updated': datetime.now().isoformat()
            }, f)

        # 同时保存 JSON 格式便于查看
        json_file = os.path.join(self.config.global_index_path, "global_index.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                'index': self.index,
                'last_updated': datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)

    def add_module(self, module_name: str, module_info: Dict[str, Any]) -> None:
        """
        添加模块信息到索引

        Args:
            module_name: 模块名称
            module_info: 模块信息字典
        """
        self.index[module_name] = {
            **module_info,
            'indexed_at': datetime.now().isoformat()
        }

    def get_module(self, module_name: str) -> Optional[Dict[str, Any]]:
        """
        获取模块信息

        Args:
            module_name: 模块名称

        Returns:
            模块信息字典，如果不存在返回 None
        """
        return self.index.get(module_name)

    def get_all_modules(self) -> Dict[str, Dict[str, Any]]:
        """获取所有模块信息"""
        return self.index

    def get_modules_by_category(self, category: str) -> List[str]:
        """
        获取指定分类的所有模块

        Args:
            category: 模块分类 (Runtime, Editor, Developer 等)

        Returns:
            模块名称列表
        """
        return [
            name for name, info in self.index.items()
            if info.get('category') == category
        ]

    def get_dependencies(self, module_name: str) -> List[str]:
        """
        获取模块的依赖列表

        Args:
            module_name: 模块名称

        Returns:
            依赖模块名称列表
        """
        module_info = self.get_module(module_name)
        if module_info:
            return module_info.get('dependencies', [])
        return []

    def get_dependents(self, module_name: str) -> List[str]:
        """
        获取依赖指定模块的所有模块

        Args:
            module_name: 模块名称

        Returns:
            依赖该模块的模块名称列表
        """
        return [
            name for name, info in self.index.items()
            if module_name in info.get('dependencies', [])
        ]

    def build_dependency_graph(self) -> nx.DiGraph:
        """
        构建模块依赖关系图

        Returns:
            NetworkX 有向图
        """
        if self.dependency_graph is not None:
            return self.dependency_graph

        graph = nx.DiGraph()

        # 添加所有模块节点
        for module_name, info in self.index.items():
            graph.add_node(module_name, **info)

        # 添加依赖关系边
        for module_name, info in self.index.items():
            for dep in info.get('dependencies', []):
                if dep in self.index:
                    graph.add_edge(module_name, dep)

        self.dependency_graph = graph
        return graph

    def analyze_layers(self) -> Dict[str, Any]:
        """
        分析模块分层结构

        Returns:
            分层分析结果
        """
        graph = self.build_dependency_graph()

        # 计算入度和出度
        degrees = {
            node: (graph.in_degree(node), graph.out_degree(node))
            for node in graph.nodes()
        }

        # 识别底层模块 (入度为 0)
        bottom_layer = [n for n, d in degrees.items() if d[0] == 0]

        # 识别顶层模块 (出度为 0)
        top_layer = [n for n, d in degrees.items() if d[1] == 0]

        # 识别中间层模块
        middle_layer = [
            n for n in graph.nodes()
            if n not in bottom_layer and n not in top_layer
        ]

        return {
            'bottom_layer': sorted(bottom_layer),
            'top_layer': sorted(top_layer),
            'middle_layer': sorted(middle_layer),
            'total_modules': len(graph.nodes()),
            'total_dependencies': len(graph.edges())
        }

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取索引统计信息

        Returns:
            统计信息字典
        """
        categories = defaultdict(int)
        total_files = 0
        total_lines = 0

        for info in self.index.values():
            categories[info.get('category', 'Unknown')] += 1
            total_files += info.get('file_count', 0)
            total_lines += info.get('estimated_lines', 0)

        return {
            'total_modules': len(self.index),
            'categories': dict(categories),
            'total_files': total_files,
            'total_estimated_lines': total_lines,
            'last_updated': max(
                (info.get('indexed_at', '') for info in self.index.values()),
                default=''
            )
        }

    def verify_coverage(self, expected_count: int = 609) -> Dict[str, Any]:
        """
        验证索引覆盖率

        Args:
            expected_count: 预期的模块数量

        Returns:
            验证结果
        """
        total = len(self.index)
        coverage = (total / expected_count * 100) if expected_count > 0 else 0

        # 检查核心模块
        core_modules = self.config.core_modules
        missing_core = [m for m in core_modules if m not in self.index]

        # 检查孤儿模块
        orphans = [
            name for name, info in self.index.items()
            if not info.get('dependencies') and info.get('file_count', 0) == 0
        ]

        return {
            'total_modules': total,
            'expected_modules': expected_count,
            'coverage_percent': round(coverage, 2),
            'verification_passed': coverage >= self.config.coverage_threshold,
            'missing_core_modules': missing_core,
            'orphan_modules': orphans,
            'modules_with_dependencies': sum(
                1 for info in self.index.values() if info.get('dependencies')
            ),
            'modules_with_files': sum(
                1 for info in self.index.values() if info.get('file_count', 0) > 0
            )
        }

    def __len__(self) -> int:
        """返回索引中的模块数量"""
        return len(self.index)

    def __contains__(self, module_name: str) -> bool:
        """检查模块是否在索引中"""
        return module_name in self.index

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        """
        保存知识库元数据到 SQLite metadata 表

        Args:
            metadata: 元数据字典，包含 kb_version, engine_version 等
        """
        import sqlite3

        db_path = os.path.join(self.config.global_index_path, "index.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create metadata table if not exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Insert metadata
        for key, value in metadata.items():
            cursor.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, str(value)))

        conn.commit()
        conn.close()

    def load_metadata(self) -> Dict[str, Any]:
        """
        从 SQLite metadata 表加载知识库元数据

        Returns:
            元数据字典
        """
        import sqlite3

        db_path = os.path.join(self.config.global_index_path, "index.db")
        if not os.path.exists(db_path):
            return {}

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT key, value FROM metadata')
        metadata = dict(cursor.fetchall())

        conn.close()
        return metadata

    def __repr__(self) -> str:
        return f"GlobalIndex(modules={len(self.index)}, version={self.config.get('project.version')})"
