"""
sheets_client.py
보유 종목 DB를 Google Sheets에서 읽고 쓴다. config/portfolio.json을 대체한다.

Sheet 구조 (2개 탭):
- Holdings: 헤더 [ticker, name, grade, quantity, avg_price, entry_stage, peak_price, entry_date]
  데이터 행이 하나도 없으면 "보유 종목 없음"으로 취급한다.
  ticker 열은 반드시 "일반 텍스트" 서식이어야 한다(숫자 서식이면 "005930"의 앞자리 0이 소실됨).
- Meta: 키-값 2열. total_capital / cash / last_updated 행을 사용한다.

수량/평단가/entry_stage 등은 사용자가 시트에서 직접 관리하며 이 모듈은 건드리지 않는다.
peak_price(트레일링 스탑 고점)만 매 실행 후 이 모듈이 갱신한다.
"""
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _client():
    if not config.GOOGLE_SHEETS_CREDENTIALS:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS 환경변수가 설정되지 않았습니다.")
    info = json.loads(config.GOOGLE_SHEETS_CREDENTIALS)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _open_sheet():
    if not config.GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID 환경변수가 설정되지 않았습니다.")
    return _client().open_by_key(config.GOOGLE_SHEET_ID)


def _find_worksheet(sheet, title):
    """탭 이름을 대소문자/앞뒤 공백 구분 없이 찾는다 (사용자가 시트에서 직접 만든 탭이라
    'Holdings' 대신 'holdings'처럼 표기가 다를 수 있음)."""
    target = title.strip().lower()
    for ws in sheet.worksheets():
        if ws.title.strip().lower() == target:
            return ws
    raise gspread.exceptions.WorksheetNotFound(
        f"'{title}' 탭을 찾을 수 없습니다. 실제 탭 이름: {[w.title for w in sheet.worksheets()]}"
    )


def _num(value, default=0.0, field=""):
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        raise RuntimeError(
            f"Sheets 값 '{value}'{f' ({field})' if field else ''}을(를) 숫자로 변환할 수 없습니다. "
            "실제 금액/수치를 입력했는지 확인하세요."
        )


def load_portfolio():
    """Sheets에서 보유 종목/자금 현황을 읽어 portfolio dict로 반환."""
    sheet = _open_sheet()
    holdings_ws = _find_worksheet(sheet, config.SHEET_HOLDINGS_TAB)
    meta_ws = _find_worksheet(sheet, config.SHEET_META_TAB)

    holdings = []
    # numericise_ignore=['all']: gspread가 "051900" 같은 숫자형 문자열을 셀 서식과
    # 무관하게 자동으로 int(51900)로 변환해 앞자리 0을 없애버리는 것을 막는다.
    # 모든 값을 원본 문자열로 받고, 숫자 필드는 아래 _num()으로 직접 변환한다.
    for row in holdings_ws.get_all_records(numericise_ignore=["all"]):
        ticker = str(row.get("ticker", "")).strip()
        if not ticker:
            continue
        avg_price = _num(row.get("avg_price"))
        holdings.append({
            "ticker": ticker,
            "name": str(row.get("name", "")).strip(),
            "grade": str(row.get("grade", "")).strip(),
            "quantity": int(_num(row.get("quantity"))),
            "avg_price": avg_price,
            "entry_stage": int(_num(row.get("entry_stage"), 1)),
            "peak_price": _num(row.get("peak_price"), avg_price),
            "entry_date": str(row.get("entry_date", "")).strip(),
        })

    meta = {row[0].strip(): row[1] for row in meta_ws.get_all_values() if len(row) >= 2 and row[0]}
    total_capital = _num(meta.get("total_capital"), config.TOTAL_CAPITAL, field="Meta!total_capital")
    cash = _num(meta.get("cash"), total_capital, field="Meta!cash")

    return {
        "total_capital": total_capital,
        "cash": cash,
        "holdings": holdings,
        "last_updated": meta.get("last_updated", ""),
    }


def save_portfolio(updated_portfolio):
    """peak_price와 last_updated만 Sheets에 반영한다 (수량/평단가/단계는 사용자 관리 영역)."""
    sheet = _open_sheet()
    holdings_ws = _find_worksheet(sheet, config.SHEET_HOLDINGS_TAB)
    meta_ws = _find_worksheet(sheet, config.SHEET_META_TAB)

    header = holdings_ws.row_values(1)
    if "ticker" not in header or "peak_price" not in header:
        raise RuntimeError("Holdings 시트 헤더에 ticker/peak_price 열이 없습니다.")
    ticker_col = header.index("ticker") + 1
    peak_col = header.index("peak_price") + 1

    peak_by_ticker = {
        h["ticker"]: h.get("peak_price") for h in updated_portfolio.get("holdings", [])
        if h.get("peak_price") is not None
    }

    ticker_column = holdings_ws.col_values(ticker_col)[1:]  # 헤더 제외
    updates = []
    for i, ticker in enumerate(ticker_column, start=2):  # 시트 행 번호(1=헤더)
        ticker = str(ticker).strip()
        if ticker in peak_by_ticker:
            cell_a1 = gspread.utils.rowcol_to_a1(i, peak_col)
            updates.append({"range": cell_a1, "values": [[peak_by_ticker[ticker]]]})
    if updates:
        holdings_ws.batch_update(updates)

    meta_rows = meta_ws.get_all_values()
    for idx, row in enumerate(meta_rows, start=1):
        if row and row[0].strip() == "last_updated":
            meta_ws.update_cell(idx, 2, updated_portfolio.get("last_updated", ""))
            break
