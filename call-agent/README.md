# 치과 1차 콜 AI 대행 (무료 모드 기본)

내가 전화를 걸고 상대가 받으면 프로그램이 대신 상담합니다.
**유료 API가 필요 없고**, 내 PC와 지금 쓰는 휴대폰만 있으면 됩니다. 목소리는 **내 실제 녹음을 그대로** 재생합니다.

```
상대 목소리 ─(휴대폰과 연결 앱)→ PC ─→ 받아 적기 (내 PC의 Whisper, 무료)
                                          ↓
                          상황표(scenarios.yaml)에서 맞는 대답 고르기
                                          ↓
상대에게 ←(휴대폰과 연결 앱)─ PC ←── 내 녹음 그대로 재생 (변환 없음)
                     통화 끝 → 결과·메모를 고객 엑셀에 기록 + 녹취 저장(logs/)
```

- 원장님 부재, 바쁨, 가격 문의, 자료 요청, 수신거부, "AI예요?" 같은 상황을 알아듣고 맞는 녹음으로 대답합니다
- 상황에 안 맞는 짧은 대답("네", "말씀하세요")이면 상담 스크립트 순서대로 다음 멘트로 넘어갑니다
- 모르는 질문이 나오면 "확인해서 연락드릴게요"라고 하고 **알림음과 함께 나에게 넘깁니다**
- 상대가 길게 말하면 바로 "네~" 맞장구를 쳐서 생각하는 동안 침묵이 생기지 않습니다
- 배경 잡음에 맞춰 자동 조정되고, 짧은 잡음으로는 내 녹음이 끊기지 않습니다
- 통화 중 언제든 `t` + Enter를 누르면 내가 직접 받고, `e` + Enter를 누르면 끝냅니다

## 무엇이 필요한가

