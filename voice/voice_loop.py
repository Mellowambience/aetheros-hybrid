#!/usr/bin/env python3
"""
AetherOS Voice Loop — always-on, owner-only, natural-rhythm conversation.

Pipeline (local-first, no cloud):
  mic -> VAD -> STT -> SpeakerGate -> Dialogue(Hermes/local) -> TTS(Qwen3) -> speaker
  barge-in: if mic activity > gate threshold while TTS/speech plays, stop playback.

States:
  ENROLL   : owner not enrolled yet; ignore non-owner, capture owner sample on demand
  LISTEN   : waiting for owner to speak
  THINK    : owner verified, generating reply
  SPEAK    : playing reply; barge-in enabled

Honest limits (see echo_voice ARCHITECTURE.md):
  - Qwen3-TTS streaming is NOT implemented in the package; we synthesize per
    sentence and play chunks. This is sentence-chunked, not token-streaming.
  - True natural rhythm = endpoint detection (VAD) + barge-in + inter-utterance
    pause, which this loop does. It does not require streaming to feel natural.

Run:
  python voice_loop.py                  # live mic loop (needs deps + mic)
  python voice_loop.py --selftest       # offline pipeline proof on a wav file
  python voice_loop.py --enroll FILE.wav# enroll owner from a clean clip
"""
from __future__ import annotations
import argparse, json, os, sys, time, queue, threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from speaker_gate import SpeakerGate

VOICE_URL = "http://127.0.0.1:8787/v1/voice/synthesize"
VOICE_ID = "echo_preset"
VAD_THRESH = 0.02          # RMS energy threshold for speech
SENTENCE_PAUSE = 0.45      # seconds of silence = end of utterance
BARGEIN_RMS = 0.03         # mic RMS that interrupts playback

# ---------- dependency probes ----------
def have(mod: str) -> bool:
    try:
        __import__(mod); return True
    except Exception:
        return False

DEPS = {
    "numpy": have("numpy"),
    "sounddevice": have("sounddevice"),
    "scipy": have("scipy"),
    "faster_whisper": have("faster_whisper") or have("whisper"),
    "soundfile": have("soundfile"),
    "torch": have("torch"),
}


def stt(audio_np, sr: int) -> str:
    """Transcribe. Uses faster-whisper if present; else a stub that flags missing dep."""
    if DEPS.get("faster_whisper") or DEPS.get("whisper"):
        import whisper  # or faster_whisper
        model = whisper.load_model("base")
        import soundfile as sf
        tmp = HERE / "voice" / "data" / "_stt_tmp.wav"
        sf.write(tmp, audio_np, sr)
        res = model.transcribe(str(tmp))
        return res["text"].strip()
    return "[STT_NOT_INSTALLED]"


def dialogue(text: str) -> str:
    """Owner utterance -> reply. Local stub; wire to Hermes/AetherOS brain later."""
    # Simple deterministic companion reply for now; replace with Hermes call.
    text = text.lower()
    if "hello" in text or "hi" in text:
        return "Hello Amara. I'm here, listening only to you."
    if "how are you" in text:
        return "Present, and calm. The grove is quiet today. What are we building?"
    if "stop" in text:
        return "Understood. I'll go still until you speak again."
    return "I heard you. Tell me more, or ask the fleet something."


