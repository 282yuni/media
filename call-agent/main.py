"""치과 1차 콜 AI 대행 — 실행 진입점.

  python main.py doctor               준비 상태 자가 점검 (결과: logs/doctor.txt)
  python main.py phones               USB 로 연결된 폰 찾아서 폰별 설정 파일 만들기
  python main.py devices              오디오 장치 목록
  python main.py meter                상대방 소리 크기 확인 (speech_threshold 조정용)
  python main.py clone-voice          voice_samples/ 녹음으로 내 목소리 복제
  python main.py clips 내녹음.mp3      내 녹음을 문장별로 잘라 그대로 쓰기 (변환 없음)
  python main.py say "안녕하세요"      복제된 내 목소리로 한 문장 들어보기
  python main.py script 상담스크립트.txt 상담 스크립트만으로 playbook.md 생성 (녹음 없어도 됨)
  python main.py train                recordings/ 통화 녹음 → playbook.md 생성
  python main.py practice             키보드로 상대 역할을 하며 AI 응대 연습 (전화 X)
  python main.py list                 고객 목록 보기
  python main.py call 5               고객 시트 5행에 전화
  python main.py next                 아직 안 한 고객부터 차례대로 계속 전화
  python main.py profile-new 곤란한전화 용도별 프로필 만들기 (녹음·상황표·말투를 용도별로)
  python main.py --profile 곤란한전화 dial 01012345678 --brief "해지만 요청" --info 정보.txt
                                      아무 번호에 AI가 내 정보로 생각해서 내 목소리로 대신 통화
  python main.py --profile 곤란한전화 coach                                   내가 통화하고 AI는 할 말만 추천
"""
import argparse
import sys
from pathlib import Path

from callagent.config import ROOT, load_config, resolve, save_voice_id


def load_playbook(cfg: dict) -> str:
    from callagent.engine import is_free
    if is_free(cfg):
        return ""  # 무료 모드는 scenarios.yaml 을 씀
    p = resolve(cfg["brain"].get("playbook", "playbook.md"))
    if not p.exists():
        sys.exit(f"{p.name} 이 없습니다. 먼저 `python main.py train` 으로 만들어 주세요.")
    return p.read_text(encoding="utf-8")


def cmd_devices(cfg, args):
    from callagent.audio import list_devices
    list_devices()


def cmd_meter(cfg, args):
    from callagent.audio import meter
    meter(cfg, args.seconds)


def cmd_clone(cfg, args):
    from callagent.voice import clone_voice
    folder = ROOT / args.folder
    print("⚠ 본인 목소리만 복제하세요. 다른 사람 목소리를 동의 없이 복제하는 것은 불법일 수 있습니다.")
    if input("이 폴더의 녹음이 모두 내 목소리입니까? (y/n) ").strip().lower() != "y":
        return
    vid = clone_voice(folder, f"{cfg['agent']['my_name']} (콜 대행)")
    save_voice_id(vid)
    print(f"완료! voice_id={vid}  → config.yaml 에 저장했습니다. `python main.py say \"안녕하세요\"` 로 들어보세요.")


def cmd_clips(cfg, args):
    from callagent.clips import ClipBank, cut
    if args.file:
        print("⚠ 본인 목소리 녹음만 쓰세요. 상대방 목소리 부분은 clips.yaml 에서 use: false 로 꺼주세요.")
        cut(cfg, Path(args.file), noise_db=args.noise, min_silence=args.gap)
    bank = ClipBank(cfg)
    print(f"\n사용 중인 녹음 문장 {len(bank.items)}개:")
    print(bank.catalog())


