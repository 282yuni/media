"""내 통화 녹음 → 대본 → 상황별 응대 플레이북(playbook.md)."""
from pathlib import Path

import anthropic

from .brain import FALLBACK_BETA
from .voice import Ears, audio_files

PROMPT = """\
아래는 한 텔레마케터(상담원)가 치과에 실제로 건 영업 전화(1차 콜) 녹음을 받아 적은 대본들이다.
화자 이름(speaker_0, speaker_1 등)은 자동 구분이라 통화마다 누가 상담원인지 다를 수 있다. 내용을 보고 판단해라.

이 상담원을 대신해 AI가 똑같이 전화를 받을 수 있도록 "플레이북"을 마크다운으로 만들어라.
상담원 본인이 나중에 직접 고쳐 쓸 문서이니 읽기 쉽게 쓴다. 구성:

# 플레이북
## 1. 무엇을 안내하는 콜인가
(회사, 상품/서비스, 핵심 혜택, 통화 목표 — 대본에서 확인되는 것만. 불확실하면 "확인 필요"라고 표시)
## 2. 말투와 습관
(존댓말 수준, 자주 쓰는 표현, 맞장구, 말 속도/길이 느낌. 실제 문장 예시를 그대로 인용)
## 3. 통화 흐름
(인사 → 확인 → 용건 → 질문 → 마무리 순서와 각 단계 실제 멘트)
## 4. 상황별 응대
상황마다 아래 형식으로. 대본에 나온 상황을 빠짐없이, 많이 나온 순서로.
### 상황: (예: 원장님 안 계세요 / 바빠요 / 이미 하는 업체 있어요 / 얼마예요? / 자료 보내주세요 / 관심 없어요 ...)
- 상대가 하는 말 예: "..."
- 내가 실제로 한 대답: "..." (대본 그대로)
- 목표/다음 단계: ...
## 5. 하면 안 되는 것 / 주의
## 6. 대본에서 확인 안 된 것 (내가 채워야 할 정보)
(가격, 계약 조건 등 AI가 지어내면 안 되는 질문에 대한 정답 자리를 비워둔다)
"""


def transcribe_folder(cfg: dict, folder: Path) -> list[Path]:
    ears = Ears(cfg)
    out_dir = folder / "transcripts"
    out_dir.mkdir(exist_ok=True)
    done = []
    for f in audio_files(folder):
        if out_dir in f.parents:
            continue
        txt = out_dir / (f.stem + ".txt")
        if txt.exists():
            print(f"  (이미 있음) {txt.name}")
        else:
            print(f"  받아 적는 중: {f.name}")
            txt.write_text(ears.transcribe_call_file(f), encoding="utf-8")
        done.append(txt)
    return done


def build_playbook(cfg: dict, transcripts: list[Path], out: Path) -> None:
    if not transcripts:
        raise RuntimeError("대본이 없습니다. recordings 폴더에 통화 녹음 파일을 넣어주세요.")
    body = "\n\n".join(f"=== 통화 {i + 1}: {p.stem} ===\n{p.read_text(encoding='utf-8')}"
                       for i, p in enumerate(transcripts))
    existing = ""
    if out.exists():
        existing = ("\n\n아래는 상담원이 이미 고쳐 둔 기존 플레이북이다. 직접 고친 내용(특히 6번에 채운 정보)은 "
                    "그대로 유지하고, 새 대본에서 나온 것만 보강해라.\n\n" + out.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    print(f"대본 {len(transcripts)}개로 플레이북을 만드는 중... (1~3분)")
    with client.beta.messages.stream(
        model=cfg["brain"].get("model", "claude-opus-5-5"), max_tokens=64000,
        output_config={"effort": "high"}, betas=[FALLBACK_BETA], fallbacks="default",
        messages=[{"role": "user", "content": PROMPT + existing + "\n\n[대본]\n" + body}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("플레이북 생성이 거절되었습니다. 대본 내용을 확인해 주세요.")
    text = "".join(b.text for b in msg.content if b.type == "text")
    out.write_text(text, encoding="utf-8")
    print(f"완료 → {out}  (꼭 열어서 6번 '내가 채워야 할 정보'를 채워주세요)")


SCRIPT_PROMPT = """\
아래는 치과 1차 영업 콜 상담 스크립트다. 이걸로 AI가 실제 상담사처럼 전화를 받을 수 있게
위와 같은 형식(1~6번)의 "플레이북"을 마크다운으로 만들어라.
- 스크립트의 멘트는 단어 하나 바꾸지 말고 그대로 인용한다 (말투를 그대로 따라 해야 하므로).
- 스크립트에 없는 흔한 상황(원장님 부재, 바쁨, 이미 업체 있음, 가격 문의, 자료 요청, 관심 없음, 수신거부,
  "AI냐"는 질문, 잘 안 들림, 엉뚱한 질문)은 스크립트 말투에 맞춰 대답을 보충하되, 보충한 대답 앞에 (보충) 이라고 표시한다.
- 스크립트에 가격·조건 같은 사실이 없으면 지어내지 말고 6번에 "확인 필요"로 남긴다.
"""


def read_script(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import zipfile
        import xml.etree.ElementTree as ET
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
        return "\n".join("".join(t.text or "" for t in p.iter(ns + "t")) for p in root.iter(ns + "p"))
    for enc in ("utf-8-sig", "cp949"):  # 메모장 한글 저장(ANSI)도 읽기
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"{path.name} 글자 인코딩을 못 읽었습니다. UTF-8 로 저장해 주세요.")


def build_playbook_from_script(cfg: dict, script: Path, out: Path) -> None:
    text = read_script(script)
    client = anthropic.Anthropic()
    print(f"{script.name} 로 플레이북을 만드는 중... (1~2분)")
    with client.beta.messages.stream(
        model=cfg["brain"].get("model", "claude-opus-5-5"), max_tokens=64000,
        output_config={"effort": "high"}, betas=[FALLBACK_BETA], fallbacks="default",
        messages=[{"role": "user", "content": PROMPT + "\n\n" + SCRIPT_PROMPT + "\n\n[상담 스크립트]\n" + text}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("플레이북 생성이 거절되었습니다. 스크립트 내용을 확인해 주세요.")
    out.write_text("".join(b.text for b in msg.content if b.type == "text"), encoding="utf-8")
    print(f"완료 → {out}  ((보충) 표시된 대답과 6번 '확인 필요'를 꼭 확인해 주세요)")
