// Commentary playback: one voice at a time; priority-1 and `interrupts` lines cut in; lines older than STALE_MS are skipped.
// Plays the server TTS `audio_url`, falling back to browser speechSynthesis on failure or when tts is "none".

"use client";

import { useEffect, useMemo, useState } from "react";
import { audioUrl, useCommentaryData, type Status } from "./api";
import { CLOCK } from "./clock";
import type { CommentaryLine, CommentaryResp, Lang } from "./types";

export type VoiceMode = "studio" | "browser" | null;

export interface BoothState {
  enabled: boolean;
  volume: number;
  speaking: CommentaryLine | null;
  mode: VoiceMode;
  blocked: boolean;
  speechAvailable: boolean;
}

const SPEECH_LANG: Record<Lang, string> = { en: "en-GB", es: "es-ES", hi: "hi-IN" };
const STALE_MS: Record<number, number> = { 1: 10000, 2: 6000, 3: 2500 };
const VOL_KEY = "fiq.matchday.volume";

export class CommentaryPlayer {
  private st: BoothState = { enabled: false, volume: 0.9, speaking: null, mode: null, blocked: false, speechAvailable: true };
  private listeners = new Set<(s: BoothState) => void>();
  private queue: CommentaryLine[] = [];
  private current: { line: CommentaryLine; audio: HTMLAudioElement | null; speech: boolean } | null = null;
  /** Advances if a voice never fires its end event (some browsers drop it). */
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private seen = new Set<string>();
  private lang: Lang = "en";
  private tts: "azure" | "none" = "azure";
  private audioBroken = false;
  private paused = false;
  private voices: SpeechSynthesisVoice[] = [];
  private onVoices = () => { this.voices = window.speechSynthesis?.getVoices() ?? []; };

  constructor() {
    if (typeof window === "undefined") return;
    this.st.speechAvailable = "speechSynthesis" in window;
    if (this.st.speechAvailable) {
      this.onVoices();
      window.speechSynthesis.addEventListener?.("voiceschanged", this.onVoices);
    }
    try {
      const v = parseFloat(localStorage.getItem(VOL_KEY) ?? "");
      if (Number.isFinite(v)) this.st.volume = Math.max(0, Math.min(1, v));
    } catch { /* storage blocked */ }
  }

  get state() { return this.st; }

