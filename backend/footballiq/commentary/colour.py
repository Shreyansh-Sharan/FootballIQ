"""Analyst lines reworded as broadcast speech by the Foundry model; the engine still sets timing and facts.

Rewrites are cached on disk per (match, language, draft), so each match is paid for once.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from footballiq import config
from footballiq.agents import foundry
from footballiq.commentary.engine import Line, speak_ms
from footballiq.commentary.lexicon import WPS

log = logging.getLogger(__name__)
SCOPE = "https://cognitiveservices.azure.com/.default"
LANG_NAME = {"en": "British English", "es": "Latin American Spanish", "hi": "Hindi"}
STYLE = {
    "en": "UK TV co-commentator: understated, insightful, present tense, full sentences.",
    "es": ("Latin American TV analyst (comentarista): warm and lively. Use Latin American football vocabulary "
           "(arquero, arco, penal, cancha, fuera de lugar, tiro libre, técnico), never Spain-only terms."),
    "hi": ("Indian TV Hindi football analyst, written in Devanagari. Keep English football terms the way Indian broadcasts do, "
           "but written in Devanagari (पास, क्रॉस, कॉर्नर, गोलकीपर, पज़ेशन, फ़्री-किक, डिफ़ेंस). Honorific plural for players."),
}
BATCH = 25
MAX_WORDS = 28
MIN_WORDS = 9


class FoundryColour:
    def __init__(self, cache_dir: Path | None = None, workers: int = 3, timeout: float = 180.0):
        self.cache_dir = cache_dir or config.data_dir() / "cache" / "commentary"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.workers = workers
        self.http = httpx.Client(timeout=timeout)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return foundry.configured()

    def _bearer(self) -> str:
        with self._lock:
            if self._token and self._token[1] - time.time() > 300:
                return self._token[0]
            r = self.http.post(f"https://login.microsoftonline.com/{os.environ['FOUNDRY_TENANT_ID']}/oauth2/v2.0/token",
                               data={"grant_type": "client_credentials", "client_id": os.environ["FOUNDRY_CLIENT_ID"],
                                     "client_secret": os.environ["FOUNDRY_CLIENT_SECRET"], "scope": SCOPE})
            r.raise_for_status()
            d = r.json()
            self._token = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
            return self._token[0]

    def _endpoint(self) -> str:
        base = os.environ["FOUNDRY_PROJECT_ENDPOINT"].split("/api/projects/")[0].rstrip("/")
        return f"{base}/openai/deployments/{foundry.default_model()}/chat/completions?api-version=2024-10-21"

    def _complete(self, lang: str, items: list[dict[str, Any]]) -> dict[str, str]:
        system = (
            f"You are the analyst (co-commentator) on a live football broadcast in {LANG_NAME[lang]}. {STYLE[lang]}\n"
            "Rewrite each draft as ONE natural spoken line for that moment. Rules:\n"
            "- State only the facts given (numbers exactly as given). Do not invent statistics, history or quotes.\n"
            "- People and teams: use only the names that appear in the item, spelled exactly. They are fictional; "
            "never use real-world player, team, competition or stadium names, even if the match seems familiar.\n"
            "- You only know the match up to the item's minute; never hint at what happens later.\n"
            "- Use the situation (the last play-by-play lines) to connect naturally, but don't repeat it.\n"
            "- Aim for about max_words words and never exceed it. Vary how lines start. No emojis, hashtags or stage directions.\n"
            'Return JSON: {"lines": [{"id": "...", "text": "..."}]} with every id.'
        )
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)}],
                "response_format": {"type": "json_object"}, "max_completion_tokens": 6000}
        for attempt in range(3):
            r = self.http.post(self._endpoint(), headers={"Authorization": f"Bearer {self._bearer()}"}, json=body)
            if r.status_code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return {x["id"]: x["text"].strip() for x in json.loads(content).get("lines", []) if x.get("id") and x.get("text")}
        return {}

    def _cache_path(self, match_id: str, lang: str) -> Path:
        return self.cache_dir / f"{hashlib.sha1(match_id.encode()).hexdigest()[:12]}_{lang}.json"

    @staticmethod
    def _draft_key(line: Line) -> str:
        return hashlib.sha1(f"{line.t_ms}|{line.text}".encode()).hexdigest()[:16]

    def polish(self, script) -> int:
        """Rewrite the analyst lines in place; returns how many changed."""
        lines: list[Line] = script.lines
        lang = script.lang
        path = self._cache_path(script.match_id, lang)
        cache: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
        wps = WPS[lang][1]
        todo = []
        for i, line in enumerate(lines):
            if line.speaker != "colour":
                continue
            slot_s = ((lines[i + 1].t_ms if i + 1 < len(lines) else line.t_ms + 12_000) - line.t_ms) / 1000 - 0.4
            max_words = int(max(MIN_WORDS, min(MAX_WORDS, slot_s * wps * 0.9)))
            recent = [l.text for l in lines[max(0, i - 3):i] if l.speaker == "pbp"][-2:]
            item = {"id": line.id, "minute": line.clock, "situation": recent, "facts": line.facts, "draft": line.text,
                    "max_words": max_words}
            todo.append((line, item, slot_s))
        changed = 0
        pending = [(l, it, s) for l, it, s in todo if self._draft_key(l) not in cache]
        batches = [pending[k:k + BATCH] for k in range(0, len(pending), BATCH)]

        def run(batch):
            return batch, self._complete(lang, [it for _, it, _ in batch])

        # retry failed batches once, in halves
        for round_ in (0, 1):
            failed = []
            with cf.ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {pool.submit(run, b): b for b in batches}
                for fut in cf.as_completed(futures):
                    try:
                        batch, out = fut.result()
                    except Exception as exc:  # noqa: BLE001 - keep the template wording for this batch
                        log.warning("colour rewrite batch failed (%s, round %d): %s", lang, round_ + 1, exc)
                        failed.extend(futures[fut])
                        continue
                    for line, item, _ in batch:
                        text = out.get(item["id"])
                        if text and len(text.split()) <= item["max_words"] * 1.3:
                            cache[self._draft_key(line)] = text
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(cache, ensure_ascii=False))
                    tmp.replace(path)
            if not failed:
                break
            batches = [failed[k:k + BATCH // 2] for k in range(0, len(failed), BATCH // 2)]
        for line, _, slot_s in todo:
            text = cache.get(self._draft_key(line))
            if text and text != line.text:
                line.text = text
                line.dur_ms = min(speak_ms(text, lang, "colour", 0), int(slot_s * 1000) + 400)
                changed += 1
        log.info("colour rewrite %s/%s: %d of %d analyst lines", script.match_id, lang, changed, len(todo))
        return changed
