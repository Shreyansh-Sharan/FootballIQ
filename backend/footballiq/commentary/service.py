"""Commentary scripts per (match, language), built once and served as cuts at the replay clock, plus audio."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

import numpy as np

from footballiq.commentary.engine import LANGS, Line, build_script
from footballiq.commentary.tts import NotReady, Speech, configured as tts_configured
from footballiq.matchday.service import MatchdayService, meta
from footballiq.replay.timeline import MatchTimeline

log = logging.getLogger(__name__)
LOOKAHEAD_MS = 90_000


class Script:
    def __init__(self, match_id: str, lang: str, lines: list[Line]):
        self.match_id, self.lang, self.lines = match_id, lang, lines
        self.t = np.array([l.t_ms for l in lines], dtype=np.int64)
        self.by_id = {l.id: l for l in lines}

    def between(self, from_ms: int, to_ms: int) -> list[Line]:
        a, b = np.searchsorted(self.t, from_ms, side="right"), np.searchsorted(self.t, to_ms, side="right")
        return self.lines[a:b]


class CommentaryService:
    def __init__(self, matchday: MatchdayService, speech: Speech | None = None, colour_writer=None, max_cached: int = 12):
        """``colour_writer(script)``, if given, rewrites analyst lines in place."""
        self.matchday = matchday
        self.speech = speech or Speech()
        self.colour_writer = colour_writer
        self._cache: OrderedDict[tuple[str, str], Script] = OrderedDict()
        self._lock = threading.Lock()
        self.max_cached = max_cached

    def script(self, tl: MatchTimeline, lang: str) -> Script:
        key = (tl.match.canonical_match_id, lang)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        d = self.matchday.data(tl)
        s = Script(key[0], lang, build_script(tl, meta(tl, d.roles), lang, d))
        with self._lock:
            self._cache[key] = s
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
        if self.colour_writer is not None:
            threading.Thread(target=self._polish, args=(s,), daemon=True, name=f"colour-{key[0]}-{lang}").start()
        return s

    def _polish(self, s: Script) -> None:
        try:
            self.colour_writer(s)
        except Exception:  # noqa: BLE001 - template colour stays if the writer fails
            log.warning("colour writer failed for %s/%s", s.match_id, s.lang, exc_info=True)

    def audio_url(self, s: Script, line: Line) -> str | None:
        return f"/v1/matches/{s.match_id}/commentary/audio/{line.id}?lang={s.lang}" if tts_configured() else None

    def lines(self, tl: MatchTimeline, lang: str, from_ms: int, to_ms: int) -> dict[str, Any]:
        s = self.script(tl, lang)
        out = s.between(from_ms, to_ms)
        # pre-synthesise upcoming lines; they are never sent early
        ahead = s.between(to_ms, to_ms + LOOKAHEAD_MS)
        self.speech.prefetch([(l.t_ms, l.text, lang, l.speaker, l.excitement) for l in [*out[-3:], *ahead]])
        return {"lang": lang, "tts": "azure" if tts_configured() else "none", "lines": [l.to_dict(self.audio_url(s, l)) for l in out]}

    def audio(self, tl: MatchTimeline, lang: str, line_id: str) -> bytes | None:
        line = self.script(tl, lang).by_id.get(line_id)
        if line is None:
            return None
        return self.speech.audio(line.text, lang, line.speaker, line.excitement)


__all__ = ["CommentaryService", "LANGS", "NotReady"]
