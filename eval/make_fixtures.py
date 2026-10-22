"""Writes the 20-run eval set as Sim log-detail JSON (GET /api/v2/logs/{runId} shape) plus answer_key.csv.

Three agents, as in the plan: numbers (counts/prices/revenue), lookup (names/dates/statuses,
incl. a Checkr-style background check), text (Tavily search + summary). Half the runs carry a
planted mismatch: the answer misreports a value its own tool returned.
To evaluate on real runs instead, use `python -m crosscheck pull` and edit answer_key.csv.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

OUT = Path(__file__).parent / "runs"

ORDERS = [
    {"order_id": "ORD-3101", "customer": "Acme Corp", "amount": 412.00, "qty": 4, "status": "shipped"},
    {"order_id": "ORD-3102", "customer": "Globex", "amount": 289.50, "qty": 2, "status": "shipped"},
    {"order_id": "ORD-3103", "customer": "Initech", "amount": 515.25, "qty": 5, "status": "processing"},
    {"order_id": "ORD-3104", "customer": "Umbrella", "amount": 198.75, "qty": 1, "status": "shipped"},
    {"order_id": "ORD-3105", "customer": "Hooli", "amount": 427.00, "qty": 3, "status": "delivered"},
]  # sum 1842.50, avg 368.50, 5 orders, 3 shipped
PLANS = {"plans": [{"plan": "Starter", "price_monthly": 19}, {"plan": "Pro", "price_monthly": 49},
                   {"plan": "Team", "price_monthly": 199}]}
SUMMARY = {"period": "2026-Q3", "total_revenue": 11870.25, "order_count": 48, "refund_rate": 0.032,
           "generated_at": "2026-10-01T08:00:00Z"}
NEWS = {"query": "Northwind Robotics funding", "results": [
    {"title": "Northwind Robotics closes Series B", "url": "https://example.com/northwind-series-b",
     "content": "Northwind Robotics announced on September 9, 2026 that it raised $42 million in Series B "
                "funding led by Harbor Ventures. The warehouse-automation startup now has 310 employees "
                "and plans to open a second plant in Ohio next year."},
    {"title": "Robotics funding roundup", "url": "https://example.com/roundup",
     "content": "Other deals this week included a $12 million seed round for Lumen Arms."}]}
CITY = {"query": "Riverton population 2026", "results": [
    {"title": "Riverton census update", "url": "https://example.com/riverton",
     "content": "Riverton's population grew 4.1% over the past year to roughly 812,000 residents, "
                "according to the county planning office's report released March 14, 2026."}]}


def tc(name, args, result):
    return {"name": name, "arguments": args, "result": result}


RUNS = [
    # ---------------- numbers agent
    ("num-01", "Numbers agent", [tc("get_orders", {"week": "2026-W40"}, {"orders": ORDERS})],
     "There were 5 orders this week totalling $1,842.50. The average order was $368.50, and 3 orders have shipped.",
     "pass", ""),
    ("num-02", "Numbers agent", [tc("get_orders", {"week": "2026-W40"}, {"orders": ORDERS})],
     "There were 7 orders this week totalling $1,842.50.",
     "flag", "order count 7 vs 5"),
    ("num-03", "Numbers agent", [tc("get_sales_summary", {"period": "2026-Q3"}, SUMMARY)],
     "Q3 revenue was about $12,000 across 48 orders, with a refund rate of 3.2%.",
     "pass", ""),
    ("num-04", "Numbers agent", [tc("get_sales_summary", {"period": "2026-Q3"}, SUMMARY)],
     "Q3 total revenue came to $14,250 across 48 orders.",
     "flag", "revenue 14,250 vs 11,870.25"),
    ("num-05", "Numbers agent", [tc("list_plans", {}, PLANS)],
     "The Pro plan costs $49 per month and the Team plan is $199 per month.",
     "pass", ""),
    ("num-06", "Numbers agent", [tc("list_plans", {}, PLANS)],
     "The Starter plan is $19 per month and the Pro plan costs $59 per month.",
     "flag", "Pro price 59 vs 49"),
    ("num-07", "Numbers agent", [tc("get_orders", {"week": "2026-W40"}, {"orders": ORDERS})],
     "This week's 5 orders had an average order value of $412.",
     "flag", "average 412 vs 368.50"),
    ("num-08", "Numbers agent",
     [tc("get_region_revenue", {"region": "North"}, {"region": "North", "revenue": 31200}),
      tc("get_region_revenue", {"region": "South"}, {"region": "South", "revenue": 27900}),
      tc("get_region_revenue", {"region": "West"}, {"region": "West", "revenue": 27300})],
     "Total revenue across the three regions was $86,400: North $31,200, South $27,900 and West $27,300.",
     "pass", ""),
    # ---------------- lookup agent
    ("look-01", "Lookup agent", [tc("lookup_order", {"order_id": "ORD-1042"},
        {"order_id": "ORD-1042", "customer": "Acme Corp", "status": "shipped",
         "shipped_date": "2026-03-03", "eta": "2026-03-07", "updated_at": "2026-03-03T17:22:10Z"})],
     "Order ORD-1042 for Acme Corp shipped on March 3, 2026 and should arrive by 2026-03-07.",
     "pass", ""),
    ("look-02", "Lookup agent", [tc("lookup_order", {"order_id": "ORD-2210"},
        {"order_id": "ORD-2210", "customer": "Globex", "status": "processing", "eta": "2026-03-12"})],
     "Order ORD-2210 for Globex has been delivered.",
     "flag", "status delivered vs processing"),
    ("look-03", "Lookup agent", [tc("lookup_account", {"account": "Globex"},
        {"account": "Globex", "manager": "Dana Kim", "renewal_date": "2026-06-30", "seats": 120})],
     "Dana Kim is the account manager for Globex. The contract renews on June 30, 2026 and covers 120 seats.",
     "pass", ""),
    ("look-04", "Lookup agent", [tc("lookup_account", {"account": "Initech"},
        {"account": "Initech", "manager": "Marcus Lee", "renewal_date": "2026-09-01", "seats": 45})],
     "Priya Patel is the account manager for Initech, which has 45 seats.",
     "flag", "manager Priya Patel vs Marcus Lee"),
    ("look-05", "Lookup agent", [tc("get_ticket", {"id": "TCK-88"},
        {"ticket": "TCK-88", "title": "SSO login loop", "status": "open", "priority": "high",
         "assignee": "Sam Ortiz", "due_date": "2026-04-15"})],
     "Ticket TCK-88 (SSO login loop) is open and due on April 12, 2026.",
     "flag", "due date Apr 12 vs Apr 15"),
    ("look-06", "Lookup agent", [tc("checkr_get_report", {"candidate_id": "cand_771"},
        {"candidate": "Lena Fischer", "report_id": "rpt_5521", "status": "complete", "result": "clear",
         "completed_at": "2026-02-18"})],
     "The background check for Lena Fischer is complete and came back clear on 2026-02-18.",
     "pass", ""),
    ("look-07", "Lookup agent", [tc("checkr_get_report", {"candidate_id": "cand_812"},
        {"candidate": "Omar Haddad", "report_id": "rpt_5590", "status": "complete", "result": "consider",
         "completed_at": "2026-02-20"})],
     "The background check for Omar Haddad came back clear.",
     "flag", "result clear vs consider"),
    # ---------------- text agent (Tavily search -> summary)
    ("text-01", "Text agent", [tc("tavily_search", {"query": "Northwind Robotics funding"}, NEWS)],
     "Northwind Robotics raised $42 million in a Series B led by Harbor Ventures and has about 300 employees.",
     "pass", ""),
    ("text-02", "Text agent", [tc("tavily_search", {"query": "Northwind Robotics funding"}, NEWS)],
     "Northwind Robotics raised $52 million in Series B funding, announced on September 9, 2026.",
     "flag", "raise 52M vs 42M"),
    ("text-03", "Text agent", [tc("tavily_search", {"query": "Riverton population 2026"}, CITY)],
     "Riverton's population grew 4.1% to around 812,000 residents, per a report released March 14, 2026.",
     "pass", ""),
    ("text-04", "Text agent", [tc("tavily_search", {"query": "Northwind Robotics funding"}, NEWS)],
     "Northwind Robotics' Series B was led by Summit Capital.",
     "flag", "lead investor Summit Capital vs Harbor Ventures"),
    ("text-05", "Text agent", [tc("tavily_search", {"query": "Northwind Robotics funding"}, NEWS)],
     "Northwind Robotics plans to open a second plant in Ohio next year.",
     "pass", ""),
]


def sim_log(run_id: str, workflow: str, calls: list[dict], answer: str) -> dict:
    t = "2026-10-22T14:00:00.000Z"
    tool_calls = [{"id": f"{run_id}-tool-{i}", "startTime": t, "endTime": t, "duration": 180, **c}
                  for i, c in enumerate(calls)]
    return {"data": {
        "runId": run_id, "workflowId": f"wf-{workflow.split()[0].lower()}", "status": "completed",
        "level": "info", "trigger": "api", "startedAt": t, "endedAt": "2026-10-22T14:00:04.000Z",
        "totalDurationMs": 4000,
        "workflow": {"id": f"wf-{workflow.split()[0].lower()}", "name": workflow},
        "traceSpans": [
            {"id": f"{run_id}-start", "name": "Start", "type": "starter", "status": "success",
             "output": {"input": "user question"}},
            {"id": f"{run_id}-agent", "name": "Agent 1", "type": "agent", "status": "success",
             "duration": 3600, "toolCalls": tool_calls,
             "output": {"content": answer, "model": "claude-sonnet-5-5"},
             "tokens": {"input": 1500, "output": 120, "total": 1620}},
        ],
        "finalOutput": {"content": answer, "model": "claude-sonnet-5-5"},
        "cost": {"total": 0.0081},
    }}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(Path(__file__).parent / "answer_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "workflow", "expected_verdict", "planted_mismatch"])
        for rid, wf, calls, answer, expected, note in RUNS:
            (OUT / f"{rid}.json").write_text(json.dumps(sim_log(rid, wf, calls, answer), indent=2), encoding="utf-8")
            w.writerow([rid, wf, expected, note])
    print(f"wrote {len(RUNS)} runs to {OUT}")


if __name__ == "__main__":
    main()
