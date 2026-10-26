"""Pre-match form and head-to-head from catalogue matches dated strictly before kickoff."""

from __future__ import annotations

from typing import Any

from footballiq.schema import Match


def _date(m: Match) -> str:
    return m.kickoff_source.split(" ")[0]


def _row(m: Match, team_id: str) -> dict[str, Any]:
    home = m.home.team_id == team_id
    gf, ga = (m.result["home_score"], m.result["away_score"]) if home else (m.result["away_score"], m.result["home_score"])
    so = m.result.get("shootout")
    pens = None
    if so:
        opp = m.away.team_id if home else m.home.team_id
        pens = f"{so.get(team_id, 0)}-{so.get(opp, 0)}"
    if gf != ga:
        res = "W" if gf > ga else "L"
    else:
        res = "D"
    return {
        "match_id": m.canonical_match_id, "date": _date(m), "stage": m.stage, "competition": m.competition,
        "opponent": (m.away if home else m.home).name, "opponent_id": (m.away if home else m.home).team_id,
        "venue": "home" if home else "away", "score": f"{gf}-{ga}", "pens": pens, "result": res,
        "goals_for": gf, "goals_against": ga,
    }


def pre_match(match: Match, catalogue: list[Match], last_n: int = 6) -> dict[str, Any]:
    cutoff = _date(match)
    earlier = sorted((m for m in catalogue if _date(m) < cutoff), key=_date, reverse=True)
    teams = {}
    for team in (match.home, match.away):
        rows = [_row(m, team.team_id) for m in earlier if team.team_id in (m.home.team_id, m.away.team_id)]
        played = rows[:last_n]
        teams[team.team_id] = {
            "team_id": team.team_id, "name": team.name, "form": played,
            "summary": {
                "played": len(played),
                "won": sum(r["result"] == "W" for r in played),
                "drawn": sum(r["result"] == "D" for r in played),
                "lost": sum(r["result"] == "L" for r in played),
                "goals_for": sum(r["goals_for"] for r in played),
                "goals_against": sum(r["goals_against"] for r in played),
            },
        }
    ids = {match.home.team_id, match.away.team_id}
    h2h = [_row(m, match.home.team_id) for m in earlier if {m.home.team_id, m.away.team_id} == ids]
    return {
        "match_id": match.canonical_match_id, "cutoff_date": cutoff,
        "cutoff_rule": "only matches dated before kickoff; the selected match and anything later are excluded",
        "coverage": "matches held in the platform (FIFA World Cup 2022, StatsBomb)",
        "teams": teams, "head_to_head": h2h,
    }
