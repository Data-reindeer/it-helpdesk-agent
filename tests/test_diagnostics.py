"""Diagnostic prerequisites, feedback, linked incidents and execution controls."""

import asyncio
import pytest
from helpdesk_agent.evaluation import checks_for
from helpdesk_agent.domain import Query
from helpdesk_agent.engine import active
from helpdesk_agent.provider import ReplayProvider
from helpdesk_agent.diagnostics import query_key
from test_system import decision, investigate


def vpn_steps():
    return decision(
        "guide",
        runbook_id="KB-002",
        evidence_ids=["KB-002"],
        condition_evidence=["USER-EMP-001", "STATUS-vpn"],
    )


def test_known_directory_question_is_replanned(app, session):
    e = app.state.engine
    e.provider = ReplayProvider(
        [
            decision(
                "clarify",
                question="Which operating system and VPN client are you using? When the VPN drops, what exact error or notification appears, if any?",
            ),
            decision(
                "query",
                queries=[
                    Query(
                        tool="search_kb", query="vpn 5.0 idle disconnect", service="vpn"
                    )
                ],
            ),
            vpn_steps(),
        ]
    )
    asyncio.run(
        e.run(
            session,
            "My VPN drops every 15 minutes. Normal internet is stable.",
            "diagnostic-case-0001",
        )
    )
    assert active(session)["status"] == "waiting_verification"
    assert any(ev["type"] == "decision_rejected" for ev in session["events"])
    assert not any(
        "Which operating system" in m["text"]
        for m in session["messages"]
        if m["role"] == "assistant"
    )
    assert not any(ev["type"] == "run_error" for ev in session["events"])
    assert len([ev for ev in session["events"] if ev["type"] == "tool"]) == 3


def test_preflight_provides_directory_before_model(app, session):
    e = app.state.engine

    class Inspect:
        async def decide(self, c):
            assert c["known_employee_context"]["equipment"]["os"] == "macOS"
            assert c["known_employee_context"]["equipment"]["vpn_version"] == "5.0"
            assert any(x.get("service") == "vpn" for x in c["evidence"])
            return decision("clarify", question="What non-secret error appears?"), {}

    e.provider = Inspect()
    asyncio.run(e.run(session, "VPN stopped working.", "directory-preflight-1"))
    assert active(session)["status"] == "waiting_user"


def test_diagnostic_runbook_does_not_request_recovery_confirmation(app, session):
    e = app.state.engine
    investigate(e, session, ("search_kb", "vpn disconnect", "vpn"))
    e.apply(session, decision("guide", runbook_id="KB-001"))
    assert active(session)["status"] == "waiting_user"


def test_human_runbook_creates_actual_handoff(app, session):
    e = app.state.engine
    investigate(e, session, ("search_kb", "okta reset failed", "okta"))
    e.apply(session, decision("guide", runbook_id="KB-008"))
    assert active(session)["status"] == "escalated" and active(session)["handoff"]


def test_failed_runbook_cannot_repeat_after_text_feedback(app, session):
    e = app.state.engine
    e.provider = ReplayProvider(
        [
            decision(
                "query",
                queries=[Query(tool="search_kb", query="vpn 5.0 idle", service="vpn")],
            ),
            vpn_steps(),
        ]
    )
    asyncio.run(
        e.run(
            session,
            "My VPN drops every 15 minutes. Normal internet is stable.",
            "feedback-turn-1",
        )
    )
    e.provider = ReplayProvider(
        [
            vpn_steps(),
            decision(
                "escalate",
                diagnosis="Safe steps failed; service team investigation required",
            ),
        ]
    )
    asyncio.run(
        e.run(
            session, "I tried those steps but it still disconnects.", "feedback-turn-2"
        )
    )
    i = active(session)
    assert i["status"] == "escalated"
    assert (
        sum(
            a.get("article") == "KB-002" and a.get("source") != "employee_feedback"
            for a in i["attempts"]
        )
        == 1
    )
    assert any(
        a.get("article") == "KB-002" and a["result"] == "employee_reported_failure"
        for a in i["attempts"]
    )


def test_feedback_button_associates_failed_article(app, client, session):
    e = app.state.engine
    active(session)["status"] = "waiting_verification"
    active(session)["attempts"].append(
        dict(article="KB-002", result="proposed_not_confirmed")
    )
    e.store.save(session)
    response = client.post(
        "/api/sessions/" + session["id"] + "/feedback", json={"resolved": False}
    )
    i = active(response.json())
    assert i["attempts"][0]["result"] == "employee_reported_failure"
    assert i["attempts"][1]["article"] == "KB-002"


def test_linked_maintenance_preflight(app, session):
    e = app.state.engine
    e.provider = ReplayProvider(
        [
            decision(
                "escalate",
                diagnosis="Review egress maintenance correlation, not a confirmed root cause",
            )
        ]
    )
    asyncio.run(
        e.run(
            session,
            "Since Friday maintenance Jenkins times out and Tableau is stale",
            "linked-maintenance-1",
        )
    )
    assert "CHG-231" in active(session)["evidence"]
    assert active(session)["status"] == "escalated"


def test_failed_directory_read_is_not_repeated_by_agent(app, session):
    e = app.state.engine
    e.tools.faults["get_current_user_context"] = True
    e.provider = ReplayProvider(
        [
            decision(
                "query",
                queries=[Query(tool="get_current_user_context", query="", service="")],
            ),
            decision(
                "escalate",
                diagnosis="Cannot verify account context; manual identity verification needed",
            ),
        ]
    )
    asyncio.run(e.run(session, "Reset my Okta password", "directory-unavailable-1"))
    assert active(session)["status"] == "escalated"
    assert (
        sum(
            ev["type"] == "tool" and ev["detail"]["tool"] == "get_current_user_context"
            for ev in session["events"]
        )
        == 1
    )
    assert not any(ev["type"] == "run_error" for ev in session["events"])


def test_tool_dedup_uses_effective_arguments():
    assert query_key(
        Query(tool="get_current_user_context", query="me", service="Okta")
    ) == query_key(Query(tool="get_current_user_context", query="", service=""))
    assert query_key(
        Query(tool="get_service_status", query="", service="VPN")
    ) == query_key(Query(tool="get_service_status", query="", service="vpn"))


def test_import_does_not_open_or_recover_user_database(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(project / "src")}
    result = subprocess.run(
        [sys.executable, "-c", "import helpdesk_agent.api"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0
    assert not (tmp_path / "var").exists()


@pytest.mark.parametrize(
    "question,should_pass",
    [
        (
            "Which Jenkins job is affected, when did it first fail, and what non-sensitive error does it show?",
            True,
        ),
        (
            "Which issue should we investigate first: Jenkins or Tableau? Please use New Issue for the other.",
            False,
        ),
    ],
)
def test_linked_incident_rubric_distinguishes_timing_from_splitting(
    session, question, should_pass
):
    case = {"id": "EVAL-034", "expected_states": ["waiting_user"]}
    active(session)["status"] = "waiting_user"
    session["messages"].append(
        dict(role="assistant", text=question, issue=session["active_issue"])
    )
    assert checks_for(case, session)["linked_incident_not_split"] == should_pass
