"""Coach service: player form, substitutions, best player and auto insights for one match.

Inputs are bounded by the replay clock; tournament history covers earlier matches only.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from footballiq.insights import detect
from footballiq.players import (
    HISTORY_SQL,
    SITUATIONS,
    PlayerHistory,
    best_for,
    player_form,
    substitution_options,
)

log = logging.getLogger(__name__)
MIN = 60_000


class CoachService:
    def __init__(self, store: Any, predictions: Callable[[], Any] | None = None, tactical: Callable[[], Any] | None = None):
        self.store = store
        self._predictions, self._tactical = predictions, tactical
        self._history: PlayerHistory | None = None
        self._history_state = "idle"
        self._insights: dict[str, tuple[list[dict[str, Any]], list[str]]] = {}
        self._lock = threading.Lock()
        self._match_locks: dict[str, threading.Lock] = {}

    def _ps(self):
        try:
            return self._predictions() if self._predictions else None
        except Exception:  # noqa: BLE001 - local source: no model outputs
            return None

    def _ts(self):
        try:
            return self._tactical() if self._tactical else None
        except Exception:  # noqa: BLE001 - local source: no tactical tables
            return None

    def warm_history(self, block: bool = False) -> None:
        """Load tournament history (one slow aggregation, then cached), in a thread unless ``block``."""
        lh = getattr(self.store, "lh", None)
        if lh is None or self._history_state != "idle":
            return

        def run() -> None:
            self._history_state = "loading"
            try:
                rows = lh.query(HISTORY_SQL, {"t": "silver_match_event"}).to_pylist()
                meta = {}
                for m in lh.query("select canonical_match_id, competition, home, kickoff_source from t", {"t": "silver_match"}).to_pylist():
                    home = json.loads(m["home"]) if isinstance(m["home"], str) else m["home"]
                    meta[m["canonical_match_id"]] = {"home": home["team_id"], "date": (m["kickoff_source"] or "")[:10],
                                                     "competition": m["competition"]}
                self._history = PlayerHistory(rows, meta)
                self._history_state = "ready"
                log.info("player history: %d player-match rows", len(rows))
            except Exception:
                log.exception("player history failed")
                self._history_state = "failed"

        if block:
            run()
        else:
            threading.Thread(target=run, daemon=True, name="player-history").start()

    def _timeline(self, match_id: str):
        tl = self.store.get(match_id)
        if tl is None:
            raise KeyError(match_id)
        return tl

    def form(self, match_id: str, at_ms: int, tl=None) -> dict[str, list]:
        tl = tl or self._timeline(match_id)
        at_ms = max(0, min(int(at_ms), tl.match.duration_ms))
        ps, ts = self._ps(), self._ts()
        xt = None
        if ps is not None:
            try:
                xt = ps.xt_by_event(match_id, at_ms)
            except Exception:  # noqa: BLE001 - not scored
                xt = None
        now = then = None
        if ts is not None and tl.tracking is not None:
            try:
                now, then = ts.physical(match_id, at_ms), ts.physical(match_id, max(0, at_ms - 15 * MIN))
            except Exception:  # noqa: BLE001 - no physical table for this match
                now = then = None
        positions = {r["player_id"]: r["position_group"] for r in tl.tracking.roster() if r.get("player_id")} if tl.tracking else None
        return player_form(tl, at_ms, history=self._history, xt_by_event=xt, physical_now=now, physical_then=then, positions=positions)

    def sources(self, tl) -> dict[str, Any]:
        return {"history": self._history_state, "model_values": self._ps() is not None,
                "physical": self._ts() is not None and tl.tracking is not None, "positions": tl.tracking is not None}

    def players(self, match_id: str, at_ms: int, team_id: str | None = None) -> dict[str, Any]:
        tl = self._timeline(match_id)
        form = self.form(match_id, at_ms, tl)
        teams = {k: [p.to_dict() for p in v] for k, v in form.items() if team_id in (None, k)}
        return {"match_id": match_id, "at_ms": at_ms, "replay_clock": tl.clock_label_at(at_ms), "teams": teams,
                "sources": self.sources(tl), "impact_note": "Impact index per 15' on the pitch; see footballiq.players for weights."}

    def substitutions(self, match_id: str, at_ms: int, team_id: str) -> dict[str, Any]:
        tl = self._timeline(match_id)
        return {**substitution_options(tl, at_ms, team_id, self.form(match_id, at_ms, tl)), "replay_clock": tl.clock_label_at(at_ms),
                "sources": self.sources(tl)}

    def best(self, match_id: str, at_ms: int, team_id: str, situation: str) -> dict[str, Any]:
        tl = self._timeline(match_id)
        return {**best_for(tl, at_ms, team_id, situation, self.form(match_id, at_ms, tl)), "replay_clock": tl.clock_label_at(at_ms),
                "sources": self.sources(tl)}

    def insights(self, match_id: str, at_ms: int) -> dict[str, Any]:
        tl = self._timeline(match_id)
        with self._lock:
            lock = self._match_locks.setdefault(match_id, threading.Lock())
        with lock:   # one computation per match; later callers reuse it
            if match_id not in self._insights:
                ps, ts = self._ps(), self._ts()
                items, sources = detect(tl, ps.latest if ps else None, ts, coach=self)
                # cache only once slow inputs are ready; early results are recomputed
                if self._history_state in ("ready", "failed") or getattr(self.store, "lh", None) is None:
                    self._insights[match_id] = ([i.to_dict() for i in items], sources)
                else:
                    return self._filtered(tl, [i.to_dict() for i in items], sources, at_ms, partial=True)
            items, sources = self._insights[match_id]
        return self._filtered(tl, items, sources, at_ms)

    def _filtered(self, tl, items, sources, at_ms, partial: bool = False) -> dict[str, Any]:
        return {"match_id": tl.match.canonical_match_id, "at_ms": at_ms, "replay_clock": tl.clock_label_at(at_ms),
                "insights": [i for i in items if i["t_ms"] <= at_ms], "total_in_match": None, "sources": sources,
                "partial": partial, "situations": list(SITUATIONS)}

    def prematch(self, match_id: str) -> dict[str, Any]:
        """Both teams' tournament profiles from earlier matches, plus tournament averages."""
        tl = self._timeline(match_id)
        m = tl.match
        if self._history is None:
            self.warm_history()
            return {"match_id": match_id, "status": self._history_state, "teams": {}}
        date = m.kickoff_source[:10]
        comp = self._history.competition_of(m.canonical_match_id, m.competition)   # not the (possibly renamed) display name
        teams = {t: self._history.team_profile(t, date, comp) for t in (m.home.team_id, m.away.team_id)}
        # reference: every team's per-match averages before this date
        all_teams = {g["team_id"] for games in self._history.by_player.values() for g in games
                     if g["competition"] == comp and g["date"] < date}
        ref = [self._history.team_profile(t, date, comp)["for"] for t in all_teams]
        ref = [r for r in ref if r.get("shots") is not None]
        avg = {k: round(sum(r[k] for r in ref if r.get(k) is not None) / len(ref), 2) for k in ("goals", "shots", "xg", "corners", "pressures",
                                                                                                "def_actions", "pass_pct")} if ref else {}
        return {"match_id": match_id, "status": "ready", "date": date, "competition": m.competition, "teams": teams,
                "tournament_average": avg, "teams_in_reference": len(ref),
                "note": "Earlier matches in this competition only (nothing from this match or later). Injury lists are not in the feeds."}

    def find_insight(self, match_id: str, insight_id: str) -> dict[str, Any] | None:
        items = self._insights[match_id][0] if match_id in self._insights else self.insights(match_id, 10**12)["insights"]
        return next((i for i in items if i["id"] == insight_id), None)
