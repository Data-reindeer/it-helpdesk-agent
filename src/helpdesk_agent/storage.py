"""Single-process SQLite repository; transactions + optimistic versions."""

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


def uid(prefix=""):
    return prefix + secrets.token_hex(12)


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.db() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,owner TEXT NOT NULL, version INTEGER NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(session TEXT,request TEXT,body TEXT,PRIMARY KEY(session,request));
            CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,session TEXT,issue TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY,session TEXT,issue TEXT,body TEXT, UNIQUE(session,issue));
            CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(id UNINDEXED, service, title, tags, body);
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def initialize(self, data):
        with self.db() as c:
            c.execute("DELETE FROM kb_fts")
            for a in data["kb"]:
                if a["approved"]:
                    c.execute(
                        "INSERT INTO kb_fts VALUES(?,?,?,?,?)",
                        (
                            a["id"],
                            a["service"],
                            a["title"],
                            a["tags"],
                            " ".join(a["steps"]),
                        ),
                    )
            for row in c.execute("SELECT * FROM sessions").fetchall():
                s = json.loads(row["body"])
                if s.get("running"):
                    s["running"] = False
                    s["events"].append(
                        dict(
                            type="interrupted",
                            at=now(),
                            detail="Previous run interrupted; actions were not replayed.",
                        )
                    )
                    c.execute(
                        "UPDATE sessions SET body=?,version=version+1 WHERE id=?",
                        (json.dumps(s), row["id"]),
                    )

    def create(self, owner, employee):
        issue = self.issue("New IT issue")
        s = dict(
            id=uid("SES-"),
            employee=employee,
            version=0,
            active_issue=issue["id"],
            issues=[issue],
            messages=[],
            events=[],
            running=False,
        )
        with self.db() as c:
            c.execute(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                (s["id"], owner, 0, json.dumps(s)),
            )
        return s

    @staticmethod
    def issue(title):
        return dict(
            id=uid("ISS-"),
            title=title,
            status="investigating",
            evidence={},
            attempts=[],
            hypotheses=[],
            pending=None,
            handoff=None,
        )

    def load(self, sid, owner):
        with self.db() as c:
            r = c.execute(
                "SELECT * FROM sessions WHERE id=? AND owner=?", (sid, owner)
            ).fetchone()
        if not r:
            raise KeyError("Session not found")
        s = json.loads(r["body"])
        s["version"] = r["version"]
        return s

    def save(self, s, action=None, handoff=None):
        # Side effects and state transition commit together for simulated connectors.
        with self.db() as c:
            n = c.execute(
                "UPDATE sessions SET body=?,version=version+1 WHERE id=? AND version=?",
                (json.dumps(s), s["id"], s["version"]),
            ).rowcount
            if n != 1:
                raise RuntimeError("Concurrent update")
            if action:
                c.execute(
                    "INSERT OR REPLACE INTO actions VALUES(?,?,?,?)",
                    (action["id"], s["id"], s["active_issue"], json.dumps(action)),
                )
            if handoff:
                c.execute(
                    "INSERT INTO handoffs VALUES(?,?,?,?) ON CONFLICT(session,issue) DO NOTHING",
                    (handoff["id"], s["id"], s["active_issue"], json.dumps(handoff)),
                )
        s["version"] += 1

    def request(self, sid, rid):
        with self.db() as c:
            r = c.execute(
                "SELECT body FROM requests WHERE session=? AND request=?", (sid, rid)
            ).fetchone()
        return json.loads(r["body"]) if r else None

    def remember(self, sid, rid, body):
        with self.db() as c:
            c.execute(
                "INSERT INTO requests VALUES(?,?,?)", (sid, rid, json.dumps(body))
            )

    def search(self, query, service):
        import re

        aliases = {
            "断开": "disconnect",
            "密码": "password",
            "登录": "login",
            "权限": "access",
            "生产": "production",
            "报表": "stale",
            "维护": "maintenance",
            "超时": "timeout",
            "慢": "slow",
            "看板": "dashboard",
            "远程": "vpn",
            "验证码": "mfa",
        }
        for k, v in aliases.items():
            query = query.replace(k, " " + v + " ")
        terms = re.findall(r"[a-zA-Z0-9]+", query.lower())[:18]
        if not terms:
            return []
        expr = " OR ".join('"' + x + '"' for x in terms)
        with self.db() as c:
            rows = c.execute(
                "SELECT id FROM kb_fts WHERE kb_fts MATCH ? "
                + ("AND service=? " if service else "")
                + "ORDER BY bm25(kb_fts) LIMIT 4",
                (expr, service) if service else (expr,),
            ).fetchall()
        return [r["id"] for r in rows]
