"""
오프라인 로직 검증 스크립트 (네트워크 불필요).
외부 API(yfinance/pykrx) 호출 함수는 monkeypatch로 대체하고,
판정 로직(시장 상태 산출 / 손절·익절·트레일링 판정 / 리포트 텍스트 생성)만 검증한다.

실행: python tests/test_logic.py
"""
import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import market_analyzer, portfolio_manager, email_sender, ai_advisor


def test_market_state_uptrend():
    # 60일간 꾸준히 우상향하는 가격 시리즈 -> MA5 > MA20 > MA60, 가격 > MA20 이어야 함
    prices = pd.Series(np.linspace(100, 160, 65))
    df = pd.DataFrame({"Close": prices})
    result = market_analyzer._judge_state(df)
    assert result["state"] == "상승장", f"expected 상승장, got {result}"
    print("OK: test_market_state_uptrend")


def test_market_state_downtrend():
    prices = pd.Series(np.linspace(160, 100, 65))
    df = pd.DataFrame({"Close": prices})
    result = market_analyzer._judge_state(df)
    assert result["state"] == "하락장", f"expected 하락장, got {result}"
    print("OK: test_market_state_downtrend")


def test_stop_loss_decision(monkeypatch):
    monkeypatch.setattr(portfolio_manager, "_get_current_price", lambda t: 65000)  # -7.1%
    monkeypatch.setattr(portfolio_manager, "_get_today_net_buy_positive", lambda t: True)

    portfolio = {
        "total_capital": 100_000_000,
        "holdings": [{
            "ticker": "005930", "name": "테스트종목", "grade": "S",
            "quantity": 100, "avg_price": 70000, "entry_stage": 1,
            "peak_price": 70000, "entry_date": "2026-07-01",
        }],
    }
    results = portfolio_manager.evaluate_holdings(portfolio)
    assert results[0]["decision"] == "SELL_PARTIAL", results[0]
    assert "손절선" in results[0]["reason"], results[0]
    print("OK: test_stop_loss_decision")


def test_target_profit_decision(monkeypatch):
    monkeypatch.setattr(portfolio_manager, "_get_current_price", lambda t: 81000)  # +15.7%
    monkeypatch.setattr(portfolio_manager, "_get_today_net_buy_positive", lambda t: True)

    portfolio = {
        "total_capital": 100_000_000,
        "holdings": [{
            "ticker": "005930", "name": "테스트종목", "grade": "S",
            "quantity": 100, "avg_price": 70000, "entry_stage": 2,
            "peak_price": 70000, "entry_date": "2026-07-01",
        }],
    }
    results = portfolio_manager.evaluate_holdings(portfolio)
    assert results[0]["decision"] == "SELL_PARTIAL", results[0]
    assert "목표가" in results[0]["reason"], results[0]
    print("OK: test_target_profit_decision")


def test_net_buy_exit_overrides_hold(monkeypatch):
    monkeypatch.setattr(portfolio_manager, "_get_current_price", lambda t: 71000)  # +1.4%
    monkeypatch.setattr(portfolio_manager, "_get_today_net_buy_positive", lambda t: False)

    portfolio = {
        "total_capital": 100_000_000,
        "holdings": [{
            "ticker": "005930", "name": "테스트종목", "grade": "S",
            "quantity": 100, "avg_price": 70000, "entry_stage": 1,
            "peak_price": 70000, "entry_date": "2026-07-01",
        }],
    }
    results = portfolio_manager.evaluate_holdings(portfolio)
    assert results[0]["decision"] == "SELL_PARTIAL", results[0]
    assert "양매수 이탈" in results[0]["reason"], results[0]
    print("OK: test_net_buy_exit_overrides_hold")