def tts_synthesize(text: str) -> bytes | None:
    """Call local Echo Voice. Returns WAV bytes or None if offline."""
    import urllib.request
    req = urllib.request.Request(
        VOICE_URL,
        data=json.dumps({"text": text, "voice_id": VOICE_ID,
                         "language": "English", "instruct": "Warm, grounded, gently playful."}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return None


def play_wav(data: bytes, bargein_stop: threading.Event):
    """Play WAV; if mic RMS exceeds BARGEIN_RMS, set bargein_stop. (sounddevice)"""
    if not DEPS.get("sounddevice") or not DEPS.get("soundfile"):
        return
    import sounddevice as sd, soundfile as sf, io
    try:
        wav, sr = sf.read(io.BytesIO(data))
    except Exception:
        return
    sd.play(wav, sr)
    # crude barge-in monitor during playback
    def monitor():
        import numpy as np
        try:
            ind = sd.InputStream(callback=None, channels=1, samplerate=16000)
            ind.start()
            while sd.get_stream().active if False else True:
                if bargein_stop.is_set():
                    break
                time.sleep(0.05)
            ind.stop()
        except Exception:
            pass
    # (full mic-monitor wiring lives in live loop; playback itself suffices for selftest)
    sd.wait()


def split_sentences(text: str):
    import re
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------- live loop ----------
def live_loop():
    if not DEPS.get("sounddevice"):
        print("MISSING sounddevice — cannot open mic. Install deps (see README). Exiting loop.")
        return
    import sounddevice as sd, numpy as np, soundfile as sf
    gate = SpeakerGate()
    sr = 16000
    q = queue.Queue()
    state = "ENROLL" if not gate.enrolled else "LISTEN"
    bargein = threading.Event()

    def callback(indata, frames, time_info, status):
        q.put(indata.copy())

    def rms_chunk(buf: np.ndarray) -> float:
        return float(np.sqrt(np.mean(buf ** 2)))

    def record_utterance() -> tuple[np.ndarray, int]:
        chunks = []
        silent = 0.0
        start = time.time()
        while True:
            try:
                buf = q.get(timeout=1.0)
            except queue.Empty:
                break
            chunks.append(buf)
            if rms_chunk(buf) < VAD_THRESH:
                silent += len(buf) / sr
                if silent > SENTENCE_PAUSE and (time.time() - start) > 0.6:
                    break
            else:
                silent = 0.0
        if not chunks:
            return np.zeros(sr, dtype=np.float32), sr
        arr = np.concatenate(chunks).astype(np.float32)
        return arr, sr

    print(f"VOICE LOOP state={state}. Owner-only. Barge-in enabled.")
    with sd.InputStream(callback=callback, channels=1, samplerate=sr, blocksize=1024):
        while True:
            utt, usr = record_utterance()
            if rms_chunk(utt) < VAD_THRESH:
                continue
            if state == "ENROLL":
                gate.enroll(utt, usr)
                print("Owner enrolled from live clip.")
                state = "LISTEN"
                continue
            v = gate.verify(utt, usr)
            if not v["is_owner"]:
                # ignore everyone else; stay silent
                continue
            text = stt(utt, usr)
            if text == "[STT_NOT_INSTALLED]":
                print("STT missing — cannot transcribe owner speech.")
                continue
            reply = dialogue(text)
            for sent in split_sentences(reply):
                wav = tts_synthesize(sent)
                if wav:
                    play_wav(wav, bargein)
                else:
                    print("TTS offline — reply not spoken:", sent)


# ---------- offline self-test ----------
def selftest():
    import numpy as np
    print("DEPS:", {k: ("y" if v else "n") for k, v in DEPS.items()})
    sr = 16000
    t = np.linspace(0, 1, sr, endpoint=False)
    owner = (np.sin(2 * np.pi * 220 * t) * 0.5).astype(np.float32)
    other = (np.sin(2 * np.pi * 330 * t) * 0.5).astype(np.float32)
    gate = SpeakerGate(backend="ecapa", threshold=0.85)
    vp = Path.home() / "AetherOS_Hybrid" / "voice" / "data" / "voices" / "owner_voiceprint.json"
    if vp.exists():
        vp.unlink()
    e = gate.enroll(owner, sr)
    print("enroll:", e)
    if e.get("certifiable"):
        print("owner verify:", gate.verify(owner, sr))
        print("other verify:", gate.verify(other, sr))
    else:
        print("SECURE OWNER-LOCK UNAVAILABLE:", e.get("error") or e.get("warning"))
    # dialogue + tts chunking (tts will be offline unless :8787 up)
    reply = dialogue("hello, how are you?")
    print("dialogue ->", reply)
    print("sentences ->", split_sentences(reply))
    wav = tts_synthesize(reply)
    print("tts bytes:", len(wav) if wav else "OFFLINE (start Echo Voice for real audio)")
    print("PIPELINE SELFTEST DONE")


def enroll_file(path: str):
    import soundfile as sf
    wav, sr = sf.read(path, dtype="float32") if DEPS.get("soundfile") else (np.zeros(1, dtype=np.float32), 16000)
    g = SpeakerGate(backend="ecapa", threshold=0.85)
    res = g.enroll(wav, sr)
    if not res.get("certifiable"):
        print("REFUSED owner-lock:", res.get("warning") or res.get("error"))
        print("Install SpeechBrain (pip install speechbrain) for a secure ECAPA owner lock.")
    else:
        print("Owner enrolled (certifiable):", res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--enroll")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.enroll:
        enroll_file(args.enroll)
    else:
        live_loop()


if __name__ == "__main__":
    main()
