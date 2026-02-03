# UE5 Knowledge Base Maker v2.5.0 - Quick Start Guide

> Context Engineering Edition - 快速开始指南

---

## 🚀 快速开始（推荐方式 - Pipeline 模式）

### 方式 1：标准 Pipeline 模式

适用于大多数场景：

```bash
# 进入引擎目录
cd "D:\Unreal Engine\UE5.1"

# 运行完整 Pipeline
ue5kb pipeline run --engine-path .

# Pipeline 会自动执行 5 个阶段：
# 1. discover - 发现所有模块
# 2. extract - 提取模块依赖
# 3. analyze - 分析代码结构
# 4. build - 构建索引
# 5. generate - 生成 Skill
```

**输出位置**：
- 中间数据：`./data/` （JSON 格式，可读）
- 最终知识库：`./KnowledgeBase/`
- Claude Skill：`~/.claude/skills/ue5kb-{version}/`

---

### 方式 2：分区模式（适用于超大引擎）

如果你的引擎有 1500+ 模块，推荐使用分区模式：

```bash
# 处理所有分区
ue5kb pipeline partitioned --engine-path .

# 或仅处理特定分区
ue5kb pipeline partitioned --engine-path . \
    --partition runtime \
    --partition editor

# 查看分区状态
ue5kb pipeline partition-status --engine-path .
```

**6 大分区**：
- `runtime` - Runtime 核心模块（~700个）
- `editor` - Editor 编辑器模块（~600个）
- `plugins` - Plugins 插件模块（~900+个）
- `developer` - Developer 开发工具
- `platforms` - Platforms 平台模块
- `programs` - Programs 独立程序

---

### 方式 3：旧方式（向后兼容）

如果你习惯旧命令，仍然可用：

```bash
ue5kb init --engine-path "D:\Unreal Engine\UE5.1"

# 等同于
ue5kb pipeline run --engine-path "D:\Unreal Engine\UE5.1"
```

---

## 📊 查看状态

### Pipeline 状态

```bash
ue5kb pipeline status --engine-path "D:\UE5"
```

输出示例：
```
=== Pipeline 状态 ===
阶段       已完成  完成时间      摘要
discover   ✓      2026-02-03   total_count: 1757
extract    ✓      2026-02-03   success_count: 1755
analyze    ✓      2026-02-03   analyzed_count: 1600
build      ✓      2026-02-03   kb_path: D:\UE5\KnowledgeBase
generate   ✓      2026-02-03   skill_name: ue5kb-5.1.500
```

### 分区状态

```bash
ue5kb pipeline partition-status --engine-path "D:\UE5"
```

---

## 🔄 增量更新

如果你修改了代码，想要重新构建：

### 完全重建（强制）

```bash
ue5kb pipeline run --engine-path . --force
```

### 增量更新（智能跳过）

```bash
# 第一次运行（全部执行）
ue5kb pipeline run --engine-path .

# 第二次运行（自动跳过已完成的阶段）
ue5kb pipeline run --engine-path .
# 输出: 阶段 'discover' 已完成，跳过
```

### 重新运行特定阶段

```bash
# 清除 analyze 阶段
ue5kb pipeline clean --engine-path . analyze

# 重新运行（只运行 analyze、build、generate）
ue5kb pipeline run --engine-path .
```

---

## 🎯 使用生成的 Skill

Skill 自动安装在 `~/.claude/skills/ue5kb-{version}/`

### 基础查询（原有方法）

```python
# 查询模块依赖
query_module_dependencies('Core')

# 搜索模块
search_modules('Render')

# 查询类信息
query_class_info('AActor')

# 查询函数
query_function_info('BeginPlay')
```

### 优化查询（新方法，推荐！）

```python
# 分层查询类信息
# 1. 先用 summary（~150 tokens）
summary = query_class_layered('AActor', 'summary')
# 返回: name, module, parent, method_count, key_methods, ref_id

# 2. 需要详情时（~800 tokens）
details = query_class_layered(summary['ref_id'], 'details')
# 返回: 完整方法列表, properties, file_path, line_number

# 3. 需要源码时（~2000+ tokens）
source = query_class_layered(details['source_ref'], 'source')
# 返回: 完整源代码

# 分层查询函数
func_summary = query_function_layered('BeginPlay', 'summary')
# ~50 tokens

func_details = query_function_layered('BeginPlay', 'details')
# ~300 tokens
```

**Token 节省**: 使用 `summary` 模式可节省 **70-85%** Token！

### 监控 Token 使用

```python
# 查看 Token 统计
stats = get_token_statistics()

# 查看缓存统计
cache = get_cache_statistics()
```

---

## 🛠️ 常见任务

### 任务 1：首次构建知识库

```bash
# 1. 进入引擎目录
cd "D:\Unreal Engine\UE5.1"

# 2. 运行 Pipeline
ue5kb pipeline run --engine-path .

# 3. 等待完成（约 30-60 分钟，取决于模块数）

# 4. 验证生成
ls KnowledgeBase/
ls ~/.claude/skills/
```

