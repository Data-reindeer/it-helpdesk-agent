import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from helpdesk_agent.domain import Decision, Query
from helpdesk_agent.engine import InvalidDecision, active
from helpdesk_agent.provider import ReplayProvider
from helpdesk_agent.security import redact


def decision(kind, **kw):
    args = dict(
        kind=kind,
        question="",
        diagnosis="",
        evidence_ids=[],
        queries=[],
        runbook_id="",
        action="none",
        resource="",
        justification="",
        condition_evidence=[],
    )
    return Decision(**(args | kw))


def investigate(engine, s, *qs):
    async def run():
        for q in qs:
            r = await engine.tools.execute(
                s, Query(tool=q[0], query=q[1], service=q[2])
            )
            for x in r["data"] or []:
                active(s)["evidence"][x["id"]] = {
                    **x,
                    "_source": q[0],
                    "_observed_at": r["at"],
                }

    asyncio.run(run())


def test_isolation(app, client, session):
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"X-Helpdesk": "1"}) as other:
        other.get("/api/bootstrap")
        assert other.get("/api/sessions/" + session["id"]).status_code == 404
        assert other.get("/api/sessions").json() == []


def test_csrf(client):
    assert (
        client.post(
            "/api/sessions",
            json={"employee_id": "EMP-001"},
            headers={"Origin": "https://evil.invalid"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sessions",
            json={"employee_id": "EMP-001"},
            headers={"X-Helpdesk": "0"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"employee_id": "EMP-999"},
        {"employee_id": "EMP-001", "admin": True},
        {"employee_id": 42},
    ],
)
def test_invalid_identity(client, payload):
    assert client.post("/api/sessions", json=payload).status_code in (404, 422)


@pytest.mark.parametrize(
    "action,resource",
    [
        ("grant", "snowflake:production:reader"),
        ("mfa_reset", "self"),
        ("rollback", "jenkins"),
        ("password_reset", "EMP-002"),
        ("access_request", "root"),
        ("shell", "self"),
    ],
)
def test_denied_actions(app, session, action, resource):
    engine = app.state.engine
    assert not engine.tools.policy(session, action, resource)["allowed"]
    with pytest.raises(InvalidDecision):
        engine.propose(session, action, resource, "urgent")


def test_no_recovery_denied(app, client):
    s = client.post("/api/sessions", json={"employee_id": "EMP-006"}).json()
    assert not app.state.engine.tools.policy(s, "password_reset", "self")["allowed"]


@pytest.mark.parametrize(
    "action,resource,end",
    [
        ("password_reset", "self", "waiting_verification"),
        ("access_request", "snowflake:production:reader", "waiting_approval"),
        ("access_request", "grafana:viewer", "waiting_approval"),
    ],
)
def test_exact_confirmation_idempotency(app, session, action, resource, end):
    e = app.state.engine
    investigate(e, session, ("get_current_user_context", "", ""))
    e.propose(session, action, resource, "Reporting project")
    aid = active(session)["pending"]["id"]
    assert active(session)["status"] == "waiting_confirmation"
    with pytest.raises(InvalidDecision):
        e.confirm(session, "other", True)
    e.confirm(session, aid, True)
    assert active(session)["status"] == end
    before = len(active(session)["attempts"])
    e.confirm(session, aid, True)
    assert len(active(session)["attempts"]) == before
    assert e.tools.user(session)["permissions"] == ["grafana:viewer"]  # no actual grant


@pytest.mark.parametrize("mutation", ["expiry", "policy", "recovery", "cancel"])
def test_confirmation_rechecked(app, session, mutation):
    e = app.state.engine
    investigate(e, session, ("get_current_user_context", "", ""))
    e.propose(session, "password_reset", "self", "Login")
    a = active(session)["pending"]
    if mutation == "expiry":
        a["expires"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    if mutation == "policy":
        e.tools.data["policies"]["version"] = "changed"
    if mutation == "recovery":
        e.tools.user(session)["recovery_registered"] = False
    e.confirm(session, a["id"], mutation != "cancel")
    assert active(session)["status"] == "waiting_user"
    assert active(session)["attempts"][-1]["result"] in ("denied", "cancelled")


def test_cannot_resolve_without_verification(client, session):
    assert (
        client.post(
            "/api/sessions/" + session["id"] + "/feedback", json={"resolved": True}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "resolved,expected", [(True, "resolved"), (False, "waiting_user")]
)
def test_verification(app, client, session, resolved, expected):
    e = app.state.engine
    active(session)["status"] = "waiting_verification"
    e.store.save(session)
    r = client.post(
        "/api/sessions/" + session["id"] + "/feedback", json={"resolved": resolved}
    )
    assert r.status_code == 200 and active(r.json())["status"] == expected


@pytest.mark.parametrize("runbook", ["invented", "KB-021", "KB-002"])
def test_unretrieved_runbook_blocked(app, session, runbook):
    with pytest.raises(InvalidDecision):
        app.state.engine.apply(session, decision("guide", runbook_id=runbook))


def test_unknown_citation(app, session):
    with pytest.raises(InvalidDecision):
        app.state.engine.apply(
            session, decision("clarify", question="Which error?", evidence_ids=["fake"])
        )


def test_cannot_invent_outage(app, session):
    with pytest.raises(InvalidDecision):
        app.state.engine.apply(session, decision("incident"))


def test_status_regional_and_global(app, client):
    s = client.post("/api/sessions", json={"employee_id": "EMP-002"}).json()
    investigate(app.state.engine, s, ("get_service_status", "", "salesforce"))
    assert {"STATUS-salesforce", "INC-SF-104"} <= set(active(s)["evidence"])
    app.state.engine.apply(s, decision("incident", evidence_ids=["INC-SF-104"]))
    assert active(s)["status"] == "waiting_service"


def test_full_multiturn_vpn(app, session):
    e = app.state.engine
    e.provider = ReplayProvider(
        [
            decision(
                "query",
                queries=[
                    Query(tool="get_current_user_context", query="", service=""),
                    Query(tool="get_service_status", query="", service="vpn"),
                    Query(tool="search_kb", query="5.0 idle disconnect", service="vpn"),
                ],
            ),
            decision(
                "guide",
                runbook_id="KB-002",
                evidence_ids=["KB-002", "USER-EMP-001", "STATUS-vpn"],
                condition_evidence=["USER-EMP-001", "STATUS-vpn"],
            ),
        ]
    )
    asyncio.run(e.run(session, "VPN disconnects every 15 minutes", "request-0001"))
    assert active(session)["status"] == "waiting_verification"
    assert any(
        m["role"] == "assistant" and "KB-002" in m["text"] for m in session["messages"]
    )
    assert len([x for x in session["events"] if x["type"] == "tool"]) == 3


def test_vpn_wrong_version(app, client):
    s = client.post("/api/sessions", json={"employee_id": "EMP-002"}).json()
    e = app.state.engine
    investigate(
        e,
        s,
        ("get_current_user_context", "", ""),
        ("get_service_status", "", "vpn"),
        ("search_kb", "5.0 idle", "vpn"),
    )
    with pytest.raises(InvalidDecision):
        e.apply(
            s,
            decision(
                "guide",
                runbook_id="KB-002",
                condition_evidence=["USER-EMP-002", "STATUS-vpn"],
            ),
        )


def test_handoff_complete_persistent(app, session):
    e = app.state.engine
    investigate(
        e,
        session,
        ("get_service_status", "", "jenkins"),
        ("get_recent_changes", "", "jenkins"),
    )
    session["messages"].append(
        dict(
            role="user",
            text="Pipeline failing since Friday",
            issue=session["active_issue"],
        )
    )
    e.handoff(session, "Requires platform investigation")
    h = active(session)["handoff"]
    assert h["timeline"] and h["evidence"] and h["unknowns"] and h["policy_version"]
    e.handoff(session, "Repeated request")
    assert active(session)["handoff"]["id"] == h["id"]
    with e.store.db() as c:
        assert c.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 1


@pytest.mark.parametrize(
    "text",
    [
        "password=super-secret",
        "密码：super-secret",
        "token: super-secret",
        "sk-abcdefghijklmnop",
        "Bearer secret-token",
    ],
)
def test_redaction(text):
    assert (
        "super-secret" not in redact(text)
        and "abcdefghijklmnop" not in redact(text)
        and "secret-token" not in redact(text)
    )


def test_tool_outage(app, session):
    e = app.state.engine
    e.tools.faults["get_service_status"] = True
    r = asyncio.run(
        e.tools.execute(
            session, Query(tool="get_service_status", query="", service="vpn")
        )
    )
    assert r["status"] == "error" and r["data"] is None


def test_missing_article(app):
    assert app.state.engine.store.search("zzzznotaword", "") == []


def test_chinese_search(app):
    assert app.state.engine.store.search("VPN 断开", "vpn")


def test_obsolete_excluded(app):
    assert "KB-021" not in app.state.engine.store.search(
        "disable firewall legacy", "vpn"
    )


def test_model_failure_saves_context(app, session):
    e = app.state.engine
    asyncio.run(e.run(session, "password=super-secret I cannot log in", "failure-0001"))
    assert active(session)["status"] == "waiting_user" and not session["running"]
    assert "super-secret" not in json.dumps(session)


def test_request_dedup(app, session):
    e = app.state.engine
    asyncio.run(e.run(session, "VPN failing", "duplicate-0001"))
    n = len(session["messages"])
    asyncio.run(e.run(session, "VPN failing", "duplicate-0001"))
    assert len(session["messages"]) == n
    with pytest.raises(InvalidDecision):
        asyncio.run(e.run(session, "Different text", "duplicate-0001"))


def test_restart_marks_interrupted(app, session):
    e = app.state.engine
    session["running"] = True
    e.store.save(session)
    e.store.initialize(e.tools.data)
    with e.store.db() as c:
        s = json.loads(
            c.execute(
                "SELECT body FROM sessions WHERE id=?", (session["id"],)
            ).fetchone()[0]
        )
    assert not s["running"] and s["events"][-1]["type"] == "interrupted"


def test_optimistic_conflict(app, session):
    import copy

    stale = copy.deepcopy(session)
    app.state.engine.store.save(session)
    with pytest.raises(RuntimeError):
        app.state.engine.store.save(stale)


def test_multi_issue_separation(client, session):
    sid = session["id"]
    r = client.post(
        "/api/sessions/" + sid + "/issues", json={"title": "Grafana access"}
    ).json()
    assert len(r["issues"]) == 2 and r["active_issue"] != session["active_issue"]
    r = client.post(
        "/api/sessions/" + sid + "/issues/" + session["active_issue"] + "/select",
        json={},
    ).json()
    assert r["active_issue"] == session["active_issue"]


def test_schema_rejects_unknown_tool():
    with pytest.raises(ValidationError):
        Query(tool="execute_shell", query="rm", service="vpn")


def test_schema_no_resolved_decision():
    with pytest.raises(ValidationError):
        decision("resolved")


def test_infinite_query_bounded(app, session):
    e = app.state.engine
    d = decision(
        "query", queries=[Query(tool="get_current_user_context", query="", service="")]
    )
    e.provider = ReplayProvider([d, d, d])
    asyncio.run(e.run(session, "help", "bounded-0001"))
    assert len([x for x in session["events"] if x["type"] == "tool"]) == 1
    assert not session["running"] and active(session)["status"] == "waiting_user"


def test_static_safety(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers["content-security-policy"]
    js = client.get("/static/app.js").text
    assert "innerHTML" not in js and "textContent" in js


def test_already_reset_cannot_reexecute(app, session):
    e = app.state.engine
    investigate(e, session, ("get_current_user_context", "", ""))
    session["messages"].append(
        dict(
            role="user",
            issue=session["active_issue"],
            text="I already reset my password",
        )
    )
    with pytest.raises(InvalidDecision):
        e.propose(session, "password_reset", "self", "Login")


def test_action_result_session_scoped(app, client, session):
    e = app.state.engine
    investigate(e, session, ("get_current_user_context", "", ""))
    e.propose(session, "password_reset", "self", "Login")
    aid = active(session)["pending"]["id"]
    other = client.post("/api/sessions", json={"employee_id": "EMP-002"}).json()
    q = Query(tool="get_action_result", query=aid, service="")
    assert asyncio.run(e.tools.execute(other, q))["data"] == []
    assert asyncio.run(e.tools.execute(session, q))["data"][0]["id"] == aid


def test_unknown_cost_and_configured_estimate(monkeypatch):
    from helpdesk_agent.observability import metrics

    s = {
        "events": [
            dict(
                type="model",
                detail={"usage": {"input_tokens": 1000, "output_tokens": 500}},
            )
        ]
    }
    monkeypatch.delenv("INPUT_PRICE_PER_MILLION", raising=False)
    assert metrics(s)["estimated_usd"] is None
    monkeypatch.setenv("INPUT_PRICE_PER_MILLION", "2")
    monkeypatch.setenv("OUTPUT_PRICE_PER_MILLION", "4")
    assert metrics(s)["estimated_usd"] == 0.004


def test_shutdown_preserves_safe_state(app, session):
    class Slow:
        mode = "test"

        async def decide(self, context):
            await asyncio.sleep(10)

    e = app.state.engine
    e.provider = Slow()

    async def run():
        task = asyncio.create_task(e.run(session, "VPN issue", "cancelled-0001"))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert active(session)["status"] == "waiting_user" and not session["running"]
    assert any(x["type"] == "interrupted" for x in session["events"])
