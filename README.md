# Alpha-Flow 2026

국내 상장 대형주/수급주(KOSPI200 + KOSDAQ150) 대상 Daily 투자 모니터링 및
이메일 자동 리포트 시스템. `docs/alpha_flow_system_spec.pdf` 기획서를 기반으로
구현한 **Phase 1 (의사결정 지원 리포트)** 단계입니다.

⚠️ **본 시스템은 투자 자문이 아닙니다.** 규칙 기반으로 생성된 참고 자료이며,
실제 매매를 자동으로 실행하지 않습니다. 최종 투자 판단과 책임은 본인에게 있습니다.

## 동작 방식

1. `core/market_analyzer.py` — KOSPI/KOSDAQ 지수 이동평균(5/20/60일)으로 시장 상태 판단
2. `core/stock_screener.py` — KOSPI200+KOSDAQ150 유니버스에서 외국인·기관 동시 순매수
   지속 종목을 걸러내고, 거래대금 급증 여부로 S/A 등급 산출
3. `core/sheets_client.py` — Google Sheets에서 보유 종목/자금 현황을 읽어온다 (보유 종목 DB)
4. `core/portfolio_manager.py` — 보유 종목 손절/트레일링스탑/목표가/신규 편입/SWAP 판정.
   보유 종목이 0개(완전 공백)일 때만 신규 편입 후보를 추천한다.
5. `core/ai_advisor.py` — (선택) Gemini로 판정 결과에 "참고의견"을 병기. 등급/판정 값 자체는
   바꾸지 않으며, API 키 미설정 시 이 단계는 건너뛴다.
6. `core/email_sender.py` — 판정 결과(+ AI 참고의견)를 리포트로 만들어 발송
7. `main.py` — 위 과정을 순서대로 실행하는 오케스트레이터. 실행 후 트레일링 스탑 기준
   (peak_price)을 Google Sheets에 다시 기록한다.
8. `.github/workflows/daily_report.yml` — 평일 16:30 KST에 GitHub Actions가 자동 실행
   (컴퓨터를 켜둘 필요 없음, GitHub 클라우드에서 실행됨)

## ⚠️ 기획서에 수치가 명시되지 않아 개발 과정에서 채택한 기본값

기획서(PDF)는 판정 로직을 정성적으로만 설명하고 있어, 아래 값들은 코드 구현을 위해
임의로 정한 기본값입니다. **실전 투입 전 반드시 본인 투자 기준에 맞게 검토/수정하세요.**
(`config/config.py`에서 전부 수정 가능)

| 항목 | 기본값 | 위치 |
|---|---|---|
| 손절선 | 진입가 대비 -7% | `STOP_LOSS_PCT` |
| 트레일링 스탑 | 보유 후 고점 대비 -8% | `TRAILING_STOP_PCT` |
| 1차 목표가(익절) | 진입가 대비 +15%, 50% 익절 | `TARGET_PROFIT_PCT` / `PARTIAL_SELL_RATIO` |
| S등급 조건 | 외국인·기관 3일 연속 동시 순매수 + 거래대금 20일 평균 대비 2배↑ | `NET_BUY_STREAK_DAYS` / `VOLUME_SURGE_MULTIPLIER` |
| A등급 조건 | 3일 연속 동시 순매수 O, 거래대금 급증 조건 미달 | 위와 동일 |
| 정배열/역배열 | MA5 > MA20 > MA60 (상승) / 역순 + 현재가 이탈 (하락) | `market_analyzer.py` |
| 스캔 유니버스 | KOSPI200 + KOSDAQ150 | `UNIVERSE_INDEX_CODES` |

## 알려진 제약사항

- **외국인/기관 순매수 데이터는 pykrx(비공식 KRX 스크래퍼)로 조회합니다.** 공식 API가
  아니므로 KRX 웹사이트 구조 변경 시 동작이 깨질 수 있습니다. Phase 2에서 한국투자증권
  Open API 등 공식 데이터 소스로 전환을 권장합니다 (기획서 로드맵 참고).
- **Google Sheets의 수량/평단가/매매 단계는 자동 반영되지 않습니다.** 실제로 매수·매도를
  체결한 뒤에는 Sheets의 `Holdings` 탭을 직접 수정해야 다음 리포트에 정확히 반영됩니다.
  (트레일링 스탑 기준 고점(peak_price)만 매일 자동 갱신되어 Sheets에 다시 기록됩니다.)
