"""
Knowledge Base Manifest Management

Defines data structures and I/O for KB version tracking and change detection.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from datetime import datetime
from pathlib import Path
import json
import hashlib


@dataclass
class FileInfo:
    """Information about a single source file"""

    path: str  # Relative path from base
    sha256: str  # File hash
    size: int  # File size in bytes
    mtime: float  # Modification timestamp

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileInfo":
        return cls(
            path=data["path"],
            sha256=data["sha256"],
            size=data["size"],
            mtime=data["mtime"]
        )


@dataclass
class ModuleManifest:
    """Manifest for a single module"""

    module_name: str
    build_cs_path: str
    category: str
    files: Dict[str, FileInfo] = field(default_factory=dict)
    module_hash: str = ""
    indexed_at: str = ""
    parser_version: str = ""

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "build_cs_path": self.build_cs_path,
            "category": self.category,
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "module_hash": self.module_hash,
            "indexed_at": self.indexed_at,
            "parser_version": self.parser_version
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleManifest":
        files = {
            k: FileInfo.from_dict(v)
            for k, v in data.get("files", {}).items()
        }
        return cls(
            module_name=data["module_name"],
            build_cs_path=data["build_cs_path"],
            category=data["category"],
            files=files,
            module_hash=data.get("module_hash", ""),
            indexed_at=data.get("indexed_at", ""),
            parser_version=data.get("parser_version", "")
        )


@dataclass
class KBManifest:
    """Knowledge base manifest (root level)"""

    kb_version: str  # KB format version (from pyproject.toml)
    engine_version: str  # Detected UE5 engine version
    engine_path: str  # Absolute path to engine
    plugin_name: Optional[str]  # For plugin mode
    created_at: str  # ISO timestamp
    last_updated: str  # ISO timestamp
    build_mode: str  # "engine" or "plugin"
    tool_version: str  # ue5kb tool version
    files: Dict[str, dict] = field(default_factory=dict)  # module_name -> {build_cs, sources}
    modules: Dict[str, dict] = field(default_factory=dict)  # module_name -> metadata
    statistics: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kb_version": self.kb_version,
            "engine_version": self.engine_version,
            "engine_path": self.engine_path,
            "plugin_name": self.plugin_name,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "build_mode": self.build_mode,
            "tool_version": self.tool_version,
            "files": self.files,
            "modules": self.modules,
            "statistics": self.statistics
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KBManifest":
        return cls(
            kb_version=data["kb_version"],
            engine_version=data["engine_version"],
            engine_path=data["engine_path"],
            plugin_name=data.get("plugin_name"),
            created_at=data["created_at"],
            last_updated=data["last_updated"],
            build_mode=data["build_mode"],
            tool_version=data["tool_version"],
            files=data.get("files", {}),
            modules=data.get("modules", {}),
            statistics=data.get("statistics", {})
        )

    def save(self, kb_path: Path) -> None:
        """Save manifest to KnowledgeBase/.kb_manifest.json"""
        manifest_file = kb_path / ".kb_manifest.json"
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, kb_path: Path) -> Optional["KBManifest"]:
        """Load manifest from KnowledgeBase/.kb_manifest.json"""
        manifest_file = kb_path / ".kb_manifest.json"
        if not manifest_file.exists():
            return None
        with open(manifest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)


class Hasher:
    """File hashing utilities"""

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """
        Compute SHA256 hash of a file

        Args:
            file_path: Path to the file

        Returns:
            Hexadecimal SHA256 hash string
        """
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def compute_module_hash(
        build_cs_path: Path,
        source_files: List[Path]
    ) -> str:
        """
        Compute combined hash for a module

        Args:
            build_cs_path: Path to the .Build.cs file
            source_files: List of source file paths

        Returns:
            Hexadecimal SHA256 hash string
        """
        hasher = hashlib.sha256()

        # Include build.cs
        hasher.update(build_cs_path.read_bytes())

        # Include all source files (sorted for consistency)
        for file_path in sorted(source_files):
            hasher.update(file_path.read_bytes())

        return hasher.hexdigest()
