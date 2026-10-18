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

    def show(item):
        m = TOKEN.fullmatch(item)
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
    intro = fill(a["opening"], cfg, customer) + (" " + a["ai_disclosure"] if a.get("ai_disclosure") else "")
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    p = sub.add_parser("meter"); p.add_argument("--seconds", type=float, default=15); p.set_defaults(fn=cmd_meter)
    p = sub.add_parser("clone-voice"); p.add_argument("--folder", default="voice_samples"); p.set_defaults(fn=cmd_clone)
    p = sub.add_parser("clips"); p.add_argument("file", nargs="?"); p.add_argument("--noise", type=int, default=-35)
    p.add_argument("--gap", type=float, default=0.6, help="이 초 이상 쉬면 문장을 나눔"); p.set_defaults(fn=cmd_clips)
    p = sub.add_parser("say"); p.add_argument("text"); p.add_argument("--to-call", action="store_true"); p.set_defaults(fn=cmd_say)
    p = sub.add_parser("train"); p.add_argument("--folder", default="recordings"); p.set_defaults(fn=cmd_train)
    p = sub.add_parser("script"); p.add_argument("file"); p.set_defaults(fn=cmd_script)
    p = sub.add_parser("practice"); p.add_argument("--row", type=int); p.add_argument("--voice", action="store_true"); p.set_defaults(fn=cmd_practice)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("doctor"); p.add_argument("--dial", default="", help="시험 전화 걸 번호 (내 다른 폰 번호)"); p.set_defaults(fn=cmd_doctor)
    sub.add_parser("phones").set_defaults(fn=cmd_phones)
    p = sub.add_parser("call"); p.add_argument("row", type=int); p.set_defaults(fn=cmd_call)
    p = sub.add_parser("next"); p.add_argument("--start", type=int); p.set_defaults(fn=cmd_call)
    args = ap.parse_args()
    args.fn(load_config(args.config), args)


if __name__ == "__main__":
    main()
