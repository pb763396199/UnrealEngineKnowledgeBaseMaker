# Change: Fix Skill Generation Double Brace Issue

## ID
fix-skill-generation

## Status
IMPLEMENTED

## Created
2026-02-04

## Why

当前工具生成的 Skill `impl.py` 文件包含语法错误的 Python 代码：

- `_module_graphs_cache = {{}}` - 应该是 `{}`
- `result = {{}}` - 应该是 `{}`
- `return {{"error": ...}}` - 应该是 `{"error": ...}`

这导致使用 Skill 时出现 `TypeError: unhashable type: 'dict'` 错误。

**根本原因**: 模板文件使用 `{{}}` 来避免与格式字符串冲突，但在生成代码时只替换了 `{ENGINE_VERSION}` 和 `{KB_PATH}` 变量，没有将剩余的 `{{` 和 `}}` 转换为单花括号。

**错误日志**:
```
TypeError: unhashable type: 'dict'
```

## What Changes

### 1. 修复生成逻辑
文件: `ue5_kb/pipeline/generate.py` (第155-158行)

在变量替换后，添加双花括号到单花括号的转换：

```python
for key, value in variables.items():
    impl_py_content = impl_py_content.replace(f'{{{key}}}', value)

# 修复：将模板中的 {{ 和 }} 转换为单花括号
impl_py_content = impl_py_content.replace('{{', '{').replace('}}', '}')
```

### 2. 验证生成文件语法
可选：在写入文件前验证生成的 Python 代码语法正确：

```python
import ast
ast.parse(impl_py_content)  # 验证语法
```

## Impact

### Affected specs
- 无

### Affected code
- `ue5_kb/pipeline/generate.py` - 添加替换逻辑

### Backward compatibility
- 完全向后兼容
- 新生成的 Skill 文件将使用正确的 Python 语法
- 旧版 Skill 文件需要重新生成才能修复

### Performance impact
- 无显著影响（仅增加一次字符串替换操作）

## Testing Plan

### 单元测试
1. 运行生成阶段
2. 检查生成的 `impl.py` 语法正确性
3. 验证函数可以正常导入和调用

### 集成测试
```bash
# 1. 重新安装包
pip install -e . --force-reinstall --no-deps

# 2. 生成 Skill（使用已有知识库）
python -m ue5_kb.cli init --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 3. 验证生成的文件
cat ~/.claude/skills/ue5kb-5.1.1/impl.py | head -30
# 应该看到: _module_graphs_cache = {} (不是 {{}})

# 4. 测试 Python 语法
python -c "import ast; ast.parse(open('~/.claude/skills/ue5kb-5.1.1/impl.py').read())"
# 应该无错误

# 5. 在 Claude Code 中测试 Skill
# /ue5kb-5.1.1 查询 AActor 类信息
```

## Verification Checklist

- [ ] `_module_graphs_cache = {}` (不是 `{{}}`)
- [ ] `result = {}` (不是 `{{}}`)
- [ ] `categories = {}` (不是 `{{}}`)
- [ ] `return {"error": ...}` (不是 `{{"error": ...}}`)
- [ ] 其他所有字典字面量使用单花括号
- [ ] 可以成功导入生成的 `impl.py`
- [ ] Skill 调用不再报 `TypeError`

## References
- 计划文件: `C:\Users\pb763\.claude\plans\glittery-munching-kurzweil.md`
- CLAUDE.md: 项目开发指导
