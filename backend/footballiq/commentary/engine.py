"""Commentary from match events: play-by-play names the player on the ball; the analyst fills calm spells.

No line is spoken before its event. Priority 1 interrupts anyone, 2 cuts off the analyst, 3 is dropped when stale.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from footballiq.commentary.lexicon import COLOUR, GOAL_FACTOR, ORDINAL, PATTERN_NAME, PBP, TALK_SHARE, WHERE, WPS
from footballiq.matchday.moments import Moment, clock_minute
from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.replay.timeline import MatchTimeline

LANGS = ("en", "es", "hi")
REACTION_MS = 350
STALE_MS = {1: 12_000, 2: 3_000, 3: 1_500}
COLOUR_STALE_MS = 20_000                 # priority-2 colour may wait this long
NAMING_GAP_MS = {"own": 2_200, "middle": 1_300, "final": 600, "box": 250}
GAP_SCALE = {"en": 1.0, "es": 0.55, "hi": 0.95}   # Spanish commentary is near-continuous
CHAIN_WINDOW_MS = 3_500
COLOUR_GAP_MS = 700
CALM_ZONES = {"own", "middle", "dead"}
# ball dead for a while after these; the analyst talks through stoppages
STOPPAGE_KINDS = {"foul", "offside", "card", "sub", "injury", "shot", "corner", "half_time", "end_90", "to_pens", "score_recap"}
POST_GOAL_MS = 90_000
POST_GOAL_SHARE = 0.85
CATEGORY_COOLDOWN_MS = 60_000
FACT_COOLDOWN_MS = 6 * 60_000
MOMENT_COLOUR_EXPIRE_MS = 75_000
BOX_DEPTH, BOX_HALF_WIDTH = 16.5, 20.16
SHOT_OUTCOME = {"Saved": "saved", "Saved Off Target": "saved", "Saved to Post": "saved", "Goal": "goal", "Off T": "off",
                "Wayward": "off", "Blocked": "blocked", "Post": "post"}
KNOCKOUT_HINT = ("final", "semi", "quarter", "round of", "play-off", "playoff", "knockout")
TOUCH_TYPES = {"Pass", "Ball Receipt*", "Carry", "Shot", "Dribble", "Clearance", "Interception", "Ball Recovery"}


@dataclass
class Line:
    t_ms: int
    speaker: str            # pbp | colour
    kind: str
    priority: int
    excitement: int
    text: str = ""
    dur_ms: int = 0
    id: str = ""
    clock: str = ""
    player_ids: list[str] = field(default_factory=list)
    zone: str = "middle"    # ball zone (team frame) for naming lines
    interrupts: bool = False
    facts: dict[str, Any] = field(default_factory=dict)   # stated facts, for the colour rewrite

    def to_dict(self, audio_url: str | None) -> dict[str, Any]:
        return {"id": self.id, "t_ms": self.t_ms, "clock": self.clock, "speaker": self.speaker, "text": self.text,
                "excitement": self.excitement, "priority": self.priority, "kind": self.kind, "dur_ms": self.dur_ms,
                "interrupts": self.interrupts, "audio_url": audio_url}


class Names:
    """Spoken names per language, from the (already aliased) matchday meta."""

    def __init__(self, meta: dict[str, Any]):
        self.player = {p["player_id"]: p for p in meta["players"]}
        self.team = {meta["home"]["team_id"]: meta["home"], meta["away"]["team_id"]: meta["away"]}
        self.home, self.away = meta["home"]["team_id"], meta["away"]["team_id"]

    def p(self, pid: str | None, lang: str) -> str:
        m = self.player.get(pid or "")
        if m is None:
            return ""
        return (m.get("short_hi") or m.get("short") or m["name"]) if lang == "hi" else (m.get("short") or m["name"])

    def t(self, tid: str | None, lang: str) -> str:
        m = self.team.get(tid or "")
        if m is None:
            return ""
        return (m.get("name_hi") or m["name"]) if lang == "hi" else m["name"]

    def score(self, sa: int, sb: int, lang: str) -> str:
        return f"{self.t(self.home, lang)} {sa}, {self.t(self.away, lang)} {sb}"


def speak_ms(text: str, lang: str, speaker: str, excitement: int) -> int:
    """Estimated spoken length in ms, fitted to the configured voices."""
    wps = WPS[lang][0 if speaker == "pbp" else 1]
    words = max(1, len(re.sub(r"\.\.\.", " ", text).split()))
    pauses = 0.3 * text.count(",") + 0.5 * text.count("...") + 0.25 * len(re.findall(r"[.!?।](\s|$)", text))
    secs = 0.45 + words / wps + pauses
    if excitement >= 3:
        secs *= GOAL_FACTOR[lang]
    return int(1000 * secs)


def _height(team_is_home: bool, x: float) -> float:
    return x if team_is_home else PITCH_LENGTH_M - x


def _zone(team_is_home: bool, x: float | None, y: float | None) -> str:
    if x is None:
        return "middle"
    h = _height(team_is_home, x)
    if h >= PITCH_LENGTH_M - BOX_DEPTH and y is not None and abs(y - PITCH_WIDTH_M / 2) <= BOX_HALF_WIDTH:
        return "box"
    return "final" if h >= 70 else "middle" if h >= 35 else "own"


class _Picker:
    def __init__(self, seed: str):
        self.seed = seed
        self.recent: dict[str, list[int]] = {}

    def pick(self, options: list[str], key: str, n: int) -> str:
        h = int(hashlib.sha1(f"{self.seed}|{key}|{n}".encode()).hexdigest()[:8], 16)
        order = [(h + i) % len(options) for i in range(len(options))]
        recent = self.recent.setdefault(key, [])
        choice = next((i for i in order if i not in recent), order[0])
        recent.append(choice)
        del recent[:-max(1, min(2, len(options) - 1))]
        return options[choice]


# ====================================================================== beats
def beats(tl: MatchTimeline, names: Names, lang: str, pick: _Picker) -> list[Line]:
    """Unscheduled candidate lines from events, including event-tied colour."""
    home, away = tl.team_ids
    out: list[Line] = []
    evs = tl.events
    score, shootout, kicks = [0, 0], [0, 0], [0, 0]
    seen_start: set[int] = set()
    seen_end: set[int] = set()
    last_pass = None
    last_completed: dict[str, Any] = {}      # team -> last completed pass (assist candidate)
    knockout = any(h in (tl.match.stage or "").lower() for h in KNOCKOUT_HINT)
    goals_by: dict[str, int] = {}

    def P(pid):
        return names.p(pid, lang)

    def T(tid):
        return names.t(tid, lang)

    def add(at, kind, prio, exc, key, seq, speaker="pbp", pids=(), zone="middle", **f):
        bank = PBP[lang] if speaker == "pbp" else COLOUR[lang]
        template = pick.pick(bank[key], key, seq)
        if any(v in ("", None) for k, v in f.items() if "{" + k + "}" in template):
            return None                                    # never say "Foul by ." for an unknown player
        line = Line(int(at), speaker, kind, prio, exc, text=template.format(**f), player_ids=[p for p in pids if p], zone=zone,
                    facts={"key": key, **{k: v for k, v in f.items() if not isinstance(v, (list, dict))}})
        out.append(line)
        return line

    for n, e in enumerate(evs):
        t = e.match_elapsed_ms
        side = 0 if e.team_id == home else 1 if e.team_id == away else None
        is_home = e.team_id == home
        other = away if is_home else home

        # ---------------------------------------------------------------- periods
        if e.type == "Half Start" and e.period not in seen_start and e.period <= 4:
            seen_start.add(e.period)
            add(t + 500, "kickoff", 1, 1, f"kickoff_{e.period}", n)
            continue
        if e.type == "Half End" and e.period not in seen_end:
            seen_end.add(e.period)
            sc = names.score(*score, lang)
            if e.period == 1:
                add(t + 300, "half_time", 1, 1, "half_time", n, score=sc)
            elif e.period == 2:
                key = "end_90" if score[0] == score[1] and knockout else "full_time"
                add(t + 300, key, 1, 2, key, n, score=sc)
            elif e.period == 3:
                add(t + 300, "half_time", 1, 1, "et_half", n, score=sc)
            elif e.period == 4:
                key = "to_pens" if score[0] == score[1] else "full_time"
                add(t + 300, key, 1, 2, key, n, score=sc)
            continue
        if side is None:
            continue

        # ---------------------------------------------------------------- shootout
        if e.is_shootout or e.period == 5:
            if e.type == "Shot":
                kicks[side] += 1
                scored = e.outcome == "Goal"
                shootout[side] += scored
                add(t + 900, "shootout", 1, 3 if scored else 2, "so_goal" if scored else "so_miss", n, pids=[e.player_id],
                    p=P(e.player_id), tally=_tally(names, shootout, lang))
                if _shootout_decided(shootout, kicks):
                    add(t + 3_000, "shootout_win", 1, 3, "so_win", n + 1, t=T(home if shootout[0] > shootout[1] else away))
            continue

        # ---------------------------------------------------------------- possession
        if e.type == "Pass":
            last_pass = e
            if e.outcome == "Complete":
                last_completed[e.team_id] = e
            if e.outcome == "Complete" and e.subtype not in ("Corner", "Free Kick", "Kick Off", "Goal Kick", "Throw-in") \
                    and None not in (e.x_m, e.end_x_m, e.y_m, e.end_y_m):
                fwd = _height(is_home, e.end_x_m) - _height(is_home, e.x_m)
                length = math.hypot(e.end_x_m - e.x_m, e.end_y_m - e.y_m)
                end_zone = _zone(is_home, e.end_x_m, e.end_y_m)
                wide = e.y_m < 18 or e.y_m > PITCH_WIDTH_M - 18
                if wide and _height(is_home, e.x_m) >= 70 and end_zone == "box":
                    add(t + REACTION_MS, "cross", 2, 2, "cross", n, pids=[e.player_id], zone="final", p=P(e.player_id))
                elif fwd >= 15 and end_zone == "box" and length >= 12:
                    add(t + REACTION_MS, "through_ball", 2, 2, "through_ball", n, pids=[e.player_id, e.recipient_id], zone="box",
                        p=P(e.player_id), p2=P(e.recipient_id))
                elif length >= 32 and fwd >= 20:
                    add(t + REACTION_MS, "long_ball", 3, 1, "long_ball", n, pids=[e.player_id, e.recipient_id],
                        zone=_zone(is_home, e.x_m, e.y_m), p=P(e.player_id), p2=P(e.recipient_id))
            elif e.subtype == "Corner":
                add(t, "corner", 2, 1, "corner", n, zone="final", t=T(e.team_id))
            if e.outcome == "Pass Offside":
                add(t + 800, "offside", 2, 1, "offside", n, pids=[e.recipient_id], p=P(e.recipient_id))
            continue
        if e.type == "Ball Receipt*":
            if e.outcome not in (None, "Complete") or e.player_id is None:
                continue
            zone = _zone(is_home, e.x_m, e.y_m)
            prev = last_pass if last_pass is not None and last_pass.recipient_id == e.player_id else None
            exc = {"own": 0, "middle": 0, "final": 1, "box": 2}[zone]
            if prev is not None and prev.player_id and None not in (prev.y_m, prev.end_y_m) and abs(prev.end_y_m - prev.y_m) >= 30:
                add(t + REACTION_MS, "pass", 3, exc, "switch", n, pids=[prev.player_id, e.player_id], zone=zone,
                    p=P(prev.player_id), p2=P(e.player_id))
            elif zone == "box":
                add(t + REACTION_MS, "in_box", 2, 2, "in_box", n, pids=[e.player_id], zone=zone, p=P(e.player_id))
            elif prev is not None and prev.player_id:
                # about 4 in 10 naming lines also say where
                if int(hashlib.sha1(f"{e.event_id}".encode()).hexdigest()[:4], 16) % 10 < 4 and e.y_m is not None:
                    lateral = e.y_m if is_home else PITCH_WIDTH_M - e.y_m        # team frame: low y = left as it attacks
                    flank = "left" if lateral < 22.7 else "right" if lateral > 45.3 else "centre"
                    where = WHERE[lang][flank if flank != "centre" or zone == "final" else zone]
                    add(t + REACTION_MS, "pass", 3, exc, "pass_where", n, pids=[prev.player_id, e.player_id], zone=zone,
                        p=P(prev.player_id), p2=P(e.player_id), where=where)
                else:
                    add(t + REACTION_MS, "pass", 3, exc, "pass_to", n, pids=[prev.player_id, e.player_id], zone=zone,
                        p=P(prev.player_id), p2=P(e.player_id))
            else:
                add(t + REACTION_MS, "pass", 3, exc, "on_ball", n, pids=[e.player_id], zone=zone, p=P(e.player_id))
            continue
        if e.type == "Carry" and None not in (e.x_m, e.end_x_m):
            gain = _height(is_home, e.end_x_m) - _height(is_home, e.x_m)
            end_zone = _zone(is_home, e.end_x_m, e.end_y_m)
            if end_zone == "box" and _zone(is_home, e.x_m, e.y_m) != "box":
                add(t + (e.duration_ms or 0), "in_box", 2, 2, "in_box", n, pids=[e.player_id], zone="box", p=P(e.player_id))
            elif gain >= 15 and _height(is_home, e.x_m) >= 35:
                add(t + REACTION_MS, "carry", 3, 1, "carry", n, pids=[e.player_id], zone=end_zone, p=P(e.player_id))
            continue
        if e.type == "Dribble" and e.outcome == "Complete":
            zone = _zone(is_home, e.x_m, e.y_m)
            add(t + REACTION_MS, "dribble", 2, 2 if zone in ("final", "box") else 1, "dribble", n, pids=[e.player_id], zone=zone,
                p=P(e.player_id))
            continue
        if e.type in ("Interception", "Ball Recovery") and e.outcome not in ("Lost", "Lost In Play", "Lost Out", "Fail"):
            add(t + REACTION_MS, "regain", 3, 0, "interception" if e.type == "Interception" else "recovery", n,
                pids=[e.player_id], zone=_zone(is_home, e.x_m, e.y_m), p=P(e.player_id))
            continue
        if e.type == "Clearance" and _zone(not is_home, e.x_m, e.y_m) == "box":
            add(t + REACTION_MS, "clearance", 3, 1, "clearance", n, pids=[e.player_id], zone="own", p=P(e.player_id))
            continue

        # ---------------------------------------------------------------- shots and goals
        if e.type == "Shot":
            outcome = SHOT_OUTCOME.get(e.outcome or "", "off")
            gk = next((x for x in evs[n + 1:n + 8] if x.type == "Goal Keeper" and x.team_id == other
                       and x.match_elapsed_ms - t <= 1_500), None)
            last_t = max(t, gk.match_elapsed_ms if gk else t)
            keeper = gk.player_id if gk else None
            pen = e.subtype == "Penalty"
            flight = 500 if pen else 700
            if outcome == "goal":
                before = list(score)
                score[side] += 1
                goals_by[e.player_id or ""] = goals_by.get(e.player_id or "", 0) + 1
                state = _state(names, before, score, side, e.team_id, lang, pick, n)
                call = add(last_t + flight + 300, "goal", 1, 3, "pen_goal" if pen else "goal", n, pids=[e.player_id, keeper],
                           zone="box", p=P(e.player_id), gk=P(keeper) or names.t(other, lang), state=state)
                if call is None:
                    continue
                minute = clock_minute(tl, t).split("+")[0].rstrip("′")
                sc = names.score(*score, lang)
                call_end = call.t_ms + speak_ms(call.text, lang, "pbp", 3)   # a held "¡GOOOL!" is long
                add(call_end + 600, "goal_reaction", 2, 2, "goal_reaction", n, pids=[e.player_id], p=P(e.player_id))
                add(call_end + 5_000, "goal_formula", 2, 1, "goal_formula", n, pids=[e.player_id], p=P(e.player_id),
                    t=T(e.team_id), m=minute, score=sc)
                if goals_by[e.player_id or ""] >= 2:
                    k_goals = goals_by[e.player_id or ""]
                    add(call.t_ms + 16_000, "goal_tally", 2, 0, "goal_tally", n, speaker="colour", pids=[e.player_id], p=P(e.player_id),
                        n=ORDINAL[lang].get(k_goals, str(k_goals)), k=k_goals)
                assist = last_completed.get(e.team_id)
                if not pen and assist is not None and assist.recipient_id == e.player_id and t - assist.match_elapsed_ms <= 15_000:
                    add(call.t_ms + 38_000, "replay", 2, 0, "replay", n, speaker="colour", pids=[e.player_id, assist.player_id],
                        p=P(e.player_id), p2=P(assist.player_id))
                add(call.t_ms + 33_000, "score_recap", 2, 0, "score_recap", n, score=sc, m=minute)
                continue
            if pen:
                key = "pen_saved" if outcome == "saved" else "pen_missed"
            else:
                wide = e.end_y_m is not None and abs(e.end_y_m - PITCH_WIDTH_M / 2) > 3.66
                key = {"saved": "shot_saved", "blocked": "shot_blocked", "post": "shot_post"}.get(outcome, "shot_wide" if wide else "shot_over")
            zone = _zone(is_home, e.x_m, e.y_m)
            exc = 2 if zone == "box" or (e.provider_xg or 0) >= 0.15 else 1
            add(last_t + flight, "shot", 1, exc, key, n, pids=[e.player_id, keeper], zone=zone, p=P(e.player_id),
                gk=P(keeper) or names.t(other, lang))
            continue
        if e.is_own_goal:
            score[side] += 1
            add(t + 800, "goal", 1, 3, "state_lead" if score[side] > score[1 - side] else "state_level", n, t=T(e.team_id),
                score=names.score(*score, lang))
            continue

        # ---------------------------------------------------------------- fouls, cards, subs
        if e.type == "Foul Committed":
            victim = next((x for x in evs[n + 1:n + 4] if x.type == "Foul Won" and x.match_elapsed_ms - t <= 500), None)
            fouled_home = other == home
            if e.x_m is not None and _zone(fouled_home, e.x_m, e.y_m) == "box":
                add(t + 900, "penalty", 1, 3, "penalty_awarded", n, zone="box", t=T(other))
            elif e.x_m is not None and _height(fouled_home, e.x_m) >= 70:
                d = round(math.hypot((PITCH_LENGTH_M if fouled_home else 0) - e.x_m, PITCH_WIDTH_M / 2 - (e.y_m or 34)) / 5) * 5
                add(t + 700, "foul", 2, 1, "foul_dangerous", n, pids=[e.player_id], zone="final", p=P(e.player_id),
                    p2=P(victim.player_id if victim else None), t=T(other), d=d)
            else:
                add(t + 700, "foul", 3, 0, "foul", n, pids=[e.player_id], p=P(e.player_id), p2=P(victim.player_id if victim else None))
        if e.card in ("Yellow Card", "Second Yellow", "Red Card"):
            key = {"Yellow Card": "yellow", "Second Yellow": "second_yellow", "Red Card": "red"}[e.card]
            add(t + 2_500, "card", 1, 1 if key == "yellow" else 2, key, n, pids=[e.player_id], p=P(e.player_id))
            continue
        if e.type == "Offside":
            add(t + 600, "offside", 2, 1, "offside", n, pids=[e.player_id], p=P(e.player_id))
        elif e.type == "Substitution":
            add(t + 1_000, "sub", 2, 0, "sub", n, pids=[e.recipient_id, e.player_id], t=T(e.team_id), p=P(e.recipient_id), p2=P(e.player_id))
        elif e.type == "Injury Stoppage":
            add(t + 1_500, "injury", 3, 0, "injury", n, pids=[e.player_id], p=P(e.player_id))

    out += _halftime_colour(tl, names, lang, pick)
    return out


def _tally(names: Names, s: list[int], lang: str) -> str:
    h, a = names.t(names.home, lang), names.t(names.away, lang)
    return {"en": f"{h} {s[0]}, {a} {s[1]} in the shootout.", "es": f"{h} {s[0]}, {a} {s[1]} en los penales.",
            "hi": f"शूटआउट में {h} {s[0]}, {a} {s[1]}।"}[lang]


def _shootout_decided(s: list[int], k: list[int]) -> bool:
    if k[0] <= 5 and k[1] <= 5:
        return s[0] + (5 - k[0]) < s[1] or s[1] + (5 - k[1]) < s[0]
    return k[0] == k[1] and s[0] != s[1]


def _state(names: Names, before: list[int], after: list[int], side: int, team_id: str, lang: str, pick: _Picker, n: int) -> str:
    us_b, them_b = before[side], before[1 - side]
    us, them = after[side], after[1 - side]
    if us == them:
        key = "state_level"
    elif us < them:
        key = "state_back"
    else:
        key = "state_lead" if us_b <= them_b else "state_extend"
    return pick.pick(PBP[lang][key], key, n).format(t=names.t(team_id, lang), score=names.score(*after, lang))


def _halftime_colour(tl: MatchTimeline, names: Names, lang: str, pick: _Picker) -> list[Line]:
    home, away = tl.team_ids
    for e in tl.events:
        if e.type == "Half End" and e.period == 1:
            s = tl.stats_at(e.match_elapsed_ms)
            ph, pa = s[home].get("possession_ms", 0), s[away].get("possession_ms", 0)
            share = round(100 * ph / (ph + pa)) if ph + pa else 50
            f = {"t": names.t(home, lang), "a": share, "b": 100 - share, "n": s[home]["shots"], "m": s[away]["shots"]}
            text = pick.pick(COLOUR[lang]["half_time"], "half_time", 0).format(**f)
            return [Line(e.match_elapsed_ms + 6_000, "colour", "half_time_stats", 2, 0, text=text, facts={"key": "half_time", **f})]
    return []


# ====================================================================== analyst
class Context:
    """Colour material at any second, from data at or before it."""

    def __init__(self, tl: MatchTimeline, names: Names, lang: str, pick: _Picker, data=None, moments: list[Moment] | None = None):
        self.tl, self.names, self.lang, self.pick, self.d = tl, names, lang, pick, data
        self.home, self.away = tl.team_ids
        self.cat_last: dict[str, int] = {}
        self.fact_last: dict[tuple, int] = {}
        self.moment_queue = sorted((m for m in (moments or []) if m.kind in ("flow", "shape", "speed", "milestone", "pass", "chance", "card", "sub")),
                                   key=lambda m: m.t_ms)
        self.booked: dict[str, int] = {e.player_id: e.match_elapsed_ms for e in tl.events if e.card == "Yellow Card" and e.player_id}
        touches: dict[str, list[int]] = {}
        passes: dict[str, list[tuple[int, bool]]] = {}
        for e in tl.events:
            if not e.player_id or e.is_shootout:
                continue
            if e.type in TOUCH_TYPES:
                touches.setdefault(e.player_id, []).append(e.match_elapsed_ms)
            if e.type == "Pass" and e.subtype != "Throw-in":
                passes.setdefault(e.player_id, []).append((e.match_elapsed_ms, e.outcome == "Complete"))
        self.touch_t = {k: np.array(v, dtype=np.int64) for k, v in touches.items()}
        self.pass_t = {k: np.array([t for t, _ in v], dtype=np.int64) for k, v in passes.items()}
        self.pass_ok = {k: np.cumsum([ok for _, ok in v]) for k, v in passes.items()}
        self.times = np.asarray(data.times, dtype=np.int64) if data is not None else np.empty(0, np.int64)

    def _series_at(self, t: int) -> int | None:
        k = int(np.searchsorted(self.times, t, side="right")) - 1
        return None if k < 0 else k

    def _line(self, t: int, key: str, cat: str, args: dict[str, Any], pids=()) -> Line | None:
        sig = (key, tuple(sorted((k, str(v)) for k, v in args.items())))
        if t - self.fact_last.get(sig, -10**12) < FACT_COOLDOWN_MS:
            return None
        template = self.pick.pick(COLOUR[self.lang][key], key, t // 1000)
        if any(v in ("", None) for k, v in args.items() if "{" + k + "}" in template):
            return None
        self.fact_last[sig] = t
        self.cat_last[cat] = t
        return Line(t, "colour", key, 3, 0, text=template.format(**args), player_ids=[p for p in pids if p], facts={"key": key, **args})

    def moment_line(self, t: int) -> Line | None:
        """Freshest unused matchday moment detected at or before t."""
        while self.moment_queue and t - self.moment_queue[0].t_ms > MOMENT_COLOUR_EXPIRE_MS:
            self.moment_queue.pop(0)
        for i, m in enumerate(self.moment_queue):
            if m.t_ms > t:
                break
            self.moment_queue.pop(i)
            line = self._moment(m, t)
            if line is not None:
                return line
            break
        return None

    def _moment(self, m: Moment, t: int) -> Line | None:
        f, n, lang = m.f, self.names, self.lang
        team = n.t(m.team_id, lang) if m.team_id else ""
        p, p2 = n.p(m.player_id, lang), n.p(m.player2_id, lang)
        pat = PATTERN_NAME[lang]
        if m.kind == "card" and (f.get("fouls") or 0) >= 3:
            return self._line(t, "card_warning", "discipline", {"p": p, "t": team, "n": f["fouls"]}, [m.player_id])
        if m.kind == "sub" and f.get("km"):
            return self._line(t, "sub_km", "players", {"p2": p2, "x": f"{f['km']:.1f}"}, [m.player2_id])
        if m.kind == "flow" and m.variant == "control":
            return self._line(t, "flow_control", "flow", {"t": team, "a": f["poss"], "b": f["acc"], "n": f["ctrl"]})
        if m.kind == "flow" and m.variant == "chaos":
            return self._line(t, "flow_chaos", "flow", {"a": f["tov"], "n": f["chaos"]})
        if m.kind == "flow" and m.variant == "rhythm":
            return self._line(t, "flow_rhythm", "flow", {"pattern": pat.get(f["pattern"], f["pattern"])})
        if m.kind == "shape" and m.variant in ("stretched", "lowblock", "highline"):
            return self._line(t, f"shape_{m.variant}", "shape",
                              {"t": team, "n": f["len"] if m.variant == "stretched" else f["def"], "a": f["gap"]})
        if m.kind == "speed" and m.variant == "sprint":
            return self._line(t, "sprint", "players", {"p": p, "x": f"{f['spd']:.0f}"}, [m.player_id])
        if m.kind == "milestone":
            return self._line(t, "km10", "players", {"p": p}, [m.player_id])
        if m.kind == "pass":
            return self._line(t, "pass_quality", "players", {"p": p, "p2": p2, "n": f.get("xpp")}, [m.player_id, m.player2_id])
        if m.kind == "chance" and (f.get("xg") or 0) >= 0.3:
            return self._line(t, "chance_big", "chances", {"t": team, "x": f"{f['xg']:.2f}"})
        return None

    def context_line(self, t: int, holder: str | None) -> Line | None:
        """A fact known at t, trying the least recently used category first."""
        for cat in sorted(("holder", "team", "flow", "shape", "win", "state"), key=lambda c: self.cat_last.get(c, -10**12)):
            if t - self.cat_last.get(cat, -10**12) < CATEGORY_COOLDOWN_MS:
                continue
            for line in self._facts(cat, t, holder):
                if line is not None:
                    return line
        return None

    def _facts(self, cat: str, t: int, holder: str | None):
        n, lang, tl = self.names, self.lang, self.tl
        if cat == "holder" and holder:
            p = n.p(holder, lang)
            touches = int(np.searchsorted(self.touch_t.get(holder, np.empty(0, np.int64)), t, side="right"))
            k = int(np.searchsorted(self.pass_t.get(holder, np.empty(0, np.int64)), t, side="right"))
            ok = int(self.pass_ok[holder][k - 1]) if k else 0
            if holder in self.booked and self.booked[holder] <= t:
                yield self._line(t, "holder_yellow", cat, {"p": p}, [holder])
            if k >= 12:
                yield self._line(t, "holder_passes", cat, {"p": p, "a": ok, "n": k}, [holder])
            if touches >= 20:
                yield self._line(t, "holder_touches", cat, {"p": p, "n": touches}, [holder])
            run = self.d.physical.at(holder, t) if self.d is not None else None
            if run and (run.get("km") or 0) >= 2:
                yield self._line(t, "holder_km", cat, {"p": p, "x": f"{run['km']:.1f}"}, [holder])
        elif cat == "team":
            s = tl.stats_at(t)
            for tid in (self.home, self.away):
                st, name = s[tid], n.t(tid, lang)
                if st["shots"] >= 3:
                    yield self._line(t, "team_shots_target", cat, {"t": name, "n": st["shots"], "m": st["shots_on_target"]})
                if st["corners"] >= 3:
                    yield self._line(t, "team_corners", cat, {"t": name, "n": st["corners"]})
                if st["passes_attempted"] >= 60:
                    yield self._line(t, "team_pass_acc", cat, {"t": name, "n": round(100 * st["passes_completed"] / st["passes_attempted"])})
                if st["fouls"] >= 8:
                    yield self._line(t, "fouls_count", cat, {"t": name, "n": st["fouls"]})
            ph, pa = s[self.home].get("possession_ms", 0), s[self.away].get("possession_ms", 0)
            if ph + pa > 600_000:
                lead = self.home if ph >= pa else self.away
                yield self._line(t, "possession", cat, {"t": n.t(lead, lang), "n": round(100 * max(ph, pa) / (ph + pa))})
        elif cat in ("flow", "shape", "win") and self.d is not None and t >= 600_000 and (k := self._series_at(t)) is not None:
            if cat == "flow":
                w = self.d.flow[k][1]
                yield self._line(t, "flow_now", cat, {"pattern": PATTERN_NAME[lang].get(w["pattern"], w["pattern"])})
                c = w["control"]
                if abs(c[0] - c[1]) >= 15:
                    lead = 0 if c[0] > c[1] else 1
                    yield self._line(t, "control_now", cat, {"t": n.t(tl.team_ids[lead], lang), "n": c[lead]})
            elif cat == "shape" and self.d.shapes:
                for side in (0, 1):
                    sh = self.d.shapes[k][1][side]
                    if sh and sh.get("def") is not None:
                        yield self._line(t, "shape_now", cat, {"t": n.t(tl.team_ids[side], lang), "n": round(sh["def"]),
                                                               "a": round(sh["length"])})
            elif cat == "win" and self.d.win[k]:
                w = self.d.win[k]
                side = 0 if w[0] >= w[2] else 1
                yield self._line(t, "win_now", cat, {"t": n.t(tl.team_ids[side], lang), "n": round(100 * w[0 if side == 0 else 2])})
        elif cat == "state":
            s = tl.stats_at(t)
            g = (s[self.home]["goals"], s[self.away]["goals"])
            p2 = next((x for x in tl.match.periods if x.period == 2), None)
            if g[0] != g[1] and tl.period_at(t) == 2 and p2 is not None:
                left = 90 - (45 + (t - p2.start_match_ms) // 60_000)
                if 3 <= left <= 25:
                    yield self._line(t, "chasing", cat, {"t": n.t(self.home if g[0] < g[1] else self.away, lang), "n": int(left)})


# ====================================================================== booth
def schedule(tl: MatchTimeline, cands: list[Line], lang: str, ctx: Context | None = None) -> list[Line]:
    for c in cands:
        c.dur_ms = speak_ms(c.text, lang, c.speaker, c.excitement)
    cands = sorted(cands, key=lambda c: (c.t_ms, c.priority))
    lines: list[Line] = []
    spoken: deque[list[int]] = deque()
    state: dict[str, Any] = {"busy": 0, "zone": "middle", "holder": None, "post_goal": -1}
    chain: list[tuple[int, str]] = []
    gap_scale, target = GAP_SCALE[lang], TALK_SHARE[lang]

    def share(at: int) -> float:
        while spoken and spoken[0][1] < at - 60_000:
            spoken.popleft()
        talk = sum(max(0, min(b, at) - max(a, at - 60_000)) for a, b in spoken)
        return talk / max(1, min(60_000, at))

    def place(c: Line, start: int) -> None:
        if lines and lines[-1].t_ms + lines[-1].dur_ms > start:      # cut the line that is still running
            prev = lines[-1]
            prev.dur_ms = max(0, start - prev.t_ms)
            if spoken:
                spoken[-1][1] = start
            c.interrupts = True
        c.t_ms = int(start)
        lines.append(c)
        spoken.append([c.t_ms, c.t_ms + c.dur_ms])
        state["busy"] = c.t_ms + c.dur_ms
        if c.kind == "goal":
            state["post_goal"] = c.t_ms + POST_GOAL_MS

    def fill_colour(until: int) -> None:
        """Fill silence before ``until`` with analyst lines known at their start."""
        if ctx is None:
            return
        f = state["busy"] + COLOUR_GAP_MS
        while f < until:
            post_goal = f <= state["post_goal"]
            if state["zone"] not in CALM_ZONES and not post_goal:
                return
            if share(f) >= (POST_GOAL_SHARE if post_goal else target):
                f += 1_500
                continue
            line = ctx.moment_line(f) or ctx.context_line(f, state["holder"])
            if line is None:
                return
            line.dur_ms = speak_ms(line.text, lang, "colour", 0)
            place(line, f)
            f = state["busy"] + COLOUR_GAP_MS

    for c in cands:
        fill_colour(c.t_ms)
        start = c.t_ms
        busy = state["busy"] > start
        running = lines[-1] if lines and busy else None
        placed = False
        if c.priority == 1:
            if running is not None and running.priority == 1 and running.speaker == "pbp":
                start = state["busy"] + 150        # don't cut one big call with another
            place(c, start)
            placed = True
        elif c.priority == 2:
            if running is not None and running.speaker == "colour" and c.speaker == "pbp":
                place(c, start)                    # the attack matters more than the analysis
                placed = True
            elif running is not None:
                if state["busy"] - c.t_ms <= (COLOUR_STALE_MS if c.speaker == "colour" else STALE_MS[2]):
                    place(c, state["busy"] + 150)
                    placed = True
            else:
                place(c, start)
                placed = True
        else:   # priority 3: naming the player on the ball
            gap = NAMING_GAP_MS.get(c.zone, NAMING_GAP_MS["middle"]) * gap_scale
            too_soon = bool(lines) and start - (lines[-1].t_ms + lines[-1].dur_ms) < gap
            if busy or too_soon:
                if c.kind in ("pass", "carry", "regain") and c.player_ids:
                    chain.append((c.t_ms, c.player_ids[-1]))
                state["zone"] = c.zone
                state["holder"] = c.player_ids[-1] if c.player_ids else state["holder"]
                continue
            recent = [pid for t, pid in chain if c.t_ms - t <= CHAIN_WINDOW_MS]
            chain.clear()
            if len(recent) >= 2 and c.kind in ("pass", "carry", "regain") and ctx is not None:
                names: list[str] = []
                for pid in [*recent[-2:], c.player_ids[-1]]:
                    nm = ctx.names.p(pid, lang)
                    if nm and (not names or names[-1] != nm):
                        names.append(nm)
                if len(names) >= 2:
                    c.text = PBP[lang]["chain"][1 if c.zone in ("final", "box") else 0].format(names="... ".join(names))
                    c.kind = "chain"
                    c.dur_ms = speak_ms(c.text, lang, "pbp", c.excitement)
            place(c, start)
            placed = True
        if placed and c.speaker == "pbp":
            state["zone"] = "dead" if c.kind in STOPPAGE_KINDS else c.zone
            if c.player_ids and c.kind not in ("sub", "card", "foul"):
                state["holder"] = c.player_ids[-1]
    fill_colour(tl.match.duration_ms)
    lines.sort(key=lambda l: l.t_ms)
    for i, l in enumerate(lines):
        l.id = f"c-{lang}-{i + 1:05d}"
        l.clock = clock_minute(tl, l.t_ms)
    return lines


def build_script(tl: MatchTimeline, meta: dict[str, Any], lang: str, data=None) -> list[Line]:
    """``data`` is MatchdayData, or None for events-only commentary."""
    if lang not in LANGS:
        raise ValueError(f"unsupported language {lang!r}")
    names = Names(meta)
    pick = _Picker(f"{tl.match.canonical_match_id}|{lang}")
    ctx = Context(tl, names, lang, pick, data, data.moments if data is not None else None)
    return schedule(tl, beats(tl, names, lang, pick), lang, ctx)
