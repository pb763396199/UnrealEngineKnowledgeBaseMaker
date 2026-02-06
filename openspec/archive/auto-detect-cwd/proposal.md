# Change: Auto-Detect Engine/Plugin from Current Working Directory

## ID
auto-detect-cwd

## Status
IMPLEMENTED

## Created
2026-02-06

## Why

当前 `ue5kb init` 命令要求用户必须显式指定 `--engine-path` 或 `--plugin-path` 参数。这在实际使用中不够便捷：

**问题**:
1. 用户已经处于引擎或插件目录中，还需要重新输入完整路径
2. 路径可能很长，容易输入错误
3. 降低工具的易用性和开发体验

**解决方案**:
当用户不指定路径参数时，自动检测当前目录是 UE5 引擎还是插件，提供"开箱即用"的体验。

## What Changes

### 1. 创建新文件: `ue5_kb/utils/auto_detect.py`

提供自动检测核心逻辑：

```python
"""
Auto-detection utilities for UE5 engines and plugins.
"""

from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass
import json

DetectionResult = Literal['plugin', 'engine', 'engine_subdir', 'unknown']


@dataclass
class DetectionInfo:
    """自动检测结果"""
    mode: DetectionResult
    detected_path: Optional[Path]
    confidence: str
    reason: str
    suggested_name: Optional[str] = None


def detect_from_cwd(cwd: Optional[Path] = None) -> DetectionInfo:
    """从当前工作目录自动检测 UE5 引擎或插件

    检测优先级:
    1. 插件: 检查当前目录的 .uplugin 文件
    2. 引擎: 检查当前目录的 Engine/Build/Build.version
    3. 引擎子目录: 向上遍历父目录查找 Engine/Build/Build.version
    4. 未知: 无法自动检测
    """
```

### 2. 修改 `ue5_kb/cli.py` 的 `init` 命令

**更新选项说明** (第68-71行):
```python
@click.option('--engine-path', type=click.Path(exists=True),
              help='UE5 引擎路径（与 --plugin-path 二选一，未指定时自动检测）')
@click.option('--plugin-path', type=click.Path(exists=True),
              help='插件路径（与 --engine-path 二选一，未指定时自动检测）')
```

**替换无参数处理逻辑** (第142-149行):
```python
if not engine_path and not plugin_path:
    # 自动检测模式
    from ue5_kb.utils.auto_detect import detect_from_cwd

    detection = detect_from_cwd()

    if detection.mode == 'unknown':
        # 检测失败，显示友好提示
        console.print("\n[red]X 自动检测失败[/red]\n")
        console.print("无法自动检测 UE5 引擎或插件路径。")
        console.print("\n[bold cyan]请手动指定路径:[/bold cyan]")
        console.print("  引擎模式: ue5kb init --engine-path \"D:\\Unreal Engine\\UE5.1\"")
        console.print("  插件模式: ue5kb init --plugin-path \"F:\\MyProject\\Plugins\\MyPlugin\"")
        return

    # 显示检测结果并设置路径
    console.print("\n[bold cyan]UE5 Knowledge Base Builder[/bold cyan]")
    console.print(f"检测模式: [cyan]{detection.mode}[/cyan]")
    console.print(f"检测路径: [yellow]{detection.detected_path}[/yellow]\n")

    if detection.mode == 'plugin':
        plugin_path = str(detection.detected_path)
    else:
        engine_path = str(detection.detected_path)
```

### 3. 修改 `ue5_kb/utils/__init__.py`

添加导出:
```python
from .auto_detect import detect_from_cwd, DetectionInfo, DetectionResult

__all__ = [
    'ProgressTracker',
    'StageTimer',
    'StageMetrics',
    'CheckpointManager',
    'detect_from_cwd',
    'DetectionInfo',
    'DetectionResult',
]
```

## Impact

### Affected specs
- core/cli-interface

### Affected code
- `ue5_kb/utils/auto_detect.py` - **新建**
- `ue5_kb/cli.py` - **修改** init 命令参数处理
- `ue5_kb/utils/__init__.py` - **修改** 添加导出

### Backward compatibility
- **完全向后兼容**: `--engine-path` 和 `--plugin-path` 参数继续工作
- 新增自动检测作为默认行为
- 检测失败时提供清晰的手动输入指导

### Performance impact
- 自动检测耗时 <100ms（本地文件系统）
- 父目录遍历限制为5层，防止无限循环

## Testing Plan

### 单元测试
```python
# 测试插件检测
def test_detect_plugin():
    detection = detect_from_cwd(Path("F:/Plugins/MyPlugin"))
    assert detection.mode == 'plugin'

# 测试引擎检测
def test_detect_engine():
    detection = detect_from_cwd(Path("D:/Unreal Engine/UE5.1"))
    assert detection.mode == 'engine'

# 测试引擎子目录
def test_detect_engine_subdir():
    detection = detect_from_cwd(Path("D:/Unreal Engine/UE5.1/Engine/Source"))
    assert detection.mode == 'engine_subdir'

# 测试未知目录
def test_detect_unknown():
    detection = detect_from_cwd(Path("C:/Users/Docs"))
    assert detection.mode == 'unknown'
```

### 集成测试
```bash
# 1. 安装更新
pip install -e . --force-reinstall --no-deps

# 2. 测试插件模式（在插件目录中）
cd F:\MyProject\Plugins\MyPlugin
ue5kb init

# 3. 测试引擎模式（在引擎目录中）
cd "D:\Unreal Engine\UE5.1"
ue5kb init

# 4. 测试引擎子目录
cd "D:\Unreal Engine\UE5.1\Engine\Source"
ue5kb init

# 5. 测试显式参数（确保兼容性）
cd C:\Users\Documents
ue5kb init --engine-path "D:\UE5"
ue5kb init --plugin-path "F:\Plugins\MyPlugin"

# 6. 测试检测失败场景
cd C:\Users\Documents
ue5kb init
# 应显示错误信息
```

## Verification Checklist
- [ ] `ue5_kb/utils/auto_detect.py` 文件存在且语法正确
- [ ] 在插件目录运行 `ue5kb init` 正确检测为插件模式
- [ ] 在引擎根目录运行 `ue5kb init` 正确检测为引擎模式
- [ ] 在引擎子目录运行 `ue5kb init` 正确检测为引擎模式
- [ ] 在随机目录运行 `ue5kb init` 显示友好的错误提示
- [ ] `--engine-path` 参数继续工作
- [ ] `--plugin-path` 参数继续工作
- [ ] 两个参数同时使用时正确报错
- [ ] 帮助信息正确显示

## References
- 计划文件: `C:\Users\pb763\.claude\plans\validated-chasing-rossum.md`
- 现有检测函数: `ue5_kb/cli.py` 中的 `detect_engine_version()` 和 `detect_plugin_info()`
