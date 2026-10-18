from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _merge(base: dict, extra: dict) -> dict:
    for k, v in (extra or {}).items():
        base[k] = _merge(base.get(k) or {}, v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def apply_profile(cfg: dict, name: str) -> dict:
    """용도별 프로필 (profiles/<이름>/): 녹음·상황표·플레이북·설정을 그 폴더 것으로 바꾼다.
    예: 치과콜, 곤란한전화, 예약 — 같은 프로그램을 여러 용도로."""
    pdir = ROOT / "profiles" / name
    if not pdir.exists():
        raise SystemExit(f"프로필이 없습니다: {pdir}  (python main.py profile-new {name} 으로 만드세요)")
    cfg.setdefault("voice", {})["clips_dir"] = str(pdir / "clips")
    cfg.setdefault("rules", {})["scenarios"] = str(pdir / "scenarios.yaml")
    cfg.setdefault("brain", {})["playbook"] = str(pdir / "playbook.md")
    cfg["logs_dir"] = str(Path(cfg.get("logs_dir", "logs")) / name)
    extra = pdir / "profile.yaml"
    if extra.exists():
        _merge(cfg, yaml.safe_load(extra.read_text(encoding="utf-8")) or {})
    cfg["_profile"] = name
    return cfg


def load_config(path: str | None = None, profile: str | None = None) -> dict:
    """path 를 주면 그 설정 파일을 쓴다 (전화기 2대: config.yaml / config2.yaml 로 각각 실행)."""
    global CONFIG_PATH
    load_dotenv(ROOT / ".env")
    if path:
        CONFIG_PATH = resolve(path)
        if not CONFIG_PATH.exists():
            raise SystemExit(f"설정 파일이 없습니다: {CONFIG_PATH}")
    path = CONFIG_PATH if CONFIG_PATH.exists() else ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return apply_profile(cfg, profile) if profile else cfg


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
