"""Safe source slicing helpers used by generated skills."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Dict, List, Optional, Tuple


DEFAULT_MAX_CONTEXT_LINES = 200
DEFAULT_MAX_OUTPUT_CHARS = 20000


class SourceSliceError(ValueError):
    """Raised when a source_slice request is invalid or unsafe."""


def _reject_unsafe_relative_path(relative_file: str) -> List[str]:
    if relative_file is None:
        raise SourceSliceError("relative path is required")
    if "\x00" in relative_file:
        raise SourceSliceError("NUL byte is not allowed")

    raw = str(relative_file).strip()
    if not raw:
        raise SourceSliceError("empty path is not allowed")
    if raw.startswith("//") or raw.startswith("\\\\"):
        raise SourceSliceError("UNC paths are not allowed")
    if raw.startswith("/") or raw.startswith("\\"):
        raise SourceSliceError("absolute paths are not allowed")

    windows_path = PureWindowsPath(raw)
    if windows_path.drive or windows_path.root or windows_path.is_absolute():
        raise SourceSliceError("drive-qualified or absolute paths are not allowed")

    parts = [part for part in raw.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts:
        raise SourceSliceError("empty path is not allowed")
    if any(part == ".." for part in parts):
        raise SourceSliceError("parent traversal is not allowed")
    return parts


def safe_resolve_source_path(source_root: Path, relative_file: str) -> Path:
    """Resolve a source-root-relative path and reject any escape."""
    if source_root is None:
        raise SourceSliceError("source_root is not available")
    root = Path(source_root).resolve(strict=True)
    parts = _reject_unsafe_relative_path(relative_file)
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"source file not found: {'/'.join(parts)}")

    try:
        common = os.path.commonpath([str(root), str(resolved)])
    except ValueError:
        raise SourceSliceError("resolved path is outside source_root")
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise SourceSliceError("resolved path is outside source_root")
    if not resolved.is_file():
        raise SourceSliceError("resolved path is not a file")
    return resolved


def _find_first_open_brace_offset(text: str) -> int:
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
        elif in_block_comment:
            if char == "*" and index + 1 < len(text) and text[index + 1] == "/":
                in_block_comment = False
                index += 1
        elif in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif in_char:
            if char == "\\":
                index += 1
            elif char == "'":
                in_char = False
        else:
            if char == "/" and index + 1 < len(text):
                if text[index + 1] == "/":
                    in_line_comment = True
                    index += 1
                elif text[index + 1] == "*":
                    in_block_comment = True
                    index += 1
            elif char == '"':
                in_string = True
            elif char == "'":
                in_char = True
            elif char == "{":
                return index
        index += 1
    return -1


def _find_matching_close_brace_offset(text: str) -> int:
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    brace_count = 0
    index = 0
    while index < len(text):
        char = text[index]
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
        elif in_block_comment:
            if char == "*" and index + 1 < len(text) and text[index + 1] == "/":
                in_block_comment = False
                index += 1
        elif in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif in_char:
            if char == "\\":
                index += 1
            elif char == "'":
                in_char = False
        else:
            if char == "/" and index + 1 < len(text):
                if text[index + 1] == "/":
                    in_line_comment = True
                    index += 1
                elif text[index + 1] == "*":
                    in_block_comment = True
                    index += 1
            elif char == '"':
                in_string = True
            elif char == "'":
                in_char = True
            elif char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return index
        index += 1
    return -1


def extract_function_block(
    lines: List[str],
    line_number: int,
    *,
    max_signature_scan: int = 30,
    max_function_lines: int = 5000,
) -> Optional[Tuple[int, int, List[str]]]:
    """Extract a brace-delimited function block near a 1-based line number."""
    if line_number <= 0 or not lines:
        return None

    total = len(lines)
    start_index = min(max(0, line_number - 1), total - 1)
    search_end = min(start_index + max_signature_scan, total)
    search_text = "".join(lines[start_index:search_end])
    brace_offset = _find_first_open_brace_offset(search_text)
    if brace_offset < 0:
        return None

    scan_end = min(start_index + max_function_lines, total)
    combined = "".join(lines[start_index:scan_end])
    close_offset = _find_matching_close_brace_offset(combined[brace_offset:])
    if close_offset < 0:
        return None

    end_index = start_index + combined[: brace_offset + close_offset + 1].count("\n")
    return start_index + 1, end_index + 1, lines[start_index : end_index + 1]


def slice_source(
    *,
    source_root: Path,
    relative_file: str,
    line_number: int,
    mode: str = "context",
    context_lines: int = 8,
    max_context_lines: int = DEFAULT_MAX_CONTEXT_LINES,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> Dict[str, object]:
    """Return a bounded source snippet in context or function mode."""
    if mode not in ("context", "function"):
        raise SourceSliceError("mode must be 'context' or 'function'")
    if line_number <= 0:
        raise SourceSliceError("line number must be positive")

    resolved = safe_resolve_source_path(source_root, relative_file)
    normalized_file = "/".join(_reject_unsafe_relative_path(relative_file))
    lines = resolved.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    if not lines:
        return {
            "file": normalized_file,
            "line_start": 1,
            "line_end": 0,
            "requested_line": line_number,
            "requested_mode": mode,
            "mode": "context",
            "boundary_hit": False,
            "truncated": False,
            "truncation_reasons": [],
            "max_context_lines": max_context_lines,
            "max_output_chars": max_output_chars,
            "content": "",
        }

    requested_line = min(line_number, len(lines))
    boundary_hit = False
    actual_mode = mode
    truncated = False
    truncation_reasons: List[str] = []
    block = extract_function_block(lines, requested_line) if mode == "function" else None
    if block:
        start_line, end_line, selected = block
        boundary_hit = True
    else:
        actual_mode = "context"
        requested_context_lines = max(0, int(context_lines))
        bounded_context_lines = min(requested_context_lines, max(0, int(max_context_lines)))
        if bounded_context_lines < requested_context_lines:
            truncated = True
            truncation_reasons.append("max_context_lines")
        start_line = max(1, requested_line - bounded_context_lines)
        end_line = min(len(lines), requested_line + bounded_context_lines)
        selected = lines[start_line - 1 : end_line]

    original_line_end = end_line
    max_chars = max(1, int(max_output_chars))
    content = "".join(selected)
    if len(content) > max_chars:
        content = content[:max_chars]
        truncated = True
        truncation_reasons.append("max_output_chars")
        returned_line_count = content.count("\n")
        if content and not content.endswith("\n"):
            returned_line_count += 1
        end_line = start_line + max(0, returned_line_count - 1)

    return {
        "file": normalized_file,
        "line_start": start_line,
        "line_end": end_line,
        "original_line_end": original_line_end,
        "requested_line": line_number,
        "requested_mode": mode,
        "mode": actual_mode,
        "boundary_hit": boundary_hit,
        "truncated": truncated,
        "truncation_reasons": truncation_reasons,
        "max_context_lines": max_context_lines,
        "max_output_chars": max_output_chars,
        "content": content,
    }
