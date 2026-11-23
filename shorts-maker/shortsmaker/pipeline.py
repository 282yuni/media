"""상품 소스 → 대본 → 음성 → 영상 4종 + 업로드용 글."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from . import render, tts
from .script import Variant, write_scripts

ALL_KEYS = ["ko_youtube", "ko_instagram", "ja_youtube", "ja_instagram"]
LABEL = {
    "ko_youtube": "한국 유튜브", "ko_instagram": "한국 인스타",
    "ja_youtube": "일본 유튜브", "ja_instagram": "일본 인스타",
}
DISCLOSURE = {
    "ko": "이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
    "ja": "※本投稿はアフィリエイト広告を利用しています。",
}


def _upload_text(v: Variant, link: str) -> str:
    lang = v.key[:2]
    parts = [v.title, "", v.description]
    if link:
        parts += ["", ("👉 상품 보기: " if lang == "ko" else "👉 商品はこちら: ") + link]
    parts += ["", DISCLOSURE[lang], "", " ".join(v.hashtags)]
    return "\n".join(parts)


def make_variant(v: Variant, media: list[Path], workdir: Path, outdir: Path, link: str) -> Path:
    lang = v.key[:2]
    vdir = workdir / v.key
    vdir.mkdir(parents=True, exist_ok=True)
    segs, offsets = [], {m: 0.0 for m in media}
    for i, line in enumerate(v.lines):
        audio = tts.speak(line, v.key, vdir / f"a{i}.mp3")
        dur = render.duration(audio) + 0.25
        m = media[i % len(media)]
        over = render.overlay_png(v.overlay_title, line, lang, vdir / f"o{i}.png")
        segs.append(render.segment(m, offsets[m], dur, over, audio, vdir / f"s{i}.mp4"))
        if m.suffix.lower() in render.VIDEO_EXT:
            total = render.duration(m)
            offsets[m] = (offsets[m] + dur) % max(total, 0.1)
    out = outdir / f"{v.key}.mp4"
    render.concat(segs, out)
    (outdir / f"{v.key}.txt").write_text(_upload_text(v, link), encoding="utf-8")
    return out


def make_all(product: str, notes: str, media: list[Path], outdir: Path,
             keys: list[str] | None = None, link: str = "",
             log: Callable[[str], None] = print) -> list[Path]:
    keys = keys or ALL_KEYS
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "_work"
    work.mkdir(exist_ok=True)
    try:
        log("상품 장면 분석 중…")
        frames = render.frames_for_ai(media, work)
        log("Claude가 대본 작성 중…")
        variants = write_scripts(product, notes, frames, keys)
        (outdir / "scripts.json").write_text(
            json.dumps([v.model_dump() for v in variants], ensure_ascii=False, indent=2), encoding="utf-8")
        results = []
        for v in variants:
            log(f"{LABEL[v.key]} 영상 만드는 중… (음성: {tts.engine()})")
            results.append(make_variant(v, media, work, outdir, link))
        log("완료!")
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)
