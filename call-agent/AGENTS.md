# AGENTS.md — 치과 1차 콜 AI 대행 (call-agent)

Codex 같은 코딩 에이전트가 이 폴더에서 작업할 때 먼저 읽는 지침이다. 사용자(상담원)는 한국어를 쓰는 비개발자다.
화면에 나오는 메시지, 주석, 설명은 모두 쉬운 한국어로 쓴다.

## 이 프로그램이 하는 일
사용자가 휴대폰(갤럭시 S8, 010 유심)으로 치과에 1차 영업 전화를 건다. 통화 소리는 PC(Windows "휴대폰과 연결")로 들어오고,
상대가 받으면 프로그램이 대신 상담한다. 통화가 끝나면 결과를 고객 시트에 기록하고 녹취를 `logs/` 에 저장한다.

### 사용자의 핵심 조건: 추가 장비 없음, 유료 API 없음 → `engine: "free"` 가 기본
- 받아 적기: `local_stt.py` (faster-whisper, 사용자 PC에서 실행, 무료)
- 대답 고르기: `rules.py` + `scenarios.yaml` (상황표. 키워드·예시 문장 유사도로 상황 판단, 없으면 스크립트 `flow` 순서, 그것도 아니면 `default` = 사람에게 넘김)
- 소리 내기: `clips.py` (사용자 실제 녹음을 **변환 없이 그대로** 재생)
- 유료 API(Anthropic, ElevenLabs)를 기본 경로에 다시 넣지 않는다. `engine: "ai"` 는 사용자가 고를 때만 쓰는 선택 기능이다.
- 무료 모드에 새 기능을 넣을 때도 유료 서비스나 새 장비가 필요하면 안 된다. 무료 오픈소스 라이브러리와 사용자 PC 안에서 해결한다.

### Codex 가 해 줄 핵심 일: 상담 스크립트 → `scenarios.yaml`
무료 모드에는 AI가 없으므로 "AI가 생각하는 부분"은 Codex 가 미리 상황표로 만들어 둔다.
1. 사용자가 준 상담 스크립트(txt/docx)와 `clips/clips.yaml`(녹음 번호별 글)을 읽는다.
2. `scenarios.example.yaml` 형식 그대로 `scenarios.yaml` 을 만든다.
   - `flow`: 스크립트의 주 흐름을 순서대로 적는다. 각 `say` 는 그 멘트와 같은 내용의 `[클립:번호]`.
   - `scenarios`: 스크립트의 상황별 대응. **수신거부, AI 질문, 담당자 요청은 맨 위에 둔다** (위가 우선).
     `keywords` 는 음성 인식이 띄어쓰기·조사를 틀려도 걸리게 짧은 핵심어로 넉넉히 적는다 (비교할 때 공백·기호는 무시됨).
     `examples` 에는 실제로 나올 법한 상대 말을 2~4개 적는다.
   - 같은 상황이 두 번 나오면 `reply` 목록의 다음 녹음을 쓴다. 첫 번째는 한 번 더 권유하고, 두 번째는 정중히 마무리하는 순서가 자연스럽다.
   - `default`: "확인해서 다시 연락드릴게요" 녹음 + `handoff: true`.
3. `config.yaml` 의 `agent.opening`, `ai_disclosure`, `fillers`, `hello_again` 을 맞는 녹음 번호로 채운다.
4. 스크립트에는 있는데 녹음이 없는 멘트는 목록으로 정리해서 사용자에게 "이 문장들을 녹음해 주세요"라고 알려준다. 녹음을 지어내거나 비워 두지 않는다.
5. 끝나면 `python -m pytest tests -q` 를 돌리고, 사용자에게 `python main.py practice` 로 확인하라고 안내한다.

통화 녹음 대본(`recordings/transcripts/*.txt`, `python main.py train` 으로 무료 생성)이 있으면, 실제 상대가 한 말로 `keywords`/`examples` 를 보강한다.

소리 내기 모드 (`voice.mode`, 유료 ai 엔진일 때만 의미 있음. free 는 항상 clips):
- `clips`: 사용자의 **실제 녹음을 그대로** 재생한다. 합성이나 목소리 변환은 하지 않는다. 사용자가 이 모드를 원했다.
  녹음에 없는 말은 하지 않고 사람에게 넘긴다.
