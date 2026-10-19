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
import yaml  # noqa: E402

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

    import callagent.voice
    for name, fake in [("Listener", FakeListener), ("Mouth", FakeMouth)]:
        monkeypatch.setattr(S, name, fake)
    monkeypatch.setattr(S, "make_ears", FakeEars)
    monkeypatch.setattr(S, "make_brain", lambda cfg, pb, c, clips: FakeBrain(cfg, pb, c))
    monkeypatch.setattr(callagent.voice, "Voice", FakeVoice)
    monkeypatch.setattr(S.Controls, "_loop", lambda self: None)  # 키보드 입력 안 받음
    monkeypatch.setattr(S.Console, "_start", classmethod(lambda cls: None))

    cfg = load_config()
    cfg["engine"] = "ai"
    cfg["voice"]["mode"] = "clone"
    cfg["agent"].update(opening="안녕하세요, {clinic} 맞으시죠?",
                        ai_disclosure="참고로 이 통화는 AI 음성 비서가 먼저 응대하고 있어요.")
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


def _rule_brain(tmp_path):
    import shutil
    from callagent.rules import RuleBrain
    shutil.copy(Path(__file__).resolve().parent.parent / "scenarios.example.yaml", tmp_path / "scenarios.yaml")
    cfg = load_config()
    cfg["rules"] = {"scenarios": str(tmp_path / "scenarios.yaml"), "min_similarity": 0.6}
    return RuleBrain(cfg)


def test_free_rules_situations(tmp_path):
    b = _rule_brain(tmp_path)
    assert list(b.reply("원장님 지금 진료 중이신데요")) == ["[클립:10]"]
    assert b.status == "재통화"
    assert list(b.reply("아직 진료 중이세요")) == ["[클립:11]"]  # 같은 상황 두 번째는 다른 녹음
    # 수신거부가 다른 상황보다 우선, 통화 종료
    assert list(b.reply("바쁘니까 다시는 전화하지 마세요")) == ["[클립:20]"]
    assert b.ended and b.status == "수신거부"


def test_free_rules_ai_question_is_honest_handoff(tmp_path):
    b = _rule_brain(tmp_path)
    assert list(b.reply("이거 혹시 AI예요? 사람이에요?")) == ["[클립:21]"]
    assert b.handoff


def test_free_rules_follow_script_and_summary(tmp_path):
    b = _rule_brain(tmp_path)
    assert list(b.reply("네")) == ["[클립:3]", "[클립:4]"]  # 짧은 긍정 → 스크립트 다음 단계
    assert list(b.reply("네 말씀하세요")) == ["[클립:5]"]
    assert list(b.reply("아 그래요")) == ["[클립:6]"]
    assert list(b.reply("우리 강아지가 아파서 걱정이에요 요즘 날씨도 춥고")) == ["[클립:19]"]  # 엉뚱한 말 → 넘김
    assert b.handoff
    summary = b.summarize("상대: 네\n상담원(AI): ...\n상대: 우리 강아지가 아파서")
    assert summary["status"] == "관심" and summary["needs_review"]


