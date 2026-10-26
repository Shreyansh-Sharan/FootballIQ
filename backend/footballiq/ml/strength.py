"""Pre-match team strength: Elo and recent form from results strictly before the match date.

Nations and clubs are separate pools; Elo follows the World Football Elo convention.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

START = 1500.0
HOME_ADV = {"nations": 100.0, "clubs": 60.0}
FORM_N = 5

# StatsBomb name -> results-feed name, where normalised names differ
ALIASES = {
    # nations
    "korea republic": "south korea", "cote d ivoire": "ivory coast", "cape verde islands": "cape verde", "ir iran": "iran", "usa": "united states", "cote divoire": "ivory coast",
    "czechia": "czech republic", "turkiye": "turkey", "congo dr": "dr congo", "china pr": "china",
    "republic of ireland": "ireland",
    # clubs
    "bayern munich": "bayern munchen", "inter milan": "internazionale", "internazionale milano": "internazionale",
    "atletico madrid": "atletico de madrid", "athletic club": "athletic bilbao", "deportivo alaves": "alaves",
    "celta vigo": "celta de vigo", "real betis": "real betis balompie", "paris saint germain": "paris saint germain",
    "olympique lyonnais": "lyon", "olympique marseille": "marseille", "as monaco": "monaco",
    "borussia monchengladbach": "monchengladbach", "bayer leverkusen": "bayer 04 leverkusen",
    "tottenham hotspur": "tottenham hotspur", "manchester city": "manchester city",
    "west ham united": "west ham united", "ac milan": "milan", "as roma": "roma",
    "rennes": "rennais", "malherbe caen": "sm caen", "racing lens": "lens", "troyes": "estac troyes",
}
_DROP = {"fc", "cf", "ac", "afc", "sc", "sd", "rc", "rcd", "cd", "ud", "ssc", "ss", "us", "club", "calcio", "sv",
         "vfl", "tsg", "bsc", "fsv", "vfb", "1", "cfc", "sad", "ogc", "losc", "stade", "as", "de", "balompie"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = " ".join(s.split())
    return ALIASES.get(s, s)


def club_key(name: str) -> str:
    s = norm(name)
    toks = [t for t in s.split() if t not in _DROP and not re.fullmatch(r"(18|19|20)\d\d", t)] or s.split()
    k = " ".join(toks)
    return ALIASES.get(k, k)


def team_key(name: str, pool: str) -> str:
    return norm(name) if pool == "nations" else club_key(name)


@dataclass(frozen=True)
class Result:
    date: str            # ISO yyyy-mm-dd
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = False
    tournament: str = "League"


def k_factor(tournament: str, pool: str) -> float:
    t = tournament.lower()
    if pool == "clubs":
        return 30.0 if any(w in t for w in ("champions", "europa", "cup", "copa", "coupe", "pokal")) else 20.0
    if "friendly" in t:
        return 20.0
    if "qualification" in t or "nations league" in t:
        return 40.0
    if "fifa world cup" in t:
        return 60.0
    if any(w in t for w in ("uefa euro", "copa am", "african cup", "afc asian", "gold cup", "confederations")):
        return 50.0
    return 30.0


def goal_multiplier(diff: int) -> float:
    d = abs(diff)
    return 1.0 if d <= 1 else 1.5 if d == 2 else (11.0 + d) / 8.0


@dataclass
class _History:
    dates: list[str] = field(default_factory=list)
    before: list[float] = field(default_factory=list)    # rating before that match
    after: list[float] = field(default_factory=list)
    points: list[int] = field(default_factory=list)
    gd: list[int] = field(default_factory=list)


class Ratings:
    def __init__(self, pool: str):
        self.pool = pool
        self.hist: dict[str, _History] = {}

    def fit(self, results: Iterable[Result], extra: Iterable[Result] = ()) -> "Ratings":
        """Rate the primary feed; `extra` names are resolved onto its teams so shared matches count once."""
        results = list(results)
        self._known = {team_key(t, self.pool) for r in results for t in (r.home, r.away)}
        self._resolved: dict[str, str] = {}
        allr = [(self.resolve(r.home), self.resolve(r.away), r) for r in results]
        allr += [(self.resolve(r.home), self.resolve(r.away), r) for r in extra]
        seen: set[tuple] = set()
        current: dict[str, float] = {}
        for h, a, r in sorted(allr, key=lambda x: x[2].date):
            key = (r.date, *sorted((h, a)))
            if key in seen or h == a:   # the same match from two feeds counts once
                continue
            seen.add(key)
            rh, ra = current.get(h, START), current.get(a, START)
            dr = rh - ra + (0.0 if r.neutral else HOME_ADV[self.pool])
            we = 1.0 / (10 ** (-dr / 400.0) + 1.0)
            w = 1.0 if r.home_goals > r.away_goals else 0.5 if r.home_goals == r.away_goals else 0.0
            delta = k_factor(r.tournament, self.pool) * goal_multiplier(r.home_goals - r.away_goals) * (w - we)
            for team, before, sign, gf, ga in ((h, rh, 1, r.home_goals, r.away_goals), (a, ra, -1, r.away_goals, r.home_goals)):
                hs = self.hist.setdefault(team, _History())
                hs.dates.append(r.date)
                hs.before.append(before)
                hs.after.append(before + sign * delta)
                hs.points.append(3 if gf > ga else 1 if gf == ga else 0)
                hs.gd.append(gf - ga)
                current[team] = before + sign * delta
        return self

    def resolve(self, name: str) -> str:
        """Map a team name onto a primary-feed key: exact, then unique token containment, then close spelling."""
        key = team_key(name, self.pool)
        known = getattr(self, "_known", set()) | set(self.hist)
        if key in known:
            return key
        cache = getattr(self, "_resolved", {})
        if key in cache:
            return cache[key]
        import difflib
        toks = set(key.split())
        hits = [k for k in known if toks and (toks <= set(k.split()) or set(k.split()) <= toks)]
        if len(hits) != 1:
            close = difflib.get_close_matches(key, list(known), n=1, cutoff=0.85)
            hits = close if len(hits) != 1 else hits
        out = hits[0] if len(hits) == 1 else key
        cache[key] = out
        self._resolved = cache
        return out

    def before(self, name: str, date: str) -> dict[str, float | None]:
        """Rating and form from matches strictly before `date` (yyyy-mm-dd)."""
        hs = self.hist.get(self.resolve(name))
        k = bisect.bisect_left(hs.dates, date) if hs else 0
        if not hs or k == 0:
            return {"elo": None, "games": 0, "form_ppg": None, "form_gd": None}
        lo = max(0, k - FORM_N)
        return {"elo": hs.after[k - 1], "games": k, "form_ppg": sum(hs.points[lo:k]) / (k - lo),
                "form_gd": sum(hs.gd[lo:k]) / (k - lo)}


def prior_features(ratings: Ratings, team: str, opponent: str, date: str) -> dict[str, float]:
    """Pre-match features for `team` vs `opponent`; NaN (not 0) when a team has no rated history."""
    nan = float("nan")
    a, b = ratings.before(team, date), ratings.before(opponent, date)
    ea, eb = a["elo"], b["elo"]
    return {
        "elo_for": ea if ea is not None else nan, "elo_against": eb if eb is not None else nan,
        "elo_diff": (ea - eb) if ea is not None and eb is not None else nan,
        "form_ppg_for": a["form_ppg"] if a["form_ppg"] is not None else nan,
        "form_ppg_against": b["form_ppg"] if b["form_ppg"] is not None else nan,
        "form_gd_for": a["form_gd"] if a["form_gd"] is not None else nan,
        "form_gd_against": b["form_gd"] if b["form_gd"] is not None else nan,
        "rated_games_min": float(min(a["games"], b["games"])),
    }


# --------------------------------------------------------------------------- feeds

def parse_martj42(csv_text: str) -> list[Result]:
    import csv
    import io
    out = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row["home_score"] in ("", "NA") or row["away_score"] in ("", "NA"):
            continue  # fixtures not yet played
        out.append(Result(row["date"], row["home_team"], row["away_team"], int(row["home_score"]), int(row["away_score"]),
                          row["neutral"].upper() == "TRUE", row["tournament"]))
    return out


def parse_openfootball(doc: dict, tournament: str = "League") -> list[Result]:
    matches = doc.get("matches") or [m for r in doc.get("rounds", []) for m in r.get("matches", [])]
    out = []
    for m in matches:
        ft = (m.get("score") or {}).get("ft")
        if not ft or m.get("date") is None:
            continue
        out.append(Result(m["date"], m["team1"], m["team2"], int(ft[0]), int(ft[1]), False, tournament))
    return out


def parse_statsbomb_matches(matches: list[dict]) -> list[Result]:
    out = []
    for m in matches:
        if m.get("home_score") is None:
            continue
        comp = (m.get("competition") or {}).get("competition_name", "League")
        out.append(Result(m["match_date"], m["home_team"]["home_team_name"], m["away_team"]["away_team_name"],
                          int(m["home_score"]), int(m["away_score"]), False, comp))
    return out


def build(results_dir, statsbomb: list[tuple[bool, dict]]) -> dict[str, "Ratings"]:
    """Both pools from the cached feeds in results_dir plus [(competition_international, match)] from StatsBomb."""
    from pathlib import Path
    import json
    d = Path(results_dir)
    nations = parse_martj42((d / "international_results.csv").read_text())
    clubs = [r for p in sorted((d / "openfootball").glob("*.json")) for r in parse_openfootball(json.loads(p.read_text()))]
    return {
        "nations": Ratings("nations").fit(nations, parse_statsbomb_matches([m for intl, m in statsbomb if intl])),
        "clubs": Ratings("clubs").fit(clubs, parse_statsbomb_matches([m for intl, m in statsbomb if not intl])),
    }


def history_rows(ratings: "Ratings") -> list[dict]:
    """Flat rating history (for gold_team_strength / the pre-match screen)."""
    return [{"pool": ratings.pool, "team_key": team, "match_date": d, "elo_before": round(b, 1), "elo_after": round(a, 1),
             "points": p, "goal_diff": g}
            for team, h in ratings.hist.items() for d, b, a, p, g in zip(h.dates, h.before, h.after, h.points, h.gd)]
