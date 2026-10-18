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

    def warm(self) -> None:
        pass

    def match(self, heard: str) -> dict | None:
        """가장 잘 맞는 상황. 위에 적힌 상황일수록 우선 (수신거부·AI 질문 같은 건 맨 위에 두기)."""
        h = _norm(heard)
        best, best_score = None, 0.0
        for i, sc in enumerate(self.scenarios):
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

    def reply(self, heard: str) -> Iterator[str]:
        self.ended = self.handoff = False
        sc = self.match(heard)
        if sc:
            text, why = self._pick(sc.get("name", "?"), sc.get("reply", [])), sc.get("name", "?")
            self.handoff = bool(sc.get("handoff"))
            self.ended = bool(sc.get("end"))
            self.status = sc.get("status") or self.status
            if "goto" in sc:  # 이 상황 다음에 스크립트 몇 번째 멘트로 갈지
                self.step = int(sc["goto"])
        elif self.step < len(self.flow) and (len(_norm(heard)) <= 12 or any(_norm(y) in _norm(heard) for y in YES)):
            step = self.flow[self.step]
            self.step += 1
            text, why = step.get("say", ""), f"스크립트 {self.step}단계"
            self.status = step.get("status") or self.status
            self.ended = bool(step.get("end"))
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
        memo = ("상황: " + ", ".join(dict.fromkeys(situations)) + ". " if situations else "") + \
               f"스크립트 {self.step}/{len(self.flow)}단계까지 진행. " + " / ".join(x[3:].strip() for x in last)
        return {
            "status": self.status or ("통화완료" if self.step >= len(self.flow) else "중간종료"),
            "memo": memo.strip(),
            "next_action": "직접 확인 필요" if "맞는 상황 없음" in self.history else "",
            "callback_time": "",
            "needs_review": "맞는 상황 없음" in self.history,
        }
