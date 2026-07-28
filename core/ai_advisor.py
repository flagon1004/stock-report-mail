"""
ai_advisor.py
규칙 기반 판정 결과(market_analyzer/stock_screener/portfolio_manager)에
Gemini의 참고의견을 "병기"한다.

중요: 등급(grade)/매매 판정(decision) 등 실제 의사결정 값은 이 모듈이
만들지도, 바꾸지도 않는다. 오직 보조 설명 텍스트만 추가한다.
API 키 미설정, 네트워크/호출 실패, 응답 파싱 실패 시 빈 dict를 반환해
리포트 발송 자체는 막지 않는다 (market_analyzer/portfolio_manager의
외부 데이터 조회 실패 처리와 동일한 방어적 패턴).
"""
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config


def _build_items(decisions):
    """참고의견을 받을 티커별 요약 정보 리스트 (보유종목/신규후보/SWAP 후보)."""
    items = []
    for h in decisions.get("holdings", []):
        if h.get("decision") == "DATA_ERROR":
            continue
        items.append({
            "ticker": h["ticker"], "name": h.get("name", h["ticker"]),
            "구분": "보유종목", "등급": h.get("grade"), "판정": h.get("decision"),
            "수익률(%)": h.get("return_pct"),
        })
    for c in decisions.get("new_candidates", []):
        items.append({
            "ticker": c["ticker"], "name": c.get("name", c["ticker"]),
            "구분": "신규편입후보", "등급": c.get("grade"),
            "거래대금배율": c.get("volume_ratio"),
        })
    for s in decisions.get("swap_suggestions", []):
        c = s["in"]
        items.append({
            "ticker": c["ticker"], "name": c.get("name", c["ticker"]),
            "구분": "SWAP편입후보", "등급": c.get("grade"),
        })
    return items


def _build_prompt(decisions, items):
    market = decisions.get("market", {})
    return (
        "다음은 규칙 기반 주식 스크리닝 시스템이 산출한 오늘의 시장 상태와 종목별 판정입니다. "
        "각 종목에 대해 1~2문장의 한국어 참고의견을 작성하세요. "
        "등급이나 매매 판정을 바꾸거나 반박하지 말고, 보조적인 맥락(업종 흐름, 유의할 점 등)만 "
        "덧붙이세요. 투자 자문이 아닌 참고용임을 전제로 간결하게 작성하세요.\n\n"
        f"오늘 종합 시장 상태: {market.get('overall_state', '알 수 없음')}\n\n"
        "종목 목록(JSON):\n"
        f"{json.dumps(items, ensure_ascii=False)}\n\n"
        "반드시 아래 형식의 JSON 객체 하나만 출력하세요 (다른 텍스트나 코드블록 금지):\n"
        '{"티커": "참고의견 문장", ...}'
    )


def _parse_response_text(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_ai_opinions(decisions):
    """티커 -> 참고의견(str) dict. 조건 미충족/실패 시 빈 dict."""
    if not config.GEMINI_API_KEY:
        return {}

    items = _build_items(decisions)
    if not items:
        return {}

    try:
        from google import genai

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=_build_prompt(decisions, items),
        )
        opinions = _parse_response_text(response.text)
        valid_tickers = {i["ticker"] for i in items}
        return {
            ticker: str(opinion).strip()
            for ticker, opinion in opinions.items()
            if ticker in valid_tickers and str(opinion).strip()
        }
    except Exception:
        return {}
