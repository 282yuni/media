"""adb(폰 자동 걸기 도구) 찾기·자동 설치. 구글 공식 platform-tools 를 이 폴더 안에 받아 둔다."""
import io
import shutil
import sys
import urllib.request
import zipfile

from .config import ROOT

URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
LOCAL = ROOT / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")


def find_adb(configured: str = "adb") -> str:
    """설정값 → PATH → 이 폴더 안 platform-tools 순서로 찾는다. 못 찾으면 설정값 그대로."""
    if configured and shutil.which(configured):
        return configured
    if LOCAL.exists():
        return str(LOCAL)
    return configured or "adb"


def fetch_adb() -> str:
    if LOCAL.exists():
        return str(LOCAL)
    if sys.platform != "win32":
        raise RuntimeError("자동 설치는 Windows 에서만 됩니다.")
    print("adb(폰 자동 걸기 도구)를 구글에서 받는 중… (약 7MB)")
    data = urllib.request.urlopen(URL, timeout=120).read()
    zipfile.ZipFile(io.BytesIO(data)).extractall(ROOT)
    print(f"설치 완료: {LOCAL}")
    return str(LOCAL)
