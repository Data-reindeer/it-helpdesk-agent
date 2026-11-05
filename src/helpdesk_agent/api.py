"""Local single-worker API. Demo browser capability isolates sessions, not enterprise SSO."""

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .diagnostics import record_feedback
from .domain import Confirm, Feedback, Message, NewIssue, NewSession
from .engine import Engine, InvalidDecision, active, say
from .presentation import project_session
from .provider import OfflineProvider, OpenAIProvider
from .storage import Store
from .tools import Tools

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).parent / "web"
load_dotenv(ROOT / ".env", override=True)


def create_app(db_path=None, provider=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        tasks = list(app.state.tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Helpdesk Agent — Synthetic Sandbox", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    store = Store(
        str(db_path or os.getenv("HELPDESK_DB", ROOT / "var/helpdesk.sqlite3"))
    )
    data = json.loads((ROOT / "data/fixtures.json").read_text())
    store.initialize(data)
    tools = Tools(store, data)
    p = provider or (
        OfflineProvider() if os.getenv("AGENT_MODE") == "offline" else OpenAIProvider()
    )
    engine = Engine(store, tools, p)
    app.state.engine = engine
    app.state.tasks = set()
    app.state.busy = set()

    @app.middleware("http")
    async def boundaries(req, call_next):
        if req.method not in ("GET", "HEAD", "OPTIONS"):
            if req.headers.get("x-helpdesk") != "1":
                return JSONResponse(
                    {"detail": "Missing same-origin request header"}, 403
                )
            origin = req.headers.get("origin")
            if origin and origin not in (
                f"http://{req.headers.get('host')}",
                f"https://{req.headers.get('host')}",
            ):
                return JSONResponse({"detail": "Cross-origin request denied"}, 403)
        r = await call_next(req)
        r.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Cache-Control"] = "no-store"
        return r

    def owner(req):
        token = req.cookies.get("helpdesk_client")
        if not token or len(token) != 64:
            raise HTTPException(401, "Initialize browser via /api/bootstrap")
        return token

    def load(sid, req):
        try:
            return store.load(sid, owner(req))
        except KeyError:
            raise HTTPException(404, "Session not found")

    def free(sid):
        if sid in app.state.busy:
            raise HTTPException(409, "Session has an active run")

    @app.exception_handler(InvalidDecision)
    async def invalid(req, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.get("/api/bootstrap")
    async def bootstrap(req: Request, response: Response):
        token = req.cookies.get("helpdesk_client")
        if not token or len(token) != 64:
            token = secrets.token_hex(32)
            response.set_cookie(
                "helpdesk_client",
                token,
                httponly=True,
                samesite="strict",
                max_age=86400 * 7,
            )
        return dict(
            mode=p.mode,
            model=getattr(p, "model", None),
            configured=p.configured,
            scenario_clock=data["scenario_clock"],
            users=[
                {k: u[k] for k in ("id", "name", "department", "location")}
                for u in data["users"]
            ],
        )

    @app.get("/api/sessions")
    async def sessions(req: Request):
        with store.db() as c:
            rows = c.execute(
                "SELECT id,body FROM sessions WHERE owner=?", (owner(req),)
            ).fetchall()
        return [
            dict(id=r["id"], employee=json.loads(r["body"])["employee"]) for r in rows
        ]

    @app.post("/api/sessions")
    async def new(body: NewSession, req: Request):
        if body.employee_id not in [u["id"] for u in data["users"]]:
            raise HTTPException(404, "Demo employee not found")
        return project_session(store.create(owner(req), body.employee_id))

    @app.get("/api/sessions/{sid}")
    async def get(sid: str, req: Request):
        return project_session(load(sid, req))

    @app.post("/api/sessions/{sid}/messages", status_code=202)
    async def message(sid: str, body: Message, req: Request):
        s = load(sid, req)
        free(sid)
        i = active(s)
        if i["pending"] or i["status"] in ("resolved", "escalated", "waiting_approval"):
            raise InvalidDecision("Finish pending action or create a new issue")
        old = store.request(sid, body.request_id)
        if old:
            from .security import redact

            if old["text"] != redact(body.text):
                raise InvalidDecision("Request ID reused with different content")
            return dict(accepted=True, deduplicated=True)
        app.state.busy.add(sid)

        async def work():
            try:
                await engine.run(s, body.text, body.request_id)
            finally:
                app.state.busy.discard(sid)

        task = asyncio.create_task(work())
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return dict(accepted=True)

    @app.post("/api/sessions/{sid}/confirm")
    async def confirm(sid: str, body: Confirm, req: Request):
        s = load(sid, req)
        free(sid)
        return project_session(engine.confirm(s, body.action_id, body.approve))

    @app.post("/api/sessions/{sid}/feedback")
    async def feedback(sid: str, body: Feedback, req: Request):
        s = load(sid, req)
        free(sid)
        i = active(s)
        if i["status"] != "waiting_verification":
            raise InvalidDecision("No pending verification")
        record_feedback(i, body.resolved)
        i["status"] = "resolved" if body.resolved else "waiting_user"
        say(
            s,
            "Employee confirmation: "
            + ("recovered / 已恢复" if body.resolved else "still failing / 仍失败"),
        )
        store.save(s)
        return project_session(s)

    @app.post("/api/sessions/{sid}/handoff")
    async def handoff(sid: str, req: Request):
        s = load(sid, req)
        free(sid)
        return project_session(
            engine.handoff(s, "Employee requested human assistance / 员工要求人工协助")
        )

    @app.post("/api/sessions/{sid}/issues")
    async def issue(sid: str, body: NewIssue, req: Request):
        s = load(sid, req)
        free(sid)
        if active(s)["pending"]:
            raise InvalidDecision("Cancel or confirm action before switching issues")
        from .security import redact

        i = store.issue(redact(body.title))
        s["issues"].append(i)
        s["active_issue"] = i["id"]
        store.save(s)
        return project_session(s)

    @app.post("/api/sessions/{sid}/issues/{iid}/select")
    async def select(sid: str, iid: str, req: Request):
        s = load(sid, req)
        free(sid)
        if active(s)["pending"]:
            raise InvalidDecision("Finish pending action first")
        if iid not in [i["id"] for i in s["issues"]]:
            raise HTTPException(404, "Issue not found")
        s["active_issue"] = iid
        store.save(s)
        return project_session(s)

    @app.get("/api/sessions/{sid}/export")
    async def export(sid: str, req: Request):
        return load(sid, req)

    @app.get("/api/sessions/{sid}/metrics")
    async def usage(sid: str, req: Request):
        from .observability import metrics

        return metrics(load(sid, req))

    @app.get("/health")
    async def health():
        return dict(
            status="ok",
            mode=p.mode,
            model=getattr(p, "model", None),
            model_configured=p.configured,
        )

    @app.get("/")
    async def home():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
