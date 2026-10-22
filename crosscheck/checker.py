"""Step 3: code-first check. Flatten tool outputs, then match every claim against
raw values, derived values (sum / average / count / min / max), or a rounding tolerance."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .claims import NUM_RE, STATUSES, Claim, parse_date, singular, tokens
from .trace import Run

SYNONYMS = {
    "total": {"sum", "total"}, "sum": {"sum", "total"}, "revenue": {"revenue", "sale", "sales", "amount"},
    "sale": {"revenue", "sale", "amount"}, "price": {"price", "cost", "amount", "unit"},
    "cost": {"price", "cost", "amount"}, "amount": {"amount", "price", "total", "revenue"},
    "average": {"avg", "average", "mean"}, "avg": {"avg", "average", "mean"}, "mean": {"avg", "average", "mean"},
    "count": {"count", "number"}, "number": {"count", "number"}, "qty": {"qty", "quantity", "unit"},
    "quantity": {"qty", "quantity", "unit"}, "unit": {"qty", "quantity", "unit"},
    "due": {"due", "deadline"}, "deadline": {"due", "deadline"}, "owner": {"owner", "assignee", "manager"},
    "assignee": {"owner", "assignee"}, "manager": {"owner", "manager"},
}
NAME_KEYS = ("name", "owner", "assignee", "customer", "contact", "manager", "author", "vendor", "company", "candidate")
STATUS_KEYS = ("status", "state", "result", "stage")
AGG = {"sum", "total", "average", "avg", "mean", "count", "min", "max"}
# Statuses that can sit on the same field. A record can have several status-like fields
# (Checkr: status=complete, result=clear); a claim is compared with the field from its family.
STATUS_FAMILIES = [
    {"clear", "consider", "flagged", "suspended"},
    {"pending", "processing", "complete", "completed", "in progress", "open", "closed", "resolved",
     "escalated", "on hold", "cancelled", "failed", "expired"},
    {"shipped", "delivered", "processing", "backordered", "cancelled", "pending"},
    {"paid", "unpaid", "overdue", "refunded"},
    {"active", "inactive", "suspended", "expired"},
    {"approved", "rejected", "pending"},
    {"in stock", "out of stock", "backordered"},
]


def _family(a: str, b: str) -> bool:
    return any(a in f and b in f for f in STATUS_FAMILIES)


@dataclass
class Value:
    span_id: str
    tool: str
    key: str                  # human-readable path, e.g. "orders[].amount" or "sum of orders[].amount"
    value: Any
    derived: bool = False
    words: set[str] = field(default_factory=set)


@dataclass
class Record:
    span_id: str
    tool: str
    path: str
    fields: dict[str, Any]
    anchors: list[str]        # identifying strings: ids, names


@dataclass
class Finding:
    claim: Claim
    verdict: str              # match | mismatch | unverified  (LLM adds: supported | contradicted | not_enough_info)
    expected: Any = None
    span_id: str | None = None
    evidence: str = ""
    checked_by: str = "code"

    def to_dict(self) -> dict:
        return {
            "claim": self.claim.text, "kind": self.claim.kind, "sentence": self.claim.sentence.strip(),
            "verdict": self.verdict, "expected": self.expected, "actual": self.claim.text,
            "span_id": self.span_id, "evidence": self.evidence, "checked_by": self.checked_by,
        }


# ---------------------------------------------------------------- flattening

def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*[$€£]?\s?(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s?%?\s*", v)
        if m:
            return float(m[1].replace(",", ""))
    return None


def _key_words(key: str) -> set[str]:
    return set(tokens(key.replace("[]", " ").replace(".", " ").replace("_", " ")))


def _is_id_key(key: str) -> bool:
    last = key.split(".")[-1].replace("[]", "")
    low = last.lower()
    return low in ("id", "uuid", "sku", "zip", "phone", "year") or low.endswith(("_id", "-id")) or last.endswith("Id")


class Index:
    def __init__(self, run: Run):
        self.numbers: list[Value] = []
        self.dates: list[Value] = []
        self.strings: list[Value] = []
        self.records: list[Record] = []
        for tc in run.tool_calls:
            self._flatten(tc.output, tc.span_id, tc.name, "")
        self._cross_tool_totals()

    def _add_num(self, span, tool, key, val, derived=False):
        if not derived and _is_id_key(key):
            return
        self.numbers.append(Value(span, tool, key, val, derived, _key_words(key)))

    def _flatten(self, obj: Any, span: str, tool: str, path: str) -> None:
        if isinstance(obj, dict):
            scal = {k: v for k, v in obj.items() if not isinstance(v, (dict, list))}
            if scal:
                anchors = [str(v) for k, v in scal.items()
                           if isinstance(v, str) and len(v) >= 3 and _num(v) is None and parse_date(v) is None
                           and v.lower() not in STATUSES and len(v) <= 60]
                self.records.append(Record(span, tool, path or "$", scal, anchors))
            for k, v in obj.items():
                self._flatten(v, span, tool, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            self._derive(obj, span, tool, path)
            for v in obj:
                self._flatten(v, span, tool, f"{path}[]")
        else:
            self._leaf(obj, span, tool, path)

    def _leaf(self, v: Any, span: str, tool: str, key: str) -> None:
        n = _num(v)
        if n is not None:
            self._add_num(span, tool, key, n)
            if isinstance(v, str) and "%" in v:
                self._add_num(span, tool, key, n / 100)
            return
        if not isinstance(v, str):
            return
        d = parse_date(v.strip())
        if d:
            self.dates.append(Value(span, tool, key, d, words=_key_words(key)))
            return
        self.strings.append(Value(span, tool, key, v, words=_key_words(key)))
        if len(v) > 40:          # free text (search results, descriptions): mine numbers and dates with nearby words
            self._mine_text(v, span, tool, key)

    def _mine_text(self, text: str, span: str, tool: str, key: str) -> None:
        from .claims import extract_claims
        for c in extract_claims(text):
            if c.kind == "number":
                words = set(c.label) | _key_words(key)
                self.numbers.append(Value(span, tool, f"{key} (text: '{c.text}')", c.value, False, words))
                if c.percent:
                    self.numbers.append(Value(span, tool, f"{key} (text: '{c.text}')", c.value / 100, False, words))
            elif c.kind == "date":
                self.dates.append(Value(span, tool, f"{key} (text)", c.value, words=set(c.label)))

    def _derive(self, items: list, span: str, tool: str, path: str) -> None:
        listname = path.split(".")[-1].replace("[]", "") or "items"
        self._add_num(span, tool, f"count of {path or 'list'}", float(len(items)), derived=True)
        nums = [_num(x) for x in items]
        if items and all(n is not None for n in nums):
            self._aggs(nums, span, tool, path or "list")
        if items and all(isinstance(x, dict) for x in items):
            keys = set().union(*(x.keys() for x in items))
            for k in keys:
                vals = [_num(x.get(k)) for x in items]
                vals = [v for v in vals if v is not None]
                if len(vals) >= 2 and not _is_id_key(k):
                    self._aggs(vals, span, tool, f"{path}[].{k}")
                strs = [x.get(k) for x in items if isinstance(x.get(k), str)]
                if strs and len(set(strs)) < len(strs):
                    for val, cnt in Counter(s.lower() for s in strs).items():
                        self._add_num(span, tool, f"count of {listname} with {k}={val}", float(cnt), derived=True)
                        self.numbers[-1].words |= {singular(w) for w in tokens(val)}

    def _aggs(self, vals: list[float], span: str, tool: str, key: str) -> None:
        for agg, v in (("sum", sum(vals)), ("average", sum(vals) / len(vals)),
                       ("min", min(vals)), ("max", max(vals))):
            self._add_num(span, tool, f"{agg} of {key}", v, derived=True)
            self.numbers[-1].words |= {agg} | SYNONYMS.get(agg, set())

    def _cross_tool_totals(self) -> None:
        """Agents often add values across several tool calls (e.g. revenue from 3 regions)."""
        groups: dict[str, list[Value]] = defaultdict(list)
        for v in self.numbers:
            if not v.derived and "(text" not in v.key:
                groups[v.key.split(".")[-1].replace("[]", "")].append(v)
        for k, vs in groups.items():
            spans = {v.span_id for v in vs}
            if len(spans) >= 2:
                self._aggs([v.value for v in vs], "+".join(sorted(spans)), "multiple tools", f"all {k}")


# ---------------------------------------------------------------- matching

def num_close(c: Claim, v: float) -> bool:
    targets = [v]
    if c.percent:
        targets.append(v * 100)
    tol = 0.5 * (10 ** -c.decimals) * c.scale + 1e-9
    for t in targets:
        err = abs(c.value - t)
        if err <= tol:
            return True
        if c.approx and err <= max(0.05 * abs(t), tol):
            return True
    return False


def _expand(words: list[str] | set[str]) -> set[str]:
    out = set()
    for w in words:
        out |= {w} | SYNONYMS.get(w, set())
    return out


def _score(label: set[str], v: Value) -> int:
    return len(label & _expand(v.words))


def _anchored(c: Claim, idx: Index) -> list[Record]:
    sent = c.sentence.lower()
    hits = []
    for r in idx.records:
        best = None
        for a in r.anchors:
            pos = sent.find(a.lower())
            if pos >= 0:
                dist = abs(pos - (c.start - _sent_start(c)))
                best = dist if best is None else min(best, dist)
        if best is not None:
            hits.append((best, r))
    hits.sort(key=lambda h: h[0])
    return [r for _, r in hits]


def _sent_start(c: Claim) -> int:
    # Claim.start is an offset into the full answer; recover the sentence start offset.
    rel = c.sentence.find(c.text)
    return c.start - rel if rel >= 0 else c.start


def check_number(c: Claim, idx: Index) -> Finding:
    label = _expand(c.label)
    anchored = _anchored(c, idx)
    # 1. a field on a record named in the same sentence (ORD-1042 ... $129.50)
    for rec in anchored[:1]:
        cands = [(k, _num(v)) for k, v in rec.fields.items() if _num(v) is not None and not _is_id_key(k)]
        scored = sorted(((len(label & _expand(_key_words(k))), k, v) for k, v in cands), reverse=True)
        if scored and scored[0][0] > 0:
            for s, k, v in scored:
                if s == scored[0][0] and num_close(c, v):
                    return Finding(c, "match", v, rec.span_id, f"{rec.path}.{k}")
            _, k, v = scored[0]
            if not any(num_close(c, x.value) for x in idx.numbers if _score(label, x) >= scored[0][0]):
                return Finding(c, "mismatch", v, rec.span_id, f"{rec.path}.{k}")
    # 2. any raw or derived value whose key shares words with the claim's label
    scored = sorted(((_score(label, v), v) for v in idx.numbers), key=lambda t: -t[0])
    top = scored[0][0] if scored else 0
    if top > 0:
        cands = [v for s, v in scored if s == top]
        for v in cands:
            if num_close(c, v.value):
                return Finding(c, "match", v.value, v.span_id, v.key)
        # a lower-scored labelled value that matches is still support, unless the claim names an
        # aggregate ("average order value") and that value is a raw one (a single order's amount)
        wants_agg = bool(label & AGG)
        for s, v in scored:
            if wants_agg and not (v.words & AGG):
                continue
            if s > 0 and num_close(c, v.value):
                return Finding(c, "match", v.value, v.span_id, v.key)
        if any(num_close(c, v.value) for v in idx.numbers if not wants_agg or v.words & AGG):
            return Finding(c, "unverified", None, None, "value appears in tool output under an unrelated key")
        best = min(cands, key=lambda v: abs(v.value - c.value))
        return Finding(c, "mismatch", best.value, best.span_id, best.key)
    # 3. no label overlap: any value at all
    for v in idx.numbers:
        if num_close(c, v.value):
            return Finding(c, "match", v.value, v.span_id, v.key)
    return Finding(c, "unverified")


def check_date(c: Claim, idx: Index) -> Finding:
    def same(a: str, b: str) -> bool:
        return a == b or (a.startswith("--") and b.endswith(a[1:])) or (b.startswith("--") and a.endswith(b[1:]))
    label = _expand(c.label)
    for rec in _anchored(c, idx)[:1]:
        ds = [(k, parse_date(str(v))) for k, v in rec.fields.items() if isinstance(v, str)]
        ds = [(k, d) for k, d in ds if d]
        if ds:
            for k, d in ds:
                if same(c.value, d):
                    return Finding(c, "match", d, rec.span_id, f"{rec.path}.{k}")
            k, d = max(ds, key=lambda kd: len(label & _expand(_key_words(kd[0]))))
            return Finding(c, "mismatch", d, rec.span_id, f"{rec.path}.{k}")
    for v in idx.dates:
        if same(c.value, v.value):
            return Finding(c, "match", v.value, v.span_id, v.key)
    scored = sorted(idx.dates, key=lambda v: -_score(label, v))
    if scored and _score(label, scored[0]) > 0:
        return Finding(c, "mismatch", scored[0].value, scored[0].span_id, scored[0].key)
    return Finding(c, "unverified")


def check_status(c: Claim, idx: Index) -> Finding:
    norm = lambda s: s.lower().replace("canceled", "cancelled")  # noqa: E731
    for rec in _anchored(c, idx)[:1]:
        fields = [(k, v) for k, v in rec.fields.items() if isinstance(v, str) and (
            any(s in k.lower() for s in STATUS_KEYS) or norm(v) in STATUSES)]
        for k, v in fields:
            if norm(v) == c.value:
                return Finding(c, "match", v, rec.span_id, f"{rec.path}.{k}")
        same_family = [(k, v) for k, v in fields if _family(norm(v), c.value)]
        if same_family:
            k, v = same_family[0]
            return Finding(c, "mismatch", v, rec.span_id, f"{rec.path}.{k}")
    for v in idx.strings:
        if v.value.lower().replace("canceled", "cancelled") == c.value:
            return Finding(c, "match", v.value, v.span_id, v.key)
    return Finding(c, "unverified")


def check_name(c: Claim, idx: Index) -> Finding:
    for v in idx.strings:
        if c.value in v.value.lower():
            return Finding(c, "match", v.value, v.span_id, v.key)
    label = _expand(c.label)
    for rec in _anchored(c, idx)[:1]:
        for k, v in rec.fields.items():
            if isinstance(v, str) and any(n in k.lower() for n in NAME_KEYS) and (label & _expand(_key_words(k))):
                return Finding(c, "mismatch", v, rec.span_id, f"{rec.path}.{k}")
    return Finding(c, "unverified")


CHECKS = {"number": check_number, "date": check_date, "status": check_status, "name": check_name}


def code_check(claims: list[Claim], run: Run) -> list[Finding]:
    idx = Index(run)
    return [CHECKS[c.kind](c, idx) for c in claims]
