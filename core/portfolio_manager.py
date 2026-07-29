"""
portfolio_manager.py
보유 종목의 당일 대응 판정(HOLD/SELL_PARTIAL/SELL_FULL/BUY_MORE)과
신규 편입/SWAP 후보를 산출한다. 실제 매매를 실행하지 않는
"의사결정 지원" 모듈이다 (Phase 1 범위).

portfolio.json 스키마:
{
  "total_capital": 100000000,
  "cash": 100000000,
  "holdings": [
    {
      "ticker": "005930", "name": "삼성전자", "grade": "S",
      "quantity": 100, "avg_price": 70000,
      "entry_stage": 1,          # 1=1차 매수만 완료, 2=2차까지 완료
      "peak_price": 72500,       # 보유 후 최고가 (트레일링 스탑 기준)
      "entry_date": "2026-07-20"
    }
  ],
  "last_updated": "2026-07-26"
}
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

from pykrx import stock


def _get_current_price(ticker):
    """당일부터 최근 5거래일 후보까지 거슬러 올라가며 종가를 조회한다.
    보유종목은 최대 5개뿐이라 실패 원인을 로그로 남겨도 로그가 폭주하지 않는다."""
    tried = []
    try:
        d = datetime.today()
        for _ in range(6):  # 당일 + 최근 5일 후보
            date_str = d.strftime("%Y%m%d")
            tried.append(date_str)
            df = stock.get_market_ohlcv_by_date(date_str, date_str, ticker)
            if df is not None and not df.empty:
                return float(df["종가"].iloc[-1])
            d -= timedelta(days=1)
        print(f"[경고] {ticker} 현재가 조회 실패 - 조회 시도한 날짜 전부 데이터 없음: {tried}")
        return None
    except Exception as e:
        print(f"[경고] {ticker} 현재가 조회 실패 - {type(e).__name__}: {e} (시도한 날짜: {tried})")
        return None


def _get_today_net_buy_positive(ticker):
    """오늘 외국인/기관 순매수가 모두 양수인지 여부. 데이터 조회 실패 시 None."""
    try:
        today = datetime.today().strftime("%Y%m%d")
        foreign = stock.get_market_net_purchases_of_equities_by_ticker(today, today, "ALL", "외국인")
        inst = stock.get_market_net_purchases_of_equities_by_ticker(today, today, "ALL", "기관합계")
        col_f = "순매수거래대금" if "순매수거래대금" in foreign.columns else foreign.columns[-1]
        col_i = "순매수거래대금" if "순매수거래대금" in inst.columns else inst.columns[-1]
        f_val = foreign[col_f].get(ticker, 0)
        i_val = inst[col_i].get(ticker, 0)
        return bool(f_val > 0 and i_val > 0)
    except Exception:
        return None


def _grade_target_weight(grade):
    if grade == "S":
        return config.S_GRADE_MAX_WEIGHT
    return (config.A_GRADE_MAX_WEIGHT_MIN + config.A_GRADE_MAX_WEIGHT_MAX) / 2


def evaluate_holdings(portfolio):
    """보유 종목별 당일 대응 판정을 계산해 리스트로 반환."""
    results = []
    for h in portfolio.get("holdings", []):
        ticker = h["ticker"]
        price = _get_current_price(ticker)
        if price is None:
            results.append({**h, "decision": "DATA_ERROR",
                             "reason": "현재가 조회 실패 - 수동 확인 필요"})
            continue

        return_pct = (price - h["avg_price"]) / h["avg_price"]
        peak_price = max(h.get("peak_price", h["avg_price"]), price)
        net_buy_ok = _get_today_net_buy_positive(ticker)

        decision, reason = "HOLD", "추세 양호, 관망"

        if net_buy_ok is False:
            decision, reason = "SELL_PARTIAL", "외국인/기관 양매수 이탈 - 비중 축소 권고"
        elif return_pct <= config.STOP_LOSS_PCT:
            decision, reason = "SELL_PARTIAL", f"손절선({config.STOP_LOSS_PCT:.0%}) 도달"
        elif price <= peak_price * (1 + config.TRAILING_STOP_PCT):
            decision, reason = "SELL_FULL", f"고점 대비 트레일링 스탑({config.TRAILING_STOP_PCT:.0%}) 도달"
        elif return_pct >= config.TARGET_PROFIT_PCT:
            decision = "SELL_PARTIAL"
            reason = f"1차 목표가(+{config.TARGET_PROFIT_PCT:.0%}) 도달 - {config.PARTIAL_SELL_RATIO:.0%} 익절 권고"
        elif h.get("entry_stage") == 1 and return_pct > 0:
            decision, reason = "HOLD", "추세 확정 시 2차 추가매수(불타기) 검토 대상"

        results.append({
            **h,
            "current_price": round(price, 2),
            "return_pct": round(return_pct * 100, 2),
            "peak_price": round(peak_price, 2),
            "net_buy_ok": net_buy_ok,
            "decision": decision,
            "reason": reason,
        })
    return results


def find_new_candidates(portfolio, screened, max_slots):
    """신규 편입 후보(현재 미보유) 목록. 목표 비중 및 1차 진입 비중 포함."""
    held_tickers = {h["ticker"] for h in portfolio.get("holdings", [])}
    candidates = []
    for c in screened:
        if c["ticker"] in held_tickers:
            continue
        target_weight = _grade_target_weight(c["grade"])
        entry_weight = target_weight * config.FIRST_ENTRY_RATIO
        candidates.append({
            **c,
            "target_weight": round(target_weight * 100, 1),
            "first_entry_weight": round(entry_weight * 100, 1),
            "first_entry_amount": round(entry_weight * portfolio.get("total_capital", config.TOTAL_CAPITAL)),
        })
        if len(candidates) >= max_slots:
            break
    return candidates


def find_swap_suggestions(holding_results, screened, portfolio):
    """
    포트폴리오가 가득 찼는데(MAX_HOLDINGS) 더 강한 S등급 후보가 있고,
    보유 중 수익률이 가장 낮으면서 S등급이 아닌 종목이 있으면 SWAP 후보로 제안.
    (실행이 아닌 제안 - 최종 판단은 사용자 몫)
    """
    if len(portfolio.get("holdings", [])) < config.MAX_HOLDINGS:
        return []

    held_tickers = {h["ticker"] for h in portfolio["holdings"]}
    s_candidates = [c for c in screened if c["grade"] == "S" and c["ticker"] not in held_tickers]
    if not s_candidates:
        return []

    non_s_holdings = [h for h in holding_results if h.get("grade") != "S" and h.get("decision") == "HOLD"]
    if not non_s_holdings:
        return []

    weakest = min(non_s_holdings, key=lambda h: h.get("return_pct", 0))
    swaps = []
    for c in s_candidates[:2]:  # 상위 2개까지만 제안
        swaps.append({
            "out": {"ticker": weakest["ticker"], "name": weakest["name"],
                    "return_pct": weakest.get("return_pct")},
            "in": {"ticker": c["ticker"], "name": c["name"], "grade": c["grade"]},
            "reason": "보유 슬롯 초과 - 더 강한 모멘텀 후보로 교체(SWAP) 제안",
        })
    return swaps


def apply_peak_price_updates(portfolio, holding_results):
    """
    트레일링 스탑 계산을 위해 보유 종목의 peak_price를 갱신한 portfolio 딕셔너리를 반환.
    수량/평단가/단계 등 매매 관련 필드는 건드리지 않는다 (실제 체결은 사용자가 수동 반영).
    """
    price_map = {h["ticker"]: h.get("peak_price") for h in holding_results
                 if h.get("decision") != "DATA_ERROR"}
    updated_holdings = []
    for h in portfolio.get("holdings", []):
        new_h = dict(h)
        if h["ticker"] in price_map and price_map[h["ticker"]] is not None:
            new_h["peak_price"] = price_map[h["ticker"]]
        updated_holdings.append(new_h)
    return {**portfolio, "holdings": updated_holdings,
            "last_updated": datetime.now().strftime("%Y-%m-%d")}


def build_decisions(portfolio, market, screened_result):
    """market_analyzer / stock_screener 결과를 받아 최종 의사결정 묶음을 반환.

    신규 편입 후보는 보유 종목이 0개(완전 공백)일 때만 추천한다. 일부 슬롯만
    비어 있는 경우(예: 5개 중 2개 보유)에는 신규 추천도, SWAP 제안도 하지 않고
    보유 종목 판정과 watchlist만 안내한다 (보유 중 판단은 사용자의 별도 검토 영역).
    """
    holding_results = evaluate_holdings(portfolio)
    open_slots = max(0, config.MAX_HOLDINGS - len(portfolio.get("holdings", [])))
    screened = screened_result.get("candidates", [])

    is_empty_portfolio = len(portfolio.get("holdings", [])) == 0
    new_candidates = find_new_candidates(portfolio, screened, config.MAX_HOLDINGS) if is_empty_portfolio else []
    swap_suggestions = find_swap_suggestions(holding_results, screened, portfolio) if open_slots == 0 else []

    watchlist = [c for c in screened if c["ticker"] not in
                 {h["ticker"] for h in portfolio.get("holdings", [])} and
                 c not in new_candidates][:3]

    return {
        "market": market,
        "holdings": holding_results,
        "new_candidates": new_candidates,
        "swap_suggestions": swap_suggestions,
        "watchlist": watchlist,
        "open_slots": open_slots,
    }
