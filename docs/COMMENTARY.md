# Live commentary (English, Spanish, Hindi)

Two voices, like a TV booth: a **play-by-play** commentator who names the player on the ball as it happens, and an
**analyst** (colour) who fills the lulls with facts known at that moment. Lines are generated from match events,
spoken with Azure neural voices, and served cut at the replay clock (`GET /v1/matches/{id}/commentary`, see
[MATCHDAY_API.md](MATCHDAY_API.md)).

## How it works

```
events (+ matchday moments, series, physical)        Foundry gpt-5.1           Azure AI Speech
        │                                                  │                          │
        ▼                                                  ▼                          ▼
 engine.beats()  ──►  engine.schedule() (booth)  ──►  colour.polish()  ──►  tts.Speech (cache, rate limit, look-ahead)
 candidate lines       one voice at a time            analyst wording            mp3 per line
        └──────────────────────── Script per (match, language), cut at to_ms by the API ──────────────┘
```

| Step | Module | What it does |
|---|---|---|
| Beats | `commentary/engine.py` `beats()` | Each event, or a shot with its keeper event, becomes a candidate line with a priority (1 goal / shot / card / period: must be said, cuts in; 2 dangerous play, set pieces, subs: said soon, cuts the analyst off; 3 naming the player on the ball: dropped when stale), an excitement level (0–3) and the time it may be spoken, which is just after the **latest** event it describes. Nothing is said before it happened. |
| Booth | `engine.schedule()` | One voice at a time. Naming leaves silences that depend on where the ball is (longer in a team's own third, shorter near goal). Names that pile up while the booth is busy come out as a chain ("Fernández... Mac Allister... Messi!"), which is how real commentators speed up before a goal. When the ball is in a calm zone or dead, and the talk share over the last minute is below the target, the analyst speaks. |
| Analyst facts | `engine.Context` | The freshest matchday moment (control, chaos, rhythm change, shape, sprint record, 10 km, pass of the match, big chance), otherwise a fact as of that second: the player on the ball (touches, passes, km, booked), team stats, rhythm, shape, model win chance, time left for the trailing team. Category and fact cooldowns keep it varied. |
| After a goal | `beats()` | Goal call, reaction, then "del {team} en el minuto {m}, gol de {p}" (Spanish formula), scorer tally, score recap at about 33 s and a replay description with the assister at about 38 s, matching the broadcast pattern measured below. |
| Wording | `commentary/colour.py` | gpt-5.1 (Foundry) rewrites each analyst line as natural speech. It is given only the facts that line states and the last play-by-play lines, sized to fit before the next line. Ids and times don't change, and results are cached on disk per match and language. |
| Voices | `commentary/tts.py` | Azure neural TTS with SSML speaking styles and rates per excitement level, disk cache, a rate limiter, and a look-ahead queue that voices the next 90 s of lines on the server so audio is ready when the clock reaches them. Lines are never sent early. |
| Client | `frontend/lib/matchday/commentary.ts` | Plays one line at a time. A priority-1 or `interrupts` line cuts off the current one; a priority-3 line more than 2.5 s late is skipped; captions always show. A 503 from the audio endpoint falls back to the browser's `speechSynthesis` (en-GB / es-ES / hi-IN). |

Fictional names: the engine speaks the names from `matchday/meta`, which the alias layer has already renamed
(`short` / `short_hi`, Devanagari for Hindi). The analyst model is told the names are fictional and to use only
those.

## Calibration: what real commentary sounds like

Measured on **SoccerNet-Echoes** (Gautam et al. 2024, CC BY 4.0): Whisper transcripts of broadcast commentary,
291 English halves (218 h) and 215 Spanish halves (158 h), after removing ASR hallucinations. The transcripts were
used for statistics and paraphrased patterns only; no transcript text is shipped.

| | English (UK TV) | Spanish (Spain TV; Latin American subset) | Hindi |
|---|---|---|---|
| Words per minute | 108 | 154; LatAm about 116 | no licensed corpus exists |
| Share of time talking | 0.68 | 0.85 | (starts at 0.68) |
| A new line every | ~5 s (IQR 3–9 s) | ~4 s (IQR 2–7 s) | |
| Gap between lines, p50 / p90 | 1 s / 4 s | under 1 s / 1 s | |
| Analyst share of talk time | ~60% | ~45% | |
| Names per minute | 5.7; 10.2 in the 10 s before a goal | 12.9; 15.5 before a goal | |
| After a goal | densest talk of the match for about a minute (140 wpm); score recap ~35 s; replay talk ~37–40 s | "¡GOOOL!" held 4–9 s, then team, minute and scorer; 160+ wpm for 1–2 minutes | |

How these numbers drive the engine:

- `lexicon.TALK_SHARE` (en 0.68, es 0.76 for the Latin American register of the es-MX voice, hi 0.68) is the booth's talk-share target.
- `NAMING_GAP_MS` × `GAP_SCALE` sets the silences.
- `POST_GOAL_MS` and `POST_GOAL_SHARE` set the post-goal density.
- The goal-call templates follow the measured patterns.
- `WPS` and `GOAL_FACTOR` are fitted to the measured mp3 lengths of the chosen voices.

Other sources were checked and rejected:

- MatchTime / SN-Caption: written live-text scraped from Flashscore, CC BY-SA. Used only for rosters and event times.
- GOAL (THU-KEG): the download links are dead.
- SoccerReplay-1988: needs an NDA.
- BraToLi: restricted.
- Hindi and Hinglish cricket ASR sets: no licence, and they bundle audio.

Hindi phrasing is therefore expert-written: Devanagari, with English football terms kept as Indian broadcasts use them. **Have native Hindi listeners review it.**

Measured on the 2022 final, the engine currently produces:

| | Line every | Analyst share of talk | Talk time | Words per minute |
|---|---|---|---|---|
| English | ~4.8 s | ~55% | ~40% | ~58 |
| Spanish | ~4.1 s | ~53% | ~40% | ~58 |
| Hindi | ~5.3 s | ~54% | ~43% | ~56 |

Talk time and words per minute are still below broadcast, because the lines are shorter than a human's. The analyst rewrite raises this.

## Voices (Azure AI Speech, `footballiq-speech`, Central India)

| Language | Play-by-play | Analyst | Excitement |
|---|---|---|---|
| English | `en-GB-Harry:MAI-Voice-2.1-Flash` | `en-GB-Emily:MAI-Voice-2.1-Flash` | +12% rate in play; `surprised` / `joyful` for chances and goals |
| Spanish | `es-MX-Alejo:MAI-Voice-2.1-Flash` | `es-MX-Valeria:MAI-Voice-2.1-Flash` | `excited`; the goal call is about 7 s |
| Hindi | `hi-IN-Arjun:MAI-Voice-2.1-Flash` | `hi-IN-Kavya:MAI-Voice-2.1-Flash` | `excited`; plain `excited` is very slow (11 s for 8 words) |

Override any voice with `FOOTBALLIQ_VOICE_<LANG>_<PBP|COLOUR>`, for example `FOOTBALLIQ_VOICE_EN_PBP=en-GB-RyanNeural`. Synthesis takes about 0.4–1.3 s per line; with look-ahead and the cache it is ready before it is needed.

**Limits and cost.**
- **Free tier (F0)**: 20 synthesis requests per minute (not adjustable) and 0.5 M characters a month. One match of commentary is about 12 lines a minute and roughly 80k characters per language. F0 can voice one listener at 1× in one language, close to its limit. At 2× and faster, or several languages at once, lines fall back to the browser voice.
- **Standard (S0)**: 30 requests per second, about $15 per million characters, so roughly $1 per match per language, voiced once and cached.
- `AZURE_SPEECH_RPM` sets the budget the server uses (default 18).

## Configuration

| Variable | Purpose |
|---|---|
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Neural voices (without them the API returns `tts: "none"` and the client uses browser voices) |
| `AZURE_SPEECH_RPM` | Synthesis budget per minute (F0: 18; S0: up to 1800) |
| `FOUNDRY_*` | Analyst rewrite with the Foundry model (optional; template wording without it) |
| `FOOTBALLIQ_VOICE_<LANG>_<SPEAKER>` | Voice overrides |

## Integrating elsewhere

- **Broadcast partner / graphics.** Every line has a match time, priority, `interrupts` flag and text, so it can be rendered as subtitles, fed to the partner's own TTS, or played from `audio_url`.
- **A truly live match.** The engine only reads events up to each line's time, so it runs unchanged on a live feed: append events as they arrive and schedule the new beats. Speaking about 0.3–1 s after an event is normal for broadcast commentary.
- **More languages.** Add a block to `PBP`, `COLOUR`, `PATTERN_NAME` and `WHERE` in `lexicon.py` (the tests check that every language has the same situations), a voice pair in `tts.VOICES`, and a `TALK_SHARE` / `WPS` entry.
