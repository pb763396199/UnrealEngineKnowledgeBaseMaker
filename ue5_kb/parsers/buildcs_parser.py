"""
UE5 知识库系统 - Build.cs 解析器

负责解析 .Build.cs 文件，提取模块依赖关系信息
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional


class BuildCsParser:
    """
    Unreal Build.cs 文件解析器

    从 .Build.cs 文件中提取:
    - 公共依赖 (PublicDependencyModuleNames)
    - 私有依赖 (PrivateDependencyModuleNames)
    - 动态加载依赖 (DynamicallyLoadedModuleNames)
    - 仅引用依赖 (WeakIncludePathsModuleNames)
    - 循环依赖 (CircularlyReferencedDependentModules)
    """

    # 依赖相关的属性名称模式
    DEPENDENCY_PATTERNS = {
        'public': r'PublicDependencyModuleNames\.(?:AddRange|Add)\(\s*new\s+string\[\]\s*{\s*([^}]+)\s*}\s*\)',
        'private': r'PrivateDependencyModuleNames\.(?:AddRange|Add)\(\s*new\s+string\[\]\s*{\s*([^}]+)\s*}\s*\)',
        'dynamic': r'DynamicallyLoadedModuleNames\.(?:AddRange|Add)\(\s*new\s+string\[\]\s*{\s*([^}]+)\s*}\s*\)',
        'weak': r'WeakIncludePathsModuleNames\.(?:AddRange|Add)\(\s*new\s+string\[\]\s*{\s*([^}]+)\s*}\s*\)',
        'circular': r'CircularlyReferencedDependentModules\.(?:AddRange|Add)\(\s*new\s+string\[\]\s*{\s*([^}]+)\s*}\s*\)',
    }

    # 单个添加的模式
    SINGLE_ADD_PATTERNS = [
        r'(Public|Private)DependencyModuleNames\.Add\(\s*"([^"]+)"\s*\)',
        r'DynamicallyLoadedModuleNames\.Add\(\s*"([^"]+)"\s*\)',
    ]

    def __init__(self):
        """初始化解析器"""
        self.dependencies = {
            'public': [],
            'private': [],
            'dynamic': [],
            'weak': [],
            'circular': []
        }

    def parse_file(self, file_path: str) -> Dict[str, List[str]]:
        """
        解析 .Build.cs 文件

        Args:
            file_path: .Build.cs 文件路径

        Returns:
            依赖字典，包含各种类型的依赖列表
        """
        if not os.path.exists(file_path):
            return {k: [] for k in self.dependencies.keys()}

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return self.parse_content(content)

    def parse_content(self, content: str) -> Dict[str, List[str]]:
        """
        解析 .Build.cs 内容

        Args:
            content: .Build.cs 文件内容

        Returns:
            依赖字典
        """
        self.dependencies = {k: [] for k in self.dependencies.keys()}

        # 使用正则表达式提取依赖
        for dep_type, pattern in self.DEPENDENCY_PATTERNS.items():
            matches = re.findall(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                modules = self._extract_module_names(match)
                self.dependencies[dep_type].extend(modules)

        # 处理单个添加的情况
        for match in re.finditer('|'.join(self.SINGLE_ADD_PATTERNS), content):
            groups = match.groups()
            if len(groups) >= 2:
                dep_type = 'public' if groups[0] == 'Public' else 'private'
                module = groups[1]
                if module and module not in self.dependencies[dep_type]:
                    self.dependencies[dep_type].append(module)
            elif len(groups) == 1:
                # 可能是动态加载
                module = groups[0]
                if module and module not in self.dependencies['dynamic']:
                    self.dependencies['dynamic'].append(module)

        # 去重并排序
        for dep_type in self.dependencies:
            self.dependencies[dep_type] = sorted(set(self.dependencies[dep_type]))

        return self.dependencies

    def _extract_module_names(self, match_text: str) -> List[str]:
        """
        从匹配文本中提取模块名称

        Args:
            match_text: 正则匹配的文本

        Returns:
            模块名称列表
        """
        # 移除注释
        match_text = re.sub(r'//.*$', '', match_text, flags=re.MULTILINE)
        match_text = re.sub(r'/\*.*?\*/', '', match_text, flags=re.DOTALL)

        # 提取引号内的字符串
        modules = re.findall(r'"([^"]+)"', match_text)

        return modules

    def get_all_dependencies(self) -> List[str]:
        """
        获取所有依赖（合并所有类型）

        Returns:
            所有依赖模块名称列表
        """
        all_deps = []
        for deps in self.dependencies.values():
            all_deps.extend(deps)
        return sorted(set(all_deps))

    def get_public_dependencies(self) -> List[str]:
        """获取公共依赖"""
        return self.dependencies['public']

    def get_private_dependencies(self) -> List[str]:
        """获取私有依赖"""
        return self.dependencies['private']

    def get_dynamic_dependencies(self) -> List[str]:
        """获取动态加载依赖"""
        return self.dependencies['dynamic']

    def get_weak_dependencies(self) -> List[str]:
        """获取弱引用依赖"""
        return self.dependencies['weak']

    def get_circular_dependencies(self) -> List[str]:
        """获取循环依赖"""
        return self.dependencies['circular']

    @staticmethod
    def find_module_build_cs(module_path: str) -> Optional[str]:
        """
        查找模块的 .Build.cs 文件

        Args:
            module_path: 模块目录路径

        Returns:
            .Build.cs 文件路径，如果不存在返回 None
        """
        module_name = os.path.basename(module_path.rstrip(os.sep))
        build_cs_path = os.path.join(module_path, f"{module_name}.Build.cs")

        if os.path.exists(build_cs_path):
            return build_cs_path

        return None

    @staticmethod
    def extract_module_name_from_file(file_path: str) -> Optional[str]:
        """
        从 .Build.cs 文件路径提取模块名称

        Args:
            file_path: .Build.cs 文件路径

        Returns:
            模块名称
        """
        if not file_path.endswith('.Build.cs'):
            return None

        basename = os.path.basename(file_path)
        # 移除 .Build.cs 后缀
        module_name = basename.replace('.Build.cs', '')
        return module_name

    def __repr__(self) -> str:
        total_deps = sum(len(deps) for deps in self.dependencies.values())
        return f"BuildCsParser(dependencies={total_deps})"
