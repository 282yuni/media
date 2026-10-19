"""ElevenLabs: 음성 인식(STT), 내 목소리 복제, 내 목소리로 말하기(TTS)."""
import io
import os
import wave
from pathlib import Path
from typing import Iterator

import numpy as np

TTS_RATE = 24000
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".amr", ".3gp", ".webm", ".mp4"}


def client():
    from elevenlabs.client import ElevenLabs  # 유료(ai) 모드에서만 필요
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError(".env 에 ELEVENLABS_API_KEY 를 넣어주세요.")
    return ElevenLabs(api_key=key)


def audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT)


def _wav_bytes(pcm: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return buf.getvalue()


class Ears:
    def __init__(self, cfg: dict):
        self.el = client()
        self.model = cfg["voice"].get("stt_model", "scribe_v1")
        self.keyterms = cfg["voice"].get("keyterms") or []

    def transcribe_pcm(self, pcm: np.ndarray, rate: int) -> str:
        kw = {"keyterms": self.keyterms} if self.keyterms else {}
        res = self.el.speech_to_text.convert(
            model_id=self.model, file=("utt.wav", _wav_bytes(pcm, rate), "audio/wav"),
            language_code="kor", tag_audio_events=False, **kw,
        )
        return (res.text or "").strip()

    def transcribe_call_file(self, path: Path) -> str:
        """녹음 파일 하나를 화자 구분해서 '화자A: ...' 형태 대본으로."""
        with open(path, "rb") as f:
            res = self.el.speech_to_text.convert(
                model_id=self.model, file=(path.name, f.read()), language_code="kor",
                diarize=True, num_speakers=2, tag_audio_events=False,
            )
        lines: list[str] = []
        cur, words = None, []
        for w in res.words or []:
            if w.type != "word" and w.type != "spacing":
                continue
            spk = getattr(w, "speaker_id", None) or "?"
            if spk != cur and w.type == "word":
                if words:
                    lines.append(f"{cur}: {''.join(words).strip()}")
                cur, words = spk, []
            words.append(w.text)
        if words:
            lines.append(f"{cur}: {''.join(words).strip()}")
        return "\n".join(lines) if lines else (res.text or "")


class Voice:
    def __init__(self, cfg: dict):
        self.el = client()
        self.voice_id = cfg["voice"].get("voice_id")
        if not self.voice_id:
            raise RuntimeError("voice_id 가 없습니다. 먼저 `python main.py clone-voice` 를 실행하세요.")
        self.model = cfg["voice"].get("tts_model", "eleven_flash_v2_5")

    def speak(self, text: str, previous_text: str = "") -> Iterator[bytes]:
        kw = {"previous_text": previous_text} if previous_text else {}
        if "flash" in self.model or "turbo" in self.model:
            kw["language_code"] = "ko"
        yield from self.el.text_to_speech.stream(
            self.voice_id, text=text, model_id=self.model, output_format=f"pcm_{TTS_RATE}", **kw,
        )


def clone_voice(folder: Path, name: str, files: list[Path] | None = None) -> str:
    files = files or audio_files(folder)
    if not files:
        raise RuntimeError(f"{folder} 에 음성 파일이 없습니다.")
    print(f"샘플 {len(files)}개로 목소리를 복제합니다: " + ", ".join(p.name for p in files))
    handles = [(p.name, p.read_bytes()) for p in files[:25]]
    res = client().voices.ivc.create(
        name=name, files=handles, remove_background_noise=True,
        description="본인 목소리 (치과 상담 콜 대행용, 본인 동의)",
    )
    return res.voice_id
