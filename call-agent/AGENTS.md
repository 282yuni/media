# AGENTS.md — 치과 1차 콜 AI 대행 (call-agent)

Codex 같은 코딩 에이전트가 이 폴더에서 작업할 때 먼저 읽는 지침이다. 사용자(상담원)는 한국어를 쓰는 비개발자다.
화면에 나오는 메시지, 주석, 설명은 모두 쉬운 한국어로 쓴다.

## 이 프로그램이 하는 일
사용자가 휴대폰으로 치과에 1차 영업 전화를 건다. 휴대폰 통화 소리는 PC(Windows "휴대폰과 연결" 등)로 들어오고,
상대가 받으면 AI가 대신 상담한다. 흐름은 다음과 같다.
상대 말 듣기(가상 오디오 케이블) → 받아 적기(ElevenLabs STT) → 대답 고르기/만들기(Claude, `playbook.md` 기준)
→ 소리 내기 → 통화가 끝나면 요약해서 고객 시트(엑셀/CSV/구글 시트)에 기록하고 녹취를 `logs/` 에 저장.

소리 내기는 세 가지 모드가 있다 (`config.yaml` 의 `voice.mode`).
- `clips`: 사용자의 **실제 녹음을 그대로** 재생한다. 합성이나 목소리 변환은 하지 않는다. 사용자가 이 모드를 원했다.
  녹음에 없는 말은 하지 않고 사람에게 넘긴다.
- `mixed`: 녹음에 있으면 녹음을, 없으면 복제 목소리(ElevenLabs)를 쓴다.
- `clone`: 전부 복제 목소리로 말한다.

## 반드시 지킬 것 (바꾸지 말 것)
1. **AI 정직성**: 상대가 "AI냐, 사람이냐"고 물으면 절대 사람이라고 답하지 않는다. `brain.py` 의 `RULES`, `CLIP_RULES` 에 있다.
   이 규칙을 끄는 설정이나 옵션은 만들지 않는다. 사람인 척하는 녹음 클립은 고르지 않는다.
2. **AI 사용 고지**: `agent.ai_disclosure` 는 기본으로 켜 둔다 (2026년 1월 시행 AI 기본법). 사용자가 빼려고 하면 위험을 알려준다.
3. **본인 목소리만**: 목소리 복제와 녹음 클립은 사용자 본인 목소리만 쓴다. 다른 사람 목소리를 쓰는 기능은 만들지 않는다.
4. **개인정보·비밀값은 git 에 올리지 않는다**: `.env`, `config*.yaml`, `playbook.md`, `clips/`, `recordings/`,
   `voice_samples/`, `logs/`, `data/`, 서비스계정 JSON. `.gitignore` 를 유지한다.
5. 수신거부(`skip_status`) 고객에게는 다시 전화하지 않는다.
6. 어떤 실패가 나도 통화가 멈추거나 침묵하면 안 된다. 실패하면 사람에게 넘긴다 (`[담당자연결]` → 알림음).

## 파일 지도
| 파일 | 역할 |
|---|---|
| `main.py` | 명령어 전부 (`devices`, `meter`, `clips`, `clone-voice`, `say`, `script`, `train`, `practice`, `list`, `call`, `next`). 공통 옵션은 `--config` |
| `callagent/audio.py` | 가상 케이블 입출력. `Listener`(말 끝 감지, 잡음 자동 적응 `adapt`, 0.3초 지속해야 끼어들기로 봄), `Mouth`(재생, 즉시 멈춤) |
| `callagent/clips.py` | 녹음 파일을 문장 단위로 자르기(ffmpeg 무음 감지, 12초가 넘으면 다시 자름), `clips.yaml` 목록, `[클립:번호]` 재생 |
| `callagent/voice.py` | ElevenLabs STT(`Ears`), TTS(`Voice`), 목소리 복제 |
| `callagent/brain.py` | Claude 대답(문장 단위 스트리밍, `[클립:N]` 토큰 분리), 통화 요약, 캐시 예열 `warm()` |
| `callagent/session.py` | 통화 한 건 진행. `prepare()` 가 신호음 동안 첫인사 소리와 맞장구 소리를 미리 만들고 캐시를 예열 |
| `callagent/trainer.py` | 통화 녹음 → 대본 → `playbook.md`, 또는 상담 스크립트(txt/md/docx) → `playbook.md` |
| `callagent/customers.py` | 고객 시트 읽기/쓰기 (시트에서 보이는 행 번호 기준, 헤더가 1행) |
| `callagent/dialer.py` | 수동(번호를 클립보드에 복사) 또는 adb 로 자동 걸기·끊기 |
| `tests/test_offline.py` | 소리 장치·API 키 없이 도는 테스트 |

