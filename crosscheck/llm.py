"""Step 4: LLM fallback. Only claims code could not settle go to Claude, with only the
tool outputs that look relevant, and the verdict comes back as a tool call."""
from __future__ import annotations

import json
import os

from .checker import Finding
from .claims import tokens
from .trace import Run

# USD per 1M tokens (input, output)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00), "claude-opus-5": (5.00, 25.00), "claude-sonnet-5": (2.00, 10.00),
}
# These models reject tool_choice {"type": "tool"}; they get "auto" + a strict schema + an instruction.
NO_FORCED_TOOL = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1"}
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_CONTEXT_CHARS = 6000

VERDICT_TOOL = {
    "name": "record_verdicts",
    "description": "Record, for each claim, whether the tool outputs support it.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdicts"],
        "properties": {"verdicts": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["claim_id", "verdict", "expected", "reason"],
            "properties": {
                "claim_id": {"type": "integer"},
                "verdict": {"type": "string", "enum": ["supported", "contradicted", "not_enough_info"]},
                "expected": {"type": "string", "description": "What the tool output says instead, or empty."},
                "reason": {"type": "string", "description": "One line."},
            },
        }}},
    },
}

SYSTEM = (
    "You audit an AI agent's final answer against the raw outputs of the tools it called in the same run. "
    "For each numbered claim decide: supported (the tool outputs state it, or it follows by simple arithmetic "
    "or reasonable paraphrase), contradicted (the tool outputs state something incompatible), or not_enough_info "
    "(the tool outputs say nothing either way). Judge only against the tool outputs, never outside knowledge. "
    "Answer by calling record_verdicts once."
)


def relevant_outputs(run: Run, findings: list[Finding]) -> str:
    want = set()
    for f in findings:
        want |= set(tokens(f.claim.sentence))
    scored = []
    for tc in run.tool_calls:
        text = json.dumps(tc.output, ensure_ascii=False, default=str)
        overlap = len(want & set(tokens(text)))
        scored.append((overlap, tc.span_id, tc.name, text))
    scored.sort(key=lambda t: -t[0])
    parts, used = [], 0
    for _, sid, name, text in scored:
        room = MAX_CONTEXT_CHARS - used
        if room <= 200:
            break
        chunk = text[:room]
        parts.append(f"<tool span_id=\"{sid}\" name=\"{name}\">\n{chunk}\n</tool>")
        used += len(chunk)
    return "\n".join(parts)


def llm_check(run: Run, pending: list[Finding], model: str | None = None) -> dict:
    """Mutates pending findings in place. Returns usage {input_tokens, output_tokens, cost_usd, calls}."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
    if not pending:
        return usage
    import anthropic

    model = model or os.getenv("CROSSCHECK_MODEL", DEFAULT_MODEL)
    claims = "\n".join(f"{i}. [{f.claim.kind}] \"{f.claim.text}\" in: {f.claim.sentence.strip()}"
                       for i, f in enumerate(pending))
    prompt = f"Tool outputs from this run:\n{relevant_outputs(run, pending)}\n\nClaims to check:\n{claims}"
    req = dict(model=model, max_tokens=2048, system=SYSTEM, tools=[VERDICT_TOOL],
               messages=[{"role": "user", "content": prompt}])
    if model in NO_FORCED_TOOL:
        req["tool_choice"] = {"type": "auto"}
        req["output_config"] = {"effort": "low"}
    else:
        req["tool_choice"] = {"type": "tool", "name": "record_verdicts"}

    resp = anthropic.Anthropic().messages.create(**req)
    usage["calls"] = 1
    usage["input_tokens"] = resp.usage.input_tokens
    usage["output_tokens"] = resp.usage.output_tokens
    pin, pout = PRICES.get(model, (0.0, 0.0))
    usage["cost_usd"] = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6

    block = next((b for b in resp.content if b.type == "tool_use"), None)
    verdicts = (block.input if block else {}).get("verdicts", [])
    by_id = {v["claim_id"]: v for v in verdicts if isinstance(v, dict) and "claim_id" in v}
    for i, f in enumerate(pending):
        v = by_id.get(i)
        f.checked_by = "llm"
        if not v:
            f.verdict, f.evidence = "not_enough_info", "no verdict returned"
            continue
        f.verdict = v["verdict"]
        f.expected = v.get("expected") or None
        f.evidence = v.get("reason", "")
    return usage