  subscribe(fn: (s: BoothState) => void) {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private set(p: Partial<BoothState>) {
    this.st = { ...this.st, ...p };
    this.listeners.forEach((l) => l(this.st));
  }

  setEnabled(on: boolean) {
    if (on) {
      this.audioBroken = false;
      this.set({ enabled: true, blocked: false });
      // inside a user gesture: unlocks later speech
      try { window.speechSynthesis?.resume(); } catch { /* not supported */ }
      this.pump();
    } else {
      this.stopCurrent();
      this.queue = [];
      this.set({ enabled: false, speaking: null, mode: null });
    }
  }

  setVolume(v: number) {
    const vol = Math.max(0, Math.min(1, v));
    if (this.current?.audio) this.current.audio.volume = vol;
    try { localStorage.setItem(VOL_KEY, String(vol)); } catch { /* storage blocked */ }
    this.set({ volume: vol });
  }

  setLang(lang: Lang) {
    if (lang === this.lang) return;
    this.lang = lang;
    this.audioBroken = false;
    this.reset();
    this.seen.clear();
  }

  setTts(tts: "azure" | "none") { this.tts = tts; }

  /** On a clock jump: drops playing and queued lines; captions are unaffected. */
  reset() {
    this.stopCurrent();
    this.queue = [];
    this.set({ speaking: null, mode: null });
  }

  setPaused(p: boolean) {
    if (p === this.paused) return;
    this.paused = p;
    const c = this.current;
    if (p) {
      c?.audio?.pause();
      if (c?.speech) try { window.speechSynthesis.pause(); } catch { /* not supported */ }
    } else {
      c?.audio?.play().catch(() => undefined);
      if (c?.speech) try { window.speechSynthesis.resume(); } catch { /* not supported */ }
      this.pump();
    }
  }

  /** New lines from the API (any order, any age). */
  offer(lines: CommentaryLine[]) {
    const now = CLOCK.t;
    for (const line of [...lines].sort((a, b) => a.t_ms - b.t_ms)) {
      if (this.seen.has(line.id)) continue;
      this.seen.add(line.id);
      if (!this.st.enabled || now - line.t_ms > (STALE_MS[line.priority] ?? 2500)) continue;
      if (line.priority === 1 || line.interrupts) {
        // cut in (goal calls, attacks cutting the analyst off)
        if (this.current) this.stopCurrent();
        const k = this.queue.findIndex((q) => q.priority !== 1);
        this.queue.splice(k < 0 ? this.queue.length : k, 0, line);
      } else this.queue.push(line);
    }
    this.pump();
  }

  private pump() {
    if (this.current || !this.st.enabled || this.paused) return;
    while (this.queue.length) {
      const line = this.queue.shift()!;
      if (CLOCK.t - line.t_ms > (STALE_MS[line.priority] ?? 2500)) continue;
      this.play(line);
      return;
    }
    if (this.st.speaking) this.set({ speaking: null, mode: null });
  }

  private finish(line: CommentaryLine) {
    if (this.current?.line !== line) return;
    this.clearWatchdog();
    this.current = null;
    this.pump();
  }

  private arm(line: CommentaryLine) {
    this.clearWatchdog();
    const ms = Math.max(4000, (line.dur_ms || 3000) * 1.8 + 1500);
    this.watchdog = setTimeout(() => {
      if (this.current?.line !== line) return;
      if (this.paused) { this.arm(line); return; }
      this.stopCurrent();
      this.pump();
    }, ms);
  }

  private clearWatchdog() {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
  }

  private play(line: CommentaryLine) {
    if (line.audio_url && this.tts !== "none" && !this.audioBroken) {
      const a = new Audio(audioUrl(line.audio_url));
      a.volume = this.st.volume;
      this.current = { line, audio: a, speech: false };
      this.set({ speaking: line, mode: "studio" });
      this.arm(line);
      const fallback = () => {
        if (this.current?.line !== line || this.current.audio !== a) return;
        this.audioBroken = true;   // e.g. 503 when server TTS is not configured
        a.onended = null;
        a.onerror = null;
        this.current = null;
        this.speak(line);
      };
      a.onended = () => this.finish(line);
      a.onerror = fallback;
      a.play().catch((err: unknown) => {
        if ((err as { name?: string })?.name === "NotAllowedError") {
          if (this.current?.audio === a) this.current = null;
          this.queue = [];
          this.set({ enabled: false, blocked: true, speaking: null, mode: null });
        } else fallback();
      });
      return;
    }
    this.speak(line);
  }

  private pickVoice(speaker: string): SpeechSynthesisVoice | null {
    const code = SPEECH_LANG[this.lang].toLowerCase();
    const base = code.slice(0, 2);
    const norm = (v: SpeechSynthesisVoice) => v.lang.replace("_", "-").toLowerCase();
    const exact = this.voices.filter((v) => norm(v) === code);
    const pool = exact.length ? exact : this.voices.filter((v) => norm(v).startsWith(base));
    if (!pool.length) return null;
    return speaker === "colour" && pool.length > 1 ? pool[1] : pool[0];
  }

  private speak(line: CommentaryLine) {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth) {
      this.set({ speechAvailable: false, speaking: null, mode: null });
      this.pump();
      return;
    }
    const u = new SpeechSynthesisUtterance(line.text);
    u.lang = SPEECH_LANG[this.lang];
    const v = this.pickVoice(line.speaker);
    if (v) u.voice = v;
    u.volume = this.st.volume;
    const ex = line.excitement ?? 0;
    u.rate = ex >= 3 ? 1.15 : ex >= 2 ? 1.08 : 1;
    u.pitch = (ex >= 3 ? 1.12 : ex >= 2 ? 1.06 : 1) * (line.speaker === "colour" ? 0.94 : 1);
    u.onend = () => this.finish(line);
    u.onerror = (e: SpeechSynthesisErrorEvent) => {
      if (e.error === "not-allowed") {
        this.current = null;
        this.queue = [];
        this.set({ enabled: false, blocked: true, speaking: null, mode: null });
        return;
      }
      this.finish(line);
    };
    this.current = { line, audio: null, speech: true };
    this.set({ speaking: line, mode: "browser" });
    this.arm(line);
    if (synth.speaking || synth.pending) synth.cancel();
    synth.speak(u);
  }

  private stopCurrent() {
    this.clearWatchdog();
    const c = this.current;
    this.current = null;
    if (!c) return;
    if (c.audio) {
      c.audio.onended = null;
      c.audio.onerror = null;
      c.audio.pause();
      c.audio.removeAttribute("src");
      try { c.audio.load(); } catch { /* ignore */ }
    }
    if (c.speech) try { window.speechSynthesis.cancel(); } catch { /* not supported */ }
  }
}

export interface Commentary {
  state: BoothState;
  lines: CommentaryLine[];
  status: Status;
  tts: "azure" | "none";
  setEnabled: (on: boolean) => void;
  setVolume: (v: number) => void;
}

/** Commentary lines for the view language plus the playback queue, synced to the clock. */
export function useCommentary(matchId: string | null, lang: Lang, playing: boolean): Commentary {
  const player = useMemo(() => new CommentaryPlayer(), []);
  const [state, setState] = useState<BoothState>(() => player.state);
  useEffect(() => {
    setState(player.state);
    const off = player.subscribe(setState);
    const offSeek = CLOCK.onSeek(() => player.reset());
    return () => { off(); offSeek(); player.reset(); };
  }, [player]);
  useEffect(() => { player.setLang(lang); }, [player, lang]);
  useEffect(() => { player.reset(); }, [player, matchId]);
  useEffect(() => { player.setPaused(!playing); }, [player, playing]);
  const data = useCommentaryData(matchId, lang, (res: CommentaryResp) => {
    player.setTts(res.tts === "none" ? "none" : "azure");
    player.offer(res.lines ?? []);
  });
  return {
    state, lines: data.data.lines, status: data.status, tts: data.data.tts,
    setEnabled: (on) => player.setEnabled(on), setVolume: (v) => player.setVolume(v),
  };
}
