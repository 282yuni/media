"""통화 한 건 진행: 듣기 → 받아 적기 → 생각하기 → 내 목소리로 말하기 반복."""
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from .audio import Listener, Mouth
from .brain import Brain
from .config import resolve
from .voice import TTS_RATE, Ears, Voice

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
    def __init__(self, cfg: dict, playbook: str, customer: dict | None):
        self.cfg = cfg
        self.customer = customer
        self.brain = Brain(cfg, playbook, customer)
        self.ears = Ears(cfg)
        self.voice = Voice(cfg)
        self.transcript: list[tuple[str, str]] = []
        self.barge_in = cfg["audio"].get("barge_in", True)
        self.no_answer = cfg["audio"].get("no_answer_timeout_sec", 12)

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
            for pcm in self.voice.speak(s, previous_text=prev):
                mouth.write(pcm)
                if self.barge_in and listener.is_speaking.is_set():
                    cut = True
                    break
            spoken.append(s)
            prev = s
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

    def run(self, ready_prompt: bool = True) -> None:
        a = self.cfg["agent"]
        listener = Listener(self.cfg)
        mouth = Mouth(self.cfg, TTS_RATE)
        try:
            with listener:
                if ready_prompt:
                    Console.ask("\n상대방이 전화를 받으면 Enter ▶ ")
                listener.flush()
                ctl = Controls()
                print(HELP)

                # 상대가 먼저 "여보세요" 할 시간을 잠깐 준다
                first = listener.next_utterance(timeout=2.5, stop=ctl.end)
                hello = "(전화가 연결됨)"
                if first is not None:
                    hello = self.ears.transcribe_pcm(first, listener.rate) or "여보세요"
                    self.log("상대", hello)
                opening = fill(a["opening"], self.cfg, self.customer)
                disclosure = (a.get("ai_disclosure") or "").strip()
                intro = [opening] + ([disclosure] if disclosure else [])
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
                        if silent_rounds >= 2:
                            print("상대가 응답이 없어 통화를 마칩니다.")
                            break
                        self.say(["여보세요? 제 말 잘 들리세요?"], listener, mouth, ctl)
                        continue
                    silent_rounds = 0
                    t0 = time.time()
                    heard = self.ears.transcribe_pcm(utt, listener.rate)
                    if not heard:
                        continue
                    self.log("상대", heard)
                    said = self.say(self.brain.reply(heard), listener, mouth, ctl)
                    if self.brain.messages[-1]["role"] == "user":  # 말하다 끊긴 경우 기록 맞추기
                        self.brain.messages.append({"role": "assistant", "content": said or "(침묵)"})
                    print(f"   (응답 지연 {time.time() - t0:.1f}초)")
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
        return "\n".join(f"{'상담원(AI)' if w == 'AI' else '상대'}: {t}" for w, t in self.transcript)

    def save_log(self, summary: dict | None) -> Path:
        logs = resolve(self.cfg.get("logs_dir", "logs"))
        logs.mkdir(parents=True, exist_ok=True)
        who = (self.customer or {}).get("_clinic") or "test"
        path = logs / f"{datetime.now():%Y%m%d_%H%M%S}_{who}.txt"
        body = self.text()
        if summary:
            body += "\n\n--- 요약 ---\n" + "\n".join(f"{k}: {v}" for k, v in summary.items())
        path.write_text(body, encoding="utf-8")
        return path