def cmd_sound_test(cfg, args):
    """스피커 확인: '삐' 소리 → (녹음이 있으면) 첫인사 녹음 재생."""
    import time
    import numpy as np
    from callagent.audio import Speaker, list_devices
    from callagent.clips import TOKEN, ClipBank, split_tokens
    from callagent.voice import TTS_RATE
    name = cfg["audio"].get("monitor_output", "")
    print(f"소리를 '{name or 'Windows 기본 스피커'}' 로 내보냅니다.")
    try:
        out = Speaker(name, TTS_RATE)
    except Exception as e:
        print(f"❌ 스피커를 열 수 없습니다: {e}\n아래 장치 목록에서 스피커 이름을 확인하세요:")
        list_devices()
        return
    t = np.arange(int(TTS_RATE * 0.8)) / TTS_RATE
    out.write((np.sin(2 * np.pi * 660 * t) * 8000).astype(np.int16).tobytes())
    print("1) '삐—' 소리가 나야 합니다.")
    while out.pending_sec() > 0:
        time.sleep(0.05)
    bank = ClipBank(cfg)
    first = next((int(m.group(1)) for x in split_tokens(cfg["agent"].get("opening", ""))
                  if (m := TOKEN.fullmatch(x)) and int(m.group(1)) in bank.items), None)
    if first:
        print(f"2) 첫인사 녹음 [클립:{first}] 을 틉니다: {bank.text(first)}")
        out.write(bank.pcm(first))
        while out.pending_sec() > 0:
            time.sleep(0.05)
    else:
        print("2) 이 프로필에는 아직 녹음이 없어 녹음 재생은 건너뜁니다 (메뉴 3번으로 넣기).")
    out.close()
    print("\n삐 소리가 안 났다면: 작업 표시줄 오른쪽 아래 스피커 아이콘 → 음량과 출력 장치(스피커/헤드셋)를 확인하세요.")


