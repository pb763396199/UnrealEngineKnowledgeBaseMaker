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


def detect_from_cwd(cwd: Optional[Path] = None) -> DetectionInfo:
    """Auto-detect UE5 engine or plugin from current working directory.

    Detection priority:
    1. Plugin: Check for .uplugin file in current directory
    2. Engine: Check for Engine/Build/Build.version in current directory
    3. Engine Subdir: Check parent directories for Engine/Build/Build.version
    4. Unknown: No automatic detection possible

    Args:
        cwd: Current working directory (defaults to Path.cwd())

    Returns:
        DetectionInfo with mode, path, confidence, and reason
    """
    cwd = cwd or Path.cwd()

    # 1. 检测插件（最高优先级）
    uplugin_files = list(cwd.glob('*.uplugin'))
    if uplugin_files:
        return DetectionInfo(
            mode='plugin',
            detected_path=cwd,
            confidence='high',
            reason=f'在当前目录找到 .uplugin 文件: {uplugin_files[0].name}',
            suggested_name=uplugin_files[0].stem
        )

    # 2. 检测引擎（当前目录）
    build_version = cwd / 'Engine' / 'Build' / 'Build.version'
    if build_version.exists():
        version = _read_engine_version(build_version)
        return DetectionInfo(
            mode='engine',
            detected_path=cwd,
            confidence='high',
            reason='在当前目录找到 Engine/Build/Build.version',
            suggested_name=version
        )

    # 3. 检测引擎（父目录遍历，最多5层）
    for level, parent in enumerate([cwd, *cwd.parents][:5]):
        build_version = parent / 'Engine' / 'Build' / 'Build.version'
        if build_version.exists():
            version = _read_engine_version(build_version)
            return DetectionInfo(
                mode='engine_subdir',
                detected_path=parent,
                confidence='medium',
                reason=f'在第 {level} 层父目录找到引擎根目录',
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
