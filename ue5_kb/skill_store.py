"""Shared skill store layout and provider adapter helpers."""

from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import os
import re
import subprocess

_SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def get_default_skill_root() -> Path:
    """Return the canonical cross-provider skill store."""
    override = os.environ.get("UE5_KB_SKILL_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".agents" / "skills"


def validate_skill_name(skill_name: str) -> str:
    """Validate a provider-visible skill name before using it as a path segment."""
    name = (skill_name or "").strip()
    if (
        not name
        or name in {".", ".."}
        or ".." in name
        or "/" in name
        or "\\" in name
        or "\n" in name
        or "\r" in name
        or not _SKILL_NAME_PATTERN.fullmatch(name)
    ):
        raise ValueError(
            "Invalid skill_name. Use only letters, numbers, dot, underscore, and hyphen; "
            "path separators, '..', and control characters are not allowed."
        )
    return name


def _ensure_under_root(path: Path, root: Path) -> Path:
    root_resolved = Path(root).resolve()
    path_resolved = Path(path).resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Resolved path escapes skill root: {path_resolved}") from exc
    return path


def get_skill_path(skill_name: str, skill_root: Optional[Path] = None) -> Path:
    """Resolve a skill directory in the canonical store."""
    skill_name = validate_skill_name(skill_name)
    root = Path(skill_root) if skill_root else get_default_skill_root()
    return _ensure_under_root(root / skill_name, root)


def get_transient_kb_path(skill_path: Path, label: str = "init") -> Path:
    """Return a temporary KB path under the skill variants store."""
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return Path(skill_path) / "variants" / f"_build_tmp_{safe_label}"


def _backup_existing_path(path: Path) -> Path:
    """Rename an existing provider artifact aside before installing an adapter."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
        counter += 1
    path.rename(backup)
    return backup


def _restore_backup(backup: Optional[Path], destination: Path) -> bool:
    """Restore a provider artifact that was backed up before a failed install."""
    if not backup or not backup.exists() or destination.exists():
        return False
    backup.rename(destination)
    return True


def create_directory_link(source: Path, destination: Path, force: bool = False) -> Dict[str, str]:
    """Create a provider-visible directory link when it is safe to do so."""
    source = Path(source)
    destination = Path(destination)

    if destination.exists():
        try:
            if destination.resolve() == source.resolve():
                return {"status": "ok", "action": "exists", "path": str(destination)}
        except OSError:
            pass
        if not force:
            return {"status": "skipped", "reason": "destination_exists", "path": str(destination)}
        backup = _backup_existing_path(destination)
    else:
        backup = None

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(source), str(destination), target_is_directory=True)
        return {"status": "ok", "action": "symlink", "path": str(destination)}
    except OSError:
        pass

    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {"status": "ok", "action": "junction", "path": str(destination)}
        restored = _restore_backup(backup, destination)
        return {
            "status": "skipped",
            "reason": f"link_failed: {result.stderr.strip() or result.stdout.strip()}",
            "path": str(destination),
            "backup": str(backup) if backup else "",
            "restored": str(restored),
        }

    restored = _restore_backup(backup, destination)
    return {
        "status": "skipped",
        "reason": "link_failed",
        "path": str(destination),
        "backup": str(backup) if backup else "",
        "restored": str(restored),
    }


def write_text_if_safe(path: Path, content: str, force: bool = False) -> Dict[str, str]:
    """Write a small adapter file without overwriting unrelated content."""
    path = Path(path)
    temp_path = path.with_name(f".{path.name}.tmp")
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return {"status": "ok", "action": "exists", "path": str(path)}
        except OSError:
            pass
        if not force:
            return {"status": "skipped", "reason": "destination_exists", "path": str(path)}
        backup = _backup_existing_path(path)
    else:
        backup = None

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if temp_path.exists():
            temp_path.unlink()
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        try:
            if temp_path.exists():
                temp_path.unlink()
            if backup and path.exists():
                path.unlink()
        except OSError:
            pass
        restored = _restore_backup(backup, path)
        return {
            "status": "skipped",
            "reason": "write_failed",
            "path": str(path),
            "backup": str(backup) if backup else "",
            "restored": str(restored),
        }
    result = {"status": "ok", "action": "created", "path": str(path)}
    if backup:
        result["backup"] = str(backup)
    return result


def install_provider_adapters(skill_name: str, skill_path: Path, force: bool = False) -> Dict[str, Dict[str, str]]:
    """Expose the canonical skill to known local provider surfaces."""
    skill_name = validate_skill_name(skill_name)
    skill_path = Path(skill_path)
    home = Path.home()
    results: Dict[str, Dict[str, str]] = {}

    results["claude"] = create_directory_link(skill_path, home / ".claude" / "skills" / skill_name, force=force)
    results["opencode"] = create_directory_link(skill_path, home / ".config" / "opencode" / "skills" / skill_name, force=force)

    codex_dir = home / ".codex" / "skills" / skill_name
    codex_content = f"""---
name: {skill_name}
description: Use when querying the generated UE5 knowledge base named {skill_name}.
---

# {skill_name}

Canonical skill directory: `{skill_path}`

Before answering UE5 source questions, run:

```powershell
py "{skill_path / 'impl.py'}" preflight
py "{skill_path / 'impl.py'}" <command> [args...]
```

Use the canonical `impl.py`; this Codex adapter intentionally does not contain KB data.
"""
    results["codex"] = write_text_if_safe(codex_dir / "SKILL.md", codex_content, force=force)

    copilot_agent = home / ".copilot" / "agents" / f"{skill_name}.agent.md"
    copilot_content = f"""---
name: {skill_name}
description: Query the generated UE5 knowledge base named {skill_name}.
---

You are a thin adapter for the canonical UE5 KB skill at:

`{skill_path}`

Use PowerShell/Python to run:

`py "{skill_path / 'impl.py'}" preflight`
`py "{skill_path / 'impl.py'}" <command> [args...]`

Do not copy or rebuild the KB from this adapter.
"""
    results["copilot"] = write_text_if_safe(copilot_agent, copilot_content, force=force)

    return results
