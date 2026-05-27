"""Safe source slicing helpers used by generated skills."""

from __future__ import annotations

import os
import bisect
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


_CONTROL_BLOCK_KEYWORDS = {
    "if",
    "else",
    "for",
    "while",
    "switch",
    "catch",
    "do",
    "try",
    "case",
    "default",
}

_TYPE_BLOCK_KEYWORDS = {
    "class",
    "struct",
    "namespace",
    "enum",
    "union",
}

_ACCESS_SPECIFIER_LABELS = {
    "public:",
    "protected:",
    "private:",
}


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _offset_to_line(offset: int, line_starts: List[int]) -> int:
    return bisect.bisect_right(line_starts, offset) - 1


def _scan_brace_blocks(text: str) -> List[Tuple[int, int]]:
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    stack: List[int] = []
    blocks: List[Tuple[int, int]] = []
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
                stack.append(index)
            elif char == "}" and stack:
                blocks.append((stack.pop(), index))
        index += 1
    return blocks


def _signature_start_offset(text: str, open_offset: int, line_starts: List[int]) -> int:
    search_start = max(0, open_offset - 12000)
    depth = 0
    index = open_offset - 1
    while index >= search_start:
        char = text[index]
        if char in ")]>":
            depth += 1
        elif char in "([<" and depth > 0:
            depth -= 1
        elif depth == 0 and char in ";{}":
            return index + 1
        index -= 1
    return search_start


def _last_identifier_before_paren(header: str) -> str:
    paren_index = header.find("(")
    if paren_index < 0:
        return ""
    index = paren_index - 1
    while index >= 0 and header[index].isspace():
        index -= 1
    end = index + 1
    while index >= 0 and (header[index].isalnum() or header[index] == "_"):
        index -= 1
    return header[index + 1 : end]


def _starts_with_keyword(header: str, keyword: str) -> bool:
    return header == keyword or header.startswith(f"{keyword} ") or header.startswith(f"{keyword}(")


def _is_header_separator_line(stripped_line: str) -> bool:
    return (
        not stripped_line
        or stripped_line in _ACCESS_SPECIFIER_LABELS
        or stripped_line.startswith("#")
        or stripped_line.startswith("//")
        or stripped_line.startswith("/*")
        or stripped_line.startswith("*")
    )


def _refine_function_header_start(text: str, signature_offset: int, open_offset: int) -> Tuple[int, str]:
    header = text[signature_offset:open_offset]
    lines = header.splitlines(keepends=True)
    if not lines:
        return signature_offset, header

    line_offsets: List[int] = []
    cursor = 0
    for line in lines:
        line_offsets.append(cursor)
        cursor += len(line)

    end_line = len(lines) - 1
    while end_line >= 0 and not lines[end_line].strip():
        end_line -= 1
    if end_line < 0:
        return signature_offset, ""

    start_line = end_line
    while start_line >= 0:
        stripped = lines[start_line].strip()
        if _is_header_separator_line(stripped):
            break
        start_line -= 1
    start_line += 1
    if start_line > end_line:
        return signature_offset, ""

    refined_offset = signature_offset + line_offsets[start_line]
    refined_header = "".join(lines[start_line : end_line + 1])
    return refined_offset, refined_header


def _looks_like_function_header(header: str) -> bool:
    compact = " ".join(header.strip().split())
    if not compact or "(" not in compact or ")" not in compact:
        return False
    if any(char in compact for char in "{};"):
        return False
    if "[]" in compact or compact.startswith("["):
        return False
    for keyword in _CONTROL_BLOCK_KEYWORDS | _TYPE_BLOCK_KEYWORDS:
        if _starts_with_keyword(compact, keyword):
            return False
    keyword = _last_identifier_before_paren(compact)
    if keyword in _CONTROL_BLOCK_KEYWORDS:
        return False
    return True


def _find_containing_function_block(
    lines: List[str],
    line_number: int,
    *,
    max_function_lines: int = 5000,
) -> Optional[Tuple[int, int, List[str]]]:
    return SourceFunctionBlockCache(lines).extract_function_block(
        line_number,
        max_function_lines=max_function_lines,
    )


class SourceFunctionBlockCache:
    """Cache brace-block scanning for repeated function lookups in one file."""

    def __init__(self, lines: List[str]) -> None:
        self.lines = lines
        self._text: Optional[str] = None
        self._starts: Optional[List[int]] = None
        self._blocks: Optional[List[Tuple[int, int]]] = None
        self.scan_count = 0

    def _ensure_scanned(self) -> None:
        if self._blocks is not None:
            return
        self._text = "".join(self.lines)
        self._starts = _line_starts(self._text)
        self._blocks = _scan_brace_blocks(self._text)
        self.scan_count += 1

    def extract_function_block(
        self,
        line_number: int,
        *,
        max_function_lines: int = 5000,
    ) -> Optional[Tuple[int, int, List[str]]]:
        if line_number <= 0 or not self.lines:
            return None

        self._ensure_scanned()
        text = self._text or ""
        starts = self._starts or [0]
        blocks = self._blocks or []
        requested_index = min(max(0, line_number - 1), len(self.lines) - 1)
        candidates: List[Tuple[int, int, int, int]] = []

        for open_offset, close_offset in blocks:
            open_line = _offset_to_line(open_offset, starts)
            close_line = _offset_to_line(close_offset, starts)
            if close_line - open_line + 1 > max_function_lines:
                continue
            signature_offset = _signature_start_offset(text, open_offset, starts)
            signature_offset, header = _refine_function_header_start(text, signature_offset, open_offset)
            signature_line = _offset_to_line(signature_offset, starts)
            if not (signature_line <= requested_index <= close_line):
                continue
            if not _looks_like_function_header(header):
                continue
            candidates.append((signature_line, close_line, open_line, close_offset - open_offset))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[1] - item[0], item[0]))
        start_index, end_index, _open_line, _span = candidates[0]
        return start_index + 1, end_index + 1, self.lines[start_index : end_index + 1]


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

    containing = _find_containing_function_block(
        lines,
        line_number,
        max_function_lines=max_function_lines,
    )
    if containing:
        return containing
    return None


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
