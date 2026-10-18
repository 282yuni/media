"""사운드 장치·API 키 없이 돌아가는 테스트.  실행: python -m pytest call-agent/tests -q"""
import os
import queue
import sys
import tempfile
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# PortAudio 가 없는 환경(CI, 클라우드)에서도 import 되게 가짜 모듈로 대체
sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))

import numpy as np  # noqa: E402

from callagent import session as S  # noqa: E402
from callagent.audio import Listener  # noqa: E402
from callagent.brain import _clean, _split_sentences  # noqa: E402
from callagent.config import load_config  # noqa: E402
from callagent.customers import CustomerBook  # noqa: E402
from callagent.dialer import normalize  # noqa: E402


def test_sentence_split():
    done, rest = _split_sentences("네, 알겠습니다. 다시 연락드릴게요! 혹시 몇 시쯤")
    assert done == ["네, 알겠습니다.", "다시 연락드릴게요!"]
    assert rest == "혹시 몇 시쯤"
    assert _clean("좋은 하루 되세요. [통화종료]") == "좋은 하루 되세요."


def test_phone_normalize():
    assert normalize("010-1234-5678") == "01012345678"
    assert normalize(1012345678.0) == "01012345678"  # 엑셀이 앞 0을 지운 경우
    assert normalize("15881234") == "15881234"


def _listener():
    L = Listener.__new__(Listener)
    L.rate, L.threshold, L.end_silence, L.max_sec = 16000, 0.015, 0.8, 25
    L.blocks, L.is_speaking = queue.Queue(), threading.Event()
    L.base_threshold, L.levels = L.threshold, []
    return L


def test_vad_ignores_short_noise():
    L = _listener()
    quiet = np.zeros(480, np.int16)
    loud = (np.sin(np.arange(480) / 3) * 3000).astype(np.int16)
    for b in [quiet] * 20 + [loud] * 3 + [quiet] * 40 + [loud] * 50 + [quiet] * 30:
        L.blocks.put(b)
    u = L.next_utterance(timeout=5)
    assert 2.3 < len(u) / 16000 < 2.8  # 0.09초 잡음은 버리고 1.5초 발화만
    assert L.next_utterance(timeout=0.5) is None


def test_customer_excel_roundtrip():
    import openpyxl
    cfg = load_config()
    path = os.path.join(tempfile.mkdtemp(), "c.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["치과명", "담당자", "전화번호", "상태"])
    ws.append(["밝은미소치과", "김실장", "010-1234-5678", ""])
    ws.append(["튼튼치과", "이원장", "02-555-1234", "거절"])
    ws.append(["하얀치과", "박실장", "031-777-8888", ""])
    wb.save(path)
    cfg["customers"].update(source="excel", path=path)
    book = CustomerBook(cfg)
    assert book.next_pending()["_clinic"] == "밝은미소치과"
    book.record_result(2, "재통화", "원장님 부재")
    assert book.next_pending(2)["_clinic"] == "하얀치과"  # 거절 행은 건너뜀
    again = CustomerBook(cfg).get(2)
    assert again["_status"] == "재통화" and "원장님 부재" in again["_memo"]


def test_call_loop_with_fakes(monkeypatch):
    heard = ["여보세요", "원장님 진료 중이세요", "이거 AI예요?", "자료 보내주세요"]
    answers = iter(["아 그러시군요. 실장님께 말씀드려도 될까요?",
                    "네, 저는 AI 음성 비서예요. 원하시면 담당자 연결해 드릴게요.",
                    "문자로 보내드릴게요. 좋은 하루 되세요. [통화종료]"])

    class FakeListener:
        rate = 16000

        def __init__(self, cfg):
            self.is_speaking = threading.Event()
            self.left = list(range(len(heard)))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def flush(self):
            pass

        def next_utterance(self, timeout=None, stop=None):
            if not self.left:
                return None
            i = self.left.pop(0)
            return np.full(16000 * 2, i, np.int16)  # 2초짜리 발화 (첫 값으로 어떤 말인지 구분)

    class FakeEars:
        def __init__(self, cfg):
            pass

        def transcribe_pcm(self, pcm, rate):
            return heard[int(pcm[0])]

    class FakeMouth:
        muted = False

        def __init__(self, cfg, rate):
            pass

        def write(self, pcm):
            pass

        def stop(self):
            pass

        def wait_done(self, interrupt=None):
            return True

        def close(self):
            pass

    class FakeVoice:
        def __init__(self, cfg):
            pass

        def speak(self, text, previous_text=""):
            yield b"\0\0"

    class FakeBrain:
        def __init__(self, cfg, playbook, customer, clips=None):
            self.messages, self.ended, self.handoff = [], False, False

        def warm(self):
            pass

        def reply(self, text):
            self.messages.append({"role": "user", "content": text})
            ans = next(answers)
            self.ended = "[통화종료]" in ans
            yield from _split_sentences(_clean(ans) + " ")[0]
            self.messages.append({"role": "assistant", "content": _clean(ans)})

    for name, fake in [("Listener", FakeListener), ("Ears", FakeEars), ("Mouth", FakeMouth),
                       ("Voice", FakeVoice), ("Brain", FakeBrain)]:
        monkeypatch.setattr(S, name, fake)
    monkeypatch.setattr(S.Controls, "_loop", lambda self: None)  # 키보드 입력 안 받음
    monkeypatch.setattr(S.Console, "_start", classmethod(lambda cls: None))

    cfg = load_config()
    cfg["voice"]["mode"] = "clone"
    cfg["agent"]["fillers"] = ["네,"]  # 맞장구 경로도 같이 확인
    call = S.CallSession(cfg, "playbook", {"_clinic": "밝은미소치과", "_name": "김실장"})
    call.run(ready_prompt=False)
    who = [w for w, _ in call.transcript]
    assert who == ["상대", "AI", "상대", "AI", "상대", "AI", "상대", "AI"]
    assert "AI 음성 비서" in call.transcript[1][1]  # 오프닝 + AI 고지
    assert call.brain.ended


def test_clip_mode_plays_my_recording_unchanged(tmp_path):
    import wave
    import yaml
    from callagent.clips import ClipBank, split_tokens
    pcm = (np.sin(np.arange(24000) / 5) * 4000).astype(np.int16).tobytes()  # 1초짜리 내 녹음 대신
    with wave.open(str(tmp_path / "clip_001.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    (tmp_path / "clips.yaml").write_text(yaml.safe_dump(
        [{"id": 1, "file": "clip_001.wav", "text": "네 원장님 안녕하세요", "use": True},
         {"id": 2, "file": "x.wav", "text": "상대방 목소리", "use": False}], allow_unicode=True), encoding="utf-8")
    cfg = load_config()
    cfg["voice"].update(mode="clips", clips_dir=str(tmp_path))
    bank = ClipBank(cfg)
    assert list(bank.items) == [1]  # use: false 는 제외
    assert "[클립:1] 네 원장님 안녕하세요" in bank.catalog()
    assert b"".join(bank.chunks(1)) == pcm  # 바이트 하나 안 바뀌고 그대로 재생
    assert split_tokens("[클립:1] 네 [클립:2]") == ["[클립:1]", "네", "[클립:2]"]

    call = S.CallSession.__new__(S.CallSession)
    call.clips, call.voice = bank, None
    audio, label = call.audio_for("[클립:1]", "")
    assert b"".join(audio) == pcm and label == "네 원장님 안녕하세요"
    assert call.audio_for("녹음에 없는 말", "") == (None, "")  # clips 모드: 합성하지 않음
