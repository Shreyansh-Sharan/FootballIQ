"""Deterministic checks on the final answer before anyone sees it.

1. Grounding: every number in the answer must appear in the evidence (tool outputs + specialist reports), allowing for
   rounding and for probabilities written as percentages (0.231 -> 23.1% / 23%).
2. No future: a minute mentioned in the answer may not be later than the current minute.
3. Neutral sources: no data-provider or vendor names (they are replaced and reported).
"""

from __future__ import annotations

import re
from typing import Iterable

from footballiq.agents.orchestrator.models import Verification

NUM = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(\s*%|\s*(?:per\s*cent|प्रतिशत|por\s*ciento))?")
MINUTE = re.compile(r"(?<![\w.])(\d{1,3})(?:\s*\+\s*(\d{1,2}))?\s*['′’]")
FORMATION = re.compile(r"\b\d(?:-\d){2,4}\b")
SCORE = re.compile(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\b")
VERSION = re.compile(r"\bv?\d{8,}(?:-c\d{8})?\b")
PROVIDERS = [(re.compile(r"StatsBomb", re.I), "event data"), (re.compile(r"\bPFF\b(\s*FC)?", re.I), "tracking"),
             (re.compile(r"SkillCorner", re.I), "tracking"), (re.compile(r"\bIDSSE\b", re.I), "tracking")]
TOL_ABS = 0.051


def _values(texts: Iterable[str]) -> set[float]:
    vals: set[float] = set()
    for t in texts:
        for m in re.finditer(r"-?\d+(?:\.\d+)?", t):
            try:
                x = abs(float(m.group()))
            except ValueError:
                continue
            vals.add(x)
            for d in (0, 1, 2):
                vals.add(round(x, d))
            if x <= 1.0:                                      # probability -> percent
                for d in (0, 1):
                    vals.add(round(100 * x, d))
    return vals


def _grounded(x: float, pct: bool, vals: set[float]) -> bool:
    if x in vals:
        return True
    cands = [x] + ([x / 100] if pct else [])
    return any(abs(c - v) <= max(TOL_ABS, 0.01 * abs(c)) for c in cands for v in vals)


def minute_value(base: str, extra: str | None) -> float:
    return int(base) + (int(extra) / 100 if extra else 0)    # 90+3 sorts after 90, before 91


def neutralise(text: str) -> tuple[str, list[str]]:
    found = []
    for rx, rep in PROVIDERS:
        if rx.search(text):
            found.append(rx.pattern)
            text = rx.sub(rep, text)
    return text, found


def verify(answer: str, evidence: Iterable[str], current_minute: float, allow: Iterable[str] = ()) -> Verification:
    ev = list(evidence)
    vals = _values(ev)
    allowed_text = "\n".join(ev) + "\n" + "\n".join(allow)
    masked = answer
    future: list[str] = []
    for m in MINUTE.finditer(answer):                         # minutes are checked for the future, not for grounding
        if minute_value(m.group(1), m.group(2)) > current_minute + 0.001:
            future.append(m.group(0).strip())
    # minutes are checked for the future (above), model versions are ids: neither is a statistic to ground
    for rx in (MINUTE, VERSION):
        masked = rx.sub(" ", masked)
    # formations ("4-3-3") and scores ("2-2") are grounded as tokens: present in the evidence as written, or every part is
    unverified: list[str] = []
    norm_text = allowed_text.replace("–", "-")
    for rx in (FORMATION, SCORE):
        for m in rx.finditer(masked):
            token = re.sub(r"\s*[-–]\s*", "-", m.group())
            if token not in norm_text and not all(float(p) in vals for p in token.split("-")):
                unverified.append(m.group())
        masked = rx.sub(" ", masked)
    checked = 0
    for m in NUM.finditer(masked):
        raw, pct = m.group(1).replace(",", "."), bool(m.group(2))
        try:
            x = float(raw)
        except ValueError:
            continue
        if x <= 1 and not pct:                               # 0 / 1 carry no claim worth checking
            continue
        checked += 1
        if not _grounded(x, pct, vals):
            unverified.append(m.group(0).strip())
    _, providers = neutralise(answer)
    issues = [f"mentions a data provider ({p})" for p in providers]
    status = "pass" if not unverified and not future and not providers else ("fail" if future else "warn")
    return Verification(status=status, numbers_checked=checked, unverified_numbers=list(dict.fromkeys(unverified)),
                        future_minutes=list(dict.fromkeys(future)), issues=issues)