def cmd_tts_clips(cfg, args):
    """녹음 대본 문장들을 내 복제 목소리로 한 번에 만들어 clips 로 저장 (ElevenLabs, 유료·한 번만).
    만든 뒤에는 무료 모드 그대로 — 통화 중엔 인터넷·API 를 쓰지 않는다."""
    import re
    import wave
    import yaml
    from callagent.config import resolve
    from callagent.voice import TTS_RATE, Voice
    pdir = ROOT / "profiles" / cfg["_profile"] if cfg.get("_profile") else Path(cfg["voice"]["clips_dir"]).parent
    script = pdir / "녹음대본.txt"
    if not script.exists():
        sys.exit("이 프로필에는 녹음대본.txt 가 없습니다. --profile 을 확인하세요.")
    lines = []
    for line in script.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\s+(.*?)(\s{2,}\(.*\))?$", line.rstrip())
        if m:
            lines.append((int(m.group(1)), m.group(2).strip()))
    out = resolve(cfg["voice"]["clips_dir"])
    out.mkdir(parents=True, exist_ok=True)
    voice = Voice(cfg)
    voice.model = "eleven_multilingual_v2"  # 미리 만들어 두는 거라 속도보다 자연스러움 우선
    print(f"녹음 대본 {len(lines)}문장을 내 목소리로 만드는 중… (2~5분)")
    catalog, prev = [], ""
    for cid, text in lines:
        pcm = b"".join(voice.speak(text, previous_text=prev))
        with wave.open(str(out / f"clip_{cid:03}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(TTS_RATE); w.writeframes(pcm)
        catalog.append({"id": cid, "file": f"clip_{cid:03}.wav", "text": text, "use": True, "source": "복제 목소리"})
        prev = text
        print(f"  [{cid:3}] {text}")
    (out / "clips.yaml").write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\n완료: {len(catalog)}문장 → {out}\n메뉴 4번(연습하기)으로 들어보세요. 어색한 문장은 그 번호만 직접 녹음해서 바꿀 수 있습니다.")


def cmd_voice_setup(cfg, args):
    """메뉴 c: 내 녹음으로 목소리 복제(처음 한 번) → 이 프로필의 녹음 대본을 내 목소리로 전부 만들기."""
    import importlib
    import os
    import subprocess
    try:
        importlib.import_module("elevenlabs")
    except ImportError:
        print("필요한 프로그램(elevenlabs) 설치 중…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "elevenlabs"], check=True)
    if not os.environ.get("ELEVENLABS_API_KEY"):
        print("ElevenLabs API 키가 필요합니다 (elevenlabs.io → 로그인 → 오른쪽 아래 프로필 → API Keys → Create).\n"
              "목소리 복제는 Starter 요금제 이상에서 됩니다. 대본 한 번 만드는 데 글자 약 2,000자 사용.")
        key = input("API 키를 붙여넣고 Enter: ").strip()
        if not key:
            return
        env = ROOT / ".env"
        lines = [l for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
                 if not l.startswith("ELEVENLABS_API_KEY")]
        env.write_text("\n".join(lines + [f"ELEVENLABS_API_KEY={key}"]) + "\n", encoding="utf-8")
        os.environ["ELEVENLABS_API_KEY"] = key
    if not cfg["voice"].get("voice_id"):
        from callagent.voice import clone_voice
        print("\n목소리 복제 (처음 한 번): 내 목소리만 들어간 녹음 파일(1~10분)이 필요합니다.")
        f = input("녹음 파일을 이 창으로 끌어다 놓고 Enter: ").strip().strip('"')
        if not f or not Path(f).exists():
            sys.exit("파일을 찾지 못했습니다.")
        if input("이 녹음이 모두 '내' 목소리입니까? (y/n) ").strip().lower() != "y":
            return
        vid = clone_voice(Path(f).parent, "전화상담 내 목소리", files=[Path(f)])
        save_voice_id(vid)
        cfg["voice"]["voice_id"] = vid
        print(f"복제 완료 (voice_id={vid}). 다음부터는 이 단계를 건너뜁니다.")
    cmd_tts_clips(cfg, args)


def cmd_say(cfg, args):
    import time
    from callagent.audio import Speaker
    from callagent.voice import TTS_RATE, Voice
    out = Speaker(cfg["audio"].get("monitor_output", "") if not args.to_call else cfg["audio"]["ai_output"], TTS_RATE)
    for pcm in Voice(cfg).speak(args.text):
        out.write(pcm)
    while out.pending_sec() > 0:
        time.sleep(0.05)
    out.close()


def cmd_train(cfg, args):
    from callagent.engine import is_free
    from callagent.trainer import build_playbook, transcribe_folder
    folder = ROOT / args.folder
    print(f"{folder} 의 통화 녹음을 받아 적습니다.")
    transcripts = transcribe_folder(cfg, folder)
    if is_free(cfg):
        print(f"\n대본 {len(transcripts)}개 → {folder / 'transcripts'}\n"
              "Codex 에게 \"recordings/transcripts 대본을 보고 scenarios.yaml 을 보강해줘\" 라고 요청하세요.")
        return
    build_playbook(cfg, transcripts, resolve(cfg["brain"].get("playbook", "playbook.md")))


def cmd_script(cfg, args):
    """녹음 없이 상담 스크립트(txt/md/docx)만으로 플레이북 만들기."""
    from callagent.trainer import build_playbook_from_script
    build_playbook_from_script(cfg, Path(args.file), resolve(cfg["brain"].get("playbook", "playbook.md")))


def cmd_practice(cfg, args):
    """전화 없이 플레이북 테스트. 내가 상대(치과) 역할로 타이핑하면 AI가 대답."""
    from callagent.engine import make_brain, voice_mode
    from callagent.session import fill
    customer = None
    if args.row:
        from callagent.customers import CustomerBook
        customer = CustomerBook(cfg).get(args.row)
    elif getattr(args, "kind", ""):
        customer = {"업종": args.kind, "_clinic": args.kind}
    from callagent.clips import TOKEN, ClipBank
    mode = voice_mode(cfg)
    clips = ClipBank(cfg) if mode in ("clips", "mixed") else None
    brain = make_brain(cfg, load_playbook(cfg), customer, clips)
    voice = speaker = None
    if args.voice:
        from callagent.audio import Speaker
        from callagent.voice import TTS_RATE, Voice
        voice = Voice(cfg) if mode != "clips" else None
        speaker = Speaker(cfg["audio"].get("monitor_output", ""), TTS_RATE)
        if mode == "clips" and not clips:
            print("⚠ 이 프로필에는 아직 녹음이 없어서 소리가 나지 않습니다. 글자로만 보여드려요.\n"
                  "  → 메뉴 3번(내 녹음 넣기)으로 녹음을 넣거나, 9번으로 녹음을 넣은 프로필로 바꾸세요.\n")
        else:
            print(f"🔊 소리는 '{cfg['audio'].get('monitor_output') or '기본 스피커'}' 로 나옵니다.\n")

    # 아직 녹음 전이면 녹음 대본 문장으로 보여주기 (녹음 전에도 흐름 연습 가능)
    import re as _re
    script_lines = {}
    sp = Path(cfg["voice"].get("clips_dir", "clips")).parent / "녹음대본.txt"
    if sp.exists():
        for line in sp.read_text(encoding="utf-8").splitlines():
            mm = _re.match(r"^(\d+)\s+(.*)", line)
            if mm:
                script_lines[int(mm.group(1))] = mm.group(2).strip()

    def show(item):
        m = TOKEN.fullmatch(item)
        if m and not (clips and int(m.group(1)) in clips.items) and int(m.group(1)) in script_lines:
            print(f"{script_lines[int(m.group(1))]}", end=" ", flush=True)
            return
        if m and clips and int(m.group(1)) in clips.items:
            cid = int(m.group(1))
            print(f"{item}({clips.text(cid)})", end=" ", flush=True)
            if speaker:
                speaker.write(clips.pcm(cid))
            return
        print(item if mode != "clips" else f"(녹음 없음: {item})", end=" ", flush=True)
        if voice:
            for pcm in voice.speak(item):
                speaker.write(pcm)
    a = cfg["agent"]
    intro = fill(getattr(brain, "opening", None) or a["opening"], cfg, customer) + (" " + a["ai_disclosure"] if a.get("ai_disclosure") else "")
    print("치과 직원/원장님 역할로 입력하세요. (빈 줄: 종료)\n")
    hello = input("👤 상대: ").strip() or "여보세요"
    from callagent.clips import split_tokens
    print("🤖 AI: ", end="")
    for item in split_tokens(intro):
        show(item)
    print()
    brain.messages += [{"role": "user", "content": hello}, {"role": "assistant", "content": intro}]
    while True:
        heard = input("👤 상대: ").strip()
        if not heard:
            break
        print("🤖 AI: ", end="", flush=True)
        for s in brain.reply(heard):
            show(s)
        if speaker:
            import time as _t
            while speaker.pending_sec() > 0:
                _t.sleep(0.05)
        print()
        if brain.handoff:
            print("   → (여기서 담당자 연결 알림이 울립니다)")
        if brain.ended:
            print("   → (AI가 통화를 마무리했습니다)")
            break


def cmd_doctor(cfg, args):
    from callagent.doctor import run
    sys.exit(1 if run(cfg, args.dial) else 0)


def cmd_phones(cfg, args):
    from callagent.doctor import setup_phones
    setup_phones(cfg.get("dialer", {}).get("adb_path", "adb"))


def cmd_profile_new(cfg, args):
    import shutil
    dst = ROOT / "profiles" / args.name
    if dst.exists():
        sys.exit(f"이미 있습니다: {dst}")
    shutil.copytree(ROOT / "profiles" / "_template", dst)
    print(f"만들었습니다 → {dst}\n"
          f"  profile.yaml : 이 용도의 첫인사, free/ai 선택\n"
          f"  playbook.md  : (ai) 내 말투와 지켜야 할 선\n"
          f"  scenarios.yaml + clips/ : (free) 녹음 상황표 — python main.py --profile {args.name} clips 녹음.mp3\n"
          f"사용: python main.py --profile {args.name} dial 01012345678 --brief \"통화 목적\"")


def cmd_dial(cfg, args):
    """고객 엑셀 없이 아무 번호에나: 곤란한 통화, 개인 용무 등. 녹취·요약은 logs/<프로필>/ 에."""
    from callagent.dialer import Dialer
    from callagent.session import CallSession, Console
    brief = args.brief
    if args.info:
        from callagent.trainer import read_script
        brief = (brief + "\n\n[내가 준 정보]\n" if brief else "") + read_script(Path(args.info))
    if brief:
        cfg["_brief"] = brief
        print(f"이번 통화 목적/정보:\n{brief[:500]}")
    coach = args.cmd == "coach" or args.coach
    who = {"_clinic": args.label or args.number or "통화", "_name": args.label or "", "_phone": args.number or ""}
    session = CallSession(cfg, load_playbook(cfg) if not coach or cfg.get("engine") == "ai" else "", who, coach=coach)
    if not coach:
        session.prepare()
    if args.number:
        Dialer(cfg).dial(args.number)
    if not coach:
        Console.ask("상대가 받으면 Enter ▶ ")
    elif args.number:
        print("상대가 받으면 직접 통화하세요. 화면에 추천 대답이 나옵니다.")
    session.run(ready_prompt=False)
    if args.number and not coach:
        from callagent.dialer import Dialer as D
        D(cfg).hang_up()
    if session.transcript:
        summary = session.brain.summarize(session.text()) if not coach else None
        if summary:
            print(f"\n결과: {summary['status']}\n메모: {summary['memo']}")
        print(f"녹취 저장: {session.save_log(summary)}")


def cmd_desktop(cfg, args):
    from callagent.installer import make_shortcut
    for m in make_shortcut():
        print(f"바탕화면에 만들었습니다: {m}")


def cmd_menu(cfg, args):
    from callagent.menu import main as menu
    menu(args.profile or "")


def cmd_list(cfg, args):
    from callagent.customers import CustomerBook
    for c in CustomerBook(cfg).all():
        print(f"{c['_row']:>4}행  {c['_clinic']:<14} {c['_name']:<6} {c['_phone']:<14} {c['_status']}")


def run_call(cfg, book, customer, playbook, dialer) -> bool:
    """한 건 통화. 계속 다음 고객으로 넘어갈지 여부를 돌려준다."""
    from callagent.session import CallSession, Console
    print("\n" + "─" * 50)
    print(f"{customer['_row']}행 | {customer['_clinic']} | {customer['_name']} | {customer['_phone']}")
    if customer["_memo"]:
        print(f"이전 메모: {customer['_memo'][:200]}")
    ans = Console.ask("전화할까요? (Enter: 걸기 / s: 건너뛰기 / q: 그만) ").strip().lower()
    if ans == "q":
        return False
    if ans == "s":
        return True
    session = CallSession(cfg, playbook, customer)
    session.prepare()  # 신호음 울리는 동안 첫인사 소리·AI 캐시를 미리 준비 → 받자마자 바로 인사
    dialer.dial(customer["_phone"])
    ans = Console.ask("상대가 받으면 Enter / 안 받으면 n + Enter ▶ ").strip().lower()
    if ans == "n":
        dialer.hang_up()
        book.record_result(customer["_row"], "부재", "전화 안 받음")
        print("→ '부재'로 기록")
        return True
    session.run(ready_prompt=False)
    dialer.hang_up()
    if not session.transcript:
        return True
    print("\n통화 요약 중...")
    summary = session.brain.summarize(session.text())
    log = session.save_log(summary)
    print(f"  결과: {summary['status']}\n  메모: {summary['memo']}")
    if summary.get("next_action"):
        print(f"  다음 할 일: {summary['next_action']} {summary.get('callback_time', '')}")
    if summary.get("needs_review"):
        print("  ⚠ AI가 확답 못 한 부분이 있어요. 녹취를 확인해 주세요.")
    print(f"  녹취 저장: {log}")
    edit = Console.ask("시트에 기록할까요? (Enter: 그대로 / 직접 쓸 메모 입력 / x: 기록 안 함) ").strip()
    if edit.lower() != "x":
        memo = edit or summary["memo"]
        if summary.get("next_action"):
            memo += f" / 다음: {summary['next_action']} {summary.get('callback_time', '')}".rstrip()
        book.record_result(customer["_row"], summary["status"], memo)
        print("→ 기록 완료")
    return True


def cmd_call(cfg, args):
    from callagent.customers import CustomerBook
    from callagent.dialer import Dialer
    book, playbook, dialer = CustomerBook(cfg), load_playbook(cfg), Dialer(cfg)
    if args.cmd == "call":
        run_call(cfg, book, book.get(args.row), playbook, dialer)
        return
    after = (args.start or 2) - 1
    while True:
        customer = book.next_pending(after)
        if not customer:
            print("더 걸 고객이 없습니다.")
            return
        after = customer["_row"]
        if not run_call(cfg, book, customer, playbook, dialer):
            return


def main():
    ap = argparse.ArgumentParser(description="치과 1차 콜 AI 대행")
    ap.add_argument("--config", help="설정 파일 (전화기 2대면 두 번째 창에서 --config config2.yaml)")
    ap.add_argument("--profile", help="용도별 프로필 (profiles/<이름>/). 예: --profile 곤란한전화")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    p = sub.add_parser("meter"); p.add_argument("--seconds", type=float, default=15); p.set_defaults(fn=cmd_meter)
    p = sub.add_parser("clone-voice"); p.add_argument("--folder", default="voice_samples"); p.set_defaults(fn=cmd_clone)
    p = sub.add_parser("clips"); p.add_argument("file", nargs="?"); p.add_argument("--noise", type=int, default=-35)
    p.add_argument("--gap", type=float, default=0.6, help="이 초 이상 쉬면 문장을 나눔"); p.set_defaults(fn=cmd_clips)
    p = sub.add_parser("say"); p.add_argument("text"); p.add_argument("--to-call", action="store_true"); p.set_defaults(fn=cmd_say)
    p = sub.add_parser("train"); p.add_argument("--folder", default="recordings"); p.set_defaults(fn=cmd_train)
    p = sub.add_parser("script"); p.add_argument("file"); p.set_defaults(fn=cmd_script)
    p = sub.add_parser("practice"); p.add_argument("--row", type=int); p.add_argument("--voice", action="store_true")
    p.add_argument("--kind", default="", help="연습할 업종 (예: 미용실, 음식점)"); p.set_defaults(fn=cmd_practice)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("doctor"); p.add_argument("--dial", default="", help="시험 전화 걸 번호 (내 다른 폰 번호)"); p.set_defaults(fn=cmd_doctor)
    sub.add_parser("phones").set_defaults(fn=cmd_phones)
    sub.add_parser("desktop").set_defaults(fn=cmd_desktop)
    sub.add_parser("menu").set_defaults(fn=cmd_menu)
    sub.add_parser("sound-test").set_defaults(fn=cmd_sound_test)
    sub.add_parser("tts-clips").set_defaults(fn=cmd_tts_clips)
    sub.add_parser("voice-setup").set_defaults(fn=cmd_voice_setup)
    p = sub.add_parser("profile-new"); p.add_argument("name"); p.set_defaults(fn=cmd_profile_new)
    for name in ("dial", "coach"):
        p = sub.add_parser(name)
        p.add_argument("number", nargs="?" if name == "coach" else None, default="", help="걸 번호 (coach 는 생략하면 지금 통화를 듣기만)")
        p.add_argument("--brief", default="", help="이번 통화 목적과 지켜야 할 선 (예: \"해지만 요청, 다른 상품 거절\")")
        p.add_argument("--info", default="", help="AI가 참고할 정보 파일 (txt/md/docx): 계약 내용, 원하는 조건, 양보 가능한 선 등")
        p.add_argument("--label", default="", help="녹취 파일에 붙일 이름 (예: 집주인)")
        p.add_argument("--coach", action="store_true", help="AI가 말하지 않고 내가 할 말만 화면에 추천")
        p.set_defaults(fn=cmd_dial)
    p = sub.add_parser("call"); p.add_argument("row", type=int); p.set_defaults(fn=cmd_call)
    p = sub.add_parser("next"); p.add_argument("--start", type=int); p.set_defaults(fn=cmd_call)
    args = ap.parse_args()
    args.fn(load_config(args.config, args.profile), args)


if __name__ == "__main__":
    main()
