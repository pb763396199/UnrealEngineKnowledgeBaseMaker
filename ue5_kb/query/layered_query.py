"""
UE5 知识库系统 - 分层查询接口

基于 Context Optimization 理论设计的分层查询接口
目标：减少单次查询的 Token 使用，避免 context 过载
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import json
import hashlib


class LayeredQueryInterface:
    """
    分层查询接口

    设计原则（来自 Context Optimization）:
    1. 优先返回摘要，避免一次性返回大量数据
    2. 使用引用 ID 机制，按需获取详情
    3. 分层提供信息：摘要 → 详情 → 源码
    4. Token 预算控制
    """

    # Token 预算（每层的最大 token 数）
    TOKEN_BUDGETS = {
        'summary': 200,      # 摘要层：最多200 tokens
        'details': 1000,     # 详情层：最多1000 tokens
        'source': 5000       # 源码层：最多5000 tokens
    }

    def __init__(self, kb_path: str):
        """
        初始化分层查询接口

        Args:
            kb_path: 知识库路径
        """
        self.kb_path = Path(kb_path)
        self.result_cache = {}  # ref_id -> 完整结果的缓存

    def query_class(self, class_name: str, detail_level: str = 'summary') -> Dict[str, Any]:
        """
        查询类信息（分层）

        Args:
            class_name: 类名
            detail_level: 详情级别 - 'summary' | 'details' | 'source'

        Returns:
            分层的查询结果
        """
        if detail_level == 'summary':
            return self._query_class_summary(class_name)
        elif detail_level == 'details':
            return self._query_class_details(class_name)
        elif detail_level == 'source':
            return self._query_class_source(class_name)
        else:
            raise ValueError(f"Invalid detail_level: {detail_level}")

    def _query_class_summary(self, class_name: str) -> Dict[str, Any]:
        """
        摘要层查询（最小化 Token 使用）

        示例输出：~100-200 tokens
        """
        # 从知识库获取基础信息（这里简化，实际会调用现有的查询函数）
        class_info = self._load_class_info(class_name)

        if not class_info:
            return {"error": f"未找到类: {class_name}"}

        # 生成引用 ID
        ref_id = self._generate_ref_id(f"class_{class_name}")

        # 缓存完整结果
        self.result_cache[ref_id] = class_info

        # 返回最小化摘要
        summary = {
            "name": class_name,
            "module": class_info.get("module", "unknown"),
            "parent": class_info.get("parent_classes", ["unknown"])[0] if class_info.get("parent_classes") else None,
            "method_count": len(class_info.get("methods", [])),
            "key_methods": class_info.get("methods", [])[:5],  # 仅前5个
            "is_uclass": class_info.get("is_uclass", False),
            "is_blueprint": class_info.get("is_blueprint", False),
            "ref_id": ref_id,  # 引用 ID，可查询完整信息
            "hint": f"使用 query_class('{class_name}', 'details') 获取完整信息"
        }

        return summary

    def _query_class_details(self, class_name_or_ref: str) -> Dict[str, Any]:
        """
        详情层查询（完整信息）

        Args:
            class_name_or_ref: 类名或引用ID

        Returns:
            完整的类信息（~500-1000 tokens）
        """
        # 检查是否为引用 ID
        if class_name_or_ref.startswith("ref_"):
            if class_name_or_ref in self.result_cache:
                return self.result_cache[class_name_or_ref]
            else:
                return {"error": f"引用ID已过期: {class_name_or_ref}"}

        # 否则查询完整信息
        class_info = self._load_class_info(class_name_or_ref)

        if not class_info:
            return {"error": f"未找到类: {class_name_or_ref}"}

        # 返回完整信息（但不包含源码）
        return {
            "name": class_name_or_ref,
            "module": class_info.get("module"),
            "parent_classes": class_info.get("parent_classes", []),
            "interfaces": class_info.get("interfaces", []),
            "methods": class_info.get("methods", []),  # 完整列表
            "properties": class_info.get("properties", []),
            "file_path": class_info.get("file"),
            "line_number": class_info.get("line"),
            "is_uclass": class_info.get("is_uclass", False),
            "source_ref": self._generate_ref_id(f"source_{class_name_or_ref}")
        }

    def _query_class_source(self, ref_id: str) -> Dict[str, Any]:
        """
        源码层查询（原始代码）

        Args:
            ref_id: 源码引用 ID

        Returns:
            源代码内容
        """
        # 从引用 ID 提取类名
        if not ref_id.startswith("ref_source_"):
            return {"error": "Invalid source ref_id"}

        class_name = ref_id.replace("ref_source_", "")

        # 加载源码（实际实现会从文件读取）
        source_code = self._load_source_code(class_name)

        return {
            "class": class_name,
            "source_code": source_code,
            "warning": "源码内容可能很长，消耗大量 tokens"
        }

    def query_function(self, function_name: str, detail_level: str = 'summary') -> Dict[str, Any]:
        """
        查询函数信息（分层）

        Args:
            function_name: 函数名
            detail_level: 详情级别

        Returns:
            分层的查询结果
        """
        if detail_level == 'summary':
            return self._query_function_summary(function_name)
        elif detail_level == 'details':
            return self._query_function_details(function_name)
        else:
            raise ValueError(f"Invalid detail_level: {detail_level}")

    def _query_function_summary(self, function_name: str) -> Dict[str, Any]:
        """
        函数摘要查询（~50-100 tokens）
        """
        # 使用函数索引快速查询
        from ue5_kb.core.function_index import FunctionIndex

        func_index_path = self.kb_path / "global_index" / "function_index.db"
        if not func_index_path.exists():
            return {"error": "函数索引不存在"}

        func_index = FunctionIndex(str(func_index_path))
        results = func_index.query_by_name(function_name)
        func_index.close()

        if not results:
            return {"error": f"未找到函数: {function_name}"}

        # 仅返回第一个匹配（最相关）
        first = results[0]

        # 生成引用 ID
        ref_id = self._generate_ref_id(f"func_{function_name}")
        self.result_cache[ref_id] = results  # 缓存所有结果

        return {
            "function": function_name,
            "signature": first['signature'],  # 完整签名（紧凑）
            "module": first['module'],
            "is_blueprint_callable": first['is_blueprint_callable'],
            "total_matches": len(results),
            "ref_id": ref_id,
            "hint": f"找到 {len(results)} 个匹配。使用 query_function('{function_name}', 'details') 查看全部"
        }

    def _query_function_details(self, function_name_or_ref: str) -> Dict[str, Any]:
        """
        函数详情查询（完整信息）
        """
        # 检查是否为引用 ID
        if function_name_or_ref.startswith("ref_"):
            if function_name_or_ref in self.result_cache:
                results = self.result_cache[function_name_or_ref]
            else:
                return {"error": f"引用ID已过期: {function_name_or_ref}"}
        else:
            # 重新查询
            from ue5_kb.core.function_index import FunctionIndex
            func_index_path = self.kb_path / "global_index" / "function_index.db"
            func_index = FunctionIndex(str(func_index_path))
            results = func_index.query_by_name(function_name_or_ref)
            func_index.close()

        if not results:
            return {"error": "未找到函数"}

        # 返回所有匹配的完整信息
        return {
            "function_name": function_name_or_ref.replace("ref_func_", ""),
            "total_matches": len(results),
            "matches": [
                {
                    "signature": r['signature'],
                    "module": r['module'],
                    "class": r['class_name'],
                    "location": f"{r['file_path']}:{r['line_number']}",
                    "parameters": r['parameters'],
                    "return_type": r['return_type'],
                    "is_blueprint_callable": r['is_blueprint_callable'],
                    "ufunction_specifiers": r['ufunction_specifiers']
                }
                for r in results
            ]
        }

    def _generate_ref_id(self, key: str) -> str:
        """生成引用 ID"""
        hash_val = hashlib.md5(key.encode()).hexdigest()[:8]
        return f"ref_{hash_val}"

    def _load_class_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """
        加载类信息（真实实现）

        从 module_graphs 中加载类的详细信息
        """
        import pickle
        from ..core.config import Config
        from ..core.global_index import GlobalIndex

        try:
            # 1. 加载 global_index 查找模块
            config = Config(str(self.kb_path / "config.yaml"))
            global_index = GlobalIndex(config)

            # 2. 遍历所有模块图谱查找类
            graphs_dir = self.kb_path / "module_graphs"
            if not graphs_dir.exists():
                return None

            for graph_file in graphs_dir.glob("*.pkl"):
                try:
                    with open(graph_file, 'rb') as f:
                        data = pickle.load(f)
                        graph = data.get('graph')

                        if not graph:
                            continue

                        # 查找类节点
                        class_node = f"class_{class_name}"
                        if class_node not in graph.nodes:
                            continue

                        # 找到了！提取信息
                        node_data = graph.nodes[class_node]
                        module_name = data.get('module', 'unknown')

                        # 提取父类
                        parent_classes = []
                        for pred in graph.predecessors(class_node):
                            if pred.startswith('class_'):
                                parent_classes.append(graph.nodes[pred].get('name', pred))

                        # 提取方法
                        methods = []
                        for succ in graph.successors(class_node):
                            if succ.startswith('method_') or succ.startswith('function_'):
                                methods.append(graph.nodes[succ].get('name', succ))

                        return {
                            'name': class_name,
                            'module': module_name,
                            'parent_classes': parent_classes,
                            'methods': methods,
                            'file': node_data.get('file', ''),
                            'line': node_data.get('line', 0),
                            'is_uclass': node_data.get('is_uclass', False),
                            'is_blueprint': node_data.get('is_blueprint', False),
                            'properties': node_data.get('properties', [])
                        }

                except Exception as e:
                    # 单个文件失败不影响其他文件
                    continue

            # 没找到
            return None

        except Exception as e:
            print(f"警告: 加载类信息失败: {e}")
            return None

    def _load_source_code(self, class_name: str) -> str:
        """
        加载源代码（真实实现）

        从文件系统读取类的源代码
        """
        # 先获取类信息（包含文件路径）
        class_info = self._load_class_info(class_name)
        if not class_info:
            return f"// 未找到类 {class_name}"

        file_path = class_info.get('file')
        if not file_path:
            return f"// 类 {class_name} 没有关联的源文件"

        # 尝试读取文件
        try:
            # 文件路径可能是相对路径，需要结合引擎路径
            full_path = Path(file_path)
            if not full_path.is_absolute():
                # 尝试从 kb_path 的父目录解析
                engine_path = self.kb_path.parent
                full_path = engine_path / file_path

            if not full_path.exists():
                return f"// 源文件不存在: {file_path}"

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        except Exception as e:
            return f"// 读取源文件失败: {e}"

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "cached_results": len(self.result_cache),
            "cache_refs": list(self.result_cache.keys())
        }

    def clear_cache(self) -> None:
        """清除缓存"""
        self.result_cache.clear()
