"""
UE5 知识库系统 - C++ 代码解析器

负责解析 C++ 源文件，提取类、函数、继承关系等信息
优化版本 - 支持 UE5 代码风格
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
class ParameterInfo:
    """函数参数信息"""
    type: str
    name: str
    default_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'name': self.name,
            'default': self.default_value
        }


@dataclass
class FunctionInfo:
    """函数信息"""
    name: str
    return_type: str = ""
    parameters: List[ParameterInfo] = field(default_factory=list)
    is_ufunction: bool = False
    is_static: bool = False
    is_virtual: bool = False
    is_const: bool = False
    is_override: bool = False
    is_blueprint_callable: bool = False
    ufunction_specifiers: Dict[str, Any] = field(default_factory=dict)
    class_name: Optional[str] = None
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'return_type': self.return_type,
            'parameters': [p.to_dict() for p in self.parameters],
            'is_ufunction': self.is_ufunction,
            'is_static': self.is_static,
            'is_virtual': self.is_virtual,
            'is_const': self.is_const,
            'is_override': self.is_override,
            'is_blueprint_callable': self.is_blueprint_callable,
            'ufunction_specifiers': self.ufunction_specifiers,
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

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return {}, {}

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

        # 预处理代码
        content = self._preprocess_content(content)

        # 解析类和结构体
        self._parse_classes_and_structs(content, file_path)

        # 解析函数
        self._parse_functions(content, file_path)

        return self.classes, self.functions

    def _preprocess_content(self, content: str) -> str:
        """预处理代码内容"""
        # 移除单行注释
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # 标准化空白
        content = re.sub(r'\s+', ' ', content)
        return content.strip()

    def _parse_classes_and_structs(self, content: str, file_path: str) -> None:
        """解析类和结构体定义"""
        lines = content.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 检查是否有 UE5 宏
            is_uclass = bool(re.search(self.UCLASS_PATTERN, line))
            is_ustruct = bool(re.search(self.USTRUCT_PATTERN, line))
            is_uinterface = bool(re.search(self.UINTERFACE_PATTERN, line))

            # 查找类/结构体声明
            # 支持以下格式:
            # - class AMyActor : public AActor
            # - class MYPROJECT_API AMyActor : public AActor
            # - class AMyActor : public AActor, public IInterface
            # - struct FMyStruct : public FMyBase

            class_pattern = r'\b(class|struct)\s+((?:[A-Z_]+_API\s+)?[A-Z][A-Za-z0-9_]*)\s*:\s*(?:public\s+)?([A-Z][A-Za-z0-9_<>*&:\s]*)'

            match = re.search(class_pattern, line)
            if match:
                decl_type = match.group(1)  # class or struct
                full_name = match.group(2).strip()
                parent_part = match.group(3).strip()

                # 清理 API 宏
                class_name = full_name.split()[-1] if ' ' in full_name else full_name

                # 提取父类
                parent_class = None
                if parent_part and parent_part != '':
                    # 移除可能的继承访问修饰符
                    parent_clean = re.sub(r'\b(public|private|protected)\s+', '', parent_part)
                    parent_clean = parent_clean.strip().split()[0] if parent_clean else None
                    if parent_clean:
                        parent_class = parent_clean

                # 确定类型标志
                if decl_type == 'struct':
                    is_struct = True
                    is_uclass = is_ustruct
                else:
                    is_struct = False
                    # 如果前面检测到 UCLASS 宏，使用它
                    is_uclass = is_uclass

                is_interface = is_uinterface

                # 创建或更新类信息
                if class_name not in self.classes:
                    self.classes[class_name] = ClassInfo(
                        name=class_name,
                        parent_class=parent_class,
                        is_uclass=is_uclass,
                        is_struct=is_struct,
                        is_interface=is_interface,
                        file_path=file_path,
                        line_number=i + 1
                    )
                else:
                    # 更新现有类信息
                    info = self.classes[class_name]
                    if is_uclass:
                        info.is_uclass = True
                    if is_struct:
                        info.is_struct = True
                    if is_interface:
                        info.is_interface = True
                    if parent_class and not info.parent_class:
                        info.parent_class = parent_class

            i += 1

    def _parse_functions(self, content: str, file_path: str) -> None:
        """解析函数声明"""
        lines = content.split('\n')

        ufunction_specifiers = {}

        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()

            # 检查是否有 UFUNCTION 宏
            ufunction_match = re.search(self.UFUNCTION_PATTERN, line_stripped)
            if ufunction_match:
                ufunction_specifiers = self._parse_ufunction_specifiers(ufunction_match.group(1))
                continue

            # 跳过明显不是函数声明的行
            if not line_stripped or line_stripped.startswith('//'):
                continue

            # 跳过关键字
            if line_stripped.split()[0] in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'namespace']:
                continue

            # 函数声明模式
            # 支持格式:
            # - void FunctionName();
            # - virtual void FunctionName() override;
            # - static float FunctionName(int32 value);
            # - UFUNCTION(BlueprintCallable) void MyFunction();
            # - void FunctionName() const;

            # 首先处理行尾的修饰符
            const_override_part = ''
            if ' const' in line_stripped:
                const_override_part = ' const'
                line_stripped = line_stripped.replace(' const', '')
            if ' override' in line_stripped:
                const_override_part += ' override'
                line_stripped = line_stripped.replace(' override', '')
            if ' final' in line_stripped:
                const_override_part += ' final'
                line_stripped = line_stripped.replace(' final', '')

            # 函数签名模式
            # 返回类型 + 函数名 + 参数列表
            func_pattern = r'^([A-Za-z_][A-Za-z0-9_<>*&:\s]*?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*(?:=\s*0\s*)?;?$'

            match = re.match(func_pattern, line_stripped.strip())
            if match:
                return_type = match.group(1).strip()
                func_name = match.group(2)
                params = match.group(3)

                # 过滤掉非函数的关键字
                if func_name in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'namespace', 'operator']:
                    continue

                # 检测修饰符
                is_virtual = 'virtual' in return_type
                is_static = 'static' in return_type
                is_const = ' const' in const_override_part
                is_override = ' override' in const_override_part

                # 清理返回类型（移除修饰符）
                return_type_clean = return_type.replace('virtual', '').replace('static', '').strip()

                # Blueprint callable 检测
                is_blueprint_callable = (
                    ufunction_specifiers.get('BlueprintCallable', False) or
                    ufunction_specifiers.get('BlueprintPure', False) or
                    ufunction_specifiers.get('BlueprintImplementableEvent', False) or
                    ufunction_specifiers.get('BlueprintNativeEvent', False)
                )

                # 跳过纯虚函数声明
                if '= 0' in params or '= delete' in params:
                    ufunction_specifiers = {}
                    continue

                # 跳过明显不是函数的
                if not params and not return_type_clean:
                    ufunction_specifiers = {}
                    continue

                func_key = f"{func_name}_{i}"
                self.functions[func_key] = FunctionInfo(
                    name=func_name,
                    return_type=return_type_clean,
                    parameters=self._parse_parameters(params),
                    is_ufunction=bool(ufunction_specifiers),
                    is_static=is_static,
                    is_virtual=is_virtual,
                    is_const=is_const,
                    is_override=is_override,
                    is_blueprint_callable=is_blueprint_callable,
                    ufunction_specifiers=ufunction_specifiers if ufunction_specifiers else {},
                    file_path=file_path,
                    line_number=i
                )

                # 重置 UFUNCTION 解析结果
                ufunction_specifiers = {}

    def _parse_parameters(self, params_str: str) -> List[ParameterInfo]:
        """解析函数参数列表"""
        if not params_str or params_str.strip() == 'void':
            return []

        params = []
        for param in params_str.split(','):
            param = param.strip()
            if not param:
                continue

            # 匹配：类型 参数名 = 默认值
            match = re.match(r'^(.+?)\s+(\w+)(?:\s*=\s*(.*))?$', param)
            if match:
                param_type = match.group(1).strip()
                param_name = match.group(2)
                default_value = match.group(3).strip() if match.group(3) else None

                params.append(ParameterInfo(
                    type=param_type,
                    name=param_name,
                    default_value=default_value
                ))
            else:
                # 无法解析的参数
                params.append(ParameterInfo(
                    type='unknown',
                    name=param,
                    default_value=None
                ))

        return params

    def _parse_ufunction_specifiers(self, spec_str: str) -> Dict[str, Any]:
        """解析 UFUNCTION 宏参数"""
        specifiers = {}

        if not spec_str:
            return specifiers

        # 提取简单标志位
        flags = ['BlueprintCallable', 'BlueprintPure', 'BlueprintImplementableEvent',
                'BlueprintNativeEvent', 'Exec', 'Server', 'Client', 'NetMulticast',
                'Reliable', 'Unreliable', 'CallInEditor', 'BlueprintInternalUseOnly']

        for flag in flags:
            if flag in spec_str:
                specifiers[flag] = True

        # 提取 Category
        cat_match = re.search(r'Category\s*=\s*"([^"]*)"', spec_str)
        if cat_match:
            specifiers['Category'] = cat_match.group(1)

        # 提取 meta 参数
        meta_match = re.search(r'meta\s*=\s*\(([^)]+)\)', spec_str)
        if meta_match:
            meta_content = meta_match.group(1)
            specifiers['meta'] = {}
            for kv_match in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', meta_content):
                specifiers['meta'][kv_match.group(1)] = kv_match.group(2)

        return specifiers

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
        """获取类的继承链"""
        chain = [class_name]
        current = class_name

        while current in self.classes:
            parent = self.classes[current].parent_class
            if not parent:
                break
            chain.append(parent)
            current = parent

        return list(reversed(chain))

    def format_function_signature(self, func_info: FunctionInfo) -> str:
        """格式化函数签名为可读字符串"""
        params_str = ", ".join([
            f"{p.type} {p.name}" + (f" = {p.default_value}" if p.default_value else "")
            for p in func_info.parameters
        ])

        signature = f"{func_info.return_type} {func_info.name}({params_str})"

        if func_info.is_const:
            signature += " const"
        if func_info.is_override:
            signature += " override"

        return signature

    def extract_classes(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        提取代码中的所有类（供 Pipeline analyze 阶段使用）

        Args:
            content: C++ 代码内容
            file_path: 文件路径

        Returns:
            类信息字典列表
        """
        classes, _ = self.parse_content(content, file_path)
        return [info.to_dict() for info in classes.values()]

    def extract_functions(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        提取代码中的所有函数（供 Pipeline analyze 阶段使用）

        Args:
            content: C++ 代码内容
            file_path: 文件路径

        Returns:
            函数信息字典列表
        """
        _, functions = self.parse_content(content, file_path)
        return [info.to_dict() for info in functions.values()]

    def __repr__(self) -> str:
        return f"CppParser(classes={len(self.classes)}, functions={len(self.functions)})"
