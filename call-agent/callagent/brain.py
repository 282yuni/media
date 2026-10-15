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


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """스트리밍 텍스트에서 완성된 문장만 떼어낸다. 나머지는 버퍼로."""
    out, pos = [], 0
    for m in _SENTENCE_END.finditer(buf):
        out.append(m.group(0).strip())
        pos = m.end()
    return [s for s in out if s], buf[pos:]


def _clean(text: str) -> str:
    return text.replace(END, "").replace(HANDOFF, "").strip()


class Brain:
    def __init__(self, cfg: dict, playbook: str, customer: dict | None = None):
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
