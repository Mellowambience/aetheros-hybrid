#!/usr/bin/env python3
"""
AetherOS Speaker Gate — owner-only voice verification.
Two backends:
  simple : MFCC-style voiceprint (numpy/scipy only, weak but zero-model)
  ecapa  : SpeechBrain ECAPA-TDNN (robust; downloads ~90MB on first use)

The gate decides whether an incoming utterance is the owner's voice.
If not enrolled, the loop stays in ENROLL state and ignores everyone else.
Local-first, no cloud, no biometrics leave the machine.
"""
from __future__ import annotations
import json, math, os
from pathlib import Path
import numpy as np

EMBED_DIR = Path.home() / "AetherOS_Hybrid" / "voice" / "data" / "voices"
EMBED_DIR.mkdir(parents=True, exist_ok=True)
VOICEPRINT = EMBED_DIR / "owner_voiceprint.json"

# ---------- simple MFCC-ish voiceprint (dependency-light) ----------
def _frames(wav: np.ndarray, sr: int, win: int = 400, hop: int = 160):
    for i in range(0, max(1, len(wav) - win), hop):
        yield wav[i:i + win]

def _preemph(win: np.ndarray, a: float = 0.97):
    return np.append(win[0], win[1:] - a * win[:-1])

def _mel_filterbank(nfilt: int, nfft: int, sr: int):
    low, high = 0, sr / 2
    pts = np.linspace(low, high, nfilt + 2)
    bins = np.floor((nfft + 1) * pts / sr).astype(int)
    fb = np.zeros((nfilt, nfft // 2 + 1))
    for m in range(1, nfilt + 1):
        f_m_minus, f_m, f_m_plus = bins[m - 1], bins[m], bins[m + 1]
        for k in range(f_m_minus, f_m):
            if f_m > f_m_minus:
                fb[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)
        for k in range(f_m, f_m_plus):
            if f_m_plus > f_m:
                fb[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)
    return fb

def _simple_embedding(wav: np.ndarray, sr: int, n_mfcc: int = 13) -> np.ndarray:
    wav = wav.astype(np.float32)
    if wav.size == 0:
        return np.zeros(n_mfcc)
    # crude normalization
    wav = wav / (np.max(np.abs(wav)) + 1e-9)
    nfft = 512
    fb = _mel_filterbank(26, nfft, sr)
    feats = []
    for win in _frames(wav, sr):
        x = _preemph(win)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), nfft))
        power = spec ** 2
        mel = fb @ power[:len(fb[0])]
        mel = np.where(mel == 0, 1e-10, mel)
        logmel = np.log(mel)
        # DCT-II (type-2) to MFCC
        n = len(logmel)
        dct = np.zeros(n_mfcc)
        for k in range(n_mfcc):
            dct[k] = np.sum(logmel * np.cos(np.pi * k * (np.arange(n) + 0.5) / n))
        feats.append(dct)
    if not feats:
        return np.zeros(n_mfcc)
    return np.mean(feats, axis=0)

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)

class SpeakerGate:
    def __init__(self, backend: str = "ecapa", threshold: float = 0.85):
        self.backend = backend
        self.threshold = threshold
        self.enrolled = VOICEPRINT.exists()
        # SECURITY: the dependency-light simple backend is NOT discriminative
        # enough to certify an owner lock. It is allowed for audit/preview only.
        self.certifiable = backend in ("ecapa",)

    def enroll(self, wav: np.ndarray, sr: int) -> dict:
        if self.backend == "simple":
            emb = _simple_embedding(wav, sr)
            rec = {"backend": self.backend, "certifiable": False,
                   "threshold": self.threshold, "embedding": emb.tolist(),
                   "created_at": _now(),
                   "warning": "simple backend is NOT a secure owner lock; install speechbrain for ECAPA."}
            VOICEPRINT.write_text(json.dumps(rec), encoding="utf-8")
            self.enrolled = True
            return {"enrolled": True, "certifiable": False,
                    "warning": "simple backend enrolled; NOT secure. Use ECAPA for owner-lock.",
                    "path": str(VOICEPRINT)}
        # ECAPA path
        emb = _ecapa_embedding(wav, sr)
        if emb is None:
            return {"enrolled": False, "error": "ecapa_unavailable",
                    "hint": "pip install speechbrain; falling back requires certifiable backend."}
        rec = {"backend": "ecapa", "certifiable": True,
               "threshold": self.threshold, "embedding": emb.tolist(),
               "created_at": _now()}
        VOICEPRINT.write_text(json.dumps(rec), encoding="utf-8")
        self.enrolled = True
        return {"enrolled": True, "certifiable": True, "path": str(VOICEPRINT)}

    def verify(self, wav: np.ndarray, sr: int) -> dict:
        if not self.enrolled:
            return {"is_owner": False, "reason": "not_enrolled", "score": 0.0}
        rec = json.loads(VOICEPRINT.read_text(encoding="utf-8"))
        ref = np.array(rec["embedding"], dtype=float)
        backend = rec.get("backend", "simple")
        if backend == "simple":
            emb = _simple_embedding(wav, sr)
            score = cosine(emb, ref)
            # simple backend can NEVER assert owner for locking; report but deny
            return {"is_owner": False, "score": round(score, 4),
                    "threshold": rec.get("threshold", self.threshold),
                    "reason": "simple_backend_not_certifiable",
                    "note": "enroll with ECAPA to enable owner-lock."}
        emb = _ecapa_embedding(wav, sr)
        if emb is None:
            return {"is_owner": False, "reason": "ecapa_unavailable", "score": 0.0}
        score = cosine(emb, ref)
        is_owner = score >= rec.get("threshold", self.threshold)
        return {"is_owner": bool(is_owner), "score": round(score, 4),
                "threshold": rec.get("threshold", self.threshold),
                "reason": "ok" if is_owner else "score_below_threshold"}


def _ecapa_embedding(wav: np.ndarray, sr: int):
    """ECAPA-TDNN speaker embedding via SpeechBrain. Returns None if unavailable."""
    try:
        from speechbrain.inference.speaker import SpeakerRecognition
        import torch
    except Exception:
        return None
    try:
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        model = SpeakerRecognition.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(EMBED_DIR / "ecapa"),
            run_opts={"device": DEVICE})
        import torch as _t
        tensor = _t.FloatTensor(wav).unsqueeze(0)
        emb = model.encode_batch(tensor)
        return emb.squeeze(0).squeeze(0).detach().cpu().numpy().astype(float)
    except Exception:
        return None

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

if __name__ == "__main__":
    # offline self-test: synth two different tones, enroll one, verify both
    import numpy as np
    sr = 16000
    t = np.linspace(0, 1, sr, endpoint=False)
    owner = (np.sin(2 * np.pi * 220 * t) * 0.5).astype(np.float32)
    other = (np.sin(2 * np.pi * 330 * t) * 0.5).astype(np.float32)
    g = SpeakerGate(backend="ecapa", threshold=0.85)  # default secure backend
    if VOICEPRINT.exists():
        VOICEPRINT.unlink()
    e = g.enroll(owner, sr)
    print("enroll:", e)
    if e.get("certifiable"):
        print("owner ->", g.verify(owner, sr))
        print("other ->", g.verify(other, sr))
        print("GATE OK" if (g.verify(owner, sr)["is_owner"] and not g.verify(other, sr)["is_owner"]) else "GATE WEAK")
    else:
        print("SECURE OWNER-LOCK UNAVAILABLE:", e.get("error") or e.get("warning"))
        print("Install SpeechBrain (pip install speechbrain) to enable ECAPA. Gate refuses to lock on weak backend.")
