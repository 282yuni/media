"""전화상담.bat 이 여는 번호 메뉴."""
import subprocess
import sys
from pathlib import Path

from .config import ROOT


def profiles() -> list[str]:
    d = ROOT / "profiles"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_")) if d.exists() else []


def find_clip_zips() -> list[Path]:
    """다운로드·바탕화면에서 다듬어 받은 녹음 ZIP(clips.yaml 이 든 것) 찾기. 최신 것부터."""
    import zipfile
    home = Path.home()
    dirs = [home / "Downloads", home / "다운로드", home / "Desktop", home / "바탕 화면",
            *home.glob("OneDrive*/Desktop"), *home.glob("OneDrive*/바탕 화면")]
    found = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.zip"):
            try:
                with zipfile.ZipFile(f) as z:
                    if any(Path(n).name == "clips.yaml" for n in z.namelist()):
                        found.append(f)
            except (zipfile.BadZipFile, OSError):
                pass
    return sorted(set(found), key=lambda f: f.stat().st_mtime, reverse=True)


def ask_clip_file() -> str:
    f = input("녹음 파일(또는 다듬어 받은 ZIP)을 이 창으로 끌어다 놓고 Enter\n"
              "  (끌어다 놓기가 안 되면 그냥 Enter → 다운로드 폴더에서 찾아요): ").strip().strip('"')
    if f:
        return f
    zips = find_clip_zips()
    if not zips:
        print("다운로드 폴더·바탕화면에 녹음 ZIP 이 없습니다. 카톡/채팅에서 ZIP 을 먼저 '다운로드' 해 주세요.")
        return ""
    for i, z in enumerate(zips[:5], 1):
        print(f"  {i}. {z.name}   ({z.parent})")
    k = input("넣을 번호 (그냥 Enter = 1번, 가장 최근 것): ").strip() or "1"
    return str(zips[int(k) - 1]) if k.isdigit() and 0 < int(k) <= min(5, len(zips)) else ""


def offer_new_zip(names: list[str]) -> None:
    """켤 때: 다운로드 폴더에 지금 녹음보다 새 녹음 ZIP 이 있으면 Enter 한 번으로 넣기."""
    zips = find_clip_zips()
    if not zips:
        return
    z = zips[0]
    # ZIP 이름이 프로필 이름으로 시작하면 그 프로필에 (예: 에셜론_완성녹음.zip → 에셜론). 긴 이름 먼저
    target = next((n for n in sorted(names, key=len, reverse=True) if z.name.startswith(n)), "")
    if not target:
        return
    cur = ROOT / "profiles" / target / "clips" / "clips.yaml"
    if cur.exists() and cur.stat().st_mtime >= z.stat().st_mtime:
        return
    k = input(f"\n새 녹음 묶음을 찾았습니다: {z.name}\n  → '{target}' 프로필에 넣을까요? (Enter = 넣기 / n = 안 넣기): ").strip().lower()
    if k != "n":
        run("--profile", target, "clips", str(z))


def run(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "main.py"), *args], cwd=ROOT)
    input("\n(Enter 를 누르면 메뉴로)")


def main(profile: str = "") -> None:
    names = profiles()
    try:
        offer_new_zip(names)
    except Exception as e:  # 찾기에 실패해도 메뉴는 열리게
        print(f"(새 녹음 찾기 건너뜀: {e})")
    if not profile and names:
        # 녹음을 넣은 프로필 우선 → 없으면 임플란트
        recorded = [n for n in names if (ROOT / "profiles" / n / "clips" / "clips.yaml").exists()]
        profile = recorded[0] if recorded else ("임플란트" if "임플란트" in names else names[0])
    while True:
        p = ["--profile", profile] if profile else []
        print("\n" + "=" * 46 + f"\n  전화상담   (프로필: {profile or '기본'})\n" + "=" * 46)
        print("  1. 점검하기           (준비됐는지 확인)\n"
              "  2. 폰 연결 설정       (USB 로 꽂은 폰 찾기)\n"
              "  3. 내 녹음 넣기       (녹음 파일을 문장별로 자르기)\n"
              "  4. 연습하기           (전화 없이 타이핑으로)\n"
              "  5. 고객에게 전화 시작 (1번 폰)\n"
              "  6. 고객에게 전화 시작 (2번 폰)\n"
              "  7. 아무 번호로 걸기\n"
              "  8. 녹음 대본 보기\n"
              "  9. 프로필 바꾸기\n"
              "  c. 내 목소리로 대본 만들기 (녹음 대신 복제 목소리로 한 번에)\n"
              "  k. 카톡 보내기 테스트  (성사 녹취록 받을 담당자 대화방)\n"
              "  s. 소리 테스트        (스피커에서 소리가 나는지)\n"
              "  u. 프로그램 업데이트 (고친 버전 받기)\n"
              "  0. 끝내기")
        c = input("\n번호를 누르고 Enter: ").strip()
        if c == "1":
            run(*p, "doctor")
        elif c == "2":
            run("phones")
        elif c == "3":
            f = ask_clip_file()
            if f:
                run(*p, "clips", f)
        elif c == "4":
            run(*p, "practice", "--voice")
        elif c == "5":
            run(*p, "next")
        elif c == "6":
            run("--config", "config2.yaml", *p, "next")
        elif c == "7":
            n = input("걸 번호: ").strip()
            b = input("통화 목적 (없으면 Enter): ").strip()
            if n:
                run(*p, "dial", n, *(["--brief", b] if b else []))
        elif c == "8":
            script = ROOT / "profiles" / profile / "녹음대본.txt"
            if script.exists():
                subprocess.Popen(["notepad", str(script)])
            else:
                print("이 프로필에는 녹음 대본이 없습니다.")
        elif c == "9":
            for i, n in enumerate(names, 1):
                print(f"  {i}. {n}")
            k = input("번호 (기본 설정은 0): ").strip()
            profile = names[int(k) - 1] if k.isdigit() and 0 < int(k) <= len(names) else ""
        elif c.lower() == "c":
            run(*p, "voice-setup")
        elif c.lower() == "k":
            run(*p, "kakao-test")
        elif c.lower() == "s":
            run(*p, "sound-test")
        elif c.lower() == "u":
            from .updater import update
            try:
                update()
            except Exception as e:
                print(f"업데이트 실패: {e}")
            input("\n(Enter)")
            return
        elif c == "0":
            return
