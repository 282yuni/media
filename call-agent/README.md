# 치과 1차 콜 AI 대행

내 통화 녹음으로 **내 말투와 상황별 대답**을 배우고, **내 목소리를 복제**해서
내가 전화를 걸면 상대가 받았을 때 AI가 대신 상담하는 프로그램입니다.

```
[휴대폰] ─미러링/연결 앱─ [PC]
                            │  상대 목소리 → 가상 케이블 → 받아 적기 (ElevenLabs)
                            │                               ↓
                            │                  내 플레이북대로 대답 생각 (Claude)
                            │                               ↓
                            │  가상 케이블 ← 내 목소리로 읽기 (ElevenLabs 복제 음성)
                            └─ 통화 끝 → 요약 → 고객 시트에 상태·메모 기록 + 녹취 저장
```

- 통화 중 언제든 `t` + Enter → AI가 멈추고 **내가 바로 이어서 통화**
- 상대가 "담당자 바꿔주세요"라고 하거나 AI가 답하기 어려우면 **알림음이 울리고 나에게 넘김**
- 상대가 AI가 말하는 중에 끼어들면 AI가 말을 멈추고 들음
- 통화마다 녹취(대본)를 `logs/` 에 저장하고, 요약해서 엑셀/구글 시트의 상태·메모 칸에 기록

---

## 1. 준비물