## 개발 규칙
- Python 3.10+, Windows 가 실제 실행 환경이다. 경로는 `pathlib` 로 다루고, 한글 파일은 `encoding="utf-8"` 로 연다.
- 변경 후에는 반드시 `python -m pytest tests -q` 를 돌린다. sounddevice/PortAudio 가 없어도 돈다 (테스트가 가짜 모듈로 바꿔 끼움).
- Claude 모델은 `config.yaml` 의 `brain.model` (기본 `claude-opus-5-5`, `effort: low`)을 쓴다.
  Anthropic 공식 SDK(`anthropic`)의 `client.beta.messages` 를 쓰고, `betas=["server-side-fallback-2026-07-01"]`,
  `fallbacks="default"` 를 유지한다. 이 모델은 `thinking: disabled`, `budget_tokens`, `temperature`, 강제 `tool_choice`,
  assistant prefill 을 보내면 400 오류가 난다.
- 지연이 가장 중요하다. 대답은 문장 단위로 흘려서 첫 문장부터 바로 재생한다. 통화 중에 무거운 작업을 추가하지 말고
  `prepare()` 로 미리 하거나 백그라운드 스레드에서 한다.
- 키보드 입력은 `session.Console` 하나로만 읽는다 (`input()` 을 직접 부르면 통화 중 명령과 충돌한다).
- 실제 통화로 확인하지 못한 변경은 "실제 통화로는 확인 안 함"이라고 사용자에게 분명히 말한다.

## 아직 실제로 확인하지 못한 것 (우선순위 순)
1. 실제 Windows + 휴대폰 연결 앱 + VB-Cable 환경에서 소리 길이 제대로 이어지는지. 장치 샘플레이트가 맞지 않으면
   WASAPI 에서 오류가 날 수 있다 (MME 장치로 고르면 대부분 해결된다).
2. 응답 지연 실측. 화면의 `(응답 지연 N초)` 를 보고 줄인다. 가장 큰 부분은 STT(발화가 끝난 뒤 통째로 올림)다.
   다음 개선 후보는 ElevenLabs 실시간(스트리밍) STT 로 바꾸는 것이다.
3. ElevenLabs STT `scribe_v1` 의 한국어 인식률과 `keyterms` 효과.
4. clips 모드에서 Claude 가 고른 클립이 대화 흐름에 자연스러운지. `practice` 로 확인하고 `playbook.md` 나 `clips.yaml` 문구를 다듬는다.
5. 전화기 2대 동시 운용. 프로그램은 `--config config2.yaml` 로 창 두 개를 띄울 수 있다.
   하지만 "휴대폰과 연결" 앱은 PC 한 대에 휴대폰 한 대만 붙으므로 PC 2대가 가장 확실하다.

## 사용자에게 처음 안내할 순서
`README.md` 의 1~8번 순서대로 안내한다. 가장 빠른 길은 다음과 같다.
`pip install -r requirements.txt` → `.env`·`config.yaml` 복사 → `python main.py clips 내녹음.mp3` →
`clips.yaml` 정리 → `python main.py script 상담스크립트.txt` → `python main.py practice` → `python main.py call 2`