def test_new_candidates_only_when_portfolio_empty(monkeypatch):
    monkeypatch.setattr(portfolio_manager, "_get_current_price", lambda t: 71000)
    monkeypatch.setattr(portfolio_manager, "_get_today_net_buy_positive", lambda t: True)

    market = {"overall_state": "중립"}
    screened = {"candidates": [
        {"ticker": "000001", "name": "후보1", "grade": "S", "volume_ratio": 2.5, "net_buy_days": 3},
    ]}

    empty_portfolio = {"total_capital": 100_000_000, "cash": 100_000_000, "holdings": []}
    decisions_empty = portfolio_manager.build_decisions(empty_portfolio, market, screened)
    assert len(decisions_empty["new_candidates"]) == 1, decisions_empty

    filled_portfolio = {
        "total_capital": 100_000_000, "cash": 50_000_000,
        "holdings": [{
            "ticker": "005930", "name": "테스트종목", "grade": "S",
            "quantity": 100, "avg_price": 70000, "entry_stage": 1,
            "peak_price": 70000, "entry_date": "2026-07-01",
        }],
    }
    decisions_filled = portfolio_manager.build_decisions(filled_portfolio, market, screened)
    assert decisions_filled["new_candidates"] == [], decisions_filled
    print("OK: test_new_candidates_only_when_portfolio_empty")


def test_ai_advisor_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(ai_advisor.config, "GEMINI_API_KEY", None)
    result = ai_advisor.generate_ai_opinions(
        {"market": {}, "holdings": [], "new_candidates": [], "swap_suggestions": []}
    )
    assert result == {}, result
    print("OK: test_ai_advisor_returns_empty_without_api_key")


def test_report_text_includes_ai_opinion_when_present():
    decisions = {
        "market": {
            "KOSPI": {"state": "상승장", "price": 2800, "ma5": 2790, "ma20": 2750, "ma60": 2700},
            "KOSDAQ": {"state": "중립", "price": 850, "ma5": 848, "ma20": 850, "ma60": 845},
            "overall_state": "중립",
            "recommended": {"stock_min": 0.5, "stock_max": 0.7, "cash_min": 0.3, "cash_max": 0.5},
            "data_error": False,
        },
        "holdings": [{
            "ticker": "005930", "name": "테스트종목", "grade": "S",
            "avg_price": 70000, "current_price": 71000, "return_pct": 1.43,
            "entry_stage": 1, "net_buy_ok": True,
            "decision": "HOLD", "reason": "추세 양호, 관망",
        }],
        "new_candidates": [],
        "swap_suggestions": [],
        "watchlist": [],
        "open_slots": 4,
        "ai_opinions": {"005930": "반도체 업황 개선 흐름이 지속되고 있어 참고할 만합니다."},
    }
    text = email_sender.build_report_text(decisions)
    assert "AI 참고의견: 반도체 업황 개선 흐름" in text, text
    assert "자동 생성되어 덧붙인 보조 설명" in text, text
    print("OK: test_report_text_includes_ai_opinion_when_present")


def test_report_text_builds_without_error():
    decisions = {
        "market": {
            "KOSPI": {"state": "상승장", "price": 2800, "ma5": 2790, "ma20": 2750, "ma60": 2700},
            "KOSDAQ": {"state": "중립", "price": 850, "ma5": 848, "ma20": 850, "ma60": 845},
            "overall_state": "중립",
            "recommended": {"stock_min": 0.5, "stock_max": 0.7, "cash_min": 0.3, "cash_max": 0.5},
            "data_error": False,
        },
        "holdings": [],
        "new_candidates": [],
        "swap_suggestions": [],
        "watchlist": [],
        "open_slots": 5,
    }
    text = email_sender.build_report_text(decisions)
    assert "Daily 주식 포트폴리오" in text
    assert "투자 자문이 아닙니다" in text
    print("OK: test_report_text_builds_without_error")


class _FakeMonkeypatch:
    """pytest 없이 monkeypatch 흉내 (테스트 종료 후 원복)."""
    def __init__(self):
        self._orig = []

    def setattr(self, obj, name, value):
        self._orig.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self._orig):
            setattr(obj, name, value)


if __name__ == "__main__":
    test_market_state_uptrend()
    test_market_state_downtrend()

    for fn in (
        test_stop_loss_decision,
        test_target_profit_decision,
        test_net_buy_exit_overrides_hold,
        test_new_candidates_only_when_portfolio_empty,
        test_ai_advisor_returns_empty_without_api_key,
    ):
        mp = _FakeMonkeypatch()
        try:
            fn(mp)
        finally:
            mp.undo()

    test_report_text_builds_without_error()
    test_report_text_includes_ai_opinion_when_present()
    print("\n모든 오프라인 로직 테스트 통과.")
