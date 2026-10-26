# Matchday API (perspectives UI + live commentary)

Contract between the backend (`backend/footballiq/matchday/`, `backend/footballiq/commentary/`) and the
Next.js Matchday UI (`frontend/components/matchday/`, `frontend/lib/matchday/`).

## Ground rules

- **Fictional names everywhere.** Teams, players, referee, stadium and competition are renamed once, in the
  backend (`footballiq/aliases.py`). Public ids are aliases too: a client never sees a real name or a
  real-name id such as `france_kylian-mbappe-lottin`. Shirt numbers, kit colours, events and positions are real.
- **No spoilers.** Every endpoint takes a replay cutoff (`to_ms` / `at_ms`) and returns nothing after it.
- **Sides.** Arrays of two are `[home, away]`. Pitch frame is 105 x 68 m, home attacks left to right.
  "Height" means metres from the team's own goal line.
- **Clock labels** (`clock`) are display strings: `57′`, `45+2′`, `105+1′`, `PEN`.

## Existing endpoints the UI keeps using

| Endpoint | Use |
|---|---|
| `GET /v1/matches` | match picker; each item has `featured: true/false` (the default match, so the UI never needs a real id) |
| `GET /v1/matches/{id}/tracking` | roster: tracking `idx` -> `player_id`, side |
| `GET /v1/matches/{id}/frames?from_ms&to_ms&max_frames` | 30 Hz frames (`WireFrame`, see `frontend/lib/trackingBuffer.ts`) |
| `GET /v1/matches/{id}/events?to_ms` | transport pins, player actions |
| `GET /v1/matches/{id}/state?at_ms` | scorebug, team counters |

## New endpoints

### `GET /v1/matches/{id}/matchday/meta`

```jsonc
{
  "match_id": "m-7f3a",
  "competition": "Continental Cup", "stage": "Final", "date": "2022-12-18", "stadium": "...",
  "home": { "team_id": "t-sol", "side": "home", "name": "Solaria", "short": "SOL", "name_hi": "सोलारिया", "short_hi": "सोल",
            "colors": { "primary": "#1f5fd6", "secondary": "#ffffff", "ink": "#ffffff", "pattern": "solid" } },
  "away": { ... },
  "periods": [{ "period": 1, "label": "1st half", "start_ms": 0, "duration_ms": 2880000, "base_minute": 0 }],
  "duration_ms": 9000000,
  "players": [{ "player_id": "p-1a2b", "team_id": "t-sol", "side": "home", "name": "Tomás Ibarra", "short": "Ibarra",
                "name_hi": "तोमास इबार्रा", "short_hi": "इबार्रा", "number": 10, "position": "Right Wing",
                "role": "ATT", "starter": true }],
  "has_tracking": true, "tracking_hz": 30
}
```

`role` is one of `GK | DEF | MID | ATT` (declared lineup position, falling back to average depth from tracking).
`pattern` is one of `solid | stripes | hoops | tricolor`.

### `GET /v1/matches/{id}/matchday/series?to_ms=`

A point every 30 s of match time up to `to_ms`. Flow metrics use a rolling 5-minute window.

```jsonc
{ "step_ms": 30000, "points": [{
  "t_ms": 1800000, "clock": "30′", "score": [1, 0],
  "win": [0.62, 0.24, 0.14],                   // home, draw, away; null if unavailable
  "flow": {
    "chaos": 41, "control": [63, 48],            // 0-100
    "comp": { "turnovers": 1.4, "duels": 1.1, "transitions": 0.2, "long_share": 0.18, "avg_seq": 3.1 },
    "tempo": 17.2, "bip": 0.71, "stops": 4, "tilt": 0.58,
    "pattern": "high_tempo",                     // balanced | settled | high_tempo | end_to_end | stop_start | siege
    "poss_share": [0.56, 0.44], "pass_acc": [0.87, 0.79], "siege_team": null
  },
  "shape": [                                     // null per team when the match has no tracking
    { "length": 41.2, "width": 46.8, "area": 1290, "def": 31.0, "mid": 44.5, "att": 66.0,
      "gap_dm": 13.5, "gap_ma": 21.5, "def_w": 38.0, "mid_w": 30.1, "att_w": 35.2 },
    null
  ]
}]}
```

Definitions (also shown in the UI):

- `chaos = 100 * (0.30 turnovers + 0.20 duels + 0.20 transitions + 0.15 long_share + 0.15 (1 - avg_seq))`, each
  ingredient scaled 0-1 between the 10th and 90th percentile of 12,710 five-minute windows of the 2022 World Cup
  (`backend/scripts/calibrate_flow.py`): turnovers/min 0.2-1.0, duels+fouls/min 0.6-2.0, fast transitions/min
  0-0.4, long-ball share 0.05-0.20, passes per possession 3.4-10 (inverted). 50 = a typical window.
- `control(team) = 100 * (0.35 possession + 0.25 pass accuracy(0.58-0.925) + 0.25 settled share + 0.15 final-third share)`;
  a settled possession has 4+ passes.
- `tempo` = passes per minute of ball in play; `bip` = share of the window with the ball in play (dead time =
  end of the event before a restart until the restart).
- Pattern rules, first match wins: `stop_start` bip < 0.47; `end_to_end` fast transitions >= 0.6/min or
  (long_share > 0.15 and turnovers > 0.8/min); `siege` one team has >= 85% of final-third passes and at least 10
  of them; `settled` avg_seq >= 7.5 and turnovers <= 0.6/min; `high_tempo` tempo >= 17.5; else `balanced`.
  On the World Cup this gives balanced 43%, siege 15%, settled 11%, end to end / high tempo / stop-start 10% each.
