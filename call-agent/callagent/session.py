"""통화 한 건 진행: 듣기 → 받아 적기 → 생각하기 → 내 목소리로 말하기 반복."""
import queue
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from .audio import Listener, Mouth, Recorder
from .engine import make_brain, make_ears, voice_mode
from .clips import TOKEN, ClipBank, split_tokens
from .config import resolve
from .voice import TTS_RATE

NOISE_TEXT = re.compile(r"[\s\W음어으흠아]*")
HELP = "  [Enter]만 누르면 아무 일 없음 | t + Enter: 내가 직접 받기(AI 멈춤) | e + Enter: 통화 종료"


def fill(template: str, cfg: dict, customer: dict | None) -> str:
    a = cfg["agent"]
    c = customer or {}
    return template.format(
        my_name=a["my_name"], company=a["company"], product=a["product"],
        name=c.get("_name") or "원장님", clinic=c.get("_clinic") or "치과",
    )


class Console:
    """키보드 입력을 한 스레드에서만 읽는다. (통화 중 명령과 평소 질문이 서로 입력을 뺏지 않게)"""

    lines: "queue.Queue[str]" = queue.Queue()
    _started = False

    @classmethod
    def ask(cls, prompt: str = "") -> str:
        cls._start()
        print(prompt, end="", flush=True)
        return cls.lines.get()

    @classmethod
    def poll(cls, timeout: float) -> str | None:
        """timeout 초 동안 입력을 기다린다. 아무것도 안 치면 None (자동 모드에서 멈춤 키 받기용)."""
        cls._start()
        try:
            return cls.lines.get(timeout=timeout)
        except queue.Empty:
            return None

    @classmethod
    def _start(cls):
        if not cls._started:
            cls._started = True
            threading.Thread(target=cls._read, daemon=True).start()

    @classmethod
    def _read(cls):
        while True:
            try:
                cls.lines.put(input())
            except EOFError:
                cls.lines.put("e")
                return


class Controls:
    """통화 중 키보드 명령 (t: 직접 받기, e: 종료)."""

    def __init__(self):
        self.takeover = threading.Event()
        self.end = threading.Event()
        Console._start()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.end.is_set():
            try:
                cmd = Console.lines.get(timeout=0.3).strip().lower()
            except queue.Empty:
                continue
            if cmd == "t":
                self.takeover.set()
                print("🙋 직접 받기로 전환 — AI 음성을 멈췄습니다. 대화가 끝나면 e + Enter.")
            elif cmd == "e":
                self.end.set()


