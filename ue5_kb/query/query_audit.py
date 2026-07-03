"""SQLite query audit helpers for generated skill commands."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


MAX_ARG_CHARS = 240
MAX_ERROR_CHARS = 500
DEFAULT_REPORT_LIMIT = 200
DEFAULT_BROAD_RESULT_THRESHOLD = 40


def memory_db_path(skill_dir: Path) -> Path:
    return Path(skill_dir) / "memory" / "memory.sqlite"


def legacy_memory_db_path(skill_dir: Path) -> Path:
    return Path(skill_dir) / "runtime" / "query_audit.db"


def ensure_memory_store(skill_dir: Path) -> Path:
    """Return canonical memory DB path and import legacy audit rows if present."""
    skill_dir = Path(skill_dir)
    db_path = memory_db_path(skill_dir)
    legacy_path = legacy_memory_db_path(skill_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists() and legacy_path.exists():
        import shutil

        shutil.copy2(legacy_path, db_path)
        return db_path
    if db_path.exists() and legacy_path.exists():
        _merge_legacy_audit_rows(db_path, legacy_path)
    return db_path


def _ensure_audit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS query_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            command TEXT NOT NULL,
            args_summary TEXT,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            timestamp TEXT,
            duration_ms INTEGER,
            status TEXT NOT NULL,
            data_trust TEXT,
            branch TEXT,
            source TEXT,
            commit_id TEXT,
            dirty INTEGER,
            fingerprint TEXT,
            result_count INTEGER,
            error TEXT,
            fallback TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_query_runs_trace_id ON query_runs(trace_id);
        CREATE TABLE IF NOT EXISTS query_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            trace_id TEXT NOT NULL,
            command TEXT NOT NULL,
            args_summary TEXT,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            timestamp TEXT,
            duration_ms INTEGER,
            status TEXT NOT NULL,
            data_trust TEXT,
            branch TEXT,
            source TEXT,
            commit_id TEXT,
            dirty INTEGER,
            fingerprint TEXT,
            result_count INTEGER,
            error TEXT,
            fallback TEXT,
            FOREIGN KEY(run_id) REFERENCES query_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_steps_trace_id ON query_steps(trace_id);
        """
    )
    for table in ("query_runs", "query_steps"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "timestamp" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN timestamp TEXT")
    conn.commit()


def _merge_legacy_audit_rows(db_path: Path, legacy_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_audit_schema(conn)
        conn.execute("ATTACH DATABASE ? AS legacy", (str(legacy_path),))
        run_exists = conn.execute(
            "SELECT 1 FROM legacy.sqlite_master WHERE type='table' AND name='query_runs'"
        ).fetchone()
        step_exists = conn.execute(
            "SELECT 1 FROM legacy.sqlite_master WHERE type='table' AND name='query_steps'"
        ).fetchone()
        run_id_map: Dict[int, int] = {}
        if run_exists:
            legacy_run_columns = {row[1] for row in conn.execute("PRAGMA legacy.table_info(query_runs)").fetchall()}
            target_run_columns = [
                column
                for column in (
                    "trace_id",
                    "command",
                    "args_summary",
                    "started_at",
                    "finished_at",
                    "timestamp",
                    "duration_ms",
                    "status",
                    "data_trust",
                    "branch",
                    "source",
                    "commit_id",
                    "dirty",
                    "fingerprint",
                    "result_count",
                    "error",
                    "fallback",
                )
                if column in legacy_run_columns
            ]
            select_columns = ["id"] + target_run_columns
            rows = conn.execute(f"SELECT {', '.join(select_columns)} FROM legacy.query_runs ORDER BY id").fetchall()
            for row in rows:
                old_id = int(row[0])
                values = dict(zip(target_run_columns, row[1:]))
                existing = conn.execute(
                    """
                    SELECT id FROM query_runs
                    WHERE trace_id=? AND command=? AND COALESCE(args_summary,'')=COALESCE(?, '')
                      AND started_at=? AND finished_at=? AND status=?
                    """,
                    (
                        values.get("trace_id"),
                        values.get("command"),
                        values.get("args_summary"),
                        values.get("started_at"),
                        values.get("finished_at"),
                        values.get("status"),
                    ),
                ).fetchone()
                if existing:
                    run_id_map[old_id] = int(existing[0])
                    continue
                placeholders = ", ".join("?" for _ in target_run_columns)
                cursor = conn.execute(
                    f"INSERT INTO query_runs ({', '.join(target_run_columns)}) VALUES ({placeholders})",
                    [values.get(column) for column in target_run_columns],
                )
                run_id_map[old_id] = int(cursor.lastrowid)
        if step_exists:
            legacy_step_columns = {row[1] for row in conn.execute("PRAGMA legacy.table_info(query_steps)").fetchall()}
            target_step_columns = [
                column
                for column in (
                    "trace_id",
                    "command",
                    "args_summary",
                    "started_at",
                    "finished_at",
                    "timestamp",
                    "duration_ms",
                    "status",
                    "data_trust",
                    "branch",
                    "source",
                    "commit_id",
                    "dirty",
                    "fingerprint",
                    "result_count",
                    "error",
                    "fallback",
                )
                if column in legacy_step_columns
            ]
            select_columns = ["id", "run_id"] + target_step_columns
            rows = conn.execute(f"SELECT {', '.join(select_columns)} FROM legacy.query_steps ORDER BY id").fetchall()
            for row in rows:
                old_run_id = int(row[1])
                new_run_id = run_id_map.get(old_run_id)
                if new_run_id is None:
                    continue
                values = dict(zip(target_step_columns, row[2:]))
                existing = conn.execute(
                    """
                    SELECT 1 FROM query_steps
                    WHERE trace_id=? AND command=? AND COALESCE(args_summary,'')=COALESCE(?, '')
                      AND started_at=? AND finished_at=? AND status=?
                    """,
                    (
                        values.get("trace_id"),
                        values.get("command"),
                        values.get("args_summary"),
                        values.get("started_at"),
                        values.get("finished_at"),
                        values.get("status"),
                    ),
                ).fetchone()
                if existing:
                    continue
                insert_columns = ["run_id"] + target_step_columns
                placeholders = ", ".join("?" for _ in insert_columns)
                conn.execute(
                    f"INSERT INTO query_steps ({', '.join(insert_columns)}) VALUES ({placeholders})",
                    [new_run_id] + [values.get(column) for column in target_step_columns],
                )
        conn.commit()
    finally:
        try:
            conn.execute("DETACH DATABASE legacy")
        except Exception:
            pass
        conn.close()


def resolve_trace_id(explicit_trace_id: Optional[str] = None) -> str:
    """Resolve trace id from CLI, environment, or a generated UUID."""
    if explicit_trace_id:
        return explicit_trace_id
    env_trace_id = os.environ.get("UE5KB_TRACE_ID")
    if env_trace_id:
        return env_trace_id
    return uuid.uuid4().hex


def summarize_args(args: Iterable[Any]) -> str:
    """Store only a compact argument summary, never large result/source bodies."""
    compact: List[str] = []
    for arg in args:
        value = str(arg)
        if len(value) > MAX_ARG_CHARS:
            value = value[:MAX_ARG_CHARS] + "..."
        compact.append(value)
    return json.dumps(compact, ensure_ascii=False)


def _result_count(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("found_count", "total", "total_modules", "result_count", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    for key in ("results", "classes", "functions", "examples", "matches", "steps"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _fallback_value(result: Any) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    for key in ("fallback", "fallback_used", "fallback_command"):
        value = result.get(key)
        if value:
            return str(value)[:MAX_ARG_CHARS]
    meta = result.get("_meta")
    if isinstance(meta, dict) and meta.get("fallback"):
        return str(meta["fallback"])[:MAX_ARG_CHARS]
    return None


def _truncate_error(error: Optional[str]) -> Optional[str]:
    if not error:
        return None
    return error[:MAX_ERROR_CHARS]


def _parse_args_summary(args_summary: Optional[str]) -> List[str]:
    if not args_summary:
        return []
    try:
        value = json.loads(args_summary)
    except Exception:
        return [args_summary]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _classify_failure(row: Dict[str, Any]) -> str:
    error = (row.get("error") or "").lower()
    if "implementation file not found" in error or "file not found" in error:
        return "path_resolution_failure"
    if "not found" in error or "未找到" in error:
        return "semantic_miss"
    if "invalid literal" in error or "requires a value" in error or "missing" in error:
        return "call_error"
    if error:
        return "query_error"
    return "none"


def _is_broad_query(row: Dict[str, Any], broad_result_threshold: int) -> bool:
    count = row.get("result_count")
    if not isinstance(count, int):
        return False
    if count >= broad_result_threshold:
        return True
    args = _parse_args_summary(row.get("args_summary"))
    for arg in reversed(args):
        if arg.isdigit() and count >= int(arg):
            return True
    return False


class QueryAudit:
    """Append-only audit writer for query_runs/query_steps."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    @classmethod
    def for_skill(cls, skill_dir: Path) -> "QueryAudit":
        return cls(ensure_memory_store(skill_dir))

    def _create_schema(self) -> None:
        _ensure_audit_schema(self.conn)

    def record(
        self,
        *,
        trace_id: str,
        command: str,
        args: Iterable[Any],
        context: Optional[Dict[str, Any]],
        result: Any = None,
        error: Optional[str] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> int:
        run_id = self.start_run(
            trace_id=trace_id,
            command=command,
            args=args,
            context=context,
            started_at=started_at,
        )
        self.record_step(
            trace_id=trace_id,
            command=command,
            args=args,
            context=context,
            result=result,
            error=error,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.finish_run(
            run_id=run_id,
            context=context,
            result=result,
            error=error,
            finished_at=finished_at,
        )
        return run_id

    def _record_fields(
        self,
        *,
        args: Iterable[Any],
        context: Optional[Dict[str, Any]],
        result: Any = None,
        error: Optional[str] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        started = started_at if started_at is not None else time.time()
        finished = finished_at if finished_at is not None else time.time()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished))
        duration_ms = int(max(0.0, finished - started) * 1000)
        status = "error" if error else "ok"
        context = context or {}
        args_summary = summarize_args(args)
        result_count = _result_count(result)
        fallback = _fallback_value(result)
        data_trust = context.get("data_trust")
        branch = context.get("branch")
        source = context.get("source") or context.get("source_root")
        commit_id = context.get("commit") or context.get("kb_commit")
        dirty = context.get("dirty")
        fingerprint = context.get("fingerprint") or context.get("worktree_fingerprint")
        dirty_value = int(bool(dirty)) if dirty is not None else None

        return {
            "args_summary": args_summary,
            "started_at": started,
            "finished_at": finished,
            "timestamp": timestamp,
            "duration_ms": duration_ms,
            "status": status,
            "data_trust": data_trust,
            "branch": branch,
            "source": source,
            "commit_id": commit_id,
            "dirty": dirty_value,
            "fingerprint": fingerprint,
            "result_count": result_count,
            "error": _truncate_error(error),
            "fallback": fallback,
        }

    def start_run(
        self,
        *,
        trace_id: str,
        command: str,
        args: Iterable[Any],
        context: Optional[Dict[str, Any]] = None,
        started_at: Optional[float] = None,
    ) -> int:
        fields = self._record_fields(
            args=args,
            context=context,
            started_at=started_at,
            finished_at=started_at,
        )

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO query_runs (
                trace_id, command, args_summary, started_at, finished_at, timestamp, duration_ms,
                status, data_trust, branch, source, commit_id, dirty, fingerprint,
                result_count, error, fallback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                command,
                fields["args_summary"],
                fields["started_at"],
                fields["finished_at"],
                fields["timestamp"],
                fields["duration_ms"],
                "running",
                fields["data_trust"],
                fields["branch"],
                fields["source"],
                fields["commit_id"],
                fields["dirty"],
                fields["fingerprint"],
                None,
                None,
                None,
            ),
        )
        run_id = int(cursor.lastrowid)
        self.conn.commit()
        return run_id

    def record_step(
        self,
        *,
        trace_id: str,
        command: str,
        args: Iterable[Any],
        context: Optional[Dict[str, Any]],
        result: Any = None,
        error: Optional[str] = None,
        run_id: Optional[int] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> int:
        created_run = run_id is None
        if run_id is None:
            run_id = self.start_run(
                trace_id=trace_id,
                command=command,
                args=args,
                context=context,
                started_at=started_at,
            )
        fields = self._record_fields(
            args=args,
            context=context,
            result=result,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO query_steps (
                run_id, trace_id, command, args_summary, started_at, finished_at,
                timestamp, duration_ms, status, data_trust, branch, source, commit_id, dirty,
                fingerprint, result_count, error, fallback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                trace_id,
                command,
                fields["args_summary"],
                fields["started_at"],
                fields["finished_at"],
                fields["timestamp"],
                fields["duration_ms"],
                fields["status"],
                fields["data_trust"],
                fields["branch"],
                fields["source"],
                fields["commit_id"],
                fields["dirty"],
                fields["fingerprint"],
                fields["result_count"],
                fields["error"],
                fields["fallback"],
            ),
        )
        step_id = int(cursor.lastrowid)
        self.conn.commit()
        if created_run:
            self.finish_run(
                run_id=run_id,
                context=context,
                result=result,
                error=error,
                finished_at=finished_at,
            )
        return step_id

    def finish_run(
        self,
        *,
        run_id: int,
        context: Optional[Dict[str, Any]] = None,
        result: Any = None,
        error: Optional[str] = None,
        finished_at: Optional[float] = None,
    ) -> None:
        row = self.conn.execute(
            "SELECT args_summary, started_at FROM query_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return
        started = float(row["started_at"])
        fields = self._record_fields(
            args=json.loads(row["args_summary"] or "[]"),
            context=context,
            result=result,
            error=error,
            started_at=started,
            finished_at=finished_at,
        )
        self.conn.execute(
            """
            UPDATE query_runs
            SET finished_at=?, timestamp=?, duration_ms=?, status=?, data_trust=?, branch=?,
                source=?, commit_id=?, dirty=?, fingerprint=?, result_count=?, error=?, fallback=?
            WHERE id=?
            """,
            (
                fields["finished_at"],
                fields["timestamp"],
                fields["duration_ms"],
                fields["status"],
                fields["data_trust"],
                fields["branch"],
                fields["source"],
                fields["commit_id"],
                fields["dirty"],
                fields["fingerprint"],
                fields["result_count"],
                fields["error"],
                fields["fallback"],
                run_id,
            ),
        )
        self.conn.commit()

    def recent(self, trace_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        cursor = self.conn.cursor()
        if trace_id:
            cursor.execute(
                """
                SELECT * FROM query_steps
                WHERE trace_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (trace_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM query_steps
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = [dict(row) for row in cursor.fetchall()]
        return {"trace_id": trace_id, "found_count": len(rows), "steps": rows}

    def report(
        self,
        trace_id: Optional[str] = None,
        limit: int = DEFAULT_REPORT_LIMIT,
        broad_result_threshold: int = DEFAULT_BROAD_RESULT_THRESHOLD,
    ) -> Dict[str, Any]:
        """Build a deterministic static report from recorded query audit rows."""
        recent = self.recent(trace_id, limit)
        steps = list(reversed(recent["steps"]))
        command_counts: Dict[str, int] = {}
        failures: List[Dict[str, Any]] = []
        broad_searches: List[Dict[str, Any]] = []
        total_duration_ms = 0
        max_result_count = 0

        for step in steps:
            command = step.get("command") or ""
            command_counts[command] = command_counts.get(command, 0) + 1
            duration = step.get("duration_ms")
            if isinstance(duration, int):
                total_duration_ms += duration
            count = step.get("result_count")
            if isinstance(count, int):
                max_result_count = max(max_result_count, count)
            if step.get("status") == "error" or step.get("error"):
                failures.append(
                    {
                        "id": step.get("id"),
                        "command": command,
                        "args": _parse_args_summary(step.get("args_summary")),
                        "type": _classify_failure(step),
                        "error": step.get("error"),
                    }
                )
            if _is_broad_query(step, broad_result_threshold):
                broad_searches.append(
                    {
                        "id": step.get("id"),
                        "command": command,
                        "args": _parse_args_summary(step.get("args_summary")),
                        "result_count": count,
                        "threshold": broad_result_threshold,
                    }
                )

        business_queries = len(steps)
        failure_count = len(failures)
        broad_count = len(broad_searches)
        failure_rate = (failure_count / business_queries) if business_queries else 0.0
        acceptance_status = (
            "PASS"
            if business_queries > 0 and failure_count == 0 and broad_count <= 1
            else "FAIL"
        )
        acceptance_reasons: List[str] = []
        if business_queries == 0:
            acceptance_reasons.append("no audit rows found")
        if failure_count:
            acceptance_reasons.append("failure_events must be 0")
        if broad_count > 1:
            acceptance_reasons.append("broad_search_events must be <= 1 or followed by narrowing queries")

        meta = {
            "trace_id": trace_id,
            "row_limit": max(1, min(int(limit), 200)),
            "broad_result_threshold": broad_result_threshold,
        }
        if steps:
            last = steps[-1]
            meta.update(
                {
                    "data_trust": last.get("data_trust"),
                    "branch": last.get("branch"),
                    "source": last.get("source"),
                    "commit": last.get("commit_id"),
                    "dirty": bool(last.get("dirty")) if last.get("dirty") is not None else None,
                }
            )

        return {
            "schema": "query-audit-report/v1",
            "meta": meta,
            "counts": {
                "business_queries": business_queries,
                "failure_events": failure_count,
                "broad_search_events": broad_count,
                "command_counts": command_counts,
            },
            "efficiency": {
                "total_duration_ms": total_duration_ms,
                "average_duration_ms": int(total_duration_ms / business_queries) if business_queries else 0,
                "failure_rate": round(failure_rate, 4),
                "max_result_count": max_result_count,
                "status": acceptance_status,
            },
            "failures": failures,
            "broad_searches": broad_searches,
            "acceptance": {
                "status": acceptance_status,
                "reasons": acceptance_reasons,
                "static_only": True,
            },
        }

    def close(self) -> None:
        self.conn.close()


def record_query(
    *,
    skill_dir: Path,
    trace_id: Optional[str],
    command: str,
    args: Iterable[Any],
    context: Optional[Dict[str, Any]],
    result: Any = None,
    error: Optional[str] = None,
    started_at: Optional[float] = None,
    finished_at: Optional[float] = None,
) -> str:
    audit = QueryAudit.for_skill(skill_dir)
    try:
        resolved_trace_id = resolve_trace_id(trace_id)
        inferred_error = error
        if inferred_error is None and isinstance(result, dict) and result.get("error"):
            inferred_error = str(result.get("error"))
        audit.record(
            trace_id=resolved_trace_id,
            command=command,
            args=args,
            context=context,
            result=result,
            error=inferred_error,
            started_at=started_at,
            finished_at=finished_at,
        )
        return resolved_trace_id
    finally:
        audit.close()
