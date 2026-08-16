import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice layer for JARVIS:
 *  - continuous speech recognition with the wake word "jarvis"
 *  - push-to-talk (bypasses the wake word)
 *  - spoken replies via the browser speech synthesis engine
 */

type SR = any;

function getRecognition(): SR | null {
  if (typeof window === "undefined") return null;
  const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

const WAKE = /\b(jarvis|jervis|jarvace|jarv)\b/i;

export function useVoice(onCommand: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [awake, setAwake] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [speaking, setSpeaking] = useState(false);

  const recRef = useRef<SR | null>(null);
  const wantRef = useRef(false);
  const forceRef = useRef(false); // push-to-talk: skip wake word
  const cmdRef = useRef(onCommand);
  cmdRef.current = onCommand;

  useEffect(() => {
    const r = getRecognition();
    setSupported(!!r && typeof window !== "undefined" && "speechSynthesis" in window);
  }, []);

  const handleFinal = useCallback((raw: string) => {
    const text = raw.trim();
    if (!text) return;
    if (forceRef.current) forceRef.current = false;
    setAwake(false);
    cmdRef.current(text);
  }, []);

  const start = useCallback((force = false) => {
    const rec = getRecognition();
    if (!rec) return;
    forceRef.current = force;
    wantRef.current = true;
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) handleFinal(res[0].transcript);
        else interim += res[0].transcript;
      }
      setHeard(interim);
    };
    rec.onerror = () => {};
    rec.onend = () => {
      setListening(false);
      setHeard("");
      if (wantRef.current) {
        // auto-restart so listening never silently dies
        setTimeout(() => {
          if (wantRef.current) {
            try { rec.start(); setListening(true); } catch {}
          }
        }, 400);
      }
    };
    try {
      rec.start();
      recRef.current = rec;
      setListening(true);
    } catch {}
  }, [handleFinal]);

  const stop = useCallback(() => {
    wantRef.current = false;
    forceRef.current = false;
    setAwake(false);
    try { recRef.current?.stop(); } catch {}
    setListening(false);
    setHeard("");
  }, []);

  const toggle = useCallback(() => {
    if (wantRef.current) stop();
    else start(false);
  }, [start, stop]);

  useEffect(() => () => { wantRef.current = false; try { recRef.current?.stop(); } catch {} }, []);

  const speak = useCallback((text: string) => {
    if (!speakReplies || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const clean = text
      .replace(/```[\s\S]*?```/g, " code block ")
      .replace(/[*_`#>|]/g, "")
      .replace(/\[(.*?)\]\(.*?\)/g, "$1")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 700);
    if (!clean) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(clean);
    const voices = window.speechSynthesis.getVoices();
    const pick =
      voices.find((v) => /Google UK English Male/i.test(v.name)) ||
      voices.find((v) => /(Daniel|Arthur|George|Ryan|Male)/i.test(v.name) && /en/i.test(v.lang)) ||
      voices.find((v) => /en-GB/i.test(v.lang)) ||
      voices.find((v) => /en/i.test(v.lang));
    if (pick) u.voice = pick;
    u.rate = 1.02;
    u.pitch = 0.95;
    u.onstart = () => setSpeaking(true);
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(u);
  }, [speakReplies]);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  return {
    supported,
    listening,
    awake,
    heard,
    speaking,
    speakReplies,
    setSpeakReplies,
    toggle,
    pushToTalk: () => start(true),
    stop,
    speak,
    stopSpeaking,
  };
}