class CallSession:
    def __init__(self, cfg: dict, playbook: str, customer: dict | None, coach: bool = False):
        self.cfg = cfg
        self.coach = coach  # 코치 모드: AI는 말하지 않고, 내가 할 말을 화면에 보여줌
        self.customer = customer
        self.mode = voice_mode(cfg)
        self.clips = ClipBank(cfg) if self.mode in ("clips", "mixed") else None
        if self.mode == "clips" and not self.clips and not coach:
            raise RuntimeError("녹음 문장이 없습니다. 먼저 `python main.py clips 내녹음.mp3` 를 실행하세요.")
        if self.mode != "clips" and not coach:
            from .voice import Voice
            self.voice = Voice(cfg)
        else:
            self.voice = None
        self.brain = make_brain(cfg, playbook, customer, self.clips)
        self.ears = make_ears(cfg)
        self.transcript: list[tuple[str, str]] = []
        self.barge_in = cfg["audio"].get("barge_in", True)
        self.no_answer = cfg["audio"].get("no_answer_timeout_sec", 12)
        self.filler_min = cfg["audio"].get("filler_after_sec", 1.2)
        self.handoff_closed = False  # 자리 비움 모드: 넘겨받을 사람이 없어 '확인 후 연락'으로 마무리함
        self.took_over = False
        self._intro: list | None = None
        self._fillers: list = []
        self._ready = threading.Event()

    def _render(self, items: list[str]) -> list[tuple[list[bytes], str]]:
        """문장/녹음번호들을 미리 소리로 만들어 메모리에 둔다 (통화 중 지연 0초)."""
        out, prev = [], ""
        for item in items:
            audio, label = self.audio_for(item, prev)
            if audio is not None:
                out.append((list(audio), label))
                prev = label
        return out

    def prepare(self) -> None:
        """전화 거는 동안(신호음 울릴 때) 미리 준비: 첫인사 소리, 맞장구 소리, AI 캐시 예열."""
        def work():
            try:
                a = self.cfg["agent"]
                intro = split_tokens(fill(getattr(self.brain, "opening", None) or a["opening"], self.cfg, self.customer))
                intro += split_tokens((a.get("ai_disclosure") or "").strip())
                self._intro = self._render(intro)
                self._fillers = [r for f in a.get("fillers", []) for r in self._render(split_tokens(f))]
            except Exception as e:
                print(f"   (미리 준비 실패, 통화 중에 만듭니다: {e})")
            finally:
                self._ready.set()
        threading.Thread(target=work, daemon=True).start()
        threading.Thread(target=self.brain.warm, daemon=True).start()

    def log(self, who: str, text: str) -> None:
        self.transcript.append((who, text))
        print(f"{'🤖 AI' if who == 'AI' else '👤 상대'}: {text}")

    def say(self, sentences, listener: Listener, mouth: Mouth, ctl: Controls) -> str:
        """문장들을 차례로 말하고 실제로 말한 내용을 돌려준다. 상대가 끼어들면 그 자리에서 멈춘다."""
        listener.is_speaking.clear()
        prev, spoken, cut = "", [], False
        for s in sentences:
            if ctl.takeover.is_set() or ctl.end.is_set():
                cut = True
                break
            audio, label = s if isinstance(s, tuple) else self.audio_for(s, prev)
            if audio is None:
                continue
            for pcm in audio:
                mouth.write(pcm)
                if self.barge_in and listener.is_speaking.is_set():
                    cut = True
                    break
            spoken.append(label)
            prev = label
            if cut:
                break
        if hasattr(sentences, "close"):
            sentences.close()  # 끊겼으면 Claude 스트림도 닫기
        if not cut:
            interrupt = listener.is_speaking if self.barge_in else ctl.takeover
            cut = not mouth.wait_done(interrupt)
        if cut:
            mouth.stop()
        else:
            listener.flush()  # AI 말하는 동안 들어온 잡음 버리기
        text = " ".join(spoken) + (" …(상대가 말을 끊음)" if cut and spoken else "")
        if text:
            self.log("AI", text)
        return text

    def audio_for(self, item: str, prev: str):
        """[클립:번호] → 내 녹음 그대로, 일반 문장 → 복제 목소리. (소리 조각들, 기록용 글) 반환."""
        m = TOKEN.fullmatch(item)
        if m:
            cid = int(m.group(1))
            if self.clips and cid in self.clips.items:
                return self.clips.chunks(cid), self.clips.text(cid)
            print(f"   (없는 녹음 번호라 건너뜀: {item})")
            return None, ""
        if self.voice:
            return self.voice.speak(item, previous_text=prev), item
        print(f"   (녹음에 없는 말이라 재생 안 함: {item})")
        return None, ""

    def run_coach(self) -> None:
        """곤란한 통화를 내가 직접 할 때: 상대 말을 받아 적고, 할 말을 화면에 띄워 준다."""
        listener = Listener(self.cfg)
        with listener:
            listener.flush()
            ctl = Controls()
            print("🎧 코치 모드 — 상대 말을 듣고 할 말을 추천합니다. 내가 직접 말하세요. (끝: e + Enter)")
            while not ctl.end.is_set():
                utt = listener.next_utterance(timeout=1.0, stop=ctl.end)
                if utt is None:
                    continue
                heard = self.ears.transcribe_pcm(utt, listener.rate)
                if not heard or NOISE_TEXT.fullmatch(heard):
                    continue
                self.log("상대", heard)
                tips = []
                for item in self.brain.reply(heard):
                    m = TOKEN.fullmatch(item)
                    tips.append(self.clips.text(int(m.group(1))) if m and self.clips else item)
                tip = " ".join(t for t in tips if t)
                if tip:
                    print(f"\n   💡 이렇게 말해 보세요:  {tip}\n")
                    self.transcript.append(("추천", tip))
                if self.brain.handoff:
                    print("   ⚠ 이 부분은 직접 판단하세요 (인증·결제·약속 등)")
            ctl.end.set()

    def _first_available(self, items: list[str]) -> list[str]:
        """['[클립:41]', '[클립:28]'] 중 녹음이 있는 첫 번째 것."""
        for item in items:
            toks = split_tokens(item)
            if toks and all(not TOKEN.fullmatch(t) or (self.clips and int(TOKEN.fullmatch(t).group(1)) in self.clips.items)
                            for t in toks):
                return toks
        return []

    def _away_handoff(self, heard: str, listener: Listener, mouth: Mouth, ctl: Controls, away: dict) -> None:
        """자리 비움 모드에서 넘겨받을 상황: 알림음 + 카톡 → 정해진 시간 안에 t 를 누르면 직접 받기,
        아무도 안 받으면 정중히 '확인 후 다시 연락드리겠습니다' 로 마무리."""
        mouth.wait_done()
        wait = away.get("takeover_wait_sec", 10)
        print(f"\a\n🔔🔔 넘겨받을 상황입니다 ('{heard}') — {wait}초 안에 t + Enter 로 직접 받으세요 🔔🔔")
        alert = away.get("alert")
        if alert:
            try:
                alert(heard)
            except Exception as e:
                print(f"   (알림 보내기 실패: {e})")
        t_end = time.time() + wait
        while time.time() < t_end and not (ctl.takeover.is_set() or ctl.end.is_set()):
            time.sleep(0.2)
        if ctl.end.is_set() and not ctl.takeover.is_set():  # 기다리는 동안 상대가 끊음
            self.handoff_closed = True
            return
        if ctl.takeover.is_set():
            self.took_over = True
            mouth.muted = True
            mouth.stop()
            ctl.end.wait()
            return
        print("   아무도 받지 않아 '확인 후 다시 연락드리겠습니다' 로 마무리합니다.")
        close = self._first_available(away.get("handoff_close") or ["[클립:41]", "[클립:28]"])
        if close:
            listener.flush()
            self.say(close, listener, mouth, ctl)
            mouth.wait_done()
        self.handoff_closed = True

    def run(self, ready_prompt: bool = True, hello: str | None = None, away: dict | None = None,
            hung_up=None) -> None:
        """hello: 자리 비움 모드에서 이미 들은 상대 첫마디 / away: 자리 비움 모드 설정 (None 이면 지금처럼 수동)
        hung_up: 상대가 끊었는지 확인하는 함수 (폰 상태로 판단, 2초마다)"""
        if self.coach:
            return self.run_coach()
        a = self.cfg["agent"]
        if not self._ready.is_set() and self._intro is None:
            self.prepare()
        listener = Listener(self.cfg)
        mouth = Mouth(self.cfg, TTS_RATE)
        if self.cfg["audio"].get("save_recording", True):  # 양쪽 소리 녹취 (logs/ 에 글 녹취록과 같은 이름의 mp3)
            self.recorder = Recorder()
            listener.recorder = self.recorder
            if getattr(mouth, "outs", None):
                mouth.outs[0].tap = lambda chunk: self.recorder.add("out", chunk, TTS_RATE)
        try:
            with listener:
                if ready_prompt:
                    Console.ask("\n상대방이 전화를 받으면 Enter ▶ ")
                listener.flush()
                ctl = Controls()
                print(HELP)
                if hung_up:
                    def watch():
                        while not ctl.end.wait(2.0):
                            try:
                                if hung_up():
                                    print("📴 상대가 전화를 끊었습니다.")
                                    ctl.end.set()
                            except Exception:
                                pass
                    threading.Thread(target=watch, daemon=True).start()

                if hello is not None:  # 자리 비움 모드: 받았는지 확인하면서 이미 들은 첫마디
                    if hello != "(전화가 연결됨)":
                        self.log("상대", hello)
                else:
                    # 상대가 먼저 "여보세요" 할 시간을 잠깐 준다
                    first = listener.next_utterance(timeout=2.5, stop=ctl.end)
                    hello = "(전화가 연결됨)"
                    if first is not None:
                        hello = self.ears.transcribe_pcm(first, listener.rate) or "여보세요"
                        self.log("상대", hello)
                opening = fill(getattr(self.brain, "opening", None) or a["opening"], self.cfg, self.customer)
                self._ready.wait(timeout=10)
                intro = self._intro or split_tokens(opening) + split_tokens((a.get("ai_disclosure") or "").strip())
                if not intro:
                    print("⚠ 첫인사로 재생할 녹음이 없습니다! config.yaml 의 agent.opening 녹음 번호를 확인하세요.")
                said = self.say(intro, listener, mouth, ctl)
                self.brain.messages += [{"role": "user", "content": hello},
                                        {"role": "assistant", "content": said or opening}]

                silent_rounds = 0
                while not (ctl.end.is_set() or ctl.takeover.is_set()):
                    utt = listener.next_utterance(timeout=self.no_answer, stop=ctl.end)
                    if ctl.end.is_set() or ctl.takeover.is_set():
                        break
                    if utt is None:
                        silent_rounds += 1
                        # 대답이 없으면 "여보세요?" 를 hello_again_times 번(기본 2번)까지 → 그래도 없으면 끊기
                        if silent_rounds > a.get("hello_again_times", 2):
                            print("상대가 응답이 없어 통화를 마칩니다.")
                            break
                        hello = a.get("hello_again", "여보세요? 제 말 잘 들리세요?")
                        if isinstance(hello, list):  # ["[클립:32]", "[클립:38]"] → 첫 번째, 두 번째 다르게
                            hello = hello[min(silent_rounds, len(hello)) - 1] if hello else ""
                        self.say(split_tokens(hello), listener, mouth, ctl)
                        continue
                    silent_rounds = 0
                    t0 = time.time()
                    # 말이 길었으면 생각하는 동안 바로 "네~" 맞장구 (진짜 상담사처럼, 침묵 없애기)
                    filler = None
                    if self._fillers and len(utt) / listener.rate >= self.filler_min:
                        filler = random.choice(self._fillers)
                        for pcm in filler[0]:
                            mouth.write(pcm)
                    heard = self.ears.transcribe_pcm(utt, listener.rate)
                    if not heard or NOISE_TEXT.fullmatch(heard):
                        continue  # 잡음·한숨·"음" 같은 건 대답하지 않음
                    self.log("상대", heard)
                    said = self.say(self.brain.reply(heard), listener, mouth, ctl)
                    if self.brain.messages[-1]["role"] == "user":  # 말하다 끊긴 경우 기록 맞추기
                        self.brain.messages.append({"role": "assistant", "content": said or "(침묵)"})
                    print(f"   (응답 지연 {time.time() - t0:.1f}초)")
                    if self.brain.handoff and away is not None:
                        self._away_handoff(heard, listener, mouth, ctl, away)
                        break
                    if self.brain.handoff:
                        mouth.muted = True
                        ctl.takeover.set()
                        print("\a\n🔔🔔 상대가 담당자 연결을 원합니다 — 지금 직접 받으세요! (끝나면 e + Enter) 🔔🔔")
                    if self.brain.ended:
                        mouth.wait_done()
                        break
                if ctl.takeover.is_set() and not ctl.end.is_set():
                    mouth.muted = True
                    mouth.stop()
                    ctl.end.wait()
                ctl.end.set()
        finally:
            mouth.close()

    def text(self) -> str:
        names = {"AI": "상담원(AI)", "추천": "추천 대답"}
        return "\n".join(f"{names.get(w, '상대')}: {t}" for w, t in self.transcript)

    def save_log(self, summary: dict | None) -> Path:
        logs = resolve(self.cfg.get("logs_dir", "logs"))
        logs.mkdir(parents=True, exist_ok=True)
        who = re.sub(r"[^\w가-힣-]", "_", (self.customer or {}).get("_clinic") or "test")
        path = logs / f"{datetime.now():%Y%m%d_%H%M%S}_{who}.txt"
        body = self.text()
        if summary:
            body += "\n\n--- 요약 ---\n" + "\n".join(f"{k}: {v}" for k, v in summary.items())
        path.write_text(body, encoding="utf-8")
        rec = getattr(self, "recorder", None)
        if rec is not None:
            try:
                out = path.with_suffix("." + self.cfg["audio"].get("recording_format", "mp3"))
                if rec.save(out):
                    print(f"   🎙 통화 녹취 저장: {out.name}")
            except Exception as e:
                print(f"   (녹취 저장 실패: {e})")
        return path
