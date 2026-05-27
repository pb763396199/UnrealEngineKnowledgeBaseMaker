"""Build and query a source-file full text index with LIKE fallback."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


INDEXED_SUFFIXES = (".h", ".hpp", ".cpp", ".inl", ".ush", ".usf")
INDEXED_BUILD_SUFFIX = ".Build.cs"
SKIP_DIR_NAMES = {
    ".git",
    ".history",
    ".hg",
    ".svn",
    ".vs",
    ".idea",
    "__pycache__",
    "Binaries",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
    "Temp",
    "Generated",
}
SKIP_DIR_NAMES_NORM = {name.lower() for name in SKIP_DIR_NAMES}
DEFAULT_MAX_FILE_BYTES = 512 * 1024


def _reset_sqlite_files(db_path: Path) -> None:
    for path in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        if path.exists():
            path.unlink()


def _is_indexed_file(path: Path) -> bool:
    return path.name.endswith(INDEXED_BUILD_SUFFIX) or path.suffix in INDEXED_SUFFIXES


def _should_skip(path: Path) -> bool:
    return any(part.lower() in SKIP_DIR_NAMES_NORM for part in path.parts)


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _module_hint(relative_path: str) -> str:
    parts = relative_path.split("/")
    if relative_path.endswith(INDEXED_BUILD_SUFFIX):
        return Path(parts[-1]).name.replace(INDEXED_BUILD_SUFFIX, "")
    if "Source" in parts:
        source_index = parts.index("Source")
        if source_index + 1 < len(parts):
            if parts[source_index + 1] in ("Runtime", "Editor", "Developer", "Programs") and source_index + 2 < len(parts):
                return parts[source_index + 2]
            return parts[source_index + 1]
    return parts[0] if parts else ""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(conn: sqlite3.Connection, *, force_disable_fts: bool = False) -> bool:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            module TEXT,
            extension TEXT,
            size_bytes INTEGER,
            content TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_module ON files(module)")
    if force_disable_fts:
        conn.commit()
        return False
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                path, module, extension, content,
                content='files', content_rowid='id'
            )
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        conn.commit()
        return False


def iter_source_files(
    source_root: Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_indexed_files: Optional[int] = None,
    max_total_bytes: Optional[int] = None,
) -> Tuple[List[Path], Dict[str, int]]:
    root = Path(source_root)
    files: List[Path] = []
    skipped = {
        "unsupported_extension": 0,
        "skipped_directory": 0,
        "large_file": 0,
        "symlink": 0,
        "file_limit": 0,
        "byte_limit": 0,
    }
    total_bytes = 0
    for current_dir, dirs, filenames in os.walk(root):
        current_path = Path(current_dir)
        kept_dirs = []
        for dirname in sorted(dirs):
            child = current_path / dirname
            if dirname.lower() in SKIP_DIR_NAMES_NORM or _should_skip(child.relative_to(root)):
                skipped["skipped_directory"] += 1
                continue
            if child.is_symlink():
                skipped["symlink"] += 1
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                skipped["symlink"] += 1
                continue
            if not _is_indexed_file(path):
                skipped["unsupported_extension"] += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skipped["unsupported_extension"] += 1
                continue
            if size > max_file_bytes:
                skipped["large_file"] += 1
                continue
            if max_indexed_files is not None and len(files) >= max_indexed_files:
                skipped["file_limit"] += 1
                continue
            if max_total_bytes is not None and total_bytes + size > max_total_bytes:
                skipped["byte_limit"] += 1
                continue
            files.append(path)
            total_bytes += size
    return files, skipped


def build_files_fts_index(
    source_root: Path,
    db_path: Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_indexed_files: Optional[int] = None,
    max_total_bytes: Optional[int] = None,
    force_disable_fts: bool = False,
) -> Dict[str, object]:
    """Build global_index/files_fts.db from source files."""
    root = Path(source_root).resolve()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _reset_sqlite_files(db_path)
    conn = _connect(db_path)
    try:
        fts_enabled = _create_schema(conn, force_disable_fts=force_disable_fts)
        files, skipped = iter_source_files(
            root,
            max_file_bytes=max_file_bytes,
            max_indexed_files=max_indexed_files,
            max_total_bytes=max_total_bytes,
        )
        rows = []
        for path in files:
            relative_path = _relative_posix(root, path)
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                size = path.stat().st_size
            except OSError:
                skipped["unsupported_extension"] += 1
                continue
            extension = INDEXED_BUILD_SUFFIX if path.name.endswith(INDEXED_BUILD_SUFFIX) else path.suffix
            rows.append((relative_path, _module_hint(relative_path), extension, size, content))

        conn.executemany(
            """
            INSERT OR REPLACE INTO files (path, module, extension, size_bytes, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        if fts_enabled:
            try:
                conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:
                fts_enabled = False
        conn.commit()
        return {
            "db_path": str(db_path),
            "indexed_count": len(rows),
            "indexed_bytes": sum(row[3] for row in rows),
            "skipped": skipped,
            "fts_enabled": fts_enabled,
        }
    finally:
        conn.close()


def _make_fts_query(keyword: str) -> str:
    tokens = [token for token in "".join(ch if ch.isalnum() or ch == "_" else " " for ch in keyword).split() if token]
    if not tokens:
        return '""'
    return " OR ".join(f"{token}*" for token in tokens)


def _make_snippet(content: str, keyword: str, max_chars: int = 240) -> str:
    lower_content = content.lower()
    lower_keyword = keyword.lower()
    index = lower_content.find(lower_keyword)
    if index < 0:
        index = 0
    start = max(0, index - max_chars // 3)
    end = min(len(content), start + max_chars)
    snippet = content[start:end].replace("\r", "").replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet += "..."
    return snippet


def _escape_like(keyword: str) -> str:
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


class FilesFtsIndex:
    """Query helper that tries MATCH first and falls back to LIKE."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = _connect(self.db_path)
        self._fts_enabled = self._detect_fts()

    def _detect_fts(self) -> bool:
        try:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='files_fts'"
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

    def search(self, keyword: str, limit: int = 20) -> Dict[str, object]:
        limit = max(1, min(int(limit), 100))
        if not keyword:
            return {"keyword": keyword, "found_count": 0, "results": [], "fallback": "empty_keyword"}
        if self._fts_enabled:
            try:
                results = self._search_fts(keyword, limit)
                if not results:
                    results = self._search_like(keyword, limit)
                    return {
                        "keyword": keyword,
                        "found_count": len(results),
                        "results": results,
                        "fallback": "like_after_match_empty",
                    }
                return {"keyword": keyword, "found_count": len(results), "results": results, "fallback": None}
            except sqlite3.OperationalError as exc:
                results = self._search_like(keyword, limit)
                return {
                    "keyword": keyword,
                    "found_count": len(results),
                    "results": results,
                    "fallback": "like_after_match_error",
                    "fallback_error": str(exc),
                }
        results = self._search_like(keyword, limit)
        return {"keyword": keyword, "found_count": len(results), "results": results, "fallback": "like_no_fts"}

    def _search_fts(self, keyword: str, limit: int) -> List[Dict[str, object]]:
        cursor = self.conn.execute(
            """
            SELECT f.path, f.module, f.extension,
                     snippet(files_fts, 3, '[', ']', '...', 12) AS snippet,
                     rank AS rank
            FROM files_fts
            JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (_make_fts_query(keyword), limit),
        )
        rows = []
        for row in cursor.fetchall():
            item = dict(row)
            item["ranking_reason"] = "fts_rank"
            rows.append(item)
        return rows

    def _search_like(self, keyword: str, limit: int) -> List[Dict[str, object]]:
        pattern = f"%{_escape_like(keyword)}%"
        cursor = self.conn.execute(
            """
            SELECT path, module, extension, content
            FROM files
            WHERE path LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'
            ORDER BY path ASC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        )
        rows = []
        for row in cursor.fetchall():
            item = dict(row)
            content = item.pop("content", "")
            item["snippet"] = _make_snippet(content, keyword)
            item["rank"] = None
            item["ranking_reason"] = "like_fallback"
            rows.append(item)
        return rows

    def close(self) -> None:
        self.conn.close()


def search_files(db_path: Path, keyword: str, limit: int = 20) -> Dict[str, object]:
    db_path = Path(db_path)
    if not db_path.exists():
        return {"keyword": keyword, "found_count": 0, "results": [], "error": "files_fts.db not found"}
    index = FilesFtsIndex(db_path)
    try:
        return index.search(keyword, limit)
    finally:
        index.close()
