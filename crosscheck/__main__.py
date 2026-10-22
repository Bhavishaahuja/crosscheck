"""python -m crosscheck check <run_id> [--no-llm]
   python -m crosscheck pull --workspace <id> [--limit 20] [--out eval/runs]   (save real Sim runs as fixtures)"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

from .core import check_run


def pull(workspace: str, limit: int, out: str) -> None:
    base = os.getenv("SIM_BASE_URL", "http://localhost:3000").rstrip("/")
    headers = {"X-API-Key": os.environ["SIM_API_KEY"]}
    listing = httpx.get(f"{base}/api/v2/logs", headers=headers, timeout=30,
                        params={"workspaceId": workspace, "limit": limit}).json()
    Path(out).mkdir(parents=True, exist_ok=True)
    for item in listing.get("data", []):
        rid = item["runId"]
        detail = httpx.get(f"{base}/api/v2/logs/{rid}", headers=headers, timeout=30).json()
        Path(out, f"{rid}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        print("saved", rid)


def main() -> None:
    p = argparse.ArgumentParser(prog="crosscheck")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("run_id")
    c.add_argument("--no-llm", action="store_true")
    pl = sub.add_parser("pull")
    pl.add_argument("--workspace", required=True)
    pl.add_argument("--limit", type=int, default=20)
    pl.add_argument("--out", default="eval/runs")
    a = p.parse_args()
    if a.cmd == "check":
        print(json.dumps(check_run(a.run_id, use_llm=False if a.no_llm else None), indent=2, default=str))
    else:
        pull(a.workspace, a.limit, a.out)


if __name__ == "__main__":
    main()
