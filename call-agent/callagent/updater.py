"""메뉴의 '프로그램 업데이트': GitHub 에서 최신 프로그램을 받아 덮어쓴다.
내 설정·녹음·고객 엑셀·통화 기록은 건드리지 않고, 내가 고친 대본/상황표는 .bak 으로 남겨 둔다."""
import io
import urllib.request
import zipfile
from pathlib import PurePosixPath

from .config import ROOT

URL = "https://github.com/282yuni/media/archive/refs/heads/claude/voice-clone-call-automation-iizrpp.zip"
KEEP_DIRS = {"data", "logs", "clips", "python", "platform-tools", "recordings", "voice_samples"}
KEEP_FILES = {"config.yaml", "config2.yaml", "config3.yaml", ".env", "playbook.md", "scenarios.yaml"}


def update() -> None:
    print("최신 프로그램 받는 중… (약 70MB, 1~3분)")
    data = urllib.request.urlopen(URL, timeout=600).read()
    changed = backed = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            parts = PurePosixPath(name).parts
            if len(parts) < 3 or parts[1] != "call-agent" or name.endswith("/"):
                continue
            rel = parts[2:]
            if KEEP_DIRS & set(rel[:-1]) or (len(rel) == 1 and rel[0] in KEEP_FILES):
                continue
            dst = ROOT.joinpath(*rel)
            new = z.read(name)
            if dst.exists():
                old = dst.read_bytes()
                if old == new:
                    continue
                if rel[0] == "profiles":  # 내가 고쳤을 수 있는 대본·상황표는 백업
                    dst.with_name(dst.name + ".bak").write_bytes(old)
                    backed += 1
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(new)
            changed += 1
    print(f"업데이트 완료: 파일 {changed}개 바뀜" + (f" (고친 대본·상황표 {backed}개는 .bak 으로 백업)" if backed else ""))
    print("메뉴를 닫고 바탕화면 '전화상담' 을 다시 실행하세요.")