- `mixed`: 녹음에 있으면 녹음을, 없으면 복제 목소리(ElevenLabs)를 쓴다.
- `clone`: 전부 복제 목소리로 말한다.

## 반드시 지킬 것 (바꾸지 말 것)
1. **AI 정직성**: 상대가 "AI냐, 사람이냐"고 물으면 절대 사람이라고 답하지 않는다. `brain.py` 의 `RULES`, `CLIP_RULES` 에 있다.
   이 규칙을 끄는 설정이나 옵션은 만들지 않는다. 사람인 척하는 녹음 클립은 고르지 않는다.
2. **AI 사용 고지**: `agent.ai_disclosure` 는 기본으로 켜 둔다 (2026년 1월 시행 AI 기본법). 사용자가 빼려고 하면 위험을 알려준다.
   무료 모드의 상황표에도 "AI 질문" 상황(사실대로 답 + `handoff: true`)을 항상 맨 위쪽에 둔다.
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
| `callagent/voice.py` | (유료) ElevenLabs STT(`Ears`), TTS(`Voice`), 목소리 복제 |
| `callagent/engine.py` | free/ai 선택 (`make_brain`, `make_ears`, `voice_mode`) |
| `callagent/rules.py` | 무료 두뇌: `scenarios.yaml` 대로 대답, 요약 (`RuleBrain`, Brain 과 같은 인터페이스) |
| `callagent/local_stt.py` | 무료 음성 인식 (faster-whisper) |
| `callagent/brain.py` | (유료) Claude 대답(문장 단위 스트리밍, `[클립:N]` 토큰 분리), 통화 요약, 캐시 예열 `warm()` |
| `callagent/session.py` | 통화 한 건 진행. `prepare()` 가 신호음 동안 첫인사 소리와 맞장구 소리를 미리 만들고 캐시를 예열 |
| `callagent/trainer.py` | 통화 녹음 → 대본 → `playbook.md`, 또는 상담 스크립트(txt/md/docx) → `playbook.md` |
| `callagent/customers.py` | 고객 시트 읽기/쓰기 (시트에서 보이는 행 번호 기준, 헤더가 1행) |
| `callagent/dialer.py` | 수동(번호를 클립보드에 복사) 또는 adb 로 자동 걸기·끊기 |
| `tests/test_offline.py` | 소리 장치·API 키 없이 도는 테스트 |

## 개발 규칙
- Python 3.10+, Windows 가 실제 실행 환경이다. 경로는 `pathlib` 로 다루고, 한글 파일은 `encoding="utf-8"` 로 연다.
- 변경 후에는 반드시 `python -m pytest tests -q` 를 돌린다. sounddevice/PortAudio 가 없어도 돈다 (테스트가 가짜 모듈로 바꿔 끼움).
- (유료 ai 모드만 해당) Claude 모델은 `config.yaml` 의 `brain.model` (기본 `claude-opus-5-5`, `effort: low`)을 쓴다.
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
2. 응답 지연 실측 (`(응답 지연 N초)`). 무료 모드에서 가장 큰 부분은 Whisper 받아 적기다.
   개선 후보: `stt.local_model: base`, GPU(`cuda`), 말하는 도중에 미리 받아 적기.
3. Whisper 의 전화 음질 한국어 인식률. 틀리는 단어는 `voice.keyterms` 와 `scenarios.yaml` keywords 에 변형 철자를 추가해서 보완한다.
4. 상황표 판단이 맞는지. `practice` 의 `(판단: …)` 출력을 보고 keywords 를 다듬는다.
5. faster-whisper 첫 실행 때 모델을 내려받는 데 인터넷이 필요하다 (한 번만, 무료).
6. 전화기 2대 동시 운용. 프로그램은 `--config config2.yaml` 로 창 두 개를 띄울 수 있다.
   하지만 "휴대폰과 연결" 앱은 PC 한 대에 휴대폰 한 대만 붙으므로 PC 2대가 가장 확실하다.

## 사용자에게 처음 안내할 순서
`README.md` 의 1~8번 순서대로 안내한다. 가장 빠른 길은 다음과 같다.
`pip install -r requirements.txt` → `config.yaml`·`scenarios.yaml` 복사 → `python main.py clips 내녹음.mp3` →
`clips.yaml` 정리 → (Codex 가) 스크립트로 `scenarios.yaml` 작성 → `python main.py practice` → `python main.py call 2`
