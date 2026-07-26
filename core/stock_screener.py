"""
stock_screener.py
KOSPI200 + KOSDAQ150 유니버스에서 "외국인·기관 동시 순매수(양매수)"가
지속되는 종목을 걸러내고, 거래대금 급증 여부로 S/A 등급을 매긴다.

1차 필터: 최근 config.NET_BUY_STREAK_DAYS 거래일 동안 외국인·기관 모두
          매일 순매수(금액 기준 양수)를 기록한 종목만 통과.
등급:
  S등급: 1차 필터 통과 + 당일 거래대금이 최근 20일 평균 대비
         config.VOLUME_SURGE_MULTIPLIER배 이상
  A등급: 1차 필터는 통과했으나 거래대금 급증 조건은 미달

주의: pykrx는 한국거래소(KRX) 웹사이트를 스크래핑하는 비공식 라이브러리라
      호출 1회당 지연이 있고, 유니버스 전체(약 350종목)를 스캔하면
      실행에 수 분이 걸릴 수 있다. GitHub Actions 자동 실행 기준으로는
      허용 범위이나, 로컬에서 반복 테스트할 때는 시간이 걸릴 수 있다.
"""
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

from pykrx import stock


def _recent_business_days(n_needed, lookback_days=15):
    """오늘부터 거슬러 올라가며 실제 거래가 있었던 날짜 문자열(YYYYMMDD) n_needed개를 최신순으로 반환."""
    days = []
    d = datetime.today()
    tries = 0
    while len(days) < n_needed and tries < lookback_days:
        date_str = d.strftime("%Y%m%d")
        # 거래일 여부는 지수 데이터 존재 여부로 간접 확인
        try:
            df = stock.get_index_ohlcv_by_date(date_str, date_str, "1001")  # KOSPI 종합지수
            if df is not None and not df.empty:
                days.append(date_str)
        except Exception:
            pass
        d -= timedelta(days=1)
        tries += 1
    return days


def get_universe():
    """KOSPI200 + KOSDAQ150 구성종목 티커 집합을 반환."""
    universe = set()
    for name, code in config.UNIVERSE_INDEX_CODES.items():
        try:
            tickers = stock.get_index_portfolio_deposit_file(code)
            universe.update(tickers)
        except Exception as e:
            print(f"[경고] {name} 유니버스 조회 실패: {e}")
    return universe


def _net_buy_by_day(date_str, investor):
    """특정일, 특정 투자자 유형의 종목별 순매수거래대금(원) Series 반환 (ticker -> 금액)."""
    try:
        df = stock.get_market_net_purchases_of_equities_by_ticker(
            date_str, date_str, "ALL", investor
        )
        col = "순매수거래대금" if "순매수거래대금" in df.columns else df.columns[-1]
        return df[col]
    except Exception:
        return None


def _check_net_buy_streak(universe, business_days):
    """universe 내 종목 중, 주어진 거래일 전부에서 외국인+기관 모두 순매수(>0)한 종목 집합 반환."""
    passed = set(universe)
    for date_str in business_days:
        foreign = _net_buy_by_day(date_str, "외국인")
        institution = _net_buy_by_day(date_str, "기관합계")
        if foreign is None or institution is None:
            print(f"[경고] {date_str} 순매수 데이터 조회 실패 - 해당일 필터 스킵")
            continue
        day_pass = set()
        for ticker in passed:
            f_val = foreign.get(ticker, 0)
            i_val = institution.get(ticker, 0)
            if f_val > 0 and i_val > 0:
                day_pass.add(ticker)
        passed = day_pass
        if not passed:
            break
    return passed


def _trading_value_ratio(ticker, business_days):
    """당일 거래대금 / 최근 20일(당일 제외) 평균 거래대금 비율을 반환. 실패 시 None."""
    try:
        end = business_days[0]
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start, end, ticker)
        if df is None or "거래대금" not in df.columns or len(df) < config.MA_MID + 1:
            return None
        today_value = df["거래대금"].iloc[-1]
        avg_20 = df["거래대금"].iloc[-(config.MA_MID + 1):-1].mean()
        if avg_20 == 0:
            return None
        return today_value / avg_20
    except Exception:
        return None


def screen_stocks():
    """
    반환값:
    {
      "candidates": [
        {"ticker": "005930", "name": "삼성전자", "grade": "S",
         "volume_ratio": 2.4, "net_buy_days": 3},
        ...
      ],
      "data_error": False
    }
    """
    business_days = _recent_business_days(config.NET_BUY_STREAK_DAYS)
    if len(business_days) < config.NET_BUY_STREAK_DAYS:
        return {"candidates": [], "data_error": True,
                "error": "최근 거래일 데이터를 충분히 가져오지 못함"}

    universe = get_universe()
    if not universe:
        return {"candidates": [], "data_error": True, "error": "유니버스 조회 실패"}

    streak_passed = _check_net_buy_streak(universe, business_days)

    candidates = []
    for ticker in streak_passed:
        ratio = _trading_value_ratio(ticker, business_days)
        grade = "S" if (ratio is not None and ratio >= config.VOLUME_SURGE_MULTIPLIER) else "A"
        try:
            name = stock.get_market_ticker_name(ticker)
        except Exception:
            name = ticker
        candidates.append({
            "ticker": ticker,
            "name": name,
            "grade": grade,
            "volume_ratio": round(ratio, 2) if ratio is not None else None,
            "net_buy_days": config.NET_BUY_STREAK_DAYS,
        })
        time.sleep(0.05)  # KRX 과호출 방지용 짧은 대기

    # S등급 우선, 거래대금 배율 높은 순 정렬
    candidates.sort(key=lambda c: (c["grade"] != "S", -(c["volume_ratio"] or 0)))

    return {"candidates": candidates, "data_error": False}


if __name__ == "__main__":
    import json
    print(json.dumps(screen_stocks(), indent=2, ensure_ascii=False))
