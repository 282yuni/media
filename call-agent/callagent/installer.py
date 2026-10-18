"""설치하기.bat 이 부르는 설치 프로그램. 표준 라이브러리만 써서 아무것도 없는 PC에서도 돈다.
실행: python -m callagent.installer"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def step(msg: str) -> None:
    print(f"\n▶ {msg}", flush=True)


def desktop_dirs() -> list[Path]:
    """바탕화면 위치 (OneDrive 로 옮겨진 경우까지)."""
    found = []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            found.append(Path(out))
    except Exception:
        pass
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    for cand in [home / "Desktop", home / "바탕 화면", *home.glob("OneDrive*/Desktop"), *home.glob("OneDrive*/바탕 화면")]:
        if cand.exists() and cand not in found:
            found.append(cand)
    return found


def make_shortcut() -> list[Path]:
    """바탕화면에 '전화상담' 바로가기. 만들기에 실패하면 실행 파일 자체를 복사해 둔다."""
    target = ROOT / "전화상담.bat"
    made = []
    for desk in desktop_dirs():
        lnk = desk / "전화상담.lnk"
        ps = ("$s=New-Object -ComObject WScript.Shell;"
              f"$l=$s.CreateShortcut('{lnk}');$l.TargetPath='{target}';"
              f"$l.WorkingDirectory='{ROOT}';$l.IconLocation='shell32.dll,197';$l.Save()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
        except Exception as e:
            print(f"   (바로가기 만들기 오류: {e})")
        if lnk.exists():
            made.append(lnk)
            break
    if not made:  # 바로가기가 막힌 PC: 폴더로 이동해서 실행하는 작은 파일을 대신 둔다
        for desk in desktop_dirs()[:1]:
            bat = desk / "전화상담.bat"
            bat.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\ncall "{target}"\r\n', encoding="utf-8")
            made.append(bat)
    return made


def main() -> None:
    print("=" * 50 + "\n  전화상담 프로그램 설치 (처음 한 번만)\n" + "=" * 50)
    step(f"Python {sys.version.split()[0]} 확인")
    if sys.version_info < (3, 10):
        print("   Python 3.10 이상이 필요합니다. https://www.python.org/downloads/ 에서 새로 설치하세요.")
        return

    portable = (ROOT.parent / "python" / "python.exe").exists() or (ROOT / "python" / "python.exe").exists()
    if portable:
        step("필요한 프로그램이 준비되어 있습니다")
    else:
        step("필요한 프로그램 설치 (몇 분 걸려요)")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
        if r.returncode != 0:
            print("   ❌ 설치 중 오류가 났습니다. 위의 빨간 글씨 마지막 몇 줄을 캡처해서 보내주세요.")
    try:
        import sherpa_onnx  # noqa: F401
        print("   ✅ 음성 인식 준비됨")
    except Exception as e:
        print(f"   ❌ 음성 인식을 불러오지 못했습니다: {e}\n"
              "      Microsoft Visual C++ 재배포 패키지를 설치한 뒤 다시 실행하세요:\n"
              "      https://aka.ms/vs/17/release/vc_redist.x64.exe")

    step("설정 파일 준비")
    for src, dst in [("config.example.yaml", "config.yaml"), ("scenarios.example.yaml", "scenarios.yaml")]:
        if not (ROOT / dst).exists():
            shutil.copy(ROOT / src, ROOT / dst)
            print(f"   {dst} 만듦")
    (ROOT / "data").mkdir(exist_ok=True)
    xlsx = ROOT / "data" / "customers.xlsx"
    if not xlsx.exists():
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "고객"
            ws.append(["이름", "전화번호", "상태", "메모", "통화일시"])
            ws.append(["(예시) 홍길동", "010-0000-0000", "", "", ""])
            for col, width in zip("ABCDE", (14, 16, 10, 60, 18)):
                ws.column_dimensions[col].width = width
            wb.save(xlsx)
            print(f"   고객 엑셀 견본 만듦: {xlsx}  (이름·전화번호를 채워 넣으세요)")
        except Exception as e:
            print(f"   (고객 엑셀 견본을 못 만들었습니다: {e})")

    step("바탕화면 바로가기 만들기")
    made = make_shortcut()
    if made:
        for m in made:
            print(f"   ✅ {m}")
    else:
        print("   ❌ 바탕화면을 못 찾았습니다. call-agent 폴더의 '전화상담.bat' 에서 오른쪽 클릭 →"
              " 보내기 → 바탕 화면에 바로 가기 만들기")

    print("\n설치 끝! 바탕화면의 '전화상담' 을 더블클릭하세요.")


if __name__ == "__main__":
    main()
