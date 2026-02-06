# Change: Knowledge Base Version Tracking and Incremental Update System

## ID
kb-version-tracking

## Status
PENDING

## Created
2026-02-06

## Why

当前 UE5 Knowledge Base Maker 工具创建的知识库没有版本号，也无法检测代码变更。当引擎或插件中的代码有变化时，再次运行 `ue5kb init` 会完全重建，无法增量更新。

**问题**:
1. 知识库（GlobalIndex、ModuleGraph、SQLite）没有存储引擎/插件版本号
2. 没有文件级变更检测（无哈希、无 mtime 跟踪）
3. 再次 init 会完全重建，无法跳过未变更的模块
4. Skill 生成的 KB 路径是硬编码的绝对路径

**解决方案**:
- 为知识库添加完整的版本追踪系统
- 实现文件级变更检测（SHA256 哈希）
- 实现增量更新系统，仅更新变更的模块
- 为 Skill 添加版本信息查询功能

## What Changes

### 1. 新建文件: `ue5_kb/core/manifest.py`

提供完整的版本追踪和变更检测系统：

```python
"""
Knowledge Base Manifest Management

Defines data structures and I/O for KB version tracking.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime
from pathlib import Path
import json
import hashlib

@dataclass
class FileInfo:
    """Information about a single source file"""
    path: str
    sha256: str
    size: int
    mtime: float

@dataclass
class ModuleManifest:
    """Manifest for a single module"""
    module_name: str
    build_cs_path: str
    category: str
    files: Dict[str, FileInfo]
    module_hash: str
    indexed_at: str
    parser_version: str

@dataclass
class KBManifest:
    """Knowledge base manifest (root level)"""
    kb_version: str
    engine_version: str
    engine_path: str
    plugin_name: Optional[str]
    created_at: str
    last_updated: str
    build_mode: str
    tool_version: str
    files: Dict[str, dict]
    modules: Dict[str, dict]
    statistics: Dict[str, int]

class Hasher:
    """File hashing utilities"""
    @staticmethod
    def compute_sha256(file_path: Path) -> str
    @staticmethod
    def compute_module_hash(build_cs_path: Path, source_files: List[Path]) -> str
```

### 2. 修改 `ue5_kb/core/config.py`

添加版本字段到默认配置。

### 3. 修改 `ue5_kb/pipeline/coordinator.py`

添加版本检测和 manifest 加载。

### 4. 修改 `ue5_kb/pipeline/discover.py`

为 .Build.cs 文件计算哈希。

### 5. 修改 `ue5_kb/pipeline/extract.py`

创建 module_manifest.json 文件。

### 6. 修改 `ue5_kb/pipeline/build.py`

创建 .kb_manifest.json 并保存元数据到 GlobalIndex。

### 7. 新建文件: `ue5_kb/pipeline/update.py`

实现增量更新逻辑。

### 8. 修改 `ue5_kb/cli.py`

- 版本号更新到 2.13.0
- 添加 `update` 命令
- 更新帮助文档

### 9. 修改模板文件

- `templates/skill.md.template` - 添加版本信息章节
- `templates/impl.py.template` - 添加 `get_kb_info()` 函数
- `templates/skill.plugin.md.template` - 添加版本信息章节（插件模式）
- `templates/impl.plugin.py.template` - 添加 `get_kb_info()` 函数（插件模式）

### 10. 更新文档

- `CHANGELOG.md` - 添加 v2.13.0 变更日志
- `README.md` - 添加增量更新系统说明
- `pyproject.toml` - 版本号更新到 2.13.0

## Impact

### Affected specs
- core/cli-interface
- core/pipeline-system

### Affected code
- `ue5_kb/core/manifest.py` - **新建**
- `ue5_kb/core/config.py` - **修改**
- `ue5_kb/core/global_index.py` - **修改**
- `ue5_kb/core/module_graph.py` - **修改**
- `ue5_kb/pipeline/coordinator.py` - **修改**
- `ue5_kb/pipeline/discover.py` - **修改**
- `ue5_kb/pipeline/extract.py` - **修改**
- `ue5_kb/pipeline/build.py` - **修改**
- `ue5_kb/pipeline/update.py` - **新建**
- `ue5_kb/cli.py` - **修改**
- `templates/*.md.template` - **修改**
- `templates/*.py.template` - **修改**
- `CHANGELOG.md` - **修改**
- `README.md` - **修改**
- `pyproject.toml` - **修改**

### Backward compatibility
- **完全向后兼容**: 旧知识库可以继续使用
- 旧知识库首次运行时自动创建 manifest
- 无 manifest 时自动降级为完全重建模式

### Performance impact
- 首次扫描: 哈希计算增加约 10-15% 时间
- 增量更新: 大幅减少更新时间（如只修改 1 个模块，更新时间从 30 分钟降至 2 分钟）

## Testing Plan

### 单元测试
```python
# 测试哈希计算
def test_compute_sha256():
    hasher = Hasher()
    hash_val = hasher.compute_sha256(Path("test.cpp"))
    assert len(hash_val) == 64  # SHA256 长度

# 测试 manifest 序列化
def test_manifest_serialization():
    manifest = KBManifest(...)
    manifest.save(kb_path)
    loaded = KBManifest.load(kb_path)
    assert loaded.kb_version == manifest.kb_version

# 测试差异计算
def test_diff_computation():
    old_manifest = KBManifest(...)
    new_modules = [...]
    diff = updater._compute_diff(old_manifest, new_modules)
    assert 'added' in diff
    assert 'modified' in diff
```

### 集成测试
```bash
# 1. 安装更新
pip install -e . --force-reinstall --no-deps

# 2. 测试引擎模式
ue5kb init --engine-path "D:\UE5"
cat "D:\UE5\KnowledgeBase\.kb_manifest.json"

# 3. 测试插件模式
ue5kb init --plugin-path "F:\Plugins\MyPlugin"
cat "F:\Plugins\MyPlugin\KnowledgeBase\.kb_manifest.json"

# 4. 测试增量更新
echo "// test" >> "D:\UE5\Engine\Source\Runtime\Core\Public\UObject\UObjectBase.h"
ue5kb update --check
ue5kb update

# 5. 测试 Skill 版本查询
python ~/.claude/skills/ue5kb-5.5.4/impl.py get_kb_info
```

## Verification Checklist
- [ ] `ue5_kb/core/manifest.py` 文件存在且语法正确
- [ ] 引擎模式创建 .kb_manifest.json
- [ ] 插件模式创建 .kb_manifest.json
- [ ] 增量更新正确检测变更模块
- [ ] `get_kb_info` 命令返回正确信息
- [ ] 旧知识库向后兼容
- [ ] CLI 版本号更新到 2.13.0
- [ ] CHANGELOG.md 包含 v2.13.0 条目
- [ ] README.md 包含增量更新说明

## References
- 计划文件: `C:\Users\pb763\.claude\plans\purring-meandering-snail.md`
- 现有版本检测: `ue5_kb/cli.py` 中的 `detect_engine_version()` 和 `detect_plugin_info()`
