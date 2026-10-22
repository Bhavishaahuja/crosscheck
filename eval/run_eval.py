"""Score Crosscheck against eval/answer_key.csv and write eval/results.md + results.json.

python eval/run_eval.py            # code check + LLM fallback (needs ANTHROPIC_API_KEY)
python eval/run_eval.py --no-llm   # code check only
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("CROSSCHECK_FIXTURES", str(HERE / "runs"))

from crosscheck import check_run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    use_llm = False if a.no_llm else None

    rows = list(csv.DictReader(open(HERE / "answer_key.csv", encoding="utf-8")))
    reports, lines = [], []
    for row in rows:
        r = check_run(row["run_id"], use_llm=use_llm)
        r["expected"] = row["expected_verdict"]
        reports.append(r)
        ok = "ok " if r["verdict"] == r["expected"] else "XX "
        lines.append(f"{ok}{row['run_id']:<8} expected={r['expected']:<5} got={r['verdict']:<6} "
                     f"claims={r['stats']['claims']} code={r['stats']['checked_by_code']} "
                     f"llm={r['stats']['sent_to_llm']}")
        for f in r["flags"]:
            lines.append(f"      flag: '{f['actual']}' vs expected {f['expected']!r} [{f['span_id']} {f['evidence']}]")
        if r["verdict"] != r["expected"]:
            for f in r["findings"]:
                if f["verdict"] not in ("match", "supported"):
                    lines.append(f"      {f['verdict']}: {f['kind']} '{f['claim']}' ({f['checked_by']}) {f['evidence']}")

    planted = [r for r in reports if r["expected"] == "flag"]
    clean = [r for r in reports if r["expected"] == "pass"]
    claims = sum(r["stats"]["claims"] for r in reports)
    by_code = sum(r["stats"]["checked_by_code"] for r in reports)
    to_llm = sum(r["stats"]["sent_to_llm"] for r in reports)
    unresolved_claims = sum(r["stats"]["unresolved"] for r in reports)
    llm_runs = [r for r in reports if r["stats"]["llm"]["calls"]]
    n = len(reports)
    summary = {
        "mode": "code only" if a.no_llm or not llm_runs else "code + LLM fallback",
        "runs_evaluated": n,
        "planted_caught": f"{sum(r['verdict'] == 'flag' for r in planted)} of {len(planted)}",
        "planted_unsure": sum(r["verdict"] == "unsure" for r in planted),
        "false_alarms_on_clean": f"{sum(r['verdict'] == 'flag' for r in clean)} of {len(clean)}",
        "clean_unsure": sum(r["verdict"] == "unsure" for r in clean),
        "claims_total": claims,
        "claims_checked_by_code": f"{by_code} ({by_code / claims:.0%})",
        "claims_sent_to_llm": f"{to_llm} ({to_llm / claims:.0%})",
        "claims_left_unresolved": unresolved_claims,
        "added_latency_per_run_s": round(sum(r["stats"]["latency_s"] for r in reports) / n, 3),
        "added_cost_per_run_usd": round(sum(r["stats"]["llm"]["cost_usd"] for r in reports) / n, 6),
        "llm_model": os.getenv("CROSSCHECK_MODEL", "claude-haiku-5-5") if llm_runs else None,
    }
    print("\n".join(lines))
    print(json.dumps(summary, indent=2))

    table = "\n".join([
        f"Mode: **{summary['mode']}**" + (f" (`{summary['llm_model']}`)" if summary["llm_model"] else ""), "",
        "| Measure | Result |", "|---|---|",
        f"| Runs evaluated | {n} |",
        f"| Planted mismatches caught | {summary['planted_caught']} |",
        f"| False alarms on clean runs | {summary['false_alarms_on_clean']} |",
        f"| Claims checked by code | {summary['claims_checked_by_code']} |",
        f"| Claims sent to the LLM | {summary['claims_sent_to_llm']} |",
        f"| Added latency per run (s) | {summary['added_latency_per_run_s']} |",
        f"| Added cost per run (USD) | {summary['added_cost_per_run_usd']} |",
        "", "```", *lines, "```", ""])
    suffix = "code_only" if summary["mode"] == "code only" else "llm"
    (HERE / f"results_{suffix}.md").write_text(table, encoding="utf-8")
    (HERE / f"results_{suffix}.json").write_text(json.dumps({"summary": summary, "runs": reports}, indent=2,
                                                            default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
