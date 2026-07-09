"""Deterministic query-memory helpers for generated skill commands.

Query memory stores reusable query routes and optional evidence-bound business
flow annotations.  Freshness is computed from current runtime metadata, file
hashes, command replay hashes, and graph/frontier hashes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ue5_kb.query.query_audit import ensure_memory_store, legacy_memory_db_path, memory_db_path


MEMORY_COMMAND_PREFIX = "query_memory_"
MAX_TEXT = 1000


CommandRunner = Callable[[str, List[str]], Dict[str, Any]]


def _auto_refresh_wiki(skill_dir: Path, source_root: Optional[Path]) -> bool:
    """尽力而为地在每次 record_memory/attach_business_flow 成功后重新生成 Memory Wiki。

    这样 agent 不需要额外记得再手动跑一次 query_memory_render_site；wiki 永远反映
    memory.sqlite 最新内容。渲染失败（例如 vendor 资源缺失）不影响 record/attach 本身
    的成功结果，只是不产出/不刷新 wiki 文件。
    """
    try:
        from ue5_kb.query.memory_site import export_site

        export_site(skill_dir=skill_dir, source_root=source_root)
        return True
    except Exception:
        return False


def stable_json(value: Any) -> str:
    """Return deterministic JSON for hashing without preserving source bodies."""
    return json.dumps(_sanitize(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def stable_json_full(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash_full(value: Any) -> str:
    return hashlib.sha256(stable_json_full(value).encode("utf-8")).hexdigest()


def _sanitize(value: Any) -> Any:
    """Drop fields that can contain large source bodies before hashing/storing.

    `_audit` and `_meta` are execution-environment metadata (trace ids, cwd-sensitive
    source resolution, freshness snapshots). They must never participate in result
    hashing: environment drift is judged by the dedicated freshness/provenance
    channels, while result hashes must only reflect the query payload itself.
    """
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"_audit", "_meta"}:
                continue
            if lowered in {"content", "file_content", "block_content", "block_content_full"}:
                result[key] = {"_omitted": True, "sha256": hashlib.sha256(str(item).encode("utf-8", "ignore")).hexdigest()}
            elif isinstance(item, (dict, list)):
                # 容器必须先递归清洗再考虑体量；直接 str() 截断会把嵌套 _meta/_audit
                # 以字符串形式带进哈希，绕过键名过滤（cwd 敏感字段污染 result hash）。
                result[key] = _sanitize(item)
            elif len(str(item)) > MAX_TEXT and lowered not in {"path", "file", "symbol"}:
                result[key] = str(item)[:MAX_TEXT]
            else:
                result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _parse_args_summary(args_summary: Optional[str]) -> List[str]:
    if not args_summary:
        return []
    try:
        parsed = json.loads(args_summary)
    except Exception:
        return [args_summary]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def _runtime_fingerprint(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = context or {}
    return {
        "skill_name": context.get("skill_name"),
        "source_root": context.get("source") or context.get("source_root"),
        "branch_name": context.get("branch") or context.get("branch_name"),
        "variant_id": context.get("variant_id") or context.get("kb_path"),
        "commit_id": context.get("commit") or context.get("kb_commit"),
        "dirty": bool(context.get("dirty")) if context.get("dirty") is not None else None,
        "source_fingerprint": context.get("fingerprint") or context.get("worktree_fingerprint"),
        "data_trust": context.get("data_trust"),
    }


def _relative_file_path(source_root: Optional[Path], path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    if source_root is None:
        return path
    return Path(source_root) / path


def _file_hash(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _anchor_hash(path: Path, line_number: int, radius: int = 3) -> Optional[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    start = max(0, int(line_number) - 1 - radius)
    end = min(len(lines), int(line_number) + radius)
    anchor = "\n".join(lines[start:end])
    return hashlib.sha256(anchor.encode("utf-8", "ignore")).hexdigest()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS query_memory_patterns (
            id TEXT PRIMARY KEY,
            intent TEXT NOT NULL,
            seed TEXT NOT NULL,
            skill_name TEXT,
            source_root TEXT,
            branch_name TEXT,
            variant_id TEXT,
            commit_id TEXT,
            dirty INTEGER,
            source_fingerprint TEXT,
            rules_version TEXT,
            command_sequence_hash TEXT,
            created_at INTEGER NOT NULL,
            last_validated_at INTEGER,
            status TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_query_memory_patterns_seed ON query_memory_patterns(seed);
        CREATE INDEX IF NOT EXISTS idx_query_memory_patterns_intent ON query_memory_patterns(intent);

        CREATE TABLE IF NOT EXISTS query_memory_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            command TEXT NOT NULL,
            args_summary TEXT,
            result_hash TEXT,
            important_fields_hash TEXT,
            result_count INTEGER,
            error TEXT,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_memory_steps_memory ON query_memory_steps(memory_id);

        CREATE TABLE IF NOT EXISTS query_memory_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            file TEXT NOT NULL,
            file_hash TEXT,
            line_start INTEGER,
            line_end INTEGER,
            anchor_text_hash TEXT,
            symbol TEXT,
            module TEXT,
            symbol_id TEXT,
            symbol_signature_hash TEXT,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_memory_evidence_memory ON query_memory_evidence(memory_id);

        CREATE TABLE IF NOT EXISTS query_memory_graph (
            memory_id TEXT PRIMARY KEY,
            node_set_hash TEXT,
            edge_set_hash TEXT,
            frontier_hash TEXT,
            edge_set_json TEXT,
            frontier_json TEXT,
            node_count INTEGER,
            edge_count INTEGER,
            frontier_count INTEGER,
            unresolved_count INTEGER,
            truncated INTEGER,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id)
        );
        CREATE TABLE IF NOT EXISTS query_memory_graph_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            node_key TEXT NOT NULL,
            node_kind TEXT,
            label TEXT NOT NULL,
            evidence_count INTEGER DEFAULT 0,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_query_memory_graph_nodes_key
            ON query_memory_graph_nodes(memory_id, node_key);

        CREATE TABLE IF NOT EXISTS query_memory_graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            edge_type TEXT,
            evidence_hash TEXT,
            evidence_count INTEGER DEFAULT 0,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_memory_graph_edges_memory
            ON query_memory_graph_edges(memory_id);

        CREATE TABLE IF NOT EXISTS business_subjects (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            primary_symbol TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_business_subjects_name ON business_subjects(display_name);

        CREATE TABLE IF NOT EXISTS business_subject_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY(subject_id) REFERENCES business_subjects(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_business_subject_aliases_unique
            ON business_subject_aliases(subject_id, alias);

        CREATE TABLE IF NOT EXISTS business_subject_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT NOT NULL,
            member_kind TEXT NOT NULL,
            member_id TEXT NOT NULL,
            memory_id TEXT,
            FOREIGN KEY(subject_id) REFERENCES business_subjects(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_business_subject_members_unique
            ON business_subject_members(subject_id, member_kind, member_id, memory_id);

        CREATE TABLE IF NOT EXISTS business_subject_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_subject_id TEXT NOT NULL,
            target_subject_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            evidence_id TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS business_patterns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS business_pattern_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            stage_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(pattern_id) REFERENCES business_patterns(id)
        );
        CREATE TABLE IF NOT EXISTS business_pattern_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            subject_id TEXT,
            FOREIGN KEY(pattern_id) REFERENCES business_patterns(id)
        );
        CREATE TABLE IF NOT EXISTS business_pattern_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            memory_id TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(pattern_id) REFERENCES business_patterns(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_business_pattern_members_unique
            ON business_pattern_members(pattern_id, subject_id, memory_id);
        CREATE TABLE IF NOT EXISTS business_suggestions (
            id TEXT PRIMARY KEY,
            suggestion_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS business_flow_annotations (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            flow_json TEXT NOT NULL,
            graph_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES query_memory_patterns(id),
            FOREIGN KEY(subject_id) REFERENCES business_subjects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_business_flow_annotations_subject
            ON business_flow_annotations(subject_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_business_flow_annotations_memory
            ON business_flow_annotations(memory_id);

        CREATE TABLE IF NOT EXISTS negative_hints (
            id TEXT PRIMARY KEY,
            trace_id TEXT,
            memory_id TEXT,
            command TEXT NOT NULL,
            args_summary TEXT,
            failure_type TEXT NOT NULL,
            error_summary TEXT,
            source_root TEXT,
            branch_name TEXT,
            variant_id TEXT,
            commit_id TEXT,
            dirty INTEGER,
            source_fingerprint TEXT,
            stale_condition_json TEXT NOT NULL,
            resolved_by TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_negative_hints_command ON negative_hints(command);

        CREATE TABLE IF NOT EXISTS memory_snapshots (
            id TEXT PRIMARY KEY,
            subject_id TEXT,
            pattern_id TEXT,
            memory_id TEXT,
            snapshot_json TEXT NOT NULL,
            graph_hash TEXT NOT NULL,
            commit_id TEXT,
            branch_name TEXT,
            variant_id TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_snapshot_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES memory_snapshots(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_snapshot_members_unique
            ON memory_snapshot_members(snapshot_id, memory_id);
        CREATE TABLE IF NOT EXISTS memory_diffs (
            id TEXT PRIMARY KEY,
            base_snapshot_id TEXT,
            head_snapshot_id TEXT,
            diff_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(query_memory_graph)").fetchall()}
    for name in ("node_set_json", "edge_set_json", "frontier_json"):
        if name not in existing:
            conn.execute(f"ALTER TABLE query_memory_graph ADD COLUMN {name} TEXT")
    pattern_columns = {row[1] for row in conn.execute("PRAGMA table_info(query_memory_patterns)").fetchall()}
    if "branch_name" not in pattern_columns:
        conn.execute("ALTER TABLE query_memory_patterns ADD COLUMN branch_name TEXT")
    evidence_columns = {row[1] for row in conn.execute("PRAGMA table_info(query_memory_evidence)").fetchall()}
    if "module" not in evidence_columns:
        conn.execute("ALTER TABLE query_memory_evidence ADD COLUMN module TEXT")
    flow_columns = {row[1] for row in conn.execute("PRAGMA table_info(business_flow_annotations)").fetchall()}
    if "status" not in flow_columns:
        conn.execute("ALTER TABLE business_flow_annotations ADD COLUMN status TEXT NOT NULL DEFAULT 'published'")
    conn.commit()


def _connect(skill_dir: Path) -> sqlite3.Connection:
    db_path = ensure_memory_store(skill_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    return conn


def _query_steps(conn: sqlite3.Connection, trace_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM query_steps
        WHERE trace_id = ?
        ORDER BY id ASC
        """,
        (trace_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        command = item.get("command") or ""
        if command.startswith(MEMORY_COMMAND_PREFIX) or command in {"query_audit", "query_audit_report"}:
            continue
        result.append(item)
    return result


def _important_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "schema",
        "seed",
        "effective_seed",
        "resolution_state",
        "candidate_count",
        "found_count",
        "counts",
        "coverage",
        "closure_validation",
        "flow_summary",
        "zero_reason",
        "frontier",
    ]
    return {key: result.get(key) for key in keys if key in result}


