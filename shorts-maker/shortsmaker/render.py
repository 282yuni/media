"""ffmpeg + Pillow로 1080x1920 세로 쇼츠를 만든다."""
from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/YuGothB.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]


def _font(size: int, lang: str) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            # Noto CJK .ttc: index 0=JP, 1=KR, 2=SC ... 한국어는 KR 글리프 사용
            idx = 1 if (path.endswith(".ttc") and "Noto" in path and lang == "ko") else 0
            return ImageFont.truetype(path, size, index=idx)
    raise RuntimeError("한글/일본어 폰트를 찾지 못했습니다. Noto Sans CJK를 설치해 주세요.")


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg 실패:\n" + p.stderr[-1500:])


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) > max_w and cur:
            # 공백에서 끊을 수 있으면 공백 기준으로
            if " " in cur:
                head, tail = cur.rsplit(" ", 1)
                lines.append(head)
                cur = tail + ch
            else:
                lines.append(cur)
                cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return [l.strip() for l in lines]


def overlay_png(title: str, caption: str, lang: str, out: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 상단 제목 띠
    tf = _font(76, lang)
    t_lines = _wrap(d, title, tf, W - 120)
    y = 170
    box_h = len(t_lines) * 96 + 50
    d.rounded_rectangle([40, y - 25, W - 40, y - 25 + box_h], radius=28, fill=(0, 0, 0, 170))
    for line in t_lines:
        w = d.textlength(line, font=tf)
        d.text(((W - w) / 2, y), line, font=tf, fill=(255, 222, 0), stroke_width=4, stroke_fill=(0, 0, 0))
        y += 96

    # 하단 자막
    cf = _font(70, lang)
    c_lines = _wrap(d, caption, cf, W - 140)
    y = 1380
    for line in c_lines:
        w = d.textlength(line, font=cf)
        d.text(((W - w) / 2, y), line, font=cf, fill=(255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0))
        y += 92
    img.save(out)
    return out


def segment(media: Path, start: float, dur: float, overlay: Path, audio: Path, out: Path) -> Path:
    """배경(흐린 꽉찬 화면) + 원본(가운데 맞춤) + 글자 + 음성 = 한 문장 구간."""
    if media.suffix.lower() in VIDEO_EXT:
        src = ["-stream_loop", "-1", "-ss", f"{start:.2f}", "-t", f"{dur:.3f}", "-i", str(media)]
    else:
        src = ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(media)]
    zoom = "scale=w='iw*(1+0.04*t/{d})':h='ih*(1+0.04*t/{d})':eval=frame,".format(d=max(dur, 0.1))
    fc = (
        f"[0:v]fps=30,split[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.15[bg];"
        f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,{zoom}setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[base];"
        f"[base][1:v]overlay=0:0,format=yuv420p[v]"
    )
    run([
        "ffmpeg", "-y", *src, "-i", str(overlay), "-i", str(audio),
        "-filter_complex", fc, "-map", "[v]", "-map", "2:a",
        "-t", f"{dur:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out),
    ])
    return out


def concat(segments: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])
    lst.unlink()
    return out


def frames_for_ai(media: list[Path], workdir: Path) -> list[Path]:
    """Claude가 상품을 볼 수 있게 영상에서 장면 몇 장을 뽑는다."""
    shots = []
    for i, m in enumerate(media):
        if m.suffix.lower() in VIDEO_EXT:
            d = duration(m)
            for j, frac in enumerate((0.15, 0.5, 0.85)):
                f = workdir / f"frame_{i}_{j}.jpg"
                run(["ffmpeg", "-y", "-ss", f"{d * frac:.2f}", "-i", str(m), "-frames:v", "1",
                     "-vf", "scale=768:-2", str(f)])
                shots.append(f)
        else:
            f = workdir / f"frame_{i}.jpg"
            Image.open(m).convert("RGB").resize((768, int(768 * Image.open(m).height / Image.open(m).width))).save(f)
            shots.append(f)
    return shots[:6]