| 항목 | 용도 | 비용 |
|---|---|---|
| Python 3.10 이상 (Windows PC) | 프로그램 실행 | 무료 |
| [Anthropic API 키](https://console.anthropic.com) | AI 상담 두뇌 (Claude) | 사용량만큼 |
| [ElevenLabs](https://elevenlabs.io) 계정 + API 키 | 목소리 복제, 음성 인식, 음성 합성 | 목소리 복제는 Starter 요금제 이상 |
| [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) **2개** (CABLE + CABLE-A, 또는 VoiceMeeter) | 통화 소리를 프로그램으로 주고받기 | 무료/기부 |
| 휴대폰 ↔ PC 통화 연결 | PC에서 통화하기 | 아래 참고 |

### 휴대폰 통화를 PC로 연결하는 방법
그냥 화면만 미러링하면(scrcpy 등) **통화 소리는 PC로 안 넘어옵니다.** 통화 소리가 PC 스피커/마이크로 오가야 합니다.
- **삼성/안드로이드 + Windows**: Windows "휴대폰과 연결(Phone Link)" 앱 → 블루투스로 연결 → PC에서 통화하기 켜기
- 또는 휴대폰 ↔ PC를 블루투스 헤드셋처럼 연결해 주는 다른 앱
- 확인 방법: PC에서 전화를 걸어 **PC 스피커에서 상대 목소리가 나오고, PC 마이크로 말하면 상대가 들으면** 준비 완료

## 2. 설치

```bat
cd call-agent
pip install -r requirements.txt
copy .env.example .env          (메모장으로 열어 API 키 2개 입력)
copy config.example.yaml config.yaml
```

## 3. 소리 길 연결 (제일 중요)

가상 케이블 2개를 이렇게 연결합니다.

| 어디서 | 설정 | 값 |
|---|---|---|
| Windows 소리 설정 → Phone Link(통화 앱)의 **출력(스피커)** | | `CABLE Input` |
| Windows 소리 설정 → Phone Link(통화 앱)의 **입력(마이크)** | | `CABLE-A Output` |
| config.yaml `audio.call_input` | 상대 목소리를 듣는 곳 | `CABLE Output` |
| config.yaml `audio.ai_output` | AI 목소리를 내보내는 곳 | `CABLE-A Input` |
| config.yaml `audio.monitor_output` | 내 헤드셋 (AI 목소리를 나도 듣기) | 내 헤드셋 이름 |

> 앱별 장치 지정: Windows 설정 → 시스템 → 소리 → 고급 → **앱 볼륨 및 장치 기본 설정**

```bat
python main.py devices      장치 이름 확인 (이름 일부만 config에 적어도 됨)
python main.py meter        통화 중 상대가 말할 때 막대가 '말하는 중'으로 바뀌는지 확인
```
상대가 말 안 할 때도 '말하는 중'이 뜨면 `speech_threshold` 를 올리고, 말해도 안 뜨면 내리세요.

> **내가 직접 받을 때(t 키)**: 위 연결 상태에서는 내 헤드셋 마이크가 통화로 안 들어갑니다.
> VoiceMeeter를 쓰면 "AI 목소리 + 내 마이크"를 한 가상 마이크로 합칠 수 있어서 버튼 없이 바로 이어받을 수 있습니다.
> 간단하게는 `t` 를 누른 뒤 휴대폰 연결 앱에서 통화를 휴대폰으로 넘겨 받으세요.

## 4. 내 목소리 복제

`voice_samples/` 폴더를 만들고 **내 목소리만** 들어간 녹음 1~3분을 넣습니다.
(통화 녹음은 상대 목소리가 섞여서 품질이 떨어져요. 평소 콜 하듯이 대본을 읽어 녹음하는 게 제일 좋습니다.)

```bat
python main.py clone-voice
python main.py say "안녕하세요, 밝은미소치과 맞으시죠?"     내 헤드셋으로 들어보기
```

## 5. 내 통화 녹음으로 학습 → 플레이북

`recordings/` 폴더에 1차 콜 통화 녹음 파일(m4a, mp3, wav 등)을 넣습니다. 많을수록 좋아요 (10~30통 권장).
거절, 부재, 바쁨, 가격 문의, 자료 요청처럼 **여러 상황이 골고루** 들어가면 좋습니다.

```bat
python main.py train
```

- `recordings/transcripts/` 에 통화별 대본이 생기고
- `playbook.md` 가 생깁니다: 말투, 통화 흐름, **상황별로 상대가 이렇게 말하면 → 내가 이렇게 대답했다** 정리
- **꼭 열어서 직접 고치세요.** 특히 6번 "대본에서 확인 안 된 것"(가격, 조건 등)을 채워야 AI가 지어내지 않고 답합니다
- 녹음을 더 넣고 다시 `train` 하면 내가 고친 내용은 유지하면서 보강합니다

## 6. 연습 (전화 없이)

```bat
python main.py practice              내가 치과 직원 역할로 타이핑 → AI 대답 확인
python main.py practice --voice      AI 대답을 내 목소리로 들으면서
python main.py practice --row 5      고객 시트 5행 정보를 넣고 연습
```
대답이 마음에 안 들면 `playbook.md` 를 고치고 다시 연습하세요.

## 7. 고객 시트 연결

config.yaml `customers` 에서 고릅니다.

- **엑셀**: `source: "excel"`, `path: "data/customers.xlsx"` (파일을 열어둔 상태면 저장이 안 되니 닫아두세요)
- **CSV**: `source: "csv"`
- **구글 시트**: `source: "google"` + `google_sheet_url`
  1. [Google Cloud 콘솔](https://console.cloud.google.com)에서 서비스 계정 만들기 → JSON 키 다운로드 → `call-agent/google-service-account.json` 으로 저장
  2. Google Sheets API 사용 설정
  3. 구글 시트 공유에 서비스 계정 이메일(…@….iam.gserviceaccount.com)을 **편집자**로 추가

`columns` 에서 내 시트의 실제 열 이름(예: 치과명, 담당자, 전화번호)을 적어주세요. 상태/메모/통화일시 열이 없으면 자동으로 추가합니다.

```bat
python main.py list
```

## 8. 실제 통화

```bat
python main.py call 5        시트 5행에 전화
python main.py next          아직 안 한 고객부터 차례대로 (거절/계약/수신거부 등은 건너뜀)
```

1. 고객 정보가 뜨면 Enter → 번호가 클립보드에 복사됨 → 내가 전화 걸기
   (config `dialer.mode: "adb"` + USB 디버깅이면 자동으로 걸고 끊어줌)
2. **상대가 받으면 Enter** (안 받으면 `n` → '부재'로 기록)
3. AI가 인사하고 상담 진행. 화면에 대화가 실시간으로 나옴
   - `t` + Enter: 내가 직접 받기 / `e` + Enter: 종료
4. 끝나면 요약이 나오고, Enter 하면 시트에 상태·메모 기록. 녹취는 `logs/` 에 저장

## 9. 꼭 알아두실 것

- **AI 사용 고지**: 2026년 1월부터 시행된 「인공지능 기본법」은 생성형 AI 결과물, 특히 실제와 구분하기 어려운 음성 등을
  AI가 만든 것이라고 알리도록 하고 있습니다. 그래서 `agent.ai_disclosure` 에 고지 문장을 기본으로 넣어 두었습니다.
  또 상대가 "AI냐, 사람이냐"고 직접 물으면 **AI는 항상 사실대로 답하도록** 고정되어 있습니다(속이는 통화는 신고·분쟁 위험이 큽니다).
  고지 문구를 바꾸거나 빼기 전에는 회사나 법률 전문가와 확인하세요. (이 안내는 법률 자문이 아닙니다.)
- **목소리 복제는 본인 목소리만** 하세요.
- **개인정보**: 통화 음성과 고객 정보(치과명, 담당자명)가 ElevenLabs와 Anthropic 서버로 전송됩니다. 회사 개인정보 방침을 확인하세요.
  `logs/`, `recordings/`, `data/` 는 git에 올라가지 않게 막아 두었습니다.
- **수신거부**: 상대가 연락하지 말라고 하면 요약 상태가 '수신거부'가 되고 `next` 에서 자동으로 건너뜁니다.
- **응답 속도**: 상대 말이 끝나고 AI가 대답 시작하기까지 보통 1.5~3초 걸립니다. 화면에 `(응답 지연 N초)` 가 표시됩니다.
  너무 느리면 `brain.effort` 를 `low` 로 유지하고, `audio.end_silence_sec` 를 0.6 정도로 줄여보세요.
- 처음 몇 통은 **옆에서 듣고 있다가 이상하면 바로 `t`** 로 이어받으세요.

## 파일 구조

```
call-agent/
  main.py              실행 명령 모음
  config.example.yaml  설정 견본 (config.yaml 로 복사해서 사용)
  callagent/
    audio.py           가상 케이블 입출력, 말 끝 감지, 끼어들기
    voice.py           ElevenLabs 음성 인식 / 목소리 복제 / 음성 합성
    brain.py           Claude 상담 응답 + 통화 요약
    trainer.py         녹음 → 대본 → playbook.md
    customers.py       엑셀 / CSV / 구글 시트 읽기·쓰기
    dialer.py          전화 걸기 (수동 또는 adb)
    session.py         통화 한 건 진행
```
