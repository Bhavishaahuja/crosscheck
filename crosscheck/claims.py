"""Step 2: pull checkable claims (numbers, dates, statuses, names) out of the final answer."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9

STATUSES = {
    "active", "inactive", "pending", "shipped", "delivered", "cancelled", "canceled", "failed",
    "completed", "complete", "open", "closed", "approved", "rejected", "paid", "unpaid", "overdue",
    "refunded", "processing", "suspended", "expired", "resolved", "escalated", "in progress",
    "on hold", "backordered", "in stock", "out of stock", "clear", "consider", "flagged",
}
EVENT_STATUSES = {"shipped", "delivered", "cancelled", "canceled", "approved", "rejected", "paid", "refunded",
                  "completed", "failed", "resolved", "escalated", "expired", "backordered"}
COPULA = (r"\b(is|are|was|were|be|been|being|remains?|stays?|came back|comes back|marked(\s+as)?|"
          r"shows?(\s+as)?|listed\s+as|now|still|currently|status(\s+is|\s+of)?)\s+(\w+\s+(and\s+)?)?$")
APPROX_WORDS = ("about", "around", "approximately", "approx", "roughly", "nearly", "almost",
                "~", "over", "under", "more than", "less than", "just over", "just under", "some")
STOP = set("""a an the and or of to in on at for by with from is are was were be been this that these those
it its as has have had which who whom their there here our your my we you they he she i than then so not
no yes total about around approximately roughly nearly almost over under more less just per each""".split())
NAME_STOP = set("""The A An This That These Those It Its There Here Our Your We You They He She I In On At For
By With From Total Overall Summary Note Also However Based According Yes No Order Orders Customer Customers
Status Today Yesterday Tomorrow Monday Tuesday Wednesday Thursday Friday Saturday Sunday Each All Both If
When Of And Or To As Per Q1 Q2 Q3 Q4 Sim Tool Results Result""".split())

NUM_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}

_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RES = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ][\d:.]+Z?)?\b")),
    ("mdy", re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)),
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?(?:,?\s+(\d{{4}}))?\b", re.I)),
    ("slash", re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")),
]
# ORD-1042, A12, #4411, 3rdParty. Not 5k / 1.2M / 3rd.
ID_RE = re.compile(r"(?<![\w.])(?:[A-Za-z]+[-_#]?\d[\w-]*|\d+(?!(?:[kKMB]|MM|bn|st|nd|rd|th)\b)[A-Za-z][\w-]*|#\d+)\b")
NUM_RE = re.compile(
    r"(?P<cur>[$€£])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<suf>k|K|M|MM|B|bn|thousand|million|billion)\b)?(?P<pct>\s?%|\s?percent)?")
QUOTED_RE = re.compile(r"[\"“']([A-Z][^\"”']{1,60})[\"”']")
CAPS_RE = re.compile(r"\b([A-Z][a-zA-Z&.'-]+(?:\s+(?:[A-Z][a-zA-Z&.'-]+|&|of|de|van))+)\b")


@dataclass
class Claim:
    kind: str                 # number | date | status | name
    text: str                 # surface form in the answer
    value: object             # float | "YYYY-MM-DD" / "--MM-DD" | lowercase str
    sentence: str
    start: int = 0
    approx: bool = False
    decimals: int = 0
    scale: float = 1.0
    percent: bool = False
    label: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return f"{self.kind} '{self.text}'"


def tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-zA-Z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text)):
        w = w.lower()
        if w in STOP or len(w) < 2:
            continue
        out.append(singular(w))
    return out


def singular(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return w[:-1]
    return w


def parse_date(text: str) -> str | None:
    for kind, rx in DATE_RES:
        m = rx.search(text)
        if m and m.start() == 0 and m.end() >= len(text.strip()) - 1:
            return _date_value(kind, m)
    return None


def _date_value(kind: str, m: re.Match) -> str | None:
    try:
        if kind == "iso":
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
        elif kind == "mdy":
            mo, d, y = _month(m[1]), int(m[2]), m[3]
            y = int(y) if y else None
        elif kind == "dmy":
            d, mo, y = int(m[1]), _month(m[2]), m[3]
            y = int(y) if y else None
        else:
            mo, d, y = int(m[1]), int(m[2]), int(m[3])
        if y is None:
            date(2000, mo, d)
            return f"--{mo:02d}-{d:02d}"
        return date(y, mo, d).isoformat()
    except (ValueError, KeyError):
        return None


def _month(name: str) -> int:
    key = name.lower().rstrip(".")
    return MONTHS.get(key) or MONTHS[key[:3]]


def _sentences(text: str) -> list[tuple[int, str]]:
    out, pos = [], 0
    for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])|\n+", text):
        idx = text.find(part, pos)
        out.append((idx, part))
        pos = idx + len(part)
    return out


def _label(sentence: str, s: int, e: int) -> list[str]:
    before = tokens(sentence[max(0, s - 60):s])[-4:]
    after = tokens(sentence[e:e + 40])[:3]
    return before + after


def extract_claims(answer: str) -> list[Claim]:
    claims: list[Claim] = []
    for off, sent in _sentences(answer):
        masked = sent
        # Dates first, so their digits are not read as numbers.
        for kind, rx in DATE_RES:
            for m in rx.finditer(masked):
                val = _date_value(kind, m)
                if val:
                    claims.append(Claim("date", m.group(0), val, sent, off + m.start(),
                                        label=_label(sent, m.start(), m.end())))
                    masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
        # IDs (ORD-1042, #55, A12) are anchors, not numeric claims.
        masked = ID_RE.sub(lambda m: " " * len(m.group(0)), masked)
        for m in NUM_RE.finditer(masked):
            raw = m["num"]
            if not raw:
                continue
            pre = masked[max(0, m.start() - 20):m.start()].lower()
            # skip list markers like "1." / "2)" at line start, and step labels
            if re.match(r"^\s*\d+[.)]\s", masked[m.start():m.start() + 4]) and masked[:m.start()].strip() == "":
                continue
            suf = (m["suf"] or "").lower()
            dec = len(raw.split(".")[1]) if "." in raw else 0
            claims.append(Claim(
                "number", m.group(0).strip(), float(raw.replace(",", "")) * NUM_SUFFIX.get(suf, 1.0),
                sent, off + m.start(),
                approx=any(re.search(rf"(^|\W){re.escape(w)}\s*$", pre) for w in APPROX_WORDS),
                decimals=dec, scale=NUM_SUFFIX.get(suf, 1.0), percent=bool(m["pct"]),
                label=_label(sent, m.start(), m.end()),
            ))
        low = sent.lower()
        for st in sorted(STATUSES, key=len, reverse=True):
            for m in re.finditer(rf"\b{re.escape(st)}\b", low):
                pre = low[:m.start()]
                if re.search(r"\b(not|no longer|never|isn't|wasn't)\s+(\w+\s+)?$", pre):
                    continue
                # "open", "clear", "active"... are only statuses after a copula ("is open", "came back clear")
                # or before "status"; past-tense ones ("shipped on March 3") stand on their own.
                if st not in EVENT_STATUSES and not (re.search(COPULA, pre) or low[m.end():].lstrip().startswith("status")):
                    continue
                if any(c.kind == "status" and c.start <= off + m.start() < c.start + len(c.text) for c in claims):
                    continue
                claims.append(Claim("status", sent[m.start():m.end()], st.replace("canceled", "cancelled"),
                                    sent, off + m.start(), label=_label(sent, m.start(), m.end())))
        seen = set()
        for rx in (QUOTED_RE, CAPS_RE):
            for m in rx.finditer(sent):
                if sent[m.end():m.end() + 1].isdigit():      # "Ticket TCK-88" is an ID, not a name
                    continue
                words = re.split(r"[’']s?\s", m.group(1) + " ")[0].split()   # "Northwind Robotics' Series B" -> owner
                while words and words[0] in NAME_STOP:
                    words.pop(0)
                name = " ".join(words).strip(" .,")
                if not name or name.lower() in seen or name.lower() in MONTHS:
                    continue
                if rx is CAPS_RE and len(words) < 2:
                    continue
                if any(name.lower() in s for s in seen):
                    continue
                seen.add(name.lower())
                claims.append(Claim("name", name, name.lower(), sent, off + m.start(),
                                    label=_label(sent, m.start(), m.end())))
    return claims
