"""내 실제 녹음을 문장 단위로 잘라 두고, 통화 때 그대로(합성·변환 없이) 재생한다.

  python main.py clips 내녹음.mp3   → clips/ 폴더에 clip_001.wav … + clips.yaml (문장 목록)
  clips.yaml 을 열어 내 목소리가 아닌 줄(상대 목소리)은 use: false 로, 틀린 글자는 고쳐 둔다.
"""
import re
import subprocess
import wave
from pathlib import Path

import yaml

from .config import resolve
from .voice import TTS_RATE

TOKEN = re.compile(r"\[클립:(\d+)\]")


def _ffmpeg(*args: str) -> str:
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg 실행 실패 (설치 확인: https://ffmpeg.org): " + res.stderr[-500:])
    return res.stderr


def _duration(src: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


def _detect(src: Path, start: float, end: float, noise_db: int, min_silence: float) -> list[tuple[float, float]]:
    """[start, end] 구간에서 조용한 부분을 기준으로 말 덩어리 (시작, 끝) 초 목록."""
    log = _ffmpeg("-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src),
                  "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-")
    starts = [start + float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [start + float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    segs, cur = [], start
    for s, e in zip(starts, ends + [end]):
        if s - cur >= 0.4:
            segs.append((max(start, cur - 0.1), min(end, s + 0.1)))  # 앞뒤 0.1초 여유 → 첫 음절 안 잘림
        cur = e
    if end - cur >= 0.4:
        segs.append((max(start, cur - 0.1), end))
    return segs


def find_segments(src: Path, noise_db: int = -35, min_silence: float = 0.6,
                  max_len: float = 12.0) -> list[tuple[float, float]]:
    """문장 단위로 자르기. 12초가 넘게 이어 말한 덩어리는 더 짧은 쉼(0.3초) 기준으로 한 번 더 자른다."""
    out = []
    for s, e in _detect(src, 0.0, _duration(src), noise_db, min_silence):
        if e - s > max_len:
            out += _detect(src, s, e, noise_db, 0.3) or [(s, e)]
        else:
            out.append((s, e))
    return out


def cut(cfg: dict, src: Path, noise_db: int = -35, min_silence: float = 0.6) -> Path:
    out_dir = resolve(cfg["voice"].get("clips_dir", "clips"))
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = out_dir / "clips.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
    next_id = max((c["id"] for c in catalog), default=0) + 1

    segs = find_segments(src, noise_db, min_silence)
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
        _ffmpeg("-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src),
                "-ac", "1", "-ar", str(TTS_RATE), "-sample_fmt", "s16", str(wav))
        text = ""
        if ears:
            import numpy as np
            with wave.open(str(wav)) as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            text = ears.transcribe_pcm(pcm, TTS_RATE)
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
