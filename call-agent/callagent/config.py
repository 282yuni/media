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
    extra = pdir / "profile.yaml"
    extra = (yaml.safe_load(extra.read_text(encoding="utf-8")) or {}) if extra.exists() else {}
    if extra.get("auto_script"):
        # 자동 프로필: 손님마다 script_for() 로 스크립트를 고름. 점검·연습 등은 기본 스크립트로
        cfg = apply_profile(cfg, extra["auto_script"]["default"])
    else:
        cfg.setdefault("voice", {})["clips_dir"] = str(pdir / "clips")
        cfg.setdefault("rules", {})["scenarios"] = str(pdir / "scenarios.yaml")
        cfg.setdefault("brain", {})["playbook"] = str(pdir / "playbook.md")
        cfg["logs_dir"] = str(Path(cfg.get("logs_dir", "logs")) / name)
    _merge(cfg, extra)
    cfg["_profile"] = name
    return cfg


def script_for(cfg: dict, customer: dict | None) -> dict:
    """자동 프로필이면 이 손님에게 쓸 스크립트(프로필) 설정을 돌려준다.
    엑셀 '스크립트' 칸(1/2)이 있으면 그것, 없으면 '업종' 칸 낱말로, 둘 다 아니면 기본 스크립트."""
    a = cfg.get("auto_script")
    if not a or not customer:
        return cfg
    pick = str(customer.get(a.get("pick_column", "스크립트")) or "").strip().removesuffix(".0")
    name = (a.get("numbers") or {}).get(pick)
    if not name:
        kind = str(customer.get(a.get("column", "업종")) or "")
        name = next((r["profile"] for r in a.get("rules", []) if any(k in kind for k in r.get("match", []))),
                    a["default"])
    sub = load_config(None, name)
    room = (cfg.get("notify") or {}).get("kakao_room")
    if room:  # 카톡 대화방은 자동 프로필에 정한 것 하나로
        sub.setdefault("notify", {})["kakao_room"] = room
    sub["_script"] = name
    return sub


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
