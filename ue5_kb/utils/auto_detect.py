"""
Auto-detection utilities for UE5 engines and plugins.

Determines whether the current working directory is:
- A UE5 plugin (contains .uplugin file)
- A UE5 engine (contains Engine/Build/Build.version)
- A subdirectory of a UE5 engine
- None of the above (requires manual specification)
"""

from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass
import json

DetectionResult = Literal['plugin', 'engine', 'engine_subdir', 'unknown']


@dataclass
class DetectionInfo:
    """Result of auto-detection

    Attributes:
        mode: The detected mode ('plugin', 'engine', 'engine_subdir', 'unknown')
        detected_path: The detected path (None if unknown)
        confidence: Detection confidence ('high', 'medium', 'low')
        reason: Human-readable reason for the detection
        suggested_name: For plugins: plugin name, For engines: version
    """
    mode: DetectionResult
    detected_path: Optional[Path]
    confidence: str  # 'high', 'medium', 'low'
    reason: str
    suggested_name: Optional[str] = None  # For plugins: plugin name, For engines: version


def _read_engine_version(build_version_file: Path) -> str:
    """从 Build.version 文件读取引擎版本

    Args:
        build_version_file: Path to Engine/Build/Build.version file

    Returns:
        Version string like "5.1.1" or "unknown" if failed to read
    """
    try:
        content = build_version_file.read_text()
        version_data = json.loads(content)
        major = version_data.get("MajorVersion")
        minor = version_data.get("MinorVersion")
        patch = version_data.get("PatchVersion")

        if major and minor:
            if patch:
                return f"{major}.{minor}.{patch}"
            else:
                return f"{major}.{minor}.0"
    except Exception:
        pass

    return "unknown"


def _is_engine_subdirectory(path: Path) -> bool:
    """检查给定路径是否是引擎的子目录

    Args:
        path: 要检查的路径

    Returns:
        True 如果路径是引擎目录的子目录
    """
    # 路径组成部分，用于判断是否在引擎目录下
    path_parts = path.parts

    # 检查是否在 Engine/Source 目录下
    if 'Engine' in path_parts:
        engine_idx = path_parts.index('Engine')
        # 如果 Engine 后面紧跟 Source，则是引擎源代码目录
        if engine_idx + 1 < len(path_parts) and path_parts[engine_idx + 1] == 'Source':
            return True

    # 检查是否在 Engine/Plugins 目录下
    if 'Engine' in path_parts:
        engine_idx = path_parts.index('Engine')
        # 如果 Engine 后面紧跟 Plugins，则是引擎插件目录
        if engine_idx + 1 < len(path_parts) and path_parts[engine_idx + 1] == 'Plugins':
            return True

    # 检查是否在 Engine/Config 目录下
    if 'Engine' in path_parts:
        engine_idx = path_parts.index('Engine')
        if engine_idx + 1 < len(path_parts) and path_parts[engine_idx + 1] == 'Config':
            return True

    # 检查是否在 Engine/Content 目录下
    if 'Engine' in path_parts:
        engine_idx = path_parts.index('Engine')
        if engine_idx + 1 < len(path_parts) and path_parts[engine_idx + 1] == 'Content':
            return True

    return False


def _find_engine_root(path: Path) -> Optional[Path]:
    """从给定路径向上查找引擎根目录

    引擎根目录定义为包含 Engine/Build/Build.version 文件的目录

    Args:
        path: 起始路径

    Returns:
        引擎根目录，如果未找到则返回 None
    """
    # 检查当前目录
    build_version = path / 'Engine' / 'Build' / 'Build.version'
    if build_version.exists():
        return path

    # 向上遍历父目录（最多5层）
    for parent in list(path.parents)[:5]:
        build_version = parent / 'Engine' / 'Build' / 'Build.version'
        if build_version.exists():
            return parent

    return None


def _is_valid_plugin_directory(path: Path) -> bool:
    """检查给定路径是否是一个有效的插件目录

    有效的插件目录：
    1. 包含 .uplugin 文件
    2. 不在引擎的 Source/Config/Content 等核心目录下

    Args:
        path: 要检查的路径

    Returns:
        True 如果是有效的插件目录
    """
    # 检查是否有 .uplugin 文件
    uplugin_files = list(path.glob('*.uplugin'))
    if not uplugin_files:
        return False

    # 检查是否在引擎子目录下（如果是，则不是独立的插件）
    if _is_engine_subdirectory(path):
        return False

    # 如果父目录是 Engine/Plugins，这可能是引擎内置插件
    # 检查是否有独立的 .Build.cs 文件（插件通常有自己的模块）
    has_build_cs = any(path.rglob('*.Build.cs'))
    if not has_build_cs:
        return False

    return True


def detect_from_cwd(cwd: Optional[Path] = None) -> DetectionInfo:
    """Auto-detect UE5 engine or plugin from current working directory.

    Detection priority（修正后）:
    1. Engine Root: 当前目录是否包含 Engine/Build/Build.version
    2. Plugin: 检查是否为独立插件目录（有 .uplugin，不在引擎子目录下）
    3. Engine Subdir: 在引擎的某个子目录下（向上能找到引擎根目录）
    4. Unknown: 无法自动检测

    Args:
        cwd: Current working directory (defaults to Path.cwd())

    Returns:
        DetectionInfo with mode, path, confidence, and reason
    """
    cwd = cwd or Path.cwd()

    # 1. 优先检测：当前目录是否是引擎根目录
    build_version = cwd / 'Engine' / 'Build' / 'Build.version'
    if build_version.exists():
        version = _read_engine_version(build_version)
        return DetectionInfo(
            mode='engine',
            detected_path=cwd,
            confidence='high',
            reason='在当前目录找到 Engine/Build/Build.version（引擎根目录）',
            suggested_name=version
        )

    # 2. 检测独立插件（必须验证不是引擎子目录）
    if _is_valid_plugin_directory(cwd):
        uplugin_files = list(cwd.glob('*.uplugin'))
        plugin_name = uplugin_files[0].stem

        # 尝试读取插件版本
        plugin_version = "unknown"
        try:
            content = uplugin_files[0].read_text(encoding='utf-8')
            plugin_data = json.loads(content)
            plugin_version = plugin_data.get("VersionName") or plugin_data.get("Version", "unknown")
        except Exception:
            pass

        return DetectionInfo(
            mode='plugin',
            detected_path=cwd,
            confidence='high',
            reason=f'在当前目录找到插件文件: {uplugin_files[0].name}（独立插件）',
            suggested_name=f"{plugin_name} v{plugin_version}" if plugin_version != "unknown" else plugin_name
        )

    # 3. 检测引擎子目录（向上查找引擎根目录）
    engine_root = _find_engine_root(cwd)
    if engine_root:
        # 计算相对路径，显示友好信息
        try:
            rel_path = cwd.relative_to(engine_root)
            location_hint = f"引擎子目录 ({rel_path})"
        except ValueError:
            location_hint = "引擎子目录"

        version_file = engine_root / 'Engine' / 'Build' / 'Build.version'
        version = _read_engine_version(version_file) if version_file.exists() else "unknown"

        return DetectionInfo(
            mode='engine_subdir',
            detected_path=engine_root,
            confidence='high',
            reason=f'检测到{location_hint}，向上找到引擎根目录',
            suggested_name=version
        )

    # 4. 无法检测
    return DetectionInfo(
        mode='unknown',
        detected_path=None,
        confidence='low',
        reason='当前目录及其父目录都未找到 UE5 引擎或插件标识文件',
        suggested_name=None
    )
