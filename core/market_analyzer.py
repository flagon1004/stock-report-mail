"""
market_analyzer.py
KOSPI/KOSDAQ 지수 추세를 분석하여 시장 상태(상승장/중립/하락장)와
권장 주식·현금 비중을 산출한다.

판단 기준 (config.MA_SHORT/MID/LONG = 5/20/60일선):
- 상승장(정배열): MA5 > MA20 > MA60  AND  현재가 > MA20
- 하락장(역배열): MA5 < MA20 < MA60  AND  현재가 < MA20 AND 현재가 < MA60
- 그 외: 중립/혼조
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

import yfinance as yf


def _fetch_index_history(ticker, period="4mo"):
    """yfinance로 지수 OHLCV를 가져온다. 실패 시 None 반환."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df is None or df.empty or len(df) < config.MA_LONG:
            return None
        return df
    except Exception:
        return None


def _judge_state(df):
    """OHLCV 데이터프레임으로 시장 상태를 판정한다."""
    close = df["Close"]
    ma_short = close.rolling(config.MA_SHORT).mean().iloc[-1]
    ma_mid = close.rolling(config.MA_MID).mean().iloc[-1]
    ma_long = close.rolling(config.MA_LONG).mean().iloc[-1]
    price = close.iloc[-1]

    if ma_short > ma_mid > ma_long and price > ma_mid:
        state = "상승장"
    elif ma_short < ma_mid < ma_long and price < ma_mid and price < ma_long:
        state = "하락장"
    else:
        state = "중립"

    return {
        "state": state,
        "price": round(float(price), 2),
        "ma5": round(float(ma_short), 2),
        "ma20": round(float(ma_mid), 2),
        "ma60": round(float(ma_long), 2),
    }


def analyze_market():
    """
    KOSPI/KOSDAQ 각각의 상태와, 두 지수 중 더 보수적인(위험한) 쪽을 기준으로 한
    전체 시장 판단(권장 주식/현금 비중)을 반환한다.

    반환값 예시:
    {
      "KOSPI": {...}, "KOSDAQ": {...},
      "overall_state": "중립",
      "recommended": {"stock_min":0.5,"stock_max":0.7,"cash_min":0.3,"cash_max":0.5},
      "data_error": False
    }
    """
    result = {}
    state_rank = {"하락장": 0, "중립": 1, "상승장": 2}  # 낮을수록 보수적

    for name, ticker in config.INDEX_TICKERS.items():
        df = _fetch_index_history(ticker)
        if df is None:
            result[name] = {"state": None, "error": "데이터 수집 실패"}
        else:
            result[name] = _judge_state(df)

    valid_states = [v["state"] for v in result.values() if v.get("state")]

    if not valid_states:
        # 두 지수 모두 데이터 수집 실패 -> 안전하게 보수적으로 처리
        overall_state = "중립"
        data_error = True
    else:
        overall_state = min(valid_states, key=lambda s: state_rank[s])
        data_error = len(valid_states) < len(config.INDEX_TICKERS)

    recommended = config.MARKET_STATE_RULES[overall_state]

    return {
        **result,
        "overall_state": overall_state,
        "recommended": recommended,
        "data_error": data_error,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(analyze_market(), indent=2, ensure_ascii=False))
