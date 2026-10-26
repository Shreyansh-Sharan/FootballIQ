"""Per-match extraction workers for the P4 notebooks (importable, so a process pool can run them)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from footballiq.ingest import statsbomb as sb
from footballiq.ml import train as T
from footballiq.ml import windows as WN
from footballiq.ml import xt as XT


@dataclass(frozen=True)
class MatchRef:
    split: str          # "train" | "test"
    competition: str    # "<competition_id>_<season_id>"
    match_id: int
    events: str
    lineups: str
    matches: str


def _read(path: str) -> Any:
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data) if path.endswith(".gz") else data)


@lru_cache(maxsize=256)
def _matches(path: str) -> list[dict[str, Any]]:
    return _read(path)


def match_meta(ref: MatchRef) -> dict[str, Any]:
    """Date and team names of a match from its season's matches.json (no events needed)."""
    m = next(x for x in _matches(ref.matches) if x["match_id"] == ref.match_id)
    return {"date": m["match_date"], "home": m["home_team"]["home_team_name"], "away": m["away_team"]["away_team_name"]}


def priors_for(ref: MatchRef, ratings) -> dict[str, dict[str, float]]:
    """Strength features per canonical team id, from results strictly before the match date."""
    from footballiq.ml.strength import prior_features
    m = match_meta(ref)
    h, a = sb.slugify(m["home"]), sb.slugify(m["away"])
    return {h: prior_features(ratings, m["home"], m["away"], m["date"]),
            a: prior_features(ratings, m["away"], m["home"], m["date"])}


def load_raw(ref: MatchRef) -> dict[str, Any]:
    return {"matches": _matches(ref.matches), "events": _read(ref.events), "lineups": _read(ref.lineups), "three_sixty": []}


def extract_actions(ref: MatchRef):
    """Shot / pass feature rows (+ xT counts for training matches)."""
    raw = load_raw(ref)
    shots, passes = T.action_rows(str(ref.match_id), raw["events"])
    for r in shots + passes:
        r["competition"] = ref.competition
    return ref, shots, passes, (XT.counts(raw["events"]) if ref.split == "train" else None)


def extract_windows(args: tuple):
    """Window examples for one match from (ref, xg by event id, step_s[, priors by team])."""
    ref, xg, step_s, *rest = args
    raw = load_raw(ref)
    match, events, _ = sb.normalize_match(raw, ref.match_id)
    rows = WN.examples(match, events, xg, step_s=step_s, priors=rest[0] if rest else None)
    for r in rows:
        r["competition"] = ref.competition
        r["sb_match_id"] = str(ref.match_id)
    return ref, rows