### 任务 2：修改代码后更新

```bash
# 1. 清除受影响的阶段
ue5kb pipeline clean --engine-path . analyze

# 2. 重新运行（仅运行需要的阶段）
ue5kb pipeline run --engine-path .

# 耗时：约 5-10 分钟（而不是 30-60 分钟！）
```

### 任务 3：仅更新特定分区

```bash
# 1. 清除 runtime 分区
ue5kb pipeline clean --engine-path . analyze

# 2. 仅重建 runtime
ue5kb pipeline partitioned --engine-path . --partition runtime

# 耗时：约 2-5 分钟
```

### 任务 4：调试特定阶段

```bash
# 1. 查看中间结果
cat data/discover/modules.json
cat data/extract/Core/dependencies.json

# 2. 清除并重跑
ue5kb pipeline clean --engine-path . extract
ue5kb pipeline run --engine-path .

# 3. 查看日志
# Pipeline 会打印详细进度
```

---

## 📁 输出结构

```
D:\Unreal Engine\UE5.1\
├── data/                          # Pipeline 中间数据（新）
│   ├── discover/
│   │   └── modules.json           # 发现的模块列表
│   ├── extract/
│   │   ├── Core/
│   │   │   └── dependencies.json  # 依赖关系
│   │   └── ...
│   ├── analyze/
│   │   ├── Core/
│   │   │   └── code_graph.json    # 代码结构
│   │   └── ...
│   └── partitions/                # 分区结果（如果使用）
│       ├── runtime.json
│       └── ...
├── .pipeline_state                # Pipeline 状态跟踪（新）
└── KnowledgeBase/                 # 最终知识库
    ├── config.yaml
    ├── global_index/
    │   ├── index.db               # SQLite 索引
    │   ├── global_index.pkl       # Pickle 备份
    │   └── function_index.db      # 函数索引
    └── module_graphs/
        ├── Core.pkl
        ├── Engine.pkl
        └── ...

~/.claude/skills/
└── ue5kb-5.1.500/                 # 生成的 Skill
    ├── skill.md
    └── impl.py
```

---

## ❓ 常见问题

### Q: Pipeline 模式和旧方式有什么区别？

**A**: Pipeline 模式的优势：
- ✅ 支持增量构建（修改后不需要全部重跑）
- ✅ 中间结果可读（JSON 格式）
- ✅ 可独立调试每个阶段
- ✅ 状态跟踪和恢复
- ✅ 更好的错误处理

### Q: 什么时候使用分区模式？

**A**: 推荐使用分区模式如果：
- 引擎模块数 > 1500
- 内存或时间受限
- 仅需要特定分类的模块
- 想要并行构建（未来支持）

### Q: 如何节省 Token？

**A**: 使用新的分层查询：
```python
# ❌ 旧方法（~1000 tokens）
result = query_class_info('AActor')

# ✅ 新方法（~150 tokens，节省 85%）
summary = query_class_layered('AActor', 'summary')
```

### Q: Pipeline 失败了怎么办？

**A**:
1. 查看错误信息
2. 查看 `.pipeline_state` 文件
3. 清除失败的阶段：`ue5kb pipeline clean --engine-path . <stage>`
4. 重新运行：`ue5kb pipeline run --engine-path .`

### Q: 旧的 `ue5kb init` 命令还能用吗？

**A**: 可以！向后兼容：
```bash
ue5kb init --engine-path "D:\UE5"
# 等同于
ue5kb pipeline run --engine-path "D:\UE5"
```

---

## 🎓 进阶使用

### 并行处理（analyze 阶段）

```bash
ue5kb pipeline run --engine-path . --parallel 4
# 使用 4 个并行线程分析代码（未来实现）
```

### 自定义输出路径

```bash
ue5kb init --engine-path "D:\UE5" \
    --kb-path "J:\CustomKB" \
    --skill-path "J:\Skills"
```

### 插件模式

```bash
# 为单个插件生成知识库
ue5kb init --plugin-path "F:\MyProject\Plugins\MyPlugin"
```

---

## 📚 更多信息

- **完整文档**: `docs/ARCHITECTURE_UPGRADE_PLAN.md`
- **实施报告**: `docs/IMPLEMENTATION_COMPLETE.md`
- **项目指南**: `CLAUDE.md`
- **Context 理论**: `docs/CONTEXT_OPTIMIZATION.md`

---

## 🎉 开始使用

```bash
# 最简单的方式
cd "D:\Unreal Engine\UE5.1"
ue5kb pipeline run --engine-path .

# 等待完成，然后在 Claude Code 中使用生成的 Skill！
```

**版本**: v2.5.0 (Context Engineering Edition)
**理论基础**: Agent Skills for Context Engineering
**实施者**: Claude (anthropic/claude-sonnet-4.5)
