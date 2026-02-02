"""
UE5 知识库系统 - 函数调用关系分析器

功能：
- 提取函数调用关系（使用正则匹配，简化版）
- 构建调用关系图
- 支持后续升级到 libclang AST 解析
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
import networkx as nx


class CallAnalyzer:
    """
    函数调用关系分析器

    使用正则表达式提取函数调用关系（简化版）
    """

    # C++ 关键字（不是函数调用）
    CPP_KEYWORDS = {
        'if', 'else', 'while', 'for', 'switch', 'case', 'break', 'continue',
        'return', 'sizeof', 'typeof', 'static_cast', 'dynamic_cast',
        'const_cast', 'reinterpret_cast', 'new', 'delete', 'throw',
        'try', 'catch', 'class', 'struct', 'enum', 'namespace', 'template'
    }

    def __init__(self):
        """初始化分析器"""
        self.call_graph = nx.DiGraph()  # 调用关系图
        self.function_bodies = {}        # 函数名 -> 函数体代码

    def analyze_file(self, file_path: str) -> List[Tuple[str, str]]:
        """
        分析单个文件的函数调用关系

        Args:
            file_path: 源文件路径

        Returns:
            [(caller, callee), ...] 调用关系列表
        """
        if not os.path.exists(file_path):
            return []

        # 只分析 .cpp 文件（函数实现）
        if not file_path.endswith('.cpp'):
            return []

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        return self.extract_calls(content)

    def extract_calls(self, cpp_content: str) -> List[Tuple[str, str]]:
        """
        从 C++ 代码提取函数调用关系

        Args:
            cpp_content: C++ 代码内容

        Returns:
            [(caller, callee), ...] 调用关系列表
        """
        # 移除注释
        cpp_content = self._remove_comments(cpp_content)

        # 移除字符串字面量
        cpp_content = re.sub(r'"[^"]*"', '""', cpp_content)

        # 提取所有函数定义
        functions = self._extract_function_definitions(cpp_content)

        calls = []

        for func_name, func_body in functions.items():
            # 提取此函数调用的其他函数
            callees = self._extract_function_calls(func_body, func_name)

            for callee in callees:
                calls.append((func_name, callee))

        return calls

    def _remove_comments(self, content: str) -> str:
        """移除注释"""
        # 移除单行注释
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content

    def _extract_function_definitions(self, content: str) -> Dict[str, str]:
        """
        提取函数定义及其函数体

        Returns:
            {函数名: 函数体代码}
        """
        functions = {}

        # 简化的函数定义模式（匹配函数名后的大括号）
        # 匹配: ReturnType FunctionName(...) { ... }
        pattern = r'(\w+)\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:const\s*)?(?:override\s*)?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}'

        for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
            func_name = match.group(2)
            func_body = match.group(3)

            # 过滤掉非函数（如 if, while 等）
            if func_name not in self.CPP_KEYWORDS:
                functions[func_name] = func_body

        return functions

    def _extract_function_calls(self, func_body: str, caller_name: str) -> Set[str]:
        """
        从函数体提取函数调用

        Args:
            func_body: 函数体代码
            caller_name: 调用者函数名

        Returns:
            被调用的函数名集合
        """
        callees = set()

        # 匹配模式：标识符后跟 (
        # 例如: MyFunction(...)
        pattern = r'(\w+)\s*\('

        for match in re.finditer(pattern, func_body):
            callee = match.group(1)

            # 过滤条件：
            # 1. 不是 C++ 关键字
            # 2. 不是调用者自己（递归调用除外）
            # 3. 不是单字母（通常是模板参数）
            if (callee not in self.CPP_KEYWORDS and
                len(callee) > 1):
                callees.add(callee)

        return callees

    def build_call_graph(self, calls: List[Tuple[str, str]]) -> nx.DiGraph:
        """
        构建调用关系图

        Args:
            calls: 调用关系列表 [(caller, callee), ...]

        Returns:
            调用关系图
        """
        graph = nx.DiGraph()

        for caller, callee in calls:
            # 添加边：caller → callee
            graph.add_edge(caller, callee)

        return graph

    def find_callers(self, function_name: str, graph: nx.DiGraph, max_depth: int = 2) -> List[List[str]]:
        """
        查找谁调用了此函数（反向深度优先搜索）

        Args:
            function_name: 函数名
            graph: 调用关系图
            max_depth: 最大深度

        Returns:
            调用链列表 [[caller1, caller2, ...], ...]
        """
        if function_name not in graph:
            return []

        # 反向图：callee → caller
        reverse_graph = graph.reverse(copy=True)

        # 深度优先搜索
        paths = []

        def dfs(node, path, depth):
            if depth >= max_depth:
                paths.append(path.copy())
                return

            # 获取所有调用者
            callers = list(reverse_graph.successors(node))

            if not callers:
                # 叶子节点
                paths.append(path.copy())
            else:
                for caller in callers:
                    path.append(caller)
                    dfs(caller, path, depth + 1)
                    path.pop()

        dfs(function_name, [function_name], 0)

        return paths

    def find_callees(self, function_name: str, graph: nx.DiGraph, max_depth: int = 2) -> List[List[str]]:
        """
        查找此函数调用了谁（正向深度优先搜索）

        Args:
            function_name: 函数名
            graph: 调用关系图
            max_depth: 最大深度

        Returns:
            调用链列表
        """
        if function_name not in graph:
            return []

        paths = []

        def dfs(node, path, depth):
            if depth >= max_depth:
                paths.append(path.copy())
                return

            callees = list(graph.successors(node))

            if not callees:
                paths.append(path.copy())
            else:
                for callee in callees:
                    path.append(callee)
                    dfs(callee, path, depth + 1)
                    path.pop()

        dfs(function_name, [function_name], 0)

        return paths

    def find_call_chain(self, from_func: str, to_func: str, graph: nx.DiGraph, max_depth: int = 5) -> Optional[List[str]]:
        """
        查找两个函数之间的调用路径

        Args:
            from_func: 起始函数
            to_func: 目标函数
            graph: 调用关系图
            max_depth: 最大深度

        Returns:
            调用路径，如果不存在则返回 None
        """
        if from_func not in graph or to_func not in graph:
            return None

        try:
            # 使用 NetworkX 的最短路径算法
            path = nx.shortest_path(graph, from_func, to_func)
            if len(path) - 1 <= max_depth:  # 边数 = 节点数 - 1
                return path
        except nx.NetworkXNoPath:
            pass

        return None

    def get_statistics(self, graph: nx.DiGraph) -> Dict[str, any]:
        """获取调用图统计信息"""
        return {
            "total_functions": graph.number_of_nodes(),
            "total_calls": graph.number_of_edges(),
            "isolated_functions": len(list(nx.isolates(graph))),
            "strongly_connected_components": nx.number_strongly_connected_components(graph),
            "max_call_depth": nx.dag_longest_path_length(nx.DiGraph(graph)) if nx.is_directed_acyclic_graph(graph) else "N/A (has cycles)"
        }
