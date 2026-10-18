"""Windows 완성본(설치 없이 압축만 풀면 되는 ZIP) 만들기.

필요한 것 (인터넷에서 받아 둔 파일):
  --python  cpython-3.12.*-x86_64-pc-windows-msvc-install_only.tar.gz  (github.com/astral-sh/python-build-standalone)
  --wheels  pip download -d wheels --platform win_amd64 --python-version 3.12 --only-binary=:all: -r requirements.txt
  models/ko 한국어 음성 인식 모델 (github.com/k2-fsa/sherpa-onnx releases: sherpa-onnx-zipformer-korean-2024-06-24, int8 파일만)

실행: python tools/build_portable.py --python py.tar.gz --wheels wheels --out 전화상담_완성본.zip
"""
import argparse
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SKIP = {"tests", "tools"}

# .bat 안에는 영어만 (cmd 가 한글을 잘못 읽는 문제). 한글 안내는 Python 이 출력.
START_BAT = """@echo off
cd /d "%~dp0app"
title CallAgent
if not exist config.yaml (
  "%~dp0python\\python.exe" -m callagent.installer
  echo.
)
"%~dp0python\\python.exe" main.py menu
if errorlevel 1 pause
"""

README = """전화상담 완성본 — 먼저 읽어주세요
=====================================

1. 이 폴더를 통째로 원하는 곳(예: 문서)에 둡니다. (바탕화면에 둬도 됩니다)
2. 「시작하기.bat」 을 더블클릭합니다.
   - 처음 한 번은 설정을 준비하고 바탕화면에 「전화상담」 바로가기를 만듭니다.
   - 따로 설치할 것은 없습니다 (Python, 음성 인식 모델이 다 들어 있음).
3. 다음부터는 바탕화면의 「전화상담」 을 더블클릭하세요.

처음 할 일 (메뉴 번호)
  1 점검하기   → ❌ 표시가 있으면 그대로 따라 고치기
  2 폰 연결 설정 (USB 디버깅 켠 폰 2대)
  8 녹음 대본 보기 → 순서대로 녹음
  3 내 녹음 넣기 → 녹음 파일을 끌어다 놓기
  4 연습하기
  5/6 고객에게 전화 시작 (1번 폰 / 2번 폰)

고객 엑셀: app\\data\\customers.xlsx (열 이름: 이름, 전화번호)
통화 녹취·요약: app\\logs\\
자세한 설명: app\\README.md

"Windows의 PC 보호" 파란 창이 뜨면: 「추가 정보」 → 「실행」
음성 인식 오류가 나면: https://aka.ms/vs/17/release/vc_redist.x64.exe 설치 후 다시 실행
"""


def app_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=APP, capture_output=True, text=True, check=True).stdout
    files = [APP / f for f in out.split("\0") if f and f.split("/")[0] not in SKIP]
    return [f for f in files if f.is_file()]


def install_wheel(whl: Path, py: Path) -> None:
    site = py / "Lib" / "site-packages"
    with zipfile.ZipFile(whl) as z:
        for name in z.namelist():
            parts = name.split("/")
            if ".data" in parts[0] and len(parts) > 2:  # pkg.data/<scheme>/...
                scheme, rest = parts[1], parts[2:]
                dst = (site if scheme in ("purelib", "platlib") else py) / Path(*rest)
            else:
                dst = site / name
            if name.endswith("/"):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(name))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True)
    ap.add_argument("--wheels", required=True)
    ap.add_argument("--out", default="전화상담_완성본.zip")
    a = ap.parse_args()
    if not (APP / "models" / "ko" / "tokens.txt").exists():
        raise SystemExit("models/ko 한국어 모델이 없습니다.")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "전화상담"
        root.mkdir()
        with tarfile.open(a.python) as t:
            t.extractall(root, filter="data")  # → 전화상담/python/
        py = root / "python"
        for whl in sorted(Path(a.wheels).glob("*.whl")):
            install_wheel(whl, py)
        # onnxruntime 가 쓰는 C++ 런타임 (없는 PC 대비)
        for dll in (py / "Lib" / "site-packages" / "numpy.libs").glob("msvcp140-*.dll"):
            for dst in (py / "msvcp140.dll", py / "Lib" / "site-packages" / "sherpa_onnx" / "lib" / "msvcp140.dll"):
                shutil.copy(dll, dst)
        for pdb in py.rglob("*.pdb"):  # 디버그 파일 빼서 용량 줄이기
            pdb.unlink()
        for f in app_files():
            dst = root / "app" / f.relative_to(APP)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
        (root / "app" / "data").mkdir(exist_ok=True)
        (root / "시작하기.bat").write_bytes(START_BAT.replace("\n", "\r\n").encode("ascii"))
        (root / "먼저 읽어주세요.txt").write_bytes(b"\xef\xbb\xbf" + README.replace("\n", "\r\n").encode("utf-8"))
        out = Path(a.out).resolve()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(root.parent))
    print(f"완성본: {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
