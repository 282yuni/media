"""바탕화면에 '전화상담' 바로가기 만들기 (Windows)."""
import subprocess
import sys

from .config import ROOT


def make_shortcut() -> None:
    if sys.platform != "win32":
        print("바탕화면 바로가기는 Windows 에서만 만들 수 있습니다.")
        return
    target = ROOT / "전화상담.bat"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell);"
        "$d=[Environment]::GetFolderPath('Desktop');"
        f"$l=$s.CreateShortcut((Join-Path $d '전화상담.lnk'));"
        f"$l.TargetPath='{target}';$l.WorkingDirectory='{ROOT}';"
        "$l.IconLocation='shell32.dll,197';$l.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print("바탕화면에 '전화상담' 바로가기를 만들었습니다. 앞으로 그걸 더블클릭하세요.")
