import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crosscheck import check_run, parse_log  # noqa: E402
from crosscheck.claims import extract_claims  # noqa: E402


def run_with(output, answer, name="tool"):
    return parse_log({"data": {"runId": "t", "traceSpans": [{
        "id": "agent", "type": "agent",
        "toolCalls": [{"id": "s1", "name": name, "arguments": {}, "result": output}]}],
        "finalOutput": {"content": answer}}})


def verdict(output, answer):
    return check_run(run_with(output, answer), use_llm=False)


# ---------- extraction

def test_extracts_kinds():
    kinds = {c.kind for c in extract_claims('Order ORD-9 for "Acme Corp" shipped on 2026-01-05 for $1,200.50.')}
    assert kinds == {"name", "status", "date", "number"}


def test_ids_are_not_numbers():
    assert not [c for c in extract_claims("Ticket TCK-88 and order #4411 are linked.") if c.kind == "number"]


def test_approx_and_suffix():
    c = [c for c in extract_claims("Revenue was about $1.2M.") if c.kind == "number"][0]
    assert c.approx and c.value == 1_200_000


# ---------- code check (cases written after the eval set, not tuned on)

def test_rounded_display_value_passes():
    assert verdict({"avg_rating": 4.27}, "The average rating is 4.3.")["verdict"] == "pass"


def test_about_tolerance():
    assert verdict({"visitors": 1187}, "We had about 1,200 visitors.")["verdict"] == "pass"


def test_sum_of_list_passes_and_wrong_sum_flags():
    out = {"invoices": [{"amount": 100}, {"amount": 250.5}, {"amount": 49.5}]}
    assert verdict(out, "The invoices total $400.")["verdict"] == "pass"
    r = verdict(out, "The invoices total $450.")
    assert r["verdict"] == "flag" and r["flags"][0]["expected"] == 400


def test_percent_vs_fraction():
    assert verdict({"churn_rate": 0.054}, "Churn rate was 5.4%.")["verdict"] == "pass"
    assert verdict({"churn_rate": 0.054}, "Churn rate was 7.4%.")["verdict"] == "flag"


def test_count_by_status():
    out = {"tickets": [{"id": "A-1", "status": "open"}, {"id": "A-2", "status": "open"},
                       {"id": "A-3", "status": "closed"}]}
    assert verdict(out, "There are 2 open tickets.")["verdict"] == "pass"


def test_status_mismatch_names_expected_and_span():
    r = verdict({"invoice": "INV-7", "status": "unpaid"}, "Invoice INV-7 is paid.")
    assert r["verdict"] == "flag"
    f = r["flags"][0]
    assert f["expected"] == "unpaid" and f["span_id"] == "s1"


def test_unknown_name_is_unsure_without_llm():
    assert verdict({"vendor": "Contoso"}, "The vendor is Fabrikam Industries.")["verdict"] == "unsure"


# ---------- LLM fallback (mocked client): forced tool use, only unverified claims sent

def test_llm_fallback(monkeypatch):
    import anthropic
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            block = SimpleNamespace(type="tool_use", input={"verdicts": [
                {"claim_id": 0, "verdict": "contradicted", "expected": "Contoso", "reason": "tool says Contoso"}]})
            return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=300, output_tokens=40))

    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(messages=FakeMessages()))
    r = check_run(run_with({"vendor": "Contoso", "total": 90}, "The vendor is Fabrikam Industries, total $90."),
                  use_llm=True, model="claude-haiku-5-5")
    assert r["verdict"] == "flag"
    assert sent["tool_choice"] == {"type": "tool", "name": "record_verdicts"}
    claims_block = sent["messages"][0]["content"].split("Claims to check:")[1]
    assert '0. [name] "Fabrikam Industries"' in claims_block and "\n1." not in claims_block
    assert r["stats"]["sent_to_llm"] == 1 and r["stats"]["checked_by_code"] == 1
    assert r["stats"]["llm"]["cost_usd"] == pytest.approx((300 * 0.10 + 40 * 0.50) / 1e6)


# ---------- API

def test_api_check_inline_log(monkeypatch):
    from fastapi.testclient import TestClient

    from crosscheck.api import app
    log = json.loads((ROOT / "eval/runs/num-02.json").read_text())
    r = TestClient(app).post("/check", json={"log": log, "use_llm": False, "alert": False}).json()
    assert r["verdict"] == "flag" and r["flags"][0]["expected"] == 5


def test_api_fetches_by_run_id_and_alerts_slack(monkeypatch):
    from fastapi.testclient import TestClient

    import crosscheck.alert as alert
    from crosscheck.api import app
    posted = []
    monkeypatch.setenv("CROSSCHECK_FIXTURES", str(ROOT / "eval/runs"))
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.setattr(alert.httpx, "post", lambda url, json, timeout: posted.append(json) or
                        SimpleNamespace(raise_for_status=lambda: None))
    r = TestClient(app).post("/check", json={"run_id": "look-02", "use_llm": False}).json()
    assert r["alerts"] == ["slack"] and "processing" in posted[0]["text"]
