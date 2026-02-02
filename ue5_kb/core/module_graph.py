"""
UE5 知识库系统 - 模块图谱模块

负责构建和管理单个模块的代码知识图谱
"""

import os
import pickle
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple

import networkx as nx

from .config import Config


class ModuleGraph:
    """
    模块知识图谱

    存储单个模块的详细代码结构信息，包括:
    - 类和继承关系
    - 函数和调用关系
    - 文件包含关系
    - 命名空间结构
    """

    # 节点类型常量
    NODE_TYPE_FILE = "File"
    NODE_TYPE_CLASS = "Class"
    NODE_TYPE_STRUCT = "Struct"
    NODE_TYPE_FUNCTION = "Function"
    NODE_TYPE_PROPERTY = "Property"
    NODE_TYPE_ENUM = "Enum"
    NODE_TYPE_INTERFACE = "Interface"
    NODE_TYPE_NAMESPACE = "Namespace"
    NODE_TYPE_MACRO = "Macro"
    NODE_TYPE_DOCUMENTATION = "Documentation"

    # 关系类型常量
    REL_TYPE_CONTAINS = "CONTAINS"
    REL_TYPE_INHERITS = "INHERITS"
    REL_TYPE_IMPLEMENTS = "IMPLEMENTS"
    REL_TYPE_HAS_METHOD = "HAS_METHOD"
    REL_TYPE_HAS_PROPERTY = "HAS_PROPERTY"
    REL_TYPE_CALLS = "CALLS"
    REL_TYPE_INCLUDES = "INCLUDES"
    REL_TYPE_DEFINED_IN = "DEFINED_IN"
    REL_TYPE_DOCUMENTS = "DOCUMENTS"

    def __init__(self, config: Config, module_name: str):
        """
        初始化模块图谱

        Args:
            config: 配置对象
            module_name: 模块名称
        """
        self.config = config
        self.module_name = module_name
        self.graph: nx.DiGraph = nx.DiGraph()
        self._load()

    def _get_graph_path(self) -> str:
        """获取图谱文件路径"""
        return os.path.join(
            self.config.module_graphs_path,
            f"{self.module_name}.pkl"
        )

    def _load(self) -> None:
        """加载已存在的图谱"""
        graph_path = self._get_graph_path()

        if os.path.exists(graph_path):
            with open(graph_path, 'rb') as f:
                data = pickle.load(f)
                self.graph = data.get('graph', nx.DiGraph())

    def save(self) -> None:
        """保存图谱到磁盘"""
        os.makedirs(self.config.module_graphs_path, exist_ok=True)

        graph_path = self._get_graph_path()
        with open(graph_path, 'wb') as f:
            pickle.dump({
                'graph': self.graph,
                'module': self.module_name,
                'last_updated': datetime.now().isoformat()
            }, f)

        # 同时保存 JSON 格式（仅保存图结构，不含边属性）
        json_path = graph_path.replace('.pkl', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            # 转换为可序列化的格式
            data = {
                'module': self.module_name,
                'nodes': [],
                'edges': [],
                'statistics': self.get_statistics()
            }

            for node, node_data in self.graph.nodes(data=True):
                data['nodes'].append({
                    'id': node,
                    'type': node_data.get('type', 'unknown'),
                    'name': node_data.get('name', node)
                })

            for source, target, edge_data in self.graph.edges(data=True):
                data['edges'].append({
                    'source': source,
                    'target': target,
                    'type': edge_data.get('type', 'unknown')
                })

            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_node(self, node_id: str, node_type: str, **attributes) -> None:
        """
        添加节点到图谱

        Args:
            node_id: 节点唯一标识
            node_type: 节点类型
            **attributes: 其他节点属性
        """
        self.graph.add_node(node_id, type=node_type, **attributes)

    def add_edge(self, source: str, target: str, relation_type: str, **attributes) -> None:
        """
        添加关系到图谱

        Args:
            source: 源节点 ID
            target: 目标节点 ID
            relation_type: 关系类型
            **attributes: 其他关系属性
        """
        self.graph.add_edge(source, target, type=relation_type, **attributes)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        获取节点信息

        Args:
            node_id: 节点 ID

        Returns:
            节点属性字典，如果不存在返回 None
        """
        if node_id in self.graph:
            return self.graph.nodes[node_id]
        return None

    def get_nodes_by_type(self, node_type: str) -> List[str]:
        """
        获取指定类型的所有节点

        Args:
            node_type: 节点类型

        Returns:
            节点 ID 列表
        """
        return [
            node for node, data in self.graph.nodes(data=True)
            if data.get('type') == node_type
        ]

    def get_related_nodes(self, node_id: str, relation_type: Optional[str] = None,
                         direction: str = 'out') -> List[str]:
        """
        获取与节点相关的其他节点

        Args:
            node_id: 节点 ID
            relation_type: 关系类型过滤，None 表示所有关系
            direction: 方向 ('out' 出边, 'in' 入边, 'both' 双向)

        Returns:
            相关节点 ID 列表
        """
        if direction == 'out':
            edges = self.graph.out_edges(node_id, data=True)
        elif direction == 'in':
            edges = self.graph.in_edges(node_id, data=True)
        else:
            edges = self.graph.edges(node_id, data=True)

        if relation_type:
            return [
                target if direction == 'out' else source
                for source, target, data in edges
                if data.get('type') == relation_type
            ]
        else:
            return [
                target if direction == 'out' else source
                for source, target, _ in edges
            ]

    def get_class_hierarchy(self, class_name: str) -> List[str]:
        """
        获取类的继承层次结构

        Args:
            class_name: 类名

        Returns:
            继承链列表 [父类, ..., 当前类]
        """
        hierarchy = [class_name]
        current = class_name

        while True:
            parents = self.get_related_nodes(current, self.REL_TYPE_INHERITS, direction='in')
            if not parents:
                break
            current = parents[0]
            hierarchy.append(current)

        return list(reversed(hierarchy))

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取图谱统计信息

        Returns:
            统计信息字典
        """
        # 统计节点类型
        node_types = {}
        for _, data in self.graph.nodes(data=True):
            node_type = data.get('type', 'unknown')
            node_types[node_type] = node_types.get(node_type, 0) + 1

        # 统计关系类型
        rel_types = {}
        for _, _, data in self.graph.edges(data=True):
            rel_type = data.get('type', 'unknown')
            rel_types[rel_type] = rel_types.get(rel_type, 0) + 1

        # 检查孤立节点
        isolated = list(nx.isolates(self.graph))

        # 计算连通分量
        undirected = self.graph.to_undirected()
        components = nx.number_connected_components(undirected)

        return {
            'module': self.module_name,
            'total_nodes': self.graph.number_of_nodes(),
            'total_edges': self.graph.number_of_edges(),
            'node_types': node_types,
            'relationship_types': rel_types,
            'isolated_nodes': isolated,
            'connected_components': components
        }

    def verify(self) -> Dict[str, Any]:
        """
        验证图谱完整性

        Returns:
            验证结果
        """
        stats = self.get_statistics()

        # 检查是否有孤立节点
        has_isolated = len(stats['isolated_nodes']) > 0

        # 检查边的目标节点是否存在
        dangling_edges = []
        for source, target in self.graph.edges():
            if target not in self.graph:
                dangling_edges.append((source, target))

        return {
            'module': self.module_name,
            'is_valid': not has_isolated and not dangling_edges,
            'has_isolated_nodes': has_isolated,
            'dangling_edges': dangling_edges,
            'statistics': stats
        }

    def __len__(self) -> int:
        """返回图谱中的节点数量"""
        return self.graph.number_of_nodes()

    def __contains__(self, node_id: str) -> bool:
        """检查节点是否在图谱中"""
        return node_id in self.graph

    def __repr__(self) -> str:
        return f"ModuleGraph(module={self.module_name}, nodes={self.graph.number_of_nodes()}, edges={self.graph.number_of_edges()})"
