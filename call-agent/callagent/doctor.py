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


def run(cfg: dict, dial: str = "") -> int:
    r = Report()
    print(f"=== 자가 점검 ({datetime.now():%Y-%m-%d %H:%M}) / 설정 파일: {CONFIG_PATH.name} ===\n")

    # 1. 기본 프로그램
    r.add(sys.version_info >= (3, 10), "Python", platform.python_version(), "python.org 에서 3.10 이상 설치")
    r.add(True, "운영체제", f"{platform.system()} {platform.release()}")
    for mod, why in [("numpy", "기본"), ("yaml", "기본"), ("openpyxl", "엑셀"), ("sounddevice", "소리 입출력"),
                     ("faster_whisper", "무료 음성 인식")]:
        try:
            importlib.import_module(mod)
            r.add(True, f"라이브러리 {mod}")
        except Exception as e:
            r.add(False, f"라이브러리 {mod} ({why})", str(e)[:80], "pip install -r requirements.txt")
    r.add(bool(shutil.which("ffmpeg")), "ffmpeg (녹음 자르기)", "", "winget install ffmpeg 후 창을 새로 열기")

    # 2. 휴대폰 (adb)
    d = cfg.get("dialer", {})
    adb = d.get("adb_path", "adb")
    if not shutil.which(adb):
        r.add(False if d.get("mode") == "adb" else None, "adb (자동 걸기)", "설치 안 됨",
              "platform-tools 를 받아 압축 풀고 그 폴더를 config 의 dialer.adb_path 에 적거나 PATH 에 추가")
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
        miss = missing(str(ag.get(key, "")))
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
            r.add("AI 질문" in names or None, "상황표에 'AI 질문' 상황", "", "AI냐고 물을 때 사실대로 답하는 상황을 맨 위에 추가")
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
                  "느리면 config 의 stt.local_model 을 base 로 (그래픽카드 있으면 device: cuda)")
        except Exception as e:
            r.add(False, "무료 음성 인식", str(e)[:120], "인터넷 연결 후 다시 (처음 한 번 모델을 내려받음)")

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
    from .config import ROOT
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
            text = re.sub(r'(?m)^(\s*adb_path:\s*)"[^"]*"', rf'\1"{adb}"', text)
        if i > 0:  # 두 번째 폰은 녹취·결과를 따로 (같은 엑셀을 동시에 쓰면 충돌)
            text = re.sub(r'(?m)^logs_dir: "logs"', 'logs_dir: "logs/phone2"', text)
        path.write_text(text, encoding="utf-8")
        print(f"📱 {p['model']} (안드로이드 {p['android']}, {p['serial']}) → {path.name}")
    if len(phones) > 1:
        print("\n두 번째 폰 설정(config2.yaml)에서 꼭 바꿀 것:\n"
              "  1) audio 장치 — 두 번째 폰 소리가 들어오고 나가는 장치 이름\n"
              "  2) customers.path — 두 번째 폰용 고객 엑셀 (같은 파일을 두 창에서 동시에 쓰면 저장이 꼬입니다)\n"
              "실행: 창1 python main.py next  /  창2 python main.py --config config2.yaml next")
    print("\n다음: python main.py doctor --dial 내다른번호  (시험 전화로 자동 걸기 확인)")