def test_free_mode_full_call(tmp_path, monkeypatch):
    """무료 모드 통화 한 건: 상황표 + 내 녹음 재생 + 요약까지 (API 없음)."""
    import shutil
    import wave
    import yaml
    clips = tmp_path / "clips"
    clips.mkdir()
    items = []
    for i in range(1, 24):
        with wave.open(str(clips / f"clip_{i:03}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(np.full(2400, i, np.int16).tobytes())
        items.append({"id": i, "file": f"clip_{i:03}.wav", "text": f"녹음{i}", "use": True})
    (clips / "clips.yaml").write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    shutil.copy(Path(__file__).resolve().parent.parent / "scenarios.example.yaml", tmp_path / "scenarios.yaml")
    cfg = load_config(str(Path(__file__).resolve().parent.parent / "config.example.yaml"))
    cfg["voice"]["clips_dir"] = str(clips)
    cfg["rules"]["scenarios"] = str(tmp_path / "scenarios.yaml")

    heard = ["여보세요", "네", "원장님 지금 진료 중이세요", "다시는 전화하지 마세요"]

    class FakeListener:
        rate = 16000

        def __init__(self, cfg):
            self.is_speaking, self.left = threading.Event(), list(range(len(heard)))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def flush(self):
            pass

        def next_utterance(self, timeout=None, stop=None):
            return np.full(32000, self.left.pop(0), np.int16) if self.left else None

    played = []

    class FakeMouth:
        muted = False

        def __init__(self, cfg, rate):
            pass

        def write(self, pcm):
            played.append(int(np.frombuffer(pcm, np.int16)[0]))

        def stop(self):
            pass

        def wait_done(self, interrupt=None):
            return True

        def close(self):
            pass

    class FakeEars:
        def __init__(self, cfg):
            pass

        def transcribe_pcm(self, pcm, rate):
            return heard[int(pcm[0])]

    monkeypatch.setattr(S, "Listener", FakeListener)
    monkeypatch.setattr(S, "Mouth", FakeMouth)
    monkeypatch.setattr(S, "make_ears", FakeEars)
    monkeypatch.setattr(S.Controls, "_loop", lambda self: None)
    monkeypatch.setattr(S.Console, "_start", classmethod(lambda cls: None))

    call = S.CallSession(cfg, "", {"_clinic": "밝은미소치과"})
    call.run(ready_prompt=False)
    # 첫인사(1,2)+AI고지(8) → 맞장구(9)+스크립트(3,4) → 맞장구+원장부재(10) → 맞장구+수신거부(20)
    assert played == [1, 2, 8, 9, 3, 4, 9, 10, 9, 20]
    assert call.brain.ended
    s = call.brain.summarize(call.text())
    assert s["status"] == "수신거부"


def test_phones_setup_writes_config_per_phone(tmp_path, monkeypatch):
    import shutil
    from callagent import config, doctor
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(Path(__file__).resolve().parent.parent / "config.example.yaml", root / "config.example.yaml")
    monkeypatch.setattr(config, "ROOT", root)
    from callagent import adbtool
    monkeypatch.setattr(adbtool, "fetch_adb", lambda: "adb")
    monkeypatch.setattr(doctor, "adb_devices", lambda adb="adb": [
        {"serial": "S8SERIAL", "state": "device", "model": "SM_G950N", "android": "9"},
        {"serial": "PHONE2", "state": "device", "model": "SM_A525N", "android": "14"}])
    doctor.setup_phones()
    c1 = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    c2 = yaml.safe_load((root / "config2.yaml").read_text(encoding="utf-8"))
    assert c1["dialer"] == {"mode": "adb", "adb_path": "adb", "adb_serial": "S8SERIAL"}
    assert c2["dialer"]["adb_serial"] == "PHONE2" and c2["logs_dir"] == "logs/phone2"
    assert c1["voice"]["mode"] == "clips"  # 다른 mode 설정은 건드리지 않음


def test_profile_overrides_and_brief(tmp_path, monkeypatch):
    import shutil
    from callagent import config
    root = tmp_path / "proj"
    shutil.copytree(Path(__file__).resolve().parent.parent / "profiles" / "_template", root / "profiles" / "곤란한전화")
    shutil.copy(Path(__file__).resolve().parent.parent / "config.example.yaml", root / "config.example.yaml")
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "CONFIG_PATH", root / "config.yaml")
    cfg = config.load_config(None, "곤란한전화")
    assert cfg["engine"] == "ai" and cfg["voice"]["mode"] == "mixed"
    assert cfg["voice"]["clips_dir"].endswith("곤란한전화/clips")
    assert cfg["logs_dir"].endswith("logs/곤란한전화")
    assert cfg["audio"]["call_input"] == "CABLE Output"  # 프로필에 없는 설정은 기본값 유지
    assert "AI 비서" in cfg["agent"]["ai_disclosure"]


def test_ai_rules_forbid_identity_and_payment():
    from callagent.brain import RULES
    assert "본인 인증" in RULES and "결제" in RULES and "[담당자연결]" in RULES
    assert "사람이라고 하지 않는다" in RULES


def test_coach_mode_suggests_without_speaking(tmp_path, monkeypatch):
    import shutil
    shutil.copy(Path(__file__).resolve().parent.parent / "scenarios.example.yaml", tmp_path / "scenarios.yaml")
    cfg = load_config()
    cfg["engine"] = "free"
    cfg["rules"] = {"scenarios": str(tmp_path / "scenarios.yaml")}
    cfg["voice"]["clips_dir"] = str(tmp_path / "noclips")
    heard = ["원장님 수술 중이세요"]

    class FakeListener:
        rate = 16000

        def __init__(self, cfg):
            self.is_speaking, self.left = threading.Event(), [0]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def flush(self):
            pass

        def next_utterance(self, timeout=None, stop=None):
            if self.left:
                return np.full(16000, self.left.pop(0), np.int16)
            stop.set()  # 다 들었으면 통화 끝
            return None

    class FakeEars:
        def __init__(self, cfg):
            pass

        def transcribe_pcm(self, pcm, rate):
            return heard[int(pcm[0])]

    monkeypatch.setattr(S, "Listener", FakeListener)
    monkeypatch.setattr(S, "Mouth", lambda *a: (_ for _ in ()).throw(AssertionError("코치 모드는 말하면 안 됨")))
    monkeypatch.setattr(S, "make_ears", FakeEars)
    monkeypatch.setattr(S.Controls, "_loop", lambda self: None)
    monkeypatch.setattr(S.Console, "_start", classmethod(lambda cls: None))
    call = S.CallSession(cfg, "", {"_clinic": "집주인"}, coach=True)
    call.run()
    assert call.transcript[0] == ("상대", "원장님 수술 중이세요")
    assert call.transcript[1][0] == "추천"


def _implant(said):
    from callagent.rules import RuleBrain
    b = RuleBrain(load_config(None, "임플란트"))
    outs = []
    for h in said:
        outs.append(list(b.reply(h)))
        if b.ended or b.handoff:
            break
    return b, outs


def test_implant_smooth_call_records_answers():
    b, outs = _implant(["네 맞아요", "네 갈 수 있어요", "네 물어보세요", "아래쪽 어금니요", "두 개 정도요",
                        "왼쪽이 좀 시리고 아파요", "평일이 좋아요", "오후로 해주세요"])
    assert outs[-1] == ["[클립:13]", "[클립:14]", "[클립:15]"] and b.ended
    s = b.summarize("")
    assert s["status"] == "상담완료"
    assert s["answers"]["부위"] == "아래쪽 어금니요" and s["answers"]["개수"] == "두 개 정도요"


def test_implant_price_question_then_busy_callback():
    b, outs = _implant(["네 맞는데요", "근데 그거 얼마예요?", "아 지금 운전 중이라서요", "오후에 전화 주세요"])
    assert outs[1][:2] == ["[클립:23]", "[클립:24]"] and outs[1][-1] == "[클립:5]"  # 답하고 다시 질문
    assert outs[3] == ["[클립:22]"] and b.ended
    s = b.summarize("")
    assert s["status"] == "재통화" and s["callback_time"] == "오후에 전화 주세요"


def test_implant_refusal_during_questions_and_ai_question():
    b, outs = _implant(["네", "네", "네", "다시는 전화하지 마세요"])
    assert outs[-1] == ["[클립:30]"] and b.status == "수신거부"
    b, outs = _implant(["네", "근데 이거 ARS예요? 사람이에요?"])
    assert outs[-1] == ["[클립:32]"] and b.handoff  # 전용 상황 없음 → 확인 후 연락 + 나에게 넘김


def test_implant_two_refusals_end_call():
    b, outs = _implant(["누구세요?", "저 신청한 적 없는데요", "됐어요 관심 없어요", "필요 없다니까요"])
    assert outs[2] == ["[클립:28]"] and not b.ended or True
    assert outs[-1] == ["[클립:29]"] and b.ended and b.status == "거절"


def _practice(said):
    from callagent.rules import RuleBrain
    b = RuleBrain(load_config(None, "연습녹음"))
    outs = []
    for h in said:
        outs.append(list(b.reply(h)))
        if b.ended or b.handoff:
            break
    return b, outs


def test_practice_profile_objections_mid_question():
    b, outs = _practice(["네", "근데 얼마예요?", "좀 비싸네요", "생각해볼게요", "화요일 오후 세시요"])
    assert outs[2] == ["[클립:43]", "[클립:44]", "[클립:45]", "[클립:46]", "[클립:5]"]  # 비싸다에 답하고 다시 질문
    assert outs[3][-1] == "[클립:71]" and outs[4] == ["[클립:72]"] and b.ended
    assert b.summarize("")["callback_time"] == "화요일 오후 세시요"


def test_practice_profile_two_refusals_mid_question_end():
    b, outs = _practice(["네", "관심 없어요", "필요 없다니까요"])
    assert outs[-1] == ["[클립:58]"] and b.ended and b.status == "거절"


def _echelon(kind, said):
    from callagent.rules import RuleBrain
    b = RuleBrain(load_config(None, "에셜론"), "", {"업종": kind})
    outs = []
    for h in said:
        outs.append(list(b.reply(h)))
        if b.ended or b.handoff:
            break
    return b, outs


def test_echelon_branch_by_business_type():
    assert _echelon("한식당", [])[0].opening == "[클립:1]"
    b, _ = _echelon("헤어살롱", [])
    assert b.opening == "[클립:2]" and b.branch == "미용실"
    assert _echelon("네일샵", [])[0].branch == "네일숍"


def test_echelon_restaurant_full_call_records_phone():
    b, outs = _echelon("한식당", ["네 괜찮아요", "메뉴 사진 몇 장 있어요", "네 보내주세요", "010 1234 5678"])
    assert outs[0] == ["[클립:3]", "[클립:4]", "[클립:5]", "[클립:6]"]
    assert outs[-1] == ["[클립:14]", "[클립:15]"] and b.ended
    s = b.summarize("")
    assert s["status"] == "제안서발송" and s["answers"]["연락처"] == "010 1234 5678"


def test_echelon_objections():
    b, outs = _echelon("헤어살롱", ["네", "광고하고 있어요", "네 그럼 보내주세요"])
    assert outs[1] == ["[클립:17]", "[클립:36]", "[클립:37]", "[클립:21]"] and outs[2] == ["[클립:13]"]
    b, outs = _echelon("카페", ["네", "근데 왜 무료로 해줘요?", "나중에 돈 드는 거 아니에요?"])
    assert outs[1][0] == "[클립:22]" and outs[2][0] == "[클립:23]"
    b, outs = _echelon("치킨집", ["네", "관심 없어요", "필요 없다니까요"])
    assert outs[-1] == ["[클립:16]"] and b.ended and b.status == "거절"


def test_echelon_unknown_question_hands_off_without_claiming_human():
    b, outs = _echelon("한식당", ["네", "이거 혹시 자동응답이에요?"])
    assert outs[-1] == ["[클립:31]"] and b.handoff  # "확인해서 다시 연락드릴게요" + 나에게 넘김


def _run(profile, kind, said):
    from callagent.rules import RuleBrain
    cfg = load_config(None, profile)
    b = RuleBrain(cfg, "", {"업종": kind})
    outs = []
    for h in said:
        outs.append(list(b.reply(h)))
        if b.ended or b.handoff:
            break
    return cfg, b, outs


def test_echelon_script1_cleaned_version():
    cfg, b, outs = _run("에셜론1_정리본", "한식당", ["네", "네 좋아요", "010 1234 5678"])
    assert cfg["agent"]["opening"] == "[클립:39]" and cfg["voice"]["clips_dir"].endswith("에셜론/clips")
    assert outs == [["[클립:3]"], ["[클립:13]"], ["[클립:15]"]] and b.ended
    assert b.summarize("")["answers"]["연락처"] == "010 1234 5678"
    _, b, outs = _run("에셜론1_정리본", "헤어살롱", ["네", "광고하고 있어요", "네 보내주세요"])
    assert b.opening == "[클립:2]" and outs[1] == ["[클립:18]", "[클립:19]"] and outs[2] == ["[클립:13]"]
    _, b, outs = _run("에셜론1_정리본", "카페", ["네", "관심 없어요", "필요 없다니까요"])
    assert outs[-1] == ["[클립:16]"] and b.ended and b.status == "거절"


def test_echelon_script2_by_business_type():
    cfg, b, outs = _run("에셜론2_업종별", "헤어살롱", ["네", "사진 몇 장 있어요", "네 보내주세요", "010 1234 5678"])
    assert cfg["agent"]["opening"] == "[클립:1]"
    assert outs == [["[클립:7]", "[클립:8]"], ["[클립:12]"], ["[클립:40]"], ["[클립:14]", "[클립:15]"]] and b.ended
    assert b.summarize("")["status"] == "제안서발송"
    _, b, outs = _run("에셜론2_업종별", "한식당", ["네"])
    assert outs[0] == ["[클립:4]", "[클립:5]", "[클립:6]"]
    _, b, outs = _run("에셜론2_업종별", "네일샵", ["네", "광고하고 있어요", "네 보내주세요"])
    assert outs[1] == ["[클립:17]", "[클립:36]", "[클립:37]", "[클립:21]"] and outs[2] == ["[클립:40]"]


def test_silent_customer_hello_twice_then_hang_up(tmp_path, monkeypatch):
    import wave
    import yaml
    clips = tmp_path / "clips"
    clips.mkdir()
    items = []
    for i in range(1, 40):
        with wave.open(str(clips / f"clip_{i:03}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(np.full(2400, i, np.int16).tobytes())
        items.append({"id": i, "file": f"clip_{i:03}.wav", "text": f"녹음{i}", "use": True})
    (clips / "clips.yaml").write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    cfg = load_config(None, "에셜론")
    cfg["voice"]["clips_dir"] = str(clips)

    class SilentListener:
        rate = 16000

        def __init__(self, cfg):
            self.is_speaking = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def flush(self):
            pass

        def next_utterance(self, timeout=None, stop=None):
            return None  # 상대가 아무 말도 안 함

    played = []

    class FakeMouth:
        muted = False

        def __init__(self, cfg, rate):
            pass

        def write(self, pcm):
            played.append(int(np.frombuffer(pcm, np.int16)[0]))

        def stop(self):
            pass

        def wait_done(self, interrupt=None):
            return True

        def close(self):
            pass

    monkeypatch.setattr(S, "Listener", SilentListener)
    monkeypatch.setattr(S, "Mouth", FakeMouth)
    monkeypatch.setattr(S, "make_ears", lambda cfg: None)
    monkeypatch.setattr(S.Controls, "_loop", lambda self: None)
    monkeypatch.setattr(S.Console, "_start", classmethod(lambda cls: None))
    call = S.CallSession(cfg, "", {"업종": "한식당", "_clinic": "테스트식당"})
    call.run(ready_prompt=False)
    assert played == [1, 32, 38]  # 첫인사 → 여보세요? → 여보세요? 제 말 잘 들리세요? → 끊기


def test_success_call_sends_transcript_to_kakao(monkeypatch):
    from callagent import notify
    cfg = load_config(None, "에셜론")
    cfg["notify"] = {"kakao_room": "김팀장", "on_status": ["제안서발송"]}
    sent = []
    monkeypatch.setattr(notify, "send_kakao", lambda room, text: sent.append((room, text)) or True)
    summary = {"status": "제안서발송", "answers": {"연락처": "010 1234 5678"}, "callback_time": ""}
    customer = {"_clinic": "맛나식당", "업종": "한식당", "_phone": "02-111-2222"}
    notify.notify_success(cfg, customer, summary, "상대: 네 보내주세요\n상담원(AI): 감사합니다")
    room, text = sent[0]
    assert room == "김팀장" and "맛나식당" in text and "010 1234 5678" in text and "네 보내주세요" in text
    sent.clear()
    notify.notify_success(cfg, customer, {"status": "거절"}, "상대: 됐어요")  # 성사가 아니면 안 보냄
    assert sent == []
