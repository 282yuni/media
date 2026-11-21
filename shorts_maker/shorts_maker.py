#!/usr/bin/env python3
"""
쇼츠 메이커 — 내가 찍은 영상을 Claude가 쇼츠로 편집해 주는 도구.

흐름
  1) 음성 인식 (faster-whisper)       : 영상 → 대사와 시간
  2) 장면 추출 (ffmpeg)               : 몇 초마다 한 장씩 사진
  3) Claude 편집 계획                  : 재밌는 구간 고르기, 순서 정하기, 제목·자막·일본어 번역·해시태그
  4) 숨 고르는 구간 자르기 (silencedetect)
  5) 렌더링 (ffmpeg + libass)          : 9:16 변환, 상단 제목, 자막 입히기 → 한국어/일본어 버전

본인이 찍었거나 사용 권리가 있는 영상에만 쓰세요. 링크(URL) 입력은 받지 않습니다.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"
W, H = 1080, 1920


# ─────────────────────────── Claude 응답 형식 ───────────────────────────
class Segment(BaseModel):
    start: float = Field(description="원본 영상 기준 시작 초")
    end: float = Field(description="원본 영상 기준 끝 초")


class Cue(BaseModel):
    start: float = Field(description="원본 영상 기준 자막 시작 초")
    end: float = Field(description="원본 영상 기준 자막 끝 초")
    ko: str = Field(description="한국어 자막 (한 줄 18자 안팎, 최대 2줄)")
    ja: str = Field(description="자연스러운 일본어 자막")


class Short(BaseModel):
    title_ko: str = Field(description="유튜브 업로드 제목 (한국어, 40자 이내)")
    title_ja: str = Field(description="유튜브 업로드 제목 (일본어)")
    hook_ko: str = Field(description="영상 상단에 계속 떠 있는 짧은 문구 (한국어, 2줄 이내)")
    hook_ja: str = Field(description="영상 상단 문구 (일본어)")
    segments: List[Segment] = Field(description="이어 붙일 구간들. 재생 순서대로. 첫 구간은 가장 강한 장면(훅)")
    cues: List[Cue] = Field(description="segments 안에 들어가는 대사 자막. 원본 시간 기준")
    hashtags: List[str]
    description_ko: str = Field(description="유튜브 설명란 (2~3문장)")
    why: str = Field(description="이 구간을 고른 이유 한 줄")


class Style(BaseModel):
    font_size: int = Field(description="자막 글자 크기(px, 1080x1920 기준). 보통 64~90")
    text_color: str = Field(description="자막 글자색 #RRGGBB")
    outline_color: str = Field(description="글자 테두리 또는 배경 상자 색 #RRGGBB")
    boxed: bool = Field(description="true면 글자 뒤에 상자 배경, false면 테두리만")
    position: Literal["middle", "lower", "bottom"] = Field(description="자막 세로 위치")
    title_size: int = Field(description="상단 문구 글자 크기(px). 보통 72~100")
    title_color: str = Field(description="상단 문구 글자색 #RRGGBB")
    title_bg: str = Field(description="상단 문구 배경 상자 색 #RRGGBB")


class Plan(BaseModel):
    shorts: List[Short]
    style: Style


DEFAULT_STYLE = Style(font_size=76, text_color="#FFFFFF", outline_color="#000000", boxed=False,
                      position="lower", title_size=86, title_color="#000000", title_bg="#FFE14D")

SYSTEM = """당신은 한국 유튜브 쇼츠 전문 편집자입니다. 사용자가 직접 찍은 영상의 대사(시간 포함)와 장면 사진을 받아 쇼츠 편집 계획을 세웁니다.

