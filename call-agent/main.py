"""치과 1차 콜 AI 대행 — 실행 진입점.

  python main.py devices              오디오 장치 목록
  python main.py meter                상대방 소리 크기 확인 (speech_threshold 조정용)
  python main.py clone-voice          voice_samples/ 녹음으로 내 목소리 복제
  python main.py say "안녕하세요"      복제된 내 목소리로 한 문장 들어보기
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
    from callagent.trainer import build_playbook, transcribe_folder
    folder = ROOT / args.folder
    print(f"{folder} 의 통화 녹음을 받아 적습니다.")
    transcripts = transcribe_folder(cfg, folder)
    build_playbook(cfg, transcripts, resolve(cfg["brain"].get("playbook", "playbook.md")))


def cmd_practice(cfg, args):
    """전화 없이 플레이북 테스트. 내가 상대(치과) 역할로 타이핑하면 AI가 대답."""
    from callagent.brain import Brain
    from callagent.session import fill
    customer = None
    if args.row:
        from callagent.customers import CustomerBook
        customer = CustomerBook(cfg).get(args.row)
    brain = Brain(cfg, load_playbook(cfg), customer)
    voice = speaker = None
    if args.voice:
        from callagent.audio import Speaker
        from callagent.voice import TTS_RATE, Voice
        voice, speaker = Voice(cfg), Speaker(cfg["audio"].get("monitor_output", ""), TTS_RATE)
    a = cfg["agent"]
    intro = fill(a["opening"], cfg, customer) + (" " + a["ai_disclosure"] if a.get("ai_disclosure") else "")
    print("치과 직원/원장님 역할로 입력하세요. (빈 줄: 종료)\n")
    hello = input("👤 상대: ").strip() or "여보세요"
    print(f"🤖 AI: {intro}")
    brain.messages += [{"role": "user", "content": hello}, {"role": "assistant", "content": intro}]
    while True:
        heard = input("👤 상대: ").strip()
        if not heard:
            break
        print("🤖 AI: ", end="", flush=True)
        for s in brain.reply(heard):
            print(s, end=" ", flush=True)
            if voice:
                for pcm in voice.speak(s):
                    speaker.write(pcm)
        print()
        if brain.handoff:
            print("   → (여기서 담당자 연결 알림이 울립니다)")
        if brain.ended:
            print("   → (AI가 통화를 마무리했습니다)")
            break


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
    dialer.dial(customer["_phone"])
    ans = Console.ask("상대가 받으면 Enter / 안 받으면 n + Enter ▶ ").strip().lower()
    if ans == "n":
        dialer.hang_up()
        book.record_result(customer["_row"], "부재", "전화 안 받음")
        print("→ '부재'로 기록")
        return True
    session = CallSession(cfg, playbook, customer)
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    p = sub.add_parser("meter"); p.add_argument("--seconds", type=float, default=15); p.set_defaults(fn=cmd_meter)
    p = sub.add_parser("clone-voice"); p.add_argument("--folder", default="voice_samples"); p.set_defaults(fn=cmd_clone)
    p = sub.add_parser("say"); p.add_argument("text"); p.add_argument("--to-call", action="store_true"); p.set_defaults(fn=cmd_say)
    p = sub.add_parser("train"); p.add_argument("--folder", default="recordings"); p.set_defaults(fn=cmd_train)
    p = sub.add_parser("practice"); p.add_argument("--row", type=int); p.add_argument("--voice", action="store_true"); p.set_defaults(fn=cmd_practice)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("call"); p.add_argument("row", type=int); p.set_defaults(fn=cmd_call)
    p = sub.add_parser("next"); p.add_argument("--start", type=int); p.set_defaults(fn=cmd_call)
    args = ap.parse_args()
    args.fn(load_config(), args)


if __name__ == "__main__":
    main()
