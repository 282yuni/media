"""무료 음성 인식: 내 PC에서 직접 돌린다. 인터넷·유료 API 필요 없음.

- sherpa (기본): 한국어 전용 모델(models/ko, 약 75MB)을 같이 넣어 배포 → 설치 즉시 동작, 빠름
- whisper: faster-whisper (pip install faster-whisper, 처음 한 번 모델을 내려받음)
"""
import re
from pathlib import Path

import numpy as np

from .config import resolve

_MODEL = None


def _sherpa(cfg: dict):
    import sherpa_onnx
    d = resolve(cfg.get("stt", {}).get("model_dir", "models/ko"))
    if not (d / "tokens.txt").exists():
        raise RuntimeError(f"한국어 음성 인식 모델이 없습니다: {d}  (완성본 ZIP 의 models 폴더를 확인하세요)")
    pick = lambda stem: str(next(iter(sorted(d.glob(f"{stem}*.int8.onnx"))), None) or next(iter(sorted(d.glob(f"{stem}*.onnx")))))
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=pick("encoder"), decoder=pick("decoder"), joiner=pick("joiner"),
        tokens=str(d / "tokens.txt"), num_threads=cfg.get("stt", {}).get("threads", 4),
    )


def _cuda_dlls() -> None:
    """그래픽카드(cuda)로 돌릴 때 필요한 무료 NVIDIA 부품(pip 의 nvidia-cublas/cudnn)을 찾게 해 줌 (Windows)."""
    import os
    import site
    for sp in site.getsitepackages():
        for sub in ("cublas", "cudnn"):
            d = Path(sp) / "nvidia" / sub / "bin"
            if d.is_dir():
                os.add_dll_directory(str(d))
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def _whisper(cfg: dict):
    from faster_whisper import WhisperModel
    s = cfg.get("stt", {})
    if s.get("device") == "cuda":
        _cuda_dlls()
    print(f"   (음성 인식 모델 '{s.get('local_model', 'small')}' 불러오는 중… 처음엔 내려받느라 몇 분 걸릴 수 있어요)")
    m = WhisperModel(s.get("local_model", "small"), device=s.get("device", "cpu"), compute_type=s.get("compute_type", "int8"))
    list(m.transcribe(np.zeros(16000, np.float32), language="ko")[0])  # 첫 받아 적기가 2초 걸리지 않게 미리 한 번 돌려 둠
    return m


def engine(cfg: dict) -> str:
    return cfg.get("stt", {}).get("local_engine", "sherpa")


def _model(cfg: dict):
    global _MODEL
    if _MODEL is None:
        _MODEL = _sherpa(cfg) if engine(cfg) == "sherpa" else _whisper(cfg)
    return _MODEL


def _to16k(pcm: np.ndarray, rate: int) -> np.ndarray:
    audio = pcm.astype(np.float32) / 32768.0
    if rate != 16000:
        n = int(len(audio) * 16000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


class LocalEars:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        terms = cfg.get("voice", {}).get("keyterms") or []
        topic = cfg.get("stt", {}).get("prompt", "치과 상담 전화.")  # 프로필마다 통화 주제 (Whisper 가 낱말을 더 잘 맞힘)
        self.prompt = f"{topic} " + ", ".join(terms) if terms else topic
        _model(cfg)

    def transcribe_pcm(self, pcm: np.ndarray, rate: int) -> str:
        audio = _to16k(pcm, rate)
        if engine(self.cfg) == "sherpa":
            rec = _model(self.cfg)
            s = rec.create_stream()
            s.accept_waveform(16000, audio)
            rec.decode_stream(s)
            return s.result.text.strip()
        segments, _ = _model(self.cfg).transcribe(
            audio, language="ko", beam_size=1, initial_prompt=self.prompt, condition_on_previous_text=False,
            # vad_filter 는 끔: 한 마디마다 1~3초 더 걸려서 대답이 늦어짐 (2026-10-21). 잡음은 no_speech_prob·아래 목록으로 거름
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.no_speech_prob < 0.6).strip()
        # Whisper 가 잡음에 자주 지어내는 말 (유튜브 자막 습관) → 못 들은 것으로
        if re.fullmatch(r"(시청해 ?주셔서 감사합니다|구독과 좋아요|MBC 뉴스.*|자막.*|감사합니다)[.!]?", text):
            return ""
        return text

    def transcribe_call_file(self, path) -> str:
        """녹음 파일 → 문장마다 시간이 붙은 대본 (화자 구분은 못 함)."""
        from .clips import decode, find_segments
        pcm = decode(path, 16000)
        lines = []
        for start, end in find_segments(path, pcm=decode(path)):
            text = self.transcribe_pcm(pcm[int(start * 16000):int(end * 16000)], 16000)
            if text:
                lines.append(f"[{int(start) // 60:02}:{int(start) % 60:02}] {text}")
        return "\n".join(lines)
