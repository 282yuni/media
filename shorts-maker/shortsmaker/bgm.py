"""저작권 걱정 없는 배경음악/효과음을 직접 합성한다 (우쿨렐레풍 뜯는 소리 + 박수)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _freq(name: str) -> float:
    n, octv = name[:-1], int(name[-1])
    semis = NOTE[n[0]] + (1 if "#" in n else 0) + 12 * (octv - 4)
    return 261.63 * 2 ** (semis / 12)


def _pluck(freq: float, dur: float, rng) -> np.ndarray:
    """Karplus-Strong 현 뜯는 소리."""
    n = int(SR * dur)
    period = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = 0.497 * (buf[i % period] + buf[(i + 1) % period])
    return out


def _clap(rng, dur=0.12) -> np.ndarray:
    n = int(SR * dur)
    return rng.uniform(-1, 1, n) * np.exp(-np.linspace(0, 30, n))


def _write(path: Path, x: np.ndarray) -> Path:
    x = x / (np.abs(x).max() + 1e-9) * 0.8
    st = np.repeat((x * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
    return path


def make_bgm(path: Path, seconds: float, bpm: int = 116, seed: int = 7) -> Path:
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    prog = [["C4", "E4", "G4", "C5"], ["A3", "C4", "E4", "A4"], ["F3", "A3", "C4", "F4"], ["G3", "B3", "D4", "G4"]]
    melody = ["E5", "G5", "A5", "G5", "E5", "D5", "C5", "D5", "E5", "E5", "D5", "C5", "D5", "E5", "G5", "G5"]
    total = int(SR * (seconds + 1))
    mix = np.zeros(total)
    t, bar = 0.0, 0
    cache: dict = {}
    while t < seconds:
        chord = prog[bar % 4]
        for b in range(4):  # 한 마디 4박: 다운-업 스트럼
            for k, off in enumerate((0, beat / 2)):
                start = int(SR * (t + b * beat + off))
                for j, nt in enumerate(chord if k == 0 else chord[::-1]):
                    key = (nt, k)
                    if key not in cache:
                        cache[key] = _pluck(_freq(nt), beat * 1.6, rng) * (0.5 if k else 0.7)
                    s = start + int(SR * 0.012 * j)
                    seg = cache[key][: max(0, total - s)]
                    mix[s:s + len(seg)] += seg
            if b in (1, 3):
                s = int(SR * (t + b * beat)); c = _clap(rng) * 0.9
                mix[s:s + len(c)] += c[: max(0, total - s)]
            mn = melody[(bar * 4 + b) % len(melody)]
            s = int(SR * (t + b * beat)); m = _pluck(_freq(mn), beat * 1.2, rng) * 0.9
            mix[s:s + len(m)] += m[: max(0, total - s)]
        t += 4 * beat
        bar += 1
    mix = mix[: int(SR * seconds)]
    fade = int(SR * 1.2)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return _write(path, mix)


def make_ding(path: Path) -> Path:
    """순위 바뀔 때 '띵' 효과음."""
    t = np.linspace(0, 0.45, int(SR * 0.45), endpoint=False)
    x = (np.sin(2 * np.pi * 1318.5 * t) + 0.5 * np.sin(2 * np.pi * 1975.5 * t)) * np.exp(-t * 9)
    return _write(path, x)
