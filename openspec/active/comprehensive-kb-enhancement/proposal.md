# Change: Comprehensive Knowledge Base Enhancement for LLM Understanding

## ID
comprehensive-kb-enhancement

## Status
PENDING

## Created
2026-02-09

## Why

经过全面审计，当前知识库在帮助 LLM 理解虚幻引擎源码方面存在 14 项关键漏洞，按严重程度分为 P0/P1/P2/P3 四个优先级。

**核心问题**:
1. **信息丢失** — Doxygen 注释、枚举、宏、说明符等关键信息被丢弃
2. **覆盖不全** — 跳过 Private 目录 + 搜索硬编码限制导致覆盖率低
3. **查询接口缺失** — 已有能力（反向继承、反向依赖、代码示例）未暴露给 LLM

## What Changes

### Wave 1: 核心解析器增强 (cpp_parser.py)

#### 1.1 修复多行注释处理 Bug [P3]
- `_preprocess_content_lines()` 改为状态机模式，正确处理跨行 `/* ... */`
- 同时更新 `_preprocess_content()` 方法

#### 1.2 提取 Doxygen 注释 [P0]
- 新增 `_extract_doxygen_comments()` 方法
- 在预处理前先提取 `/** ... */` 注释，关联到紧随其后的类/函数
- 新增 `ClassInfo.doc_comment: str` 和 `FunctionInfo.doc_comment: str` 字段

#### 1.3 解析 UENUM / enum class [P1]
- 新增 `EnumInfo` dataclass: name, values, is_uenum, namespace, file_path, line_number, doc_comment
- 新增 `UENUM_PATTERN` 正则
- 新增 `_parse_enums()` 方法
- `parse_content()` 返回值扩展为 (classes, functions, enums)

#### 1.4 提取 UCLASS/UPROPERTY/USTRUCT 说明符 [P1]
- `ClassInfo` 新增 `specifiers: Dict[str, Any]` 字段（存储 Blueprintable, Abstract 等）
- `PropertyInfo` 新增 `specifiers: Dict[str, Any]` 字段（存储 EditAnywhere, BlueprintReadWrite 等）
- 新增 `_parse_uclass_specifiers()`, `_parse_uproperty_specifiers()` 方法
- 正确填充 `is_blueprintable` 字段

#### 1.5 解析 Delegate 宏 [P2]
- 新增 `DelegateInfo` dataclass: name, type(single/multicast/dynamic), params, doc_comment
- 新增 `_parse_delegates()` 方法
- 识别 DECLARE_DELEGATE_*, DECLARE_MULTICAST_DELEGATE_*, DECLARE_DYNAMIC_MULTICAST_DELEGATE_* 等宏

#### 1.6 解析 typedef/using 别名 [P2]
- 新增 `TypeAliasInfo` dataclass: name, underlying_type, file_path, line_number
- 新增 `_parse_type_aliases()` 方法

#### 1.7 保留纯虚函数声明 [P3]
- 移除 `= 0` 过滤逻辑
- `FunctionInfo` 新增 `is_pure_virtual: bool` 字段

### Wave 2: 构建器和索引增强

#### 2.1 停止跳过 Private 目录 [P0]
- `module_graph_builder.py`: 从排除列表中移除 'Private'
- `analyze.py` 的 `_find_source_files()`: 确保同时扫描 .h 和 .cpp

#### 2.2 构建 #include 依赖图 [P2]
- 新增 `_parse_includes()` 方法到 module_graph_builder
- 在图谱中添加 INCLUDES 关系边
- 记录每个文件的 #include 列表

#### 2.3 更新 ModuleGraph 支持新节点类型 [P1+P2]
- 已有 NODE_TYPE_ENUM, NODE_TYPE_MACRO, NODE_TYPE_DOCUMENTATION 常量
- 新增 NODE_TYPE_DELEGATE, NODE_TYPE_TYPEDEF 常量
- 构建器使用新的解析结果创建节点和关系

#### 2.4 更新 BuildStage 处理新数据结构 [ALL]
- `_create_networkx_graph()` 支持 enums, delegates, typedefs
- 支持 doc_comment 属性
- 支持 specifiers 属性

#### 2.5 更新 ClassIndex [P1]
- 新增 `specifiers TEXT` 列（JSON 序列化）
- 正确填充 `is_blueprintable` 字段
- 新增 `doc_comment TEXT` 列

#### 2.6 新增 EnumIndex [P1]
- 新建 `ue5_kb/core/enum_index.py`
- SQLite 表: enum_index (name, module, values, is_uenum, namespace, file_path, line_number, doc_comment)
- 支持按名称查询和模糊搜索

### Wave 3: 查询接口增强 (templates)

