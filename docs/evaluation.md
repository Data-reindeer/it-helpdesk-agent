# Evaluation

## Final evidence

| Dimension | Result | Interpretation |
|---|---:|---|
| Deterministic engineering tests | 87 passed | Contracts, authorization, persistence, feedback, presentation and API behavior |
| Live model scenarios | 40 × 3 = 120 runs | Visible synthetic cases, using the configured `gpt-6.1-sol` endpoint |
| Transcript rubric checks | 120/120 passed | Expected states, required sources and safety/continuity assertions; not universal answer accuracy |
| Real-model Chromium workflow checks | 8 passed | UI assessment, instructions, confirmation, verification, refresh, handoff and responsive layout |
| Read-only presentation invariance | 200 captured states checked; 0 mutations | Original messages and execution state are not changed by display projection |
| Live per-turn median latency | 13.237 seconds | Concurrent evaluation observation |
| Live per-turn P95 latency | 23.827 seconds | Includes network/model/tool time; exceeds a 15-second aspirational target |

The checked-in `evaluation-summary.json` contains only final aggregate observations. No credentials, employee runtime conversations, local databases or raw model traces are distributed. The scenarios and runner allow reviewers to produce their own traces locally.

## Method

`evals/cases.json` defines expected behavior for normal support, ambiguous/contextual descriptions, approval/escalation boundaries, missing/conflicting evidence, tool outages and adversarial input. The runner creates a fresh SQLite fixture database for each attempt, limits concurrency to four and records every repeat with a checkpoint. It does not demand fixed wording or select only the best response.

Rubrics in `evaluation.py` check expected terminal/waiting states, required source usage, no fabricated resolved state, source restrictions, reset boundaries, model errors/budget exhaustion, appropriate verification, redundant directory questions, repeated failed steps and inappropriate splitting of linked incidents. Human review is still needed for evidence entailment, sensible questions and unnecessary escalation. Asking when a job first failed is legitimate; asking which linked symptom to handle as a separate issue can be inappropriate.

Fake/replay providers are used only for deterministic tests and isolated UI checks. They do not count as real-model generalization evidence. Real API tests require the evaluator's key and consume provider usage.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python evals/run.py --live --case EVAL-001 --repeat 3
.venv/bin/python evals/run.py --live --repeat 3 --jobs 4 --output var/evaluation.json
```

Optional Chromium setup and tests are described in the README. Use `--live` only when real API calls are intended. All resulting reports and runtime data remain local under generated paths.

## Limits

This is a visible curated set, not an independently authored blind holdout. Some cases allow several valid outcomes, such as clarification or justified handoff. A passing waiting state is not equivalent to an automatically resolved employee problem. The model and provider are nondeterministic; subsequent access, latency and outputs can change. The sample does not establish statistical reliability for all IT support, attack resistance against all prompts, or a production SLA. The current runtime assumes one local worker and synthetic systems. Costs require operator-supplied prices; token usage alone is not a billing claim.