def _result_count(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("found_count", "total", "total_modules", "result_count", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    for key in ("results", "classes", "functions", "matches", "steps", "ranked_edges", "evidence_slices"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _extract_graph(result: Dict[str, Any]) -> Tuple[List[str], List[str], List[str], int, bool]:
    nodes = set()
    edges = set()
    frontier = set()
    unresolved = 0
    truncated = False

    for key in ("edges", "semantic_edges", "ranked_edges"):
        for edge in result.get(key, []) if isinstance(result.get(key), list) else []:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            edge_type = str(edge.get("semantic_edge_type") or edge.get("edge_type") or edge.get("relation_type") or "")
            if source:
                nodes.add(source)
            if target:
                nodes.add(target)
            if source or target:
                edges.add(f"{source}->{edge_type}->{target}")
            if str(edge.get("resolution_state", "")).lower() in {"unresolved", "ambiguous"}:
                unresolved += 1

    for item in result.get("frontier", []) if isinstance(result.get("frontier"), list) else []:
        symbol = str(item.get("symbol", item))
        if symbol:
            frontier.add(symbol)

    closure = result.get("closure_validation")
    if isinstance(closure, dict):
        truncated = bool(closure.get("upstream_truncated") or closure.get("hit_limit"))
        unresolved += len([r for r in closure.get("reasons", []) if "unresolved" in str(r).lower()])
    if result.get("closure_status") == "truncated":
        truncated = True

    return sorted(nodes), sorted(edges), sorted(frontier), unresolved, truncated


def _merge_graph(graphs: Iterable[Tuple[List[str], List[str], List[str], int, bool]]) -> Dict[str, Any]:
    nodes = set()
    edges = set()
    frontier = set()
    unresolved = 0
    truncated = False
    for g_nodes, g_edges, g_frontier, g_unresolved, g_truncated in graphs:
        nodes.update(g_nodes)
        edges.update(g_edges)
        frontier.update(g_frontier)
        unresolved += g_unresolved
        truncated = truncated or g_truncated
    return {
        "nodes": sorted(nodes),
        "edges": sorted(edges),
        "frontier": sorted(frontier),
        "unresolved_count": unresolved,
        "truncated": truncated,
        "node_set_hash": stable_hash(sorted(nodes)),
        "edge_set_hash": stable_hash(sorted(edges)),
        "frontier_hash": stable_hash(sorted(frontier)),
    }


def _normalize_flow_node(raw: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    node_id = str(raw.get("id") or f"step_{index}").strip()
    label = str(raw.get("label") or raw.get("title") or node_id).strip()
    if not node_id or not label:
        return None
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
    details = raw.get("details")
    if isinstance(details, str):
        details_list = [details]
    elif isinstance(details, list):
        details_list = [str(item) for item in details if str(item).strip()]
    else:
        details_list = []
    return {
        "id": node_id,
        "label": label,
        "kind": str(raw.get("kind") or raw.get("type") or "stage"),
        "lane": str(raw.get("lane") or raw.get("phase") or "业务流程"),
        "summary": str(raw.get("summary") or raw.get("description") or ""),
        "details": details_list,
        "evidence": [str(item) for item in evidence if str(item).strip()],
    }


def _normalize_flow_edge(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or raw.get("from") or "").strip()
    target = str(raw.get("target") or raw.get("to") or "").strip()
    if not source or not target:
        return None
    return {
        "source": source,
        "target": target,
        "label": str(raw.get("label") or raw.get("relation") or raw.get("type") or "next"),
        "type": str(raw.get("type") or raw.get("relation") or "flow"),
        "condition": str(raw.get("condition") or ""),
    }


def _derive_flow_lanes(nodes: List[Dict[str, Any]], raw_lanes: Any) -> List[str]:
    lanes: List[str] = []
    if isinstance(raw_lanes, list):
        for item in raw_lanes:
            lane = str(item.get("id") or item.get("name") or item) if isinstance(item, dict) else str(item)
            lane = lane.strip()
            if lane and lane not in lanes:
                lanes.append(lane)
    for node in nodes:
        lane = str(node.get("lane") or "业务流程").strip()
        if lane and lane not in lanes:
            lanes.append(lane)
    return lanes or ["业务流程"]


def _score_business_flow(flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    lanes = flow.get("lanes", [])
    baseline = flow.get("quality_baseline") if isinstance(flow.get("quality_baseline"), dict) else {}
    text = " ".join(
        [
            str(flow.get("title") or ""),
            *[str(node.get("label") or "") for node in nodes],
            *[str(node.get("summary") or "") for node in nodes],
            *[" ".join(node.get("details", [])) for node in nodes],
            *[str(edge.get("label") or "") for edge in edges],
            *[str(edge.get("condition") or "") for edge in edges],
        ]
    )
    required_terms_raw = baseline.get("required_terms") if isinstance(baseline.get("required_terms"), list) else []
    required_terms = [str(term) for term in required_terms_raw if str(term).strip()]
    covered_terms = [term for term in required_terms if term.lower() in text.lower()]
    nodes_with_evidence = sum(1 for node in nodes if node.get("evidence"))
    branch_edges = sum(1 for edge in edges if edge.get("condition") or "true" in str(edge.get("label")).lower() or "false" in str(edge.get("label")).lower())
    detailed_nodes = sum(1 for node in nodes if node.get("summary") and node.get("details"))
    checks = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "lane_count": len(lanes),
        "nodes_with_evidence": nodes_with_evidence,
        "detailed_nodes": detailed_nodes,
        "branch_edges": branch_edges,
        "required_terms_total": len(required_terms),
        "required_terms_covered": len(covered_terms),
        "covered_terms": covered_terms,
        "missing_terms": [term for term in required_terms if term not in covered_terms],
    }
    score = 0
    score += min(20, len(nodes) * 20 // 16)
    score += min(15, len(edges) * 15 // 18)
    score += min(15, len(lanes) * 15 // 8)
    score += 15 if nodes and nodes_with_evidence == len(nodes) else (nodes_with_evidence * 15 // max(1, len(nodes)))
    score += min(15, len(covered_terms) * 15 // len(required_terms)) if required_terms else 15
    score += min(10, branch_edges * 5)
    score += min(10, detailed_nodes * 10 // max(1, len(nodes)))
    minimum_score = int(baseline.get("minimum_score") or 90)
    pass_status = str(baseline.get("status_on_pass") or "high_quality_business_flow")
    fail_status = str(baseline.get("status_on_fail") or "below_quality_baseline")
    passed = score >= minimum_score
    status = pass_status if passed else fail_status
    return {"score": score, "status": status, "minimum_score": minimum_score, "passed": passed, "checks": checks}


def _normalize_business_flow(flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = [
        node
        for index, item in enumerate(flow.get("nodes", []), start=1)
        for node in [_normalize_flow_node(item, index)]
        if node
    ]
    node_ids = {node["id"] for node in nodes}
    edges = [
        edge
        for item in flow.get("edges", [])
        for edge in [_normalize_flow_edge(item)]
        if edge and edge["source"] in node_ids and edge["target"] in node_ids
        ]
    if not edges and len(nodes) > 1:
        edges = [
            {"source": nodes[index]["id"], "target": nodes[index + 1]["id"], "label": "next", "type": "flow", "condition": ""}
            for index in range(len(nodes) - 1)
        ]
    normalized = {
        "schema": "business-flow/v2",
        "title": str(flow.get("title") or flow.get("name") or ""),
        "language": str(flow.get("language") or "zh-CN"),
        "quality_baseline": flow.get("quality_baseline") if isinstance(flow.get("quality_baseline"), dict) else {},
        "lanes": _derive_flow_lanes(nodes, flow.get("lanes")),
        "nodes": nodes,
        "edges": edges,
        "notes": str(flow.get("notes") or ""),
    }
    normalized["quality"] = _score_business_flow(normalized)
    return normalized


def _subject_id_for_memory(conn: sqlite3.Connection, memory_id: str) -> Optional[str]:
    row = conn.execute(
        """
        SELECT subject_id FROM business_subject_members
        WHERE memory_id=?
        ORDER BY id
        LIMIT 1
        """,
        (memory_id,),
    ).fetchone()
    return row["subject_id"] if row else None


def _module_from_file(file_value: Optional[str]) -> Optional[str]:
    if not file_value:
        return None
    parts = str(file_value).replace("\\", "/").split("/")
    if "Source" in parts:
        index = parts.index("Source")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def _failure_type(command: str, error: Optional[str], result: Any) -> str:
    text = f"{command} {error or ''} {stable_json(_important_fields(result)) if isinstance(result, dict) else ''}".lower()
    if "file not found" in text or "implementation file not found" in text:
        return "path_resolution_failure"
    if "not found" in text or "未找到" in text or "miss" in text:
        return "semantic_miss"
    if "requires" in text or "missing" in text or "invalid" in text:
        return "call_error"
    return "query_error"


def _stale_condition(runtime: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "invalidate_when_commit_changes": True,
        "invalidate_when_fingerprint_changes": True,
        "recorded_commit_id": runtime.get("commit_id"),
        "recorded_source_fingerprint": runtime.get("source_fingerprint"),
        "recorded_variant_id": runtime.get("variant_id"),
    }


def _insert_negative_hint(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    memory_id: str,
    command: str,
    args: List[str],
    error: Optional[str],
    result: Any,
    runtime: Dict[str, Any],
) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO negative_hints (
            id, trace_id, memory_id, command, args_summary, failure_type, error_summary,
            source_root, branch_name, variant_id, commit_id, dirty, source_fingerprint,
            stale_condition_json, resolved_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            trace_id,
            memory_id,
            command,
            json.dumps(args, ensure_ascii=False),
            _failure_type(command, error, result),
            str(error or "")[:500],
            runtime.get("source_root"),
            runtime.get("branch_name"),
            runtime.get("variant_id"),
            runtime.get("commit_id"),
            int(bool(runtime.get("dirty"))) if runtime.get("dirty") is not None else None,
            runtime.get("source_fingerprint"),
            stable_json(_stale_condition(runtime)),
            None,
            now,
        ),
    )


def _edge_parts(edge: str) -> Tuple[str, str, str]:
    parts = edge.split("->", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return edge, "", ""


def _insert_graph_tables(conn: sqlite3.Connection, *, memory_id: str, graph: Dict[str, Any]) -> None:
    for node in graph.get("nodes", []):
        node_key = stable_hash({"node": node})
        conn.execute(
            """
            INSERT OR IGNORE INTO query_memory_graph_nodes (
                memory_id, node_key, node_kind, label, evidence_count
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (memory_id, node_key, "symbol", node, 0),
        )
    for edge in graph.get("edges", []):
        source, edge_type, target = _edge_parts(edge)
        if not source and not target:
            continue
        conn.execute(
            """
            INSERT INTO query_memory_graph_edges (
                memory_id, source_key, target_key, edge_type, evidence_hash, evidence_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                stable_hash({"node": source}),
                stable_hash({"node": target}),
                edge_type,
                stable_hash(edge),
                0,
            ),
        )


def _insert_evidence_graph_nodes(conn: sqlite3.Connection, *, memory_id: str, evidence_rows: List[Dict[str, Any]]) -> None:
    for evidence in evidence_rows:
        file_value = evidence.get("file")
        module = evidence.get("module")
        symbol = evidence.get("symbol")
        for node_kind, label in (("file", file_value), ("module", module), ("symbol", symbol)):
            if not label:
                continue
            node_key = stable_hash({node_kind: label})
            conn.execute(
                """
                INSERT OR IGNORE INTO query_memory_graph_nodes (
                    memory_id, node_key, node_kind, label, evidence_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, node_key, node_kind, str(label), 1),
            )


def _subject_id_for(seed: str, intent: str) -> str:
    normalized = (seed or "unknown").strip() or "unknown"
    return "subject-" + stable_hash({"seed": normalized.lower(), "intent": intent})[:16]


def _upsert_subject_overlay(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    intent: str,
    seed: str,
    evidence_count: int,
    graph: Dict[str, Any],
) -> str:
    now = int(time.time())
    subject_id = _subject_id_for(seed, intent)
    conn.execute(
        """
        INSERT INTO business_subjects (id, display_name, primary_symbol, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, status=excluded.status
        """,
        (subject_id, seed, seed, "active", now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO business_subject_aliases (subject_id, alias, source)
        VALUES (?, ?, ?)
        """,
        (subject_id, seed, "seed"),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO business_subject_members (subject_id, member_kind, member_id, memory_id)
        VALUES (?, ?, ?, ?)
        """,
        (subject_id, "trace_route", memory_id, memory_id),
    )
    for node in graph.get("nodes", []):
        conn.execute(
            """
            INSERT OR IGNORE INTO business_subject_members (subject_id, member_kind, member_id, memory_id)
            VALUES (?, ?, ?, ?)
            """,
            (subject_id, "node", stable_hash({"node": node}), memory_id),
        )
    for edge in graph.get("edges", []):
        conn.execute(
            """
            INSERT OR IGNORE INTO business_subject_members (subject_id, member_kind, member_id, memory_id)
            VALUES (?, ?, ?, ?)
            """,
            (subject_id, "edge", stable_hash(edge), memory_id),
        )
    module_rows = conn.execute(
        "SELECT DISTINCT module FROM query_memory_evidence WHERE memory_id=? AND module IS NOT NULL",
        (memory_id,),
    ).fetchall()
    for row in module_rows:
        module = row["module"]
        conn.execute(
            """
            INSERT OR IGNORE INTO business_subject_members (subject_id, member_kind, member_id, memory_id)
            VALUES (?, ?, ?, ?)
            """,
            (subject_id, "module", module, memory_id),
        )
    if evidence_count:
        conn.execute(
            """
            INSERT OR IGNORE INTO business_subject_members (subject_id, member_kind, member_id, memory_id)
            VALUES (?, ?, ?, ?)
            """,
            (subject_id, "evidence_set", stable_hash({"memory_id": memory_id, "evidence_count": evidence_count}), memory_id),
        )
    return subject_id


def _pattern_id_for(intent: str) -> str:
    normalized = (intent or "unknown").strip() or "unknown"
    return "pattern-" + stable_hash({"intent": normalized.lower()})[:16]


def _upsert_business_pattern(
    conn: sqlite3.Connection,
    *,
    intent: str,
    subject_id: str,
    memory_id: str,
    command_sequence: List[Dict[str, Any]],
    evidence_ids: List[int],
) -> str:
    now = int(time.time())
    pattern_id = _pattern_id_for(intent)
    existing_subjects = {
        row["subject_id"]
        for row in conn.execute(
            "SELECT DISTINCT subject_id FROM business_pattern_members WHERE pattern_id=?",
            (pattern_id,),
        ).fetchall()
    }
    subject_count = len(existing_subjects | {subject_id})
    status = "active" if subject_count >= 2 else "candidate"
    conn.execute(
        """
        INSERT INTO business_patterns (id, name, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, status=excluded.status
        """,
        (pattern_id, intent or "unknown", status, now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO business_pattern_members (pattern_id, subject_id, memory_id, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pattern_id, subject_id, memory_id, "active", now),
    )
    seen_stages = set()
    for index, step in enumerate(command_sequence, start=1):
        stage_name = str(step.get("command") or f"stage_{index}")
        stage_key = (pattern_id, stage_name)
        if stage_key in seen_stages:
            continue
        seen_stages.add(stage_key)
        exists = conn.execute(
            "SELECT 1 FROM business_pattern_stages WHERE pattern_id=? AND stage_name=?",
            (pattern_id, stage_name),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO business_pattern_stages (pattern_id, stage_name, stage_index, status)
                VALUES (?, ?, ?, ?)
                """,
                (pattern_id, stage_name, index, "active"),
            )
    stage_names = [str(step.get("command") or "route_step") for step in command_sequence] or ["evidence"]
    for index, evidence_id in enumerate(evidence_ids):
        stage_name = stage_names[min(index, len(stage_names) - 1)]
        exists = conn.execute(
            """
            SELECT 1 FROM business_pattern_evidence
            WHERE pattern_id=? AND stage_name=? AND evidence_id=? AND subject_id=?
            """,
            (pattern_id, stage_name, str(evidence_id), subject_id),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO business_pattern_evidence (pattern_id, stage_name, evidence_id, subject_id)
                VALUES (?, ?, ?, ?)
                """,
                (pattern_id, stage_name, str(evidence_id), subject_id),
            )
    return pattern_id


def _source_evidence_from_step(
    *,
    source_root: Optional[Path],
    args: List[str],
) -> Optional[Dict[str, Any]]:
    if len(args) < 2:
        return None
    try:
        line = int(args[1])
    except ValueError:
        return None
    rel_file = args[0]
    path = _relative_file_path(source_root, rel_file)
    file_hash = _file_hash(path)
    return {
        "file": rel_file,
        "file_hash": file_hash,
        "line_start": line,
        "line_end": line,
        "anchor_text_hash": _anchor_hash(path, line),
        "symbol": None,
        "module": _module_from_file(rel_file),
        "symbol_id": None,
        "symbol_signature_hash": None,
    }


def _evidence_from_result(source_root: Optional[Path], result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for item in result.get("evidence_slices", []) if isinstance(result.get("evidence_slices"), list) else []:
        file_value = item.get("file")
        line = item.get("line")
        if not file_value or not line:
            continue
        path = _relative_file_path(source_root, str(file_value))
        try:
            line_value = int(line)
        except ValueError:
            continue
        symbol = item.get("source") or item.get("target")
        module = item.get("module") or item.get("source_module") or item.get("target_module") or _module_from_file(str(file_value))
        evidence.append(
            {
                "file": str(file_value),
                "file_hash": _file_hash(path),
                "line_start": line_value,
                "line_end": line_value,
                "anchor_text_hash": _anchor_hash(path, line_value),
                "symbol": symbol,
                "module": module,
                "symbol_id": str(symbol) if symbol else None,
                "symbol_signature_hash": stable_hash(symbol) if symbol else None,
            }
        )
    return evidence


def record_memory(
    *,
    skill_dir: Path,
    trace_id: str,
    intent: str,
    seed: str,
    context: Dict[str, Any],
    source_root: Optional[Path],
    command_runner: CommandRunner,
) -> Dict[str, Any]:
    """Promote a trace into a reusable query route."""
    conn = _connect(skill_dir)
    try:
        steps = _query_steps(conn, trace_id)
        if not steps:
            return {"schema": "query-memory-record/v1", "error": "no trace steps found", "trace_id": trace_id}

        memory_id = uuid.uuid4().hex
        runtime = _runtime_fingerprint(context)
        command_sequence = []
        replay_graphs = []
        evidence_rows: List[Dict[str, Any]] = []
        negative_hint_count = 0
        route_step_index = 0

        for step in steps:
            args = _parse_args_summary(step.get("args_summary"))
            command = step.get("command") or ""
            error = step.get("error")
            try:
                result: Dict[str, Any] = command_runner(command, args)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            if isinstance(result, dict) and result.get("error"):
                error = result["error"]
            if error:
                _insert_negative_hint(
                    conn,
                    trace_id=trace_id,
                    memory_id=memory_id,
                    command=command,
                    args=args,
                    error=error,
                    result=result,
                    runtime=runtime,
                )
                negative_hint_count += 1
                continue

            route_step_index += 1
            command_sequence.append({"command": command, "args": args})
            result_hash = stable_hash(result)
            important_hash = stable_hash(_important_fields(result) if isinstance(result, dict) else result)
            conn.execute(
                """
                INSERT INTO query_memory_steps (
                    memory_id, step_index, command, args_summary, result_hash,
                    important_fields_hash, result_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    route_step_index,
                    command,
                    json.dumps(args, ensure_ascii=False),
                    result_hash,
                    important_hash,
                    _result_count(result),
                    error,
                ),
            )

            if command == "source_slice":
                evidence = _source_evidence_from_step(source_root=source_root, args=args)
                if evidence:
                    evidence_rows.append(evidence)
            if isinstance(result, dict):
                replay_graphs.append(_extract_graph(result))
                evidence_rows.extend(_evidence_from_result(source_root, result))

        if route_step_index == 0:
            conn.commit()
            return {
                "schema": "query-memory-record/v1",
                "trace_id": trace_id,
                "intent": intent,
                "seed": seed,
                "recorded": False,
                "error": "no successful route steps",
                "step_count": 0,
                "negative_hint_count": negative_hint_count,
                "stores_business_facts": False,
                "static_only": True,
            }

        graph = _merge_graph(replay_graphs)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO query_memory_patterns (
                id, intent, seed, skill_name, source_root, branch_name, variant_id, commit_id, dirty,
                source_fingerprint, rules_version, command_sequence_hash, created_at,
                last_validated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                intent,
                seed,
                runtime.get("skill_name"),
                runtime.get("source_root"),
                runtime.get("branch_name"),
                runtime.get("variant_id"),
                runtime.get("commit_id"),
                int(bool(runtime.get("dirty"))) if runtime.get("dirty") is not None else None,
                runtime.get("source_fingerprint"),
                None,
                stable_hash(command_sequence),
                now,
                None,
                "active",
            ),
        )
        seen_evidence = set()
        evidence_ids: List[int] = []
        deduped_evidence_rows: List[Dict[str, Any]] = []
        for evidence in evidence_rows:
            key = (evidence.get("file"), evidence.get("line_start"), evidence.get("symbol"))
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            cursor = conn.execute(
                """
                INSERT INTO query_memory_evidence (
                    memory_id, file, file_hash, line_start, line_end, anchor_text_hash,
                    symbol, module, symbol_id, symbol_signature_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    evidence.get("file"),
                    evidence.get("file_hash"),
                    evidence.get("line_start"),
                    evidence.get("line_end"),
                    evidence.get("anchor_text_hash"),
                    evidence.get("symbol"),
                    evidence.get("module"),
                    evidence.get("symbol_id"),
                    evidence.get("symbol_signature_hash"),
                ),
            )
            evidence_ids.append(int(cursor.lastrowid))
            deduped_evidence_rows.append(evidence)

        conn.execute(
            """
            INSERT INTO query_memory_graph (
                memory_id, node_set_hash, edge_set_hash, frontier_hash,
                node_set_json, edge_set_json, frontier_json, node_count, edge_count,
                frontier_count, unresolved_count, truncated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                graph["node_set_hash"],
                graph["edge_set_hash"],
                graph["frontier_hash"],
                stable_json(graph["nodes"]),
                stable_json(graph["edges"]),
                stable_json(graph["frontier"]),
                len(graph["nodes"]),
                len(graph["edges"]),
                len(graph["frontier"]),
                graph["unresolved_count"],
                int(bool(graph["truncated"])),
            ),
        )
        _insert_graph_tables(conn, memory_id=memory_id, graph=graph)
        _insert_evidence_graph_nodes(conn, memory_id=memory_id, evidence_rows=deduped_evidence_rows)
        subject_id = _upsert_subject_overlay(
            conn,
            memory_id=memory_id,
            intent=intent,
            seed=seed,
            evidence_count=len(seen_evidence),
            graph=graph,
        )
        pattern_id = _upsert_business_pattern(
            conn,
            intent=intent,
            subject_id=subject_id,
            memory_id=memory_id,
            command_sequence=command_sequence,
            evidence_ids=evidence_ids,
        )
        conn.commit()
        wiki_refreshed = _auto_refresh_wiki(skill_dir, source_root)
        return {
            "schema": "query-memory-record/v1",
            "memory_id": memory_id,
            "subject_id": subject_id,
            "pattern_id": pattern_id,
            "trace_id": trace_id,
            "intent": intent,
            "seed": seed,
            "step_count": route_step_index,
            "negative_hint_count": negative_hint_count,
            "evidence_count": len(seen_evidence),
            "graph": {key: graph[key] for key in ("node_set_hash", "edge_set_hash", "frontier_hash", "unresolved_count", "truncated")},
            "freshness_basis": runtime,
            "stores_business_facts": False,
            "static_only": True,
            "wiki_refreshed": wiki_refreshed,
        }
    finally:
        conn.close()


def _derive_auto_seed(conn: sqlite3.Connection, trace_id: str) -> Optional[str]:
    """从 trace 的历史步骤里确定性推导一个默认 seed：取最近一次成功查询的第一个参数，
    没有则退回整条 trace 里出现次数最多的第一个参数。纯统计，不涉及语义判断。"""
    steps = _query_steps(conn, trace_id)
    if not steps:
        return None
    for step in reversed(steps):
        if step.get("error"):
            continue
        args = _parse_args_summary(step.get("args_summary"))
        if args and args[0]:
            return args[0]
    counter: Dict[str, int] = {}
    for step in steps:
        args = _parse_args_summary(step.get("args_summary"))
        if args and args[0]:
            counter[args[0]] = counter.get(args[0], 0) + 1
    if not counter:
        return None
    return max(counter.items(), key=lambda item: item[1])[0]


def auto_capture_memory(
    *,
    skill_dir: Path,
    trace_id: Optional[str],
    intent: Optional[str],
    seed: Optional[str],
    context: Dict[str, Any],
    source_root: Optional[Path],
    command_runner: CommandRunner,
) -> Dict[str, Any]:
    """兜底安全网：即使 agent 忘了显式调用 query_memory_record，也能一条命令把"当前活跃
    会话 trace"沉淀成可复用路线（不产出业务流程图，那一步仍需要 agent 用
    query_memory_attach_flow 手工归纳，因为"什么才算一次完整业务解释"本质上需要语义判断，
    静态后端无法自动判定）。

    trace_id/intent/seed 均可省略：
    - trace_id 省略时用当前仍在 TTL 内的会话 trace（session_trace.json）
    - seed 省略时用 _derive_auto_seed 从历史步骤确定性推导
    - intent 省略时固定为 "auto_capture"，避免语义化字符串污染 subject 显示名
    """
    from ue5_kb.query.query_audit import peek_session_trace

    resolved_trace_id = trace_id
    if not resolved_trace_id:
        active = peek_session_trace(skill_dir)
        if not active:
            return {
                "schema": "query-memory-auto-capture/v1",
                "error": "no active session trace found; pass trace_id explicitly or run a query first",
            }
        resolved_trace_id = active["trace_id"]

    resolved_intent = intent or "auto_capture"

    resolved_seed = seed
    if not resolved_seed:
        conn = _connect(skill_dir)
        try:
            resolved_seed = _derive_auto_seed(conn, resolved_trace_id)
        finally:
            conn.close()
        if not resolved_seed:
            return {
                "schema": "query-memory-auto-capture/v1",
                "trace_id": resolved_trace_id,
                "error": "could not derive a seed from trace history; pass seed explicitly",
            }

    result = record_memory(
        skill_dir=skill_dir,
        trace_id=resolved_trace_id,
        intent=resolved_intent,
        seed=resolved_seed,
        context=context,
        source_root=source_root,
        command_runner=command_runner,
    )
    result["schema"] = "query-memory-auto-capture/v1"
    result["auto_derived_seed"] = seed is None
    result["auto_derived_trace_id"] = trace_id is None
    return result


def _validate_flow_evidence(source_root: Optional[Path], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """程序化校验 flow 节点证据：file:line 必须真实存在且行号在范围内。

    这是堵住"AI 写假证据混过质量门禁"的机器校验闸：解释层（命名/摘要）可以由
    AI 提供，但事实层锚点必须现场可证伪。校验通过的锚点当场计算 anchor hash
    入库，供后续 flow 级新鲜度判定使用。
    """
    checked = 0
    invalid: List[Dict[str, Any]] = []
    for node in nodes:
        anchors: List[Dict[str, Any]] = []
        for ref in node.get("evidence", []):
            checked += 1
            # 允许 "path:line | 注释" 形式，仅校验 path:line 核心部分
            ref_core = str(ref).split("|", 1)[0].strip()
            path_part, _, line_part = ref_core.rpartition(":")
            reason = None
            anchor = None
            if not path_part or not line_part.isdigit():
                reason = "malformed_reference"
            elif source_root is None:
                reason = "source_root_unavailable"
            else:
                target = _relative_file_path(source_root, path_part)
                if not target.exists() or not target.is_file():
                    reason = "file_not_found"
                else:
                    line_number = int(line_part)
                    try:
                        total_lines = len(target.read_text(encoding="utf-8", errors="ignore").splitlines())
                    except OSError:
                        total_lines = 0
                    if line_number < 1 or line_number > total_lines:
                        reason = "line_out_of_range"
                    else:
                        anchor = _anchor_hash(target, line_number)
            if reason:
                invalid.append({"node": node.get("id"), "reference": ref, "reason": reason})
            else:
                anchors.append({"reference": ref, "anchor_hash": anchor})
        if anchors:
            node["evidence_anchors"] = anchors
    return {"checked": checked, "invalid": invalid, "all_valid": not invalid}


def attach_business_flow(
    *,
    skill_dir: Path,
    memory_id: str,
    flow: Dict[str, Any],
    source_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Attach an evidence-bound business-flow annotation to a recorded memory.

    The flow is an agent-curated view over already recorded evidence.  It is
    stored separately from deterministic query replay data so freshness checks
    can keep proving the underlying route while Markdown can show the useful
    business path.
    """
    conn = _connect(skill_dir)
    try:
        memory = _load_memory(conn, memory_id)
        if not memory:
            return {"schema": "query-memory-attach-flow/v1", "memory_id": memory_id, "error": "memory not found"}
        subject_id = _subject_id_for_memory(conn, memory_id)
        if not subject_id:
            subject_id = _subject_id_for(memory.get("seed") or "unknown", memory.get("intent") or "unknown")
        normalized = _normalize_business_flow(flow)
        if not normalized["nodes"]:
            return {
                "schema": "query-memory-attach-flow/v1",
                "memory_id": memory_id,
                "subject_id": subject_id,
                "error": "flow requires at least one node",
            }
        effective_source_root = source_root
        if effective_source_root is None and memory.get("source_root"):
            effective_source_root = Path(str(memory.get("source_root")))
        evidence_validation = _validate_flow_evidence(effective_source_root, normalized["nodes"])
        normalized["evidence_validation"] = evidence_validation
        annotation_id = "flow-" + uuid.uuid4().hex
        quality = normalized.get("quality") if isinstance(normalized.get("quality"), dict) else {}
        if not evidence_validation["all_valid"]:
            quality = dict(quality)
            quality["passed"] = False
            quality["status"] = "evidence_validation_failed"
            quality.setdefault("checks", {})
            quality["checks"]["invalid_evidence"] = evidence_validation["invalid"]
            normalized["quality"] = quality
        publication_status = "published" if quality.get("passed") else "candidate"
        normalized["publication_status"] = publication_status
        flow_json = stable_json_full(normalized)
        graph_hash = stable_hash_full(normalized)
        conn.execute(
            """
            INSERT INTO business_flow_annotations (
                id, memory_id, subject_id, flow_json, graph_hash, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (annotation_id, memory_id, subject_id, flow_json, graph_hash, publication_status, int(time.time())),
        )
        conn.commit()
        wiki_refreshed = _auto_refresh_wiki(skill_dir, effective_source_root)
        return {
            "schema": "query-memory-attach-flow/v1",
            "annotation_id": annotation_id,
            "memory_id": memory_id,
            "subject_id": subject_id,
            "node_count": len(normalized["nodes"]),
            "edge_count": len(normalized["edges"]),
            "lane_count": len(normalized.get("lanes", [])),
            "quality": normalized.get("quality", {}),
            "evidence_validation": evidence_validation,
            "publication_status": publication_status,
            "graph_hash": graph_hash,
            "stores_business_flow": True,
            "markdown_is_authoritative": False,
            "wiki_refreshed": wiki_refreshed,
        }
    finally:
        conn.close()


def _search_audit_traces(conn: sqlite3.Connection, keyword: str, limit: int) -> List[Dict[str, Any]]:
    pattern = f"%{keyword}%"
    rows = conn.execute(
        """
        SELECT
            trace_id,
            COUNT(*) AS step_count,
            SUM(CASE WHEN error IS NULL OR error = '' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1 ELSE 0 END) AS error_count,
            MAX(id) AS last_step_id,
            MAX(timestamp) AS last_timestamp,
            GROUP_CONCAT(DISTINCT command) AS commands,
            MAX(source) AS source_root,
            MAX(branch) AS branch_name,
            MAX(commit_id) AS commit_id,
            MAX(data_trust) AS data_trust
        FROM query_steps
        WHERE args_summary LIKE ? OR command LIKE ? OR fallback LIKE ?
        GROUP BY trace_id
        HAVING success_count > 0
        ORDER BY last_step_id DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        trace_id = row["trace_id"]
        preview_rows = conn.execute(
            """
            SELECT id, command, args_summary, result_count, error
            FROM query_steps
            WHERE trace_id = ?
            ORDER BY id ASC
            LIMIT 12
            """,
            (trace_id,),
        ).fetchall()
        results.append(
            {
                "kind": "audit_trace",
                "trace_id": trace_id,
                "step_count": row["step_count"],
                "success_count": row["success_count"],
                "error_count": row["error_count"],
                "last_step_id": row["last_step_id"],
                "last_timestamp": row["last_timestamp"],
                "commands": [item for item in str(row["commands"] or "").split(",") if item],
                "source_root": row["source_root"],
                "branch_name": row["branch_name"],
                "commit_id": row["commit_id"],
                "data_trust": row["data_trust"],
                "steps_preview": [dict(item) for item in preview_rows],
                "record_command": f"query_memory_record {trace_id} <intent> <seed>",
                "facts_reused": False,
                "reusable_as": "route_fragment",
            }
        )
    return results


def _search_negative_audit_traces(conn: sqlite3.Connection, keyword: str, limit: int) -> List[Dict[str, Any]]:
    pattern = f"%{keyword}%"
    rows = conn.execute(
        """
        SELECT
            trace_id,
            COUNT(*) AS step_count,
            SUM(CASE WHEN error IS NULL OR error = '' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1 ELSE 0 END) AS error_count,
            MAX(id) AS last_step_id,
            MAX(timestamp) AS last_timestamp,
            GROUP_CONCAT(DISTINCT command) AS commands,
            MAX(branch) AS branch_name,
            MAX(commit_id) AS commit_id
        FROM query_steps
        WHERE args_summary LIKE ? OR command LIKE ? OR fallback LIKE ?
        GROUP BY trace_id
        HAVING success_count = 0 AND error_count > 0
        ORDER BY last_step_id DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [
        {
            "kind": "negative_audit_trace",
            "trace_id": row["trace_id"],
            "step_count": row["step_count"],
            "success_count": row["success_count"],
            "error_count": row["error_count"],
            "last_step_id": row["last_step_id"],
            "last_timestamp": row["last_timestamp"],
            "commands": [item for item in str(row["commands"] or "").split(",") if item],
            "branch_name": row["branch_name"],
            "commit_id": row["commit_id"],
            "facts_reused": False,
            "reusable_as": "negative_hint_candidate",
        }
        for row in rows
    ]


def _search_evidence_matches(conn: sqlite3.Connection, keyword: str, limit: int) -> List[Dict[str, Any]]:
    pattern = f"%{keyword}%"
    rows = conn.execute(
        """
        SELECT
            e.id AS evidence_id,
            e.memory_id,
            e.file,
            e.line_start,
            e.line_end,
            e.module,
            e.symbol,
            e.file_hash,
            s.id AS subject_id,
            s.display_name AS subject_name
        FROM query_memory_evidence e
        LEFT JOIN business_subject_members m
            ON m.memory_id = e.memory_id AND m.member_kind = 'trace_route'
        LEFT JOIN business_subjects s ON s.id = m.subject_id
        WHERE e.file LIKE ? OR e.module LIKE ? OR e.symbol LIKE ?
        ORDER BY e.id DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [
        {
            "kind": "evidence_anchor",
            "evidence_id": row["evidence_id"],
            "memory_id": row["memory_id"],
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"],
            "file": row["file"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "module": row["module"],
            "symbol": row["symbol"],
            "file_hash": row["file_hash"],
            "facts_reused": False,
            "reusable_as": "evidence_anchor",
        }
        for row in rows
    ]


def search_memory(*, skill_dir: Path, keyword: str, intent: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        limit = max(1, min(int(limit), 100))
        pattern = f"%{keyword}%"
        params: List[Any] = [pattern, pattern]
        where = "(seed LIKE ? OR intent LIKE ?)"
        if intent:
            where += " AND intent = ?"
            params.append(intent)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM query_memory_patterns
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        memory_results = [dict(row) for row in rows]
        audit_results = _search_audit_traces(conn, keyword, max(1, limit - len(memory_results)))
        negative_audit_results = _search_negative_audit_traces(conn, keyword, limit)
        evidence_results = _search_evidence_matches(conn, keyword, limit)
        return {
            "schema": "query-memory-search/v1",
            "keyword": keyword,
            "intent": intent,
            "found_count": len(memory_results) + len(audit_results) + len(evidence_results),
            "pattern_count": len(memory_results),
            "audit_trace_count": len(audit_results),
            "negative_audit_trace_count": len(negative_audit_results),
            "evidence_match_count": len(evidence_results),
            "results": memory_results,
            "audit_traces": audit_results,
            "negative_audit_traces": negative_audit_results,
            "evidence_matches": evidence_results,
            "facts_reused": False,
        }
    finally:
        conn.close()


def _load_memory(conn: sqlite3.Connection, memory_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM query_memory_patterns WHERE id=?", (memory_id,)).fetchone()
    return dict(row) if row else None


def _load_memory_steps(conn: sqlite3.Connection, memory_id: str) -> List[Dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM query_memory_steps WHERE memory_id=? ORDER BY step_index", (memory_id,)).fetchall()]


def _load_memory_evidence(conn: sqlite3.Connection, memory_id: str) -> List[Dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM query_memory_evidence WHERE memory_id=? ORDER BY id", (memory_id,)).fetchall()]


def _validate_evidence(source_root: Optional[Path], evidence_rows: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    details = []
    status = "same"
    for row in evidence_rows:
        file_value = row.get("file") or ""
        path = _relative_file_path(source_root, file_value)
        current_hash = _file_hash(path)
        current_anchor_hash = _anchor_hash(path, int(row.get("line_start") or 1)) if current_hash else None
        stored_hash = row.get("file_hash")
        stored_anchor_hash = row.get("anchor_text_hash")
        if current_hash is None:
            item_status = "missing"
            status = "broken"
        elif stored_hash and current_hash != stored_hash:
            if stored_anchor_hash and current_anchor_hash == stored_anchor_hash:
                item_status = "equivalent"
                if status == "same":
                    status = "equivalent"
            else:
                item_status = "changed"
            if status not in {"broken", "changed"} and item_status == "changed":
                status = "changed"
        else:
            item_status = "same"
        details.append(
            {
                "file": file_value,
                "status": item_status,
                "stored_hash": stored_hash,
                "current_hash": current_hash,
                "stored_anchor_text_hash": stored_anchor_hash,
                "current_anchor_text_hash": current_anchor_hash,
            }
        )
    return status, details


def _replay_steps(steps: List[Dict[str, Any]], command_runner: CommandRunner) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    results = []
    graphs = []
    for step in steps:
        args = _parse_args_summary(step.get("args_summary"))
        command = step.get("command") or ""
        try:
            result = command_runner(command, args)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        current_hash = stable_hash(result)
        stored_hash = step.get("result_hash")
        status = "failed" if isinstance(result, dict) and result.get("error") else ("same" if stored_hash == current_hash else "changed")
        results.append(
            {
                "step_index": step.get("step_index"),
                "command": command,
                "args": args,
                "status": status,
                "stored_result_hash": stored_hash,
                "current_result_hash": current_hash,
                "result_count": _result_count(result),
                "error": result.get("error") if isinstance(result, dict) else None,
            }
        )
        if isinstance(result, dict):
            graphs.append(_extract_graph(result))
    return results, _merge_graph(graphs)


def _load_stored_set(value: Optional[str]) -> set:
    if not value:
        return set()
    try:
        parsed = json.loads(value)
    except Exception:
        return set()
    if isinstance(parsed, list):
        return {str(item) for item in parsed}
    return set()


def _set_change_status(stored_items: set, current_items: Iterable[str]) -> str:
    current = {str(item) for item in current_items}
    if current == stored_items:
        return "same"
    if stored_items and current.issuperset(stored_items):
        return "expanded"
    return "changed"


def validate_memory(
    *,
    skill_dir: Path,
    memory_id: str,
    context: Dict[str, Any],
    source_root: Optional[Path],
    command_runner: CommandRunner,
) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        pattern = _load_memory(conn, memory_id)
        if not pattern:
            return {"schema": "query-memory-validate/v1", "memory_id": memory_id, "error": "memory not found", "overall": "unknown"}
        steps = _load_memory_steps(conn, memory_id)
        evidence = _load_memory_evidence(conn, memory_id)
        runtime = _runtime_fingerprint(context)

        if not steps:
            return {
                "schema": "query-memory-validate/v1",
                "memory_id": memory_id,
                "overall": "broken",
                "reusable_as": "not_reusable",
                "freshness": {
                    "kb": "unknown",
                    "files": "unknown",
                    "commands": "failed",
                    "business_path": "unknown",
                },
                "provenance": {"current": runtime, "diffs": [], "affects_reusability": False},
                "reasons": ["no_successful_route_steps"],
                "evidence": [],
                "replay": [],
                "facts_reused": False,
                "static_only": True,
            }

        reasons: List[str] = []
        provenance_diffs: List[str] = []
        kb_status = "same"
        if pattern.get("source_root") and runtime.get("source_root") and pattern.get("source_root") != runtime.get("source_root"):
            provenance_diffs.append("source_root_changed")
        if pattern.get("branch_name") and runtime.get("branch_name") and pattern.get("branch_name") != runtime.get("branch_name"):
            provenance_diffs.append("branch_name_changed")
        if pattern.get("variant_id") and runtime.get("variant_id") and pattern.get("variant_id") != runtime.get("variant_id"):
            provenance_diffs.append("variant_id_changed")
        if pattern.get("dirty") is not None and runtime.get("dirty") is not None and bool(pattern.get("dirty")) != bool(runtime.get("dirty")):
            provenance_diffs.append("dirty_state_changed")
        if pattern.get("source_fingerprint") and runtime.get("source_fingerprint") and pattern.get("source_fingerprint") != runtime.get("source_fingerprint"):
            provenance_diffs.append("source_fingerprint_changed")
        if pattern.get("commit_id") and runtime.get("commit_id") and pattern.get("commit_id") != runtime.get("commit_id"):
            provenance_diffs.append("commit_id_changed")
        if runtime.get("data_trust") != "fresh":
            kb_status = "unknown"
            reasons.append("current_kb_not_fresh")

        evidence_status, evidence_details = _validate_evidence(source_root, evidence)
        if evidence_status != "same":
            reasons.append(f"evidence_{evidence_status}")

        replay, graph = _replay_steps(steps, command_runner)
        command_status = "same" if all(item["status"] == "same" for item in replay) else "changed"
        if any(item["status"] == "failed" for item in replay):
            command_status = "failed"
        if command_status != "same":
            reasons.append(f"commands_{command_status}")

        stored_graph = conn.execute("SELECT * FROM query_memory_graph WHERE memory_id=?", (memory_id,)).fetchone()
        graph_status = "same"
        if stored_graph:
            stored = dict(stored_graph)
            if stored.get("node_set_hash") != graph.get("node_set_hash"):
                graph_status = _set_change_status(_load_stored_set(stored.get("node_set_json")), graph.get("nodes", []))
                reasons.append("node_set_changed")
            if stored.get("edge_set_hash") != graph.get("edge_set_hash"):
                edge_status = _set_change_status(_load_stored_set(stored.get("edge_set_json")), graph.get("edges", []))
                if graph_status == "same" or edge_status == "changed":
                    graph_status = edge_status
                reasons.append("edge_set_changed")
            if stored.get("frontier_hash") != graph.get("frontier_hash"):
                if graph_status == "same":
                    graph_status = _set_change_status(_load_stored_set(stored.get("frontier_json")), graph.get("frontier", []))
                reasons.append("frontier_changed")

        if "current_kb_not_fresh" in reasons:
            overall = "unknown"
        elif evidence_status == "broken" or command_status == "failed":
            overall = "broken"
        elif graph_status == "expanded":
            overall = "expanded"
        elif evidence_status == "equivalent" and kb_status == "same" and command_status == "same" and graph_status == "same":
            overall = "equivalent"
        elif evidence_status == "changed" or command_status == "changed" or graph_status == "changed":
            overall = "changed"
        else:
            overall = "fresh"

        reusable_as = "route_and_evidence" if overall == "fresh" else ("route_only" if overall in {"equivalent", "expanded", "changed"} else "not_reusable")
        conn.execute("UPDATE query_memory_patterns SET last_validated_at=?, status=? WHERE id=?", (int(time.time()), overall, memory_id))
        conn.commit()
        return {
            "schema": "query-memory-validate/v1",
            "memory_id": memory_id,
            "overall": overall,
            "reusable_as": reusable_as,
            "freshness": {
                "kb": kb_status,
                "files": evidence_status,
                "commands": command_status,
                "business_path": graph_status,
            },
            "provenance": {
                "recorded": {
                    "source_root": pattern.get("source_root"),
                    "branch_name": pattern.get("branch_name"),
                    "variant_id": pattern.get("variant_id"),
                    "commit_id": pattern.get("commit_id"),
                    "dirty": bool(pattern.get("dirty")) if pattern.get("dirty") is not None else None,
                    "source_fingerprint": pattern.get("source_fingerprint"),
                },
                "current": runtime,
                "diffs": provenance_diffs,
                "affects_reusability": False,
            },
            "reasons": reasons,
            "evidence": evidence_details,
            "replay": replay,
            "facts_reused": False,
            "static_only": True,
        }
    finally:
        conn.close()


def replay_memory(
    *,
    skill_dir: Path,
    memory_id: str,
    command_runner: CommandRunner,
) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        pattern = _load_memory(conn, memory_id)
        if not pattern:
            return {"schema": "query-memory-replay/v1", "memory_id": memory_id, "error": "memory not found"}
        steps = _load_memory_steps(conn, memory_id)
        replay, graph = _replay_steps(steps, command_runner)
        return {
            "schema": "query-memory-replay/v1",
            "memory_id": memory_id,
            "step_count": len(replay),
            "steps": replay,
            "graph": {key: graph[key] for key in ("node_set_hash", "edge_set_hash", "frontier_hash", "unresolved_count", "truncated")},
            "facts_reused": False,
        }
    finally:
        conn.close()


def diff_memory(
    *,
    skill_dir: Path,
    memory_id: str,
    context: Dict[str, Any],
    source_root: Optional[Path],
    command_runner: CommandRunner,
) -> Dict[str, Any]:
    validation = validate_memory(
        skill_dir=skill_dir,
        memory_id=memory_id,
        context=context,
        source_root=source_root,
        command_runner=command_runner,
    )
    result = {
        "schema": "query-memory-diff/v1",
        "memory_id": memory_id,
        "overall": validation.get("overall"),
        "reasons": validation.get("reasons", []),
        "changed_steps": [item for item in validation.get("replay", []) if item.get("status") != "same"],
        "changed_evidence": [item for item in validation.get("evidence", []) if item.get("status") != "same"],
        "facts_reused": False,
    }
    conn = _connect(skill_dir)
    try:
        base = conn.execute(
            """
            SELECT s.id, s.subject_id, s.pattern_id FROM memory_snapshots s
            JOIN memory_snapshot_members m ON m.snapshot_id = s.id
            WHERE m.memory_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (memory_id,),
        ).fetchone()
        pattern_row = conn.execute(
            "SELECT intent, seed FROM query_memory_patterns WHERE id=?",
            (memory_id,),
        ).fetchone()
        subject_id = _subject_id_for(pattern_row["seed"], pattern_row["intent"]) if pattern_row else None
        snapshot_target = None
        if base and base["pattern_id"]:
            snapshot_target = base["pattern_id"]
        elif base and base["subject_id"]:
            snapshot_target = base["subject_id"]
        else:
            snapshot_target = subject_id
        head_snapshot_id = None
        if snapshot_target:
            head = snapshot_memory(skill_dir=skill_dir, subject_or_pattern_id=snapshot_target)
            head_snapshot_id = head.get("snapshot_id")
        diff_id = "diff-" + uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO memory_diffs (id, base_snapshot_id, head_snapshot_id, diff_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (diff_id, base["id"] if base else None, head_snapshot_id, stable_json(result), int(time.time())),
        )
        conn.commit()
        result["diff_id"] = diff_id
        result["base_snapshot_id"] = base["id"] if base else None
        result["head_snapshot_id"] = head_snapshot_id
    finally:
        conn.close()
    return result


def list_subjects(*, skill_dir: Path, keyword: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        limit = max(1, min(int(limit), 200))
        params: List[Any] = []
        where = "1=1"
        if keyword:
            where = "(s.display_name LIKE ? OR s.primary_symbol LIKE ? OR a.alias LIKE ?)"
            pattern = f"%{keyword}%"
            params.extend([pattern, pattern, pattern])
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
                s.id,
                s.display_name,
                s.primary_symbol,
                s.status,
                COUNT(DISTINCT m.id) AS member_count,
                COUNT(DISTINCT a.id) AS alias_count,
                MAX(s.updated_at) AS updated_at
            FROM business_subjects s
            LEFT JOIN business_subject_aliases a ON a.subject_id = s.id
            LEFT JOIN business_subject_members m ON m.subject_id = s.id
            WHERE {where}
            GROUP BY s.id
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return {
            "schema": "query-memory-subjects/v1",
            "keyword": keyword,
            "found_count": len(rows),
            "subjects": [dict(row) for row in rows],
            "facts_reused": False,
        }
    finally:
        conn.close()


def list_negative_hints(*, skill_dir: Path, keyword: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        limit = max(1, min(int(limit), 200))
        params: List[Any] = []
        where = "1=1"
        if keyword:
            pattern = f"%{keyword}%"
            where = "(command LIKE ? OR args_summary LIKE ? OR error_summary LIKE ? OR failure_type LIKE ?)"
            params.extend([pattern, pattern, pattern, pattern])
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM negative_hints
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return {
            "schema": "query-memory-negative-hints/v1",
            "keyword": keyword,
            "found_count": len(rows),
            "negative_hints": [dict(row) for row in rows],
            "participates_in_main_graph": False,
        }
    finally:
        conn.close()


def _subject_graph(conn: sqlite3.Connection, subject_id: str) -> Dict[str, Any]:
    subject = conn.execute("SELECT * FROM business_subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        return {}
    memory_ids = [
        row["memory_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT memory_id FROM business_subject_members
            WHERE subject_id=? AND memory_id IS NOT NULL
            ORDER BY memory_id
            """,
            (subject_id,),
        ).fetchall()
    ]
    nodes = []
    edges = []
    evidence = []
    memories = []
    for memory_id in memory_ids:
        memory_row = conn.execute("SELECT * FROM query_memory_patterns WHERE id=?", (memory_id,)).fetchone()
        if memory_row:
            memories.append(dict(memory_row))
        nodes.extend(
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_memory_graph_nodes WHERE memory_id=? ORDER BY label",
                (memory_id,),
            ).fetchall()
        )
        edges.extend(
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_memory_graph_edges WHERE memory_id=? ORDER BY source_key, target_key",
                (memory_id,),
            ).fetchall()
        )
        evidence.extend(
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_memory_evidence WHERE memory_id=? ORDER BY file, line_start",
                (memory_id,),
            ).fetchall()
        )
    deduped_evidence: Dict[Tuple[Any, Any, Any], Dict[str, Any]] = {}
    for item in evidence:
        key = (item.get("file"), item.get("line_start"), item.get("symbol"))
        existing = deduped_evidence.get(key)
        if existing is None or (not existing.get("module") and item.get("module")):
            deduped_evidence[key] = item
    flow_row = conn.execute(
        """
        SELECT * FROM business_flow_annotations
        WHERE subject_id=? AND status='published'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (subject_id,),
    ).fetchone()
    business_flow = None
    if flow_row:
        try:
            business_flow = json.loads(flow_row["flow_json"])
            business_flow["_annotation"] = {
                "id": flow_row["id"],
                "memory_id": flow_row["memory_id"],
                "graph_hash": flow_row["graph_hash"],
                "status": flow_row["status"] if "status" in flow_row.keys() else "published",
                "created_at": flow_row["created_at"],
            }
        except Exception:
            business_flow = None
    return {
        "subject": dict(subject),
        "graph_kind": "subject",
        "memory_ids": memory_ids,
        "memories": memories,
        "nodes": nodes,
        "edges": edges,
        "business_flow": business_flow,
        "evidence": list(deduped_evidence.values()),
        "graph_hash": stable_hash({"nodes": nodes, "edges": edges, "business_flow": business_flow, "evidence": list(deduped_evidence.values())}),
    }


def _pattern_graph(conn: sqlite3.Connection, pattern_id: str) -> Dict[str, Any]:
    pattern = conn.execute("SELECT * FROM business_patterns WHERE id=?", (pattern_id,)).fetchone()
    if not pattern:
        return {}
    stages = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM business_pattern_stages WHERE pattern_id=? ORDER BY stage_index, stage_name",
            (pattern_id,),
        ).fetchall()
    ]
    subject_ids = [
        row["subject_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT subject_id FROM business_pattern_evidence
            WHERE pattern_id=? AND subject_id IS NOT NULL
            ORDER BY subject_id
            """,
            (pattern_id,),
        ).fetchall()
    ]
    evidence_ids = [
        row["evidence_id"]
        for row in conn.execute(
            "SELECT DISTINCT evidence_id FROM business_pattern_evidence WHERE pattern_id=? ORDER BY evidence_id",
            (pattern_id,),
        ).fetchall()
    ]
    evidence = []
    memory_ids = []
    for evidence_id in evidence_ids:
        row = conn.execute("SELECT * FROM query_memory_evidence WHERE id=?", (evidence_id,)).fetchone()
        if not row:
            continue
        item = dict(row)
        evidence.append(item)
        if item.get("memory_id") and item["memory_id"] not in memory_ids:
            memory_ids.append(item["memory_id"])
    nodes = []
    edges = []
    memories = []
    for memory_id in memory_ids:
        memory_row = conn.execute("SELECT * FROM query_memory_patterns WHERE id=?", (memory_id,)).fetchone()
        if memory_row:
            memories.append(dict(memory_row))
        nodes.extend(
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_memory_graph_nodes WHERE memory_id=? ORDER BY node_kind, label",
                (memory_id,),
            ).fetchall()
        )
        edges.extend(
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_memory_graph_edges WHERE memory_id=? ORDER BY source_key, target_key",
                (memory_id,),
            ).fetchall()
        )
    subjects = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM business_subjects WHERE id IN ({','.join(['?'] * len(subject_ids))}) ORDER BY display_name"
            if subject_ids
            else "SELECT * FROM business_subjects WHERE 0",
            subject_ids,
        ).fetchall()
    ]
    return {
        "pattern": dict(pattern),
        "graph_kind": "pattern",
        "subject_ids": subject_ids,
        "subjects": subjects,
        "memory_ids": memory_ids,
        "memories": memories,
        "stages": stages,
        "nodes": nodes,
        "edges": edges,
        "evidence": evidence,
        "graph_hash": stable_hash({"pattern": dict(pattern), "stages": stages, "nodes": nodes, "edges": edges, "evidence": evidence}),
    }


def _attach_query_steps(conn: sqlite3.Connection, graph: Dict[str, Any]) -> Dict[str, Any]:
    for memory in graph.get("memories", []):
        memory_id = memory.get("id")
        if not memory_id:
            memory["_steps"] = []
            continue
        memory["_steps"] = [
            dict(row)
            for row in conn.execute(
                "SELECT step_index, command, args_summary, result_count, error FROM query_memory_steps WHERE memory_id=? ORDER BY step_index",
                (memory_id,),
            ).fetchall()
        ]
    return graph


def _attach_evolution_events(conn: sqlite3.Connection, graph: Dict[str, Any]) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    subject = graph.get("subject")
    pattern = graph.get("pattern")
    if subject:
        subject_id = subject.get("id")
        rows = conn.execute(
            """
            SELECT id, graph_hash, status, created_at FROM business_flow_annotations
            WHERE subject_id=?
            ORDER BY created_at
            """,
            (subject_id,),
        ).fetchall()
        for row in rows:
            events.append({
                "kind": "flow",
                "kind_label": "流程附注",
                "id": row["id"],
                "display": f"{row['status']} {str(row['id'])[:12]}",
                "created_at": row["created_at"],
                "graph_hash": row["graph_hash"],
            })
        snapshot_rows = conn.execute(
            """
            SELECT id, graph_hash, created_at FROM memory_snapshots
            WHERE subject_id=?
            ORDER BY created_at
            """,
            (subject_id,),
        ).fetchall()
    elif pattern:
        pattern_id = pattern.get("id")
        snapshot_rows = conn.execute(
            """
            SELECT id, graph_hash, created_at FROM memory_snapshots
            WHERE pattern_id=?
            ORDER BY created_at
            """,
            (pattern_id,),
        ).fetchall()
    else:
        snapshot_rows = []
    for row in snapshot_rows:
        events.append({
            "kind": "snapshot",
            "kind_label": "快照",
            "id": row["id"],
            "display": str(row["id"])[:12],
            "created_at": row["created_at"],
            "graph_hash": row["graph_hash"],
        })
    graph["evolution_events"] = sorted(events, key=lambda item: (item.get("created_at") or 0, item.get("id") or ""))
    return graph


def _graph_title(graph: Dict[str, Any]) -> str:
    if graph.get("subject"):
        return str(graph["subject"].get("display_name") or graph["subject"].get("id") or "业务主题")
    if graph.get("pattern"):
        return _human_pattern_name(graph["pattern"].get("name"))
    return "Memory Graph"


def _view_label(view: str) -> str:
    return {
        "business": "业务视图",
        "evidence": "证据视图",
        "evolution": "演进视图",
        "query-path": "查询路径视图",
        "full": "完整视图",
    }.get(view, view)


def _mermaid_for_graph_view(graph: Dict[str, Any], view: str) -> str:
    if view == "business":
        return _mermaid_for_business_overview(graph)
    if view == "evidence":
        return _mermaid_for_evidence_view(graph)
    if view == "query-path":
        return _mermaid_for_query_path_view(graph)
    if view == "evolution":
        return _mermaid_for_evolution_view(graph)
    return _mermaid_for_graph(graph)


def _render_graph_view_markdown(graph: Dict[str, Any], view: str) -> str:
    title = _graph_title(graph)
    lines = [
        "---",
        "generated_by: UE5_KnowledgeBaseMaker query_memory_render_graph",
        "schema_version: query-memory-graph-view/v1",
        f"graph_kind: {graph.get('graph_kind')}",
        f"view: {view}",
        f"graph_hash: {graph.get('graph_hash')}",
        f"generated_at: {int(time.time())}",
        "data_source: memory/memory.sqlite",
        "markdown_is_authoritative: false",
        "---",
        "",
        f"# {title} - {_view_label(view)}",
        "",
        "```mermaid",
        _mermaid_for_graph_view(graph, view),
        "```",
        "",
        "## 视图说明",
        "",
    ]
    if view == "business":
        lines.append("- 展示业务流程或模式流程，适合人先看全局结构。")
    elif view == "evidence":
        lines.append("- 展示主题/模式与源码证据文件、行号锚点的关系，用来复查事实来源。")
    elif view == "query-path":
        lines.append("- 展示历史查询路线的命令顺序，用来复用或审计 AI 是怎么查到这里的。")
    elif view == "evolution":
        lines.append("- 展示快照和流程附注随时间的变化，用来追踪 memory 演化。")
    lines.extend(["", "## 统计", "", "| 项 | 数量 |", "| --- | ---: |"])
    lines.append(f"| 业务主题 | {len(graph.get('subjects', [])) if graph.get('pattern') else 1 if graph.get('subject') else 0} |")
    lines.append(f"| 路线记忆 | {len(graph.get('memories', []))} |")
    lines.append(f"| 证据 | {len(graph.get('evidence', []))} |")
    if view == "query-path":
        step_count = sum(len(memory.get("_steps", [])) for memory in graph.get("memories", []))
        compacted_step_count = sum(len(_compact_query_steps(memory.get("_steps", []))) for memory in graph.get("memories", []))
        lines.append(f"| 查询步骤 | {step_count} |")
        lines.append(f"| 压缩后步骤 | {compacted_step_count} |")
    if view == "evolution":
        lines.append(f"| 演进事件 | {len(graph.get('evolution_events', []))} |")
    lines.extend(["", "## 明细", ""])
    if view == "query-path":
        for memory in graph.get("memories", []):
            lines.append(f"### {memory.get('id')}")
            for step in _compact_query_steps(memory.get("_steps", [])):
                args = step.get("args_summary") or ""
                if int(step.get("count") or 1) > 1:
                    args = f"{args} ... {step.get('last_args_summary') or ''}".strip()
                lines.append(f"- {_compact_step_label(step)} `{step.get('command')}` {args}")
            lines.append("")
    elif view == "evolution":
        for event in graph.get("evolution_events", []):
            lines.append(f"- `{event.get('kind')}` `{event.get('id')}` {event.get('display')} hash `{event.get('graph_hash')}`")
    elif view == "evidence":
        lines.extend(["| 文件 | 行号 | 模块 | 符号 | 文件哈希 |", "| --- | ---: | --- | --- | --- |"])
        for item in graph.get("evidence", []):
            lines.append(
                f"| {_markdown_table_cell(item.get('file'))} | {item.get('line_start') or ''} | {_markdown_table_cell(item.get('module'))} | {_markdown_table_cell(item.get('symbol'))} | {_markdown_table_cell(item.get('file_hash'))} |"
            )
    else:
        for memory_id in graph.get("memory_ids", []):
            lines.append(f"- `{memory_id}`")
    lines.extend(["", "## 说明", "", "本文件由 `memory/memory.sqlite` 程序化生成，是图视图导出；事实仍以 sqlite、hash、validate/replay 为准。"])
    return "\n".join(lines) + "\n"


def _graph_provenance(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    seen = set()
    for memory in graph.get("memories", []):
        item = {
            "memory_id": memory.get("id"),
            "commit_id": memory.get("commit_id"),
            "branch_name": memory.get("branch_name"),
            "variant_id": memory.get("variant_id"),
            "source_root": memory.get("source_root"),
            "source_fingerprint": memory.get("source_fingerprint"),
        }
        key = tuple(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items


def snapshot_memory(*, skill_dir: Path, subject_or_pattern_id: str) -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        graph = _subject_graph(conn, subject_or_pattern_id)
        graph_kind = "subject"
        if not graph:
            graph = _pattern_graph(conn, subject_or_pattern_id)
            graph_kind = "pattern"
        if not graph:
            return {
                "schema": "query-memory-snapshot/v1",
                "id": subject_or_pattern_id,
                "error": "subject or pattern not found",
            }
        snapshot_id = "snapshot-" + uuid.uuid4().hex
        now = int(time.time())
        graph_hash = graph["graph_hash"]
        subject = graph.get("subject")
        pattern = graph.get("pattern")
        provenance = _graph_provenance(graph)
        commits = sorted({item.get("commit_id") for item in provenance if item.get("commit_id")})
        branches = sorted({item.get("branch_name") for item in provenance if item.get("branch_name")})
        variants = sorted({item.get("variant_id") for item in provenance if item.get("variant_id")})
        conn.execute(
            """
            INSERT INTO memory_snapshots (
                id, subject_id, pattern_id, memory_id, snapshot_json, graph_hash,
                commit_id, branch_name, variant_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                subject_or_pattern_id if graph_kind == "subject" else None,
                subject_or_pattern_id if graph_kind == "pattern" else None,
                ",".join(graph.get("memory_ids", [])),
                stable_json(graph),
                graph_hash,
                ",".join(commits),
                ",".join(branches),
                ",".join(variants),
                now,
            ),
        )
        for memory_id in graph.get("memory_ids", []):
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_snapshot_members (snapshot_id, memory_id)
                VALUES (?, ?)
                """,
                (snapshot_id, memory_id),
            )
        conn.commit()
        return {
            "schema": "query-memory-snapshot/v1",
            "snapshot_id": snapshot_id,
            "subject_id": subject_or_pattern_id if graph_kind == "subject" else None,
            "pattern_id": subject_or_pattern_id if graph_kind == "pattern" else None,
            "display_name": (subject or pattern or {}).get("display_name") or (pattern or {}).get("name"),
            "graph_hash": graph_hash,
            "commit_id": ",".join(commits),
            "branch_name": ",".join(branches),
            "variant_id": ",".join(variants),
            "provenance": provenance,
            "provenance_count": len(provenance),
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "evidence_count": len(graph["evidence"]),
            "snapshot_is_authoritative": True,
        }
    finally:
        conn.close()


def _mermaid_for_graph(graph: Dict[str, Any]) -> str:
    business_flow = graph.get("business_flow")
    if isinstance(business_flow, dict) and business_flow.get("nodes"):
        return _mermaid_for_business_flow(business_flow)
    lines = ["flowchart TD"]
    labels = {row.get("node_key"): row.get("label") for row in graph.get("nodes", [])}
    if not graph.get("edges") and not labels:
        subject_label = str(graph.get("subject", {}).get("display_name") or "Subject").replace('"', "'")
        lines.append(f'  subject["{subject_label}"]')
        for index, item in enumerate(graph.get("evidence", []), start=1):
            file_label = str(item.get("file") or f"evidence {index}").replace('"', "'")
            line = item.get("line_start") or ""
            lines.append(f'  ev{index}["{file_label}:{line}"]')
            lines.append(f"  subject -->|evidence| ev{index}")
        return "\n".join(lines)
    if not graph.get("edges"):
        for key, label in labels.items():
            lines.append(f'  {key[:12]}["{str(label).replace(chr(34), chr(39))}"]')
    for edge in graph.get("edges", []):
        source_key = str(edge.get("source_key", ""))
        target_key = str(edge.get("target_key", ""))
        source_label = labels.get(source_key, source_key[:12])
        target_label = labels.get(target_key, target_key[:12])
        source_id = source_key[:12]
        target_id = target_key[:12]
        edge_type = str(edge.get("edge_type") or "rel").replace('"', "'")
        lines.append(f'  {source_id}["{source_label}"] -->|{edge_type}| {target_id}["{target_label}"]')
    return "\n".join(lines)


def _safe_mermaid_id(value: str, index: int) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8", "ignore")).hexdigest()[:10]
    return f"n{index}_{digest}"


def _mermaid_label(value: Any) -> str:
    text = str(value or "").replace("\r\n", " ").replace("\n", " ")
    return (
        text.replace('"', "'")
        .replace("|", "¦")
        .replace("[", "(")
        .replace("]", ")")
    )


def _markdown_table_cell(value: Any) -> str:
    return (
        str(value or "")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("|", "&#124;")
    )


_INTENT_LABELS = {
    "explain_business_flow": "业务流程解释模式",
    "trace_business_flow": "业务链路追踪模式",
    "layer_pattern_smoke": "Layer 模式冒烟验证",
}


_COMMAND_STAGE_LABELS = {
    "preflight": "确认知识库与源码新鲜度",
    "query_memory_search": "复用历史查询路线",
    "search_classes": "搜索候选类",
    "search_files": "搜索候选文件",
    "search_functions": "搜索候选函数",
    "resolve_seed": "解析业务入口",
    "query_class_info": "查看类结构",
    "query_class_hierarchy": "查看继承关系",
    "get_function_implementation": "读取函数实现",
    "query_static_closure": "扩展静态闭包",
    "query_flow": "查看调用/依赖流",
    "trace_flow_path": "追踪路径",
    "source_slice": "回源读取代码片段",
    "symbol_evidence_bundle": "收集符号证据包",
    "query_memory_record": "沉淀查询路线",
    "query_memory_attach_flow": "附加业务流程图",
    "query_memory_render": "生成可视化文档",
}


def _human_pattern_name(name: Any) -> str:
    raw = str(name or "unknown").strip() or "unknown"
    return _INTENT_LABELS.get(raw, raw.replace("_", " ").strip().title())


def _human_stage_name(stage_name: Any) -> str:
    raw = str(stage_name or "route_step").strip() or "route_step"
    return _COMMAND_STAGE_LABELS.get(raw, raw.replace("_", " "))


def _pattern_quality(graph: Dict[str, Any]) -> Dict[str, Any]:
    subject_count = len(graph.get("subjects", []))
    stage_count = len(graph.get("stages", []))
    evidence_count = len(graph.get("evidence", []))
    memory_count = len(graph.get("memories", []))
    status = str((graph.get("pattern") or {}).get("status") or "candidate")
    score = 0
    score += min(35, subject_count * 18)
    score += min(25, stage_count * 5)
    score += min(25, evidence_count * 8)
    score += min(15, memory_count * 8)
    reusable = status == "active" and subject_count >= 2 and stage_count >= 3 and evidence_count >= 3 and score >= 85
    if reusable:
        label = "可复用模式"
        recommendation = "可以作为相似业务的起步路线，但仍必须 validate/replay 并回源验证。"
    elif subject_count >= 2:
        label = "低价值模式"
        recommendation = "有多个业务主题支撑，但阶段或证据太薄，只能当线索，不能当可复用查询模式。"
    else:
        label = "候选模式"
        recommendation = "暂不建议直接复用；至少需要两个业务主题和足够证据后再视为可复用模式。"
    return {
        "score": min(100, score),
        "label": label,
        "recommendation": recommendation,
        "subject_count": subject_count,
        "stage_count": stage_count,
        "evidence_count": evidence_count,
        "memory_count": memory_count,
    }


def _mermaid_for_business_flow(flow: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    node_ids: Dict[str, str] = {}
    nodes = flow.get("nodes", [])
    for index, node in enumerate(flow.get("nodes", []), start=1):
        raw_id = str(node.get("id") or f"step_{index}")
        mermaid_id = _safe_mermaid_id(raw_id, index)
        node_ids[raw_id] = mermaid_id
    lanes = flow.get("lanes") if isinstance(flow.get("lanes"), list) else []
    if lanes:
        for lane_index, lane in enumerate(lanes, start=1):
            lane_name = str(lane)
            lane_nodes = [node for node in nodes if str(node.get("lane") or "业务流程") == lane_name]
            if not lane_nodes:
                continue
            lines.append(f'  subgraph lane{lane_index}["{_mermaid_label(lane_name)}"]')
            for node in lane_nodes:
                raw_id = str(node.get("id"))
                mermaid_id = node_ids.get(raw_id)
                if not mermaid_id:
                    continue
                label = _mermaid_label(node.get("label") or raw_id)
                lines.append(f'    {mermaid_id}["{label}"]')
            lines.append("  end")
    else:
        for node in nodes:
            raw_id = str(node.get("id"))
            mermaid_id = node_ids.get(raw_id)
            if not mermaid_id:
                continue
            label = _mermaid_label(node.get("label") or raw_id)
            lines.append(f'  {mermaid_id}["{label}"]')
    for edge in flow.get("edges", []):
        source = node_ids.get(str(edge.get("source")))
        target = node_ids.get(str(edge.get("target")))
        if not source or not target:
            continue
        label = _mermaid_label(edge.get("condition") or edge.get("label") or "next")
        lines.append(f"  {source} -->|{label}| {target}")
    return "\n".join(lines)


def _mermaid_for_pattern(graph: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    pattern = graph.get("pattern") or {}
    pattern_id = _safe_mermaid_id(pattern.get("id") or "pattern", 0)
    lines.append(f'  {pattern_id}["{_mermaid_label(_human_pattern_name(pattern.get("name")))}"]')
    stage_ids: Dict[str, str] = {}
    if graph.get("stages"):
        lines.append('  subgraph stages["查询阶段"]')
        for index, stage in enumerate(graph.get("stages", []), start=1):
            stage_name = str(stage.get("stage_name") or f"stage_{index}")
            stage_id = _safe_mermaid_id(f"stage:{stage_name}", index)
            stage_ids[stage_name] = stage_id
            label = f"{index}. {_human_stage_name(stage_name)}"
            lines.append(f'    {stage_id}["{_mermaid_label(label)}"]')
        lines.append("  end")
        previous = pattern_id
        for stage in graph.get("stages", []):
            stage_id = stage_ids.get(str(stage.get("stage_name") or ""))
            if stage_id:
                lines.append(f"  {previous} --> {stage_id}")
                previous = stage_id
    if graph.get("subjects"):
        lines.append('  subgraph subjects["支撑业务主题"]')
        for index, subject in enumerate(graph.get("subjects", []), start=1):
            subject_id = _safe_mermaid_id(f"subject:{subject.get('id')}", index)
            lines.append(f'    {subject_id}["{_mermaid_label(subject.get("display_name"))}"]')
            if stage_ids:
                lines.append(f"  {list(stage_ids.values())[-1]} -->|支撑| {subject_id}")
            else:
                lines.append(f"  {pattern_id} -->|支撑| {subject_id}")
        lines.append("  end")
    if graph.get("evidence"):
        evidence_id = _safe_mermaid_id(f"evidence:{pattern.get('id')}", 999)
        lines.append(f'  {evidence_id}["证据 {len(graph.get("evidence", []))} 条"]')
        if graph.get("subjects"):
            for index, subject in enumerate(graph.get("subjects", []), start=1):
                subject_id = _safe_mermaid_id(f"subject:{subject.get('id')}", index)
                lines.append(f"  {subject_id} --> {evidence_id}")
        else:
            lines.append(f"  {pattern_id} --> {evidence_id}")
    return "\n".join(lines)


def _mermaid_for_evidence_view(graph: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    root_label = graph.get("subject", {}).get("display_name") or _human_pattern_name(graph.get("pattern", {}).get("name"))
    root_id = _safe_mermaid_id(f"root:{root_label}", 0)
    lines.append(f'  {root_id}["{_mermaid_label(root_label)}"]')
    file_nodes: Dict[str, str] = {}
    for index, item in enumerate(graph.get("evidence", []), start=1):
        file_value = str(item.get("file") or f"evidence_{index}")
        file_id = file_nodes.get(file_value)
        if not file_id:
            file_id = _safe_mermaid_id(f"file:{file_value}", len(file_nodes) + 1)
            file_nodes[file_value] = file_id
            lines.append(f'  {file_id}["{_mermaid_label(file_value)}"]')
            lines.append(f"  {root_id} -->|证据| {file_id}")
        anchor_id = _safe_mermaid_id(f"anchor:{file_value}:{item.get('line_start')}:{index}", index + 1000)
        anchor_label = f"{item.get('line_start') or '?'} {item.get('symbol') or item.get('module') or ''}".strip()
        lines.append(f'  {anchor_id}["{_mermaid_label(anchor_label)}"]')
        lines.append(f"  {file_id} --> {anchor_id}")
    return "\n".join(lines)


def _compact_query_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for step in steps:
        command = str(step.get("command") or "")
        if compacted and compacted[-1].get("command") == command:
            compacted[-1]["end_index"] = step.get("step_index")
            compacted[-1]["count"] = int(compacted[-1].get("count") or 1) + 1
            compacted[-1]["last_args_summary"] = step.get("args_summary")
            continue
        item = dict(step)
        item["start_index"] = step.get("step_index")
        item["end_index"] = step.get("step_index")
        item["count"] = 1
        item["last_args_summary"] = step.get("args_summary")
        compacted.append(item)
    return compacted


def _compact_step_label(step: Dict[str, Any]) -> str:
    start = step.get("start_index") or step.get("step_index")
    end = step.get("end_index") or start
    prefix = str(start) if start == end else f"{start}-{end}"
    suffix = f" x{step.get('count')}" if int(step.get("count") or 1) > 1 else ""
    return f"{prefix}. {_human_stage_name(step.get('command'))}{suffix}"


def _mermaid_for_query_path_view(graph: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    root_label = graph.get("subject", {}).get("display_name") or _human_pattern_name(graph.get("pattern", {}).get("name"))
    root_id = _safe_mermaid_id(f"route:{root_label}", 0)
    lines.append(f'  {root_id}["{_mermaid_label(root_label)}"]')
    for memory_index, memory in enumerate(graph.get("memories", []), start=1):
        memory_id = memory.get("id")
        mem_node = _safe_mermaid_id(f"memory:{memory_id}", memory_index)
        lines.append(f'  {mem_node}["{_mermaid_label(str(memory_id)[:12])}"]')
        lines.append(f"  {root_id} -->|路线| {mem_node}")
        previous = mem_node
        for step_index, step in enumerate(_compact_query_steps(memory.get("_steps", [])), start=1):
            step_node = _safe_mermaid_id(f"step:{memory_id}:{step_index}:{step.get('command')}", memory_index * 100 + step_index)
            label = _compact_step_label(step)
            lines.append(f'  {step_node}["{_mermaid_label(label)}"]')
            lines.append(f"  {previous} --> {step_node}")
            previous = step_node
    return "\n".join(lines)


def _mermaid_for_business_overview(graph: Dict[str, Any]) -> str:
    if graph.get("pattern"):
        return _mermaid_for_pattern(graph)
    business_flow = graph.get("business_flow")
    if not isinstance(business_flow, dict) or not business_flow.get("nodes"):
        return _mermaid_for_graph(graph)
    lanes = business_flow.get("lanes") if isinstance(business_flow.get("lanes"), list) else []
    if not lanes:
        return _mermaid_for_business_flow(business_flow)
    lines = ["flowchart TD"]
    previous = None
    for index, lane in enumerate(lanes, start=1):
        lane_nodes = [node for node in business_flow.get("nodes", []) if str(node.get("lane") or "业务流程") == str(lane)]
        lane_id = _safe_mermaid_id(f"lane:{lane}", index)
        lines.append(f'  {lane_id}["{_mermaid_label(f"{lane} ({len(lane_nodes)} 节点)")}"]')
        if previous:
            lines.append(f"  {previous} --> {lane_id}")
        previous = lane_id
    return "\n".join(lines)


def _mermaid_for_evolution_view(graph: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    root_label = graph.get("subject", {}).get("display_name") or _human_pattern_name(graph.get("pattern", {}).get("name"))
    root_id = _safe_mermaid_id(f"evolution:{root_label}", 0)
    lines.append(f'  {root_id}["{_mermaid_label(root_label)}"]')
    previous = root_id
    events = graph.get("evolution_events", [])
    if not events:
        lines.append(f'  empty["暂无快照或流程附注演进记录"]')
        lines.append(f"  {root_id} --> empty")
        return "\n".join(lines)
    for index, event in enumerate(events, start=1):
        event_id = _safe_mermaid_id(f"event:{event.get('kind')}:{event.get('id')}:{index}", index)
        label = f"{event.get('kind_label')} {event.get('display')}"
        lines.append(f'  {event_id}["{_mermaid_label(label)}"]')
        lines.append(f"  {previous} --> {event_id}")
        previous = event_id
    return "\n".join(lines)


def _render_subject_markdown(graph: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None) -> str:
    subject = graph["subject"]
    business_flow = graph.get("business_flow")
    has_business_flow = isinstance(business_flow, dict) and bool(business_flow.get("nodes"))
    flow_diagram = _mermaid_for_business_flow(business_flow) if has_business_flow else _mermaid_for_graph(graph)
    lines = [
        "---",
        "generated_by: UE5_KnowledgeBaseMaker query_memory_render",
        "schema_version: query-memory-obsidian/v1",
        f"subject_id: {subject.get('id')}",
        f"graph_hash: {graph.get('graph_hash')}",
        f"generated_at: {int(time.time())}",
        "data_source: memory/memory.sqlite",
        "markdown_is_authoritative: false",
        "---",
        "",
        f"# {subject.get('display_name')}",
        "",
        "## 流程图",
        "",
        "```mermaid",
        flow_diagram,
        "```",
        "",
        "## 质量评分",
        "",
    ]
    if has_business_flow:
        quality = business_flow.get("quality") or {}
        checks = quality.get("checks") if isinstance(quality.get("checks"), dict) else {}
        baseline = business_flow.get("quality_baseline") if isinstance(business_flow.get("quality_baseline"), dict) else {}
        lines.extend([
            f"- 分数：`{quality.get('score', 0)}`",
            f"- 状态：`{quality.get('status', '')}`",
            f"- 基线：`{baseline.get('id') or 'generic-business-flow'}`",
            f"- 节点/边/泳道：`{checks.get('node_count', 0)}` / `{checks.get('edge_count', 0)}` / `{checks.get('lane_count', 0)}`",
            f"- 节点证据覆盖：`{checks.get('nodes_with_evidence', 0)}` / `{checks.get('node_count', 0)}`",
            f"- 关键实体覆盖：`{checks.get('required_terms_covered', 0)}` / `{checks.get('required_terms_total', 0)}`",
        ])
        missing_terms = checks.get("missing_terms") or []
        if missing_terms:
            lines.append(f"- 缺失关键实体：`{', '.join(str(item) for item in missing_terms)}`")
    else:
        lines.append("- 尚无发布态业务流程附注，无法进行业务图质量评分。")
    lines.extend([
        "",
        "## 业务流程",
        "",
    ])
    if has_business_flow:
        annotation = business_flow.get("_annotation") or {}
        if annotation:
            lines.append(f"- 附注来源：`{annotation.get('id')}`，memory `{annotation.get('memory_id')}`")
        lanes = business_flow.get("lanes") if isinstance(business_flow.get("lanes"), list) else ["业务流程"]
        for lane in lanes:
            lane_nodes = [node for node in business_flow.get("nodes", []) if str(node.get("lane") or "业务流程") == str(lane)]
            if not lane_nodes:
                continue
            lines.extend(["", f"### {lane}", ""])
            for index, node in enumerate(lane_nodes, start=1):
                summary = node.get("summary") or ""
                lines.append(f"- {index}. `{node.get('kind')}` {node.get('label')}: {summary}")
                for detail in node.get("details", []):
                    lines.append(f"  - {detail}")
    else:
        lines.append("- 尚未保存通过质量基线的业务流程附注；上方流程图为静态代码关系兜底图。")
    lines.extend([
        "",
        "## 节点证据",
        "",
        "| 节点 | 泳道 | 证据 |",
        "| --- | --- | --- |",
    ])
    if has_business_flow:
        for node in business_flow.get("nodes", []):
            evidence = "<br>".join(_markdown_table_cell(item) for item in node.get("evidence", []))
            lines.append(f"| {_markdown_table_cell(node.get('label'))} | {_markdown_table_cell(node.get('lane'))} | {evidence} |")
    else:
        lines.append("|  |  |  |")
    lines.extend([
        "",
        "## 证据",
        "",
        "| 文件 | 行号 | 模块 | 符号 | 文件哈希 |",
        "| --- | ---: | --- | --- | --- |",
    ])
    for item in graph.get("evidence", []):
        lines.append(
            f"| {_markdown_table_cell(item.get('file'))} | {item.get('line_start') or ''} | {_markdown_table_cell(item.get('module'))} | {_markdown_table_cell(item.get('symbol'))} | {_markdown_table_cell(item.get('file_hash'))} |"
        )
    lines.extend(["", "## 新鲜度", "", "| 记忆 | 状态 | 最近校验 | Commit | 变体 |", "| --- | --- | ---: | --- | --- |"])
    for memory in graph.get("memories", []):
        lines.append(
            f"| `{memory.get('id')}` | {memory.get('status') or ''} | {memory.get('last_validated_at') or ''} | {memory.get('commit_id') or ''} | {memory.get('variant_id') or ''} |"
        )
    lines.extend(["", "## 路线记忆", ""])
    for memory_id in graph.get("memory_ids", []):
        lines.append(f"- `{memory_id}`")
    if snapshot:
        snapshot_id = snapshot.get("snapshot_id") or snapshot.get("id")
        lines.extend(["", "## 快照", "", f"- `{snapshot_id}` `{snapshot.get('graph_hash')}`"])
    lines.extend(["", "## 说明", "", "本文件由 `memory/memory.sqlite` 程序化生成，仅用于人工阅读和 Obsidian 可视化；不要把它当作事实数据源手写维护。"])
    return "\n".join(lines) + "\n"


def _render_pattern_markdown(graph: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None) -> str:
    pattern = graph["pattern"]
    quality = _pattern_quality(graph)
    pattern_name = _human_pattern_name(pattern.get("name"))
    lines = [
        "---",
        "generated_by: UE5_KnowledgeBaseMaker query_memory_render",
        "schema_version: query-memory-obsidian/v1",
        f"pattern_id: {pattern.get('id')}",
        f"graph_hash: {graph.get('graph_hash')}",
        f"generated_at: {int(time.time())}",
        "data_source: memory/memory.sqlite",
        "markdown_is_authoritative: false",
        "---",
        "",
        f"# {pattern_name}",
        "",
        "## 流程图",
        "",
        "```mermaid",
        _mermaid_for_pattern(graph),
        "```",
        "",
        "## 模式质量",
        "",
        f"- 状态：`{quality['label']}`",
        f"- 分数：`{quality['score']}`",
        f"- 支撑业务主题：`{quality['subject_count']}`",
        f"- 阶段数：`{quality['stage_count']}`",
        f"- 证据数：`{quality['evidence_count']}`",
        f"- 路线记忆数：`{quality['memory_count']}`",
        f"- 结论：{quality['recommendation']}",
        "",
        "## 使用建议",
        "",
        "- 适合：遇到相似业务主题时，用它作为查询路线起点。",
        "- 不适合：把它当业务事实结论；事实仍必须回到源码证据、hash、validate/replay。",
        "",
        "## 阶段",
        "",
        "| 阶段 | 原始命令 | 序号 | 状态 |",
        "| --- | --- | ---: | --- |",
    ]
    for stage in graph.get("stages", []):
        lines.append(
            f"| {_markdown_table_cell(_human_stage_name(stage.get('stage_name')))} | `{_markdown_table_cell(stage.get('stage_name'))}` | {stage.get('stage_index')} | {_markdown_table_cell(stage.get('status'))} |"
        )
    lines.extend(["", "## 业务主题", ""])
    for subject in graph.get("subjects", []):
        lines.append(f"- `{subject.get('id')}` {subject.get('display_name')}")
    lines.extend(["", "## 证据", "", "| 文件 | 行号 | 模块 | 符号 | 文件哈希 |", "| --- | ---: | --- | --- | --- |"])
    for item in graph.get("evidence", []):
        lines.append(
            f"| {_markdown_table_cell(item.get('file'))} | {item.get('line_start') or ''} | {_markdown_table_cell(item.get('module'))} | {_markdown_table_cell(item.get('symbol'))} | {_markdown_table_cell(item.get('file_hash'))} |"
        )
    lines.extend(["", "## 来源", "", "| 记忆 | Commit | 分支 | 变体 |", "| --- | --- | --- | --- |"])
    for item in _graph_provenance(graph):
        lines.append(
            f"| `{_markdown_table_cell(item.get('memory_id'))}` | {_markdown_table_cell(item.get('commit_id'))} | {_markdown_table_cell(item.get('branch_name'))} | {_markdown_table_cell(item.get('variant_id'))} |"
        )
    if snapshot:
        snapshot_id = snapshot.get("snapshot_id") or snapshot.get("id")
        lines.extend(["", "## 快照", "", f"- `{snapshot_id}` `{snapshot.get('graph_hash')}`"])
    lines.extend(["", "## 说明", "", "本文件由 `memory/memory.sqlite` 程序化生成，仅用于人工阅读和 Obsidian 可视化；不要把它当作事实数据源手写维护。"])
    return "\n".join(lines) + "\n"


def _safe_markdown_filename(value: Any) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or "memory"))


def _prepare_graph_for_view(conn: sqlite3.Connection, graph: Dict[str, Any], view: str) -> Dict[str, Any]:
    if view == "query-path":
        graph = _attach_query_steps(conn, graph)
    if view == "evolution":
        graph = _attach_evolution_events(conn, graph)
    return graph


def render_memory(*, skill_dir: Path, target: str = "all", view: str = "full") -> Dict[str, Any]:
    conn = _connect(skill_dir)
    try:
        valid_views = {"full", "business", "evidence", "evolution", "query-path"}
        if view not in valid_views:
            return {
                "schema": "query-memory-render/v1",
                "target": target,
                "view": view,
                "error": f"unknown view: {view}",
                "valid_views": sorted(valid_views),
            }
        out_dir = Path(skill_dir) / "memory" / "obsidian"
        business_dir = out_dir / "business"
        patterns_dir = out_dir / "patterns"
        graphs_dir = out_dir / "graphs" / view
        business_dir.mkdir(parents=True, exist_ok=True)
        patterns_dir.mkdir(parents=True, exist_ok=True)
        if view != "full":
            graphs_dir.mkdir(parents=True, exist_ok=True)
        if target == "all":
            subjects = [row["id"] for row in conn.execute("SELECT id FROM business_subjects ORDER BY display_name").fetchall()]
            patterns = [row["id"] for row in conn.execute("SELECT id FROM business_patterns ORDER BY name").fetchall()]
        else:
            row = conn.execute(
                "SELECT id FROM business_subjects WHERE id=? OR display_name=? OR primary_symbol=?",
                (target, target, target),
            ).fetchone()
            subjects = [row["id"]] if row else []
            pattern_row = conn.execute(
                "SELECT id FROM business_patterns WHERE id=? OR name=?",
                (target, target),
            ).fetchone()
            patterns = [pattern_row["id"]] if pattern_row else []
        rendered = []
        for subject_id in subjects:
            graph = _subject_graph(conn, subject_id)
            if not graph:
                continue
            snapshot_row = conn.execute(
                """
                SELECT id, graph_hash, created_at FROM memory_snapshots
                WHERE subject_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (subject_id,),
            ).fetchone()
            snapshot = dict(snapshot_row) if snapshot_row else None
            filename = _safe_markdown_filename(graph["subject"]["display_name"])
            if view == "full":
                path = business_dir / f"{filename}.md"
                path.write_text(_render_subject_markdown(graph, snapshot=snapshot), encoding="utf-8")
            else:
                graph = _prepare_graph_for_view(conn, graph, view)
                path = graphs_dir / f"{filename}.md"
                path.write_text(_render_graph_view_markdown(graph, view), encoding="utf-8")
            rendered.append(str(path))
        for pattern_id in patterns:
            graph = _pattern_graph(conn, pattern_id)
            if not graph:
                continue
            snapshot_row = conn.execute(
                """
                SELECT id, graph_hash, created_at FROM memory_snapshots
                WHERE pattern_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (pattern_id,),
            ).fetchone()
            snapshot = dict(snapshot_row) if snapshot_row else None
            filename = _safe_markdown_filename(_human_pattern_name(graph["pattern"]["name"]))
            if view == "full":
                legacy_filename = _safe_markdown_filename(graph["pattern"]["name"])
                path = patterns_dir / f"{filename}.md"
                legacy_path = patterns_dir / f"{legacy_filename}.md"
                if legacy_path != path and legacy_path.exists():
                    legacy_path.unlink()
                path.write_text(_render_pattern_markdown(graph, snapshot=snapshot), encoding="utf-8")
            else:
                graph = _prepare_graph_for_view(conn, graph, view)
                path = graphs_dir / f"{filename}.md"
                path.write_text(_render_graph_view_markdown(graph, view), encoding="utf-8")
            rendered.append(str(path))
        index_lines = [
            "# 记忆",
            "",
            "由 `memory/memory.sqlite` 程序化生成；Markdown 只是展示视图，不是事实数据源。",
            "",
        ]
        for path in rendered:
            if view == "full":
                kind = "patterns" if str(Path(path).parent).endswith("patterns") else "business"
            else:
                kind = f"graphs/{view}"
            index_lines.append(f"- [[{kind}/{Path(path).stem}]]")
        (out_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        return {
            "schema": "query-memory-render/v1",
            "target": target,
            "view": view,
            "rendered_count": len(rendered),
            "rendered_files": rendered,
            "index": str(out_dir / "index.md"),
            "markdown_is_authoritative": False,
        }
    finally:
        conn.close()