- Everything is causal: a stoppage counts once play restarts, a possession is held up to its latest event so far,
  a transition counts from the moment it reaches the final third.
- Shape: outfield players only. Broadcast tracking only sees players on camera, so a player counts where he was
  observed in the last 5 s, a team needs 8+ such outfield players, dead-ball seconds are skipped, and a point is
  the median of per-second samples over the last 30 s. `length` = deepest to highest, `width` = widest left to
  widest right, `def/mid/att` = mean height of each unit, `*_w` = a unit's internal width, `gap_*` = height
  difference. Compact reference: length <= 35, width <= 40, unit gaps <= 14.
- Tracking and event data spell player ids differently for some players; (team, shirt number) is the person key.

### `GET /v1/matches/{id}/matchday/moments?to_ms=`

Moments are detected once and rendered per perspective and language by the UI.

```jsonc
{ "moments": [{
  "id": "mo-0042", "t_ms": 4680000, "clock": "79′",
  "kind": "goal", "variant": null,               // goal | chance | card | sub | flow | shape | speed | pass | milestone
  "side": 1, "team_id": "t-azu", "player_id": "p-9c1d", "player2_id": null,
  "imp": 0.86,                                   // 0-1 importance
  "f": { "xg": 0.78, "spd": 102, "dist": 11, "sa": 2, "sb": 1, "pen": true, "wcB": 9, "wcA": 31 }
}]}
```

Units: percentages in `f` (`poss`, `acc`, `bip`, `lb`, `xpp`, `wcB`, `wcA`) are 0-100; shares in series `flow` are 0-1.
`side`/`team_id` is the team the moment is about; for a goal, the team credited with it (for an own goal, the team that
benefits, while `player_id` is the player who put it into his own net). For a goal `player2_id` is the assister (the
completed pass to the scorer in the 15 s before the shot; none for penalties); for a pass it is the receiver; for a
substitution `player_id` comes on and `player2_id` goes off. No moments are emitted for the penalty shootout (the
commentary covers it).

Variants and the fields `f` carries (all template placeholders the UI needs):

| kind.variant | f |
|---|---|
| `goal` | xg, spd, dist, sa, sb, pen, own_goal, wcB, wcA (scoring side's win %, before/after) |
| `chance` | xg, spd, dist, txg (team xG so far) |
| `card` | card (`yellow`/`red`/`second_yellow`), fouls (team fouls last 10′) |
| `sub` | behind (bool), km, sprints (of the player going off = `player2_id`) |
| `pass` | pdist, diff (0-100), xpp (completion %) |
| `flow.chaos` | chaos, tov, tr, du, lb, seq |
| `flow.control` | ctrl, poss, acc |
| `flow.rhythm` | pattern, tempo, bip, seq |
| `shape.stretched` / `shape.lowblock` / `shape.highline` | len, wid, def, gap, area |
| `speed.sprint` | spd, km, sprints |
| `speed.rocket` | spd, dist, xg |
| `milestone.km10` | km, sprints |

### `GET /v1/matches/{id}/matchday/player/{player_id}?at_ms=`

```jsonc
{ "player_id": "p-1a2b", "on_pitch": true, "minutes": 57.5, "dist_km": 6.81, "top_kmh": 31.4, "sprints": 14,
  "touches": 48, "passes": 31, "passes_ok": 27, "pass_diff": 34, "shots": 2, "xg": 0.41, "goals": 1, "duels_won": 3,
  "heat": { "cols": 21, "rows": 14, "counts": [0, 3, ...] },   // row-major counts[row * cols + col]: rows along y (0 -> 68),
                                                               // cols along x (0 -> 105, home attacks left to right); null without tracking
  "actions": [{ "t_ms": 3361000, "clock": "57′", "type": "Pass", "detail": "-> Ibarra · 24 m · 41/100", "ok": true }] }
```

## Commentary

### `GET /v1/matches/{id}/commentary?lang=en|es|hi&from_ms=&to_ms=`

Lines with `from_ms < t_ms <= to_ms`, generated from past events only.

```jsonc
{ "lang": "es", "tts": "azure",                   // "azure" when audio is available, else "none"
  "lines": [{
    "id": "c-es-000731", "t_ms": 4679400, "clock": "79′",
    "speaker": "pbp",                              // pbp = play-by-play, colour = analyst
    "text": "¡Lo pone de penal! ¡GOOOOL de Ibarra!",
    "excitement": 3,                               // 0 calm .. 3 goal call
    "priority": 1,                                 // 1 must play (interrupts) .. 3 droppable
    "interrupts": true,                            // this line cuts off the one still playing (goal call, or an attack cutting the analyst off)
    "kind": "goal", "dur_ms": 3100,
    "audio_url": "/v1/matches/m-7f3a/commentary/audio/c-es-000731?lang=es"
  }]}
```

Client playback rules: one voice at a time; a priority-1 line, or any line with `interrupts`, cuts off whatever is playing; a priority-3
line is skipped if it would start more than 2.5 s late; captions show every line even when audio is off.

### `GET /v1/matches/{id}/commentary/audio/{line_id}?lang=`

`audio/mpeg` (Azure neural TTS, cached server-side). `503` when speech is not configured: the client then uses
the browser's `speechSynthesis` with the line text.
