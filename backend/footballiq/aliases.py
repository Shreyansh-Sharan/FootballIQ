"""Fictional names and public ids for everything a client sees.

``AliasedStore`` renames data in place as it leaves the store; ``AliasBook.to_public`` scrubs every outbound payload.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import unicodedata
import weakref
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ENV_SWITCH = "FOOTBALLIQ_PSEUDONYMS"
ENV_SALT = "FOOTBALLIQ_ALIAS_SALT"
DEFAULT_SALT = "fiq-alias-v1"
NAME_SEED = "fiq-names-v1"            # fixed across deployments, unlike the id salt
POOLS_PATH = Path(__file__).with_name("data") / "name_pools.json"

ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"   # Crockford base32, lower case
ID_LEN = 6
ALIAS_RE = re.compile(r"^[mtp]-[0-9a-hjkmnp-tv-z]{6}$")
_DATE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_")
_ID_TOKEN = re.compile(r"[0-9a-z][0-9a-z-]*(?:_[0-9a-z-]+)+")
_ALIAS_TOKEN = re.compile(r"(?<![0-9a-z-])[mtp]-[0-9a-hjkmnp-tv-z]{6}(?![0-9a-z])")
_TOKEN = re.compile(r"[^\W_]+")
_SEP_OK = re.compile(r"[\s\-'’.]{1,3}")

_PARTICLES = {"de", "di", "da", "del", "della", "dalla", "van", "von", "der", "den", "le", "la", "mac", "mc", "dos", "das",
              "do", "du", "ter", "ten", "st", "al", "el", "ben", "bin", "abu", "ibn", "dei", "des", "zu", "af"}
_SUFFIXES = {"junior", "jr", "filho", "neto", "sobrinho", "ii", "iii"}
_FOLD = {"ø": "o", "ł": "l", "đ": "d", "ß": "s", "æ": "a", "œ": "o", "ı": "i", "ð": "d", "þ": "t", "ħ": "h", "ŀ": "l"}

# values under these keys are enums, ids or labels, never free text
ENUM_KEYS = frozenset({
    "event_id", "type", "subtype", "outcome", "play_pattern", "card", "position_group", "position", "role", "formation",
    "declared_formation", "raw_formation", "from_formation", "to_formation", "clock_label", "clock", "period_label",
    "kind", "variant", "category", "source", "method", "provider", "pattern", "zone", "speaker", "lang", "tts", "model",
    "model_version", "mode", "status", "phase", "side", "situation", "target", "target_name", "window_id", "id",
    "insight_id", "thread_id", "run_id", "agent_id", "minute", "replay_clock", "date", "kickoff_utc", "kickoff_source",
    "season", "stage", "jersey", "jersey_num", "direction_convention", "attribution", "confidence", "primary",
    "secondary", "ink", "unit", "version"})
_PLAYER_NAME_KEYS = {"name": "name", "player_name": "name", "player": "name", "display_name": "name", "full_name": "name",
                     "short": "short", "short_name": "short", "nickname": "nickname", "name_hi": "name_hi",
                     "short_hi": "short_hi"}
_TEAM_NAME_KEYS = {"name": "name", "team_name": "name", "short": "short", "name_hi": "name_hi", "short_hi": "short_hi"}
_LINKED_NAME_KEYS = (("recipient_id", ("recipient_name", "recipient"), "player"),
                     ("opponent_id", ("opponent", "opponent_name"), "team"))
_JERSEY_KEYS = ("jersey", "jersey_num", "jersey_number", "number")


# --------------------------------------------------------------------------- small helpers
def pseudonyms_enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "on").strip().lower() not in ("off", "0", "false", "no", "disabled")


def _fold_char(ch: str) -> str:
    if ch < "\x80":
        return ch.lower()
    low = ch.lower()[:1]
    if low in _FOLD:
        return _FOLD[low]
    base = unicodedata.normalize("NFD", low)[:1]
    return base or ch


def fold(s: str) -> str:
    """Lower-case, accent-free copy of ``s``; same length, so spans map back."""
    return s.lower() if s.isascii() else "".join(_fold_char(c) for c in s)


def name_key(s: str | None) -> tuple[str, ...]:
    """Tokens of a name for matching: case, accents, hyphens and apostrophes ignored."""
    if not s:
        return ()
    if not s.isascii():
        s = unicodedata.normalize("NFC", s)
    return tuple(_TOKEN.findall(fold(s)))


def _h(*parts: object) -> int:
    return int.from_bytes(hashlib.blake2b("\x1f".join(map(str, parts)).encode(), digest_size=8).digest(), "big")


def _b32(value: int, n: int = ID_LEN) -> str:
    out = []
    for _ in range(n):
        out.append(ID_ALPHABET[value & 31])
        value >>= 5
    return "".join(out)


def surname_keys(name: str | None, family_first: bool = False) -> list[tuple[str, ...]]:
    """Name keys for a surname on its own, particles included ("Di María", "Mac Allister")."""
    words = (name or "").split()
    if not words:
        return []
    if len(words) == 1 or family_first:
        return [name_key(words[0])]
    while len(words) > 1 and fold(words[-1]).strip(".") in _SUFFIXES:
        words.pop()
    if len(words) == 1:
        return [name_key(words[0])]
    last = [words[-1]]
    i = len(words) - 2
    while i >= 1 and fold(words[i]) in _PARTICLES:
        last.insert(0, words[i])
        i -= 1
    keys = [name_key(" ".join(last))]
    if len(words) >= 3 and len(last) == 1:          # two-word surnames, e.g. "Kolo Muani"
        keys.append(name_key(" ".join(words[-2:])))
    return keys


def _plural_form(real: str) -> bool:
    low = real.lower()
    return low.endswith("men") or (low.endswith("s") and not low.endswith("ss") and not low.endswith("ese"))


def _jersey_int(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- public records
@dataclass(frozen=True)
class TeamAlias:
    canonical_id: str
    public_id: str
    name: str
    short: str
    name_hi: str
    short_hi: str
    demonym: str
    colors: dict[str, str]
    kind: str = "club"


@dataclass(frozen=True)
class PlayerAlias:
    canonical_id: str
    public_id: str
    team_id: str
    name: str
    short: str
    name_hi: str
    short_hi: str
    culture: str = ""


@dataclass(frozen=True)
class NameAlias:
    """Fictional referee, stadium or competition."""
    name: str
    name_hi: str


@dataclass
class _Pool:
    first: list[tuple[str, str]]
    last: list[tuple[str, str]]
    order: str


@dataclass
class _MatchInfo:
    match_id: str
    teams: list[str] = field(default_factory=list)
    names: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))    # primary player id -> real names
    jersey: dict[tuple[str, int], str] = field(default_factory=dict)                  # (team, shirt) -> primary id
    primaries: set[str] = field(default_factory=set)
    referee: str | None = None
    stadium: str | None = None
    competition: str | None = None
    version: int = 0


class _Scrubber:
    """Real-name keys (token tuples) -> fictional replacement."""

    __slots__ = ("keys", "maxn")

    def __init__(self) -> None:
        self.keys: dict[tuple[str, ...], str] = {}
        self.maxn = 0

    def add(self, key: tuple[str, ...], repl: str, stop: frozenset[str] = frozenset()) -> None:
        if not key or not repl:
            return
        if len(key) == 1 and (len(key[0]) < 3 or key[0] in stop or key[0].isdigit()):
            return
        if name_key(repl) == key:
            return
        self.keys.setdefault(key, repl)
        self.maxn = max(self.maxn, len(key))


# id(match) -> real names captured before in-place renaming, so a fresh book can recover them
_REAL_BY_ID: dict[int, dict[str, Any]] = {}
_REAL_LOCK = threading.Lock()


def _capture_match(m: Any) -> dict[str, Any]:
    return {"match_id": m.canonical_match_id, "competition": m.competition, "stadium": m.stadium, "referee": m.referee,
            "home": m.home.team_id, "away": m.away.team_id,
            "teams": {m.home.team_id: m.home.name, m.away.team_id: m.away.name},
            "players": [[p.player_id, p.team_id, p.jersey_number, p.name, p.nickname] for p in m.players]}


def _real_of_match(m: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    key = id(m)
    with _REAL_LOCK:
        real = _REAL_BY_ID.get(key)
        if real is not None and real["match_id"] == m.canonical_match_id:
            return real
        real = fallback if fallback is not None else _capture_match(m)
        _REAL_BY_ID[key] = real
    try:
        weakref.finalize(m, _REAL_BY_ID.pop, key, None)
    except TypeError:  # not weak-referenceable; bounded by the catalogue size
        pass
    return real


# --------------------------------------------------------------------------- the book
class AliasBook:
    """Process-wide registry of fictional names and public ids; deterministic for a catalogue and salt."""

    def __init__(self, pools: dict[str, Any] | None = None, salt: str | None = None, enabled: bool | None = None):
        self._enabled = enabled            # None: follow FOOTBALLIQ_PSEUDONYMS at call time
        self.salt = salt if salt is not None else os.environ.get(ENV_SALT, DEFAULT_SALT)
        self.pools = pools if pools is not None else json.loads(POOLS_PATH.read_text(encoding="utf-8"))
        self.signature = f"{self.pools.get('version', 1)}:{NAME_SEED}"
        self._lock = threading.RLock()
        self._cultures = self._load_cultures()
        self._stop = frozenset(fold(w) for w in self.pools.get("stopwords", []))
        self._famous = frozenset(t for w in self.pools.get("famous_surnames", []) for t in name_key(w))
        # registry
        self._can2pub: dict[str, str] = {}
        self._pub2can: dict[str, str] = {}
        self._kind: dict[str, str] = {}
        # teams
        self._teams: dict[str, TeamAlias] = {}
        self._team_culture: dict[str, list[tuple[str, float]]] = {}
        self._real_team_names: dict[str, set[str]] = defaultdict(set)
        self._used_team_names = {fold(t["name"]) for t in self.pools.get("teams", {}).values()}
        self._used_team_shorts = {t["short"] for t in self.pools.get("teams", {}).values()}
        # players
        self._team_players: dict[str, set[str]] = defaultdict(set)
        self._player_team: dict[str, str] = {}
        self._players: dict[str, PlayerAlias] = {}
        self._link: dict[str, str] = {}
        self._extra: set[str] = set()          # ids first seen outside a match line-up (tracking, gold tables)
        self._used_last: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        self._used_full: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        # real-name tokens and full names that generated names must avoid
        self._reserved: set[str] = set()
        self._real_full: set[tuple[str, ...]] = set()
        self._fictional_full: set[tuple[str, ...]] = set()
        for t in self.pools.get("teams", {}).values():
            for s in [*t.get("real_aka", []), *t.get("real_aka_local", []), *t.get("real_demonyms", [])]:
                self._reserved.update(name_key(s))
        # matches
        self._matches: dict[str, _MatchInfo] = {}
        self._registered: set[tuple[str, str]] = set()
        self._seen: weakref.WeakValueDictionary[int, Any] = weakref.WeakValueDictionary()
        self._renamed: weakref.WeakValueDictionary[int, Any] = weakref.WeakValueDictionary()
        # officials / venues / competitions
        self._officials: dict[str, NameAlias] = {}
        self._venues: dict[str, NameAlias] = {}
        self._pending_officials: set[str] = set()
        self._pending_venues: set[str] = set()
        self._fictional: dict[str, NameAlias] = {}       # fictional name -> alias (idempotent renames)
        self._competitions: dict[str, NameAlias] = {}
        for real, c in self.pools.get("competitions", {}).items():
            a = NameAlias(c["name"], c["name_hi"])
            self._competitions[fold(real)] = a
            self._fictional[a.name] = a
        for name, hi in self.pools.get("competition_fallback", []):
            self._fictional[name] = NameAlias(name, hi)
        # scrubbing
        self._version = 0
        self._global: tuple[int, _Scrubber] | None = None
        self._match_scrub: dict[str, tuple[tuple[int, int], _Scrubber]] = {}
        self._cache: dict[tuple[str | None, str], tuple[int, str]] = {}
        self._loaders: list[Any] = []

    @property
    def enabled(self) -> bool:
        return pseudonyms_enabled() if self._enabled is None else self._enabled

    # ------------------------------------------------------------------ pools
    def _load_cultures(self) -> dict[str, _Pool]:
        raw = self.pools.get("cultures", {})
        out = {}
        for key, c in raw.items():
            last = c.get("last") or raw.get(c.get("last_from", ""), {}).get("last", [])
            out[key] = _Pool([tuple(e) for e in c["first"]], [tuple(e) for e in last], c.get("order", "given_family"))
        return out

    # ------------------------------------------------------------------ public ids
    def _register_id(self, kind: str, canonical: str) -> str:
        pub = self._can2pub.get(canonical)
        if pub is not None:
            return pub
        with self._lock:
            pub = self._can2pub.get(canonical)
            if pub is not None:
                return pub
            for attempt in range(1000):
                digest = hashlib.sha256(f"{self.salt}|{kind}|{canonical}|{attempt}".encode()).digest()
                pub = f"{kind}-{_b32(int.from_bytes(digest[:8], 'big'))}"
                other = self._pub2can.get(pub)
                if other is None or other == canonical:
                    break
            self._pub2can[pub] = canonical
            self._can2pub[canonical] = pub
            self._kind[canonical] = kind
            return pub

    def match_public_id(self, match_id: str) -> str:
        return self._register_id("m", match_id)

    def team_public_id(self, team_id: str) -> str:
        return self.team(team_id).public_id

    def player_public_id(self, player_id: str) -> str:
        return self.player(player_id).public_id

    def to_canonical(self, public_id: str) -> str | None:
        """Canonical id for a public alias, or None; a canonical id passes through."""
        if not isinstance(public_id, str):
            return None
        can = self._pub2can.get(public_id)
        if can is not None:
            return can
        return None if ALIAS_RE.match(public_id) else (public_id if public_id in self._kind else None)

    def from_public(self, obj: Any) -> Any:
        """Deep copy of ``obj`` with every known public alias (values only) replaced by its canonical id."""
        t = type(obj)
        if t is str:
            if ALIAS_RE.match(obj):
                return self._pub2can.get(obj, obj)
            return _ALIAS_TOKEN.sub(lambda m: self._pub2can.get(m.group(), m.group()), obj) if "-" in obj else obj
        if t is dict:
            return {k: self.from_public(v) for k, v in obj.items()}
        if t is list or t is tuple:
            return [self.from_public(v) for v in obj]
        return obj

    # ------------------------------------------------------------------ loaders
    def add_loader(self, fn: Callable[[str | None], Any]) -> None:
        """``fn(match_id | None)`` registers the catalogue and that match; bound methods are held weakly."""
        ref = weakref.WeakMethod(fn) if hasattr(fn, "__self__") else (lambda f=fn: f)
        self._loaders.append(ref)

    def ensure_loaded(self, match_id: str | None = None) -> None:
        alive = []
        for ref in list(self._loaders):
            fn = ref()
            if fn is None:
                continue
            alive.append(ref)
            try:
                fn(match_id)
            except Exception:  # noqa: BLE001 - a broken source must not break id translation
                log.warning("alias loader failed", exc_info=True)
        self._loaders = alive

    # ------------------------------------------------------------------ teams
    def _culture_weights(self, team_id: str) -> list[tuple[str, float]]:
        w = self._team_culture.get(team_id)
        if w is None:
            curated = self.pools.get("teams", {}).get(team_id)
            w = [(c, float(x)) for c, x in curated["cultures"]] if curated else [("english", 1.0)]
            self._team_culture[team_id] = w
        return w

    def team(self, team_id: str) -> TeamAlias:
        a = self._teams.get(team_id)
        if a is not None:
            return a
        with self._lock:
            a = self._teams.get(team_id)
            if a is not None:
                return a
            pub = self._register_id("t", team_id)
            curated = self.pools.get("teams", {}).get(team_id)
            if curated:
                a = TeamAlias(team_id, pub, curated["name"], curated["short"], curated["name_hi"], curated["short_hi"],
                              curated.get("demonym", curated["name"]), dict(curated["colors"]), curated.get("kind", "club"))
            else:
                a = self._generated_team(team_id, pub)
            self._teams[team_id] = a
            self._fictional[a.name] = NameAlias(a.name, a.name_hi)
            self._version += 1
            return a

    def _generated_team(self, team_id: str, pub: str) -> TeamAlias:
        places = self.pools["places"]
        suffixes = self.pools["club_suffixes"]
        real = {k for n in self._real_team_names.get(team_id, ()) for k in [fold(n)]}
        for attempt in range(500):
            place, place_hi = places[_h(NAME_SEED, "team", team_id, attempt) % len(places)]
            suf, suf_hi = suffixes[_h(NAME_SEED, "suffix", team_id, attempt) % len(suffixes)]
            name = f"{place} {suf}"
            letters = re.sub(r"[^A-Za-z]", "", place).upper()
            short = letters[:3] if attempt < 50 else letters[0] + letters[-2:]
            if fold(name) in self._used_team_names or fold(name) in real or short in self._used_team_shorts:
                continue
            break
        self._used_team_names.add(fold(name))
        self._used_team_shorts.add(short)
        pal = self.pools["palettes"][_h(NAME_SEED, "kit", team_id) % len(self.pools["palettes"])]
        hi_short = place_hi.split()[0]
        return TeamAlias(team_id, pub, name, short, f"{place_hi} {suf_hi}", hi_short, f"{place.split()[0]}er",
                         {"primary": pal[0], "secondary": pal[1], "ink": pal[2], "pattern": pal[3]}, "club")

    # ------------------------------------------------------------------ players
    def _team_of(self, player_id: str) -> str:
        t = self._player_team.get(player_id)
        if t is not None:
            return t
        best = ""
        for tid in self._teams.keys() | self._team_players.keys():
            if player_id.startswith(tid + "_") and len(tid) > len(best):
                best = tid
        return best or (player_id.split("_", 1)[0] if "_" in player_id else "_unknown")

    def _resolve(self, player_id: str) -> str:
        return self._link.get(player_id, player_id)

    def player(self, player_id: str) -> PlayerAlias:
        pid = self._resolve(player_id)
        a = self._players.get(pid)
        if a is not None:
            return a
        with self._lock:
            pid = self._resolve(player_id)
            a = self._players.get(pid)
            if a is not None:
                return a
            team_id = self._team_of(pid)
            self._add_player(pid, team_id, extra=True)
            self._assign_pending(team_id)
            return self._players[pid]

    def _add_player(self, pid: str, team_id: str, extra: bool = False) -> None:
        if pid in self._player_team:
            if not extra:
                self._extra.discard(pid)
            return
        self._player_team[pid] = team_id
        self._team_players[team_id].add(pid)
        if extra:
            self._extra.add(pid)
        self._register_id("p", pid)

    def _assign_pending(self, team_id: str) -> None:
        # line-up first; extras reserve no names, so they never depend on each other
        pending = sorted((p in self._extra, p) for p in self._team_players.get(team_id, ())
                         if p not in self._players and p not in self._link)
        if not pending:
            return
        self.team(team_id)
        for extra, pid in pending:
            self._players[pid] = self._make_player(pid, team_id, extra)

    def _pick_culture(self, team_id: str, pid: str) -> str:
        weights = self._culture_weights(team_id)
        if len(weights) == 1:
            return weights[0][0]
        u = (_h(NAME_SEED, "culture", pid) % 10_000) / 10_000 * sum(w for _, w in weights)
        for c, w in weights:
            if u < w:
                return c
            u -= w
        return weights[-1][0]

    def _name_ok(self, first: str, last: str, team_id: str) -> bool:
        lk, fk = name_key(last), name_key(first)
        if len(fk) == 1 and fk[0] in self._famous:
            return False
        if not lk or lk in self._used_last[team_id] or set(lk) & set(fk):
            return False
        core = [t for t in lk if t not in _PARTICLES] or list(lk)
        if any(t in self._reserved or t in self._famous for t in core) or any(t in self._reserved for t in fk):
            return False
        full = fk + lk
        return full not in self._real_full and full not in self._used_full[team_id]

    def _make_player(self, pid: str, team_id: str, extra: bool = False) -> PlayerAlias:
        culture = self._pick_culture(team_id, pid)
        pool = self._cultures.get(culture) or self._cultures["english"]
        nf, nl = len(pool.first), len(pool.last)
        choice = None
        for attempt in range(48):
            f = pool.first[_h(NAME_SEED, "first", pid, attempt) % nf]
            l_ = pool.last[_h(NAME_SEED, "last", pid, attempt) % nl]
            if self._name_ok(f[0], l_[0], team_id):
                choice = (f, l_)
                break
        if choice is None:   # probes failed: deterministic sweep
            s0, f0 = _h(NAME_SEED, "sweep", pid) % nl, _h(NAME_SEED, "sweepf", pid) % nf
            for i in range(nl * nf):
                f, l_ = pool.first[(f0 + i // nl) % nf], pool.last[(s0 + i) % nl]
                if self._name_ok(f[0], l_[0], team_id):
                    choice = (f, l_)
                    break
        if choice is None:   # pool exhausted for this team: allow a repeat
            f, l_ = pool.first[_h(NAME_SEED, "x", pid) % nf], pool.last[_h(NAME_SEED, "y", pid) % nl]
            choice = (f, l_)
        (first, first_hi), (last, last_hi) = choice
        if pool.order == "family_given":
            name, name_hi = f"{last} {first}", f"{last_hi} {first_hi}"
        else:
            name, name_hi = f"{first} {last}", f"{first_hi} {last_hi}"
        if not extra:
            self._used_last[team_id].add(name_key(last))
            self._used_full[team_id].add(name_key(first) + name_key(last))
        self._fictional_full.add(name_key(name))
        return PlayerAlias(pid, self._register_id("p", pid), team_id, name, last, name_hi, last_hi, culture)

    def link_player(self, alt_id: str, primary_id: str) -> None:
        """Treat ``alt_id`` (e.g. a PFF roster id) as the same person as ``primary_id``: same public id and name."""
        if not alt_id or not primary_id or alt_id == primary_id:
            return
        with self._lock:
            primary_id = self._resolve(primary_id)
            if self._link.get(alt_id) == primary_id or alt_id == primary_id:
                return
            self._link[alt_id] = primary_id
            team = self._player_team.get(primary_id) or self._team_of(primary_id)
            self._add_player(primary_id, team)
            self._player_team.setdefault(alt_id, team)
            self._can2pub[alt_id] = self._register_id("p", primary_id)
            self._kind[alt_id] = "p"

    def link_jersey(self, match_id: str, team_id: str, jersey: Any, player_id: str) -> str | None:
        """Link ``player_id`` to the match player wearing ``jersey`` for ``team_id``; returns the primary id."""
        info = self._matches.get(match_id)
        num = _jersey_int(jersey)
        if info is None or num is None:
            return None
        primary = info.jersey.get((team_id, num))
        if primary and player_id and player_id != primary and player_id not in info.primaries:
            self.link_player(player_id, primary)
        return primary

    # ------------------------------------------------------------------ referee / stadium / competition
    def competition(self, real: str | None) -> NameAlias | None:
        if not real:
            return None
        if real in self._fictional:
            return self._fictional[real]
        a = self._competitions.get(fold(real))
        if a is None:
            fb = self.pools.get("competition_fallback") or [["Invitational Cup", "इनविटेशनल कप"]]
            name, hi = fb[_h(NAME_SEED, "comp", fold(real)) % len(fb)]
            a = NameAlias(name, hi)
            with self._lock:
                self._competitions[fold(real)] = a
                self._fictional[a.name] = a
                self._version += 1
        return a

    def official(self, real: str | None) -> NameAlias | None:
        """Fictional referee."""
        return self._named(real, self._officials, self._pending_officials, self._make_official)

    def venue(self, real: str | None) -> NameAlias | None:
        """Fictional stadium."""
        return self._named(real, self._venues, self._pending_venues, self._make_venue)

    referee = official
    stadium = venue

    def _named(self, real, table, pending, make) -> NameAlias | None:
        if not real or not real.strip():
            return None
        real = real.strip()
        if real in self._fictional:
            return self._fictional[real]
        k = fold(real)
        a = table.get(k)
        if a is not None:
            return a
        with self._lock:
            pending.add(k)
            for p in sorted(pending - table.keys()):      # batch, sorted: independent of lookup order
                table[p] = make(p)
                self._fictional[table[p].name] = table[p]
            pending.clear()
            self._version += 1
            return table[k]

    def _make_official(self, k: str) -> NameAlias:
        cultures = self.pools.get("referee_cultures") or ["english"]
        used = {fold(a.name) for a in self._officials.values()}
        for attempt in range(200):
            pool = self._cultures[cultures[_h(NAME_SEED, "refc", k, attempt) % len(cultures)]]
            f = pool.first[_h(NAME_SEED, "reff", k, attempt) % len(pool.first)]
            l_ = pool.last[_h(NAME_SEED, "refl", k, attempt) % len(pool.last)]
            lk = name_key(l_[0])
            core = [t for t in lk if t not in _PARTICLES] or list(lk)
            if any(t in self._reserved or t in self._famous for t in core) or (name_key(f[0]) + lk) in self._real_full:
                continue
            name = f"{l_[0]} {f[0]}" if pool.order == "family_given" else f"{f[0]} {l_[0]}"
            if fold(name) in used:
                continue
            hi = f"{l_[1]} {f[1]}" if pool.order == "family_given" else f"{f[1]} {l_[1]}"
            return NameAlias(name, hi)
        return NameAlias("Match Official", "मैच अधिकारी")

    def _make_venue(self, k: str) -> NameAlias:
        places, kinds = self.pools["places"], self.pools["venue_kinds"]
        used = {fold(a.name) for a in self._venues.values()}
        used_places = {a.name.rsplit(" ", 1)[0] for a in self._venues.values()}
        for attempt in range(500):
            p = places[_h(NAME_SEED, "venue", k, attempt) % len(places)]
            kind = kinds[_h(NAME_SEED, "vkind", k, attempt) % len(kinds)]
            name = f"{p[0]} {kind[0]}"
            if fold(name) not in used and (p[0] not in used_places or attempt >= 200):
                return NameAlias(name, f"{p[1]} {kind[1]}")
        return NameAlias("Central Stadium", "सेंट्रल स्टेडियम")

    # ------------------------------------------------------------------ registration
    def register_match(self, match: Any) -> None:
        """Register a match's ids and real names; idempotent, and safe on already-renamed objects."""
        if not self.enabled or match is None:
            return
        if self._seen.get(id(match)) is match:
            return
        real = _real_of_match(match)
        self._register_real(real)
        try:
            self._seen[id(match)] = match
        except TypeError:
            pass

    def register_matches(self, matches: list[Any]) -> None:
        for m in matches:
            self.register_match(m)

    def register_timeline(self, tl: Any) -> None:
        if not self.enabled or tl is None:
            return
        real = tl.__dict__.get("_fiq_real")
        if real is None:
            real = self._capture_timeline(tl)
            tl._fiq_real = real
        _real_of_match(tl.match, fallback=real["match"])
        self._register_real(real["match"])
        self._register_timeline_real(real)

    def _capture_timeline(self, tl: Any) -> dict[str, Any]:
        match_real = _real_of_match(tl.match)
        events: dict[str, set[str]] = defaultdict(set)
        for e in tl.events:
            if e.player_id and e.player_name:
                events[e.player_id].add(e.player_name)
            if e.recipient_id and e.recipient_name:
                events[e.recipient_id].add(e.recipient_name)
        tr = getattr(tl, "tracking", None)
        roster = [[p.player_id, p.team_id, p.jersey_num, p.name] for p in (tr.players if tr is not None else [])]
        return {"match": match_real, "events": {k: sorted(v) for k, v in events.items()}, "roster": roster}

    def _learn_name(self, info: _MatchInfo, pid: str, team_id: str, name: str | None) -> None:
        if not name or not name.strip():
            return
        k = name_key(name)
        if k in self._fictional_full:                  # renamed data seen again
            return
        info.names[pid].add(name)
        if len(k) >= 2:
            self._real_full.add(k)
        family_first = self._culture_weights(team_id)[0][0] == "korean"
        for sk in surname_keys(name, family_first):
            self._reserved.update(t for t in sk if t not in _PARTICLES)

    def _register_real(self, real: dict[str, Any]) -> None:
        mid = real["match_id"]
        if (mid, "match") in self._registered:
            return
        with self._lock:
            if (mid, "match") in self._registered:
                return
            self._register_id("m", mid)
            info = self._matches.setdefault(mid, _MatchInfo(mid))
            info.teams = [real["home"], real["away"]]
            for tid, tname in real["teams"].items():
                self._register_id("t", tid)
                self._culture_weights(tid)
                if tname and tname not in self._fictional and not (tid in self._teams and self._teams[tid].name == tname):
                    self._real_team_names[tid].add(tname)
                    self._reserved.update(name_key(tname))
            for pid, tid, jersey, name, nick in real["players"]:
                self._add_player(pid, tid)
                info.primaries.add(pid)
                num = _jersey_int(jersey)
                if num is not None:
                    info.jersey.setdefault((tid, num), pid)
                self._learn_name(info, pid, tid, name)
                self._learn_name(info, pid, tid, nick)
            for attr, pending in (("referee", self._pending_officials), ("stadium", self._pending_venues)):
                v = (real.get(attr) or "").strip() or None
                setattr(info, attr, v)
                if v and v not in self._fictional:
                    pending.add(fold(v))
                    if attr == "referee":
                        self._real_full.add(name_key(v))
                        for sk in surname_keys(v):
                            self._reserved.update(t for t in sk if t not in _PARTICLES)
            info.competition = real.get("competition")
            info.version += 1
            self._registered.add((mid, "match"))
            self._version += 1

    def _register_timeline_real(self, real: dict[str, Any]) -> None:
        mid = real["match"]["match_id"]
        if (mid, "timeline") in self._registered:
            return
        with self._lock:
            if (mid, "timeline") in self._registered:
                return
            info = self._matches[mid]
            for pid, names in real.get("events", {}).items():
                tid = self._player_team.get(pid) or self._team_of(pid)
                self._add_player(pid, tid, extra=True)
                for n in names:
                    self._learn_name(info, self._resolve(pid), tid, n)
            for pid, tid, jersey, name in real.get("roster", []):
                num = _jersey_int(jersey)
                primary = info.jersey.get((tid, num)) if num is not None else None
                if pid and primary and pid != primary and pid not in info.primaries:
                    self.link_player(pid, primary)
                elif pid:
                    self._add_player(pid, tid, extra=True)
                owner = primary or pid
                if owner:
                    self._learn_name(info, self._resolve(owner), tid, name)
            info.version += 1
            self._registered.add((mid, "timeline"))
            self._version += 1

    # ------------------------------------------------------------------ renaming
    def rename_match(self, match: Any) -> Any:
        if not self.enabled or match is None:
            return match
        if self._renamed.get(id(match)) is match:
            return match
        self.register_match(match)
        real = _real_of_match(match)
        for team in (match.home, match.away):
            team.name = self.team(team.team_id).name
        for p in match.players:
            a = self.player(p.player_id)
            p.name = a.name
            p.nickname = a.short if p.nickname else None
        ref, ven, comp = self.official(real.get("referee")), self.venue(real.get("stadium")), self.competition(real.get("competition"))
        match.referee = ref.name if ref else None
        match.stadium = ven.name if ven else None
        if comp:
            match.competition = comp.name
        try:
            self._renamed[id(match)] = match
        except TypeError:
            pass
        return match

    def rename_timeline(self, tl: Any) -> Any:
        if not self.enabled or tl is None:
            return tl
        self.register_timeline(tl)
        if tl.__dict__.get("_fiq_aliased") == self.signature and self._renamed.get(id(tl)) is tl:
            return tl
        self._renamed.pop(id(tl.match), None)
        self.rename_match(tl.match)
        teams: dict[str, str] = {}
        players: dict[str, str] = {}

        def tname(tid):
            if tid not in teams:
                teams[tid] = self.team(tid).name
            return teams[tid]

        def pname(pid):
            if pid not in players:
                players[pid] = self.player(pid).name
            return players[pid]

        for e in tl.events:
            e.team_name = tname(e.team_id) if e.team_id else None
            e.player_name = pname(e.player_id) if e.player_id else None
            e.recipient_name = pname(e.recipient_id) if e.recipient_id else None
        tr = getattr(tl, "tracking", None)
        if tr is not None:
            info = self._matches.get(tl.match.canonical_match_id)
            for p in tr.players:
                if p.player_id:
                    p.name = pname(p.player_id)
                else:
                    num = _jersey_int(p.jersey_num)
                    primary = info.jersey.get((p.team_id, num)) if info is not None and num is not None else None
                    p.name = pname(primary) if primary else None
        tl._fiq_aliased = self.signature
        try:
            self._renamed[id(tl)] = tl
        except TypeError:
            pass
        return tl

    def rename_summary(self, s: dict[str, Any]) -> dict[str, Any]:
        """Copy of a catalogue summary (``store.summary_of``) with fictional team and competition names."""
        if not self.enabled:
            return s
        out = dict(s)
        comp = self.competition(s.get("competition"))
        if comp:
            out["competition"] = comp.name
        for side in ("home", "away"):
            t = s.get(side)
            if isinstance(t, dict) and t.get("team_id"):
                out[side] = {**t, "name": self.team(t["team_id"]).name}
        return out

    # ------------------------------------------------------------------ outbound
    def to_public(self, obj: Any, match_id: str | None = None) -> Any:
        """JSON-able copy of ``obj`` that is safe for a client: public ids everywhere, fictional names only."""
        if not self.enabled:
            return obj
        return self._pub(obj, match_id if match_id in self._matches else None, None)

    def scrub_text(self, s: str, match_id: str | None = None) -> str:
        """Replace real names (and canonical ids) in free text."""
        if not self.enabled or not isinstance(s, str):
            return s
        return self._pub_str(s, match_id if match_id in self._matches else None, None)

    def _pub(self, x: Any, mid: str | None, key: str | None) -> Any:
        t = type(x)
        if t is str:
            return self._pub_str(x, mid, key)
        if t is dict:
            return self._pub_dict(x, mid)
        if t is list or t is tuple:
            return [v if (type(v) is int or type(v) is float or v is None) else self._pub(v, mid, key) for v in x]
        return x

    def _pub_dict(self, x: dict, mid: str | None) -> dict:
        m = x.get("match_id")
        if mid is None and type(m) is str and m in self._matches:
            mid = m
        pid, tid = x.get("player_id"), x.get("team_id")
        if mid and type(pid) is str and pid and type(tid) is str:     # a PFF id next to a shirt number: same person
            for jk in _JERSEY_KEYS:
                if x.get(jk) is not None:
                    self.link_jersey(mid, tid, x[jk], pid)
                    break
        out = {}
        for k, v in x.items():
            if k == "source_ids":        # provider ids are searchable and would re-identify
                out[k] = {}
                continue
            if k == "attribution":       # names the data providers; clients never show it
                out[k] = None
                continue
            nk = self._can2pub.get(k, k) if type(k) is str else k
            tv = type(v)
            out[nk] = v if (tv is int or tv is float or tv is bool or v is None) else self._pub(v, mid, k)
        if type(pid) is str and pid:
            a = self._known_player(pid)
            if a is not None:
                self._set_names(x, out, a, _PLAYER_NAME_KEYS)
        else:
            if type(tid) is str and self._kind.get(tid) == "t":
                self._set_names(x, out, self.team(tid), _TEAM_NAME_KEYS)
        for idk, keys, kind in _LINKED_NAME_KEYS:
            v = x.get(idk)
            if type(v) is not str:
                continue
            a = self._known_player(v) if kind == "player" else (self.team(v) if self._kind.get(v) == "t" else None)
            if a is not None:
                for nk in keys:
                    if type(x.get(nk)) is str:
                        out[nk] = a.name
        return out

    @staticmethod
    def _set_names(x: dict, out: dict, a: Any, keys: dict[str, str]) -> None:
        for k, attr in keys.items():
            v = x.get(k)
            if type(v) is not str:
                continue
            out[k] = a.short if attr == "nickname" else getattr(a, attr)

    def _known_player(self, pid: str) -> PlayerAlias | None:
        if self._kind.get(pid) == "p" or pid in self._link:
            return self.player(pid)
        if "_" in pid and not _DATE_ID.match(pid):
            team = self._team_of(pid)
            if team in self._kind:
                return self.player(pid)
        return None

    def _pub_str(self, s: str, mid: str | None, key: str | None) -> str:
        pub = self._can2pub.get(s)
        if pub is not None:
            return pub
        if "_" in s:
            s = _ID_TOKEN.sub(self._ids_in_token, s)
        if " " in s and s.lower() == s and key not in ENUM_KEYS:      # lower-case free text can carry team ids
            s = self._team_words().sub(lambda m: self._can2pub.get(m.group(), m.group()), s)
        if key in ENUM_KEYS or len(s) < 3 or s.lower() == s:            # names are capitalised; caseless text passes
            return s
        ck = (mid, s)
        hit = self._cache.get(ck)
        if hit is not None and hit[0] == self._version:
            return hit[1]
        out = self._scrub(s, mid)
        if len(self._cache) > 50_000:
            self._cache.clear()
        self._cache[ck] = (self._version, out)
        return out

    def _team_words(self) -> re.Pattern:
        """Whole-word regex of canonical team ids, rebuilt when the book grows."""
        cached = getattr(self, "_team_words_re", None)
        if cached is not None and cached[0] == self._version:
            return cached[1]
        ids = sorted((k for k, v in self._kind.items() if v == "t" and "_" not in k and len(k) >= 3), key=len, reverse=True)
        rx = re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, ids)) + r")(?![\w-])") if ids else re.compile(r"(?!x)x")
        self._team_words_re = (self._version, rx)
        return rx

    def _ids_in_token(self, m: re.Match) -> str:
        tok = m.group()
        pub = self._can2pub.get(tok)
        if pub is not None:
            return pub
        if _DATE_ID.match(tok) and tok.count("_") == 2:
            return self.match_public_id(tok)             # match ids embed team names: never let one through
        parts = tok.split("_")
        out, i = [], 0
        while i < len(parts):
            for j in range(len(parts), i, -1):
                cand = "_".join(parts[i:j])
                pub = self._can2pub.get(cand)
                if pub is None and j - i >= 2 and self._kind.get(parts[i]) == "t":
                    a = self._known_player(cand)
                    pub = a.public_id if a is not None else None
                if pub is not None:
                    out.append(pub)
                    i = j
                    break
            else:
                out.append(parts[i])
                i += 1
        return "_".join(out)

    # ------------------------------------------------------------------ free-text scrubbing
    def _global_scrubber(self) -> _Scrubber:
        g = self._global
        if g is not None and g[0] == self._version:
            return g[1]
        with self._lock:
            sc = _Scrubber()
            stop = self._stop
            for tid in list(self._kind):
                if self._kind.get(tid) != "t":
                    continue
                a = self.team(tid)
                curated = self.pools.get("teams", {}).get(tid, {})
                for real in [*self._real_team_names.get(tid, ()), *curated.get("real_aka", [])]:
                    sc.add(name_key(real), a.name, stop)
                for dem in curated.get("real_demonyms", []):
                    sc.add(name_key(dem), a.demonym + "s" if _plural_form(dem) else a.demonym, stop)
            for real, c in self.pools.get("competitions", {}).items():
                for v in [real, *c.get("aka", [])]:
                    sc.add(name_key(v), c["name"], stop)
            for info in list(self._matches.values()):
                for pid, names in list(info.names.items()):
                    a = self.player(pid)
                    for n in list(names):
                        k = name_key(n)
                        if len(k) >= 2:
                            sc.add(k, a.name, stop)
                for real, fn in ((info.referee, self.official), (info.stadium, self.venue)):
                    if real:
                        a = fn(real)
                        sc.add(name_key(real), a.name, stop)
            self._global = (self._version, sc)
            return sc

    def _match_scrubber(self, mid: str) -> _Scrubber | None:
        info = self._matches.get(mid)
        if info is None:
            return None
        cached = self._match_scrub.get(mid)
        if cached is not None and cached[0] == (info.version, self._version):
            return cached[1]
        with self._lock:
            sc = _Scrubber()
            stop = self._stop
            fict: set[str] = set()
            aliases = {pid: self.player(pid) for pid in list(info.names)}
            for a in aliases.values():
                fict.update(name_key(a.name))
            for tid in info.teams:
                ta = self.team(tid)
                fict.update(name_key(ta.name) + name_key(ta.demonym))
            ref = self.official(info.referee)
            ven = self.venue(info.stadium)
            for a in (ref, ven):
                if a:
                    fict.update(name_key(a.name))
            owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
            for pid, names in list(info.names.items()):
                a = aliases[pid]
                family_first = self._culture_weights(a.team_id)[0][0] == "korean"
                for n in list(names):
                    k = name_key(n)
                    if len(k) >= 2:
                        sc.add(k, a.name, stop)
                    for sk in surname_keys(n, family_first):
                        owners[sk].add(a.canonical_id)
            by_id = {a.canonical_id: a for a in aliases.values()}
            for sk, pids in owners.items():
                if len(pids) != 1 or (len(sk) == 1 and sk[0] in fict):
                    continue
                sc.add(sk, by_id[next(iter(pids))].short, stop)
            if info.referee and ref:
                sc.add(name_key(info.referee), ref.name, stop)
                for sk in surname_keys(info.referee):
                    if not owners.get(sk) and not (len(sk) == 1 and sk[0] in fict):
                        sc.add(sk, ref.name.split()[-1], stop)
            if info.stadium and ven:
                words = [w for w in re.split(r"[\s\-]+", info.stadium.strip()) if w]
                core = [w for w in words if fold(w) not in ("stadium", "stadion", "arena", "park", "ground", "field", "fields")]
                if core and core != words:
                    k = name_key(" ".join(core))
                    if not (len(k) == 1 and k[0] in fict):
                        sc.add(k, ven.name, stop)
            for tid in info.teams:
                curated = self.pools.get("teams", {}).get(tid, {})
                for real in curated.get("real_aka_local", []):
                    k = name_key(real)
                    if not (len(k) == 1 and k[0] in fict):
                        sc.add(k, self.team(tid).name, stop)
            self._match_scrub[mid] = ((info.version, self._version), sc)
            return sc

    def _scrub(self, s: str, mid: str | None) -> str:
        if not s.isascii():
            s = unicodedata.normalize("NFC", s)
        layers = [sc for sc in (self._match_scrubber(mid) if mid else None, self._global_scrubber()) if sc is not None and sc.keys]
        if not layers:
            return s
        folded = fold(s)
        toks = [(mt.start(), mt.end()) for mt in _TOKEN.finditer(folded)]
        n = len(toks)
        if not n:
            return s
        run = [1] * n
        for i in range(n - 2, -1, -1):
            if _SEP_OK.fullmatch(folded, toks[i][1], toks[i + 1][0]):
                run[i] = run[i + 1] + 1
        maxn = max(sc.maxn for sc in layers)
        out: list[str] = []
        last = i = 0
        while i < n:
            hit = None
            for k in range(min(maxn, run[i]), 0, -1):
                key = tuple(folded[a:b] for a, b in toks[i:i + k])
                for sc in layers:
                    r = sc.keys.get(key)
                    if r is not None:
                        hit = r
                        break
                if hit is None:
                    continue
                starts = [s[a] for a, _ in toks[i:i + k]]
                if (k == 1 and not starts[0].isupper()) or not any(c.isupper() for c in starts):
                    hit = None
                    continue
                a, b = toks[i][0], toks[i + k - 1][1]
                span = s[a:b]
                if len(span) > 1 and span.isupper():
                    hit = hit.upper()
                out.append(s[last:a])
                out.append(hit)
                last = b
                i += k
                break
            else:
                i += 1
        if not out:
            return s
        out.append(s[last:])
        return "".join(out)


