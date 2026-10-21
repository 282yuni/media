# 에셜론 녹음 보정 (2026-10-20): 서림(2번)에서 고른 "녹음판"과 똑같이 — 솔 톤 + 부드럽게 + 쇳소리 줄임 + 문장별 크기 맞춤
# clips_보정전/ (원래 녹음) → clips/. 문장 끝 올리기·내리기는 안 함 (로봇처럼 들려서 뺌)
# 새로 녹음해서 clips_보정전/ 에 넣은 뒤:  python\python.exe profiles\서림\목소리보정.py
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SRC, OUT = HERE / "clips_보정전", HERE / "clips"
SPEED = 196 / 200   # 에셜론 녹음 중앙값 200Hz → "솔"(196Hz)


def fix(x: np.ndarray, r: int) -> np.ndarray:
    n = int(len(x) / SPEED)
    x = np.interp(np.arange(n) * SPEED, np.arange(len(x)), x)
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / r)
    g = np.ones_like(fr)
    g[fr < 80] = 0.4
    g *= 1 + 0.25 * np.exp(-((fr - 280) / 200) ** 2)    # 따뜻하고 둥글게
    g *= 1 - 0.35 * np.exp(-((fr - 3500) / 1300) ** 2)  # 거친 소리 빼서 부드럽게
    g *= 1 / (1 + (fr / 3600) ** 6)                      # 쇳소리 줄이기: 전화가 안 쓰는 높은 소리 걷어냄 (2026-10-20)
    g *= 1 - 0.2 * np.exp(-((fr - 450) / 200) ** 2)     # 방 울림처럼 먹먹한 소리 빼기
    g *= 1 + 0.4 * np.exp(-((fr - 2000) / 700) ** 2)    # 말소리 앞으로 (가까이서 말하는 느낌)
    y = np.fft.irfft(X * g, len(x))
    env = np.abs(y)
    thr = np.percentile(env, 97)
    y = np.where(env > thr, np.sign(y) * (thr + (env - thr) * 0.7), y)
    rms = np.sqrt(np.mean(y ** 2)) + 1e-6
    return y * min(5200 / rms, 31000 / (np.abs(y).max() + 1e-6))   # 2026-10-21 소리 크게 (3200 → 5200, 약 +4dB)


if __name__ == "__main__":
    for f in sorted(SRC.glob("clip_*.wav")):
        with wave.open(str(f)) as w:
            r = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
        with wave.open(str(OUT / f.name), "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(r)
            o.writeframes(fix(x, r).astype(np.int16).tobytes())
    print("보정 완료")

# 빠르기 맞추기 (2026-10-20): 다른 문장보다 10% 넘게 빠른 녹음만 중간 빠르기(5.4 글자/초) 근처로 살짝 늦춤
# 번호: 늦출 비율 (1보다 작을수록 느려짐). 임시 녹음(24~31·33·35)은 글과 실제 말이 달라 재지 않음
SLOW = {11: 0.84, 18: 0.92, 20: 0.88, 22: 0.91}
if __name__ == "__main__":
    import subprocess, tempfile
    for cid, k in SLOW.items():
        f = OUT / f"clip_{cid:03d}.wav"
        if not f.exists():
            continue
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.wav"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(f), "-af",
                            f"rubberband=tempo={k}:transients=smooth:formant=preserved", str(t)], check=True)
            f.write_bytes(t.read_bytes())
    print("빠르기 맞춤:", ", ".join(f"{c}번" for c in SLOW))
