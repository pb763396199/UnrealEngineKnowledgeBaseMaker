"""
UE5 知识库系统 - 符号调用/引用图谱索引

从函数实现体中提取：
  - call: 对已知函数的调用（relation_type='call'）
  - type_reference: 对已知类名的引用（relation_type='type_reference'）

SQLite 路径: global_index/symbol_reference_index.db
"""

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# C++ 关键字及常见控制语句，避免将其识别为函数调用目标
_CPP_KEYWORDS: Set[str] = {
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "break", "continue", "default", "sizeof", "alignof", "new", "delete",
    "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
    "true", "false", "nullptr", "this", "auto", "try", "catch", "throw",
    "template", "typename", "class", "struct", "enum", "namespace",
    "operator", "virtual", "override", "final", "explicit", "inline",
    "extern", "static", "const", "constexpr", "volatile", "mutable",
    "public", "private", "protected", "friend", "typedef", "using",
    "decltype", "noexcept", "assert", "check", "verify", "ensure",
    "TEXT", "TCHAR",
}


class SymbolReferenceIndex:
    """
    符号调用/引用图谱索引

    功能：
    - 基于 SQLite 存储函数调用和类型引用关系
    - 支持 query_callees / query_callers / query_symbol_references 快速查询
    """

    def __init__(self, db_path: str) -> None:
        """
        初始化索引

        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbol_references (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                caller_name      TEXT NOT NULL,
                caller_class     TEXT,
                caller_module    TEXT,
                caller_file      TEXT,
                caller_line      INTEGER,
                target_symbol    TEXT NOT NULL,
                target_kind      TEXT,
                target_class     TEXT,
                target_module    TEXT,
                target_file      TEXT,
                target_line      INTEGER,
                relation_type    TEXT,
                occurrence_file  TEXT,
                occurrence_line  INTEGER,
                expression       TEXT,
                confidence       TEXT,
                candidate_count  INTEGER DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_caller "
            "ON symbol_references(caller_name, caller_class)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_target "
            "ON symbol_references(target_symbol)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_target_class "
            "ON symbol_references(target_symbol, target_class)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_relation "
            "ON symbol_references(relation_type)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # 构建接口
    # ------------------------------------------------------------------

    def build_from_indices(
        self,
        function_index_db: str,
        class_index_db: str,
        max_callers: int = 0,
        source_root: Optional[Any] = None,
    ) -> Dict[str, int]:
        """
        从已有的 function_index.db 和 class_index.db 构建符号引用图谱

        Args:
            function_index_db: function_index.db 路径
            class_index_db:    class_index.db 路径
            max_callers:       最多处理多少个 caller（0 = 全部）
            source_root:       源码根目录；用于将 impl_file_path 相对路径解析为绝对路径

        Returns:
            {"callers_processed": N, "callers_skipped": N, "rows_inserted": N}
        """
        self.conn.execute("DELETE FROM symbol_references")
        self.conn.commit()

        fi_path = Path(function_index_db)
        ci_path = Path(class_index_db)

        if not fi_path.exists():
            return {"error": "function_index.db not found", "rows_inserted": 0,
                    "callers_processed": 0, "callers_skipped": 0}

        # ---- 读取所有函数（name → list[record]）--------------------------
        fi_conn = sqlite3.connect(str(fi_path))
        fi_conn.row_factory = sqlite3.Row
        func_by_name: Dict[str, List[Dict]] = {}
        for row in fi_conn.execute(
            "SELECT name, class_name, module, file_path, line_number, "
            "impl_file_path, impl_line_number FROM function_index"
        ):
            rec = dict(row)
            func_by_name.setdefault(rec["name"], []).append(rec)
        fi_conn.close()

        # ---- 读取所有类名 ------------------------------------------------
        known_classes: Dict[str, Dict] = {}
        if ci_path.exists():
            ci_conn = sqlite3.connect(str(ci_path))
            ci_conn.row_factory = sqlite3.Row
            try:
                for row in ci_conn.execute(
                    "SELECT name, module, file_path, line_number FROM class_index"
                ):
                    rec = dict(row)
                    known_classes[rec["name"]] = rec
            except sqlite3.OperationalError:
                known_classes = {}
            ci_conn.close()

        known_func_names: Set[str] = set(func_by_name.keys()) - _CPP_KEYWORDS
        known_class_names: Set[str] = set(known_classes.keys()) - _CPP_KEYWORDS

        # ---- 收集 caller 列表（有唯一 impl 的函数）-----------------------
        callers: List[Dict] = []
        seen_impl: Set[Tuple] = set()
        for records in func_by_name.values():
            for rec in records:
                impl_file = rec.get("impl_file_path", "") or ""
                impl_line = rec.get("impl_line_number", 0) or 0
                if not impl_file or not impl_line:
                    continue
                key = (impl_file, impl_line)
                if key in seen_impl:
                    continue
                seen_impl.add(key)
                callers.append(rec)

        if max_callers > 0:
            callers = callers[:max_callers]

        # ---- 处理每个 caller --------------------------------------------
        batch: List[Tuple] = []
        processed = 0
        skipped = 0
        rows_inserted = 0

        for caller in callers:
            impl_file = caller.get("impl_file_path", "") or ""
            impl_line = caller.get("impl_line_number", 0) or 0
            caller_name = caller.get("name", "") or ""
            caller_class = caller.get("class_name", "") or ""
            caller_module = caller.get("module", "") or ""
            caller_decl_file = caller.get("file_path", "") or ""
            caller_decl_line = caller.get("line_number", 0) or 0

            body_lines, body_start = _slice_function_body(impl_file, impl_line, source_root=source_root)
            if body_lines is None:
                skipped += 1
                continue

            processed += 1

            # 提取函数调用
            for qualifier, target_name, occ_line, expr in _extract_calls(
                body_lines, body_start, known_func_names
            ):
                candidates = func_by_name[target_name]
                candidate_count = len(candidates)
                best, confidence = _select_function_candidate(
                    candidates,
                    caller_class=caller_class,
                    qualifier=qualifier,
                )
                batch.append((
                    caller_name, caller_class, caller_module,
                    caller_decl_file, caller_decl_line,
                    target_name, "function",
                    best.get("class_name", "") or "",
                    best.get("module", "") or "",
                    best.get("file_path", "") or "",
                    best.get("line_number", 0) or 0,
                    "call",
                    impl_file, occ_line,
                    expr,
                    confidence, candidate_count,
                ))

            # 提取类型引用（每个类名每个函数体只记录一次首次出现）
            for class_name, occ_line, expr in _extract_type_refs(
                body_lines, body_start, known_class_names,
                exclude_class=caller_class,
            ):
                cls_rec = known_classes[class_name]
                batch.append((
                    caller_name, caller_class, caller_module,
                    caller_decl_file, caller_decl_line,
                    class_name, "class",
                    "",
                    cls_rec.get("module", "") or "",
                    cls_rec.get("file_path", "") or "",
                    cls_rec.get("line_number", 0) or 0,
                    "type_reference",
                    impl_file, occ_line,
                    expr,
                    "resolved", 1,
                ))

            if len(batch) >= 2000:
                self._insert_batch(batch)
                rows_inserted += len(batch)
                batch.clear()

        if batch:
            self._insert_batch(batch)
            rows_inserted += len(batch)

        return {
            "callers_processed": processed,
            "callers_skipped": skipped,
            "rows_inserted": rows_inserted,
        }

    def _insert_batch(self, batch: List[Tuple]) -> None:
        self.conn.executemany(
            """
            INSERT INTO symbol_references (
                caller_name, caller_class, caller_module, caller_file, caller_line,
                target_symbol, target_kind, target_class, target_module,
                target_file, target_line,
                relation_type, occurrence_file, occurrence_line, expression,
                confidence, candidate_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            batch,
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def query_callees(
        self,
        function_name: str,
        class_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """查询某函数调用的所有目标（callees）"""
        if class_name:
            cursor = self.conn.execute(
                "SELECT * FROM symbol_references "
                "WHERE caller_name=? AND caller_class=? AND relation_type='call' "
                "ORDER BY occurrence_line LIMIT ?",
                (function_name, class_name, limit),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM symbol_references "
                "WHERE caller_name=? AND relation_type='call' "
                "ORDER BY occurrence_line LIMIT ?",
                (function_name, limit),
            )
        return [dict(r) for r in cursor.fetchall()]

    def query_callers(
        self,
        function_name: str,
        class_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """查询调用某函数的所有 callers"""
        if class_name:
            cursor = self.conn.execute(
                "SELECT * FROM symbol_references "
                "WHERE target_symbol=? AND target_class=? AND relation_type='call' "
                "ORDER BY caller_name LIMIT ?",
                (function_name, class_name, limit),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM symbol_references "
                "WHERE target_symbol=? AND relation_type='call' "
                "ORDER BY caller_name LIMIT ?",
                (function_name, limit),
            )
        return [dict(r) for r in cursor.fetchall()]

    def query_symbol_references(
        self,
        symbol_name: str,
        limit: int = 50,
    ) -> List[Dict]:
        """查询所有引用某 symbol 的记录（call 或 type_reference）"""
        cursor = self.conn.execute(
            "SELECT * FROM symbol_references "
            "WHERE target_symbol=? "
            "ORDER BY relation_type, caller_name LIMIT ?",
            (symbol_name, limit),
        )
        return [dict(r) for r in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, int]:
        """获取索引统计信息"""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM symbol_references"
        ).fetchone()[0]
        calls = self.conn.execute(
            "SELECT COUNT(*) FROM symbol_references WHERE relation_type='call'"
        ).fetchone()[0]
        type_refs = self.conn.execute(
            "SELECT COUNT(*) FROM symbol_references WHERE relation_type='type_reference'"
        ).fetchone()[0]
        return {"total": total, "calls": calls, "type_references": type_refs}

    def close(self) -> None:
        self.conn.close()


# ===========================================================================
# 公共入口：供 build 阶段调用
# ===========================================================================

def build_from_config(config: Any, source_root: Optional[Any] = None) -> Dict[str, Any]:
    """
    从 Config 对象构建符号引用索引

    BuildStage 和 ParallelBuildStage 共用此函数，避免重复实现。

    Args:
        config:      Config 对象（需有 global_index_path 属性）
        source_root: 源码根目录；传给 build_from_indices 用于解析相对 impl_file_path

    Returns:
        统计字典
    """
    global_index_path = Path(config.global_index_path)
    fi_db = str(global_index_path / "function_index.db")
    ci_db = str(global_index_path / "class_index.db")
    sr_db = str(global_index_path / "symbol_reference_index.db")

    if not Path(fi_db).exists():
        print("  [符号索引] function_index.db 不存在，跳过")
        return {"rows_inserted": 0, "callers_processed": 0, "callers_skipped": 0}

    print("  构建符号引用索引（call graph）...")

    idx = SymbolReferenceIndex(sr_db)
    try:
        build_stats = idx.build_from_indices(fi_db, ci_db, source_root=source_root)
        final_stats = idx.get_statistics()
    finally:
        idx.close()

    print(
        f"    caller 处理: {build_stats.get('callers_processed', 0)}, "
        f"跳过: {build_stats.get('callers_skipped', 0)}"
    )
    print(
        f"    调用关系: {final_stats.get('calls', 0)} 条, "
        f"类型引用: {final_stats.get('type_references', 0)} 条"
    )
    return {**build_stats, **final_stats}


# ===========================================================================
# 内部工具函数
# ===========================================================================

def _slice_function_body(
    impl_file: str,
    impl_line: int,
    source_root: Optional[Any] = None,
) -> Tuple[Optional[List[str]], int]:
    """
    从源文件切片函数体

    Args:
        impl_file:   实现文件路径（绝对或相对 POSIX 路径）
        impl_line:   函数定义起始行号（1-based）
        source_root: 源码根目录；当 impl_file 为相对路径时用于拼接为绝对路径

    Returns:
        (body_lines, first_brace_line_1based) 或 (None, 0) 表示失败
    """
    impl_path = Path(impl_file)
    if impl_path.is_absolute():
        resolved = impl_path
    elif source_root is not None:
        # 将 Windows 反斜杠规范化为 POSIX 路径后拼接
        normalized = impl_file.replace("\\", "/")
        resolved = Path(source_root) / normalized
    else:
        resolved = impl_path
    try:
        with open(resolved, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
    except OSError:
        return None, 0

    total = len(all_lines)
    start_idx = max(0, impl_line - 1)  # 0-based

    # 在 impl_line 往后最多 30 行内找首个 '{'
    search_end = min(start_idx + 30, total)
    combined = "".join(all_lines[start_idx:search_end])

    brace_start_idx = _find_first_open_brace(combined, start_idx)
    if brace_start_idx < 0:
        return None, 0

    # 从 brace_start_idx 行做 brace 计数，最多扫 5000 行
    scan_end = min(brace_start_idx + 5000, total)
    flat = "".join(all_lines[brace_start_idx:scan_end])
    body_end_offset = _find_matching_close_brace(flat)
    if body_end_offset < 0:
        return None, 0

    body_end_line = brace_start_idx + flat[:body_end_offset].count("\n")
    body_lines = all_lines[brace_start_idx : body_end_line + 1]
    if body_lines and "{" in body_lines[0]:
        body_lines[0] = body_lines[0].split("{", 1)[1]
    return body_lines, brace_start_idx + 1  # 1-based


def _find_first_open_brace(text: str, base_line_idx: int) -> int:
    """
    在 text 中找第一个裸 '{'（跳过字符串/注释内的）

    Returns:
        源文件中的行索引（0-based），找不到返回 -1
    """
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            if c == "*" and i + 1 < len(text) and text[i + 1] == "/":
                in_block_comment = False
                i += 1
        elif in_string:
            if c == "\\" :
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == "\\":
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == "/" and i + 1 < len(text):
                if text[i + 1] == "/":
                    in_line_comment = True
                    i += 1
                elif text[i + 1] == "*":
                    in_block_comment = True
                    i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == "{":
                line_offset = text[:i].count("\n")
                return base_line_idx + line_offset
        i += 1
    return -1


def _find_matching_close_brace(text: str) -> int:
    """
    在 text 中找与首个 '{' 匹配的 '}'，返回其在 text 中的字符偏移；失败返回 -1
    """
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    brace_count = 0
    i = 0
    while i < len(text):
        c = text[i]
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            if c == "*" and i + 1 < len(text) and text[i + 1] == "/":
                in_block_comment = False
                i += 1
        elif in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == "\\":
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == "/" and i + 1 < len(text):
                if text[i + 1] == "/":
                    in_line_comment = True
                    i += 1
                elif text[i + 1] == "*":
                    in_block_comment = True
                    i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == "{":
                brace_count += 1
            elif c == "}":
                brace_count -= 1
                if brace_count == 0:
                    return i
        i += 1
    return -1


_CALL_RE = re.compile(
    r"\b(?:(?P<qualifier>[A-Za-z_][A-Za-z0-9_]*)\s*::\s*)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s*<[^>]*>)?\s*\("
)
_WORD_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def _strip_line_comment(line: str) -> str:
    """去除行注释 //（简单实现，不处理字符串内的 //）"""
    line = re.sub(r"/\*.*?\*/", "", line)
    in_string = False
    for i, c in enumerate(line):
        if c == '"':
            in_string = not in_string
        elif not in_string and c == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i]
    return line


def _extract_calls(
    body_lines: List[str],
    body_start_line: int,
    known_func_names: Set[str],
) -> List[Tuple[str, str, int, str]]:
    """
    从函数体中提取对已知函数名的调用

    Returns:
        [(qualifier, target_name, occurrence_line_1based, expression), ...]
    """
    results = []
    for idx, line in enumerate(body_lines):
        stripped = _strip_line_comment(line)
        for m in _CALL_RE.finditer(stripped):
            name = m.group("name")
            if name in known_func_names:
                qualifier = m.group("qualifier") or ""
                results.append((qualifier, name, body_start_line + idx, stripped.strip()[:80]))
    return results


def _select_function_candidate(
    candidates: List[Dict],
    caller_class: str,
    qualifier: str = "",
) -> Tuple[Dict, str]:
    """选择最可信的函数目标，无法唯一判定时保留 ambiguous。"""
    if qualifier:
        qualified = [c for c in candidates if (c.get("class_name") or "") == qualifier]
        if len(qualified) == 1:
            return qualified[0], "resolved"
        if qualified:
            return qualified[0], "ambiguous"

    if caller_class:
        same_class = [c for c in candidates if (c.get("class_name") or "") == caller_class]
        if len(same_class) == 1:
            return same_class[0], "resolved"
        if same_class:
            return same_class[0], "ambiguous"

    if len(candidates) == 1:
        return candidates[0], "resolved"
    return candidates[0], "ambiguous"


def _extract_type_refs(
    body_lines: List[str],
    body_start_line: int,
    known_class_names: Set[str],
    exclude_class: str = "",
) -> List[Tuple[str, int, str]]:
    """
    从函数体中提取已知类名引用（每个类名每个函数体只记录首次出现）

    Returns:
        [(class_name, occurrence_line_1based, expression), ...]
    """
    results = []
    seen: Set[str] = set()
    for idx, line in enumerate(body_lines):
        stripped = _strip_line_comment(line)
        for m in _WORD_RE.finditer(stripped):
            name = m.group(1)
            if (
                name in known_class_names
                and name != exclude_class
                and name not in seen
            ):
                seen.add(name)
                results.append((name, body_start_line + idx, stripped.strip()[:80]))
    return results
