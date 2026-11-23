"""랭킹(카운트다운)형 쇼츠 템플릿.

잘 터진 '꿀템 랭킹' 쇼츠의 *구성*만 따온 틀:
  상단 고정 헤더(채널 태그 + 두 줄 제목) → 0초에 1위 장면으로 훅
  → 5위부터 1위까지 역순, 순위마다 짧은 자막 2~3개 → 마지막 1위는 길게 + 행동 유도.
영상/사진은 직접 찍었거나 허락받은 것, 또는 직접 만든 그림만 넣는다.

spec(JSON) 예:
{
  "tag": "⭐ 쇼핑 쇼츠", "title": ["집들이 가면 꼭 물어보는", "귀여운 살림템 랭킹"],
  "hook": {"media": "1.png", "captions": ["집들이 가면 다들 어디서 샀냐고 묻는 살림템"]},
  "items": [{"rank": 5, "name": "참새 티 인퓨저", "media": "5.png",
             "captions": ["5위는 참새 티 인퓨저임", "..."], "audio": "옵션: 내레이션 mp3"}],
  "bgm": true
}
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import bgm, render

W, H = render.W, render.H
CAP_SEC = 1.9          # 음성 없을 때 자막 하나당 시간
HOOK_TOP, MEDIA_BOX = 360, (60, 400, 1020, 1360)


def _header(d: ImageDraw.ImageDraw, tag: str, title: list[str]):
    d.rectangle([0, 0, W, 340], fill=(18, 18, 22))
    tf = render._font(34, "ko")
    star = tag.startswith("⭐")
    tag = tag.lstrip("⭐ ").strip()
    pad = 52 if star else 0   # 폰트에 이모지가 없어서 별은 직접 그림
    d.rounded_rectangle([40, 34, 104 + pad + d.textlength(tag, font=tf), 90], 26, fill=(255, 204, 0))
    if star:
        import math
        cx, cy, R, r = 86, 62, 21, 9
        pts = [(cx + (R if i % 2 == 0 else r) * math.sin(i * math.pi / 5),
                cy - (R if i % 2 == 0 else r) * math.cos(i * math.pi / 5)) for i in range(10)]
        d.polygon(pts, fill=(230, 40, 40))
    d.text((64 + pad, 40), tag, font=tf, fill=(18, 18, 22))
    f = render._font(66, "ko")
    for i, line in enumerate(title[:2]):
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, 120 + i * 96), line, font=f,
               fill=(255, 255, 255) if i == 0 else (255, 214, 0), stroke_width=3, stroke_fill=(0, 0, 0))


def _frame_png(tag, title, rank, caption, out: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _header(d, tag, title)
    if rank:
        bf = render._font(84, "ko")
        txt = f"{rank}위"
        bw = d.textlength(txt, font=bf) + 70
        d.rounded_rectangle([50, 430, 50 + bw, 560], 30, fill=(255, 64, 64))
        d.text((85, 438), txt, font=bf, fill="white", stroke_width=3, stroke_fill=(120, 0, 0))
    cf = render._font(68, "ko")
    lines = render._wrap(d, caption, cf, W - 140)
    y = 1500
    for line in lines:
        w = d.textlength(line, font=cf)
        d.text(((W - w) / 2, y), line, font=cf, fill="white", stroke_width=8, stroke_fill=(0, 0, 0))
        y += 90
    img.save(out)
    return out


def _clip(media: Path, overlay: Path, dur: float, punch: bool, audio: Path | None, out: Path):
    is_vid = media.suffix.lower() in render.VIDEO_EXT
    src = (["-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", str(media)] if is_vid
           else ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(media)])
    bw, bh = MEDIA_BOX[2] - MEDIA_BOX[0], MEDIA_BOX[3] - MEDIA_BOX[1]
    # 순위 바뀔 때 살짝 튀어나오는 줌(punch-in) + 천천히 확대
    z = "1.10-0.10*min(t/0.25\\,1)+0.03*t/{d}".format(d=dur) if punch else "1+0.03*t/{d}".format(d=dur)
    fc = (
        f"color=c=0x2a2a30:s={W}x{H}:d={dur:.3f}:r=30[bg];"
        f"[0:v]fps=30,scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
        f"scale=w='trunc(iw*({z})/2)*2':h='trunc(ih*({z})/2)*2':eval=frame,"
        f"crop={bw}:{bh},setsar=1[fg];"
        f"[bg][fg]overlay={MEDIA_BOX[0]}:{MEDIA_BOX[1]}:shortest=1[b];"
        f"[b][1:v]overlay=0:0,format=yuv420p[v]"
    )
    aud = (["-i", str(audio)] if audio else
           ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo"])
    render.run(["ffmpeg", "-y", *src, "-i", str(overlay), *aud, "-filter_complex", fc,
                "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}", "-r", "30",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out)])


def build(spec_path: Path, out: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    root = spec_path.parent
    work = out.parent / "_cd_work"
    work.mkdir(parents=True, exist_ok=True)
    tag, title = spec.get("tag", "⭐ 쇼핑 쇼츠"), spec["title"]
    scenes = [dict(spec["hook"], rank=None)] + spec["items"]
    clips, ding_at, t = [], [], 0.0
    for si, sc in enumerate(scenes):
        media = root / sc["media"]
        audio = root / sc["audio"] if sc.get("audio") else None
        caps = sc["captions"]
        if audio:   # 음성 길이를 자막 글자수 비율로 나눔
            total = render.duration(audio) + 0.2
            weights = [max(len(c), 1) for c in caps]
            durs = [total * w / sum(weights) for w in weights]
        else:
            durs = [CAP_SEC + (0.6 if sc.get("rank") == 1 and i == len(caps) - 1 else 0) for i in range(len(caps))]
        if sc.get("rank"):
            ding_at.append(t)
        for ci, (cap, du) in enumerate(zip(caps, durs)):
            ov = _frame_png(tag, title, sc.get("rank"), cap, work / f"o{si}_{ci}.png")
            a = None
            if audio:   # 문장별 오디오 조각
                a = work / f"a{si}_{ci}.m4a"
                st = sum(durs[:ci])
                render.run(["ffmpeg", "-y", "-ss", f"{st:.3f}", "-t", f"{du:.3f}", "-i", str(audio),
                            "-c:a", "aac", str(a)])
            c = work / f"c{si}_{ci}.mp4"
            _clip(media, ov, du, ci == 0 and si > 0, a, c)
            clips.append(c)
            t += du
    body = render.concat(clips, work / "body.mp4")
    if spec.get("bgm", True):
        music = bgm.make_bgm(work / "bgm.wav", t)
        ding = bgm.make_ding(work / "ding.wav")
        inputs = ["-i", str(body), "-i", str(music)]
        has_voice = any(sc.get("audio") for sc in scenes)
        parts = [f"[1:a]volume={0.2 if has_voice else 0.6}[m]"]  # 내레이션 있으면 음악을 낮춤
        mixes = "[0:a][m]"
        for k, at in enumerate(ding_at):
            inputs += ["-i", str(ding)]
            parts.append(f"[{k + 2}:a]adelay={int(at * 1000)}|{int(at * 1000)},volume=0.5[d{k}]")
            mixes += f"[d{k}]"
        fc = ";".join(parts) + f";{mixes}amix=inputs={2 + len(ding_at)}:normalize=0:duration=first[a]"
        render.run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
    else:
        shutil.copy(body, out)
    shutil.rmtree(work, ignore_errors=True)
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
