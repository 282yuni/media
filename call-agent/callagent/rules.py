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


def short(v: str) -> str:  # "삼 년 됐어요" → "삼 년", "한 이천 정도요" → "이천"
    v = re.sub(r"^((네|내|예|응|어|아|음|한|대략|그냥)[.,~]?\s+)+", "", v.strip())
    v = re.sub(r"\s*(정도|쯤|가량)?\s*(됐어요|되었어요|됐죠|내고 있어요|내요|이에요|예요|이요|에요|(?<!세)요|죠|이야|(?<!아)야)?[.!?~]*$", "", v)
    return v.strip()


class RuleBrain:
    def __init__(self, cfg: dict, playbook: str = "", customer: dict | None = None, clips=None):
        path = resolve(cfg.get("rules", {}).get("scenarios", "scenarios.yaml"))
        if not path.exists():
            raise RuntimeError(f"{path.name} 이 없습니다. scenarios.example.yaml 을 복사하거나 Codex 에게 "
                               "\"상담스크립트를 scenarios.yaml 로 바꿔줘\" 라고 요청하세요.")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.scenarios = data.get("scenarios") or []
        self.flow = data.get("flow") or []
        self.opening = None   # 업종별 첫인사 (flows 에 opening 이 있으면 config 의 opening 대신)
        self.disclosure = None  # 업종별로 첫인사 뒤에 이어서 할 말 (flows 에 disclosure 가 있으면 config 의 ai_disclosure 대신)
        self.branch = ""
        # 업종별 스크립트: 고객 시트의 '업종' 칸을 보고 flows 중 맞는 걸 고름 (없으면 match 가 빈 것 = 기본)
        flows = data.get("flows") or []
        if flows:
            col = cfg.get("rules", {}).get("branch_column", "업종")
            kind = _norm(str((customer or {}).get(col, "")))
            pick = next((f for f in flows if any(_norm(k) in kind for k in f.get("match", []) if _norm(k)) and kind), None)
            pick = pick or next((f for f in flows if not f.get("match")), flows[0])
            self.flow, self.opening, self.branch = pick.get("steps", []), pick.get("opening"), pick.get("name", "")
            self.disclosure = pick.get("disclosure")
        self.default = data.get("default") or {"reply": [], "handoff": True}
        # 메모를 업무 시트 방식으로: 예 "오픈3년/기장10만/일반/..." (memo_order 가 있을 때)
        self.memo_order = data.get("memo_order") or []
        self.default_status = data.get("default_status")
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
        # 말끝 올림에 붙은 "?"만으로는 되묻기로 안 봄 ("50만원 정도야?"는 대답)
        asking_back = re.search(r"(나요|까요|가요|어요\?|에요\?|예요|인가|뭐|얼마|어디|누구|언제|왜|어떻게)", heard)
        best, best_score = None, 0.0
        for i, sc in enumerate(self.scenarios):
            # interrupt: true → 거절·망설임처럼 질문의 '대답'이 아닌 말이면 질문 중에도 그 상황으로 대응
            if answering and not sc.get("always") and not sc.get("interrupt") and not asking_back:
                continue
            # after: 바로 앞 판단이 이 상황일 때만 (예: "기장 필요하세요?" 다음의 "아니요")
            if self.waiting and self.waiting in (sc.get("not_during") or []):  # 예: 조정료를 묻는 중의 "50만원"은 기장료가 아님
                continue
            if sc.get("after") and (not self.history or self.history[-1] != sc["after"]):
                continue
            if sc.get("max_chars") and len(h) > sc["max_chars"]:  # 짧은 말일 때만 (예: "여보세요?" — 긴 말 속 여보세요는 무시)
                continue
            if sc.get("question_only") and "?" not in heard:  # 예: 되묻기 "네?" — 그냥 "네."는 대답이니까 제외
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

    def _stop_if(self, asked: str, heard: str) -> dict | None:
        """스크립트 멘트의 stop_if: 이 질문의 대답에 keywords 가 있고, when 의 앞 대답 조건도 맞으면 그 마무리."""
        step = next((s for s in self.flow if s.get("ask") == asked), None)
        rule = (step or {}).get("stop_if")
        if not rule:
            return None
        h = _norm(heard)
        if not any(_norm(k) and _norm(k) in h for k in rule.get("keywords", [])):
            return None
        if any(_norm(k) and _norm(k) in h for k in rule.get("unless", [])):  # 애매하면 끝내지 않고 진행
            return None
        for name, words in (rule.get("when") or {}).items():
            if not any(_norm(w) in _norm(self.answers.get(name, "")) for w in words):
                return None
        return rule

    def reply(self, heard: str) -> Iterator[str]:
        self.ended = self.handoff = False
        asked = self.waiting
        sc = self.match(heard, answering=bool(asked))
        if sc and sc.get("note"):  # 이 상황의 말 자체를 메모 (예: "10만원이요" → 기장료)
            self.answers[sc["note"]] = heard.strip()
        # 받아 적기가 말끝 올림만 보고 "?"를 붙이는 경우가 많아서 ("한 1년이요?"), 물음표만으로는 질문으로 안 봄
        questioning = re.search(r"(인가요|나요|까요|뭐|어떻게|왜)\??$", heard.strip()) or (
            "?" in heard and re.search(r"(뭐|왜|어떻게|어디|누구|얼마|언제|무슨|어느|가요|나요|까요|인가|건가|는지|예요\?|에요\?)", heard))
        rules = next((s.get("retry_if") for s in self.flow if s.get("ask") == asked), None) if asked and not sc else None
        rules = rules if isinstance(rules, list) else ([rules] if rules else [])
        retry = next((r for r in rules
                      if any(_norm(k) and _norm(k) in _norm(heard) for k in r.get("keywords", []))
                      and not any(_norm(k) and _norm(k) in _norm(heard) for k in r.get("unless", []))), None)
        if retry:
            # 대답이 질문의 답이 아님 (예: 시간 묻는데 "내일은 안 돼요") → 정해 둔 말로 다시 묻고 계속 기다림
            text = retry.get("say", "")
            self.history.append(f"'{asked}' 다시 물음")
            print(f"   (판단: '{asked}' 대답이 아니라서 다시 물음)")
            self.messages += [{"role": "user", "content": heard}, {"role": "assistant", "content": text}]
            yield from split_tokens(text)
            return
        if asked and not sc and questioning and not self.default.get("handoff", True):
            # default 가 넘기지 않는 설정이면 (예: "방문 담당자님이 안내해 드릴 거예요") 그 멘트 후 원래 질문을 다시
            text = f"{self._pick('__default__', self.default.get('reply', []))} {self.last_question}".strip()
            self.history.append("맞는 상황 없음")
            print("   (판단: 모르는 질문 → 기본 대답 후 다시 질문)")
            self.messages += [{"role": "user", "content": heard}, {"role": "assistant", "content": text}]
            yield from split_tokens(text)
            return
        if asked and not sc and questioning and self.default.get("handoff", True):
            # 질문의 대답 대신 모르는 걸 되물음 → 지어내지 않고 기본 대답(확인 후 연락) + 나에게 넘김
            text, why = self._pick("__default__", self.default.get("reply", [])), "모르는 질문 → 넘김"
            self.handoff = True
            self.waiting = None
            self.history.append("맞는 상황 없음")
            print(f"   (판단: {why})")
            self.messages += [{"role": "user", "content": heard}, {"role": "assistant", "content": text}]
            yield from split_tokens(text)
            return
        if asked and not sc:
            self.answers[asked] = heard.strip()  # 고객 대답 그대로 메모
            self.waiting = None
            stop = self._stop_if(asked, heard)
            if stop:  # 앞 대답과 이번 대답을 보고 접수 조건이 안 되면 (예: 간이 + 월매출 미달) 정중히 마무리
                text, why = stop.get("say", ""), "접수 조건 안 됨"
                self.status = stop.get("status") or self.status
                self.ended = bool(stop.get("end", True))
            elif self.after_answer:  # 상황에서 물은 질문 → 정해 둔 마무리
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
            if "goto" in sc:  # 그 상황의 대답이 따로 묻는 말이면 (예: "매달 기장이 필요하세요?") 원래 질문은 다시 안 하고 그쪽으로
                self.step, self.waiting = int(sc["goto"]), None
                why = f"{name} (질문 도중이지만 먼저 확인)"
            else:
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
        elif self.step < len(self.flow) and ((len(_norm(heard)) <= 12 and not questioning) or any(_norm(y) in _norm(heard) for y in YES)):
            text, why = self._next_step()
        else:
            text, why = self._pick("__default__", self.default.get("reply", [])), "맞는 상황 없음"
            self.handoff = bool(self.default.get("handoff", True))
            if self.default.get("keep_going") and not questioning and self.step < len(self.flow):
                # 거절도 질문도 아닌 말 (혼잣말·맞장구·잘못 받아 적은 말) → 담당자 안내 없이 스크립트를 자연스럽게 이어감
                text, why = "", "알아듣기 어려운 말 → 그냥 이어감"
            if self.default.get("resume") and not self.handoff and self.step < len(self.flow):
                more, _ = self._next_step()  # 기본 대답 후 바로 스크립트 다음 멘트로
                text = f"{text} {more}".strip()
        self.history.append(why)
        print(f"   (판단: {why})")
        self.messages += [{"role": "user", "content": heard}, {"role": "assistant", "content": text}]
        yield from split_tokens(text)

    def summarize(self, transcript: str) -> dict:
        situations = [h for h in self.history if not h.startswith("스크립트")]
        last = [line for line in transcript.splitlines() if line.startswith("상대:")][-2:]
        situations = [h for h in situations if "대답 기록" not in h]
        answers = " / ".join(f"{k}: {v}" for k, v in self.answers.items())
        if self.memo_order:
            # 업무 시트 방식: 오픈3년/기장10만/일반/상황/대표가 마지막에 한 말
            noted = {sc.get("name") for sc in self.scenarios if sc.get("note")}
            parts = [f"{o.get('label', '')}{short(self.answers[o['key']])}" for o in self.memo_order if self.answers.get(o["key"])]
            parts += list(dict.fromkeys(h.split(" (")[0] for h in situations
                                        if not h.endswith("다시 물음") and h.split(" (")[0] not in noted))
            said = [x[3:].strip() for x in last[-1:]]
            if said and said[0] not in self.answers.values():
                parts += said
            memo = "/".join(p for p in parts if p)
        else:
            memo = (f"[답변] {answers}. " if answers else "") + \
               ("상황: " + ", ".join(dict.fromkeys(situations)) + ". " if situations else "") + \
               f"스크립트 {self.step}/{len(self.flow)}단계까지 진행. " + " / ".join(x[3:].strip() for x in last)
        return {
            "status": "" if self.status == "빈칸" else self.status or self.default_status or ("통화완료" if self.step >= len(self.flow) else "중간종료"),
            "memo": memo.strip(),
            "next_action": "직접 확인 필요" if "맞는 상황 없음" in self.history else "",
            "callback_time": next((v for k, v in self.answers.items() if "재통화" in k or "시간" in k), ""),
            "needs_review": "맞는 상황 없음" in self.history,
            "answers": self.answers,
        }
