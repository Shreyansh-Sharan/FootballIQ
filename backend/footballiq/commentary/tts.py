"""Azure neural text-to-speech for commentary lines, with a disk cache, rate limiter and look-ahead queue.

AZURE_SPEECH_RPM sets the request budget (default 18, under the F0 tier limit of 20 per minute).
"""

from __future__ import annotations

import hashlib
import heapq
import logging
import os
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from footballiq import config

log = logging.getLogger(__name__)
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"

# (locale, voice, speaking style per excitement level 0..3)
VOICES: dict[str, dict[str, tuple[str, str, tuple[str | None, ...]]]] = {
    "en": {"pbp": ("en-GB", "en-GB-Harry:MAI-Voice-2.1-Flash", (None, None, "surprised", "joyful")),
           "colour": ("en-GB", "en-GB-Emily:MAI-Voice-2.1-Flash", (None, None, None, "joyful"))},
    "es": {"pbp": ("es-MX", "es-MX-Alejo:MAI-Voice-2.1-Flash", (None, None, "excited", "excited")),
           "colour": ("es-MX", "es-MX-Valeria:MAI-Voice-2.1-Flash", (None, None, None, "joyful"))},
    "hi": {"pbp": ("hi-IN", "hi-IN-Arjun:MAI-Voice-2.1-Flash", (None, None, "excited", "excited")),
           "colour": ("hi-IN", "hi-IN-Kavya:MAI-Voice-2.1-Flash", (None, None, None, "joyful"))},
}


class NotReady(Exception):
    """Audio is not cached and the synthesis budget is used up right now."""


def configured() -> bool:
    return bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))


def voice_for(lang: str, speaker: str) -> tuple[str, str, tuple[str | None, ...]]:
    loc, voice, styles = VOICES[lang]["pbp" if speaker not in VOICES[lang] else speaker]
    return loc, os.environ.get(f"FOOTBALLIQ_VOICE_{lang.upper()}_{speaker.upper()}", voice), styles


def ssml(text: str, lang: str, speaker: str, excitement: int) -> str:
    loc, voice, styles = voice_for(lang, speaker)
    body = escape(text)
    style = styles[max(0, min(3, excitement))] if styles else None
    if style:
        body = f'<mstts:express-as style="{style}">{body}</mstts:express-as>'
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" '
            f'xml:lang="{loc}"><voice name="{voice}">{body}</voice></speak>')


class _Bucket:
    """Token bucket in requests per minute, refilled continuously."""

    def __init__(self, rpm: float):
        self.rate = rpm / 60.0
        self.capacity = max(1.0, rpm / 4)
        self.tokens = self.capacity
        self.at = time.monotonic()
        self.lock = threading.Lock()

    def take(self, block: bool) -> bool:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.at) * self.rate)
                self.at = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1 - self.tokens) / self.rate
            if not block:
                return False
            time.sleep(min(wait, 5.0))


class Speech:
    def __init__(self, cache_dir: Path | None = None, rpm: float | None = None):
        self.cache_dir = cache_dir or config.data_dir() / "cache" / "tts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bucket = _Bucket(rpm or float(os.environ.get("AZURE_SPEECH_RPM", "18")))
        self.http = httpx.Client(timeout=20.0)
        self._queue: list[tuple[int, int, str, str, str, int]] = []
        self._queued: set[str] = set()
        self._cv = threading.Condition()
        self._seq = 0
        self._worker: threading.Thread | None = None
        self.stats = {"synthesised": 0, "cache_hits": 0, "not_ready": 0, "errors": 0}

    def key(self, text: str, lang: str, speaker: str, excitement: int) -> str:
        return hashlib.sha1(ssml(text, lang, speaker, excitement).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.mp3"

    def cached(self, text: str, lang: str, speaker: str, excitement: int) -> bytes | None:
        p = self._path(self.key(text, lang, speaker, excitement))
        return p.read_bytes() if p.exists() else None

    def _synthesise(self, text: str, lang: str, speaker: str, excitement: int) -> bytes:
        region, key = os.environ["AZURE_SPEECH_REGION"], os.environ["AZURE_SPEECH_KEY"]
        body = ssml(text, lang, speaker, excitement)
        for attempt in range(3):
            r = self.http.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", content=body.encode("utf-8"),
                               headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                                        "X-Microsoft-OutputFormat": OUTPUT_FORMAT, "User-Agent": "footballiq-commentary"})
            if r.status_code == 429 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError("speech service throttled")

    def audio(self, text: str, lang: str, speaker: str, excitement: int, block: bool = False) -> bytes:
        """Cached audio, or synthesise now if the budget allows (block=True waits for budget)."""
        key = self.key(text, lang, speaker, excitement)
        p = self._path(key)
        if p.exists():
            self.stats["cache_hits"] += 1
            return p.read_bytes()
        if not configured():
            raise NotReady("speech is not configured")
        if not self.bucket.take(block):
            self.stats["not_ready"] += 1
            raise NotReady("synthesis budget used up; retry shortly")
        try:
            data = self._synthesise(text, lang, speaker, excitement)
        except Exception:
            self.stats["errors"] += 1
            raise
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
        self.stats["synthesised"] += 1
        return data

    def prefetch(self, items: list[tuple[int, str, str, str, int]]) -> None:
        """Queue ``(due_ms, text, lang, speaker, excitement)`` items for synthesis, earliest due first."""
        if not configured():
            return
        with self._cv:
            for due, text, lang, speaker, exc in items:
                k = self.key(text, lang, speaker, exc)
                if k in self._queued or self._path(k).exists():
                    continue
                self._queued.add(k)
                self._seq += 1
                heapq.heappush(self._queue, (due, self._seq, text, lang, speaker, exc))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True, name="tts-prefetch")
                self._worker.start()
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait(timeout=30)
                    if not self._queue:
                        return
                _, _, text, lang, speaker, exc = heapq.heappop(self._queue)
            try:
                self.audio(text, lang, speaker, exc, block=True)
            except Exception:  # noqa: BLE001 - one failed line must not stop the queue
                log.warning("tts prefetch failed", exc_info=True)
            finally:
                with self._cv:
                    self._queued.discard(self.key(text, lang, speaker, exc))

    def status(self) -> dict:
        return {"configured": configured(), "rpm": round(self.bucket.rate * 60), "queued": len(self._queue), **self.stats,
                "voices": {lang: {s: voice_for(lang, s)[1] for s in ("pbp", "colour")} for lang in VOICES}}
