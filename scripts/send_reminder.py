"""Đọc tasks.json và gửi email nhắc việc qua Gmail SMTP.

Biến môi trường cần có (đặt trong GitHub Secrets):
  GMAIL_USER          địa chỉ Gmail dùng để gửi
  GMAIL_APP_PASSWORD  App Password 16 ký tự của Gmail (không phải mật khẩu thường)
  MAIL_TO             (tùy chọn) địa chỉ nhận, mặc định = GMAIL_USER
  SITE_URL            (tùy chọn) link website để chèn vào mail

Chạy thử không gửi mail:  python scripts/send_reminder.py --dry-run
"""

import html
import json
import os
import smtplib
import sys
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TASKS_FILE = Path(__file__).resolve().parent.parent / "tasks.json"


def load_tasks():
    with open(TASKS_FILE, encoding="utf-8") as f:
        return json.load(f)


def classify(tasks, today):
    groups = {"overdue": [], "today": [], "soon": [], "later": []}
    for t in tasks:
        if int(t.get("progress", 0)) >= 100:
            continue
        dl = t.get("deadline")
        if not dl:
            groups["later"].append((t, None))
            continue
        days = (date.fromisoformat(dl) - today).days
        if days < 0:
            groups["overdue"].append((t, days))
        elif days == 0:
            groups["today"].append((t, days))
        elif days <= int(t.get("remindBefore", 3)):
            groups["soon"].append((t, days))
        else:
            groups["later"].append((t, days))
    for g in groups.values():
        g.sort(key=lambda x: (x[1] is None, x[1] if x[1] is not None else 0))
    return groups


def bar(progress):
    p = max(0, min(100, int(progress)))
    color = "#16a34a" if p >= 70 else "#ca8a04" if p >= 30 else "#dc2626"
    return (
        '<div style="background:#e5e7eb;border-radius:4px;height:8px;width:160px">'
        f'<div style="background:{color};height:8px;border-radius:4px;width:{p * 1.6:.0f}px"></div>'
        f'</div><span style="font-size:12px;color:#555">{p}%</span>'
    )


def when_text(days):
    if days is None:
        return "Không có deadline"
    if days < 0:
        return f"Quá hạn {-days} ngày"
    if days == 0:
        return "Hạn hôm nay"
    return f"Còn {days} ngày"


def render(groups, today, site_url):
    sections = [
        ("overdue", "🔴 Quá hạn", "#dc2626"),
        ("today", "🟠 Hạn hôm nay", "#ea580c"),
        ("soon", "🟡 Sắp đến hạn", "#ca8a04"),
        ("later", "⚪ Đang theo dõi", "#6b7280"),
    ]
    parts = [
        '<div style="font-family:Arial,sans-serif;max-width:600px;color:#111">',
        f'<h2 style="margin:0 0 4px">Nhắc việc ngày {today.strftime("%d/%m/%Y")}</h2>',
    ]
    for key, label, color in sections:
        items = groups[key]
        if not items:
            continue
        parts.append(f'<h3 style="color:{color};margin:20px 0 8px">{label} ({len(items)})</h3>')
        for t, days in items:
            dl = t.get("deadline")
            dl_txt = datetime.strptime(dl, "%Y-%m-%d").strftime("%d/%m/%Y") if dl else ""
            note = t.get("note", "").strip()
            parts.append(
                '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin-bottom:8px">'
                f'<b>{html.escape(t.get("title", ""))}</b><br>'
                f'<span style="font-size:13px;color:#555">{when_text(days)}'
                f'{" · " + dl_txt if dl_txt else ""}</span><br>'
                f"{bar(t.get('progress', 0))}"
                + (f'<div style="font-size:13px;color:#444;margin-top:4px">{html.escape(note)}</div>' if note else "")
                + "</div>"
            )
    if site_url:
        parts.append(
            f'<p style="margin-top:20px"><a href="{html.escape(site_url)}" '
            'style="background:#2563eb;color:#fff;padding:8px 14px;border-radius:6px;text-decoration:none">'
            "Cập nhật tiến độ</a></p>"
        )
    parts.append("</div>")
    return "".join(parts)


def main():
    dry_run = "--dry-run" in sys.argv
    today = datetime.now(TZ).date()
    groups = classify(load_tasks(), today)
    pending = sum(len(g) for g in groups.values())
    if pending == 0:
        print("Không còn việc nào chưa xong, không gửi mail.")
        return

    urgent = len(groups["overdue"]) + len(groups["today"]) + len(groups["soon"])
    subject = f"[Nhắc việc] {today.strftime('%d/%m')}: {pending} việc chưa xong"
    if groups["overdue"]:
        subject += f", {len(groups['overdue'])} quá hạn"
    elif urgent:
        subject += f", {urgent} việc gấp"

    body = render(groups, today, os.environ.get("SITE_URL", ""))
    if dry_run:
        print(subject)
        print(body)
        return

    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    to = os.environ.get("MAIL_TO") or user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Nhắc việc <{user}>"
    msg["To"] = to
    msg.attach(MIMEText(body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, password)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    print(f"Đã gửi mail tới {to}: {subject}")


if __name__ == "__main__":
    main()
