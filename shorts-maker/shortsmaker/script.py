"""Claude로 쇼핑 쇼츠 대본을 만든다 (한국어/일본어 × 유튜브/인스타 4종)."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import List

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"


class Variant(BaseModel):
    key: str = Field(description="ko_youtube | ko_instagram | ja_youtube | ja_instagram 중 하나")
    title: str = Field(description="업로드 제목. 40자 이내, 호기심을 끄는 문장")
    overlay_title: str = Field(description="영상 상단에 계속 떠 있을 짧은 문구. 16자 이내")
    lines: List[str] = Field(description="내레이션 문장들. 6~9개, 문장당 25자 이내. 첫 문장은 강한 훅, 마지막은 행동 유도")
    description: str = Field(description="업로드 설명란 본문 (링크와 고지 문구는 제외, 프로그램이 따로 붙임)")
    hashtags: List[str] = Field(description="해시태그 5~8개, # 포함")


class ScriptSet(BaseModel):
    variants: List[Variant]


SYSTEM = """너는 유튜브 쇼츠·인스타 릴스용 쇼핑 영상 대본 작가다.
상품 정보와 이미지를 보고, 30초 안팎(내레이션 6~9문장)의 짧고 리듬감 있는 대본을 쓴다.

규칙:
- 첫 문장은 스크롤을 멈추게 하는 훅(놀라움, 문제 제기, 반전).
- 과장·허위 효능, 의학적 효과 단정, '최저가 보장' 같은 확인 안 된 주장은 쓰지 않는다.
- 이미지에 보이지 않거나 사용자가 알려주지 않은 사양(용량, 가격 등)은 지어내지 않는다.
- 유튜브 버전 마지막 문장: 영상 속 상품 링크/설명란을 확인하라고 유도.
- 인스타 버전 마지막 문장: 프로필 링크 또는 댓글로 링크를 받으라고 유도. 유튜브 버전과 표현·순서를 다르게 써서 같은 영상처럼 보이지 않게 한다.
- 일본어 버전은 번역투가 아닌 자연스러운 일본 쇼츠 말투로 새로 쓴다.
- 해시태그는 해당 언어로 쓴다.
"""


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    mt = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}


def write_scripts(product: str, notes: str, images: list[Path], keys: list[str]) -> list[Variant]:
    client = anthropic.Anthropic()
    content = [_image_block(p) for p in images[:6]]
    content.append({
        "type": "text",
        "text": (
            f"상품명: {product}\n"
            f"참고 메모(특징·장점·대상 등): {notes or '(없음)'}\n\n"
            f"다음 버전을 각각 만들어줘: {', '.join(keys)}"
        ),
    })
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=ScriptSet,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 상품 대본 작성을 거절했습니다. 상품 정보를 확인해 주세요.")
    got = {v.key: v for v in resp.parsed_output.variants}
    missing = [k for k in keys if k not in got]
    if missing:
        raise RuntimeError(f"대본이 빠진 버전: {missing}")
    return [got[k] for k in keys]
