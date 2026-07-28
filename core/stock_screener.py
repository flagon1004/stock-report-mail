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


def _recent_weekdays(lookback_days=15):
    """오늘부터 거슬러 올라가며 평일(월~금) 날짜 문자열(YYYYMMDD) 후보를 최신순으로 반환.
    공휴일이 섞여 있을 수 있으며, 실제 거래일 여부는 데이터 조회 시점에 판별한다
    (별도 지수 조회로 거래일을 미리 확인하지 않음 - 불필요한 API 호출과 실패 지점을 줄이기 위함)."""
    days = []
    d = datetime.today()
    for _ in range(lookback_days):
        if d.weekday() < 5:  # 0=월 ... 4=금
            days.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return days


def get_universe():
    """
    KOSPI200 + KOSDAQ150 구성종목 티커 집합을 반환.

    주의: get_index_portfolio_deposit_file(code)를 날짜 없이 호출하면 pykrx가
    내부적으로 "가장 최근 영업일"을 알아내려고 get_index_ohlcv_by_date(...,"1001")를
    자동 호출하는데, 이 내부 호출이 실패하면 전체가 깨진다. 날짜를 직접 지정해서
    이 내부 호출 자체를 건너뛴다.
    """
    universe = set()
    for name, code in config.UNIVERSE_INDEX_CODES.items():
        got = False
        for date_str in _recent_weekdays(lookback_days=10):
            try:
                tickers = stock.get_index_portfolio_deposit_file(code, date=date_str)
                if tickers:
                    universe.update(tickers)
                    got = True
                    break
            except Exception:
                continue
            time.sleep(0.2)
        if not got:
            print(f"[경고] {name} 유니버스 조회 실패: 최근 10거래일 후보 모두 실패")
    return universe


def _net_buy_by_day(date_str, investor):
    """특정일, 특정 투자자 유형의 종목별 순매수거래대금(원) Series 반환 (ticker -> 금액).
    데이터가 없는 날(휴장일 등)이거나 조회 실패 시 None을 반환한다."""
    try:
        df = stock.get_market_net_purchases_of_equities_by_ticker(
            date_str, date_str, "ALL", investor
        )
        if df is None or df.empty:
            return None
        col = "순매수거래대금" if "순매수거래대금" in df.columns else df.columns[-1]
        return df[col]
    except Exception:
        return None


def _check_net_buy_streak(universe, candidate_days, days_needed):
    """
    universe 내 종목 중, 최근 실제 거래일 days_needed일 연속으로 외국인+기관 모두
    순매수(>0)한 종목 집합을 반환한다.

    candidate_days는 평일 후보 목록(공휴일 포함 가능)이며, 데이터가 없는 날은
    거래일이 아닌 것으로 보고 건너뛴다(거래일수에 포함하지 않음).

    반환값: (통과 종목 집합, 실제 사용된 거래일 목록[최신순])
    """
    passed = set(universe)
    used_days = []
    for date_str in candidate_days:
        foreign = _net_buy_by_day(date_str, "외국인")
        institution = _net_buy_by_day(date_str, "기관합계")
        if foreign is None or institution is None:
            continue  # 휴장일 등 - 거래일수에 포함하지 않고 스킵

        used_days.append(date_str)
        day_pass = set()
        for ticker in passed:
            f_val = foreign.get(ticker, 0)
            i_val = institution.get(ticker, 0)
            if f_val > 0 and i_val > 0:
                day_pass.add(ticker)
        passed = day_pass

        if len(used_days) >= days_needed:
            break
        if not passed:
            break
    return passed, used_days


def _trading_value_ratio(ticker, latest_trading_day):
    """당일 거래대금 / 최근 20일(당일 제외) 평균 거래대금 비율을 반환. 실패 시 None(원인은 로그에 남김).

    이 함수는 양매수 필터를 통과한 소수 종목에만 호출되므로 종목별 실패 로그를 남겨도
    유니버스 전체(약 350종목)를 스캔하는 다른 단계처럼 로그가 폭주하지 않는다.
    """
    try:
        end = latest_trading_day
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 거래대금 조회 실패 - 조회 결과 없음 (기간 {start}~{end})")
            return None
        if "거래대금" not in df.columns:
            print(f"[경고] {ticker} 거래대금 조회 실패 - '거래대금' 컬럼 없음 (컬럼: {list(df.columns)})")
            return None
        if len(df) < config.MA_MID + 1:
            print(f"[경고] {ticker} 거래대금 조회 실패 - 데이터 부족 ({len(df)}일치, {config.MA_MID + 1}일 필요)")
            return None
        today_value = df["거래대금"].iloc[-1]
        avg_20 = df["거래대금"].iloc[-(config.MA_MID + 1):-1].mean()
        if avg_20 == 0:
            print(f"[경고] {ticker} 거래대금 조회 실패 - 20일 평균 거래대금이 0")
            return None
        return today_value / avg_20
    except Exception as e:
        print(f"[경고] {ticker} 거래대금 조회 실패 - {type(e).__name__}: {e}")
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
    universe = get_universe()
    if not universe:
        return {"candidates": [], "data_error": True, "error": "유니버스 조회 실패"}

    candidate_days = _recent_weekdays(lookback_days=15)
    streak_passed, used_days = _check_net_buy_streak(universe, candidate_days, config.NET_BUY_STREAK_DAYS)
    if len(used_days) < config.NET_BUY_STREAK_DAYS:
        return {"candidates": [], "data_error": True,
                "error": f"최근 거래일 데이터를 충분히 가져오지 못함 (확보: {len(used_days)}일)"}

    latest_trading_day = used_days[0]
    candidates = []
    for ticker in streak_passed:
        ratio = _trading_value_ratio(ticker, latest_trading_day)
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