원칙
- 첫 1~2초 안에 가장 강하거나 궁금증을 부르는 장면이 나오게 순서를 정하세요. 필요하면 뒤 장면을 맨 앞으로 끌어와도 됩니다.
- 각 쇼츠 길이는 지정된 최대 길이 이하. 구간 경계는 말이 끊기지 않는 곳으로.
- 자막은 실제 대사를 다듬은 것이어야 합니다. 없는 말을 지어내지 마세요. 오타·말더듬만 정리하세요.
- 대사가 없는 영상이면 cues는 비워 두고, 장면 사진을 보고 상단 문구로 상황을 설명하세요.
- 제목과 상단 문구는 과장·낚시 없이, 영상 내용 그대로 궁금하게.
- 일본어는 직역이 아니라 일본 시청자가 자연스럽게 읽는 표현으로.
- 사용자가 스타일 요청을 주면 style에 반영하고, 없으면 흰 글자+검은 테두리, 노란 상단 띠를 기본으로 하세요."""


# ─────────────────────────── 유틸 ───────────────────────────
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
               "-of", "json", str(path)]).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    has_audio = any(s["codec_type"] == "audio" for s in j["streams"])
    if not v:
        sys.exit("영상 스트림이 없는 파일이에요.")
    return {"duration": float(j["format"]["duration"]), "w": v["width"], "h": v["height"], "audio": has_audio}


def say(msg: str) -> None:
    print(f"• {msg}", flush=True)


# ─────────────────────────── 1. 음성 인식 ───────────────────────────
def transcribe(video: Path, model_size: str, lang: str) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper가 없어요: pip install faster-whisper")
    say(f"음성 인식 중 (whisper {model_size}) — 처음 실행 때는 모델을 내려받느라 오래 걸려요")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segs, _ = model.transcribe(str(video), language=lang, vad_filter=True)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]


# ─────────────────────────── 2. 장면 사진 ───────────────────────────
def keyframes(video: Path, duration: float, workdir: Path, max_frames: int = 16) -> list[tuple[float, str]]:
    step = max(1.0, duration / max_frames)
    frames = []
    t = step / 2
    while t < duration and len(frames) < max_frames:
        out = workdir / f"f{len(frames):02d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=512:-2", "-q:v", "5", str(out)], check=False)
        if out.exists():
            frames.append((round(t, 1), base64.standard_b64encode(out.read_bytes()).decode()))
        t += step
    return frames


# ─────────────────────────── 3. Claude 편집 계획 ───────────────────────────
def plan_with_claude(transcript: list[dict], frames: list[tuple[float, str]], duration: float,
                     count: int, max_sec: int, style_req: str, note: str) -> Plan:
    import anthropic

    client = anthropic.Anthropic()
    content: list[dict] = []
    for t, b64 in frames:
        content.append({"type": "text", "text": f"[장면 {t}초]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    lines = "\n".join(f"[{s['start']:.2f}–{s['end']:.2f}] {s['text']}" for s in transcript) or "(대사 없음)"
    content.append({"type": "text", "text": (
        f"원본 길이: {duration:.1f}초\n만들 쇼츠 개수: {count}\n쇼츠 최대 길이: {max_sec}초\n"
        f"스타일 요청: {style_req or '(없음)'}\n추가 요청: {note or '(없음)'}\n\n대사:\n{lines}")})

    say(f"Claude가 편집 계획을 세우는 중 ({MODEL})")
    try:
        resp = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
            output_format=Plan,
        )
    except anthropic.AuthenticationError:
        sys.exit("Claude API 키가 없거나 틀렸어요. ANTHROPIC_API_KEY 환경 변수를 확인해 주세요.")
    except anthropic.RateLimitError:
        sys.exit("요청이 너무 많아요. 잠시 뒤 다시 실행해 주세요.")
    except anthropic.APIStatusError as e:
        sys.exit(f"Claude API 오류 ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("Claude API에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
    if resp.stop_reason == "refusal":
        sys.exit("Claude가 이 영상의 편집을 거절했어요.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        sys.exit("Claude 응답이 중간에 끊겼어요. --count를 줄여 다시 실행해 주세요.")
    return resp.parsed_output


# ─────────────────────────── 4. 숨 고르는 구간 자르기 ───────────────────────────
def silences(video: Path, min_gap: float, noise_db: int) -> list[tuple[float, float]]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_gap}", "-f", "null", "-"],
                       text=True, capture_output=True)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


def tighten(segments: list[Segment], gaps: list[tuple[float, float]], pad: float = 0.12) -> list[tuple[float, float]]:
    """각 구간에서 긴 침묵을 빼고 남은 조각들을 순서대로 돌려준다."""
    out = []
    for seg in segments:
        pieces = [(seg.start, seg.end)]
        for gs, ge in gaps:
            cut_s, cut_e = gs + pad, ge - pad
            if cut_e - cut_s <= 0:
                continue
            nxt = []
            for a, b in pieces:
                if cut_e <= a or cut_s >= b:
                    nxt.append((a, b))
                    continue
                if cut_s > a:
                    nxt.append((a, cut_s))
                if cut_e < b:
                    nxt.append((cut_e, b))
            pieces = nxt
        out.extend((a, b) for a, b in pieces if b - a >= 0.25)
    return out


def remap(t0: float, t1: float, pieces: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """원본 시간 구간을 편집본 시간으로 옮긴다 (잘린 부분은 빠짐)."""
    res, offset = [], 0.0
    for a, b in pieces:
        s, e = max(t0, a), min(t1, b)
        if e > s:
            res.append((offset + s - a, offset + e - a))
        offset += b - a
    return res


# ─────────────────────────── 5. 렌더링 ───────────────────────────
def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_text(s: str) -> str:
    return s.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(style: Style, hook: str, cues: list[tuple[float, float, str]], total: float, font: str,
              channel: str) -> str:
    margin_v = {"middle": 760, "lower": 520, "bottom": 260}[style.position]
    sub_border = 3 if style.boxed else 1
    sub_back = ass_color(style.outline_color, 0x30)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Sub,{font},{style.font_size},{ass_color(style.text_color)},&H000000FF,"
        f"{ass_color(style.outline_color)},{sub_back},-1,0,0,0,100,100,0,0,{sub_border},"
        f"{6 if not style.boxed else 14},0,2,80,80,{margin_v},1",
        f"Style: Title,{font},{style.title_size},{ass_color(style.title_color)},&H000000FF,"
        f"{ass_color(style.title_bg)},{ass_color(style.title_bg)},-1,0,0,0,100,100,0,0,3,18,0,8,70,70,190,1",
        f"Style: Credit,{font},40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,40,40,70,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook.strip():
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,{ass_text(hook)}")
    if channel.strip():
        lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Credit,,0,0,0,,{ass_text(channel)}")
    for s, e, text in cues:
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Sub,,0,0,0,,{ass_text(text)}")
    return "\n".join(lines) + "\n"


def render(video: Path, info: dict, pieces: list[tuple[float, float]], ass_path: Path, out: Path) -> None:
    parts, n = [], len(pieces)
    for i, (a, b) in enumerate(pieces):
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if info["audio"]:
            parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    if info["audio"]:
        parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]")
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cv]")

    src_ratio = info["w"] / info["h"]
    if src_ratio > (W / H) * 1.05:  # 가로 영상 → 흐린 배경 위에 원본을 가운데
        parts.append("[cv]split[bg][fg]")
        parts.append(f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2[bgb]")
        parts.append(f"[fg]scale={W}:-2[fgs]")
        parts.append("[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base]")
    else:  # 세로·정사각 → 꽉 채워 자르기
        parts.append(f"[cv]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[base]")
    ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    parts.append(f"[base]setsar=1,ass='{ass_arg}'[outv]")

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-filter_complex", ";".join(parts), "-map", "[outv]"]
    if info["audio"]:
        cmd += ["-map", "[ca]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
            "-movflags", "+faststart", str(out)]
    try:
        run(cmd)
    except subprocess.CalledProcessError as e:
        sys.exit(f"렌더링 실패:\n{e.stderr[-1500:]}")


# ─────────────────────────── 실행 ───────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="내가 찍은 영상을 Claude가 쇼츠로 편집합니다.")
    ap.add_argument("video", help="내 영상 파일 경로 (mp4, mov 등)")
    ap.add_argument("--count", type=int, default=1, help="만들 쇼츠 개수 (기본 1)")
    ap.add_argument("--max-sec", type=int, default=59, help="쇼츠 최대 길이 초 (기본 59)")
    ap.add_argument("--style", default="", help='자막 스타일 요청. 예: "검정 배경에 하얀 글자, 화면 가운데"')
    ap.add_argument("--note", default="", help='편집 요청. 예: "개구리가 넘어지는 장면을 맨 앞에"')
    ap.add_argument("--channel", default="", help="화면 아래 작게 넣을 채널명")
    ap.add_argument("--langs", default="ko,ja", help="만들 자막 언어 (기본 ko,ja)")
    ap.add_argument("--whisper", default="small", help="음성 인식 모델 크기: tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", default="ko", help="영상 속 말의 언어 (기본 ko)")
    ap.add_argument("--no-trim", action="store_true", help="숨 고르는 구간을 자르지 않음")
    ap.add_argument("--transcript", help="이미 있는 대사 JSON 사용 (음성 인식 건너뜀)")
    ap.add_argument("--plan", help="저장된 편집 계획 JSON으로 다시 렌더링 (Claude 호출 안 함)")
    ap.add_argument("--font", default="Noto Sans CJK KR", help="자막 글꼴 이름")
    ap.add_argument("--out", default="shorts_out", help="결과 폴더")
    a = ap.parse_args()

    if re.match(r"^[a-z]+://", a.video):
        sys.exit("링크는 받지 않아요. 직접 찍었거나 사용 권리가 있는 영상 파일을 넣어 주세요.")
    video = Path(a.video)
    if not video.exists():
        sys.exit(f"파일을 찾을 수 없어요: {video}")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool}이 설치돼 있지 않아요.")
    langs = [l.strip() for l in a.langs.split(",") if l.strip() in ("ko", "ja")] or ["ko"]
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video.stem
    info = probe(video)
    say(f"원본: {info['w']}x{info['h']}, {info['duration']:.1f}초")

    if a.plan:
        plan = Plan.model_validate_json(Path(a.plan).read_text(encoding="utf-8"))
        say(f"저장된 계획 사용: {a.plan}")
    else:
        tpath = out_dir / f"{stem}.transcript.json"
        if a.transcript:
            transcript = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
        elif tpath.exists():
            transcript = json.loads(tpath.read_text(encoding="utf-8"))
            say(f"이전 음성 인식 결과 재사용: {tpath}")
        else:
            transcript = transcribe(video, a.whisper, a.lang) if info["audio"] else []
            tpath.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            frames = keyframes(video, info["duration"], Path(td))
        plan = plan_with_claude(transcript, frames, info["duration"], a.count, a.max_sec, a.style, a.note)
        (out_dir / f"{stem}.plan.json").write_text(plan.model_dump_json(indent=1), encoding="utf-8")
        say(f"편집 계획 저장: {out_dir / (stem + '.plan.json')}  (고쳐서 --plan 으로 다시 렌더링 가능)")

    gaps = [] if a.no_trim or not info["audio"] else silences(video, 0.45, -35)
    notes = []
    for i, sh in enumerate(plan.shorts, 1):
        segs = [Segment(start=max(0, s.start), end=min(info["duration"], s.end)) for s in sh.segments if s.end > s.start]
        pieces = tighten(segs, gaps) if gaps else [(s.start, s.end) for s in segs]
        if not pieces:
            say(f"{i}번 쇼츠: 남은 구간이 없어 건너뜀")
            continue
        total = sum(b - a for a, b in pieces)
        if total > a.max_sec + 0.5:  # 길이 초과분은 뒤에서 자르기
            keep, acc = [], 0.0
            for p0, p1 in pieces:
                if acc + (p1 - p0) > a.max_sec:
                    keep.append((p0, p0 + (a.max_sec - acc)))
                    break
                keep.append((p0, p1))
                acc += p1 - p0
            pieces, total = keep, float(a.max_sec)
        for lang in langs:
            cues = []
            for c in sh.cues:
                for s, e in remap(c.start, c.end, pieces):
                    if e - s >= 0.2:
                        cues.append((s, e, c.ko if lang == "ko" else c.ja))
            hook = sh.hook_ko if lang == "ko" else sh.hook_ja
            out = out_dir / f"{stem}_{i}_{lang}.mp4"
            with tempfile.NamedTemporaryFile("w", suffix=".ass", delete=False, encoding="utf-8") as f:
                f.write(build_ass(plan.style, hook, cues, total, a.font, a.channel))
                ass_path = Path(f.name)
            say(f"{i}번 쇼츠 [{lang}] 렌더링 중 ({total:.1f}초, 조각 {len(pieces)}개)")
            try:
                render(video, info, pieces, ass_path, out)
            finally:
                os.unlink(ass_path)
            say(f"완성: {out}")
        notes.append(
            f"■ {i}번 쇼츠\n[한국어 제목] {sh.title_ko}\n[일본어 제목] {sh.title_ja}\n"
            f"[설명] {sh.description_ko}\n[해시태그] {' '.join('#' + h.lstrip('#') for h in sh.hashtags)}\n"
            f"[고른 이유] {sh.why}\n")
    up = out_dir / f"{stem}.upload.txt"
    up.write_text("\n".join(notes), encoding="utf-8")
    say(f"업로드용 제목·설명: {up}")


if __name__ == "__main__":
    main()
