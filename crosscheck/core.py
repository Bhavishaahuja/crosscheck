"""Step 5: verdict. Ties trace -> claims -> code check -> LLM fallback together."""
from __future__ import annotations

import os
import time

from .checker import code_check
from .claims import extract_claims
from .trace import Run, fetch_run

BAD = {"mismatch", "contradicted"}
OPEN = {"unverified", "not_enough_info"}


def check_run(run: Run | str, use_llm: bool | None = None, model: str | None = None) -> dict:
    t0 = time.perf_counter()
    if isinstance(run, str):
        run = fetch_run(run)
    claims = extract_claims(run.final_answer)
    findings = code_check(claims, run)
    code_settled = sum(f.verdict not in OPEN for f in findings)
    pending = [f for f in findings if f.verdict == "unverified"]

    if use_llm is None:
        use_llm = os.getenv("CROSSCHECK_LLM", "1") != "0" and bool(
            os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
    if use_llm and pending:
        from .llm import llm_check
        usage = llm_check(run, pending, model)

    if any(f.verdict in BAD for f in findings):
        verdict = "flag"
    elif any(f.verdict in OPEN for f in findings):
        verdict = "unsure"
    else:
        verdict = "pass"

    return {
        "run_id": run.run_id,
        "workflow": run.workflow,
        "verdict": verdict,
        "flags": [f.to_dict() for f in findings if f.verdict in BAD],
        "findings": [f.to_dict() for f in findings],
        "stats": {
            "claims": len(findings),
            "tool_calls": len(run.tool_calls),
            "checked_by_code": code_settled,
            "sent_to_llm": len(pending) if use_llm else 0,
            "unresolved": sum(f.verdict in OPEN for f in findings),
            "latency_s": round(time.perf_counter() - t0, 3),
            "llm": usage,
        },
    }
