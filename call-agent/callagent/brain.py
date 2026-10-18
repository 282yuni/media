"""Claude: 플레이북을 보고 상대방 말에 내 방식대로 대답하기 + 통화 끝나고 요약하기."""
import json
import re
from typing import Iterator

import anthropic

END = "[통화종료]"
HANDOFF = "[담당자연결]"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

RULES = """\
너는 지금 실제 전화 통화 중이다. 상대방 말은 음성인식으로 받아 적은 것이라 오타가 있을 수 있다.
너의 답은 그대로 음성으로 읽힌다. 그래서:
- 한 번에 1~3문장, 짧고 자연스러운 구어체로 말한다. 목록, 기호, 이모지, 괄호 설명은 쓰지 않는다.
- 숫자는 읽히는 대로 쓴다 (예: "월 30만 원", "3시 반").
- 아래 [플레이북]의 말투, 표현, 상황별 대응을 최대한 그대로 따라 한다. 플레이북은 이 상담원이 실제 통화에서 쓴 방식이다.
- 플레이북에 없는 사실(가격, 조건, 약속, 일정 확정 등)은 지어내지 않는다. 모르면 "그 부분은 정확히 확인해서 다시 연락드릴게요"라고 한다.
- 상대가 "AI야?", "기계야?", "사람이에요?"처럼 묻으면 절대 사람이라고 하지 않는다. AI 음성 비서라고 솔직히 말하고, 원하면 담당자를 연결해 드린다고 한다.
- 상대가 그만 연락하라고 하거나, 명확히 거절하면 정중히 인사하고 끝낸다.
- 본인 인증(주민번호, 카드번호, 인증번호, 계좌 비밀번호), 결제·송금, 계약 체결·동의, 법적 책임이 생기는 약속은
  절대 대신 하지 않는다. 그런 순간이 오면 "그 부분은 제가 직접 말씀드릴게요"라고 하고 {HANDOFF} 를 붙인다.
- [이번 통화 목적]이 있으면 그 목표와 한계를 지킨다. 목적에 없는 것을 새로 약속하거나 양보하지 않는다.

특수 표시 (음성으로 읽히지 않고 프로그램이 처리함):
- 대화를 마무리하는 마지막 인사를 했으면 답 맨 끝에 {END} 를 붙인다.
- 상대가 담당자/사람 연결을 원하거나, 네가 판단하기 어려운 상황(항의, 계약 조건 협상, 개인적인 질문 등)이면 "잠시만요, 담당자 바로 연결해 드릴게요" 같은 말을 하고 답 끝에 {HANDOFF} 를 붙인다.
""".format(END=END, HANDOFF=HANDOFF)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "결과 한 단어: 관심, 재통화, 자료요청, 미팅확정, 부재, 거절, 수신거부, 번호오류, 기타"},
        "memo": {"type": "string", "description": "고객 시트 메모 칸에 넣을 2~3문장 요약 (상대 반응, 약속한 것)"},
        "next_action": {"type": "string", "description": "다음에 내가 할 일 (없으면 빈 문자열)"},
        "callback_time": {"type": "string", "description": "다시 연락하기로 한 시간 (없으면 빈 문자열)"},
        "needs_review": {"type": "boolean", "description": "AI가 확답 못 한 질문이 있거나 내가 직접 확인해야 하면 true"},
    },
    "required": ["status", "memo", "next_action", "callback_time", "needs_review"],
    "additionalProperties": False,
}

_SENTENCE_END = re.compile(r"(.+?[.!?~…]+[\"')]*\s+|.+?\n)", re.S)


_CLIP = re.compile(r"\[클립:\d+\]")

CLIP_RULES = {
    "clips": """
[녹음 문장 사용법 — 반드시 지킬 것]
너는 문장을 새로 만들어 말할 수 없다. 상담원의 실제 녹음만 그대로 재생된다.
아래 [녹음 문장 목록]에서 지금 상황에 가장 맞는 것을 1~3개 골라 [클립:번호] 형식으로만 답한다. 다른 글자는 쓰지 않는다.
예: [클립:12] [클립:3]
딱 맞는 녹음이 없으면 "잠시만요", "확인해서 다시 연락드릴게요" 같은 녹음을 고르고 끝에 {HANDOFF} 를 붙인다.
상대가 AI냐고 물으면 AI 고지 녹음이 있으면 그걸 고르고, 없으면 {HANDOFF} 만 출력한다 (사람이라고 답하는 녹음은 절대 고르지 않는다).
""",
    "mixed": """
[녹음 문장 사용법]
아래 [녹음 문장 목록]은 상담원 실제 목소리 녹음이다. 상황에 맞는 게 있으면 문장을 쓰지 말고 [클립:번호] 로 고른다.
딱 맞는 녹음이 없을 때만 짧게 직접 말한다 (그 부분은 복제 음성으로 읽힌다). 녹음과 직접 말하기를 섞어도 된다.
""",
}


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """스트리밍 텍스트에서 완성된 문장과 [클립:번호] 를 떼어낸다. 나머지는 버퍼로."""
    out = []
    while (m := _CLIP.search(buf)):
        head = buf[:m.start()]
        done, rest = _split_text(head)
        out += done + ([rest.strip()] if rest.strip() else []) + [m.group(0)]
        buf = buf[m.end():]
    done, rest = _split_text(buf)
    return out + done, rest


