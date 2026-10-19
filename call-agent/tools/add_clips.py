"""새로 녹음한 문장을 밝게 다듬어서 녹음 묶음 ZIP 에 넣기/바꾸기 (개발용 도구, ffmpeg 필요).

사용자가 보낸 녹음(m4a/mp3)에서 문장을 잘라 → 다듬기(아래 CHAIN) → clip_###.wav 로 만들고,
기존 완성녹음 ZIP 에 추가하거나 같은 번호를 교체해서 새 ZIP 을 만든다.
글(text)은 profiles/<프로필>/녹음대본.txt 의 같은 번호 줄에서 가져온다.

  # 1) 문장 위치 확인 (자동으로 자른 구간 + 받아쓰기)
  python tools/add_clips.py segments 새녹음.m4a
  # 2) 번호=시작-끝(초) 로 넣기. 같은 문장을 여러 번 읽었으면 마지막 것을 고른다
  python tools/add_clips.py add 에셜론_완성녹음.zip 새녹음.m4a 41=1.2-5.8 42=7.0-12.4 -o 새_완성녹음.zip
  # 여러 조각을 이어 붙이기: 39=16.0-17.25+9.7-15.0 (사이 0.25초 쉼)
"""
import argparse
import re
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 다듬기: 저음 정리 → 잡음 제거 → 웅웅거림 줄이고 또렷함·밝음 올리기 → 압축(음량 고르게)
#         → 음높이 +4.5% (목소리는 그대로, 살짝 밝게) → 음량 맞추기 → 24kHz
CHAIN = ("highpass=f=100,afftdn=nf=-28:tn=1,equalizer=f=250:t=q:w=1:g=-3.5,equalizer=f=1800:t=q:w=1.5:g=1.5,"
         "equalizer=f=3200:t=q:w=1.2:g=4.5,treble=g=3.5:f=8500,"
         "acompressor=threshold=-22dB:ratio=3:attack=5:release=90:makeup=2,"
         "asetrate=48000*1.045,aresample=48000,atempo=0.99,loudnorm=I=-16:TP=-1.5:LRA=7,aresample=24000")


def script_texts(profile: str) -> dict[int, str]:
    out = {}
    p = ROOT / "profiles" / profile / "녹음대본.txt"
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\s+(.*?)(\s{2,}\(.*\))?$", line.rstrip())
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def cmd_segments(args):
    from callagent.clips import decode, find_segments
    pcm = decode(Path(args.src), 16000)
    ears = None
    try:
        from callagent.local_stt import LocalEars
        ears = LocalEars({"stt": {"local_engine": "sherpa", "model_dir": "models/ko"}})
    except Exception as e:
        print(f"(받아쓰기 없이 구간만: {e})")
    for i, (s, e) in enumerate(find_segments(Path(args.src)), 1):
        text = ears.transcribe_pcm(pcm[int(s * 16000):int(e * 16000)], 16000) if ears else ""
        print(f"{i:3}  {s:7.2f}-{e:7.2f}  {text}")


def polish(pcm48: np.ndarray, out: Path) -> None:
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "raw.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(pcm48.tobytes())
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-af", CHAIN,
                        "-ac", "1", "-sample_fmt", "s16", str(out)], check=True)


def cmd_add(args):
    from callagent.clips import decode
    src = decode(Path(args.src), 48000)
    texts = script_texts(args.profile)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        with zipfile.ZipFile(args.zip) as z:
            for n in z.namelist():
                base = Path(n).name
                if base.endswith(".wav") or base == "clips.yaml":
                    (d / base).write_bytes(z.read(n))
        items = yaml.safe_load((d / "clips.yaml").read_text(encoding="utf-8")) or []
        by_id = {it["id"]: it for it in items}
        for spec in args.parts:
            cid, ranges = spec.split("=", 1)
            cid = int(cid)
            pieces = []
            for r in ranges.split("+"):
                s, e = (float(x) for x in r.split("-"))
                pieces += [src[int(s * 48000):int(e * 48000)], np.zeros(int(0.25 * 48000), np.int16)]
            fname = f"clip_{cid:03}.wav"
            polish(np.concatenate(pieces[:-1]), d / fname)
            if cid not in texts:
                print(f"⚠ {cid}번이 녹음대본.txt 에 없습니다. 대본에 먼저 적어 주세요.")
            by_id[cid] = {"id": cid, "file": fname, "text": texts.get(cid, ""), "use": True, "source": "내 녹음 (다듬음)"}
            print(f"{cid:3}번 ← {ranges}   {texts.get(cid, '')}")
        items = [by_id[k] for k in sorted(by_id)]
        (d / "clips.yaml").write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
            for it in items:
                z.write(d / it["file"], it["file"])
            z.write(d / "clips.yaml", "clips.yaml")
    print(f"\n완성: {args.out}  (문장 {len(items)}개)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("segments"); p.add_argument("src"); p.set_defaults(fn=cmd_segments)
    p = sub.add_parser("add"); p.add_argument("zip"); p.add_argument("src"); p.add_argument("parts", nargs="+")
    p.add_argument("-o", "--out", required=True); p.add_argument("--profile", default="에셜론")
    p.set_defaults(fn=cmd_add)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
