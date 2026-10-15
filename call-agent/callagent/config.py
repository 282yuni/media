from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
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
