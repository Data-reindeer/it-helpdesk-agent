"""Small deterministic diagnostic invariants; no canned issue resolutions."""

import re
from datetime import datetime, timezone

ALIASES = {
    "vpn": ("vpn", "虚拟专用网络"),
    "okta": ("okta",),
    "salesforce": ("salesforce",),
    "snowflake": ("snowflake",),
    "grafana": ("grafana",),
    "jenkins": ("jenkins",),
    "tableau": ("tableau",),
    "wifi": ("wi-fi", "wifi", "无线网络"),
    "email": ("outlook", "email", "邮件"),
    "teams": ("teams",),
}


def mentioned_services(text):
    text = text.lower()
    return [
        service
        for service, aliases in ALIASES.items()
        if any(
            re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", text)
            for a in aliases
        )
    ]


def record_feedback(issue, resolved):
    result = "employee_confirmed_recovered" if resolved else "employee_reported_failure"
    attempt = next(
        (
            a
            for a in reversed(issue["attempts"])
            if a.get("result") == "proposed_not_confirmed"
        ),
        None,
    )
    if attempt:
        attempt["result"] = result
    issue["attempts"].append(
        dict(
            result=result,
            article=attempt.get("article") if attempt else None,
            at=datetime.now(timezone.utc).isoformat(),
            source="employee_feedback",
        )
    )


def failure_report(text):
    return bool(
        re.search(
            r"still (?:fails?|failing|disconnects?|broken)|did(?:n.t| not) (?:work|help)|没有(?:解决|恢复)|仍然|还是(?:断|不行)|依然|无效",
            text,
            re.I,
        )
    )


def failed_runbooks(issue):
    return {
        a["article"]
        for a in issue["attempts"]
        if a.get("article") and a.get("result") == "employee_reported_failure"
    }


def redundant_directory_question(question, context):
    if not context:
        return False
    equipment = context.get("equipment", {})
    # Reject only explicit questions for facts the authoritative directory already supplies.
    os_ask = bool(
        re.search(
            r"which operating system|what (?:operating system|os)\b|什么(?:操作)?系统|(?:操作)?系统是什么",
            question,
            re.I,
        )
    )
    client_ask = bool(
        re.search(
            r"(?:which|what) vpn client|vpn (?:client )?version.*\?|vpn.*(?:客户端|版本).*[？?]",
            question,
            re.I,
        )
    )
    return bool(
        (os_ask and equipment.get("os"))
        or (client_ask and equipment.get("vpn_version"))
    )


def query_key(query):
    if query.tool == "get_current_user_context":
        return (query.tool,)
    if query.tool in (
        "get_service_status",
        "get_recent_changes",
        "search_resolution_history",
        "evaluate_action_policy",
    ):
        return (query.tool, query.service.casefold())
    return (
        query.tool,
        query.service.casefold(),
        " ".join(query.query.casefold().split()),
    )
