"""Read-only tool gateway and independently enforced write policy."""

import asyncio
import json
import time

from .storage import now, uid


class Tools:
    def __init__(self, store, data):
        self.store = store
        self.data = data
        self.faults = {}

    def user(self, s):
        return next(u for u in self.data["users"] if u["id"] == s["employee"])

    def policy(self, s, action, resource):
        p = self.data["policies"]
        u = self.user(s)
        allowed = action in p["allowed_actions"]
        if action == "password_reset":
            allowed = allowed and u["recovery_registered"] and resource == "self"
        elif action == "access_request":
            allowed = allowed and resource in p["access_resources"]
        else:
            allowed = False
        return dict(
            allowed=bool(allowed),
            version=p["version"],
            confirmation_required=True,
            approval_required=action == "access_request",
            direct_grant=False,
        )

    async def execute(self, s, q):
        start = time.monotonic()
        result = None
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(self._read(s, q), timeout=3)
                break
            except (TimeoutError, ConnectionError):
                if attempt == 0:
                    await asyncio.sleep(0.05)
        return dict(
            id=uid("TOOL-"),
            tool=q.tool,
            query=q.model_dump(),
            at=now(),
            elapsed_ms=round((time.monotonic() - start) * 1000),
            status="ok" if result is not None else "error",
            data=result,
            error=None if result is not None else "unavailable",
            retryable=result is None,
        )

    async def _read(self, s, q):
        fault = self.faults.get(q.tool)
        if fault:
            raise ConnectionError("Injected outage")
        d = self.data
        service = q.service.lower()
        if q.tool == "search_kb":
            ids = self.store.search(q.query, service)
            return [a for a in d["kb"] if a["id"] in ids and a["approved"]]
        if q.tool == "get_current_user_context":
            return [
                {
                    **self.user(s),
                    "employee_id": s["employee"],
                    "id": "USER-" + s["employee"],
                }
            ]
        if q.tool == "get_service_status":
            region = self.user(s)["location"]
            records = [
                x
                for x in d["status"]
                if (not service or x["service"] == service)
                and x["region"] in ("global", region)
            ]
            # Keep global alongside regional so conflicts remain visible.
            return records
        if q.tool == "get_recent_changes":
            return [
                x
                for x in d["changes"]
                if not service or service == x["service"] or service in x["related"]
            ]
        if q.tool == "search_resolution_history":
            return [x for x in d["history"] if service == x["service"]][:4]
        if q.tool == "get_action_result":
            with self.store.db() as c:
                row = c.execute(
                    "SELECT body FROM actions WHERE id=? AND session=?",
                    (q.query, s["id"]),
                ).fetchone()
            return [json.loads(row["body"])] if row else []
        if q.tool == "evaluate_action_policy":
            return [dict(id="POLICY", **d["policies"])]
        raise ValueError("Unknown tool")
