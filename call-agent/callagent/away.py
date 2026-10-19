"""자리 비움 자동 모드: 사람이 없어도 다음 고객 걸기 → 받으면 첫인사 → 끝나면 바로 엑셀 기록.
메뉴에서 켰을 때만 동작한다 (python main.py next --away). 기본은 지금처럼 수동.

설정 (config.yaml 또는 profile.yaml, 안 적으면 아래 기본값):
  away:
    answer_timeout_sec: 30     # 이 시간 안에 상대가 안 받으면 '부재' 기록 후 다음
    gap_sec: 5                 # 다음 고객 걸기 전 쉬는 시간 (이때 q + Enter 로 멈춤)
    takeover_wait_sec: 10      # 넘겨받을 상황에서 내가 t + Enter 로 받을 수 있는 시간
    handoff_close: ["[클립:41]", "[클립:28]"]   # 아무도 안 받으면 마무리 멘트 (있는 녹음 중 첫 번째)
"""
import sys
import threading
import time

from .audio import Listener
from .session import NOISE_TEXT

DEFAULTS = {"answer_timeout_sec": 30, "gap_sec": 5, "takeover_wait_sec": 10,
            "handoff_close": ["[클립:41]", "[클립:28]"]}
ANSWER_MAX_SEC = 4.0  # 받는 사람의 첫마디("여보세요", "네 ○○입니다")는 짧다. 컬러링·음악은 길게 이어짐
AFTER_HELLO_QUIET = 1.2  # 첫마디 뒤 이만큼 조용해야 사람 (매장 컬러링 "안녕하세요 ○○입니다…" 는 계속 이어짐)
# 통신사 안내 음성 → 받은 게 아님
CARRIER = ["음성사서함", "사서함", "받을수없", "연결되지않", "연결이되지않", "삐소리", "전원이꺼져", "없는번호", "결번",
           "통화중이", "잠시후다시", "고객님의전화", "녹음후", "통화가어렵"]


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("away") or {})}


def alarm() -> None:
    """PC 스피커로 알림음 3번 (통화 쪽 소리와 따로, 기본 스피커로 나옴)."""
    def work():
        if sys.platform == "win32":
            import winsound
            for _ in range(3):
                winsound.Beep(1300, 250)
                time.sleep(0.12)
        else:
            print("\a", end="", flush=True)
    threading.Thread(target=work, daemon=True).start()


def handoff_alert(cfg: dict, customer: dict | None):
    """넘겨받을 상황 알림 함수 (알림음 + 카톡). session.run(away={"alert": ...}) 에 넘긴다."""
    def alert(heard: str) -> None:
        alarm()
        room = (cfg.get("notify") or {}).get("kakao_room")
        if not room:
            print("   (카톡 대화방이 설정되지 않아 카톡 알림은 건너뜀 — 메뉴 k 로 설정)")
            return
        from .notify import send_kakao
        c = customer or {}
        text = (f"[전화상담 넘겨받기] {c.get('_clinic', '')} {c.get('_phone', '')}\n"
                f"상대 말: {heard}\n"
                f"{settings(cfg)['takeover_wait_sec']}초 안에 PC 에서 t + Enter 로 받으세요. 안 받으면 '확인 후 다시 연락' 으로 마무리합니다.")
        if not send_kakao(room, text):
            print(f"   (카톡 대화방 '{room}' 창을 못 찾아 카톡 알림을 못 보냄)")
    return alert


def wait_for_answer(cfg: dict, ears, dialer, timeout: float | None = None) -> tuple[str, str]:
    """전화를 건 뒤 상대가 받을 때까지 듣는다.
    ('answered', 상대 첫마디) / ('carrier', 안내 음성) / ('ended', '') 상대가 거절·끊음 / ('no_answer', '')"""
    timeout = settings(cfg)["answer_timeout_sec"] if timeout is None else timeout
    listener = Listener(cfg)
    start = time.time()
    pending = None  # 짧은 첫마디를 들었음 → 뒤에 조용하면(사람이 대답을 기다림) 받은 것
    with listener:
        listener.flush()
        while time.time() - start < timeout:
            if time.time() - start > 3 and dialer.is_idle():
                return "ended", ""
            left = timeout - (time.time() - start)
            utt = listener.next_utterance(timeout=AFTER_HELLO_QUIET if pending else min(1.0, max(0.2, left)))
            if utt is None:
                if pending:
                    return "answered", pending
                continue
            text = (ears.transcribe_pcm(utt, listener.rate) or "").strip()
            if any(k in text.replace(" ", "") for k in CARRIER):
                return "carrier", text
            if len(utt) / listener.rate <= ANSWER_MAX_SEC and text and not NOISE_TEXT.fullmatch(text):
                pending = text
            else:
                # 길게 이어지는 소리(컬러링·음악)나 알아들을 수 없는 소리 → 아직 안 받음
                pending = None
    return ("answered", pending) if pending else ("no_answer", "")
