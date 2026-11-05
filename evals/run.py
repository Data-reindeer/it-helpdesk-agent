"""Opt-in repeated live evaluation, with bounded concurrency and durable checkpoints."""

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dotenv import load_dotenv
from helpdesk_agent.engine import Engine, active
from helpdesk_agent.evaluation import checks_for
from helpdesk_agent.provider import OpenAIProvider, PROMPT_VERSION
from helpdesk_agent.storage import Store
from helpdesk_agent.tools import Tools

ROOT = Path(__file__).resolve().parents[1]


async def run_case(c, repeat, p):
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "eval.sqlite"))
        data = json.loads((ROOT / "data/fixtures.json").read_text())
        store.initialize(data)
        tools = Tools(store, data)
        if c.get("fault"):
            tools.faults[c["fault"]] = True
        engine = Engine(store, tools, p)
        s = store.create("eval", c["employee"])
        start = time.monotonic()
        for n, text in enumerate(c["messages"]):
            if active(s)["pending"] or active(s)["status"] in (
                "escalated",
                "resolved",
                "waiting_approval",
            ):
                break
            await engine.run(s, text, f"eval-{n:08}")
        checks = checks_for(c, s)
        return dict(
            case=c["id"],
            name=c["name"],
            repeat=repeat,
            checks=checks,
            passed=all(checks.values()),
            elapsed_ms=round((time.monotonic() - start) * 1000),
            state=s,
        )


async def main(args):
    load_dotenv(ROOT / ".env", override=True)
    p = OpenAIProvider()
    cases = json.loads((ROOT / "evals/cases.json").read_text())
    if args.case:
        wanted = set(args.case.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        if {c["id"] for c in cases} != wanted:
            raise ValueError("Unknown evaluation case ID")
    report = dict(
        model=p.model,
        prompt=PROMPT_VERSION,
        data_version="1.0",
        cases_sha256=hashlib.sha256(
            (ROOT / "evals/cases.json").read_bytes()
        ).hexdigest(),
        mode="live" if args.live else "not_run",
        repeat=args.repeat,
        jobs=args.jobs,
        results=[],
        notes="Coarse checks supplement transcript review; wording is not compared verbatim.",
    )

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.output.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        tmp.replace(args.output)

    if not args.live or not p.configured:
        report["status"] = "NOT_RUN: supply .env and explicitly pass --live"
        save()
        print(report["status"])
        return 2
    report["status"] = "running"
    report["planned"] = len(cases) * args.repeat
    save()
    semaphore = asyncio.Semaphore(args.jobs)

    async def work(c, n):
        async with semaphore:
            result = await run_case(c, n, p)
            report["results"].append(result)
            save()
            errors = [
                e["detail"]["code"]
                for e in result["state"]["events"]
                if e["type"] == "run_error"
            ]
            print(
                f"{len(report['results'])}/{report['planned']} {c['id']} run={n + 1} {'PASS' if result['passed'] else 'FAIL'} state={active(result['state'])['status']} ms={result['elapsed_ms']} errors={errors}",
                flush=True,
            )

    await asyncio.gather(*(work(c, n) for c in cases for n in range(args.repeat)))
    report["status"] = "completed"
    report["passed"] = sum(r["passed"] for r in report["results"])
    report["total"] = len(report["results"])
    save()
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0 if report["passed"] == report["total"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--case")
    parser.add_argument("--output", type=Path, default=ROOT / "var/live-eval.json")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10 or not 1 <= args.jobs <= 4:
        parser.error("repeat must be 1..10 and jobs 1..4")
    sys.exit(asyncio.run(main(args)))
