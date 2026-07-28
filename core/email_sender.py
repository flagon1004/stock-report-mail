"""
email_sender.py
포트폴리오 판정 결과를 PDF 명세서의 레이아웃대로 텍스트 리포트로 만들고
Gmail SMTP로 발송한다.
"""
import sys
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

DIVIDER = "=" * 70


def _fmt_holding(h, ai_opinions=None):
    ai_opinions = ai_opinions or {}
    lines = [f"[{h.get('name', h['ticker'])}] (모멘텀 {h.get('grade', '?')}등급)"]
    if h.get("decision") == "DATA_ERROR":
        lines.append(f"- 상태: 데이터 조회 실패 ({h.get('reason')}) - 수동 확인 필요")
        return "\n".join(lines)
    lines.append(
        f"- 평단가 {h['avg_price']:,.0f}원 (현재가 {h.get('current_price', 0):,.0f}원, "
        f"{h.get('return_pct', 0):+.2f}%)"
    )
    lines.append(f"- 분할 단계: {h.get('entry_stage', 1)}차 매수 완료")
    net_buy_str = "양매수 유지" if h.get("net_buy_ok") else "양매수 이탈/불명"
    lines.append(f"- 양매수 현황: [{net_buy_str}]")
    lines.append(f"- 당일 대응 판정: {h.get('decision')} - {h.get('reason')}")
    opinion = ai_opinions.get(h["ticker"])
    if opinion:
        lines.append(f"- AI 참고의견: {opinion}")
    return "\n".join(lines)


def build_report_text(decisions):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    market = decisions["market"]
    ai_opinions = decisions.get("ai_opinions", {})
    lines = []
    lines.append("[Daily 주식 포트폴리오 & 시장 대응 리포트]")
    lines.append(f"발송 일시: {now} | 수신자: {config.EMAIL_RECEIVER}")
    lines.append(DIVIDER)
    lines.append("1. 지수 연동형 시장 상태 & 권장 자금 배분")
    lines.append(DIVIDER)

    for idx_name in ("KOSPI", "KOSDAQ"):
        info = market.get(idx_name, {})
        if info.get("state"):
            lines.append(f"- {idx_name} 현황: [{info['state']}] (현재가 {info['price']:,} / MA20 {info['ma20']:,})")
        else:
            lines.append(f"- {idx_name} 현황: 데이터 수집 실패")

    rec = market["recommended"]
    lines.append(f"- 종합 시장 상태: [{market['overall_state']}]")
    lines.append(
        f"- 권장 포트폴리오 비중: 주식 {rec['stock_min']:.0%}~{rec['stock_max']:.0%} / "
        f"현금 {rec['cash_min']:.0%}~{rec['cash_max']:.0%}"
    )
    if market.get("data_error"):
        lines.append("- ⚠ 일부 지수 데이터 수집에 실패했습니다. 수치를 직접 확인하세요.")

    lines.append(DIVIDER)
    lines.append(f"2. 현재 보유 포트폴리오 현황 & 매일 대응 판정 (최대 {config.MAX_HOLDINGS}개 이내)")
    lines.append(DIVIDER)
    if decisions["holdings"]:
        for h in decisions["holdings"]:
            lines.append(_fmt_holding(h, ai_opinions))
            lines.append("")
    else:
        lines.append("- 현재 보유 종목 없음 (현금 100%)")

    lines.append(DIVIDER)
    lines.append("3. 신규 편입 후보 및 SWAP 시그널")
    lines.append(DIVIDER)
    if decisions["new_candidates"]:
        for c in decisions["new_candidates"]:
            lines.append(
                f"- [신규 편입 후보] {c.get('name', c['ticker'])} ({c['grade']}등급) - "
                f"거래대금 20일 평균 대비 {c.get('volume_ratio', '?')}배"
            )
            lines.append(
                f"  1차 탐색 매수 권장: 목표비중 {c['target_weight']}% 중 "
                f"{c['first_entry_weight']}% (약 {c['first_entry_amount']:,}원)"
            )
            opinion = ai_opinions.get(c["ticker"])
            if opinion:
                lines.append(f"  AI 참고의견: {opinion}")
    else:
        lines.append("- 신규 편입 후보 없음")

    if decisions["swap_suggestions"]:
        for s in decisions["swap_suggestions"]:
            lines.append(
                f"- [SWAP 제안] {s['out']['name']}({s['out']['return_pct']:+.2f}%) 편출 → "
                f"{s['in']['name']}({s['in']['grade']}등급) 편입 검토 - {s['reason']}"
            )
            opinion = ai_opinions.get(s["in"]["ticker"])
            if opinion:
                lines.append(f"  AI 참고의견: {opinion}")

    lines.append(DIVIDER)
    lines.append("4. 조건 충족 양매수/모멘텀 후보군 (Watchlist)")
    lines.append(DIVIDER)
    if decisions["watchlist"]:
        for i, w in enumerate(decisions["watchlist"], 1):
            lines.append(f"{i}. {w.get('name', w['ticker'])}: [{w['grade']}등급 / 거래대금 급증]")
    else:
        lines.append("- 조건 충족 종목 없음")

    lines.append("")
    lines.append(DIVIDER)
    lines.append(
        "※ 본 리포트는 사전 정의된 규칙 기반의 참고 자료이며 투자 자문이 아닙니다. "
        "최종 매매 판단과 책임은 투자자 본인에게 있습니다."
    )
    if ai_opinions:
        lines.append(
            "※ 'AI 참고의견'은 위 규칙 기반 판정 결과에 자동 생성되어 덧붙인 보조 설명이며, "
            "등급/매매 판정을 대체하거나 변경하지 않습니다."
        )
    lines.append(DIVIDER)

    return "\n".join(lines)


def send_email(subject, body):
    if not config.EMAIL_SENDER or not config.EMAIL_APP_PASSWORD:
        raise RuntimeError(
            "EMAIL_ADDRESS / EMAIL_APP_PASSWORD 환경변수가 설정되지 않았습니다. "
            ".env 또는 GitHub Secrets를 확인하세요."
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECEIVER

    # 실제로 어떤 서버/계정으로 접속을 시도하는지 로그에 남긴다 (비밀번호는 출력하지 않음).
    print(f"[정보] SMTP 접속 시도: {config.SMTP_SERVER}:{config.SMTP_PORT} (로그인 계정: {config.SMTP_LOGIN_USER})")

    # 포트 465 = SSL(암시적 암호화), 그 외(587 등) = STARTTLS
    if config.SMTP_PORT == 465:
        server_cm = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
    else:
        server_cm = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)

    with server_cm as server:
        if config.SMTP_PORT != 465:
            server.starttls()
        server.login(config.SMTP_LOGIN_USER, config.EMAIL_APP_PASSWORD)
        server.sendmail(config.EMAIL_SENDER, [config.EMAIL_RECEIVER], msg.as_string())


def send_report(decisions):
    body = build_report_text(decisions)
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"[Alpha-Flow] {today} Daily 주식 포트폴리오 리포트"
    send_email(subject, body)
    return body
