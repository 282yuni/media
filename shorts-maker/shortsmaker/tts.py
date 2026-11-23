"""음성 합성. 기본은 ElevenLabs, 키가 없으면 무료 edge-tts로 대체."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import requests

# ElevenLabs 기본 제공 보이스 (multilingual 모델로 한국어/일본어 모두 가능).
# 마음에 드는 목소리가 있으면 환경변수로 바꾸면 된다.
ELEVEN_VOICES = {
    "ko_youtube": os.getenv("VOICE_KO_YT", "21m00Tcm4TlvDq8ikWAM"),     # Rachel
    "ko_instagram": os.getenv("VOICE_KO_IG", "EXAVITQu4vr4xnSDxMaL"),   # Sarah
    "ja_youtube": os.getenv("VOICE_JA_YT", "pNInz6obpgDQGcFmaJgB"),     # Adam
    "ja_instagram": os.getenv("VOICE_JA_IG", "XrExE9yKIg1WjnnlVkGX"),   # Matilda
}
EDGE_VOICES = {
    "ko_youtube": "ko-KR-SunHiNeural",
    "ko_instagram": "ko-KR-InJoonNeural",
    "ja_youtube": "ja-JP-NanamiNeural",
    "ja_instagram": "ja-JP-KeitaNeural",
}


def engine() -> str:
    return "elevenlabs" if os.getenv("ELEVENLABS_API_KEY") else "edge"


def speak(text: str, variant_key: str, out: Path) -> Path:
    if engine() == "elevenlabs":
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICES[variant_key]}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json={
                "text": text,
                "model_id": os.getenv("ELEVEN_MODEL", "eleven_multilingual_v2"),
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3},
            },
            timeout=120,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs 오류 {r.status_code}: {r.text[:300]}")
        out.write_bytes(r.content)
    else:
        import edge_tts

        async def _run():
            await edge_tts.Communicate(text, EDGE_VOICES[variant_key], rate="+12%").save(str(out))

        asyncio.run(_run())
    return out
