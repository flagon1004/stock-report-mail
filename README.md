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
3. `core/portfolio_manager.py` — 보유 종목 손절/트레일링스탑/목표가/신규 편입/SWAP 판정
4. `core/email_sender.py` — 판정 결과를 리포트로 만들어 Gmail로 발송
5. `main.py` — 위 과정을 순서대로 실행하는 오케스트레이터
6. `.github/workflows/daily_report.yml` — 평일 16:30 KST에 GitHub Actions가 자동 실행
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
- **portfolio.json의 수량/평단가/매매 단계는 자동 반영되지 않습니다.** 실제로 매수·매도를
  체결한 뒤에는 `config/portfolio.json`을 직접 수정해야 다음 리포트에 정확히 반영됩니다.
  (트레일링 스탑 기준 고점(peak_price)만 매일 자동 갱신되어 커밋됩니다.)
- 종목 스캐닝은 유니버스(약 350종목) 전체를 순회하므로 실행에 수 분이 걸릴 수 있습니다.
- 공휴일 등 휴장일 처리는 단순화되어 있습니다(거래일 존재 여부만 확인).

## 로컬 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env   # 이후 .env 파일에 실제 Gmail 발신 계정/앱 비밀번호 입력
python main.py
```

Gmail 앱 비밀번호는 일반 로그인 비밀번호가 아닌 별도 발급 값입니다.
Google 계정 > 보안 > 2단계 인증 활성화 후 "앱 비밀번호"에서 발급받으세요.

## 자동 실행(GitHub Actions) 설정

1. 저장소 **Settings > Secrets and variables > Actions**에서 아래 Secret 등록
   - `EMAIL_ADDRESS`
   - `EMAIL_APP_PASSWORD`
   - `EMAIL_RECEIVER`
   - (선택) `KRX_ID`, `KRX_PW` — data.krx.co.kr 회원 계정. 클라우드(GitHub Actions) IP에서
     KRX가 익명 요청을 차단하는 경우, 로그인 세션을 사용해 우회를 시도합니다.
2. 이후 평일 16:30 KST에 자동 실행되며, **Actions** 탭에서 `workflow_dispatch`로 수동 실행도 가능
3. Private 저장소 기준 GitHub Actions 무료 한도(월 2,000분) 내에서 충분히 운용 가능

## 로드맵

- Phase 2: 한국투자증권 Open API 연동, 데이터 정밀도 향상
- Phase 3: 텔레그램 1-Click 매매 연동, Streamlit/Dash 대시보드

자세한 투자 원칙 및 산식은 `docs/alpha_flow_system_spec.pdf` 참고.
