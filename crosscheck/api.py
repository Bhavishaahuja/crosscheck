"""POST /check {"run_id": "..."}  -> verdict report.

A Sim workflow calls this from an API block, either as the final block of the agent
workflow (passing <start.executionId> or similar) or from a scheduled audit workflow
that lists recent runs via GET /api/v2/logs and checks each one.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .alert import send_alerts
from .core import check_run
from .trace import parse_log

app = FastAPI(title="Crosscheck", version="0.1.0")


class CheckRequest(BaseModel):
    run_id: str | None = None
    log: dict | None = None          # optional: post the Sim log detail inline instead of fetching it
    use_llm: bool | None = None
    alert: bool = True


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/check")
def check(req: CheckRequest) -> dict:
    if not req.run_id and not req.log:
        raise HTTPException(400, "send run_id or log")
    try:
        run = parse_log(req.log) if req.log else req.run_id
        report = check_run(run, use_llm=req.use_llm)
    except LookupError as e:
        raise HTTPException(404, str(e))
    report["alerts"] = send_alerts(report) if req.alert else []
    return report
