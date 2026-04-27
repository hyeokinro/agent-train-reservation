# 열차 좌석 알림 봇 (SRT + KTX)

SRT / KTX 매진 열차를 주기적으로 감시해서, 빈 좌석이 생기면 **즉시 예약(결제 제외)**하고 텔레그램으로 알림을 보내는 봇입니다.

> ⚠️ 봇이 잡은 예약은 **일정 시간 내 결제하지 않으면 자동 취소**됩니다. 알림을 받은 즉시 앱에서 결제하세요.

---

## 목차

1. [회원번호 확인법](#1-회원번호-확인법)
2. [텔레그램 봇 만들기](#2-텔레그램-봇-만들기)
3. [GitHub Secrets 설정](#3-github-secrets-설정)
4. [로컬 테스트](#4-로컬-테스트)
5. [config.json 수정법](#5-configjson-수정법)
6. [SRT vs KTX 차이점](#6-srt-vs-ktx-차이점)
7. [GitHub Actions cron 한계](#7-github-actions-cron-한계)
8. [알려진 한계](#8-알려진-한계)
9. [주의사항](#9-주의사항)

---

## 1. 회원번호 확인법

**SRT**
1. SRT 앱 또는 [etk.srail.kr](https://etk.srail.kr) 로그인
2. 마이페이지 → 회원정보 → 회원번호 (10자리 숫자)

**코레일 (KTX)**
1. 코레일 앱 또는 [letskorail.com](https://www.letskorail.com) 로그인
2. 마이페이지 → 회원번호 확인
3. 이메일 또는 전화번호로도 로그인 가능

---

## 2. 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 검색 후 채팅 시작
2. `/newbot` 입력 → 봇 이름과 username 설정
3. 봇 토큰 발급 (예: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`)
4. 알림을 받을 채팅방에서 봇과 대화 시작 (1:1 또는 그룹방에 봇 초대)
5. 아래 URL에서 `chat_id` 확인:
   ```
   https://api.telegram.org/bot<봇토큰>/getUpdates
   ```
   응답의 `"chat": {"id": -1234567890}` 값이 CHAT_ID

---

## 3. GitHub Secrets 설정

GitHub 레포지토리 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 이름 | 설명 | 필요 여부 |
|---|---|---|
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 | 필수 |
| `CHAT_ID` | 알림받을 채팅방 ID | 필수 |
| `SRT_ID` | SRT 회원번호 | SRT target이 있을 때만 |
| `SRT_PASSWORD` | SRT 비밀번호 | SRT target이 있을 때만 |
| `KTX_ID` | 코레일 회원번호/이메일/전화 | KTX target이 있을 때만 |
| `KTX_PASSWORD` | 코레일 비밀번호 | KTX target이 있을 때만 |

사용하지 않는 쪽 (SRT만 쓴다면 KTX_ID, KTX_PASSWORD)은 등록 안 해도 됩니다.

---

## 4. 로컬 테스트

```bash
# 가상환경 생성 (선택)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정 (SRT만 사용하는 경우 예시)
export SRT_ID="회원번호"
export SRT_PASSWORD="비밀번호"
export TELEGRAM_TOKEN="봇토큰"
export CHAT_ID="채팅방ID"

# 실행
python check_trains.py

# 디버그 모드 (예약 없이 train/reservation 객체 속성 출력 후 종료)
DEBUG=1 python check_trains.py
```

> 💡 테스트 시 빈 좌석이 많은 비인기 시간대 열차로 config.json을 수정하면 예약 성공 플로우를 확인할 수 있습니다. **테스트 후 SRT 앱에서 반드시 취소하세요.**

---

## 5. config.json 수정법

`config.json`의 `targets` 배열만 수정하면 됩니다. **코드 변경 불필요.**

```json
{
  "targets": [
    {
      "type": "SRT",
      "label": "전주 출장",
      "date": "20260430",
      "dep": "수서",
      "arr": "전주",
      "dep_time": "190000",
      "train_no": "683",
      "passengers": 1
    },
    {
      "type": "KTX",
      "label": "부산 가족여행",
      "date": "20260505",
      "dep": "서울",
      "arr": "부산",
      "dep_time": "080000",
      "train_no": "",
      "passengers": 3
    }
  ]
}
```

| 필드 | 설명 | 예시 |
|---|---|---|
| `type` | `"SRT"` 또는 `"KTX"` | `"SRT"` |
| `label` | 텔레그램 알림에 표시할 이름 | `"전주 출장"` |
| `date` | 탑승 날짜 (YYYYMMDD) | `"20260430"` |
| `dep` | 출발역 | `"수서"`, `"서울"` |
| `arr` | 도착역 | `"전주"`, `"부산"` |
| `dep_time` | 출발 시각 이후로 조회 (HHMMSS) | `"190000"` |
| `train_no` | 특정 열차번호. 빈 값이면 조건 맞는 첫 열차 | `"683"` 또는 `""` |
| `passengers` | 탑승 인원 수 | `1` |

**변경 예시:**
- 새 열차 추가: `targets` 배열에 항목 추가 후 commit & push
- 감시 중단: 해당 항목 삭제
- 인원 변경: `passengers` 값 수정
- 특정 열차 안 가림: `train_no`를 `""` (빈 문자열)로
- SRT ↔ KTX 전환: `type` 값만 변경

---

## 6. SRT vs KTX 차이점

| 항목 | SRT | KTX |
|---|---|---|
| 출발역 | 수서, 동탄, 지제 | 서울, 용산, 광명 등 |
| 예약 사이트 | [etk.srail.kr](https://etk.srail.kr) | [letskorail.com](https://www.letskorail.com) |
| 회원체계 | SRT 회원 (별도 가입) | 코레일 회원 |
| 환경변수 | `SRT_ID`, `SRT_PASSWORD` | `KTX_ID`, `KTX_PASSWORD` |

---

## 7. GitHub Actions cron 한계

- **최소 실행 간격: 5분** (`*/5 * * * *`)
- GitHub 서버 부하에 따라 최대 수 분 지연 가능 (즉각성 보장 안 됨)
- **무료 플랜 제한**: public 레포는 무제한 / private 레포는 월 2,000분
- Actions 탭 → **Run workflow** 버튼으로 수동 즉시 실행 가능

---

## 8. 알려진 한계

### `train_no` 빈값일 때 중복 예약 가능성

`train_no`를 빈 문자열(`""`)로 설정하면, 봇은 조건에 맞는 **첫 번째 열차**를 잡습니다. 이 경우 중복 예약 방지 로직이 동작하지 않습니다 — 열차번호를 모르면 기존 예약과 대조할 수 없기 때문입니다.

**실제 상황:** 5분마다 cron이 실행되고, 1회차에 A 열차를 잡았는데 미결제로 자동 취소된 뒤 2회차에 B 열차를 또 잡는 식으로 중복이 생길 수 있습니다.

**권장 대응:**
- 가능하면 `train_no`를 지정하세요.
- 빈값을 쓸 경우, 텔레그램 알림이 오면 즉시 결제하거나 SRT/코레일 앱에서 중복 예약 여부를 확인하세요.

---

## 9. 주의사항

- **예약 후 미결제**: 봇이 잡은 예약은 일정 시간(SRT 약 20분, KTX 약 30분) 내 결제 안 하면 자동 취소됩니다
- **API 제한**: 너무 잦은 호출은 SRT/코레일 서버에서 IP 제한이 걸릴 수 있습니다. 5분 이하 간격은 권장하지 않습니다
- **과거 날짜**: `date`가 오늘 이전이면 자동으로 스킵합니다 (로그인도 안 함)
