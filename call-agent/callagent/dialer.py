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
        self.adb = d.get("adb_path", "adb")

    def _adb(self, *args: str) -> None:
        subprocess.run([self.adb, "shell", *args], check=True, capture_output=True, timeout=10)

    def dial(self, phone: str) -> None:
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
