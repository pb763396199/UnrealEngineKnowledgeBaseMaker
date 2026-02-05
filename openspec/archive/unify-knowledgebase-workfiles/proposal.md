# Change: Unify KnowledgeBase Work Files Management + Align Plugin Skill Template

## ID
unify-knowledgebase-workfiles

## Status
IMPLEMENTED

## Created
2026-02-05

## Why

### 问题 1：工作文件分散
当前工具在创建知识库的过程中，工作文件（`.pipeline_state` 和 `data/` 文件夹）散落在引擎/插件根目录下，导致：

1. **目录污染**: 引擎源码目录下产生与知识库相关的文件
2. **管理不便**: 删除知识库时需要手动删除多个位置的文件
3. **结构不清晰**: 用户不清楚哪些文件属于知识库系统

### 问题 2：插件模式 Skill 模板不完整
插件模式的 Skill markdown 模板 (`skill.plugin.md.template`) 缺少以下内容，导致用户体验不一致：

1. **缺少 `search_functions` 命令** - 函数搜索功能未在文档中列出
2. **缺少查询降级机制说明** - 查询失败时的处理策略未说明
3. **缺少函数相关查询示例** - 示例不够全面
4. **示例对话不够详细** - 用户体验不如引擎模式

**注意**: `impl.py` 实际上已包含所有功能（包括 `search_functions`），问题仅在于文档层面。

## What Changes

### 问题 1：修改工作文件位置

#### 1. 修改 PipelineState 状态文件位置
**文件**: `ue5_kb/pipeline/state.py` (第 28 行)

**当前代码**:
```python
self.state_file = self.base_path / ".pipeline_state"
```

**修改为**:
```python
# 将状态文件放在 KnowledgeBase 目录下统一管理
self.state_file = self.base_path / "KnowledgeBase" / ".pipeline_state"
```

#### 2. 修改 PipelineStage 工作数据目录位置
**文件**: `ue5_kb/pipeline/base.py` (第 32 行)

**当前代码**:
```python
self.data_dir = self.base_path / "data"
```

**修改为**:
```python
# 将工作数据放在 KnowledgeBase 目录下统一管理
self.data_dir = self.base_path / "KnowledgeBase" / "data"
```

### 问题 2：对齐插件模式 Skill 模板

#### 3. 修改插件模式 Skill 模板
**文件**: `templates/skill.plugin.md.template`

**需要添加的内容**：

1. **在命令列表中添加 `search_functions` 命令**（第 37 行后）
   ```markdown
   | `search_functions` | `<keyword> [limit=50]` | 搜索包含关键字的函数 |
   ```

2. **在"何时使用此技能"后添加函数相关查询示例**（第 12 行后）
   ```markdown
   ### 函数相关查询
   - "MyFunction 函数的定义是什么？"
   - "GetXXX 函数在哪些模块中定义？"
   - "查找包含 'Process' 的函数"
   ```

3. **在使用建议中添加 search_functions**（第 65 行）
   ```markdown
   3. **使用搜索功能**：如果只知道关键字，使用 `search_modules`、`search_classes` 或 `search_functions`
   ```

4. **添加完整的查询降级机制说明**（第 66 行后）
   - 查询降级流程
   - 具体降级命令映射
   - 示例对话（错误做法 vs 正确做法）
   - 关键原则

5. **扩展示例对话**（替换第 74-88 行）
   - 添加类继承关系查询示例
   - 添加模块依赖查询示例
   - 添加类搜索示例

## Impact

### Affected specs
None (此变更不涉及功能规范变更，仅涉及文件组织结构)

### Affected code
**问题 1**:
- `ue5_kb/pipeline/state.py` - 修改 state_file 路径计算
- `ue5_kb/pipeline/base.py` - 修改 data_dir 路径计算

**问题 2**:
- `templates/skill.plugin.md.template` - 添加缺失的命令和说明

### Backward compatibility
**破坏性变更**: 此修改会改变工作文件的位置。

**迁移指南**:
- 如果用户已有正在进行的 Pipeline，需要手动将旧的文件移动：
  ```bash
  # 移动状态文件
  mv {Engine}/.pipeline_state {Engine}/KnowledgeBase/.pipeline_state

  # 移动工作数据目录
  mv {Engine}/data {Engine}/KnowledgeBase/data
  ```
- 或使用 `--force` 重新运行 Pipeline

### Performance impact
无性能影响（仅路径计算变更）

### 引擎模式和插件模式兼容性

两种模式的路径计算逻辑完全相同，修改方案对两者都适用。

| 模式 | base_path | 当前 state_file | 修改后 state_file |
|------|-----------|-----------------|-------------------|
| 引擎模式 | `D:\UE5\Engine` | `D:\UE5\Engine\.pipeline_state` | `D:\UE5\Engine\KnowledgeBase\.pipeline_state` |
| 插件模式 | `F:\Project\Plugins\MyPlugin` | `F:\Project\Plugins\MyPlugin\.pipeline_state` | `F:\Project\Plugins\MyPlugin\KnowledgeBase\.pipeline_state` |

**原因**: `PipelineState` 和 `PipelineStage` 都使用相同的 `base_path` 参数，而 KnowledgeBase 路径的计算方式是统一的 `base_path / "KnowledgeBase"`。

## Testing Plan

### 单元测试
- 验证 `PipelineState` 在两种模式下都能正确加载/保存状态
- 验证 `PipelineStage` 在两种模式下都能正确创建工作目录

### 集成测试

#### 引擎模式测试
```bash
ue5kb init --engine-path "D:\Unreal Engine\UE5.1" --force
```

验证输出：
- `{Engine}/KnowledgeBase/.pipeline_state` 存在
- `{Engine}/KnowledgeBase/data/` 目录存在
- `{Engine}/.pipeline_state` 不存在
- `{Engine}/data/` 不存在

#### 插件模式测试
```bash
ue5kb init --plugin-path "F:\MyProject\Plugins\MyPlugin" --force
```

验证输出：
- `{Plugin}/KnowledgeBase/.pipeline_state` 存在
- `{Plugin}/KnowledgeBase/data/` 目录存在
- `{Plugin}/.pipeline_state` 不存在
- `{Plugin}/data/` 不存在

## References
- 计划文件: `C:\Users\pb763\.claude\plans\lexical-watching-music.md`
- CLAUDE.md: 项目开发指导
