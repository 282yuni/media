"""전화 걸기/끊기. adb 모드는 USB·무선 디버깅으로 연결된 안드로이드폰을 직접 조작한다."""
import re
import shutil
import subprocess
import sys


def normalize(phone: str) -> str:
    n = re.sub(r"\.0$", "", str(phone or "").strip())
    n = re.sub(r"[^0-9+]", "", n)
    # 엑셀이 숫자로 저장하면서 맨 앞 0을 지운 경우 (1012345678 → 01012345678). 1588-xxxx 같은 8자리는 제외
    if n and n[0] not in "0+" and len(n) >= 9:
        n = "0" + n
    return n


def copy_to_clipboard(text: str) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.run("clip", input=text.encode("utf-16le"), check=True, shell=True)
        elif sys.platform == "darwin":
            subprocess.run("pbcopy", input=text.encode(), check=True)
        elif shutil.which("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        else:
            return False
        return True
    except Exception:
        return False


class Dialer:
    def __init__(self, cfg: dict):
        d = cfg.get("dialer", {})
        self.mode = d.get("mode", "manual")
        from .adbtool import find_adb
        self.adb = find_adb(d.get("adb_path", "adb"))
        # 폰 2대를 한 PC에 꽂으면 어느 폰인지 지정해야 함 (`adb devices` 에 나오는 일련번호)
        self.serial = d.get("adb_serial", "")

    def _adb(self, *args: str) -> None:
        target = ["-s", self.serial] if self.serial else []
        subprocess.run([self.adb, *target, "shell", *args], check=True, capture_output=True, timeout=10)

    def call_state(self) -> str | None:
        """폰의 통화 상태: 'idle'(통화 없음) / 'offhook'(거는 중·통화 중) / None(알 수 없음, adb 아님)."""
        if self.mode != "adb":
            return None
        target = ["-s", self.serial] if self.serial else []
        try:
            out = subprocess.run([self.adb, *target, "shell", "dumpsys", "telephony.registry"],
                                 capture_output=True, timeout=5, text=True, encoding="utf-8", errors="ignore").stdout
        except Exception:
            return None
        states = re.findall(r"mCallState=(\d)", out)  # 유심 2개 폰은 여러 줄
        if not states:
            return None
        if all(x == "0" for x in states):
            return "idle"
        self._seen_offhook = True
        return "offhook"

    def is_idle(self) -> bool:
        """상대가 끊었는지. 이번 통화에서 '통화 중'을 한 번이라도 봤을 때만 믿는다
        (상태를 잘못 알려 주는 폰에서 멀쩡한 통화를 끊지 않게)."""
        return self.call_state() == "idle" and self._seen_offhook

    _seen_offhook = False

    def dial(self, phone: str) -> None:
        self._seen_offhook = False
        number = normalize(phone)
        if self.mode == "adb":
            self._adb("am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{number}")
            print(f"📞 {phone} 로 전화를 걸었습니다.")
        else:
            copied = copy_to_clipboard(number)
            print(f"📞 {phone} 로 전화를 걸어주세요." + ("  (번호가 클립보드에 복사됨)" if copied else ""))

    def hang_up(self) -> None:
        if self.mode == "adb":
            try:
                self._adb("input", "keyevent", "KEYCODE_ENDCALL")
            except Exception as e:
                print(f"(자동 끊기 실패: {e}) 직접 끊어주세요.")
        else:
            print("☎ 전화를 끊어주세요.")