# --------------------------------------------------------------------------- singleton
_BOOK: AliasBook | None = None
_BOOK_LOCK = threading.Lock()


def get_book() -> AliasBook:
    """The process-wide book; it follows ``FOOTBALLIQ_PSEUDONYMS`` (``off`` makes it a no-op)."""
    global _BOOK
    if _BOOK is None:
        with _BOOK_LOCK:
            if _BOOK is None:
                _BOOK = AliasBook()
    return _BOOK


def reset_book() -> None:
    """Drop the singleton (tests); the next one re-reads the salt and starts empty."""
    global _BOOK
    with _BOOK_LOCK:
        _BOOK = None


# --------------------------------------------------------------------------- store wrapper
class AliasedStore:
    """Store wrapper whose output carries fictional names; objects are renamed in place, once.

    Ids stay canonical inside the backend; other attributes are the inner store's.
    """

    def __init__(self, inner: Any, book: AliasBook | None = None):
        self._inner = inner
        self._book = book or get_book()
        self._catalogue_size = -1
        self._lock = threading.Lock()
        self._book.add_loader(self._load_for_alias)

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in ("_inner", "_book"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def _ensure_catalogue(self) -> list[Any]:
        matches = self._inner.all_matches()
        if not self._book.enabled:
            return matches
        if len(matches) != self._catalogue_size or any(self._book._renamed.get(id(m)) is not m for m in matches):
            with self._lock:
                self._book.register_matches(matches)       # whole catalogue first, for deterministic names
                for m in matches:
                    self._book.rename_match(m)
                self._catalogue_size = len(matches)
        return matches

    def _load_for_alias(self, match_id: str | None) -> None:
        self._ensure_catalogue()
        if match_id:
            self.get(match_id)

    def match_ids(self) -> list[str]:
        return self._inner.match_ids()

    def summaries(self) -> list[dict[str, Any]]:
        self._ensure_catalogue()
        return [self._book.rename_summary(s) for s in self._inner.summaries()]

    def all_matches(self) -> list[Any]:
        return self._ensure_catalogue()

    def get(self, match_id: str) -> Any:
        tl = self._inner.get(match_id)
        if tl is None or not self._book.enabled:
            return tl
        self._ensure_catalogue()
        return self._book.rename_timeline(tl)

    def status(self) -> dict[str, Any]:
        return self._inner.status()