| 항목 | 비용 | 비고 |
|---|---|---|
| Windows PC (블루투스 있는 것) | 이미 있음 | 노트북은 대부분 블루투스가 있음 |
| 휴대폰 (갤럭시 S8 등) | 이미 있음 | 010 유심으로 그대로 걸림 |
| [Python 3.10+](https://www.python.org/downloads/) | 무료 | 설치할 때 "Add to PATH" 체크 |
| [ffmpeg](https://ffmpeg.org/download.html) | 무료 | `winget install ffmpeg` |
| [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) 2개 (CABLE, CABLE-A) | 무료(기부형) | 장비가 아닌 소프트웨어 |
| Windows "휴대폰과 연결" + 폰의 "Windows와 연결" 앱 | 무료 | PC에서 통화하기 |
| adb (platform-tools) | 무료 | 자동으로 걸고 끊기 (선택) |

> **제일 먼저 확인할 것**: PC에서 "휴대폰과 연결" 앱으로 전화를 걸었을 때 **PC 스피커로 상대 목소리가 들리는지** 확인하세요.
> 이게 안 되면 이 프로그램은 쓸 수 없습니다. 갤럭시 S8은 안드로이드 9까지 업데이트되는데,
> 앱의 최신 지원 조건은 바뀔 수 있으니 직접 설치해서 확인해야 합니다.

## 설치

```bat
cd call-agent
pip install -r requirements.txt
copy config.example.yaml config.yaml
copy scenarios.example.yaml scenarios.yaml
```

## 0. 자가 점검 (막히면 이것부터)

```bat
python main.py phones                      USB로 연결된 폰을 찾아 폰별 설정 파일 자동 생성 (1대째 config.yaml, 2대째 config2.yaml)
python main.py doctor                      준비 상태를 ✅/❌ 로 점검 → logs/doctor.txt
python main.py doctor --dial 010XXXXXXXX   내 다른 번호로 시험 전화를 걸고 8초 뒤 끊어서 자동 걸기 확인
python main.py --config config2.yaml doctor --dial 010XXXXXXXX   두 번째 폰 확인
```
`logs/doctor.txt` 내용을 Claude나 Codex에게 그대로 붙여 넣으면 무엇을 고칠지 알려줍니다.

> USB 디버깅은 **전화 걸기·끊기**만 합니다. **통화 소리는 USB로 오지 않으므로** 아래 1번(블루투스) 또는 이어폰 단자 유선 연결이 따로 필요합니다.

## 1. 소리 길 연결

| 설정하는 곳 | 값 |
|---|---|
| Windows 설정 → 소리 → 앱 볼륨 및 장치 → "휴대폰과 연결"의 **출력** | `CABLE Input` |
| 같은 곳의 **입력(마이크)** | `CABLE-A Output` |
| config.yaml `audio.call_input` (상대 목소리 듣기) | `CABLE Output` |
| config.yaml `audio.ai_output` (내 녹음 내보내기) | `CABLE-A Input` |
| config.yaml `audio.monitor_output` (나도 같이 듣기) | 내 헤드셋 이름 |

```bat
python main.py devices      장치 이름 확인
python main.py meter        상대가 말할 때만 '말하는 중'이 뜨는지 확인 (speech_threshold 조정)
```

## 2. 내 녹음 넣기 (목소리, 변환 없음)

상담 멘트를 한 문장씩 읽고 **1초씩 쉬면서** 녹음합니다. 휴대폰 녹음 앱으로 녹음하면 됩니다.

```bat
python main.py clips 내녹음.mp3
```
- `clips/clip_001.wav …`(문장별 소리)와 `clips/clips.yaml`(번호별 받아 적은 글)이 생깁니다
- `clips.yaml`을 열어서 상대 목소리나 잡음 줄은 `use: false`로 바꾸고, 틀린 글자를 고칩니다
- 꼭 녹음해 둘 것:
  - 첫인사
  - AI 고지 ("이 통화는 AI 음성 비서가 먼저 안내드리고 있어요")
  - 맞장구 ("네~", "아 네")
  - "여보세요? 잘 들리세요?"
  - "확인해서 다시 연락드릴게요"
  - "앞으로 연락 안 드릴게요"
- 나중에 녹음을 더 하면 `python main.py clips 추가녹음.mp3`로 번호가 이어 붙습니다

## 3. 상황표 만들기 (scenarios.yaml)

상대가 이렇게 말하면 이 녹음으로 대답한다는 표입니다. `scenarios.example.yaml`에 설명과 예시가 있습니다.

**가장 쉬운 방법은 Codex에게 맡기는 것입니다.** 상담 스크립트 파일과 `clips/clips.yaml`을 같이 주고 이렇게 요청하세요.
> 상담스크립트.txt 와 clips/clips.yaml 을 보고 AGENTS.md 지침대로 scenarios.yaml 과 config.yaml 의 opening 을 만들어줘

예전 통화 녹음이 있으면 받아 적어서 상황표를 보강할 수도 있습니다.
```bat
python main.py train         recordings/ 폴더의 통화 녹음 → recordings/transcripts/*.txt (무료)
```
그다음 Codex에게 "transcripts 를 보고 scenarios.yaml 을 보강해줘"라고 요청하면 됩니다.

## 4. 연습 (전화 없이)

```bat
python main.py practice             내가 치과 직원 역할로 타이핑하면 어떤 녹음을 고르는지 확인
python main.py practice --voice     실제 녹음 소리까지 들으면서 확인
```
화면에 `(판단: 원장님 부재)`처럼 왜 그 대답을 골랐는지 나옵니다. 틀리면 `scenarios.yaml`의 `keywords`를 고치세요.

## 5. 고객 엑셀 연결

config.yaml `customers`에 파일 경로(`data/customers.xlsx`)와 내 엑셀의 열 이름(치과명, 담당자, 전화번호)을 적습니다.
상태, 메모, 통화일시 열은 없으면 자동으로 만듭니다. 엑셀 파일은 닫아 둔 상태에서 실행하세요.
CSV나 구글 시트도 됩니다. 구글 시트는 서비스 계정 키가 필요한데, 이것도 무료입니다.

```bat
python main.py list
```

## 6. 실제 통화

```bat
python main.py call 5        엑셀 5행에 전화
python main.py next          아직 안 한 고객부터 차례대로 (거절·수신거부 등은 건너뜀)
```
1. 고객 정보가 나오면 Enter를 누릅니다. 신호음이 울리는 동안 첫인사가 미리 준비됩니다.
2. 상대가 받으면 Enter를 누릅니다. 안 받으면 `n`을 누르면 '부재'로 기록됩니다.
3. 프로그램이 상담합니다. 화면에 대화가 실시간으로 나오고, `t`를 누르면 내가 직접 받습니다.
4. 끝나면 결과와 메모를 엑셀에 기록하고 녹취를 `logs/`에 저장합니다.

**갤럭시 S8 자동 걸기 (선택)**
1. 설정 → 휴대전화 정보 → 소프트웨어 정보 → 빌드번호를 7번 누릅니다.
2. 개발자 옵션 → USB 디버깅을 켭니다.
3. USB로 PC에 연결합니다.
4. config에 `dialer.mode: "adb"`를 적습니다.

그러면 프로그램이 S8의 010 번호로 직접 걸고 끊습니다.

**전화기 2대** — 방법은 세 가지입니다. 프로그램은 하나로, 창 두 개에서 실행합니다
(첫 번째 창: `python main.py next`, 두 번째 창: `python main.py --config config2.yaml next`).

| 방법 | 준비물 | 장점 / 단점 |
|---|---|---|
| ① PC 2대 | 노트북 한 대 더 | 설정이 제일 쉬움. 각 PC에 "휴대폰과 연결" 앱으로 폰 1대씩 |
| ② 이어폰 단자 유선 연결 (PC 1대) | 폰마다 **4극 이어폰 분배 케이블 + USB 사운드카드** (합쳐서 1~2만 원 정도) | 소리가 제일 깨끗하고 끊김이 없음. "휴대폰과 연결" 앱과 가상 케이블도 필요 없음. 갤럭시 S8은 이어폰 단자가 있어서 바로 됨 (단자 없는 폰은 C타입 이어폰 젠더 추가) |
| ③ 폰 1대는 블루투스, 1대는 유선 (PC 1대) | 유선 1세트 | ①과 ②를 섞은 방법 |

②번 연결: 폰 이어폰 단자 → 분배 케이블 → 초록(헤드폰) 쪽을 USB 사운드카드 **마이크 입력**에, 분홍(마이크) 쪽을 사운드카드 **헤드폰 출력**에 꽂습니다.
그다음 config2.yaml에서 `call_input`과 `ai_output`을 둘 다 그 USB 사운드카드 이름으로 지정합니다.
두 폰 모두 USB로 자동 걸기를 하려면 `adb devices`에 나오는 일련번호를 각 설정 파일의 `dialer.adb_serial`에 적습니다.

> "휴대폰과 연결" 앱 하나로 폰 2대를 **동시에** 통화시키는 방법은 없습니다. 앱이 한 번에 폰 한 대만 연결하기 때문입니다.
> 폰 안에서만 처리하는 방법(폰이 직접 통화 소리를 녹음·재생)도 안드로이드가 막아 두어서, 폰을 루팅하지 않는 한 불가능합니다.

## 꼭 알아두실 것

- **AI 고지**: 2026년 1월 시행된 「인공지능 기본법」에 따라 첫인사 뒤에 AI 고지 녹음을 넣도록 해 두었습니다.
  상대가 "AI냐"고 물으면 사실대로 답하고 사람에게 넘깁니다. 사람인 척하는 녹음은 상황표에 넣지 마세요. 이 안내는 법률 자문이 아닙니다.
- **녹음은 본인 목소리만** 쓰세요.
- **개인정보**: 무료 모드는 통화 음성과 고객 정보가 **내 PC 밖으로 나가지 않습니다**. `clips/`, `logs/`, `data/`는 git에 올라가지 않습니다.
- **응답 속도**: 내 PC에서 받아 적는 데 보통 1~3초 걸립니다. 맞장구가 그 사이를 메웁니다.
  느리면 `stt.local_model`을 `base`로 바꾸세요. NVIDIA 그래픽카드가 있으면 `device: "cuda"`로 바꾸면 훨씬 빨라집니다.
- 무료 모드는 **녹음해 둔 말만** 할 수 있습니다. 처음 몇 통은 옆에서 듣다가 이상하면 `t`를 누르세요.
  자주 넘어오는 질문은 대답을 녹음해서 상황표에 추가하면 점점 혼자 처리하는 통화가 늘어납니다.

## (선택) 유료 AI 모드
config.yaml에서 `engine: "ai"`로 바꾸면 쓸 수 있습니다. 녹음에 없는 말도 AI(Claude)가 만들어서 내 복제 목소리(ElevenLabs)로 말합니다.
`pip install anthropic elevenlabs`를 실행하고 `.env`에 API 키를 넣어야 합니다. 관련 명령은 `script`, `clone-voice`, `say`입니다.

## 파일 구조
```
call-agent/
  main.py                 실행 명령 모음
  config.example.yaml     설정 견본 → config.yaml
  scenarios.example.yaml  상황표 견본 → scenarios.yaml
  AGENTS.md               Codex 등 코딩 AI용 작업 지침
  callagent/
    audio.py      소리 입출력, 말 끝 감지, 잡음 적응, 끼어들기
    clips.py      내 녹음을 문장별로 자르고 그대로 재생
    local_stt.py  무료 음성 인식 (내 PC의 Whisper)
    rules.py      무료 상담 두뇌 (상황표대로 대답 + 요약)
    session.py    통화 한 건 진행 (미리 준비, 맞장구)
    customers.py  엑셀/CSV/구글 시트
    dialer.py     수동 또는 adb 자동 걸기
    engine.py     무료/유료 선택
    brain.py, voice.py, trainer.py   유료 AI 모드용
  tests/          소리 장치 없이 도는 테스트 (python -m pytest tests -q)
```