#### 3.1 移除搜索限制 [P0]
- `query_function_info`: 使用 FunctionIndex SQLite 查询替代遍历前 50 模块
- `_find_module_for_class`: 使用 ClassIndex SQLite 查询替代遍历前 200 模块

#### 3.2 暴露 query_by_parent [P1]
- 新增 `query_subclasses` CLI 命令
- 调用 ClassIndex.query_by_parent()

#### 3.3 暴露 get_dependents [P1]
- 新增 `query_module_dependents` CLI 命令
- 实现反向依赖查询

#### 3.4 暴露 ExampleExtractor [P2]
- 新增 `query_examples` CLI 命令
- 查询代码示例

#### 3.5 新增枚举查询命令 [P1]
- `query_enum_info <enum_name>` — 查询枚举详细信息
- `search_enums <keyword>` — 搜索枚举

#### 3.6 优化 get_function_implementation [P3]
- 定位到函数体起始行，提取函数体 + 前后 5 行上下文
- 而非返回整个 cpp 文件

#### 3.7 更新 skill.md.template [ALL]
- 添加新命令文档
- 添加枚举查询示例
- 添加反向继承/依赖查询示例

### Wave 4: 版本和文档

#### 4.1 版本号升级到 2.14.0
- pyproject.toml
- cli.py
- config.py

#### 4.2 更新 README.md
- 添加新功能说明
- 更新命令列表

## Impact

### Affected code
- `ue5_kb/parsers/cpp_parser.py` — **重大修改**: 新增 5 个数据类, 8+ 个新方法
- `ue5_kb/core/module_graph.py` — **修改**: 新增节点类型常量
- `ue5_kb/core/class_index.py` — **修改**: 新增列和方法
- `ue5_kb/core/enum_index.py` — **新建**: 枚举索引
- `ue5_kb/builders/module_graph_builder.py` — **重大修改**: 支持新数据类型, 移除 Private 排除
- `ue5_kb/pipeline/analyze.py` — **修改**: 支持新解析结果
- `ue5_kb/pipeline/build.py` — **修改**: 支持新数据结构
- `templates/impl.py.template` — **重大修改**: 新增 6+ CLI 命令, 移除搜索限制
- `templates/impl.plugin.py.template` — **同上**
- `templates/skill.md.template` — **修改**: 新增命令文档
- `templates/skill.plugin.md.template` — **同上**
- `pyproject.toml` — **修改**: 版本号
- `README.md` — **修改**: 新功能说明

### Backward compatibility
- 新增字段使用默认值，旧 KB 可正常加载
- 新的 enum_index.db 不存在时自动降级
- `parse_content()` 返回值变更为 3-tuple — **破坏性变更**，需更新所有调用点
- 旧 pickle 文件需要重新生成

### Performance impact
- Doxygen 提取: +5% 解析时间
- Private 目录扫描: +30-50% 文件数量，相应增加解析时间
- 枚举/委托/别名解析: +10% 解析时间
- SQLite 索引查询替代遍历: **查询性能大幅提升**

## Testing Plan

### 单元测试 (tests/test_cpp_parser_v2.py)
- 多行注释处理
- Doxygen 注释提取
- UENUM 解析
- UCLASS/UPROPERTY 说明符提取
- Delegate 宏解析
- typedef/using 解析
- 纯虚函数保留
- 枚举索引 CRUD

### 集成测试 (tests/test_integration_v2.py)
- 使用 D:\Unreal Engine\UE_5.5 的 Core 模块运行完整 pipeline
- 输出到 J:\UE5_KnowledgeBaseMaker\test_output\
- 验证:
  - 枚举数量 > 0
  - 注释数量 > 0
  - Private 目录文件被扫描
  - 反向继承查询返回结果
  - 反向依赖查询返回结果
  - 函数查询无模块限制

## Verification Checklist
- [ ] CppParser 返回 enums
- [ ] Doxygen 注释关联到类和函数
- [ ] UCLASS/UPROPERTY 说明符被存储
- [ ] Private 目录被扫描
- [ ] 搜索限制已移除
- [ ] query_subclasses 命令可用
- [ ] query_module_dependents 命令可用
- [ ] query_enum_info / search_enums 命令可用
- [ ] query_examples 命令可用
- [ ] 纯虚函数被记录
- [ ] 委托宏被解析
- [ ] typedef/using 被解析
- [ ] #include 关系被记录
- [ ] get_function_implementation 只返回函数体
- [ ] 版本号为 2.14.0
- [ ] 所有测试通过

## References
- 审计报告: 上一条对话消息中的完整分析
- 现有 proposal 格式: openspec/archive/enhance-cpp-parser/proposal.md
