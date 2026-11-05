"""Generate versioned, entirely synthetic fixtures. No production instructions."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = "2026-11-04T09:00:00+08:00"
articles = []


def kb(service, title, tags, steps, verification, conditions=None, active=True):
    articles.append(
        dict(
            id=f"KB-{len(articles) + 1:03}",
            service=service,
            title=title,
            tags=tags,
            platform="all",
            version=2,
            updated_at=T,
            approved=active,
            conditions=conditions or [],
            steps=steps,
            verification=verification,
            escalation="If the applicable safe steps fail, preserve the results and contact the service team.",
        )
    )


kb(
    "vpn",
    "Intermittent VPN: collect context",
    "vpn disconnect 断开 远程",
    [
        "Record the disconnect time and exact client error, without sharing credentials.",
        "Check whether normal internet also drops at that time.",
    ],
    "Observe whether the failure affects internet or only VPN.",
)
kb(
    "vpn",
    "VPN 5.0 known idle disconnect",
    "vpn 5.0 idle 15 minutes 断开",
    [
        "Save work, then install the approved VPN 5.1 update from the managed Software Center.",
        "Reconnect and observe for at least 20 minutes.",
    ],
    "VPN stays connected for at least 20 minutes.",
    ["Managed VPN client version is 5.0", "No regional VPN outage"],
)
kb(
    "vpn",
    "VPN local network instability",
    "vpn wifi internet unstable 网络",
    [
        "Move closer to the access point or test an approved wired connection.",
        "Reconnect VPN and compare with the previous network.",
    ],
    "Internet and VPN remain stable.",
    ["Normal internet also disconnects"],
)
kb(
    "vpn",
    "VPN gateway outage",
    "vpn gateway outage 故障",
    [
        "Check the current service incident and affected region.",
        "Use only work resources already accessible without VPN while awaiting recovery.",
    ],
    "Service status recovers and employee confirms access.",
    ["An active matching VPN incident exists"],
)
kb(
    "vpn",
    "VPN authentication rejected",
    "vpn authentication login 登录",
    [
        "Check the exact non-secret error and whether Okta sign-in works.",
        "If Okta also fails, follow the account runbook rather than reinstalling VPN.",
    ],
    "Sign-in and internal access work.",
)
kb(
    "okta",
    "Differentiate login failure",
    "okta login password 登录 密码",
    [
        "Record the non-secret error and whether the user reaches the MFA step.",
        "Check current Okta health before asking the employee to repeat a reset.",
    ],
    "Successful sign-in confirmed by employee.",
)
kb(
    "okta",
    "Forgotten password self-service",
    "okta password reset 密码 重置",
    [
        "Open the company-managed Okta sign-in bookmark and choose the self-service password reset option.",
        "Use only the recovery channel already registered in the directory. Never share codes in chat.",
    ],
    "Employee confirms successful login.",
    [
        "Trusted recovery channel is registered",
        "No reset already tried without success",
    ],
)
kb(
    "okta",
    "Repeated reset did not help",
    "okta reset failed locked 重置 失败",
    [
        "Do not repeat a failed password reset. Record the error and whether MFA is reached.",
        "Ask Identity Support to inspect lockout or recovery policy if status is healthy.",
    ],
    "Identity Support verifies recovery; employee confirms sign-in.",
)
kb(
    "okta",
    "Lost MFA device",
    "okta mfa lost 手机 丢失",
    [
        "Do not approve new MFA prompts or share recovery codes.",
        "Request Identity Support identity verification and MFA recovery.",
    ],
    "Identity Support completes verification.",
    ["MFA factor unavailable"],
)
kb(
    "okta",
    "Unexpected MFA prompts",
    "okta security suspicious mfa 安全",
    [
        "Decline unexpected prompts and stop trying to approve them.",
        "Contact Security using the configured handoff; do not share passwords.",
    ],
    "Security validates account safety.",
)
kb(
    "salesforce",
    "Chicago shared latency",
    "salesforce slow chicago 慢 芝加哥",
    [
        "Check regional Salesforce status and whether coworkers are affected.",
        "If a matching incident exists, link it and avoid repeated local resets.",
    ],
    "Incident recovery and normal loading confirmed.",
)
kb(
    "salesforce",
    "Single browser loading issue",
    "salesforce browser cache loading 浏览器",
    [
        "Save work and test the managed browser private window.",
        "If only one browser is affected, record its version and extension list without exporting private data.",
    ],
    "Application loads normally.",
    ["No matching active incident", "Issue isolated to one browser"],
)
kb(
    "snowflake",
    "Production access approval",
    "snowflake production access 权限 生产",
    [
        "Check current entitlements and department.",
        "Submit a least-privilege approval request with business justification; do not grant access directly.",
    ],
    "Owner approval and subsequent provisioning confirmed.",
)
kb(
    "grafana",
    "Dashboard access request",
    "grafana dashboard permission 权限 看板",
    [
        "Check existing viewer entitlement.",
        "Request viewer access with the dashboard scope and business justification if missing.",
    ],
    "Approved access and dashboard loading confirmed.",
)
kb(
    "jenkins",
    "Pipeline timeout after maintenance",
    "jenkins timeout maintenance pipeline 超时 维护",
    [
        "Collect job name, first failure timestamp and non-secret error.",
        "Compare recent network changes and Snowflake connectivity; do not rerun destructive jobs or roll back production.",
    ],
    "Platform team verifies dependencies and a successful safe job run.",
)
kb(
    "tableau",
    "Stale downstream reports",
    "tableau stale refresh report 报表",
    [
        "Check latest successful refresh and upstream job status.",
        "Correlate failures with Jenkins; do not assume the report itself is the root cause.",
    ],
    "Upstream recovery and successful refresh confirmed.",
)
kb(
    "wifi",
    "Office Wi-Fi connectivity",
    "wifi network 连接 无线",
    [
        "Check whether other devices or coworkers on the same network are affected.",
        "Use an approved wired connection if available and report the location.",
    ],
    "Connectivity confirmed.",
)
kb(
    "email",
    "Mail delivery delay",
    "email mail outlook 邮件",
    [
        "Check mail service health and whether multiple recipients are affected.",
        "Record the non-secret error and time; never paste mail bodies containing sensitive data.",
    ],
    "Test message delivery confirmed.",
)
kb(
    "device",
    "Managed laptop startup",
    "laptop startup hardware 笔记本 开机",
    [
        "Check power connection and visible indicator lights.",
        "For overheating, swelling or damage, stop use and contact Hardware Support.",
    ],
    "Hardware team or employee confirms safe operation.",
)
kb(
    "teams",
    "Meeting audio issue",
    "teams audio meeting 麦克风",
    [
        "Check selected input/output in the managed meeting client.",
        "Test with the built-in audio test without recording confidential meetings.",
    ],
    "Employee confirms test audio.",
)
kb(
    "vpn",
    "Deprecated VPN workaround",
    "vpn disable firewall legacy",
    ["Do not use: obsolete workaround."],
    "Not applicable.",
    active=False,
)
kb(
    "snowflake",
    "Query performance triage",
    "snowflake slow query 慢",
    [
        "Record query ID without pasting customer data.",
        "Compare service status and route warehouse configuration changes to Data Platform.",
    ],
    "Data Platform confirms query performance.",
)
users = []
for i, (name, dept, loc, role) in enumerate(
    [
        ("Alex Chen", "Data Engineering", "Shanghai", "engineer"),
        ("Morgan Lee", "Sales", "Chicago", "analyst"),
        ("Sam Rivera", "Finance", "London", "analyst"),
        ("Taylor Park", "Data Engineering", "Chicago", "engineer"),
        ("Jordan Wu", "Research", "Shanghai", "scientist"),
        ("Casey Lin", "Operations", "Singapore", "associate"),
        ("Riley Zhao", "IT", "London", "engineer"),
        ("Jamie Sun", "Sales", "Shanghai", "associate"),
    ]
):
    users.append(
        dict(
            id=f"EMP-{i + 1:03}",
            name=name,
            department=dept,
            location=loc,
            role=role,
            equipment={
                "os": "macOS" if i % 2 == 0 else "Windows",
                "vpn_version": "5.0" if i % 2 == 0 else "5.1",
                "managed": True,
            },
            permissions=["grafana:viewer"] if i in (0, 3) else [],
            recovery_registered=i != 5,
        )
    )
services = []
for s in [
    "vpn",
    "okta",
    "salesforce",
    "snowflake",
    "grafana",
    "jenkins",
    "tableau",
    "wifi",
    "email",
    "teams",
]:
    services.append(
        dict(
            id=f"STATUS-{s}",
            service=s,
            region="global",
            health="healthy",
            updated_at=T,
            incident=None,
        )
    )
services.append(
    dict(
        id="INC-SF-104",
        service="salesforce",
        region="Chicago",
        health="degraded",
        updated_at=T,
        incident={
            "id": "INC-SF-104",
            "started_at": "2026-11-03T08:00:00+08:00",
            "description": "Chicago regional Salesforce latency under investigation",
            "owner": "Business Applications",
            "eta": None,
        },
    )
)
changes = [
    dict(
        id="CHG-231",
        service="jenkins",
        changed_at="2026-10-30T22:00:00+08:00",
        description="Friday maintenance: egress allowlist changed for build subnet.",
        related=["snowflake", "tableau"],
        causality_confirmed=False,
    ),
    dict(
        id="CHG-232",
        service="vpn",
        changed_at="2026-11-02T10:00:00+08:00",
        description="Managed VPN 5.1 released for 5.0 idle disconnect defect.",
        related=[],
        causality_confirmed=True,
    ),
]
history = []
for i, a in enumerate(articles[:20]):
    history.append(
        dict(
            id=f"HIST-{i + 1:03}",
            service=a["service"],
            symptoms=a["tags"],
            resolution=a["title"],
            article_id=a["id"],
            outcome="resolved" if i % 4 else "escalated",
            date="2026-10-20",
            caution="Historical similarity is not proof of current root cause.",
        )
    )
policies = dict(
    version="2026-11-04.1",
    allowed_actions=["password_reset", "access_request"],
    access_resources=["snowflake:production:reader", "grafana:viewer"],
    rules=[
        {"id": "POL-01", "rule": "Self only; server injects employee identity."},
        {"id": "POL-02", "rule": "Registered recovery channel required for reset."},
        {
            "id": "POL-03",
            "rule": "Every reset/access request requires exact confirmation.",
        },
        {
            "id": "POL-04",
            "rule": "Production access requires owner approval; never directly grant.",
        },
        {"id": "POL-05", "rule": "MFA recovery requires human identity verification."},
        {
            "id": "POL-06",
            "rule": "No production rollback, shell, SQL or firewall modification tool.",
        },
        {"id": "POL-07", "rule": "Urgency never overrides authorization."},
        {
            "id": "POL-08",
            "rule": "History is advisory; current policy/status takes precedence.",
        },
        {"id": "POL-09", "rule": "Reset does not imply successful employee login."},
        {"id": "POL-10", "rule": "Handoff queue is simulated and not staffed."},
    ],
)
(ROOT / "data" / "fixtures.json").write_text(
    json.dumps(
        dict(
            version="1.0",
            scenario_clock=T,
            kb=articles,
            users=users,
            status=services,
            changes=changes,
            history=history,
            policies=policies,
        ),
        ensure_ascii=False,
        indent=2,
    )
)
print(
    f"Created {len(articles)} KB articles, {len(users)} users, {len(services)} status records, {len(history)} histories."
)
