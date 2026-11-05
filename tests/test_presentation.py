"""Display projection must not mutate state, prompts, attempts, or canonical history."""

import copy
from helpdesk_agent.presentation import project_session
from helpdesk_agent.engine import active


def captured(
    session,
    kind="guide",
    diagnosis="Your managed client is version 5.0. A documented idle-disconnect issue is a possible match.",
):
    i = active(session)
    i["evidence"] = {
        "KB-002": dict(
            id="KB-002",
            title="VPN idle disconnect",
            approved=True,
            version=2,
            conditions=["Managed VPN version is 5.0"],
            steps=[
                "Install the approved VPN 5.1 update from the managed Software Center."
            ],
            verification="Observe for at least 20 minutes.",
        )
    }
    session["messages"] = [
        dict(
            role="user",
            issue=i["id"],
            text="My VPN drops every 15 minutes.",
            at="2026-11-04T10:00:00+00:00",
        ),
        dict(
            role="assistant",
            issue=i["id"],
            text="[KB-002 v2] VPN idle disconnect\n1. Install the update.",
            at="2026-11-04T10:00:03+00:00",
        ),
    ]
    session["events"] = [
        dict(
            type="decision",
            issue=i["id"],
            at="2026-11-04T10:00:02+00:00",
            detail={
                "decision": dict(
                    kind=kind, diagnosis=diagnosis, evidence_ids=["KB-002"]
                )
            },
        )
    ]
    return session


def strip_display(view):
    clean = copy.deepcopy(view)
    for m in clean["messages"]:
        m.pop("presentation", None)
    return clean


def test_projection_preserves_engine_state_and_canonical_text(session):
    s = captured(session)
    before = copy.deepcopy(s)
    view = project_session(s)
    assert s == before and strip_display(view) == before
    assert (
        view["messages"][-1]["presentation"]["assessment"]
        == s["events"][0]["detail"]["decision"]["diagnosis"]
    )
    assert (
        view["messages"][-1]["presentation"]["steps"]
        == active(s)["evidence"]["KB-002"]["steps"]
    )
    view["issues"][0]["status"] = "arbitrary"
    assert s == before


def test_instructions_source_is_approved_and_has_no_invented_link(session):
    p = project_session(captured(session))["messages"][-1]["presentation"]
    assert p["source"]["id"] == "KB-002"
    assert "No link is available" in p["help"]
    assert "http" not in p["help"]


def test_rejected_or_error_diagnosis_not_exposed_as_assessment(session):
    s = captured(session)
    s["events"].append(
        dict(
            type="decision_rejected",
            issue=s["active_issue"],
            at="2026-11-04T10:00:02.500000+00:00",
            detail={},
        )
    )
    assert project_session(s)["messages"][-1]["presentation"]["assessment"] == ""
    s["messages"][-1]["text"] = "Reliable diagnosis is currently unavailable."
    assert project_session(s)["messages"][-1]["presentation"]["kind"] == "plain"


def test_historical_messages_do_not_use_latest_hypothesis(session):
    s = captured(session)
    i = active(s)
    i["hypotheses"] = [
        dict(assessment="A later, unrelated assessment", at="2026-11-04T11:00:00+00:00")
    ]
    p = project_session(s)["messages"][-1]["presentation"]
    assert "unrelated" not in p["assessment"]


def test_clarification_removes_internal_prefix_but_preserves_question(session):
    s = captured(session, kind="clarify", diagnosis="The exact error is still unknown.")
    s["messages"][-1]["text"] = "Clarification (model question): What error appears?"
    p = project_session(s)["messages"][-1]["presentation"]
    assert p["body"] == "What error appears?"
    assert p["assessment"] == "The exact error is still unknown."


def test_api_display_is_not_saved_or_exported(app, client, session):
    s = captured(session)
    app.state.engine.store.save(s)
    view = client.get("/api/sessions/" + s["id"]).json()
    raw = client.get("/api/sessions/" + s["id"] + "/export").json()
    assert "presentation" in view["messages"][-1]
    assert "presentation" not in raw["messages"][-1]
    assert strip_display(view) == raw


def test_guide_version_mismatch_keeps_original_instructions(session):
    s = captured(session)
    active(s)["evidence"]["KB-002"]["version"] = 3
    p = project_session(s)["messages"][-1]["presentation"]
    assert not p["steps"] and p["body"] == s["messages"][-1]["text"]


def test_english_feedback_does_not_change_resolution(session):
    s = captured(session)
    s["messages"][-1]["text"] = "Employee confirmation: recovered / 已恢复"
    view = project_session(s)
    assert "Thanks for confirming" in view["messages"][-1]["presentation"]["body"]
    assert active(view)["status"] == active(s)["status"]
