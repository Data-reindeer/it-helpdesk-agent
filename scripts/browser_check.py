"""Real browser verification against an isolated server; replay is explicit test data."""

import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import uvicorn
from playwright.sync_api import sync_playwright

from helpdesk_agent.api import create_app
from helpdesk_agent.domain import Decision, Query
from helpdesk_agent.provider import ReplayProvider, OpenAIProvider

ROOT = Path(__file__).resolve().parents[1]
LIVE = "--live" in sys.argv


def d(kind, **kw):
    return Decision(
        **(
            dict(
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
            | kw
        )
    )


with tempfile.TemporaryDirectory() as tmp:
    decisions = [
        d(
            "query",
            queries=[
                Query(tool="get_current_user_context", query="", service=""),
                Query(tool="get_service_status", query="", service="vpn"),
                Query(tool="search_kb", query="5.0 idle disconnect", service="vpn"),
            ],
        ),
        d(
            "guide",
            runbook_id="KB-002",
            diagnosis="Your managed VPN client is version 5.0 and current service status is healthy. The documented idle-disconnect issue is a possible match for this pattern.",
            evidence_ids=["KB-002"],
            condition_evidence=["USER-EMP-001", "STATUS-vpn"],
        ),
        d(
            "query",
            queries=[Query(tool="get_current_user_context", query="", service="")],
        ),
        d(
            "action",
            action="access_request",
            resource="snowflake:production:reader",
            justification="Reporting project",
        ),
    ]
    provider = OpenAIProvider() if LIVE else ReplayProvider(decisions)
    if LIVE and not provider.configured:
        raise RuntimeError("Configure the project model before --live browser testing")
    app = create_app(Path(tmp) / "browser.sqlite", provider)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    checks = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 980})
            page.set_default_timeout(80000)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_role("button", name="＋ 新会话").click()
            page.locator("#message").fill(
                "VPN drops every 15 minutes; normal internet is stable."
            )
            page.get_by_role("button", name="发送 ↑").click()
            page.get_by_text("等待验证", exact=True).wait_for()
            assert page.locator("#chat").inner_text().count("KB-002") >= 1
            checks.append("multi-source guide and verification UI")
            assessment_box = page.locator("#chat .assessment").last.bounding_box()
            chat_box = page.locator("#chat").bounding_box()
            assert assessment_box and chat_box and assessment_box["y"] >= chat_box["y"]
            checks.append(
                "new replies show their assessment first rather than scrolling past it"
            )
            if LIVE:
                projected = page.evaluate(
                    """async () => {const id=localStorage.getItem('helpdesk_session');return (await fetch('/api/sessions/'+id)).json();}"""
                )
                reply = next(
                    m
                    for m in reversed(projected["messages"])
                    if m["role"] == "assistant"
                )
                assessment = reply.get("presentation", {}).get("assessment", "")
                assert assessment and assessment in page.locator("#chat").inner_text()
                assert page.locator("#chat .entry-help").count() == 1
                checks.append(
                    "accepted assessment visible in chat with approved steps and entry guidance"
                )
            page.screenshot(
                path=str(
                    ROOT
                    / ("docs/ui-live-desktop.png" if LIVE else "docs/ui-desktop.png")
                ),
                full_page=True,
            )
            page.reload()
            page.get_by_text("等待验证", exact=True).wait_for()
            checks.append("refresh restores session and pending verification")
            page.get_by_role("button", name="已恢复", exact=True).click()
            page.get_by_text("员工确认已恢复", exact=True).wait_for()
            checks.append("employee verification resolves case")
            page.once(
                "dialog", lambda dialog: dialog.accept("Production reader request")
            )
            page.get_by_role("button", name="＋ 新问题").click()
            page.locator("#message").fill(
                "Need Snowflake production reader for reporting."
            )
            page.get_by_role("button", name="发送 ↑").click()
            page.get_by_role("button", name="确认执行", exact=True).wait_for()
            page.get_by_role("button", name="确认执行", exact=True).click()
            page.get_by_text("等待审批", exact=True).wait_for()
            checks.append("exact action confirmation reaches approval, not resolved")
            page.get_by_role("button", name="人工协助", exact=True).click()
            page.get_by_text("已创建模拟交接", exact=True).wait_for()
            checks.append("persisted human handoff")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(
                    ROOT / ("docs/ui-live-mobile.png" if LIVE else "docs/ui-mobile.png")
                ),
                full_page=True,
            )
            checks.append("390px layout without horizontal overflow")
            assert not errors, errors
            checks.append("no JavaScript runtime errors")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    report = dict(
        mode="live project model"
        if LIVE
        else "isolated replay; not live model evidence",
        checks=checks,
        passed=len(checks),
        errors=errors,
    )
    (
        ROOT
        / ("docs/browser-live-results.json" if LIVE else "docs/browser-results.json")
    ).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
