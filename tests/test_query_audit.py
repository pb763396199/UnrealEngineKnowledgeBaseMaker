import sqlite3

from ue5_kb.query.query_audit import QueryAudit, record_query


def test_query_audit_writes_runs_and_steps_without_result_body(tmp_path):
    skill_dir = tmp_path / "Skill"
    context = {
        "data_trust": "fresh",
        "branch": "DEV",
        "source": "F:/Project/Plugin",
        "commit": "abc1234",
        "dirty": False,
        "fingerprint": "fingerprint12",
    }
    result = {
        "found_count": 1,
        "results": [{"name": "BeginPlay"}],
        "file_content": "SECRET_SOURCE_BODY_SHOULD_NOT_BE_STORED",
    }

    trace_id = record_query(
        skill_dir=skill_dir,
        trace_id="trace-demo",
        command="query_function_info",
        args=["BeginPlay"],
        context=context,
        result=result,
    )

    assert trace_id == "trace-demo"
    db_path = skill_dir / "runtime" / "query_audit.db"
    conn = sqlite3.connect(str(db_path))
    run_count = conn.execute("SELECT COUNT(*) FROM query_runs").fetchone()[0]
    step_count = conn.execute("SELECT COUNT(*) FROM query_steps").fetchone()[0]
    step = conn.execute(
        "SELECT trace_id, command, args_summary, result_count, error, data_trust FROM query_steps"
    ).fetchone()
    run_text = "\n".join(
        " ".join(str(value) for value in row if value is not None)
        for row in conn.execute("SELECT * FROM query_runs")
    )
    step_text = "\n".join(
        " ".join(str(value) for value in row if value is not None)
        for row in conn.execute("SELECT * FROM query_steps")
    )
    all_text = run_text + "\n" + step_text
    conn.close()

    assert run_count == 1
    assert step_count == 1
    assert step[0] == "trace-demo"
    assert step[1] == "query_function_info"
    assert "BeginPlay" in step[2]
    assert step[3] == 1
    assert step[4] is None
    assert step[5] == "fresh"
    assert "SECRET_SOURCE_BODY_SHOULD_NOT_BE_STORED" not in all_text


def test_query_audit_records_failures_and_recent_steps(tmp_path):
    skill_dir = tmp_path / "Skill"
    record_query(
        skill_dir=skill_dir,
        trace_id="trace-error",
        command="source_slice",
        args=["../bad.cpp", "1"],
        context={"data_trust": "stale", "dirty": True},
        error="parent traversal is not allowed",
    )

    audit = QueryAudit.for_skill(skill_dir)
    try:
        recent = audit.recent("trace-error", 10)
    finally:
        audit.close()

    assert recent["found_count"] == 1
    assert recent["steps"][0]["status"] == "error"
    assert recent["steps"][0]["error"] == "parent traversal is not allowed"
