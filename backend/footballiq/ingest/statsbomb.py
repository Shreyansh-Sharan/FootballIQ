"""StatsBomb adapter: download to bronze, normalise to silver; the normalisers are pure, so Fabric reuses them.

StatsBomb open data: free for non-commercial use with attribution (https://github.com/statsbomb/open-data).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from footballiq import config
from footballiq.pitch import statsbomb_to_canonical
from footballiq.schema import (
    PERIOD_BASE_MINUTE,
    PERIOD_LABELS,
    FreezeFrame,
    FreezeFramePlayer,
    Match,
    MatchEvent,
    Period,
    Player,
    Team,
)

PROVIDER = "statsbomb"
BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
ATTRIBUTION = "Data: StatsBomb open data (https://github.com/statsbomb/open-data)"
NOMINAL_PERIOD_MIN = {1: 45, 2: 45, 3: 15, 4: 15}

# event types whose missing outcome means success
IMPLICIT_SUCCESS = {"Pass": "Complete", "Ball Receipt*": "Complete"}


# --------------------------------------------------------------------------- helpers


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_timestamp_ms(ts: str) -> int:
    """'00:52:34.569' -> 3154569"""
    h, m, s = ts.split(":")
    return int(round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000))


def clock_label(period: int, period_elapsed_ms: int) -> str:
    """Scoreboard-style clock, e.g. '22:24', '45+07:34', 'PEN'."""
    if period >= 5:
        return "PEN"
    base = PERIOD_BASE_MINUTE[period]
    nominal_ms = NOMINAL_PERIOD_MIN[period] * 60_000
    if period_elapsed_ms < nominal_ms:
        total_s = base * 60 + period_elapsed_ms // 1000
        return f"{total_s // 60:02d}:{total_s % 60:02d}"
    over_s = (period_elapsed_ms - nominal_ms) // 1000
    return f"{base + NOMINAL_PERIOD_MIN[period]}+{over_s // 60:02d}:{over_s % 60:02d}"


def _qualifier_key(type_name: str) -> str:
    return {
        "Ball Receipt*": "ball_receipt",
        "Goal Keeper": "goalkeeper",
        "50/50": "50_50",
    }.get(type_name, type_name.lower().replace(" ", "_"))


def _name(obj: dict | None) -> str | None:
    return obj.get("name") if isinstance(obj, dict) else None


# --------------------------------------------------------------------------- bronze


def download_match(
    match_id: int = config.STATSBOMB_FINAL_MATCH_ID,
    competition_id: int = config.STATSBOMB_WC2022["competition_id"],
    season_id: int = config.STATSBOMB_WC2022["season_id"],
    out_dir: Path | None = None,
    retries: int = 4,
) -> Path:
    """Download raw StatsBomb JSON for one match into the immutable bronze tier."""
    import httpx

    out = (out_dir or config.bronze_dir()) / PROVIDER / str(match_id)
    out.mkdir(parents=True, exist_ok=True)
    assets = {
        "matches.json": f"{BASE_URL}/matches/{competition_id}/{season_id}.json",
        "events.json": f"{BASE_URL}/events/{match_id}.json",
        "lineups.json": f"{BASE_URL}/lineups/{match_id}.json",
        "three-sixty.json": f"{BASE_URL}/three-sixty/{match_id}.json",
    }
    manifest: dict[str, Any] = {
        "provider": PROVIDER,
        "match_id": match_id,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "attribution": ATTRIBUTION,
        "files": {},
    }
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for fname, url in assets.items():
            for attempt in range(retries + 1):
                try:
                    resp = client.get(url)
                    if resp.status_code == 404 and fname == "three-sixty.json":
                        break  # 360 is not available for every match
                    resp.raise_for_status()
                    (out / fname).write_bytes(resp.content)
                    manifest["files"][fname] = {
                        "url": url,
                        "sha256": hashlib.sha256(resp.content).hexdigest(),
                        "bytes": len(resp.content),
                    }
                    break
                except httpx.HTTPError:
                    if attempt == retries:
                        raise
                    time.sleep(2 ** (attempt + 1))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out


def load_bronze(match_id: int, bronze: Path | None = None) -> dict[str, Any]:
    base = (bronze or config.bronze_dir()) / PROVIDER / str(match_id)
    raw = {
        "matches": json.loads((base / "matches.json").read_text()),
        "events": json.loads((base / "events.json").read_text()),
        "lineups": json.loads((base / "lineups.json").read_text()),
        "three_sixty": [],
    }
    if (base / "three-sixty.json").exists():
        raw["three_sixty"] = json.loads((base / "three-sixty.json").read_text())
    return raw


# --------------------------------------------------------------------------- silver


def _period_table(raw_events: list[dict]) -> list[Period]:
    durations: dict[int, int] = {}
    for ev in raw_events:
        p, t = ev["period"], parse_timestamp_ms(ev["timestamp"])
        if ev["type"]["name"] == "Half End":
            durations[p] = max(durations.get(p, 0), t)
        else:
            durations.setdefault(p, 0)
            durations[p] = max(durations[p], t)
    periods, start = [], 0
    for p in sorted(durations):
        periods.append(Period(period=p, label=PERIOD_LABELS.get(p, f"Period {p}"), start_match_ms=start, duration_ms=durations[p]))
        start += durations[p]
    return periods


def format_formation(value: int | str | None) -> str | None:
    """StatsBomb encodes formations as digits (4231, 41212); render them as "4-2-3-1"."""
    digits = str(value) if value is not None else ""
    return "-".join(digits) if digits.isdigit() else None


def normalize_match(raw: dict[str, Any], match_id: int) -> tuple[Match, list[MatchEvent], list[FreezeFrame]]:
    """Convert raw StatsBomb JSON into canonical match, events and 360 snapshots."""
    meta = next(m for m in raw["matches"] if m["match_id"] == match_id)
    home_name = meta["home_team"]["home_team_name"]
    away_name = meta["away_team"]["away_team_name"]
    home = Team(team_id=slugify(home_name), name=home_name, source_ids={PROVIDER: meta["home_team"]["home_team_id"]})
    away = Team(team_id=slugify(away_name), name=away_name, source_ids={PROVIDER: meta["away_team"]["away_team_id"]})
    sb_team_to_canonical = {home.source_ids[PROVIDER]: home.team_id, away.source_ids[PROVIDER]: away.team_id}
    home_sb_id = home.source_ids[PROVIDER]

    canonical_match_id = f"{meta['match_date']}_{home.team_id}_{away.team_id}"

    starters: set[int] = set()
    for ev in raw["events"]:
        if ev["type"]["name"] == "Starting XI":
            starters.update(p["player"]["id"] for p in ev["tactics"]["lineup"])

    players: list[Player] = []
    sb_player_to_canonical: dict[int, str] = {}
    for team_block in raw["lineups"]:
        team_id = sb_team_to_canonical[team_block["team_id"]]
        for p in team_block["lineup"]:
            pid = f"{team_id}_{slugify(p['player_name'])}"
            sb_player_to_canonical[p["player_id"]] = pid
            players.append(
                Player(
                    player_id=pid,
                    team_id=team_id,
                    name=p["player_name"],
                    nickname=p.get("player_nickname"),
                    jersey_number=p.get("jersey_number"),
                    starter=p["player_id"] in starters,
                    source_ids={PROVIDER: p["player_id"]},
                )
            )

    periods = _period_table(raw["events"])
    period_start = {p.period: p.start_match_ms for p in periods}

    events: list[MatchEvent] = []
    for ev in raw["events"]:
        type_name = ev["type"]["name"]
        qual = ev.get(_qualifier_key(type_name)) or {}
        sb_team = ev.get("team", {}).get("id")
        is_home = sb_team == home_sb_id
        period = ev["period"]
        period_ms = parse_timestamp_ms(ev["timestamp"])

        outcome = _name(qual.get("outcome")) or IMPLICIT_SUCCESS.get(type_name)
        subtype = _name(qual.get("type"))
        if type_name == "Substitution":
            subtype = _name(qual.get("outcome"))
            outcome = None
        card = _name(qual.get("card"))

        recipient = qual.get("recipient") or qual.get("replacement")
        loc = statsbomb_to_canonical(ev.get("location"), is_home)
        end = statsbomb_to_canonical(qual.get("end_location"), is_home)
        player = ev.get("player")

        is_goal = type_name == "Shot" and outcome == "Goal"
        is_own_goal = type_name == "Own Goal For"

        events.append(
            MatchEvent(
                event_id=ev["id"],
                match_id=canonical_match_id,
                provider=PROVIDER,
                source_sequence=ev["index"],
                period=period,
                period_elapsed_ms=period_ms,
                match_elapsed_ms=period_start[period] + period_ms,
                clock_label=clock_label(period, period_ms),
                team_id=sb_team_to_canonical.get(sb_team),
                team_name=_name(ev.get("team")),
                player_id=sb_player_to_canonical.get(player["id"]) if player else None,
                player_name=_name(player),
                type=type_name,
                subtype=subtype,
                outcome=outcome,
                x_m=loc[0] if loc else None,
                y_m=loc[1] if loc else None,
                end_x_m=end[0] if end else None,
                end_y_m=end[1] if end else None,
                source_location=ev.get("location"),
                possession=ev.get("possession"),
                possession_team_id=sb_team_to_canonical.get((ev.get("possession_team") or {}).get("id")),
                play_pattern=_name(ev.get("play_pattern")),
                duration_ms=int(round(ev["duration"] * 1000)) if ev.get("duration") is not None else None,
                under_pressure=bool(ev.get("under_pressure")),
                is_goal=is_goal,
                is_own_goal=is_own_goal,
                is_shootout=period >= 5,
                provider_xg=qual.get("statsbomb_xg") if type_name == "Shot" else None,
                card=card,
                recipient_id=sb_player_to_canonical.get(recipient["id"]) if recipient else None,
                recipient_name=_name(recipient),
                related_events=ev.get("related_events", []),
                formation=format_formation((ev.get("tactics") or {}).get("formation")),
            )
        )

    events.sort(key=lambda e: (e.match_elapsed_ms, e.source_sequence))
    by_id = {e.event_id: e for e in events}

    frames: list[FreezeFrame] = []
    for ff in raw.get("three_sixty", []):
        ev = by_id.get(ff["event_uuid"])
        if ev is None or ev.team_id is None:
            continue
        actor_is_home = ev.team_id == home.team_id
        other = away.team_id if actor_is_home else home.team_id
        ff_players = []
        for p in ff.get("freeze_frame", []):
            xy = statsbomb_to_canonical(p["location"], actor_is_home)
            if xy is None:
                continue
            ff_players.append(
                FreezeFramePlayer(
                    x_m=xy[0], y_m=xy[1],
                    team_id=ev.team_id if p["teammate"] else other,
                    teammate=p["teammate"], actor=p["actor"], keeper=p["keeper"],
                )
            )
        va = ff.get("visible_area") or []
        polygon = [list(statsbomb_to_canonical(va[i:i + 2], actor_is_home)) for i in range(0, len(va) - 1, 2)]
        ev.has_freeze_frame = True
        frames.append(FreezeFrame(event_id=ev.event_id, match_elapsed_ms=ev.match_elapsed_ms, players=ff_players, visible_area=polygon))
    frames.sort(key=lambda f: f.match_elapsed_ms)

    shootout = {home.team_id: 0, away.team_id: 0}
    for e in events:
        if e.is_goal and e.is_shootout:
            shootout[e.team_id] += 1

    match = Match(
        canonical_match_id=canonical_match_id,
        competition=meta["competition"]["competition_name"],
        season=meta["season"]["season_name"],
        stage=_name(meta.get("competition_stage")),
        kickoff_source=f"{meta['match_date']} {meta.get('kick_off') or ''}".strip(),
        stadium=_name(meta.get("stadium")),
        referee=_name(meta.get("referee")),
        home=home,
        away=away,
        periods=periods,
        duration_ms=periods[-1].start_match_ms + periods[-1].duration_ms,
        source_ids={PROVIDER: match_id, "pff": config.PFF_FINAL_GAME_ID} if match_id == config.STATSBOMB_FINAL_MATCH_ID else {PROVIDER: match_id},
        players=players,
        result={
            "home_score": meta["home_score"],
            "away_score": meta["away_score"],
            "shootout": shootout if any(shootout.values()) else None,
        },
        attribution=ATTRIBUTION,
    )
    return match, events, frames


def write_silver(match: Match, events: list[MatchEvent], frames: list[FreezeFrame], silver: Path | None = None) -> Path:
    out = (silver or config.silver_dir()) / match.canonical_match_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "match.json").write_text(match.model_dump_json(indent=2))
    with (out / "events.jsonl").open("w") as fh:
        for e in events:
            fh.write(e.model_dump_json() + "\n")
    with (out / "freeze_frames.jsonl").open("w") as fh:
        for f in frames:
            fh.write(f.model_dump_json() + "\n")
    # provider -> canonical id map
    with (out / "id_map.jsonl").open("w") as fh:
        rows = [{"entity": "match", "canonical_id": match.canonical_match_id, "provider": k, "provider_id": v} for k, v in match.source_ids.items()]
        for t in (match.home, match.away):
            rows += [{"entity": "team", "canonical_id": t.team_id, "provider": k, "provider_id": v} for k, v in t.source_ids.items()]
        for p in match.players:
            rows += [{"entity": "player", "canonical_id": p.player_id, "provider": k, "provider_id": v} for k, v in p.source_ids.items()]
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Ingest a StatsBomb open-data match into bronze + silver")
    ap.add_argument("--match-id", type=int, default=config.STATSBOMB_FINAL_MATCH_ID)
    ap.add_argument("--competition-id", type=int, default=config.STATSBOMB_WC2022["competition_id"])
    ap.add_argument("--season-id", type=int, default=config.STATSBOMB_WC2022["season_id"])
    ap.add_argument("--skip-download", action="store_true", help="Re-normalise existing bronze files")
    args = ap.parse_args(argv)

    if not args.skip_download:
        path = download_match(args.match_id, args.competition_id, args.season_id)
        print(f"bronze: {path}")
    match, events, frames = normalize_match(load_bronze(args.match_id), args.match_id)
    out = write_silver(match, events, frames)
    print(f"silver: {out}  ({len(events)} events, {len(frames)} 360 snapshots, {len(match.periods)} periods)")


if __name__ == "__main__":
    main()
