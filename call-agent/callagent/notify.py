"""성사된 통화의 녹취록을 담당자 카톡으로 보내기 (Windows PC 카카오톡).

열어 둔 카톡 대화방 창(창 제목 = 대화방 이름)의 입력칸에 글을 넣고 Enter 를 보낸다.
설정 (config.yaml 또는 profile.yaml):
  notify:
    kakao_room: "김팀장"                 # 열어 둘 대화방 이름 (창 제목과 똑같이)
    on_status: ["제안서발송", "방문예약"]   # 이 결과일 때만 보냄 (비우면 보내지 않음)
"""
import sys
import time
from datetime import datetime

MAX_LEN = 4000  # 카톡 한 번에 너무 길면 잘림 → 뒤쪽 녹취는 줄임


def build_message(cfg: dict, customer: dict | None, summary: dict, transcript: str) -> str:
    c = customer or {}
    profile = cfg.get("_profile") or cfg.get("agent", {}).get("company", "")
    lines = [f"[{profile} 성사] {datetime.now():%Y-%m-%d %H:%M}"]
    who = " / ".join(x for x in (c.get("_clinic"), c.get(cfg.get("rules", {}).get("branch_column", "업종"), ""), c.get("_phone")) if x)
    if who:
        lines.append(f"고객: {who}")
    lines.append(f"결과: {summary.get('status', '')}")
    for k, v in (summary.get("answers") or {}).items():
        lines.append(f"- {k}: {v}")
    if summary.get("callback_time"):
        lines.append(f"다시 연락: {summary['callback_time']}")
    lines += ["", "── 녹취록 ──", transcript.strip()]
    text = "\n".join(lines)
    return text if len(text) <= MAX_LEN else text[:MAX_LEN - 20] + "\n…(이하 생략)"


def should_send(cfg: dict, summary: dict) -> bool:
    n = cfg.get("notify") or {}
    return bool(n.get("kakao_room")) and summary.get("status") in (n.get("on_status") or [])


def send_kakao(room: str, text: str) -> bool:
    """열려 있는 카톡 대화방 창에 text 를 보낸다. 창을 못 찾으면 False."""
    if sys.platform != "win32":
        print("   (카톡 보내기는 Windows 에서만 됩니다)")
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowExW.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, room)
    if not hwnd:
        return False
    edit = user32.FindWindowExW(hwnd, None, "RichEdit50W", None)
    if not edit:
        return False
    WM_SETTEXT, WM_KEYDOWN, WM_KEYUP, VK_RETURN = 0x000C, 0x0100, 0x0101, 0x0D
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.c_wchar_p(text))
    time.sleep(0.2)
    user32.PostMessageW(edit, WM_KEYDOWN, VK_RETURN, 0)
    time.sleep(0.05)
    user32.PostMessageW(edit, WM_KEYUP, VK_RETURN, 0)
    return True


def notify_success(cfg: dict, customer: dict | None, summary: dict, transcript: str) -> None:
    if not should_send(cfg, summary):
        return
    room = cfg["notify"]["kakao_room"]
    text = build_message(cfg, customer, summary, transcript)
    if send_kakao(room, text):
        print(f"   💬 담당자 카톡({room})으로 녹취록을 보냈습니다.")
    else:
        from .dialer import copy_to_clipboard
        copied = copy_to_clipboard(text)
        print(f"   ⚠ 카톡 대화방 '{room}' 창을 못 찾았습니다. 대화방을 따로 열어 두세요 (창 제목이 이 이름과 같아야 함)."
              + ("\n     녹취록은 클립보드에 복사해 두었으니 직접 붙여넣기(Ctrl+V) 하셔도 됩니다." if copied else ""))