- 종목 스캐닝은 유니버스(약 350종목) 전체를 순회하므로 실행에 수 분이 걸릴 수 있습니다.
- 공휴일 등 휴장일 처리는 단순화되어 있습니다(거래일 존재 여부만 확인).
- **AI(Gemini) 참고의견은 보조 설명일 뿐 매매 판단에 반영되지 않습니다.** `GEMINI_API_KEY`가
  없으면 이 기능은 자동으로 건너뛰며, 리포트의 등급/판정은 항상 규칙 기반 결과입니다.

## Google Sheets 설정 가이드 (보유 종목 DB)

1. **Google Cloud 프로젝트 생성 및 API 활성화**
   - [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성
   - "API 및 서비스 > 라이브러리"에서 **Google Sheets API** 활성화
2. **서비스 계정 생성**
   - "API 및 서비스 > 사용자 인증 정보 > 사용자 인증 정보 만들기 > 서비스 계정"
   - 생성된 서비스 계정에서 "키 추가 > JSON" 다운로드 (이 JSON 파일 내용 전체가
     `GOOGLE_SHEETS_CREDENTIALS` 값이 됩니다)
3. **Google Sheet 준비**
   - 새 스프레드시트 생성, 아래 두 탭(시트)을 정확한 이름으로 만듭니다.
     - `Holdings` 탭 1행(헤더): `ticker | name | grade | quantity | avg_price | entry_stage | peak_price | entry_date`
       - `ticker` 열은 **서식을 "일반 텍스트"로 지정**하세요 (숫자 서식이면 "005930"의
         앞자리 0이 사라집니다).
       - 보유 종목이 없으면 헤더만 두고 데이터 행은 비워둡니다.
     - `Meta` 탭: A/B 2열로 `total_capital`/금액, `cash`/금액, `last_updated`/(빈 값) 3행
   - 다운로드한 JSON의 `client_email` 값(서비스 계정 이메일)을 이 스프레드시트에
     **"편집자" 권한으로 공유**합니다.
   - 스프레드시트 URL `https://docs.google.com/spreadsheets/d/{여기}/edit`에서
     `{여기}` 부분이 `GOOGLE_SHEET_ID`입니다.
4. `.env` 또는 GitHub Secrets에 `GOOGLE_SHEETS_CREDENTIALS`(JSON 전체 내용),
   `GOOGLE_SHEET_ID`를 등록합니다.

## (선택) AI 참고의견 설정 가이드

1. [Google AI Studio](https://aistudio.google.com/)에서 API 키 발급
2. `.env` 또는 GitHub Secrets에 `GEMINI_API_KEY` 등록 (모델은 기본값 `gemini-3.5-flash`,
   바꾸려면 `GEMINI_MODEL` 지정)
3. 키를 등록하지 않으면 AI 참고의견 없이 기존과 동일한 규칙 기반 리포트만 발송됩니다.

## 로컬 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env   # 이후 .env 파일에 실제 값 입력 (이메일, Google Sheets, Gemini)
python main.py
```

Gmail 앱 비밀번호는 일반 로그인 비밀번호가 아닌 별도 발급 값입니다.
Google 계정 > 보안 > 2단계 인증 활성화 후 "앱 비밀번호"에서 발급받으세요.

## 자동 실행(GitHub Actions) 설정

1. 저장소 **Settings > Secrets and variables > Actions**에서 아래 Secret 등록
   - `EMAIL_ADDRESS`
   - `EMAIL_APP_PASSWORD`
   - `EMAIL_RECEIVER`
   - `GOOGLE_SHEETS_CREDENTIALS`, `GOOGLE_SHEET_ID` — 위 "Google Sheets 설정 가이드" 참고
   - (선택) `GEMINI_API_KEY` — AI 참고의견 기능 사용 시
   - (선택) `KRX_ID`, `KRX_PW` — data.krx.co.kr 회원 계정. 클라우드(GitHub Actions) IP에서
     KRX가 익명 요청을 차단하는 경우, 로그인 세션을 사용해 우회를 시도합니다.
2. 이후 평일 16:30 KST에 자동 실행되며, **Actions** 탭에서 `workflow_dispatch`로 수동 실행도 가능
3. Private 저장소 기준 GitHub Actions 무료 한도(월 2,000분) 내에서 충분히 운용 가능

## 로드맵

- Phase 2: 한국투자증권 Open API 연동, 데이터 정밀도 향상
- Phase 3: 텔레그램 1-Click 매매 연동, Streamlit/Dash 대시보드

자세한 투자 원칙 및 산식은 `docs/alpha_flow_system_spec.pdf` 참고.
