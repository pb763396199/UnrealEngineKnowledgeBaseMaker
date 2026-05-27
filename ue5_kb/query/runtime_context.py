"""
Runtime context and preflight helpers for generated skills.

These helpers keep generated engine/plugin impl.py files thin: the template passes
its resolved KB path, source root, and BranchManager, while this module performs
the metadata and index checks in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_INDEX_FILES = (
    "index.db",
    "class_index.db",
    "function_index.db",
    "enum_index.db",
    "symbol_reference_index.db",
    "files_fts.db",
)


def _stringify_path(path_value: Optional[Path]) -> Optional[str]:
    if path_value is None:
        return None
    try:
        return str(Path(path_value))
    except TypeError:
        return None


def _active_branch_record(branch_manager: Any) -> Optional[Dict[str, Any]]:
    try:
        status = branch_manager.status()
    except Exception:
        return None

    active = status.get("active_branch")
    for branch in status.get("branches", []):
        if branch.get("active") or branch.get("branch") == active:
            return branch
    return None


def inspect_indices(kb_path: Path, index_files: Iterable[str] = DEFAULT_INDEX_FILES) -> Dict[str, Dict[str, Any]]:
    """Return existence/size information for global_index SQLite files."""
    global_index = Path(kb_path) / "global_index"
    result: Dict[str, Dict[str, Any]] = {}
    for filename in index_files:
        index_path = global_index / filename
        exists = index_path.exists()
        item: Dict[str, Any] = {
            "exists": exists,
            "path": str(index_path),
        }
        if exists:
            try:
                item["size_bytes"] = index_path.stat().st_size
            except OSError:
                item["size_bytes"] = None
        result[filename] = item
    return result


def collect_runtime_context(
    *,
    skill_dir: Path,
    kb_path: Path,
    source_root: Optional[Path],
    branch_manager: Any = None,
    index_files: Iterable[str] = DEFAULT_INDEX_FILES,
) -> Dict[str, Any]:
    """Collect branch/source/index freshness metadata without reading source files."""
    kb_path = Path(kb_path)
    source_root_path = Path(source_root) if source_root else None

    context: Dict[str, Any] = {
        "skill_dir": str(Path(skill_dir)),
        "kb_path": str(kb_path),
        "source_root": _stringify_path(source_root_path),
        "branch": None,
        "commit": None,
        "source": _stringify_path(source_root_path),
        "dirty": None,
        "fingerprint": None,
        "indices": inspect_indices(kb_path, index_files),
        "data_trust": "unknown",
    }

    required_missing = [
        name
        for name in ("index.db", "class_index.db", "function_index.db")
        if not context["indices"].get(name, {}).get("exists")
    ]
    if required_missing:
        context["missing_required_indices"] = required_missing

    if branch_manager is None:
        context["data_trust"] = "unknown"
        context["fresh"] = False
        context["stale_reason"] = "branch_manager_unavailable"
        return context

    active_record = _active_branch_record(branch_manager)
    if active_record:
        context["branch"] = active_record.get("branch")
        context["commit"] = active_record.get("commit")
        context["source"] = active_record.get("source") or context["source"]
        context["dirty"] = active_record.get("dirty")
        context["fingerprint"] = active_record.get("worktree_fingerprint")

    if source_root_path is None:
        context["fresh"] = False
        context["stale_reason"] = "source_root_missing"
        context["data_trust"] = "unknown"
        return context

    try:
        freshness = branch_manager.check_freshness(str(source_root_path))
        context["freshness"] = freshness
        context["fresh"] = bool(freshness.get("fresh"))
        context["branch"] = freshness.get("branch") or context.get("branch")
        context["commit"] = freshness.get("kb_commit") or context.get("commit")
        context["dirty"] = freshness.get("dirty")
        context["fingerprint"] = freshness.get("worktree_fingerprint")
        context["source"] = str(source_root_path)
        context["stale_reason"] = freshness.get("stale_reason")
        context["data_trust"] = "fresh" if context["fresh"] and not required_missing else "stale"
    except Exception as exc:
        context["fresh"] = False
        context["stale_reason"] = "freshness_check_failed"
        context["freshness_error"] = f"{type(exc).__name__}: {exc}"
        context["data_trust"] = "unknown"

    if required_missing:
        context["data_trust"] = "stale"
        if not context.get("stale_reason"):
            context["stale_reason"] = "missing_required_indices"

    return context


def preflight(**kwargs: Any) -> Dict[str, Any]:
    """Public alias used by generated impl.py commands."""
    return collect_runtime_context(**kwargs)