def _split_text(buf: str) -> tuple[list[str], str]:
    out, pos = [], 0
    for m in _SENTENCE_END.finditer(buf):
        out.append(m.group(0).strip())
        pos = m.end()
    return [s for s in out if s], buf[pos:]


def _clean(text: str) -> str:
    return text.replace(END, "").replace(HANDOFF, "").strip()


class Brain:
    def __init__(self, cfg: dict, playbook: str, customer: dict | None = None, clips=None):
        self.cfg = cfg
        self.client = anthropic.Anthropic()
        b = cfg["brain"]
        self.model = b.get("model", "claude-opus-5-5")
        self.effort = b.get("effort", "low")
        a = cfg["agent"]
        # 플레이북은 통화마다 같으므로 맨 앞에 두고 캐시. 고객별 정보는 그 뒤에.
        self.system = [
            {"type": "text", "text": RULES + f"\n상담원: {a['company']} {a['my_name']} / 용건: {a['product']}\n\n[플레이북]\n{playbook}",
             "cache_control": {"type": "ephemeral"}},
        ]
        mode = cfg["voice"].get("mode", "clone")
        if clips and mode in CLIP_RULES:
            self.system[0]["text"] += CLIP_RULES[mode].format(HANDOFF=HANDOFF) + "\n[녹음 문장 목록]\n" + clips.catalog()
        brief = (cfg.get("_brief") or "").strip()
        if brief:
            self.system.append({"type": "text", "text": f"[이번 통화 목적 — 사용자가 직접 적은 것]\n{brief}"})
        if customer:
            info = "\n".join(f"- {k}: {v}" for k, v in customer.items() if v not in (None, "") and not k.startswith("_"))
            self.system.append({"type": "text", "text": f"[이번 통화 상대 정보 (고객 시트)]\n{info}"})
        self.messages: list[dict] = []
        self.ended = False
        self.handoff = False

    def _stream(self, **kw):
        return self.client.beta.messages.stream(
            model=self.model, output_config={"effort": self.effort},
            betas=[FALLBACK_BETA], fallbacks="default", **kw,
        )

    def warm(self) -> None:
        """통화 연결 전에 플레이북을 캐시에 올려 둔다 → 첫 대답이 빨라짐 (출력 토큰 비용 없음)."""
        try:
            self.client.beta.messages.create(
                model=self.model, max_tokens=0, output_config={"effort": self.effort},
                betas=[FALLBACK_BETA], fallbacks="default", system=self.system,
                messages=[{"role": "user", "content": "(전화가 연결됨)"}],
            )
        except Exception as e:
            print(f"   (캐시 예열 실패, 통화에는 지장 없음: {e})")

    def reply(self, heard: str) -> Iterator[str]:
        """상대방 말 → 내 대답을 문장 단위로 흘려 준다 (첫 문장부터 바로 TTS 시작 가능)."""
        self.ended = self.handoff = False
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"] += " " + heard
        else:
            self.messages.append({"role": "user", "content": heard})
        full, buf = "", ""
        with self._stream(max_tokens=2000, system=self.system, messages=self.messages) as stream:
            for chunk in stream.text_stream:
                full += chunk
                buf += chunk
                sentences, buf = _split_sentences(buf)
                for s in sentences:
                    if _clean(s):
                        yield _clean(s)
            final = stream.get_final_message()
        if final.stop_reason == "refusal":
            full = "죄송해요, 그 부분은 담당자가 직접 말씀드릴게요. " + HANDOFF
            buf = full
        if _clean(buf):
            yield _clean(buf)
        self.ended = END in full
        self.handoff = HANDOFF in full
        self.messages.append({"role": "assistant", "content": _clean(full) or "(침묵)"})

    def summarize(self, transcript: str) -> dict:
        res = self.client.beta.messages.create(
            model=self.model, max_tokens=4000, betas=[FALLBACK_BETA], fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
            system=self.system,
            messages=[{"role": "user", "content": "아래 통화 기록을 고객 시트에 적을 수 있게 정리해줘.\n\n" + transcript}],
        )
        text = next((b.text for b in res.content if b.type == "text"), "{}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"status": "기타", "memo": text[:300], "next_action": "", "callback_time": "", "needs_review": True}
