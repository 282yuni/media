"""전화상담.bat 이 여는 번호 메뉴."""
import subprocess
import sys

from .config import ROOT


def profiles() -> list[str]:
    d = ROOT / "profiles"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_")) if d.exists() else []


def run(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "main.py"), *args], cwd=ROOT)
    input("\n(Enter 를 누르면 메뉴로)")


def main(profile: str = "") -> None:
    names = profiles()
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
              "  u. 프로그램 업데이트 (고친 버전 받기)\n"
              "  0. 끝내기")
        c = input("\n번호를 누르고 Enter: ").strip()
        if c == "1":
            run(*p, "doctor")
        elif c == "2":
            run("phones")
        elif c == "3":
            f = input("녹음 파일을 이 창으로 끌어다 놓고 Enter: ").strip().strip('"')
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
