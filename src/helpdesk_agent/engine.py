"""Bounded orchestration. LLM decides; deterministic code authorizes and renders."""

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta

from .domain import Query
from .diagnostics import (
    mentioned_services,
    query_key,
    record_feedback,
    failure_report,
    failed_runbooks,
    redundant_directory_question,
)
from .provider import PROMPT_VERSION, ProviderError
from .security import redact
from .storage import now, uid


class InvalidDecision(Exception):
    pass


def active(s):
    return next(i for i in s["issues"] if i["id"] == s["active_issue"])


def zh(s):
    return any(
        "\u4e00" <= c <= "\u9fff"
        for c in (s["messages"][-1]["text"] if s["messages"] else "")
    )


def localized(s, cn, en):
    return cn if zh(s) else en


def say(s, text):
    s["messages"].append(
        dict(role="assistant", text=redact(text), issue=s["active_issue"], at=now())
    )


class Engine:
    def __init__(self, store, tools, provider):
        self.store = store
        self.tools = tools
        self.provider = provider

    def event(self, s, kind, detail):
        s["events"].append(
            dict(type=kind, at=now(), issue=s["active_issue"], detail=detail)
        )

    def context(self, s, results):
        i = active(s)
        # Bounded recent messages; full user facts and attempts are preserved in durable issue history.
        return dict(
            scenario_clock=self.tools.data["scenario_clock"],
            employee=s["employee"],
            issue={k: v for k, v in i.items() if k != "evidence"},
            conversation=[m for m in s["messages"] if m["issue"] == i["id"]][-16:],
            evidence=list(i["evidence"].values())[-16:],
            latest_tool_results=results,
            known_employee_context=next(
                (
                    x
                    for x in i["evidence"].values()
                    if x.get("_source") == "get_current_user_context"
                ),
                None,
            ),
            failed_runbooks=sorted(failed_runbooks(i)),
            execution_feedback=i.get("execution_feedback", []),
            constraints="Tools unavailable => do not assume healthy. Guidance requires retrieved approved runbook.",
        )

    async def run(self, s, text, rid):
        previous = self.store.request(s["id"], rid)
        if previous:
            if previous["text"] != redact(text):
                raise InvalidDecision("Request ID reused with different text")
            return s
        i = active(s)
        if i["pending"]:
            raise InvalidDecision("Confirm or cancel pending action first")
        if i["status"] in ("resolved", "escalated", "waiting_approval"):
            raise InvalidDecision(
                "Create a new issue to continue after terminal or approval state"
            )
        if i["status"] == "waiting_verification" and failure_report(text):
            record_feedback(i, False)
        self.store.remember(s["id"], rid, dict(text=redact(text), at=now()))
        s["messages"].append(
            dict(role="user", text=redact(text), issue=i["id"], at=now())
        )
        s["running"] = True
        i["status"] = "investigating"
        self.store.save(s)
        run = uid("RUN-")
        start = time.monotonic()
        results = []
        seen = set()
        calls = 0
        try:
            async with asyncio.timeout(70):
                # Deterministic prerequisite reads; no diagnosis or answer is hardcoded.
                # Fetch directory before asking for OS/client data; status before local fixes.
                bootstrap = [
                    Query(tool="get_current_user_context", query="", service="")
                ]
                explicit = mentioned_services(text)
                for service in explicit[:2]:
                    bootstrap.append(
                        Query(tool="get_service_status", query="", service=service)
                    )
                if explicit and re.search(
                    r"maintenance|changes?|维护|变更", text, re.I
                ):
                    bootstrap.append(
                        Query(tool="get_recent_changes", query="", service=explicit[0])
                    )
                results = await asyncio.gather(
                    *(self.tools.execute(s, q) for q in bootstrap)
                )
                calls += len(bootstrap)
                seen.update(query_key(q) for q in bootstrap)
                for result in results:
                    self.event(s, "tool", result)
                    for item in result["data"] or []:
                        i["evidence"][item["id"]] = {
                            **item,
                            "_source": result["tool"],
                            "_observed_at": result["at"],
                        }
                self.store.save(s)
                for step in range(5):
                    t = time.monotonic()
                    decision, usage = await self.provider.decide(
                        self.context(s, results)
                    )
                    self.event(
                        s,
                        "model",
                        dict(
                            run_id=run,
                            step=step,
                            elapsed_ms=round((time.monotonic() - t) * 1000),
                            usage=usage,
                            prompt_version=PROMPT_VERSION,
                            model=getattr(self.provider, "model", None),
                        ),
                    )
                    self.event(
                        s, "decision", dict(run_id=run, decision=decision.model_dump())
                    )
                    if decision.kind == "query":
                        if not decision.queries:
                            raise InvalidDecision("Empty tool batch")
                        queries = []
                        for q in decision.queries:
                            key = query_key(q)
                            if key not in seen and calls < 8:
                                seen.add(key)
                                queries.append(q)
                                calls += 1
                        if not queries:
                            feedback = dict(
                                code="These reads were already attempted (including unavailable results), or the tool budget is exhausted. Do not repeat them; use known evidence, ask genuinely missing facts or escalate."
                            )
                            i.setdefault("execution_feedback", []).append(feedback)
                            self.event(
                                s, "decision_rejected", dict(run_id=run, **feedback)
                            )
                            results = [
                                dict(
                                    status="rejected", data=None, error=feedback["code"]
                                )
                            ]
                            continue
                        results = await asyncio.gather(
                            *(self.tools.execute(s, q) for q in queries)
                        )
                        for r in results:
                            self.event(s, "tool", r)
                            for item in r["data"] or []:
                                item = dict(item)
                                item["_source"] = r["tool"]
                                item["_observed_at"] = r["at"]
                                i["evidence"][item["id"]] = item
                        self.store.save(s)
                        continue
                    try:
                        self.apply(s, decision)
                    except InvalidDecision as invalid:
                        feedback = dict(
                            code=str(invalid),
                            rejected_kind=decision.kind,
                            runbook_id=decision.runbook_id,
                        )
                        i.setdefault("execution_feedback", []).append(feedback)
                        self.event(s, "decision_rejected", dict(run_id=run, **feedback))
                        # Re-plan with precise, safe feedback within the SAME original budget.
                        # Never rerun a denied write or expand authority.
                        results = [
                            dict(status="rejected", data=None, error=str(invalid))
                        ]
                        continue
                    break
                else:
                    say(
                        s,
                        localized(
                            s,
                            "调查已达到本轮预算，尚未确认根因。请补充错误信息，或点击人工协助。",
                            "Investigation budget reached without a verified cause. Please share the non-secret error or request human assistance.",
                        ),
                    )
                    i["status"] = "waiting_user"
        except asyncio.CancelledError:
            i["status"] = "waiting_user"
            self.event(s, "interrupted", dict(run_id=run, code="shutdown_cancelled"))
            say(
                s,
                localized(
                    s,
                    "本轮因服务停止而中断，请核对已保存的记录后再继续。",
                    "This turn was interrupted by shutdown. Review persisted records before continuing.",
                ),
            )
            raise
        except (
            ProviderError,
            TimeoutError,
            InvalidDecision,
            StopIteration,
            RuntimeError,
            ValueError,
        ) as e:
            self.event(
                s,
                "run_error",
                dict(
                    run_id=run,
                    code=str(e)
                    if isinstance(e, (ProviderError, InvalidDecision))
                    else type(e).__name__,
                ),
            )
            say(
                s,
                localized(
                    s,
                    "当前无法完成可靠诊断（模型未配置、不可用或输出校验未通过）。已保存上下文；可稍后重试或点击“人工协助”。",
                    "Reliable diagnosis is currently unavailable (model configuration, availability or output validation). Context is saved; retry later or select Human assistance.",
                ),
            )
            i["status"] = "waiting_user"
        finally:
            s["running"] = False
            self.event(
                s,
                "run_complete",
                dict(
                    run_id=run,
                    elapsed_ms=round((time.monotonic() - start) * 1000),
                    tool_calls=calls,
                ),
            )
            self.store.save(s)
        return s

    def apply(self, s, d):
        i = active(s)
        e = i["evidence"]
        if any(x not in e for x in d.evidence_ids):
            raise InvalidDecision("Unknown evidence reference")
        if d.diagnosis:
            i["hypotheses"].append(
                dict(
                    assessment=redact(d.diagnosis),
                    evidence=d.evidence_ids,
                    at=now(),
                    confirmed=False,
                )
            )
        if d.kind == "clarify":
            user_context = next(
                (
                    x
                    for x in e.values()
                    if x.get("_source") == "get_current_user_context"
                ),
                None,
            )
            if redundant_directory_question(d.question, user_context):
                raise InvalidDecision(
                    "OS/client are already in known_employee_context; ask only genuinely missing evidence such as the exact error"
                )
            # Free text explicitly a model question, never an execution record or verified claim.
            say(
                s,
                localized(s, "待澄清（模型提问）：", "Clarification (model question): ")
                + d.question,
            )
            i["status"] = "waiting_user"
        elif d.kind == "guide":
            a = e.get(d.runbook_id)
            if not a or a.get("_source") != "search_kb" or not a.get("approved"):
                raise InvalidDecision("Unapproved/unretrieved runbook")
            if len(d.condition_evidence) != len(a["conditions"]) or any(
                x not in e for x in d.condition_evidence
            ):
                raise InvalidDecision("Missing runbook preconditions")
            if d.runbook_id in failed_runbooks(i):
                raise InvalidDecision(
                    "This runbook was already reported unsuccessful; investigate a DIFFERENT cause or escalate"
                )
            if d.runbook_id in ("KB-013", "KB-014"):
                raise InvalidDecision(
                    "This is an access approval workflow, not a repair. Propose access_request with exact scope, or clarify missing justification"
                )
            if d.runbook_id in ("KB-008", "KB-009", "KB-010"):
                self.handoff(
                    s,
                    f"[{a['id']}] {a['title']}: human identity/security review required",
                )
                return
            # Bind version-sensitive VPN fix to independently retrieved current user and health records.
            if a["id"] == "KB-002":
                u = next(
                    (
                        x
                        for x in e.values()
                        if x.get("_source") == "get_current_user_context"
                    ),
                    None,
                )
                health = [
                    x
                    for x in e.values()
                    if x.get("_source") == "get_service_status"
                    and x.get("service") == "vpn"
                ]
                if (
                    not u
                    or u["equipment"]["vpn_version"] != "5.0"
                    or not health
                    or any(x["health"] != "healthy" for x in health)
                ):
                    raise InvalidDecision("VPN update not applicable")
            if a["id"] == "KB-007":
                user_messages = " ".join(
                    m["text"].lower()
                    for m in s["messages"]
                    if m["role"] == "user" and m["issue"] == i["id"]
                )
                if any(
                    x in user_messages
                    for x in ["already reset", "tried resetting", "重置过", "已经重置"]
                ):
                    raise InvalidDecision("Reset already attempted")
            say(
                s,
                (
                    localized(
                        s,
                        "仅在以下条件适用时执行：",
                        "Only proceed if these conditions apply: ",
                    )
                    + "; ".join(a["conditions"])
                    + "\n"
                    if a["conditions"]
                    else ""
                )
                + f"[{a['id']} v{a['version']}] {a['title']}\n"
                + "\n".join(f"{n + 1}. {x}" for n, x in enumerate(a["steps"]))
                + "\n"
                + localized(s, "下一步检查：", "Next check: ")
                + a["verification"],
            )
            i["attempts"].append(
                dict(article=a["id"], at=now(), result="proposed_not_confirmed")
            )
            # These runbooks collect information; they do not claim to repair anything.
            i["status"] = (
                "waiting_user"
                if a["id"]
                in (
                    "KB-001",
                    "KB-005",
                    "KB-006",
                    "KB-011",
                    "KB-015",
                    "KB-016",
                    "KB-017",
                    "KB-018",
                    "KB-022",
                )
                else "waiting_verification"
            )
        elif d.kind == "action":
            self.propose(s, d.action, d.resource, d.justification)
        elif d.kind == "incident":
            incidents = [
                e[x]
                for x in d.evidence_ids
                if e[x].get("_source") == "get_service_status"
                and e[x].get("health") in ("degraded", "outage")
            ]
            if not incidents:
                raise InvalidDecision("No active incident evidence")
            incident = incidents[0]
            say(
                s,
                localized(
                    s,
                    "已发现匹配的服务事件，等待恢复；尚未解决。",
                    "Matching service incident found; awaiting recovery, not resolved.",
                )
                + f"\n[{incident['id']}] {json.dumps(incident.get('incident'), ensure_ascii=False)}",
            )
            i["status"] = "waiting_service"
        elif d.kind == "escalate":
            self.handoff(s, d.diagnosis or "Agent boundary reached")
        else:
            raise InvalidDecision("Unsupported decision")

    def propose(self, s, action, resource, justification):
        i = active(s)
        if i["pending"]:
            raise InvalidDecision("Another action already awaits confirmation")
        if action == "password_reset":
            messages = " ".join(
                m["text"].lower()
                for m in s["messages"]
                if m["role"] == "user" and m["issue"] == i["id"]
            )
            if any(
                t in messages
                for t in ["already reset", "tried resetting", "重置过", "已经重置"]
            ):
                raise InvalidDecision("Reset already attempted; investigate instead")
        policy = self.tools.policy(s, action, resource)
        if not policy["allowed"]:
            raise InvalidDecision("Action denied by current policy")
        if action == "access_request" and not justification.strip():
            raise InvalidDecision("Business justification required")
        if not any(
            x.get("_source") == "get_current_user_context"
            for x in i["evidence"].values()
        ):
            raise InvalidDecision("User context not investigated")
        a = dict(
            id=uid("ACT-"),
            employee=s["employee"],
            issue=i["id"],
            action=action,
            resource=resource,
            justification=redact(justification),
            policy_version=policy["version"],
            expires=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            status="pending",
            simulated=True,
        )
        i["pending"] = a
        i["status"] = "waiting_confirmation"
        say(
            s,
            localized(
                s,
                "请核对下方模拟动作后确认。提交申请不会直接授予权限。",
                "Review and confirm the simulated action below. An access request does not grant permission.",
            ),
        )
        self.store.save(s, action=a)

    def confirm(self, s, aid, approve):
        i = active(s)
        a = i["pending"]
        if not a:
            with self.store.db() as c:
                row = c.execute(
                    "SELECT body FROM actions WHERE id=? AND session=? AND issue=?",
                    (aid, s["id"], i["id"]),
                ).fetchone()
            if row:
                return s  # Idempotent replay of this issue's own action.
            raise InvalidDecision("Unknown action")
        if a["id"] != aid:
            raise InvalidDecision("Action mismatch")
        policy = self.tools.policy(s, a["action"], a["resource"])
        if not approve:
            a["status"] = "cancelled"
            i["status"] = "waiting_user"
        elif (
            datetime.fromisoformat(a["expires"]) < datetime.now(UTC)
            or a["employee"] != s["employee"]
            or a["issue"] != i["id"]
            or a["policy_version"] != policy["version"]
            or not policy["allowed"]
        ):
            a["status"] = "denied"
            i["status"] = "waiting_user"
        else:
            a["status"] = "submitted"
            a["result_id"] = uid("SIM-")
            i["status"] = (
                "waiting_approval"
                if a["action"] == "access_request"
                else "waiting_verification"
            )
        i["attempts"].append(dict(action=a.copy(), at=now(), result=a["status"]))
        i["pending"] = None
        say(
            s,
            localized(s, "模拟动作状态：", "Simulated action status: ")
            + a["status"]
            + " "
            + a.get("result_id", "")
            + localized(
                s,
                "。这不代表故障已解决。",
                ". This does not establish issue resolution.",
            ),
        )
        self.event(s, "action", a.copy())
        self.store.save(s, action=a)
        return s

    def handoff(self, s, reason):
        i = active(s)
        if i["handoff"]:
            return s
        if i["pending"]:
            self.confirm(s, i["pending"]["id"], False)
        h = dict(
            id=uid("HANDOFF-"),
            simulated=True,
            queue="IT triage (local, unstaffed)",
            employee=self.tools.user(s),
            issue_id=i["id"],
            reason=redact(reason),
            created_at=now(),
            timeline=[m for m in s["messages"] if m["issue"] == i["id"]],
            evidence=list(i["evidence"].values()),
            attempts=i["attempts"],
            hypotheses=i["hypotheses"],
            unknowns=[
                "Root cause and service recovery are not verified unless explicitly shown in evidence."
            ],
            policy_version=self.tools.data["policies"]["version"],
            next_step="Review evidence, validate identity if needed, and route to service owner.",
            tool_failures=[
                ev
                for ev in s["events"]
                if ev["issue"] == i["id"]
                and ev["type"] == "tool"
                and ev["detail"]["status"] == "error"
            ],
        )
        i["handoff"] = h
        i["status"] = "escalated"
        say(
            s,
            localized(
                s,
                "已创建本地模拟交接记录（无人值守）：",
                "Created local simulated handoff (not staffed): ",
            )
            + h["id"]
            + "\n"
            + redact(reason),
        )
        self.event(s, "handoff", dict(id=h["id"]))
        self.store.save(s, handoff=h)
        return s
