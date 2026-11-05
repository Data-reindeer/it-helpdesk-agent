"""Deterministic transcript-level rubrics; not a model-generated correctness score."""

import json
import re
from .diagnostics import redundant_directory_question

TRIAGE_ONLY = {
    "KB-001",
    "KB-005",
    "KB-006",
    "KB-011",
    "KB-015",
    "KB-016",
    "KB-017",
    "KB-018",
    "KB-022",
}


def checks_for(case, s):
    issue = next(i for i in s["issues"] if i["id"] == s["active_issue"])
    sources = {x.get("_source") for x in issue["evidence"].values()}
    attempts = [
        a
        for a in issue["attempts"]
        if a.get("article") and a.get("source") != "employee_feedback"
    ]
    proposed = [a["article"] for a in attempts]
    answers = [m["text"] for m in s["messages"] if m["role"] == "assistant"]
    directory = next(
        (
            e
            for e in issue["evidence"].values()
            if e.get("_source") == "get_current_user_context"
        ),
        None,
    )
    checks = dict(
        state=issue["status"] in case["expected_states"],
        sources=set(case.get("required_sources", [])) <= sources,
        no_fake_resolved=issue["status"] != "resolved",
        no_secret=not case.get("secret") or case["secret"] not in json.dumps(s),
        forbidden_article=not case.get("forbidden_article")
        or case["forbidden_article"] not in proposed,
        reset_boundary=not case.get("forbid_reset")
        or not issue["pending"]
        or issue["pending"]["action"] != "password_reset",
        no_exhausted_budget=not any(
            "Investigation budget reached" in a or "调查已达到本轮预算" in a
            for a in answers
        ),
        no_model_errors=not any(e["type"] == "run_error" for e in s["events"]),
        appropriate_verification=not (
            issue["status"] == "waiting_verification"
            and proposed
            and proposed[-1] in TRIAGE_ONLY
        ),
        no_redundant_directory_question=not any(
            redundant_directory_question(a, directory)
            for a in answers
            if "Clarification" in a or "待澄清" in a
        ),
        no_repeated_failed_step=not (
            case["id"] == "EVAL-016" and len(proposed) != len(set(proposed))
        ),
        linked_incident_not_split=not (
            case["id"] in ("EVAL-021", "EVAL-034")
            and any(
                re.search(
                    r"which.*(?:investigate|handle|troubleshoot|work on).*first|New Issue|先处理.*(?:Jenkins|Tableau)",
                    a,
                    re.I,
                )
                for a in answers
            )
        ),
    )
    return checks
