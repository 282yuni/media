"""자가 점검: python main.py doctor  →  준비 상태를 하나씩 확인하고 logs/doctor.txt 로 저장.
결과 파일을 그대로 Claude/Codex 에게 붙여 넣으면 무엇을 고쳐야 할지 바로 알 수 있다."""
import importlib
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import yaml

from .config import CONFIG_PATH, resolve


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.fails = 0

    def add(self, ok: bool | None, title: str, detail: str = "", fix: str = "") -> None:
        mark = {True: "✅", False: "❌", None: "⚠️"}[ok]
        self.fails += ok is False
        line = f"{mark} {title}" + (f" — {detail}" if detail else "")
        if fix and ok is not True:
            line += f"\n     → 해결: {fix}"
        self.lines.append(line)
        print(line)


def adb_devices(adb: str = "adb") -> list[dict]:
    """연결된 안드로이드폰 목록: [{serial, state, model, android}]"""
    out = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=15).stdout
    phones = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        model = re.search(r"model:(\S+)", line)
        info = {"serial": serial, "state": state, "model": model.group(1) if model else "?", "android": "?"}
        if state == "device":
            ver = subprocess.run([adb, "-s", serial, "shell", "getprop", "ro.build.version.release"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            info["android"] = ver or "?"
        phones.append(info)
    return phones


# ── 폰별 USB 사운드카드 자동 찾기 ──────────────────────────────
# USB 꽂는 자리를 바꾸거나 허브 전원이 끊기면 Windows 가 '마이크(2- USB Audio Device)' 의 번호를 4-, 6- 로 바꾼다.
# 폰에서 벨소리를 틀고, 모든 USB 사운드카드 마이크를 동시에 들어서 소리가 크게 들어온 카드가 그 폰의 카드.
CARD = re.compile(r"(\d+)- USB Audio Device")
BEEP = "file:///system/media/audio/ringtones/Beep-Beep.ogg"


def usb_cards() -> dict[str, dict]:
    """꽂혀 있는 USB 사운드카드: {번호: {"input": (장치번호, 이름), "output": (장치번호, 이름)}}"""
    import sounddevice as sd
    cards: dict[str, dict] = {}
    for i, dv in enumerate(sd.query_devices()):
        m = CARD.search(dv["name"])
        if not m:
            continue
        card = cards.setdefault(m.group(1), {})
        if dv["max_input_channels"] > 0:
            card.setdefault("input", (i, dv["name"]))  # 같은 장치가 여러 번 나오면 맨 앞(MME) 것
        if dv["max_output_channels"] > 0:
            card.setdefault("output", (i, dv["name"]))
    return {n: c for n, c in cards.items() if "input" in c and "output" in c}


def record_levels(devices: dict[str, int], sec: float = 4.0) -> dict[str, float]:
    """여러 마이크를 동시에 sec 초 듣고 각각의 소리 크기(RMS)."""
    import numpy as np
    import sounddevice as sd
    got: dict[str, list] = {n: [] for n in devices}
    streams = []
    for n, idx in devices.items():
        def cb(indata, frames, t, status, n=n):
            got[n].append(indata[:, 0].copy())
        try:
            s = sd.InputStream(samplerate=int(sd.query_devices(idx)["default_samplerate"]), channels=1,
                               dtype="float32", device=idx, callback=cb)
            s.start()
            streams.append(s)
        except Exception:
            pass  # 못 여는 카드는 0 으로
    time.sleep(sec)
    for s in streams:
        s.stop()
        s.close()
    return {n: float(np.sqrt(np.mean(np.square(np.concatenate(v))))) if v else 0.0 for n, v in got.items()}


def phone_in_call(adb: str, serial: str, sh=subprocess.run) -> bool:
    """통화 중(또는 알 수 없음)이면 True — 그때는 벨소리를 틀지 않는다."""
    try:
        out = sh([adb, "-s", serial, "shell", "dumpsys", "telephony.registry"], capture_output=True, text=True,
                 encoding="utf-8", errors="ignore", timeout=10).stdout
    except Exception:
        return True
    states = re.findall(r"mCallState=(\d)", out or "")
    return not states or any(x != "0" for x in states)


def find_phone_soundcard(serial: str, adb: str = "adb", sh=subprocess.run, cards=None,
                         record=record_levels) -> tuple[dict | None, str]:
    """이 폰(serial)이 꽂힌 USB 사운드카드 찾기. 돌려주는 값: (카드 또는 None, 사람이 읽을 설명)
    카드 = {"number": "6", "input": "마이크(6- USB Audio Device)", "output": "스피커(6- USB Audio Device)"}"""
    if phone_in_call(adb, serial, sh):
        return None, "폰이 통화 중이거나 상태를 알 수 없어서 찾지 않았습니다. 통화가 끝난 뒤 다시 해 주세요."
    cards = usb_cards() if cards is None else cards
    if not cards:
        return None, "PC 에 USB 사운드카드가 안 보입니다. 사운드카드 USB 가 꽂혀 있는지 확인해 주세요."
    target = [adb, "-s", serial, "shell"]
    try:
        sh([*target, "am", "start", "-a", "android.intent.action.VIEW", "-d", BEEP, "-t", "audio/ogg"],
           capture_output=True, timeout=10)
        time.sleep(0.5)
        levels = record({n: c["input"][0] for n, c in cards.items()})
    finally:
        try:
            sh([*target, "input", "keyevent", "KEYCODE_HOME"], capture_output=True, timeout=10)
        except Exception:
            pass
    ranked = sorted(levels.items(), key=lambda kv: kv[1], reverse=True)
    detail = ", ".join(f"{n}-번 {v:.3f}" for n, v in ranked)
    best, loud = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if loud < 0.005:
        return None, (f"폰 소리가 어느 사운드카드에도 안 들어왔습니다 ({detail}). "
                      "이어폰 잭이 끝까지 꽂혔는지, 폰 미디어 소리가 켜져 있는지 확인해 주세요.")
    if loud < second * 5:
        return None, f"어느 카드인지 확실하지 않습니다 ({detail}). 다른 폰이 통화 중이면 끝난 뒤 다시 해 주세요."
    c = cards[best]
    return {"number": best, "input": c["input"][1], "output": c["output"][1]}, detail


def write_soundcard(path, card: dict) -> None:
    """설정 파일의 audio.call_input / audio.ai_output 두 줄의 장치 이름만 바꾼다 (주석·다른 설정은 그대로)."""
    text = path.read_text(encoding="utf-8")
    for key, name in (("call_input", card["input"]), ("ai_output", card["output"])):
        text = re.sub(rf'(?m)^(\s*{key}:\s*)"[^"]*"', lambda m, name=name: f'{m.group(1)}"{name}"', text, count=1)
    path.write_text(text, encoding="utf-8")


def fix_soundcard(path, audio: dict, serial: str, adb: str = "adb", cards=None, **kw) -> dict | None:
    """설정의 USB 사운드카드가 지금 PC 에 없으면 (번호가 바뀐 경우) 폰 벨소리로 찾아서 설정 파일을 고친다.
    가상 케이블처럼 USB 사운드카드가 아닌 설정이거나, 장치가 그대로 있으면 아무것도 안 한다."""
    name = audio.get("call_input", "")
    if not serial or not CARD.search(name):
        return None
    cards = usb_cards() if cards is None else cards
    if any(name.lower() in c["input"][1].lower() for c in cards.values()):
        return None  # 그대로 있음
    print(f"\n🔎 설정에 적힌 '{name}' 이 지금 PC 에 없습니다 (USB 꽂는 자리를 바꾸면 번호가 바뀝니다).\n"
          f"   폰({serial})에서 '삑삑' 소리를 4초 틀어서 어느 사운드카드인지 찾습니다…")
    card, detail = find_phone_soundcard(serial, adb, cards=cards, **kw)
    if not card:
        print(f"   ⚠️ 못 찾았습니다: {detail}")
        return None
    write_soundcard(path, card)
    audio["call_input"], audio["ai_output"] = card["input"], card["output"]
    print(f"   ✅ 찾았습니다: {card['number']}-번 사운드카드 ({detail})\n"
          f"   {path.name} 를 고쳤습니다 → 들어오는 소리 '{card['input']}', 내보내는 소리 '{card['output']}'")
    return card


def run(cfg: dict, dial: str = "") -> int:
    r = Report()
    print(f"=== 자가 점검 ({datetime.now():%Y-%m-%d %H:%M}) / 설정 파일: {CONFIG_PATH.name} ===\n")

    # 1. 기본 프로그램
    r.add(sys.version_info >= (3, 10), "Python", platform.python_version(), "python.org 에서 3.10 이상 설치")
    r.add(True, "운영체제", f"{platform.system()} {platform.release()}")
    for mod, why in [("numpy", "기본"), ("yaml", "기본"), ("openpyxl", "엑셀"), ("sounddevice", "소리 입출력"),
                     ("sherpa_onnx", "무료 음성 인식"), ("av", "녹음 파일 읽기")]:
        try:
            importlib.import_module(mod)
            r.add(True, f"라이브러리 {mod}")
        except Exception as e:
            r.add(False, f"라이브러리 {mod} ({why})", str(e)[:80], "pip install -r requirements.txt")

    # 2. 휴대폰 (adb)
    d = cfg.get("dialer", {})
    from .adbtool import find_adb
    adb = find_adb(d.get("adb_path", "adb"))
    phones: list[dict] = []
    if not shutil.which(adb):
        r.add(False if d.get("mode") == "adb" else None, "adb (자동 걸기)", "설치 안 됨",
              "메뉴 2번(폰 연결 설정)을 누르면 자동으로 받아서 설치합니다")
    else:
        try:
            phones = adb_devices(adb)
        except Exception as e:
            phones = []
            r.add(False, "adb 실행", str(e)[:80])
        r.add(bool(phones), f"연결된 휴대폰 {len(phones)}대", "", "USB 연결 후 폰 화면의 'USB 디버깅 허용'에서 허용 누르기")
        for p in phones:
            ok = p["state"] == "device"
            r.add(ok, f"  폰 {p['model']} (일련번호 {p['serial']}, 안드로이드 {p['android']})", p["state"],
                  "폰 화면에 뜬 'USB 디버깅을 허용하시겠습니까?'에서 '항상 허용' 체크 후 허용")
        serial = d.get("adb_serial", "")
        if len(phones) > 1 and not serial:
            r.add(False, "이 설정 파일이 쓸 폰", "폰이 2대인데 adb_serial 이 비어 있음", "python main.py phones 를 실행하면 자동으로 채워짐")
        elif serial:
            r.add(any(p["serial"] == serial for p in phones), "이 설정 파일이 쓸 폰", serial, "python main.py phones 다시 실행")
        r.add(d.get("mode") == "adb" or None, "자동 걸기 설정", f"dialer.mode = {d.get('mode')}", "config 의 dialer.mode 를 \"adb\" 로")
        if dial:
            from .dialer import Dialer
            try:
                dl = Dialer({**cfg, "dialer": {**d, "mode": "adb"}})
                dl.dial(dial)
                print("   (8초 뒤 자동으로 끊습니다)")
                time.sleep(8)
                dl.hang_up()
                ok = input("   폰에서 전화가 걸렸다가 끊겼나요? (y/n) ").strip().lower() == "y"
                r.add(ok, f"시험 전화 {dial}", "", "폰 잠금 화면을 풀고 다시 시도. 안 되면 폰 기본 전화 앱이 삼성 전화인지 확인")
            except Exception as e:
                r.add(False, f"시험 전화 {dial}", str(e)[:120])

    # 3. 소리 장치
    a = cfg.get("audio", {})
    ready = [p["serial"] for p in phones if p["state"] == "device"]
    serial = d.get("adb_serial", "") or (ready[0] if len(ready) == 1 else "")
    if serial in ready:  # USB 사운드카드 번호가 바뀌었으면 폰 벨소리로 찾아서 설정 고치기
        try:
            from . import config
            fix_soundcard(config.CONFIG_PATH, a, serial, adb)
        except Exception as e:
            print(f"(사운드카드 자동 찾기 건너뜀: {e})")
    try:
        from .audio import find_device
        for key, kind, what in [("call_input", "input", "상대 목소리 들어오는 곳"), ("ai_output", "output", "내 녹음 내보내는 곳"),
                                ("monitor_output", "output", "내 헤드셋")]:
            name = a.get(key, "")
            if not name:
                r.add(None, f"소리 {key} ({what})", "비어 있음 (헤드셋은 비워도 됨)")
                continue
            try:
                idx = find_device(name, kind)
                r.add(True, f"소리 {key} ({what})", f"'{name}' → 장치 {idx}번")
            except Exception:
                r.add(False, f"소리 {key} ({what})", f"'{name}' 장치 없음",
                      "python main.py devices 로 이름을 보고 config 에 그 이름 일부를 적기 (VB-Cable 설치 후 재부팅 필요)")
    except Exception as e:
        r.add(False, "소리 장치 확인", str(e)[:100], "pip install sounddevice")

    # 4. 내 녹음 + 상황표
    from .clips import TOKEN, ClipBank
    bank = ClipBank(cfg)
    r.add(bool(bank), f"내 녹음 문장 {len(bank.items)}개", str(bank.dir), "python main.py clips 내녹음.mp3")
    blank = 0
    path = bank.dir / "clips.yaml"
    if path.exists():
        blank = sum(1 for c in yaml.safe_load(path.read_text(encoding="utf-8")) or [] if c.get("use", True) and not (c.get("text") or "").strip())
    if blank:
        r.add(None, f"글이 비어 있는 녹음 {blank}개", "글이 없으면 상황표에서 고를 수 없음", "clips.yaml 의 text 채우기")

    def missing(text: str) -> list[int]:
        return [int(m) for m in TOKEN.findall(text or "") if int(m) not in bank.items]

    ag = cfg.get("agent", {})
    for key in ("opening", "ai_disclosure", "hello_again"):
        val = ag.get(key, "")
        miss = missing(" ".join(val) if isinstance(val, list) else str(val))
        r.add(not miss, f"agent.{key}", str(ag.get(key, "")) + (f" (없는 번호 {miss})" if miss else ""), "clips.yaml 에 있는 번호로 고치기")
    sc_path = resolve(cfg.get("rules", {}).get("scenarios", "scenarios.yaml"))
    if sc_path.exists():
        try:
            sc = yaml.safe_load(sc_path.read_text(encoding="utf-8")) or {}
            refs = yaml.safe_dump(sc, allow_unicode=True)
            miss = sorted(set(missing(refs)))
            names = [s.get("name") for s in sc.get("scenarios", [])]
            r.add(True, f"상황표 {sc_path.name}", f"상황 {len(names)}개, 스크립트 {len(sc.get('flow', []))}단계")
            r.add(not miss, "상황표의 녹음 번호", f"없는 번호 {miss}" if miss else "모두 있음", "clips.yaml 번호에 맞게 scenarios.yaml 고치기")
        except Exception as e:
            r.add(False, f"상황표 {sc_path.name}", f"읽기 실패: {e}"[:120], "들여쓰기(띄어쓰기)가 틀렸는지 확인")
    else:
        r.add(False, "상황표 scenarios.yaml", "없음", "copy scenarios.example.yaml scenarios.yaml 또는 Codex 에게 만들어 달라고 하기")

    # 5. 고객 목록
    try:
        from .customers import CustomerBook
        book = CustomerBook(cfg)
        pend = book.next_pending()
        r.add(True, f"고객 목록 {len(book.all())}명", f"다음 전화: {pend['_clinic']} {pend['_phone']}" if pend else "걸 고객 없음")
        cols = cfg["customers"]["columns"]
        for k in ("clinic", "phone"):
            r.add(cols[k] in book.header, f"고객 목록 열 '{cols[k]}'", "", f"엑셀 첫 줄 열 이름: {book.header} 중 맞는 걸 config 의 columns.{k} 에 적기")
    except Exception as e:
        r.add(False, "고객 목록", str(e)[:120], "config 의 customers.path 와 엑셀 파일 위치 확인 (엑셀은 닫아 두기)")

    # 6. 음성 인식 속도
    if cfg.get("engine", "free") == "free":
        try:
            import numpy as np
            from .local_stt import LocalEars
            t0 = time.time()
            ears = LocalEars(cfg)
            load = time.time() - t0
            t0 = time.time()
            ears.transcribe_pcm(np.zeros(16000 * 3, np.int16), 16000)
            spent = time.time() - t0
            r.add(spent < 3 or None, "음성 인식 속도 (3초 말 받아 적기)", f"{spent:.1f}초 (모델 준비 {load:.0f}초)",
                  "PC가 느리면 다른 프로그램을 닫고 다시 점검")
        except Exception as e:
            r.add(False, "무료 음성 인식", str(e)[:120], "완성본 ZIP 을 다시 풀어 models 폴더가 있는지 확인")

    verdict = "모두 준비됨! python main.py practice 로 연습해 보세요." if r.fails == 0 else f"❌ {r.fails}개를 고쳐야 합니다."
    print(f"\n{verdict}")
    logs = resolve(cfg.get("logs_dir", "logs"))
    logs.mkdir(parents=True, exist_ok=True)
    out = logs / "doctor.txt"
    out.write_text("\n".join(r.lines + ["", verdict]), encoding="utf-8")
    print(f"결과 저장: {out}  (이 내용을 그대로 붙여 넣어 주시면 원인을 찾아 드려요)")
    return r.fails


def setup_phones(adb: str = "adb") -> None:
    """연결된 폰마다 설정 파일을 만든다: 1번째 폰 → config.yaml, 2번째 → config2.yaml"""
    from .adbtool import fetch_adb, find_adb
    from .config import ROOT
    adb = find_adb(adb)
    if not shutil.which(adb):
        adb = fetch_adb()
    phones = [p for p in adb_devices(adb) if p["state"] == "device"]
    if not phones:
        raise SystemExit("연결된 폰이 없습니다. USB 연결 후 폰 화면에서 'USB 디버깅 허용'을 눌러 주세요. (adb devices 로 확인)")
    for i, p in enumerate(phones[:2]):
        path = ROOT / ("config.yaml" if i == 0 else f"config{i + 1}.yaml")
        src = path if path.exists() else ROOT / "config.example.yaml"
        text = src.read_text(encoding="utf-8")
        text = re.sub(r'(?m)^(\s*)mode: "manual"', r'\1mode: "adb"', text)
        text = re.sub(r'(?m)^(\s*adb_serial:\s*)"[^"]*"', rf'\1"{p["serial"]}"', text)
        if adb != "adb":
            adb = adb.replace("\\", "/")
            text = re.sub(r'(?m)^(\s*adb_path:\s*)"[^"]*"', rf'\1"{adb}"', text)
        if i > 0:  # 두 번째 폰은 녹취·결과를 따로 (같은 엑셀을 동시에 쓰면 충돌)
            text = re.sub(r'(?m)^logs_dir: "logs"', 'logs_dir: "logs/phone2"', text)
        path.write_text(text, encoding="utf-8")
        print(f"📱 {p['model']} (안드로이드 {p['android']}, {p['serial']}) → {path.name}")
        try:
            fix_soundcard(path, (yaml.safe_load(text) or {}).get("audio") or {}, p["serial"], adb)
        except Exception as e:
            print(f"(사운드카드 자동 찾기 건너뜀: {e})")
    if len(phones) > 1:
        print("\n두 번째 폰 설정(config2.yaml)에서 꼭 바꿀 것:\n"
              "  1) audio 장치 — 두 번째 폰 소리가 들어오고 나가는 장치 이름\n"
              "  2) customers.path — 두 번째 폰용 고객 엑셀 (같은 파일을 두 창에서 동시에 쓰면 저장이 꼬입니다)\n"
              "실행: 창1 python main.py next  /  창2 python main.py --config config2.yaml next")
    print("\n다음: python main.py doctor --dial 내다른번호  (시험 전화로 자동 걸기 확인)")
