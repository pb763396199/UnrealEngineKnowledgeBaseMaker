"""
UE5 知识库系统 - C++ 代码解析器

负责解析 C++ 源文件，提取类、函数、继承关系等信息
优化版本 - 支持 UE5 代码风格
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

# 使用 TYPE_CHECKING 来避免循环引用问题
if TYPE_CHECKING:
    from typing import ForwardRef
else:
    # 运行时使用字符串类型注解
    List_PropertyInfo = 'List[PropertyInfo]'
    PropertyInfo = 'PropertyInfo'


@dataclass
class PropertyInfo:
    """属性信息（基础版本）"""
    name: str
    type: str
    is_uproperty: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'type': self.type,
            'is_uproperty': self.is_uproperty
        }


@dataclass
class ClassInfo:
    """类信息"""
    name: str
    is_uclass: bool = False
    is_struct: bool = False
    is_interface: bool = False
    parent_class: Optional[str] = None
    parent_classes: List[str] = field(default_factory=list)  # 完整继承列表
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    properties: List[PropertyInfo] = field(default_factory=list)  # 使用 PropertyInfo 类型
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
            'parent_classes': self.parent_classes,
            'interfaces': self.interfaces,
            'methods': self.methods,
            'properties': [p.to_dict() for p in self.properties],
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
        try:
            self.classes = {}
            self.functions = {}

            # 预处理代码（保持行结构用于类体解析）
            content_lines = self._preprocess_content_lines(content)

            # 解析类和结构体
            self._parse_classes_and_structs(content_lines, file_path)

            # 同时使用压缩版本用于函数解析（向后兼容）
            content_flat = '\n'.join(content_lines)
            self._parse_functions(content_flat, file_path)

            return self.classes, self.functions
        except Exception as e:
            # 捕获解析异常，避免整个文件解析失败
            from pathlib import Path
            file_name = Path(file_path).name if file_path else "unknown"
            print(f"    [错误] 解析失败 {file_name}: {e}")
            return {}, {}

    def _preprocess_content_lines(self, content: str) -> List[str]:
        """
        预处理代码内容，返回行列表（保持行结构用于类体解析）

        Returns:
            预处理后的代码行列表
        """
        # 移除单行注释（保持行）
        lines = content.split('\n')
        processed_lines = []

        for line in lines:
            # 移除行内注释
            line = re.sub(r'//.*$', '', line)
            # 移除多行注释标记（简化处理）
            line = re.sub(r'/\*.*?\*/', '', line)
            # 标准化行内空白，但保留行结构
            line = re.sub(r'[ \t]+', ' ', line)
            processed_lines.append(line.rstrip())

        return processed_lines

    def _preprocess_content(self, content: str) -> str:
        """预处理代码内容（旧方法，用于函数解析）"""
        # 移除单行注释
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # 标准化空白
        content = re.sub(r'\s+', ' ', content)
        return content.strip()

    def _parse_namespace_stack(self, content: str) -> List[str]:
        """
        解析命名空间栈，跟踪当前命名空间上下文

        Returns:
            命名空间栈列表，每个元素是命名空间名称
        """
        namespace_stack = []
        lines = content.split('\n')

        for line in lines:
            line = line.strip()

            # 匹配 namespace 开始
            # 支持两种语法:
            # 1. namespace Name {
            # 2. namespace Name::Nested {
            ns_start_match = re.search(r'namespace\s+([A-Za-z_][A-Za-z0-9_:]*)\s*\{', line)
            if ns_start_match:
                ns_name = ns_start_match.group(1)
                # 处理嵌套命名空间语法如 "UE::Core"
                if '::' in ns_name:
                    parts = ns_name.split('::')
                    namespace_stack.extend(parts)
                else:
                    namespace_stack.append(ns_name)
                continue

            # 简单匹配 namespace 结束 (匹配单独的 } )
            # 注意：这是一种简化处理，可能无法处理所有复杂情况
            if line == '}':
                if namespace_stack:
                    namespace_stack.pop()

        return namespace_stack

    def _build_namespace_path(self, namespace_stack: List[str]) -> str:
        """从命名空间栈构建完整路径"""
        return '::'.join(namespace_stack) if namespace_stack else ""

    def _parse_classes_and_structs(self, lines: List[str], file_path: str) -> None:
        """
        解析类和结构体定义（增强版）

        支持:
        - 多重继承 (multiple inheritance)
        - 命名空间检测
        - 类体解析 (方法和属性)

        Args:
            lines: 预处理后的代码行列表
            file_path: 文件路径
        """
        # 跟踪命名空间栈
        namespace_stack = []

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 处理命名空间声明
            ns_start_match = re.search(r'namespace\s+([A-Za-z_][A-Za-z0-9_:]*)\s*\{', line)
            if ns_start_match:
                ns_name = ns_start_match.group(1)
                if '::' in ns_name:
                    namespace_stack.extend(ns_name.split('::'))
                else:
                    namespace_stack.append(ns_name)

            # 简单匹配 namespace 结束
            if line == '}' and (i + 1 >= len(lines) or 'namespace' not in lines[i + 1]):
                if namespace_stack:
                    namespace_stack.pop()

            # 构建当前命名空间路径
            current_namespace = self._build_namespace_path(namespace_stack)

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
            # - class UObject (无继承)

            # 更新正则以捕获所有父类，继承部分变为可选
            class_pattern = r'\b(class|struct)\s+((?:[A-Z_]+_API\s+)?[A-Z][A-Za-z0-9_]*)(?:\s*:\s*(.*))?'

            match = re.search(class_pattern, line)
            if match:
                decl_type = match.group(1)  # class or struct
                full_name = match.group(2).strip()
                inheritance_part = match.group(3).strip() if match.group(3) else ""

                # 清理 API 宏
                class_name = full_name.split()[-1] if ' ' in full_name else full_name

                # 解析继承列表
                parent_classes = []
                interfaces = []

                if inheritance_part:
                    # 移除可能的访问修饰符并分割逗号
                    parents = [p.strip() for p in re.split(r',', inheritance_part)]
                    for parent in parents:
                        # 移除 public/private/protected
                        parent_clean = re.sub(r'\b(public|private|protected)\s+', '', parent)
                        parent_clean = parent_clean.strip()
                        if parent_clean and parent_clean not in ['public', 'private', 'protected']:
                            # 过滤掉单独的访问修饰符
                            parent_classes.append(parent_clean)
                            # 检查是否是接口（I 开头的类名通常是接口）
                            if parent_clean.startswith('I') and parent_clean[1].isupper():
                                interfaces.append(parent_clean)

                # 确定主父类 (第一个非接口的父类)
                parent_class = None
                for pc in parent_classes:
                    if not pc.startswith('I') or not pc[1].isupper():
                        parent_class = pc
                        break

                # 如果没有非接口父类，使用第一个父类
                if parent_class is None and parent_classes:
                    parent_class = parent_classes[0]

                # 确定类型标志
                if decl_type == 'struct':
                    is_struct = True
                    is_uclass = is_ustruct
                else:
                    is_struct = False
                    is_uclass = is_uclass

                is_interface = is_uinterface

                # 创建或更新类信息
                if class_name not in self.classes:
                    self.classes[class_name] = ClassInfo(
                        name=class_name,
                        parent_class=parent_class,
                        parent_classes=parent_classes,
                        interfaces=interfaces,
                        is_uclass=is_uclass,
                        is_struct=is_struct,
                        is_interface=is_interface,
                        namespace=current_namespace,
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
                    if parent_classes and not info.parent_classes:
                        info.parent_classes = parent_classes
                    if interfaces and not info.interfaces:
                        info.interfaces = interfaces
                    if current_namespace and not info.namespace:
                        info.namespace = current_namespace

                # 解析类体内的内容（方法和属性）
                self._parse_class_body(lines, i + 1, class_name, file_path)

            i += 1

    def _parse_class_body(self, lines: List[str], start_line: int, class_name: str, file_path: str) -> int:
        """
        解析类体内容，提取方法和属性

        Args:
            lines: 所有代码行
            start_line: 类定义开始的下一行
            class_name: 当前类名
            file_path: 文件路径

        Returns:
            类体结束的行号
        """
        # 边界检查：防止索引越界
        if start_line >= len(lines):
            return len(lines) - 1 if lines else 0

        # 最大花括号深度限制（防止无限循环或过深嵌套）
        MAX_BRACE_DEPTH = 100

        # 假设类定义行已经包含开始大括号
        brace_count = 1
        found_opening_brace = True
        uproperty_pending = False  # 追踪 UPROPERTY 宏是否在上一行出现

        for i in range(start_line, len(lines)):
            line = lines[i].strip()

            # 检查花括号深度
            if '{' in line:
                brace_count += line.count('{')
                if brace_count > MAX_BRACE_DEPTH:
                    print(f"    [警告] 花括号嵌套过深 ({brace_count})，跳过类体解析: {class_name}")
                    return i

            # 查找结束大括号
            if '}' in line:
                brace_count -= line.count('}')
                if brace_count <= 0:
                    return i  # 类体结束

            # 检查是否有 UPROPERTY 宏
            has_uproperty = bool(re.search(self.UPROPERTY_PATTERN, line))
            if has_uproperty:
                uproperty_pending = True
                # 如果 UPROPERTY 和属性在同一行，直接解析
                if ';' in line:
                    prop = self._try_parse_property(line, True)
                    if prop and class_name in self.classes:
                        self.classes[class_name].properties.append(prop)
                    uproperty_pending = False
                continue

            # 尝试解析属性声明
            if ';' in line and not any(kw in line for kw in ['class', 'struct', 'enum', 'typedef', 'friend']):
                prop = self._try_parse_property(line, uproperty_pending)
                if prop and class_name in self.classes:
                    self.classes[class_name].properties.append(prop)
                uproperty_pending = False  # 重置标志

            # 尝试解析方法声明
            method = self._try_parse_method(line, class_name)
            if method and class_name in self.classes:
                self.classes[class_name].methods.append(method)

        return len(lines) - 1

    def _try_parse_property(self, line: str, has_uproperty: bool) -> Optional[PropertyInfo]:
        """尝试解析一行属性声明"""
        # 移除 UPROPERTY 宏（如果有）
        line = re.sub(self.UPROPERTY_PATTERN, '', line)
        line = line.strip()

        # 如果行包含 ( )，则可能是方法声明，跳过
        if '(' in line and ')' in line:
            return None

        # 基本属性声明模式: type name;
        # 支持复杂的 UE5 类型: TArray<FString>, TMap<K,V>, etc.
        prop_pattern = r'^([A-Za-z_][A-Za-z0-9_:<>*&\s]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;'

        match = re.match(prop_pattern, line)
        if match:
            prop_type = match.group(1).strip()
            prop_name = match.group(2)

            # 过滤掉关键字
            if prop_name in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'operator']:
                return None

            return PropertyInfo(
                name=prop_name,
                type=prop_type,
                is_uproperty=has_uproperty
            )

        return None

    def _try_parse_method(self, line: str, class_name: str) -> Optional[str]:
        """尝试解析一行方法声明，返回方法签名字符串"""
        # 跳过明显不是方法的行
        if ';' not in line or '=' in line:
            return None

        # 方法声明模式: return_type method_name(params);
        # 支持 const, override, final 等修饰符
        method_pattern = r'^([A-Za-z_][A-Za-z0-9_<>*&:\s]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*(?:const)?\s*(?:override|final)?\s*;'

        match = re.match(method_pattern, line)
        if match:
            return_type = match.group(1).strip()
            method_name = match.group(2)
            params = match.group(3)

            # 过滤掉关键字
            if method_name in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum']:
                return None

            # 过滤掉纯虚函数
            if '= 0' in params or '= delete' in line:
                return None

            # 构建方法签名
            return f"{return_type} {method_name}({params})"

        return None

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
