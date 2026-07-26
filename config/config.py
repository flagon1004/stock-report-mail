"""
Alpha-Flow 2026 설정 파일
- 이메일, 자금, 리스크 파라미터, 종목 유니버스 등 시스템 전역 설정
- 민감정보(이메일 비밀번호)는 .env 파일 / GitHub Secrets에서 로드하며 이 파일에는 절대 하드코딩하지 않는다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 이메일 설정 ──────────────────────────────────────────────
EMAIL_SENDER = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "kbrothers.han@gmail.com")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ── 자금 설정 ────────────────────────────────────────────────
TOTAL_CAPITAL = 100_000_000  # 1억원

# ── 포트폴리오 제약 ──────────────────────────────────────────
MAX_HOLDINGS = 5  # 최대 보유 종목 수 (가변, 최대 5개 이내)

# 등급별 최대 비중 (총자산 대비)
S_GRADE_MAX_WEIGHT = 0.30          # S등급: 최대 30%
A_GRADE_MAX_WEIGHT_MIN = 0.15      # A등급: 15%
A_GRADE_MAX_WEIGHT_MAX = 0.20      # A등급: ~20%

# 분할 매수 비율 (목표 비중 대비)
FIRST_ENTRY_RATIO = 0.5   # 1차 탐색 매수: 목표 비중의 50%
SECOND_ENTRY_RATIO = 0.5  # 2차 불타기: 나머지 50%

# ── 리스크 관리 기준값 (PDF 명세서에 수치가 명시되지 않아 채택한 기본값)
# 주의: 실전 투입 전 반드시 검토/조정할 것. README 참고.
STOP_LOSS_PCT = -0.07        # 손절선: 진입가 대비 -7%
TRAILING_STOP_PCT = -0.08    # 트레일링 스탑: 보유 후 고점 대비 -8%
TARGET_PROFIT_PCT = 0.15     # 1차 목표가: 진입가 대비 +15%
PARTIAL_SELL_RATIO = 0.5     # 1차 목표가 도달 시 익절 비율 50%

# ── 종목 등급 판정 기준 (PDF에 수치 미명시, 채택한 기본값) ──────
NET_BUY_STREAK_DAYS = 3          # 외국인·기관 동시 순매수 지속 일수 (S등급 조건)
VOLUME_SURGE_MULTIPLIER = 2.0    # 거래대금이 20일 평균 대비 몇 배 이상이면 급증으로 판단

# ── 이동평균 기간 ────────────────────────────────────────────
MA_SHORT = 5
MA_MID = 20
MA_LONG = 60

# ── 시장 상태별 권장 현금 비중 (명세서 표 2.1 그대로 반영) ───────
MARKET_STATE_RULES = {
    "상승장": {"stock_min": 0.70, "stock_max": 1.00, "cash_min": 0.00, "cash_max": 0.30},
    "중립": {"stock_min": 0.50, "stock_max": 0.70, "cash_min": 0.30, "cash_max": 0.50},
    "하락장": {"stock_min": 0.00, "stock_max": 0.30, "cash_min": 0.70, "cash_max": 1.00},
}

# ── 종목 스캐닝 유니버스 ─────────────────────────────────────
# pykrx 지수 구성종목 코드: KOSPI200 = "1028", KOSDAQ150 = "2203"
UNIVERSE_INDEX_CODES = {
    "KOSPI200": "1028",
    "KOSDAQ150": "2203",
}

# ── 지수 티커 (yfinance) ─────────────────────────────────────
INDEX_TICKERS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
}

# ── 파일 경로 ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "config", "portfolio.json")
