"""Usage-derived estimates; prices supplied by operator, never invented."""

import os


def metrics(s):
    model = [e["detail"] for e in s["events"] if e["type"] == "model"]
    reads = [e["detail"] for e in s["events"] if e["type"] == "tool"]
    usage = [e.get("usage") for e in model if e.get("usage")]
    inp = sum(u.get("input_tokens", 0) for u in usage)
    out = sum(u.get("output_tokens", 0) for u in usage)
    estimate = None
    try:
        pi = float(os.environ["INPUT_PRICE_PER_MILLION"])
        po = float(os.environ["OUTPUT_PRICE_PER_MILLION"])
        if usage and pi >= 0 and po >= 0:
            estimate = (inp * pi + out * po) / 1_000_000
    except (KeyError, ValueError):
        pass
    return dict(
        model_calls=len(model),
        tool_calls=len(reads),
        tool_failures=sum(r["status"] == "error" for r in reads),
        input_tokens=inp if usage else None,
        output_tokens=out if usage else None,
        usage_complete=len(usage) == len(model) and bool(model),
        estimated_usd=estimate,
        cost_note="Operator-supplied rates; excludes cached-token discounts. Unknown if rates/usage unavailable.",
    )
