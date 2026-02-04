# Change: Enhance C++ Parser to Fill Empty module_graphs Fields

## ID
enhance-cpp-parser

## Status
IMPLEMENTED

## Created
2026-02-04

## Why

当前工具生成的 `module_graphs` pickle 文件包含不完整的数据：
- `ClassInfo.interfaces` - 多重继承的接口始终为空
- `ClassInfo.methods` - 类成员函数未关联到类（始终为空）
- `ClassInfo.properties` - UPROPERTY 声明未解析（始终为空）
- `ClassInfo.namespace` - 命名空间未检测（始终为空）
- `functions` 虽然被解析但由于键格式问题导致查询困难

这导致生成的知识库无法提供完整的类结构信息，影响代码查询和理解的准确性。

## What Changes

### 1. 新增 PropertyInfo 数据类
文件: `ue5_kb/parsers/cpp_parser.py`
- 添加 `PropertyInfo` dataclass，包含 name, type, is_uproperty 字段
- 更新 `ClassInfo.properties` 类型从 `List[str]` 改为 `List[PropertyInfo]`

### 2. 增强类解析 (_parse_classes_and_structs)
文件: `ue5_kb/parsers/cpp_parser.py` (第 178-252 行)
- 更新正则表达式以捕获 `:` 后的完整继承列表
- 解析逗号分隔的多个父类：`class A : public B, public IInterface, public IOther`
- 区分主父类和接口（I 开头的类名）
- 填充 `ClassInfo.interfaces` 列表
- 添加 `parent_classes` 字段存储完整继承列表

### 3. 添加命名空间检测
文件: `ue5_kb/parsers/cpp_parser.py` (新增 _parse_namespace 方法)
- 使用栈结构跟踪 namespace 块
- 支持嵌套命名空间：`namespace UE { namespace Core { class Log {} } }`
- 支持简化语法：`namespace UE::Core { class Log {} }`
- 记录完整路径如 `"UE::Core"` 到 `ClassInfo.namespace`

### 4. 添加属性解析
文件: `ue5_kb/parsers/cpp_parser.py` (新增 _parse_properties 方法)
- 基础解析：只检测是否为 UPROPERTY
- 解析属性声明：`int32 MyProperty;`
- 处理 UE5 类型：`TArray<FString>`, `TMap<int, AActor*>` 等
- 不解析详细的 UPROPERTY 说明符（EditAnywhere 等）

### 5. 块级解析关联函数到类
文件: `ue5_kb/parsers/cpp_parser.py` (修改 _parse_classes_and_structs 和 _parse_functions)
- 解析到类定义后，继续解析类体内的所有内容直到匹配的 `};`
- 检测方法声明并关联到当前类
- 设置 `FunctionInfo.class_name` 为当前类名
- 将关联的方法签名添加到 `ClassInfo.methods` 列表

### 6. 更新 BuildStage
文件: `ue5_kb/pipeline/build.py` (第 311-385 行)
- 更新 `_create_networkx_graph` 处理新的数据结构
- 支持 `parent_classes` 列表
- 处理属性对象数据

## Impact

### Affected specs
- `specs/core/parsers/cpp-parser-spec.md` - C++ 解析器规范

### Affected code
- `ue5_kb/parsers/cpp_parser.py` - 主要修改
- `ue5_kb/pipeline/build.py` - 更新图构建逻辑
- `ue5_kb/pipeline/analyze.py` - 可能需要调整

### Backward compatibility
- 添加 `parent_classes` 字段（保留 `parent_class` 向后兼容）
- `properties` 从 `List[str]` 改为 `List[PropertyInfo]`（破坏性变更）
- 旧版 pickle 文件需要重新生成

### Performance impact
- 块级解析可能增加解析时间（需要处理类体内内容）
- 预计整体解析时间增加 10-20%

## Testing Plan

### 单元测试
- 测试多重继承解析
- 测试命名空间检测
- 测试属性解析
- 测试函数关联到类

### 集成测试
使用 `D:\Unreal Engine\UnrealEngine51_500` 引擎运行：
```bash
ue5kb init --engine-path "D:\Unreal Engine\UnrealEngine51_500" --module Core
```

验证输出：
- `classes[].interfaces` 非空
- `classes[].methods` 非空
- `classes[].properties` 非空
- `classes[].namespace` 非空

## References
- 计划文件: `C:\Users\pb763\.claude\plans\rosy-petting-lynx.md`
- CLAUDE.md: 项目开发指导
