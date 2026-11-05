"""Read-only employee-facing projection. Never persisted or passed back to the model."""

import copy
import re
from .security import redact


def choose(cn, en, language):
    return cn if language == "zh" else en


def language_of(text):
    return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


def message_kind(text):
    if text.startswith(("Clarification (model question):", "待澄清（模型提问）：")):
        return "clarify"
    if text.startswith(("Review and confirm", "请核对下方")):
        return "action"
    if text.startswith(("Matching service incident", "已发现匹配的服务事件")):
        return "incident"
    if text.startswith(("Created local simulated handoff", "已创建本地模拟交接")):
        return "handoff"
    if text.startswith(("Simulated action status:", "模拟动作状态：")):
        return "action_result"
    if text.startswith("Employee confirmation:"):
        return "feedback"
    if re.search(r"\[KB-\d{3} v\d+\]", text):
        return "guide"
    return "plain"


def project_session(session):
    """Add display metadata to a deep copy. Canonical text and engine state are untouched."""
    view = copy.deepcopy(session)
    issues = {i["id"]: i for i in session["issues"]}
    previous = {}
    languages = {}
    for message in view["messages"]:
        iid = message["issue"]
        boundary = previous.get(iid, "")
        at = message.get("at", "")
        previous[iid] = at
        if message["role"] == "user":
            languages[iid] = language_of(message["text"])
            continue
        issue = issues.get(iid)
        if not issue:
            continue
        lang = languages.get(iid, "en")
        kind = message_kind(message["text"])
        p = dict(
            kind=kind,
            language=lang,
            assessment="",
            references=[],
            body=message["text"],
            steps=[],
            conditions=[],
            help="",
            verification="",
            source=None,
        )
        # Only the decision directly preceding THIS output is eligible. Never display
        # the latest issue-level hypothesis for every historical message or a failed run.
        window = [
            ev
            for ev in session["events"]
            if ev.get("issue") == iid and boundary < ev.get("at", "") <= at
        ]
        decisions = [
            ev
            for ev in window
            if ev["type"] == "decision" and ev["detail"]["decision"]["kind"] != "query"
        ]
        latest = decisions[-1] if decisions else None
        rejected = latest and any(
            ev["type"] == "decision_rejected" and ev.get("at", "") >= latest["at"]
            for ev in window
        )
        d = (
            latest["detail"]["decision"]
            if latest
            and not rejected
            and kind not in ("plain", "action_result", "feedback")
            else None
        )
        if d:
            ids = d.get("evidence_ids", [])
            if all(ref in issue["evidence"] for ref in ids):
                p["assessment"] = redact(d.get("diagnosis", ""))
                p["references"] = [
                    dict(
                        id=ref,
                        title=issue["evidence"][ref].get("title")
                        or issue["evidence"][ref].get("service")
                        or ref,
                    )
                    for ref in ids
                ]
        if kind == "clarify":
            p["body"] = re.sub(
                r"^(Clarification \(model question\):\s*|待澄清（模型提问）：\s*)",
                "",
                message["text"],
            )
        elif kind == "guide":
            match = re.search(r"\[(KB-\d{3}) v(\d+)\]", message["text"])
            article = issue["evidence"].get(match[1], {}) if match else {}
            # Never replace historical guidance with a later document version.
            if not article.get("approved") or str(article.get("version")) != match[2]:
                message["presentation"] = p
                continue
            p["source"] = dict(
                id=article["id"], version=article["version"], title=article["title"]
            )
            p["steps"] = article["steps"]
            p["conditions"] = article["conditions"]
            p["verification"] = article["verification"]
            p["body"] = choose(
                "我找到了可以继续处理这件事的步骤。请先按下面的说明操作，并把结果告诉我。",
                "I found an approved next step for this issue. Please follow the instructions below and let me know what happens.",
                lang,
            )
            if any("Software Center" in step for step in article["steps"]):
                p["help"] = choose(
                    "这里的 Software Center 指公司批准的软件分发入口。当前资料未提供入口链接，请使用公司已发布的入口；如果找不到，请直接告诉我，或点击下方“人工协助”，不要从陌生网站下载安装包。",
                    "“Software Center” is the company-approved software distribution entry named in this guide. No link is available in the current records. Use your published company entry; if you cannot find it, tell me here or select Human assistance below. Do not download an installer from an unfamiliar website.",
                    lang,
                )
        elif kind == "action":
            resource = (d or {}).get("resource", "")
            name = {
                "snowflake:production:reader": "Snowflake 生产库只读权限"
                if lang == "zh"
                else "Snowflake production read-only access",
                "grafana:viewer": "Grafana 看板查看权限"
                if lang == "zh"
                else "Grafana dashboard viewer access",
                "self": "本人账户密码重置"
                if lang == "zh"
                else "a password-reset request for your own account",
            }.get(resource, resource)
            p["body"] = choose(
                f"我可以为你准备{name}的模拟申请。请核对下面的用途和范围，再选择“确认执行”或“取消”。确认前不会提交；访问申请提交后仍需审批，不会直接授予权限。",
                f"I can prepare a simulated request for {name}. Review the purpose and scope below, then select Confirm or Cancel. Nothing is submitted before confirmation; an access request still requires approval and does not grant permission.",
                lang,
            )
        elif kind == "incident":
            evidence = [
                issue["evidence"][r["id"]]
                for r in p["references"]
                if issue["evidence"][r["id"]].get("incident")
                and issue["evidence"][r["id"]].get("health") in ("degraded", "outage")
            ]
            if evidence:
                record = evidence[0]
                inc = record["incident"]
                p["body"] = choose(
                    f"我查到一条影响 {record['region']} 地区 {record['service']} 的服务事件：{inc.get('description', '')}。目前仍在等待服务恢复，不能认为问题已解决。",
                    f"I found an active {record['service']} incident affecting {record['region']}: {inc.get('description', '')}. The issue remains open while the service recovers.",
                    lang,
                )
                if inc.get("eta") is None:
                    p["body"] += choose(
                        " 当前记录没有预计恢复时间。",
                        " No recovery estimate is available in the current record.",
                        lang,
                    )
        elif kind == "handoff":
            match = re.search(r"HANDOFF-[a-f0-9]+", message["text"])
            hid = match[0] if match else ""
            p["body"] = choose(
                f"这一步需要人工继续处理。我已将问题描述、已查证据和尝试记录保存到交接单 {hid}，你不需要重新描述。这里是本地模拟队列，尚未通知真实 IT 人员；可以在右侧“人工交接”查看详情，或点击下方“导出记录”。",
                f"This needs human follow-up. I saved the problem description, evidence and attempted steps in handoff {hid}, so the context is ready to share. This is a local simulated queue; no real IT specialist has been notified. See Human handoff in the investigation panel or export the record below.",
                lang,
            )
        elif kind == "action_result":
            rid = re.search(r"SIM-[a-f0-9]+", message["text"])
            ref = rid[0] if rid else ""
            if "submitted" in message["text"]:
                p["body"] = choose(
                    f"模拟申请已提交，记录编号为 {ref}。这不代表权限已获批或故障已恢复；请按页面当前状态继续处理。",
                    f"The simulated request has been submitted. Your reference is {ref}. This does not establish approved access or recovered service; the current case status shows what is still pending.",
                    lang,
                )
            elif "cancelled" in message["text"]:
                p["body"] = choose(
                    "已取消这次模拟申请，没有提交操作。你可以继续描述问题，或调整需求。",
                    "I cancelled this simulated request without submitting an operation. You can continue describing the issue or revise the request.",
                    lang,
                )
            elif "denied" in message["text"]:
                p["body"] = choose(
                    "这次确认未通过当前权限或有效期检查，没有提交操作。请重新核对申请，或选择人工协助。",
                    "This confirmation did not pass the current authorization or expiry checks. No operation was submitted. Review the request again or select Human assistance.",
                    lang,
                )
        elif kind == "feedback":
            p["body"] = (
                choose(
                    "谢谢确认，我已把这件问题记为“员工确认已恢复”。如果有另一件事需要处理，请在左侧点击“＋ 新问题”。",
                    "Thanks for confirming. I marked this issue as recovered based on your feedback. For a different issue, select New Issue on the left.",
                    lang,
                )
                if "recovered /" in message["text"]
                else choose(
                    "收到，我已记录这次处理仍然无效。请继续告诉我现在的表现或错误信息，我会基于已有记录继续排查；也可以点击“人工协助”。",
                    "Understood. I recorded that the attempted fix did not work. Tell me what happens now or share the non-secret error so we can continue from the existing investigation; you can also select Human assistance.",
                    lang,
                )
            )
        message["presentation"] = p
    return view
