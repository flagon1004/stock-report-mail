"""
main.py
Alpha-Flow 2026 Daily 오케스트레이터.
market_analyzer -> stock_screener -> portfolio_manager -> ai_advisor -> email_sender
순서로 실행하고, 리포트를 이메일로 발송한다.
보유 종목 DB는 Google Sheets(core/sheets_client)를 사용한다.

실행 실패 시(예: 데이터 수집 전면 실패) 가능한 경우 오류 알림 메일을 보낸다.
pykrx는 KRX_ID/KRX_PW가 설정되어 있으면 import 시점에 자동으로 KRX 로그인을
시도하는데, KRX 서버가 비정상 응답을 주면 그 자리에서 예외가 나며 import 자체가
죽을 수 있다. email_sender만 미리 가져오고 pykrx에 의존하는 모듈들은 run() 안에서
지연 임포트해서, 이런 import 단계 실패도 아래 try/except가 잡아 실패 알림 메일을
보낼 수 있게 한다.
"""
import sys
import traceback

from core import email_sender


def run():
    from core import market_analyzer, stock_screener, portfolio_manager, ai_advisor, sheets_client

    market = market_analyzer.analyze_market()
    screened = stock_screener.screen_stocks()
    portfolio = sheets_client.load_portfolio()
    decisions = portfolio_manager.build_decisions(portfolio, market, screened)
    decisions["ai_opinions"] = ai_advisor.generate_ai_opinions(decisions)
    body = email_sender.send_report(decisions)
    print(body)
    print("\n리포트 발송 완료.")

    # 트레일링 스탑 기준(peak_price)을 갱신해 다음 실행에 반영 (실제 매매 수량/평단가는 미변경)
    updated_portfolio = portfolio_manager.apply_peak_price_updates(portfolio, decisions["holdings"])
    sheets_client.save_portfolio(updated_portfolio)


def send_failure_alert(error_text):
    try:
        subject = "[Alpha-Flow] 실행 실패 알림"
        body = (
            "Alpha-Flow 일일 리포트 생성 중 오류가 발생하여 정상 리포트를 보내지 못했습니다.\n\n"
            f"오류 내용:\n{error_text}\n\n"
            "GitHub Actions 로그를 확인하세요."
        )
        email_sender.send_email(subject, body)
    except Exception:
        # 알림 메일조차 보낼 수 없는 상황 (자격증명 미설정 등) - 콘솔 출력만으로 종료
        print("실패 알림 메일 발송도 실패했습니다.", file=sys.stderr)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        send_failure_alert(err)
        sys.exit(1)
