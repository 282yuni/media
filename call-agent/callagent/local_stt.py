"""무료 음성 인식: 내 PC에서 직접 돌리는 Whisper (faster-whisper). 인터넷·유료 API 필요 없음.
처음 한 번만 모델 파일(small 기준 약 460MB)을 자동으로 내려받는다."""
import numpy as np

_MODEL = None


def _model(cfg: dict):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        s = cfg.get("stt", {})
        name = s.get("local_model", "small")
        print(f"   (음성 인식 모델 '{name}' 불러오는 중… 처음엔 내려받느라 몇 분 걸릴 수 있어요)")
        _MODEL = WhisperModel(name, device=s.get("device", "cpu"), compute_type=s.get("compute_type", "int8"))
    return _MODEL


class LocalEars:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        terms = cfg.get("voice", {}).get("keyterms") or []
        # 자주 나오는 단어를 미리 알려주면 고유명사 인식이 좋아짐
        self.prompt = "치과 상담 전화. " + ", ".join(terms) if terms else "치과 상담 전화."
        _model(cfg)

    def transcribe_pcm(self, pcm: np.ndarray, rate: int) -> str:
        audio = pcm.astype(np.float32) / 32768.0
        if rate != 16000:  # Whisper 는 16kHz 입력
            n = int(len(audio) * 16000 / rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
        segments, _ = _model(self.cfg).transcribe(
            audio, language="ko", beam_size=1, initial_prompt=self.prompt, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe_call_file(self, path) -> str:
        """녹음 파일 → 시간 표시가 붙은 대본 (화자 구분은 못 함)."""
        segments, _ = _model(self.cfg).transcribe(str(path), language="ko", beam_size=5, initial_prompt=self.prompt)
        return "\n".join(f"[{int(s.start) // 60:02}:{int(s.start) % 60:02}] {s.text.strip()}" for s in segments)
