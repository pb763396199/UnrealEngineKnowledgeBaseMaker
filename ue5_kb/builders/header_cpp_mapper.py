"""
UE5 知识库系统 - 头文件到 CPP 文件映射器

基于 #include 关系建立反向映射：
- 解析所有 cpp 文件的 #include 语句
- 建立映射：头文件路径 -> [包含它的 cpp 文件路径列表]
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional


class HeaderToCppMapper:
    """
    头文件到 CPP 文件映射器

    基于 #include 关系建立反向映射：
    - 解析所有 cpp 文件的 #include 语句
    - 建立映射：头文件路径 -> [包含它的 cpp 文件路径列表]
    """

    # #include 匹配模式
    INCLUDE_PATTERN = re.compile(r'#include\s+["<]([^">]+)[">]')

    def __init__(self, module_path: str):
        self.module_path = Path(module_path)
        self.header_to_cpps: Dict[str, List[str]] = {}  # 头文件 -> cpp列表
        self.cpp_includes: Dict[str, List[str]] = {}    # cpp文件 -> 包含的头文件列表

    def build_mapping(self) -> Dict[str, List[str]]:
        """
        构建头文件到 cpp 文件的映射

        Returns:
            {头文件绝对路径: [包含它的cpp文件绝对路径列表]}
        """
        # 第一遍：收集所有头文件和cpp文件的完整路径索引
        all_headers = {}  # {文件名: [完整路径列表]}
        all_cpps = {}     # {文件名: [完整路径列表]}

        for root, dirs, files in os.walk(self.module_path):
            dirs[:] = [d for d in dirs if d not in ['Intermediate', 'Saved', 'Binaries']]

            for file in files:
                file_path = os.path.join(root, file)
                if file.endswith('.h'):
                    all_headers.setdefault(file, []).append(file_path)
                elif file.endswith('.cpp'):
                    all_cpps.setdefault(file, []).append(file_path)

        # 第二遍：解析每个 cpp 文件的 #include
        for cpp_name, cpp_paths in all_cpps.items():
            for cpp_path in cpp_paths:
                includes = self._extract_includes(cpp_path)
                self.cpp_includes[cpp_path] = includes

                # 建立反向映射
                for include in includes:
                    # 解析 include 路径，找到对应的头文件
                    header_path = self._resolve_include_path(
                        include, cpp_path, all_headers
                    )
                    if header_path:
                        self.header_to_cpps.setdefault(header_path, []).append(cpp_path)

        return self.header_to_cpps

    def _extract_includes(self, cpp_path: str) -> List[str]:
        """从 cpp 文件提取 #include 语句"""
        includes = []
        try:
            with open(cpp_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    match = self.INCLUDE_PATTERN.search(line)
                    if match:
                        includes.append(match.group(1))
        except Exception:
            pass
        return includes

    def _resolve_include_path(
        self, include: str, cpp_path: str, all_headers: Dict[str, List[str]]
    ) -> Optional[str]:
        """
        将 #include 路径解析为绝对路径

        Args:
            include: include 语句中的路径，如 "MyClass.h" 或 "Module/Public/MyClass.h"
            cpp_path: 包含此 include 的 cpp 文件路径
            all_headers: 所有头文件的索引

        Returns:
            头文件的绝对路径，如果找不到则返回 None
        """
        # 策略1: 如果是相对路径，相对于 cpp 文件目录解析
        if not os.path.isabs(include):
            # 尝试相对于 cpp 文件目录
            cpp_dir = os.path.dirname(cpp_path)
            resolved = os.path.normpath(os.path.join(cpp_dir, include))
            if os.path.exists(resolved):
                return resolved

            # 策略2: 尝试相对于模块根目录的常见位置
            possible_paths = [
                self.module_path / 'Public' / include,
                self.module_path / 'Private' / include,
                self.module_path / 'Classes' / include,
                self.module_path / include,
            ]
            for path in possible_paths:
                if path.exists():
                    return str(path)

        # 策略3: 按文件名在 all_headers 中查找
        file_name = os.path.basename(include)
        if file_name in all_headers:
            # 如果有多个匹配，尝试路径匹配
            for header_path in all_headers[file_name]:
                if include in header_path or include.replace('/', os.sep) in header_path:
                    return header_path
            # 默认返回第一个匹配
            return all_headers[file_name][0]

        return None

    def get_cpps_for_header(self, header_path: str) -> List[str]:
        """获取包含指定头文件的所有 cpp 文件"""
        return self.header_to_cpps.get(header_path, [])
