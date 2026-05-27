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


def test_query_audit_can_record_multiple_steps_for_one_trace_and_run(tmp_path):
    skill_dir = tmp_path / "Skill"
    audit = QueryAudit.for_skill(skill_dir)
    try:
        run_id = audit.start_run(
            trace_id="trace-multi",
            command="compound_query",
            args=["AActor"],
            context={"data_trust": "fresh"},
        )
        audit.record_step(
            run_id=run_id,
            trace_id="trace-multi",
            command="search_classes",
            args=["Actor"],
            context={"data_trust": "fresh"},
            result={"results": [{"name": "AActor"}]},
        )
        audit.record_step(
            run_id=run_id,
            trace_id="trace-multi",
            command="source_slice",
            args=["Source/Actor.cpp", "100"],
            context={"data_trust": "fresh"},
            result={"file_content": "SOURCE_BODY_SHOULD_NOT_BE_STORED", "found_count": 1},
        )
        audit.finish_run(
            run_id=run_id,
            context={"data_trust": "fresh"},
            result={"steps": [1, 2]},
        )
    finally:
        audit.close()

    conn = sqlite3.connect(str(skill_dir / "runtime" / "query_audit.db"))
    steps = conn.execute(
        "SELECT run_id, trace_id, command, result_count FROM query_steps ORDER BY id"
    ).fetchall()
    run = conn.execute("SELECT status, result_count FROM query_runs WHERE id=?", (run_id,)).fetchone()
    all_text = "\n".join(
        " ".join(str(value) for value in row if value is not None)
        for row in conn.execute("SELECT * FROM query_steps")
    )
    conn.close()

    assert len(steps) == 2
    assert {step[0] for step in steps} == {run_id}
    assert all(step[1] == "trace-multi" for step in steps)
    assert [step[2] for step in steps] == ["search_classes", "source_slice"]
    assert run == ("ok", 2)
    assert "SOURCE_BODY_SHOULD_NOT_BE_STORED" not in all_text
