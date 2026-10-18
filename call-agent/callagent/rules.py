"""무료 상담 두뇌: scenarios.yaml(상황표)대로 대답한다. AI API 를 쓰지 않는다.

상대 말 → 상황표에서 맞는 상황 찾기(키워드 + 예시 문장 유사도) → 그 상황의 녹음 재생.
맞는 상황이 없으면 스크립트 순서(flow)대로 다음 멘트, 그것도 끝났으면 default(사람에게 넘기기).
"""
import difflib
import re
from typing import Iterator

import yaml

from .clips import split_tokens
from .config import resolve

YES = ["네", "예", "그래요", "말씀하세요", "괜찮아요", "듣고 있", "어떤", "뭔데요", "무슨", "그런데요", "맞아요", "맞는데"]


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


class RuleBrain:
    def __init__(self, cfg: dict, playbook: str = "", customer: dict | None = None, clips=None):
        path = resolve(cfg.get("rules", {}).get("scenarios", "scenarios.yaml"))
        if not path.exists():
            raise RuntimeError(f"{path.name} 이 없습니다. scenarios.example.yaml 을 복사하거나 Codex 에게 "
                               "\"상담스크립트를 scenarios.yaml 로 바꿔줘\" 라고 요청하세요.")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.scenarios = data.get("scenarios") or []
        self.flow = data.get("flow") or []
        self.default = data.get("default") or {"reply": [], "handoff": True}
        self.min_similarity = cfg.get("rules", {}).get("min_similarity", 0.6)
        self.clips = clips
        self.step = 0
        self.used: dict[str, int] = {}
        self.history: list[str] = []
        self.messages: list[dict] = []
        self.status = ""
        self.ended = self.handoff = False
        self.waiting: str | None = None   # 방금 질문한 항목 (예: "부위") → 상대 대답을 그대로 받아 적고 다음으로
        self.answers: dict[str, str] = {}
        self.after_answer: dict | None = None  # 상황에서 물은 질문의 대답을 받은 뒤 할 일 (예: 재통화 시간 → 인사하고 끊기)
        self.last_question = ""                # 다시 물어볼 질문 녹음 (되물음에 답한 뒤)

    def warm(self) -> None:
        pass

    def match(self, heard: str, answering: bool = False) -> dict | None:
        """가장 잘 맞는 상황. 위에 적힌 상황일수록 우선 (수신거부·AI 질문 같은 건 맨 위에 두기).
        answering: 질문의 대답을 기다리는 중 — always 상황이거나, 상대가 되묻는 말(?)일 때만 상황으로 봄.
        (예: "아래쪽이 아파요"는 대답으로 기록, "근데 얼마예요?"는 가격 문의로 대답)"""
        h = _norm(heard)
        asking_back = "?" in heard or re.search(r"(나요|까요|가요|어요\?|에요\?|예요|인가|뭐|얼마|어디|누구|언제)", heard)
        best, best_score = None, 0.0
        for i, sc in enumerate(self.scenarios):
            # interrupt: true → 거절·망설임처럼 질문의 '대답'이 아닌 말이면 질문 중에도 그 상황으로 대응
            if answering and not sc.get("always") and not sc.get("interrupt") and not asking_back:
                continue
            hits = sum(1 for k in sc.get("keywords", []) if _norm(k) and _norm(k) in h)
            sim = max((difflib.SequenceMatcher(None, h, _norm(e)).ratio() for e in sc.get("examples", [])), default=0.0)
            if hits == 0 and sim < self.min_similarity:
                continue
            score = hits * 2 + sim - i * 0.01
            if score > best_score:
                best, best_score = sc, score
        return best

    def _pick(self, key: str, replies: list[str]) -> str:
        """같은 상황이 또 나오면 다른 대답 (준비된 대답을 돌아가며)."""
        if not replies:
            return ""
        n = self.used.get(key, 0)
        self.used[key] = n + 1
        return replies[min(n, len(replies) - 1)] if key == "__flow__" else replies[n % len(replies)]

    def _next_step(self) -> tuple[str, str]:
        step = self.flow[self.step]
        self.step += 1
        self.status = step.get("status") or self.status
        self.ended = bool(step.get("end"))
        self.waiting = step.get("ask")  # 이 멘트가 질문이면 다음 대답을 이 항목으로 기록
        if self.waiting:
            self.last_question = (split_tokens(step.get("say", "")) or [""])[-1]
        return step.get("say", ""), f"스크립트 {self.step}단계"

    def reply(self, heard: str) -> Iterator[str]:
        self.ended = self.handoff = False
        asked = self.waiting
        sc = self.match(heard, answering=bool(asked))
        if asked and not sc:
            self.answers[asked] = heard.strip()  # 고객 대답 그대로 메모
            self.waiting = None
            if self.after_answer:  # 상황에서 물은 질문 → 정해 둔 마무리
                aa, self.after_answer = self.after_answer, None
                text, why = aa.get("say", ""), "대답 기록"
                self.status = aa.get("status") or self.status
                self.ended = bool(aa.get("end"))
            else:
                text, why = self._next_step() if self.step < len(self.flow) else ("", "대답 기록")
            why = f"'{asked}' 대답 기록 → {why}"
        elif sc and asked and not sc.get("always") and not sc.get("ask"):
            # 질문 도중 상대가 되묻거나 망설임 → 그 말에 먼저 대답하고 원래 질문을 다시
            name = sc.get("name", "?")
            text = self._pick(name, sc.get("reply", []))
            self.status = sc.get("status") or self.status
            self.handoff = bool(sc.get("handoff"))
            self.ended = bool(sc.get("end")) or (bool(sc.get("end_on_repeat")) and self.used.get(name, 0) >= 2)
            if not (self.ended or self.handoff):
                text = f"{text} {self.last_question}".strip()
            why = f"{name} (먼저 대답하고 '{asked}' 다시 질문)"
        elif sc:
            text, why = self._pick(sc.get("name", "?"), sc.get("reply", [])), sc.get("name", "?")
            self.handoff = bool(sc.get("handoff"))
            # end_on_repeat: 같은 상황이 두 번째면 (예: 두 번 거절) 마무리 인사 후 끊기
            self.ended = bool(sc.get("end")) or (bool(sc.get("end_on_repeat")) and self.used.get(sc.get("name", "?"), 0) >= 2)
            self.status = sc.get("status") or self.status
            if "goto" in sc:  # 이 상황 다음에 스크립트 몇 번째 멘트로 갈지
                self.step = int(sc["goto"])
            if sc.get("ask"):  # 이 상황의 대답이 질문이면 (예: "몇 시가 편하세요?") 대답을 받아 적기
                self.waiting, self.after_answer = sc["ask"], sc.get("after_answer")
                self.last_question = (split_tokens(text) or [""])[-1]
            if sc.get("resume") and self.step < len(self.flow):  # 대답 후 바로 스크립트 다음 멘트로 이어가기
                more, _ = self._next_step()
                text = f"{text} {more}"
        elif self.step < len(self.flow) and (len(_norm(heard)) <= 12 or any(_norm(y) in _norm(heard) for y in YES)):
            text, why = self._next_step()
        else:
            text, why = self._pick("__default__", self.default.get("reply", [])), "맞는 상황 없음"
            self.handoff = bool(self.default.get("handoff", True))
        self.history.append(why)
        print(f"   (판단: {why})")
        self.messages += [{"role": "user", "content": heard}, {"role": "assistant", "content": text}]
        yield from split_tokens(text)

    def summarize(self, transcript: str) -> dict:
        situations = [h for h in self.history if not h.startswith("스크립트")]
        last = [line for line in transcript.splitlines() if line.startswith("상대:")][-2:]
        situations = [h for h in situations if "대답 기록" not in h]
        answers = " / ".join(f"{k}: {v}" for k, v in self.answers.items())
        memo = (f"[답변] {answers}. " if answers else "") + \
               ("상황: " + ", ".join(dict.fromkeys(situations)) + ". " if situations else "") + \
               f"스크립트 {self.step}/{len(self.flow)}단계까지 진행. " + " / ".join(x[3:].strip() for x in last)
        return {
            "status": self.status or ("통화완료" if self.step >= len(self.flow) else "중간종료"),
            "memo": memo.strip(),
            "next_action": "직접 확인 필요" if "맞는 상황 없음" in self.history else "",
            "callback_time": next((v for k, v in self.answers.items() if "재통화" in k or "시간" in k), ""),
            "needs_review": "맞는 상황 없음" in self.history,
            "answers": self.answers,
        }
