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
        return cls(Path(skill_dir) / "runtime" / "query_audit.db")

    def _create_schema(self) -> None:
        self.conn.executescript(
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
            columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "timestamp" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN timestamp TEXT")
        self.conn.commit()

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
        audit.record(
            trace_id=resolved_trace_id,
            command=command,
            args=args,
            context=context,
            result=result,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
        return resolved_trace_id
    finally:
        audit.close()
