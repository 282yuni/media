from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: str | None = None) -> dict:
    """path 를 주면 그 설정 파일을 쓴다 (전화기 2대: config.yaml / config2.yaml 로 각각 실행)."""
    global CONFIG_PATH
    load_dotenv(ROOT / ".env")
    if path:
        CONFIG_PATH = resolve(path)
        if not CONFIG_PATH.exists():
            raise SystemExit(f"설정 파일이 없습니다: {CONFIG_PATH}")
    path = CONFIG_PATH if CONFIG_PATH.exists() else ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_voice_id(voice_id: str) -> None:
    """config.yaml 의 voice.voice_id 한 줄만 바꾼다 (주석 보존)."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text((ROOT / "config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().startswith("voice_id:"):
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f'{indent}voice_id: "{voice_id}"\n'
            break
    CONFIG_PATH.write_text("".join(lines), encoding="utf-8")


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
