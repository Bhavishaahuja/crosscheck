"""Step 1: pull a finished Sim run and normalize it to tool calls + final answer.

Sources, in order:
  1. A local fixture file  <CROSSCHECK_FIXTURES>/<run_id>.json  (same shape as the Sim log detail)
  2. The Sim Logs API      GET {SIM_BASE_URL}/api/v2/logs/{run_id}   (X-API-Key: SIM_API_KEY)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ANSWER_KEYS = ("content", "answer", "result", "output", "text", "response")


@dataclass
class ToolCall:
    span_id: str
    name: str
    input: Any
    output: Any


@dataclass
class Run:
    run_id: str
    tool_calls: list[ToolCall]
    final_answer: str
    workflow: str = ""
    raw: dict = field(default_factory=dict, repr=False)


def fetch_run(run_id: str) -> Run:
    fixtures = os.getenv("CROSSCHECK_FIXTURES")
    if fixtures:
        path = Path(fixtures) / f"{run_id}.json"
        if path.exists():
            return parse_log(json.loads(path.read_text(encoding="utf-8")))
    base = os.getenv("SIM_BASE_URL", "http://localhost:3000").rstrip("/")
    key = os.getenv("SIM_API_KEY")
    if not key:
        raise LookupError(f"run {run_id} not in fixtures and SIM_API_KEY is not set")
    resp = httpx.get(f"{base}/api/v2/logs/{run_id}", headers={"X-API-Key": key}, timeout=30)
    resp.raise_for_status()
    return parse_log(resp.json())


def parse_log(payload: dict) -> Run:
    """Accepts a Sim log-detail response ({"data": {...}}) or the bare detail object."""
    data = payload.get("data", payload)
    calls: list[ToolCall] = []
    for span in data.get("traceSpans") or []:
        _walk(span, calls)
    workflow = (data.get("workflow") or {}).get("name", "")
    return Run(
        run_id=data.get("runId") or data.get("executionId") or "",
        tool_calls=calls,
        final_answer=_answer_text(data.get("finalOutput")),
        workflow=workflow,
        raw=data,
    )


def _walk(span: dict, calls: list[ToolCall]) -> None:
    sid = span.get("id", "")
    # Agent blocks record tool use as toolCalls on the span.
    for i, tc in enumerate(span.get("toolCalls") or []):
        if tc.get("error"):
            continue
        calls.append(ToolCall(
            span_id=tc.get("id") or f"{sid}#tool{i}",
            name=tc.get("name", "tool"),
            input=tc.get("arguments"),
            output=_maybe_json(tc.get("result")),
        ))
    # Standalone tool/integration blocks (API, function, Tavily, ...) are their own spans.
    if span.get("type") not in (None, "agent", "workflow", "starter", "start", "response", "evaluator") \
            and span.get("output") is not None and not span.get("toolCalls"):
        calls.append(ToolCall(span_id=sid, name=span.get("name", span.get("type", "block")),
                              input=span.get("input"), output=_maybe_json(span.get("output"))))
    for child in span.get("children") or []:
        _walk(child, calls)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "[{":
            try:
                return json.loads(s)
            except ValueError:
                pass
    return value


def _answer_text(final: Any) -> str:
    if final is None:
        return ""
    if isinstance(final, str):
        return final
    if isinstance(final, dict):
        for k in ANSWER_KEYS:
            if isinstance(final.get(k), str):
                return final[k]
            if isinstance(final.get(k), dict):
                return _answer_text(final[k])
    return json.dumps(final)
