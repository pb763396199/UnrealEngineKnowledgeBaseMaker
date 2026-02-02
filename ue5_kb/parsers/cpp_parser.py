"""
UE5 知识库系统 - C++ 代码解析器

负责解析 C++ 源文件，提取类、函数、继承关系等信息
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field


@dataclass
class ClassInfo:
    """类信息"""
    name: str
    is_uclass: bool = False
    is_struct: bool = False
    is_interface: bool = False
    parent_class: Optional[str] = None
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    properties: List[str] = field(default_factory=list)
    file_path: str = ""
    line_number: int = 0
    namespace: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'is_uclass': self.is_uclass,
            'is_struct': self.is_struct,
            'is_interface': self.is_interface,
            'parent_class': self.parent_class,
            'interfaces': self.interfaces,
            'methods': self.methods,
            'properties': self.properties,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'namespace': self.namespace
        }


@dataclass
class FunctionInfo:
    """函数信息"""
    name: str
    return_type: str = ""
    parameters: List[str] = field(default_factory=list)
    is_ufunction: bool = False
    is_static: bool = False
    is_virtual: bool = False
    is_const: bool = False
    class_name: Optional[str] = None
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'return_type': self.return_type,
            'parameters': self.parameters,
            'is_ufunction': self.is_ufunction,
            'is_static': self.is_static,
            'is_virtual': self.is_virtual,
            'is_const': self.is_const,
            'class_name': self.class_name,
            'file_path': self.file_path,
            'line_number': self.line_number
        }


class CppParser:
    """
    C++ 代码解析器

    使用正则表达式解析 C++ 源文件，提取:
    - 类定义 (包括 UCLASS)
    - 结构体定义 (包括 USTRUCT)
    - 函数定义 (包括 UFUNCTION)
    - 继承关系
    - 接口实现
    """

    # UE5 宏模式
    UCLASS_PATTERN = r'UCLASS\s*\(([^)]*)\)'
    USTRUCT_PATTERN = r'USTRUCT\s*\(([^)]*)\)'
    UFUNCTION_PATTERN = r'UFUNCTION\s*\(([^)]*)\)'
    UPROPERTY_PATTERN = r'UPROPERTY\s*\(([^)]*)\)'
    UINTERFACE_PATTERN = r'UINTERFACE\s*\(([^)]*)\)'

    # 类/结构体声明模式
    CLASS_DECL_PATTERN = r'class\s+([A-Z_][A-Z0-9_]*)\s*:\s*public\s+([A-Z_][A-Z0-9_]*)'
    STRUCT_DECL_PATTERN = r'struct\s+([A-Z_][A-Z0-9_]*)\s*:\s*public\s+([A-Z_][A-Z0-9_]*)'

    # 函数声明模式
    FUNCTION_DECL_PATTERN = r'([A-Z_][A-Z0-9_<>:*&\s]+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)'

    def __init__(self):
        """初始化解析器"""
        self.classes: Dict[str, ClassInfo] = {}
        self.functions: Dict[str, FunctionInfo] = {}

    def parse_file(self, file_path: str) -> Tuple[Dict[str, ClassInfo], Dict[str, FunctionInfo]]:
        """
        解析 C++ 源文件

        Args:
            file_path: 源文件路径

        Returns:
            (类信息字典, 函数信息字典)
        """
        if not os.path.exists(file_path):
            return {}, {}

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        return self.parse_content(content, file_path)

    def parse_content(self, content: str, file_path: str = "") -> Tuple[Dict[str, ClassInfo], Dict[str, FunctionInfo]]:
        """
        解析 C++ 代码内容

        Args:
            content: C++ 代码内容
            file_path: 文件路径（用于调试）

        Returns:
            (类信息字典, 函数信息字典)
        """
        self.classes = {}
        self.functions = {}

        # 移除注释
        content = self._remove_comments(content)

        # 移除字符串字面量
        content = re.sub(r'"[^"]*"', '""', content)

        # 解析类
        self._parse_classes(content, file_path)

        # 解析函数
        self._parse_functions(content, file_path)

        return self.classes, self.functions

    def _remove_comments(self, content: str) -> str:
        """移除注释"""
        # 移除单行注释
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content

    def _parse_classes(self, content: str, file_path: str) -> None:
        """解析类定义"""
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # 检查是否有 UCLASS 宏
            is_uclass = bool(re.search(self.UCLASS_PATTERN, line))
            is_ustruct = bool(re.search(self.USTRUCT_PATTERN, line))
            is_uinterface = bool(re.search(self.UINTERFACE_PATTERN, line))

            if is_uclass or is_ustruct or is_uinterface:
                # 尝试在下一行找到类声明
                if line_num < len(lines):
                    next_line = lines[line_num]
                    self._extract_class_declaration(next_line, file_path, line_num, is_uclass, is_ustruct, is_uinterface)

            # 也检查普通类声明
            match = re.search(self.CLASS_DECL_PATTERN, line)
            if match:
                class_name = match.group(1)
                parent_class = match.group(2)

                if class_name not in self.classes:
                    self.classes[class_name] = ClassInfo(
                        name=class_name,
                        parent_class=parent_class,
                        file_path=file_path,
                        line_number=line_num
                    )

    def _extract_class_declaration(self, line: str, file_path: str, line_num: int,
                                   is_uclass: bool, is_ustruct: bool, is_uinterface: bool) -> None:
        """从行中提取类声明"""
        # 匹配 class ClassName : public ParentClass
        match = re.search(r'class\s+([A-Z_][A-Z0-9_]*)\s*:\s*public\s+([A-Z_][A-Z0-9_]*)', line)

        if match:
            class_name = match.group(1)
            parent_class = match.group(2)

            if class_name not in self.classes:
                self.classes[class_name] = ClassInfo(
                    name=class_name,
                    parent_class=parent_class,
                    is_uclass=is_uclass,
                    is_struct=is_ustruct,
                    is_interface=is_uinterface,
                    file_path=file_path,
                    line_number=line_num
                )
            else:
                # 更新现有类信息
                info = self.classes[class_name]
                info.is_uclass = is_uclass
                info.is_struct = is_ustruct
                info.is_interface = is_uinterface

    def _parse_functions(self, content: str, file_path: str) -> None:
        """解析函数声明"""
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # 检查是否有 UFUNCTION 宏
            is_ufunction = bool(re.search(self.UFUNCTION_PATTERN, line))

            # 尝试匹配函数声明
            match = re.search(self.FUNCTION_DECL_PATTERN, line)
            if match:
                return_type = match.group(1).strip()
                func_name = match.group(2)
                params = match.group(3)

                # 过滤掉非函数的关键字
                if func_name in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct']:
                    continue

                func_key = f"{func_name}_{line_num}"
                self.functions[func_key] = FunctionInfo(
                    name=func_name,
                    return_type=return_type,
                    parameters=self._parse_parameters(params),
                    is_ufunction=is_ufunction,
                    file_path=file_path,
                    line_number=line_num
                )

    def _parse_parameters(self, params_str: str) -> List[str]:
        """解析函数参数"""
        if not params_str or params_str.strip() == 'void':
            return []

        params = []
        for param in params_str.split(','):
            param = param.strip()
            if param:
                params.append(param)

        return params

    def get_classes(self) -> Dict[str, ClassInfo]:
        """获取所有解析的类"""
        return self.classes

    def get_functions(self) -> Dict[str, FunctionInfo]:
        """获取所有解析的函数"""
        return self.functions

    def get_uclasses(self) -> List[str]:
        """获取所有 UCLASS 类名"""
        return [
            name for name, info in self.classes.items()
            if info.is_uclass
        ]

    def get_inheritance_chain(self, class_name: str) -> List[str]:
        """
        获取类的继承链

        Args:
            class_name: 类名

        Returns:
            继承链 [父类, ..., 当前类]
        """
        chain = [class_name]
        current = class_name

        while current in self.classes:
            parent = self.classes[current].parent_class
            if not parent:
                break
            chain.append(parent)
            current = parent

        return list(reversed(chain))

    def __repr__(self) -> str:
        return f"CppParser(classes={len(self.classes)}, functions={len(self.functions)})"
