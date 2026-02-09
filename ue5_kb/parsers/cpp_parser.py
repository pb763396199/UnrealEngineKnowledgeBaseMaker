"""
UE5 知识库系统 - C++ 代码解析器 (v2.14.0)

负责解析 C++ 源文件，提取类、函数、枚举、委托、类型别名等信息
增强版本 - 支持 UE5 代码风格，Doxygen 注释提取，UENUM/USTRUCT 说明符
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from typing import ForwardRef
else:
    List_PropertyInfo = 'List[PropertyInfo]'
    PropertyInfo = 'PropertyInfo'


@dataclass
class PropertyInfo:
    """属性信息"""
    name: str
    type: str
    is_uproperty: bool = False
    specifiers: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {'name': self.name, 'type': self.type, 'is_uproperty': self.is_uproperty}
        if self.specifiers:
            result['specifiers'] = self.specifiers
        return result


@dataclass
class ClassInfo:
    """类信息"""
    name: str
    is_uclass: bool = False
    is_struct: bool = False
    is_interface: bool = False
    parent_class: Optional[str] = None
    parent_classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    properties: List[PropertyInfo] = field(default_factory=list)
    file_path: str = ""
    line_number: int = 0
    namespace: str = ""
    doc_comment: str = ""
    specifiers: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'name': self.name, 'is_uclass': self.is_uclass, 'is_struct': self.is_struct,
            'is_interface': self.is_interface, 'parent_class': self.parent_class,
            'parent_classes': self.parent_classes, 'interfaces': self.interfaces,
            'methods': self.methods, 'properties': [p.to_dict() for p in self.properties],
            'file_path': self.file_path, 'line_number': self.line_number, 'namespace': self.namespace
        }
        if self.doc_comment:
            result['doc_comment'] = self.doc_comment
        if self.specifiers:
            result['specifiers'] = self.specifiers
        return result


@dataclass
class ParameterInfo:
    """函数参数信息"""
    type: str
    name: str
    default_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {'type': self.type, 'name': self.name, 'default': self.default_value}


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
    is_pure_virtual: bool = False
    is_blueprint_callable: bool = False
    ufunction_specifiers: Dict[str, Any] = field(default_factory=dict)
    class_name: Optional[str] = None
    file_path: str = ""
    line_number: int = 0
    impl_file_path: str = ""
    impl_line_number: int = 0
    impl_candidates: List[str] = field(default_factory=list)
    doc_comment: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'name': self.name, 'return_type': self.return_type,
            'parameters': [p.to_dict() for p in self.parameters],
            'is_ufunction': self.is_ufunction, 'is_static': self.is_static,
            'is_virtual': self.is_virtual, 'is_const': self.is_const,
            'is_override': self.is_override, 'is_pure_virtual': self.is_pure_virtual,
            'is_blueprint_callable': self.is_blueprint_callable,
            'ufunction_specifiers': self.ufunction_specifiers,
            'class_name': self.class_name, 'file_path': self.file_path,
            'line_number': self.line_number, 'impl_file_path': self.impl_file_path,
            'impl_line_number': self.impl_line_number, 'impl_candidates': self.impl_candidates
        }
        if self.doc_comment:
            result['doc_comment'] = self.doc_comment
        return result


@dataclass
class EnumInfo:
    """枚举信息"""
    name: str
    values: List[str] = field(default_factory=list)
    is_uenum: bool = False
    namespace: str = ""
    file_path: str = ""
    line_number: int = 0
    doc_comment: str = ""
    specifiers: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'name': self.name, 'values': self.values, 'is_uenum': self.is_uenum,
            'namespace': self.namespace, 'file_path': self.file_path, 'line_number': self.line_number
        }
        if self.doc_comment:
            result['doc_comment'] = self.doc_comment
        if self.specifiers:
            result['specifiers'] = self.specifiers
        return result


@dataclass
class DelegateInfo:
    """委托信息"""
    name: str
    type: str = ""
    params: List[str] = field(default_factory=list)
    file_path: str = ""
    line_number: int = 0
    doc_comment: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name, 'type': self.type, 'params': self.params,
            'file_path': self.file_path, 'line_number': self.line_number,
            'doc_comment': self.doc_comment
        }


@dataclass
class TypeAliasInfo:
    """类型别名信息"""
    name: str
    underlying_type: str = ""
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name, 'underlying_type': self.underlying_type,
            'file_path': self.file_path, 'line_number': self.line_number
        }


class CppParser:
    """
    C++ 代码解析器 (v2.14.0 增强版)

    提取: 类(UCLASS), 结构体(USTRUCT), 函数(UFUNCTION), 枚举(UENUM),
    委托(DECLARE_DELEGATE_*), 类型别名(typedef/using), 继承关系,
    Doxygen注释, UPROPERTY说明符
    """

    UCLASS_PATTERN = r'UCLASS\s*\(([^)]*)\)'
    USTRUCT_PATTERN = r'USTRUCT\s*\(([^)]*)\)'
    UFUNCTION_PATTERN = r'UFUNCTION\s*\(([^)]*)\)'
    UPROPERTY_PATTERN = r'UPROPERTY\s*\(([^)]*)\)'
    UINTERFACE_PATTERN = r'UINTERFACE\s*\(([^)]*)\)'
    UENUM_PATTERN = r'UENUM\s*\(([^)]*)\)'

    DELEGATE_PATTERN = re.compile(
        r'DECLARE_(DYNAMIC_)?(MULTICAST_)?DELEGATE'
        r'(?:_(?:RetVal_)?(?:OneParam|TwoParams|ThreeParams|FourParams|'
        r'FiveParams|SixParams|SevenParams|EightParams|NineParams))?'
        r'\s*\(\s*(\w+)(?:\s*,\s*(.+?))?\s*\)'
    )

    def __init__(self):
        self.classes: Dict[str, ClassInfo] = {}
        self.functions: Dict[str, FunctionInfo] = {}
        self.enums: Dict[str, EnumInfo] = {}
        self.delegates: Dict[str, DelegateInfo] = {}
        self.type_aliases: Dict[str, TypeAliasInfo] = {}

    def parse_file(self, file_path: str) -> Tuple[Dict[str, ClassInfo], Dict[str, FunctionInfo], Dict[str, EnumInfo]]:
        if not os.path.exists(file_path):
            return {}, {}, {}
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return {}, {}, {}
        return self.parse_content(content, file_path)

    def parse_content(
        self, content: str, file_path: str = ""
    ) -> Tuple[Dict[str, ClassInfo], Dict[str, FunctionInfo], Dict[str, EnumInfo]]:
        try:
            self.classes = {}
            self.functions = {}
            self.enums = {}
            self.delegates = {}
            self.type_aliases = {}

            doxygen_map = self._extract_doxygen_map(content)
            content_lines = self._preprocess_content_lines(content)
            self._parse_classes_and_structs(content_lines, file_path, doxygen_map)
            self._parse_enums(content_lines, file_path, doxygen_map)
            self._parse_delegates(content_lines, file_path, doxygen_map)
            self._parse_type_aliases(content_lines, file_path)
            content_flat = '\n'.join(content_lines)
            self._parse_functions(content_flat, file_path, doxygen_map)

            return self.classes, self.functions, self.enums
        except Exception as e:
            file_name = Path(file_path).name if file_path else "unknown"
            print(f"    [错误] 解析失败 {file_name}: {e}")
            return {}, {}, {}

    # =========================================================================
    # 预处理
    # =========================================================================

    def _extract_doxygen_map(self, content: str) -> Dict[int, str]:
        """提取 Doxygen 注释 => {下一行行号(1-based): 注释文本}"""
        doc_map: Dict[int, str] = {}
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('///'):
                comment_lines = []
                while i < len(lines) and lines[i].strip().startswith('///'):
                    text = lines[i].strip()[3:].strip()
                    if text:
                        comment_lines.append(text)
                    i += 1
                if comment_lines:
                    doc_map[i + 1] = ' '.join(comment_lines)
                continue
            if line.startswith('/**'):
                comment_lines = []
                if '*/' in line:
                    text = line[3:]
                    idx = text.find('*/')
                    if idx != -1:
                        text = text[:idx]
                    text = text.strip()
                    if text:
                        comment_lines.append(text)
                    doc_map[i + 2] = ' '.join(comment_lines) if comment_lines else ''
                    i += 1
                    continue
                else:
                    first_text = line[3:].strip()
                    if first_text:
                        comment_lines.append(first_text)
                    i += 1
                    while i < len(lines):
                        cline = lines[i].strip()
                        if '*/' in cline:
                            text = cline.replace('*/', '').strip()
                            if text.startswith('*'):
                                text = text[1:].strip()
                            if text:
                                comment_lines.append(text)
                            doc_map[i + 2] = ' '.join(comment_lines) if comment_lines else ''
                            i += 1
                            break
                        else:
                            text = cline
                            if text.startswith('*'):
                                text = text[1:].strip()
                            if text:
                                comment_lines.append(text)
                        i += 1
                    continue
            i += 1
        return doc_map

    def _preprocess_content_lines(self, content: str) -> List[str]:
        """预处理代码，正确处理跨行多行注释 (v2.14.0 修复)"""
        lines = content.split('\n')
        processed = []
        in_block = False
        for line in lines:
            if in_block:
                end_idx = line.find('*/')
                if end_idx != -1:
                    in_block = False
                    line = line[end_idx + 2:]
                else:
                    processed.append('')
                    continue
            result = ''
            idx = 0
            while idx < len(line):
                if line[idx:idx + 2] == '//':
                    break
                elif line[idx:idx + 2] == '/*':
                    end_idx = line.find('*/', idx + 2)
                    if end_idx != -1:
                        idx = end_idx + 2
                    else:
                        in_block = True
                        break
                else:
                    result += line[idx]
                    idx += 1
            result = re.sub(r'[ \t]+', ' ', result)
            processed.append(result.rstrip())
        return processed

    def _preprocess_content(self, content: str) -> str:
        """预处理（保留向后兼容）"""
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'\s+', ' ', content)
        return content.strip()

    # =========================================================================
    # 说明符解析
    # =========================================================================

    def _parse_uclass_specifiers(self, spec_str: str) -> Dict[str, Any]:
        specifiers: Dict[str, Any] = {}
        if not spec_str:
            return specifiers
        for flag in ['Blueprintable', 'NotBlueprintable', 'BlueprintType', 'Abstract',
                     'MinimalAPI', 'Transient', 'NonTransient', 'Config', 'DefaultConfig',
                     'EditInlineNew', 'NotEditInlineNew', 'HideDropdown', 'Deprecated']:
            if flag in spec_str:
                specifiers[flag] = True
        cat = re.search(r'Category\s*=\s*"([^"]*)"', spec_str)
        if cat:
            specifiers['Category'] = cat.group(1)
        meta = re.search(r'meta\s*=\s*\(([^)]+)\)', spec_str)
        if meta:
            specifiers['meta'] = {}
            for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', meta.group(1)):
                specifiers['meta'][kv.group(1)] = kv.group(2)
        return specifiers

    def _parse_uproperty_specifiers(self, spec_str: str) -> Dict[str, Any]:
        specifiers: Dict[str, Any] = {}
        if not spec_str:
            return specifiers
        for flag in ['EditAnywhere', 'EditDefaultsOnly', 'EditInstanceOnly',
                     'VisibleAnywhere', 'VisibleDefaultsOnly', 'VisibleInstanceOnly',
                     'BlueprintReadWrite', 'BlueprintReadOnly', 'BlueprintAssignable',
                     'Replicated', 'ReplicatedUsing', 'NotReplicated',
                     'Transient', 'DuplicateTransient', 'SaveGame',
                     'AdvancedDisplay', 'Config', 'GlobalConfig',
                     'Interp', 'NoClear', 'Export', 'EditFixedSize', 'Instanced']:
            if flag in spec_str:
                specifiers[flag] = True
        cat = re.search(r'Category\s*=\s*"([^"]*)"', spec_str)
        if not cat:
            cat = re.search(r'Category\s*=\s*(\w+)', spec_str)
        if cat:
            specifiers['Category'] = cat.group(1)
        meta = re.search(r'meta\s*=\s*\(([^)]+)\)', spec_str)
        if meta:
            specifiers['meta'] = {}
            for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', meta.group(1)):
                specifiers['meta'][kv.group(1)] = kv.group(2)
        return specifiers

    def _parse_ufunction_specifiers(self, spec_str: str) -> Dict[str, Any]:
        specifiers: Dict[str, Any] = {}
        if not spec_str:
            return specifiers
        for flag in ['BlueprintCallable', 'BlueprintPure', 'BlueprintImplementableEvent',
                     'BlueprintNativeEvent', 'Exec', 'Server', 'Client', 'NetMulticast',
                     'Reliable', 'Unreliable', 'CallInEditor', 'BlueprintInternalUseOnly',
                     'BlueprintAuthorityOnly', 'WithValidation']:
            if flag in spec_str:
                specifiers[flag] = True
        cat = re.search(r'Category\s*=\s*"([^"]*)"', spec_str)
        if cat:
            specifiers['Category'] = cat.group(1)
        meta = re.search(r'meta\s*=\s*\(([^)]+)\)', spec_str)
        if meta:
            specifiers['meta'] = {}
            for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', meta.group(1)):
                specifiers['meta'][kv.group(1)] = kv.group(2)
        return specifiers

    # =========================================================================
    # 类和结构体解析
    # =========================================================================

    def _parse_classes_and_structs(self, lines: List[str], file_path: str, doxygen_map: Dict[int, str] = None) -> None:
        doxygen_map = doxygen_map or {}
        namespace_stack: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            ns_match = re.search(r'namespace\s+([A-Za-z_][A-Za-z0-9_:]*)\s*\{', line)
            if ns_match:
                ns_name = ns_match.group(1)
                namespace_stack.extend(ns_name.split('::')) if '::' in ns_name else namespace_stack.append(ns_name)
            if line == '}' and (i + 1 >= len(lines) or 'namespace' not in lines[i + 1]):
                if namespace_stack:
                    namespace_stack.pop()
            current_ns = '::'.join(namespace_stack) if namespace_stack else ""

            uclass_m = re.search(self.UCLASS_PATTERN, line)
            ustruct_m = re.search(self.USTRUCT_PATTERN, line)
            uiface_m = re.search(self.UINTERFACE_PATTERN, line)
            is_uclass = bool(uclass_m)
            is_ustruct = bool(ustruct_m)
            is_uiface = bool(uiface_m)
            spec_str = (uclass_m or ustruct_m or uiface_m)
            spec_str = spec_str.group(1) if spec_str else ''

            class_m = re.search(r'\b(class|struct)\s+((?:[A-Z_]+_API\s+)?[A-Z][A-Za-z0-9_]*)(?:\s*:\s*(.*))?', line)
            if class_m:
                decl_type = class_m.group(1)
                full_name = class_m.group(2).strip()
                inherit = class_m.group(3).strip() if class_m.group(3) else ""
                class_name = full_name.split()[-1] if ' ' in full_name else full_name

                parent_classes, interfaces = [], []
                if inherit:
                    for p in re.split(r',', inherit):
                        pc = re.sub(r'\b(public|private|protected)\s+', '', p).strip()
                        if pc and pc not in ['public', 'private', 'protected']:
                            parent_classes.append(pc)
                            if len(pc) > 1 and pc[0] == 'I' and pc[1].isupper():
                                interfaces.append(pc)

                parent_class = None
                for pc in parent_classes:
                    if not (len(pc) > 1 and pc[0] == 'I' and pc[1].isupper()):
                        parent_class = pc
                        break
                if parent_class is None and parent_classes:
                    parent_class = parent_classes[0]

                is_struct_f = decl_type == 'struct'
                is_uclass_f = is_ustruct if is_struct_f else is_uclass
                parsed_spec = self._parse_uclass_specifiers(spec_str)
                doc = doxygen_map.get(i + 1, '') or doxygen_map.get(i, '') or doxygen_map.get(i - 1, '')

                if class_name not in self.classes:
                    self.classes[class_name] = ClassInfo(
                        name=class_name, parent_class=parent_class, parent_classes=parent_classes,
                        interfaces=interfaces, is_uclass=is_uclass_f, is_struct=is_struct_f,
                        is_interface=is_uiface, namespace=current_ns, file_path=file_path,
                        line_number=i + 1, doc_comment=doc, specifiers=parsed_spec
                    )
                else:
                    info = self.classes[class_name]
                    if is_uclass_f: info.is_uclass = True
                    if is_struct_f: info.is_struct = True
                    if is_uiface: info.is_interface = True
                    if parent_class and not info.parent_class: info.parent_class = parent_class
                    if parent_classes and not info.parent_classes: info.parent_classes = parent_classes
                    if interfaces and not info.interfaces: info.interfaces = interfaces
                    if current_ns and not info.namespace: info.namespace = current_ns
                    if doc and not info.doc_comment: info.doc_comment = doc
                    if parsed_spec and not info.specifiers: info.specifiers = parsed_spec

                self._parse_class_body(lines, i + 1, class_name, file_path, doxygen_map)
            i += 1

    def _parse_class_body(self, lines: List[str], start_line: int, class_name: str,
                          file_path: str, doxygen_map: Dict[int, str] = None) -> int:
        doxygen_map = doxygen_map or {}
        if start_line >= len(lines):
            return len(lines) - 1 if lines else 0
        brace_count = 1
        uprop_pending = False
        uprop_spec = ''
        for i in range(start_line, len(lines)):
            line = lines[i].strip()
            if '{' in line:
                brace_count += line.count('{')
                if brace_count > 100:
                    return i
            if '}' in line:
                brace_count -= line.count('}')
                if brace_count <= 0:
                    return i

            uprop_m = re.search(self.UPROPERTY_PATTERN, line)
            if uprop_m:
                uprop_pending = True
                uprop_spec = uprop_m.group(1)
                if ';' in line:
                    prop = self._try_parse_property(line, True, uprop_spec)
                    if prop and class_name in self.classes:
                        self.classes[class_name].properties.append(prop)
                    uprop_pending = False
                    uprop_spec = ''
                continue

            if ';' in line and not any(kw in line for kw in ['class', 'struct', 'enum', 'typedef', 'friend']):
                prop = self._try_parse_property(line, uprop_pending, uprop_spec)
                if prop and class_name in self.classes:
                    self.classes[class_name].properties.append(prop)
                uprop_pending = False
                uprop_spec = ''

            method = self._try_parse_method(line, class_name)
            if method and class_name in self.classes:
                self.classes[class_name].methods.append(method)
        return len(lines) - 1

    def _try_parse_property(self, line: str, has_uprop: bool, spec_str: str = '') -> Optional[PropertyInfo]:
        line = re.sub(self.UPROPERTY_PATTERN, '', line).strip()
        if '(' in line and ')' in line:
            return None
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_:<>*&\s]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*[^;]*)?\s*;', line)
        if m:
            ptype, pname = m.group(1).strip(), m.group(2)
            if pname in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'operator']:
                return None
            specs = self._parse_uproperty_specifiers(spec_str) if has_uprop else {}
            return PropertyInfo(name=pname, type=ptype, is_uproperty=has_uprop, specifiers=specs)
        return None

    def _try_parse_method(self, line: str, class_name: str) -> Optional[str]:
        if ';' not in line:
            return None
        m = re.match(
            r'^([A-Za-z_][A-Za-z0-9_<>*&:\s]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*'
            r'\(([^)]*)\)\s*(?:const)?\s*(?:override|final)?\s*(?:=\s*0\s*)?;', line
        )
        if m:
            rt, mn, params = m.group(1).strip(), m.group(2), m.group(3)
            if mn in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum']:
                return None
            if '= delete' in line:
                return None
            sig = f"{rt} {mn}({params})"
            if '= 0' in line:
                sig += " = 0"
            return sig
        return None

    # =========================================================================
    # 枚举解析
    # =========================================================================

    def _parse_enums(self, lines: List[str], file_path: str, doxygen_map: Dict[int, str] = None) -> None:
        doxygen_map = doxygen_map or {}
        ns_stack: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            ns_m = re.search(r'namespace\s+([A-Za-z_][A-Za-z0-9_:]*)\s*\{', line)
            if ns_m:
                ns = ns_m.group(1)
                ns_stack.extend(ns.split('::')) if '::' in ns else ns_stack.append(ns)
            if line == '}' and ns_stack:
                ns_stack.pop()
            cur_ns = '::'.join(ns_stack) if ns_stack else ""

            uenum_m = re.search(self.UENUM_PATTERN, line)
            is_uenum = bool(uenum_m)
            uenum_spec = uenum_m.group(1) if uenum_m else ''

            enum_m = re.search(r'\benum\s+(?:class\s+)?([A-Z][A-Za-z0-9_]*)(?:\s*:\s*\w+)?\s*(?:\{)?', line)
            if not enum_m and is_uenum and i + 1 < len(lines):
                enum_m = re.search(
                    r'\benum\s+(?:class\s+)?([A-Z][A-Za-z0-9_]*)(?:\s*:\s*\w+)?\s*(?:\{)?', lines[i + 1].strip()
                )
                if enum_m:
                    i += 1

            if enum_m:
                ename = enum_m.group(1)
                doc = doxygen_map.get(i + 1, '') or doxygen_map.get(i, '')
                vals = self._extract_enum_values(lines, i)
                specs = self._parse_uclass_specifiers(uenum_spec) if uenum_spec else {}
                self.enums[ename] = EnumInfo(
                    name=ename, values=vals, is_uenum=is_uenum, namespace=cur_ns,
                    file_path=file_path, line_number=i + 1, doc_comment=doc, specifiers=specs
                )
            i += 1

    def _extract_enum_values(self, lines: List[str], start: int) -> List[str]:
        values = []
        brace = False
        for i in range(start, min(start + 200, len(lines))):
            line = lines[i].strip()
            if '{' in line:
                brace = True
                after = line[line.index('{') + 1:]
                if after.strip():
                    self._parse_enum_line(after, values)
            elif brace:
                if '}' in line:
                    before = line[:line.index('}')]
                    if before.strip():
                        self._parse_enum_line(before, values)
                    break
                elif line and not line.startswith('#'):
                    self._parse_enum_line(line, values)
        return values

    def _parse_enum_line(self, line: str, values: List[str]) -> None:
        line = re.sub(r'//.*$', '', line).strip()
        if not line:
            return
        for part in line.split(','):
            part = part.strip()
            if not part:
                continue
            name = part.split('=')[0].strip()
            name = re.sub(r'UMETA\s*\([^)]*\)', '', name).strip()
            if name and re.match(r'^[A-Za-z_]\w*$', name):
                values.append(name)

    # =========================================================================
    # 委托解析
    # =========================================================================

    def _parse_delegates(self, lines: List[str], file_path: str, doxygen_map: Dict[int, str] = None) -> None:
        doxygen_map = doxygen_map or {}
        for i, line in enumerate(lines):
            ls = line.strip()
            if not ls.startswith('DECLARE_'):
                continue
            full = ls
            if '(' in full and ')' not in full:
                for j in range(i + 1, min(i + 5, len(lines))):
                    full += ' ' + lines[j].strip()
                    if ')' in full:
                        break
            m = self.DELEGATE_PATTERN.search(full)
            if m:
                is_dyn, is_mc = bool(m.group(1)), bool(m.group(2))
                dname = m.group(3)
                pstr = m.group(4) or ''
                if is_dyn and is_mc:
                    dt = 'dynamic_multicast'
                elif is_dyn:
                    dt = 'dynamic'
                elif is_mc:
                    dt = 'multicast'
                else:
                    dt = 'single'
                params = [p.strip() for p in pstr.split(',') if p.strip()] if pstr else []
                doc = doxygen_map.get(i + 1, '')
                self.delegates[dname] = DelegateInfo(
                    name=dname, type=dt, params=params,
                    file_path=file_path, line_number=i + 1, doc_comment=doc
                )

    # =========================================================================
    # 类型别名解析
    # =========================================================================

    def _parse_type_aliases(self, lines: List[str], file_path: str) -> None:
        for i, line in enumerate(lines):
            ls = line.strip()
            m = re.match(r'using\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*;', ls)
            if m:
                name, underlying = m.group(1), m.group(2).strip()
                if underlying and not underlying.startswith('namespace'):
                    self.type_aliases[name] = TypeAliasInfo(
                        name=name, underlying_type=underlying, file_path=file_path, line_number=i + 1
                    )
                continue
            m = re.match(r'typedef\s+(.+?)\s+([A-Za-z_]\w*)\s*;', ls)
            if m:
                underlying, name = m.group(1).strip(), m.group(2)
                self.type_aliases[name] = TypeAliasInfo(
                    name=name, underlying_type=underlying, file_path=file_path, line_number=i + 1
                )

    # =========================================================================
    # 函数解析
    # =========================================================================

    def _parse_functions(self, content: str, file_path: str, doxygen_map: Dict[int, str] = None) -> None:
        doxygen_map = doxygen_map or {}
        lines = content.split('\n')
        uf_specs: Dict[str, Any] = {}

        for i, line in enumerate(lines, 1):
            ls = line.strip()
            uf_m = re.search(self.UFUNCTION_PATTERN, ls)
            if uf_m:
                uf_specs = self._parse_ufunction_specifiers(uf_m.group(1))
                continue
            if not ls or ls.startswith('//'):
                continue
            fw = ls.split()[0] if ls.split() else ''
            if fw in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'namespace']:
                continue

            is_pv = '= 0' in ls
            co_part = ''
            wl = ls
            if ' const' in wl:
                co_part = ' const'
                wl = wl.replace(' const', '', 1)
            if ' override' in wl:
                co_part += ' override'
                wl = wl.replace(' override', '', 1)
            if ' final' in wl:
                co_part += ' final'
                wl = wl.replace(' final', '', 1)
            wl = re.sub(r'\s*=\s*0\s*', '', wl)

            fm = re.match(r'^([A-Za-z_][A-Za-z0-9_<>*&:\s]*?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*;?$', wl.strip())
            if fm:
                rt, fn, params = fm.group(1).strip(), fm.group(2), fm.group(3)
                if fn in ['if', 'for', 'while', 'switch', 'return', 'class', 'struct', 'enum', 'namespace', 'operator']:
                    continue
                if '= delete' in ls:
                    uf_specs = {}
                    continue
                if not params and not rt:
                    uf_specs = {}
                    continue

                is_virt = 'virtual' in rt
                is_stat = 'static' in rt
                is_const = ' const' in co_part
                is_over = ' override' in co_part
                rt_clean = rt.replace('virtual', '').replace('static', '').strip()
                is_bp = (uf_specs.get('BlueprintCallable', False) or uf_specs.get('BlueprintPure', False)
                         or uf_specs.get('BlueprintImplementableEvent', False)
                         or uf_specs.get('BlueprintNativeEvent', False))
                doc = doxygen_map.get(i, '')

                self.functions[f"{fn}_{i}"] = FunctionInfo(
                    name=fn, return_type=rt_clean, parameters=self._parse_parameters(params),
                    is_ufunction=bool(uf_specs), is_static=is_stat, is_virtual=is_virt,
                    is_const=is_const, is_override=is_over, is_pure_virtual=is_pv,
                    is_blueprint_callable=is_bp, ufunction_specifiers=uf_specs.copy() if uf_specs else {},
                    file_path=file_path, line_number=i, doc_comment=doc
                )
                uf_specs = {}

    def _parse_parameters(self, params_str: str) -> List[ParameterInfo]:
        if not params_str or params_str.strip() == 'void':
            return []
        params = []
        for part in self._split_params(params_str):
            part = part.strip()
            if not part:
                continue
            m = re.match(r'^(.+?)\s+(\w+)(?:\s*=\s*(.*))?$', part)
            if m:
                params.append(ParameterInfo(
                    type=m.group(1).strip(), name=m.group(2),
                    default_value=m.group(3).strip() if m.group(3) else None
                ))
            else:
                params.append(ParameterInfo(type='unknown', name=part, default_value=None))
        return params

    def _split_params(self, params_str: str) -> List[str]:
        """按逗号分割参数，忽略模板 <> 内的逗号"""
        parts, depth, cur = [], 0, ''
        for ch in params_str:
            if ch == '<':
                depth += 1
                cur += ch
            elif ch == '>':
                depth -= 1
                cur += ch
            elif ch == ',' and depth == 0:
                parts.append(cur)
                cur = ''
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        return parts

    # =========================================================================
    # 公共辅助方法
    # =========================================================================

    def _parse_namespace_stack(self, content: str) -> List[str]:
        ns = []
        for line in content.split('\n'):
            line = line.strip()
            m = re.search(r'namespace\s+([A-Za-z_][A-Za-z0-9_:]*)\s*\{', line)
            if m:
                n = m.group(1)
                ns.extend(n.split('::')) if '::' in n else ns.append(n)
                continue
            if line == '}' and ns:
                ns.pop()
        return ns

    def _build_namespace_path(self, namespace_stack: List[str]) -> str:
        return '::'.join(namespace_stack) if namespace_stack else ""

    def get_classes(self) -> Dict[str, ClassInfo]:
        return self.classes

    def get_functions(self) -> Dict[str, FunctionInfo]:
        return self.functions

    def get_enums(self) -> Dict[str, EnumInfo]:
        return self.enums

    def get_delegates(self) -> Dict[str, DelegateInfo]:
        return self.delegates

    def get_type_aliases(self) -> Dict[str, TypeAliasInfo]:
        return self.type_aliases

    def get_uclasses(self) -> List[str]:
        return [n for n, i in self.classes.items() if i.is_uclass]

    def get_inheritance_chain(self, class_name: str) -> List[str]:
        chain = [class_name]
        cur = class_name
        while cur in self.classes:
            p = self.classes[cur].parent_class
            if not p:
                break
            chain.append(p)
            cur = p
        return list(reversed(chain))

    def format_function_signature(self, func_info: FunctionInfo) -> str:
        ps = ", ".join([
            f"{p.type} {p.name}" + (f" = {p.default_value}" if p.default_value else "")
            for p in func_info.parameters
        ])
        sig = f"{func_info.return_type} {func_info.name}({ps})"
        if func_info.is_const:
            sig += " const"
        if func_info.is_override:
            sig += " override"
        if func_info.is_pure_virtual:
            sig += " = 0"
        return sig

    def extract_classes(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        classes, _, _ = self.parse_content(content, file_path)
        return [i.to_dict() for i in classes.values()]

    def extract_functions(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        _, functions, _ = self.parse_content(content, file_path)
        return [i.to_dict() for i in functions.values()]

    def extract_enums(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        _, _, enums = self.parse_content(content, file_path)
        return [i.to_dict() for i in enums.values()]

    def __repr__(self) -> str:
        return (f"CppParser(classes={len(self.classes)}, functions={len(self.functions)}, "
                f"enums={len(self.enums)}, delegates={len(self.delegates)}, "
                f"type_aliases={len(self.type_aliases)})")
