# Change: Fix Analyze Stage Silent Failure and Improve Error Reporting

## ID
fix-analyze-silent-failure

## Status
IMPLEMENTED

## Created
2026-02-04

## Why

当前工具在执行 `ue5kb init --engine-path ...` 时，analyze 阶段可能出现"突然退出"或"无响应"的问题。

**根本原因**:
1. `analyze.py:169-171` 使用 `pass` 静默忽略文件解析错误，没有任何日志输出
2. 进度报告每 50 个模块才输出一次，Engine 模式有 1757+ 模块，前几个模块崩溃时用户看不到任何进度
3. 没有使用 logging 模块，无法追踪具体哪些文件/模块解析失败
4. C++ 解析器缺乏边界检查和异常处理

**用户影响**:
- 程序崩溃时完全没有任何错误信息
- 无法诊断是哪个文件或模块导致解析失败
- 调试困难，用户体验差

## What Changes

### 1. 替换静默错误处理 (高优先级)
文件: `ue5_kb/pipeline/analyze.py` (第 169-171 行)

**修改前**:
```python
except Exception as e:
    # 单个文件解析失败不影响其他文件
    pass
```

**修改后**:
```python
except Exception as e:
    # 记录文件解析失败
    print(f"    [警告] 文件解析失败: {source_file}")
    print(f"      错误: {e}")
```

### 2. 改进进度报告 (高优先级)
文件: `ue5_kb/pipeline/analyze.py` (第 59-61 行)

**修改前**:
```python
if (i + 1) % 50 == 0:
    print(f"  进度: {i + 1}/{len(modules)} ({success_count} 成功)")
```

**修改后**:
```python
# 每个模块都输出当前处理状态
print(f"  [{i+1}/{len(modules)}] 正在分析: {module['name']}...")
```

### 3. 添加文件级进度 (中优先级)
文件: `ue5_kb/pipeline/analyze.py` (_analyze_module 方法)

**新增**:
```python
for file_idx, source_file in enumerate(source_files):
    if len(source_files) > 10 and (file_idx + 1) % 10 == 0:
        print(f"    文件进度: {file_idx + 1}/{len(source_files)}")
```

### 4. 收集失败文件列表 (中优先级)
文件: `ue5_kb/pipeline/analyze.py` (_analyze_module 方法)

**新增**:
```python
failed_files = []

# 在 _analyze_module 中收集失败文件
except Exception as e:
    failed_files.append({
        'file': str(source_file),
        'error': str(e),
        'error_type': type(e).__name__
    })

# 在返回结果中包含
return {
    'module': module_name,
    'source_file_count': len(source_files),
    'classes': classes,
    'functions': functions,
    'failed_files': failed_files[:5]  # 只保存前5个
}
```

### 5. 添加边界检查到 C++ 解析器 (中优先级)
文件: `ue5_kb/parsers/cpp_parser.py` (_parse_class_body 方法)

**新增**:
```python
def _parse_class_body(self, lines: List[str], start_line: int, class_name: str, file_path: str) -> int:
    # 添加边界检查
    if start_line >= len(lines):
        return len(lines) - 1

    MAX_BRACE_DEPTH = 100
    brace_count = 1
    # ... 现有逻辑 ...

    if brace_count > MAX_BRACE_DEPTH:
        print(f"    [警告] 花括号嵌套过深，跳过类体解析: {class_name}")
        return start_line
```

### 6. 添加异常处理到 parse_content (中优先级)
文件: `ue5_kb/parsers/cpp_parser.py` (parse_content 方法)

**新增**:
```python
def parse_content(self, content: str, file_path: str = "") -> Tuple:
    try:
        # 现有解析逻辑
        ...
    except Exception as e:
        print(f"    [错误] 解析失败 {file_path}: {e}")
        return {}, {}
```

### 7. 添加 verbose 选项 (低优先级)
文件: `ue5_kb/cli.py` (init_engine_mode 函数)

**新增**:
```python
@click.option('--verbose', '-v', is_flag=True, help='显示详细输出')
def init_engine_mode(engine_path, module, force, verbose):
    # 传递 verbose 参数到 pipeline
    results = coordinator.run_all(force=force, verbose=verbose)
```

文件: `ue5_kb/pipeline/analyze.py` (run 方法)

**新增**:
```python
def run(self, parallel: int = 1, verbose: bool = False, **kwargs):
    # 在 verbose 模式下显示每个文件
    if verbose:
        print(f"      解析: {source_file.name}")
```

## Impact

### Affected specs
- 无

### Affected code
- `ue5_kb/pipeline/analyze.py` - 主要修改
- `ue5_kb/parsers/cpp_parser.py` - 添加边界检查和异常处理
- `ue5_kb/cli.py` - 添加 verbose 选项

### Backward compatibility
- 完全向后兼容
- 只增加输出，不改变数据结构
- 旧版本生成的知识库可以继续使用

### Performance impact
- 额外的 print 语句可能略微增加输出时间
- 进度报告频率增加（每模块 vs 每50模块）
- 预计整体性能影响 < 1%

## Testing Plan

### 单元测试
1. 测试文件解析失败时的错误输出
2. 测试进度报告正确显示
3. 测试边界检查防止索引越界

### 集成测试
```bash
# 1. 重新安装包
pip install -e . --force-reinstall --no-deps

# 2. 运行 analyze 阶段
ue5kb init --engine-path "D:\UnrealEngine\UnrealEngine" --force

# 3. 验证输出
# - 应该看到每个模块的处理进度
# - 如果文件解析失败，应该看到具体的文件名和错误信息

# 4. 使用 verbose 模式
ue5kb init --engine-path "D:\UnrealEngine\UnrealEngine" --verbose
```

### 验证清单
- [ ] 每个模块都显示进度 `[1/1757] 正在分析: Core...`
- [ ] 文件解析失败时显示警告和错误信息
- [ ] 程序不再"静默失败"
- [ ] verbose 模式显示文件级进度
- [ ] C++ 解析器有边界检查
- [ ] parse_content 有异常处理

## References
- 计划文件: `C:\Users\pb763\.claude\plans\reflective-baking-crane.md`
- CLAUDE.md: 项目开发指导
- 相关 Issue: 用户报告 analyze 阶段突然退出
