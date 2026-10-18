"""내 실제 녹음을 문장 단위로 잘라 두고, 통화 때 그대로(합성·변환 없이) 재생한다.

  python main.py clips 내녹음.mp3   → clips/ 폴더에 clip_001.wav … + clips.yaml (문장 목록)
  clips.yaml 을 열어 내 목소리가 아닌 줄(상대 목소리)은 use: false 로, 틀린 글자는 고쳐 둔다.
"""
import re
import wave
from pathlib import Path

import numpy as np
import yaml

from .config import resolve
from .voice import TTS_RATE

TOKEN = re.compile(r"\[클립:(\d+)\]")


def decode(src: Path, rate: int = TTS_RATE) -> np.ndarray:
    """녹음 파일(mp3, m4a, wav …)을 모노 int16 로. 소리 자체는 바꾸지 않고 형식만 맞춘다. (ffmpeg 설치 필요 없음)"""
    import av
    out = []
    with av.open(str(src)) as f:
        res = av.AudioResampler(format="s16", layout="mono", rate=rate)
        for frame in f.decode(audio=0):
            for r in res.resample(frame):
                out.append(r.to_ndarray().reshape(-1))
        for r in res.resample(None):
            out.append(r.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.int16) if out else np.zeros(0, np.int16)


def _detect(db: np.ndarray, start: int, end: int, noise_db: float, min_silence: float, hop: float) -> list[tuple[int, int]]:
    """[start, end) 프레임 구간에서 noise_db 보다 조용한 게 min_silence 초 이상이면 끊는다 → 말 덩어리 (시작, 끝) 프레임."""
    need = int(min_silence / hop)
    segs, cur, quiet = [], None, 0
    for i in range(start, end):
        if db[i] > noise_db:
            if cur is None:
                cur = i
            quiet = 0
        elif cur is not None:
            quiet += 1
            if quiet >= need:
                segs.append((cur, i - quiet + 1))
                cur, quiet = None, 0
    if cur is not None:
        segs.append((cur, end - quiet))
    pad = int(0.1 / hop)  # 앞뒤 0.1초 여유 → 첫 음절 안 잘림
    return [(max(start, s - pad), min(end, e + pad)) for s, e in segs if (e - s) * hop >= 0.4]


def find_segments(src, noise_db: float = -35, min_silence: float = 0.6,
                  max_len: float = 12.0, pcm: np.ndarray | None = None) -> list[tuple[float, float]]:
    """문장 단위로 자르기 (초 단위 목록). 12초 넘게 이어 말한 덩어리는 더 짧은 쉼(0.3초)으로 한 번 더 자른다."""
    pcm = decode(src) if pcm is None else pcm
    hop = 0.01
    n = int(TTS_RATE * hop)
    frames = pcm[: len(pcm) // n * n].astype(np.float32).reshape(-1, n) / 32768.0
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    out = []
    for s, e in _detect(db, 0, len(db), noise_db, min_silence, hop):
        if (e - s) * hop > max_len:
            out += _detect(db, s, e, noise_db, 0.3, hop) or [(s, e)]
        else:
            out.append((s, e))
    return [(s * hop, e * hop) for s, e in out]


def cut(cfg: dict, src: Path, noise_db: int = -35, min_silence: float = 0.6) -> Path:
    out_dir = resolve(cfg["voice"].get("clips_dir", "clips"))
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = out_dir / "clips.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
    next_id = max((c["id"] for c in catalog), default=0) + 1

    pcm = decode(src)
    segs = find_segments(src, noise_db, min_silence, pcm=pcm)
    print(f"{src.name}: 문장 덩어리 {len(segs)}개를 찾았습니다.")
    try:
        from .engine import make_ears
        ears = make_ears(cfg)
    except Exception as e:
        ears = None
        print(f"  (음성 인식 없이 자르기만 합니다: {e}) → clips.yaml 의 text 를 직접 채워주세요.")

    for start, end in segs:
        cid = next_id
        next_id += 1
        wav = out_dir / f"clip_{cid:03}.wav"
        # 소리 자체는 손대지 않고 재생용 형식(모노 24kHz)으로만 바꿔 저장
        piece = pcm[int(start * TTS_RATE):int(end * TTS_RATE)]
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TTS_RATE)
            w.writeframes(piece.tobytes())
        text = ears.transcribe_pcm(piece, TTS_RATE) if ears else ""
        catalog.append({"id": cid, "file": wav.name, "text": text, "use": True,
                        "source": f"{src.name} {start:.1f}~{end:.1f}초"})
        print(f"  [{cid:3}] {end - start:4.1f}초  {text}")

    catalog_path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\n완료 → {catalog_path}\n"
          "꼭 열어서 (1) 상대방 목소리·잡음 줄은 use: false  (2) 틀린 글자 고치기  (3) 너무 긴 덩어리는 다시 자르기")
    return catalog_path


class ClipBank:
    """통화 중 재생할 내 녹음 문장들."""

    def __init__(self, cfg: dict):
        self.dir = resolve(cfg["voice"].get("clips_dir", "clips"))
        path = self.dir / "clips.yaml"
        items = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
        self.items = {c["id"]: c for c in items if c.get("use", True) and (c.get("text") or "").strip()}

    def __bool__(self):
        return bool(self.items)

    def catalog(self) -> str:
        return "\n".join(f"[클립:{cid}] {c['text'].strip()}" for cid, c in sorted(self.items.items()))

    def text(self, cid: int) -> str:
        return self.items[cid]["text"].strip() if cid in self.items else ""

    def pcm(self, cid: int) -> bytes:
        with wave.open(str(self.dir / self.items[cid]["file"])) as w:
            if w.getframerate() != TTS_RATE or w.getnchannels() != 1:
                raise RuntimeError(f"clip {cid}: 24kHz 모노가 아닙니다. `python main.py clips` 로 다시 만들어 주세요.")
            return w.readframes(w.getnframes())

    def chunks(self, cid: int, size: int = TTS_RATE // 5 * 2):
        """0.2초씩 나눠서 내보냄 (중간에 상대가 끼어들면 바로 멈출 수 있게)."""
        data = self.pcm(cid)
        for i in range(0, len(data), size):
            yield data[i:i + size]


def split_tokens(text: str) -> list[str]:
    """'네 [클립:3] 그럼 [클립:7]' → ['네', '[클립:3]', '그럼', '[클립:7]']"""
    parts, pos = [], 0
    for m in TOKEN.finditer(text):
        if text[pos:m.start()].strip():
            parts.append(text[pos:m.start()].strip())
        parts.append(m.group(0))
        pos = m.end()
    if text[pos:].strip():
        parts.append(text[pos:].strip())
    return parts
