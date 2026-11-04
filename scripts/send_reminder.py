"""Đọc tasks.json và gửi email nhắc việc qua Gmail SMTP.

Biến môi trường (đặt trong GitHub Secrets / workflow):
  GMAIL_USER          địa chỉ Gmail dùng để gửi
  GMAIL_APP_PASSWORD  App Password 16 chữ cái của Gmail (không phải mật khẩu thường)
  MAIL_TO             (tùy chọn) địa chỉ nhận, nhiều địa chỉ cách nhau bằng dấu phẩy; mặc định = GMAIL_USER
  SITE_URL            (tùy chọn) link website, dùng cho các nút bấm trong mail
  TASKS_FILE          (tùy chọn) đường dẫn tasks.json
  MODE                auto | full | urgent | weekly  (mặc định auto)

Chế độ:
  full    bản đầy đủ: mọi việc chưa xong, chia theo mức gấp
  urgent  chỉ việc quá hạn và hạn hôm nay; không có thì không gửi
  weekly  báo cáo tuần: đã xong, quá hạn, tuần tới
  auto    trước 9h sáng (giờ VN) = full; tối Chủ nhật (20h–22h) = weekly; còn lại = urgent

Chạy thử không gửi mail:  python scripts/send_reminder.py --dry-run
"""

import html
import json
import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TASKS_FILE = Path(os.environ.get("TASKS_FILE") or Path(__file__).resolve().parent.parent / "tasks.json")
NO_GROUP = "Chưa phân nhóm"
PRIO_RANK = {"high": 0, "normal": 1, "low": 2}
REPEAT_TEXT = {"daily": "Hằng ngày", "weekly": "Hằng tuần", "monthly": "Hằng tháng"}


# ---------------------------------------------------------------- dữ liệu

def load_tasks():
    if not TASKS_FILE.exists():
        print(f"Chưa có file {TASKS_FILE} (chưa thêm việc nào trên website).")
        return []
    with open(TASKS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # Dữ liệu cũ là một mảng việc; dữ liệu mới là {"groups": [...], "tasks": [...]}
    return data if isinstance(data, list) else data.get("tasks", [])


def items(t):
    return t.get("items") if isinstance(t.get("items"), list) else []


def progress_of(t):
    it = items(t)
    if it:
        return round(sum(1 for i in it if i.get("done")) / len(it) * 100)
    try:
        return max(0, min(100, int(float(t.get("progress") or 0))))
    except ValueError:
        return 0


def is_done(t):
    return progress_of(t) >= 100


def remind_of(t):
    v = t.get("remindBefore")
    try:
        return 3 if v is None or v == "" else max(0, int(v))
    except (TypeError, ValueError):
        return 3


def prio_of(t):
    return t.get("priority") if t.get("priority") in PRIO_RANK else "normal"


def group_of(t):
    return (t.get("group") or "").strip()


def parse_time(t):
    try:
        return datetime.strptime(t.get("time") or "", "%H:%M").time()
    except ValueError:
        return None


def days_left(t, today):
    try:
        return (date.fromisoformat(t["deadline"]) - today).days
    except (KeyError, TypeError, ValueError):
        return None


STATUS_RANK = {"overdue": 0, "today": 1, "soon": 2, "later": 3, "done": 4}


def status_at(dl, tm, remind, now):
    """Mức gấp của một mốc deadline (việc chính hoặc việc con)."""
    d = days_left({"deadline": dl}, now.date())
    if d is None:
        return "later"
    if d < 0:
        return "overdue"
    if d == 0:
        return "overdue" if tm and now.time() > tm else "today"
    if d <= remind:
        return "soon"
    return "later"


def urgent_item(t):
    """Việc con chưa xong có deadline sớm nhất."""
    cands = [i for i in items(t) if not i.get("done") and days_left(i, date.today()) is not None]
    return min(cands, key=lambda i: i["deadline"]) if cands else None


def status_of(t, now):
    """Mức gấp của cả việc = gấp nhất giữa deadline chính và deadline các việc con chưa xong."""
    if is_done(t):
        return "done"
    s = status_at(t.get("deadline"), parse_time(t), remind_of(t), now)
    it = urgent_item(t)
    if it:
        si = status_at(it["deadline"], None, remind_of(t), now)
        if STATUS_RANK[si] < STATUS_RANK[s]:
            s = si
    return s


def eff_deadline(t):
    main = (t.get("deadline") or "9999-99-99") + (t.get("time") or "99:99")
    it = urgent_item(t)
    sub = it["deadline"] + "99:99" if it else "9999-99-99"
    return min(main, sub)


def sort_key(t):
    return (PRIO_RANK[prio_of(t)], eff_deadline(t))


def classify(tasks, now):
    groups = {"overdue": [], "today": [], "soon": [], "later": []}
    for t in tasks:
        s = status_of(t, now)
        if s != "done":
            groups[s].append(t)
    for g in groups.values():
        g.sort(key=sort_key)
    return groups


# ---------------------------------------------------------------- hiển thị

def fmt_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def due_text(dl, today):
    d = days_left({"deadline": dl}, today)
    if d < 0:
        return f"quá hạn {-d} ngày"
    if d == 0:
        return "hạn hôm nay"
    return f"còn {d} ngày · {fmt_date(dl)}"


def when_text(t, now):
    d = days_left(t, now.date())
    at = f" {t['time']}" if parse_time(t) else ""
    if d is None:
        text = "Không có deadline"
    elif d < 0:
        text = f"Quá hạn {-d} ngày · {fmt_date(t['deadline'])}{at}"
    elif d == 0:
        tm = parse_time(t)
        text = f"Quá hạn từ {t['time']} hôm nay" if tm and now.time() > tm else f"Hạn hôm nay{at}"
    else:
        text = f"Còn {d} ngày · {fmt_date(t['deadline'])}{at}"
    it = urgent_item(t)
    if it:
        late = days_left(it, now.date()) < 0
        sub = due_text(it["deadline"], now.date())
        text += (
            f'<br>↳ Việc con gần nhất “{html.escape(it.get("text", ""))}”: '
            + (f'<b style="color:#dc2626">{sub}</b>' if late else sub)
        )
    return text


def bar(p):
    color = "#16a34a" if p >= 70 else "#ca8a04" if p >= 30 else "#dc2626"
    return (
        '<table cellpadding="0" cellspacing="0" style="margin-top:6px"><tr>'
        '<td style="background:#e5e7eb;border-radius:4px;width:160px;height:8px">'
        f'<div style="background:{color};height:8px;border-radius:4px;width:{p * 1.6:.0f}px"></div></td>'
        f'<td style="font-size:12px;color:#555;padding-left:8px">{p}%</td></tr></table>'
    )


def tag(text, bg="#eef2ff", fg="#3730a3"):
    return (
        f'<span style="background:{bg};color:{fg};border-radius:999px;padding:1px 8px;'
        f'font-size:12px;margin-right:4px">{html.escape(text)}</span>'
    )


def button(href, text, primary=False):
    style = (
        "background:#2563eb;color:#fff;border:1px solid #2563eb"
        if primary
        else "background:#fff;color:#2563eb;border:1px solid #c7d2fe"
    )
    return (
        f'<a href="{html.escape(href)}" style="{style};display:inline-block;padding:4px 12px;'
        f'border-radius:6px;font-size:13px;text-decoration:none;margin-right:6px">{text}</a>'
    )


def task_html(t, now, site_url):
    p = progress_of(t)
    tags = ""
    if prio_of(t) == "high":
        tags += tag("🔥 Cao", "#fee2e2", "#991b1b")
    if group_of(t):
        tags += tag(group_of(t))
    if t.get("repeat") in REPEAT_TEXT:
        tags += tag("🔁 " + REPEAT_TEXT[t["repeat"]])
    note = (t.get("note") or "").strip()
    it = items(t)
    checklist = ""
    if it:
        def due(i):
            if not i.get("deadline") or days_left(i, now.date()) is None:
                return ""
            d = days_left(i, now.date())
            color = "#9ca3af" if i.get("done") else "#dc2626" if d < 0 else "#ea580c" if d == 0 else "#6b7280"
            return f' <span style="color:{color};font-size:12px">📅 {fmt_date(i["deadline"])[:5]}</span>'

        lines = "".join(
            f'<div style="font-size:13px;color:{"#9ca3af" if i.get("done") else "#333"}">'
            f'{"☑" if i.get("done") else "☐"} {html.escape(i.get("text", ""))}{due(i)}</div>'
            for i in it
        )
        checklist = f'<div style="margin-top:4px">{lines}</div>'
    buttons = ""
    if site_url and t.get("id"):
        tid = quote(str(t["id"]))
        plus_text = "☑ Tích việc con tiếp theo" if any(not i.get("done") for i in it) else "+25%"
        buttons = (
            '<div style="margin-top:8px">'
            + button(f"{site_url}?act=plus&id={tid}", plus_text)
            + button(f"{site_url}?act=done&id={tid}", "✓ Xong", primary=True)
            + "</div>"
        )
    return (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin-bottom:8px">'
        + (f"<div>{tags}</div>" if tags else "")
        + f'<b>{html.escape(t.get("title", ""))}</b><br>'
        + f'<span style="font-size:13px;color:#555">{when_text(t, now)}</span>'
        + (f'<div style="font-size:13px;color:#444;margin-top:4px">{html.escape(note)}</div>' if note else "")
        + checklist
        + bar(p)
        + buttons
        + "</div>"
    )


def group_summary(tasks):
    counts = {}
    for t in tasks:
        g = group_of(t) or NO_GROUP
        counts[g] = counts.get(g, 0) + 1
    if not counts or (len(counts) == 1 and NO_GROUP in counts):
        return ""
    names = sorted(counts, key=lambda g: (g == NO_GROUP, g.lower()))
    return " · ".join(f"{html.escape(g)} <b>{counts[g]}</b>" for g in names)


def wrap(title, body, site_url):
    footer = ""
    if site_url:
        footer = f'<p style="margin-top:20px">{button(site_url, "Mở danh sách việc", primary=True)}</p>'
    return (
        '<div style="font-family:Arial,sans-serif;max-width:600px;color:#111">'
        f'<h2 style="margin:0 0 4px">{title}</h2>{body}{footer}</div>'
    )


SECTIONS = [
    ("overdue", "🔴 Quá hạn", "#dc2626"),
    ("today", "🟠 Hạn hôm nay", "#ea580c"),
    ("soon", "🟡 Sắp đến hạn", "#ca8a04"),
    ("later", "⚪ Đang theo dõi", "#6b7280"),
]


def render_sections(groups, keys, now, site_url):
    parts = []
    for key, label, color in SECTIONS:
        if key not in keys or not groups[key]:
            continue
        parts.append(f'<h3 style="color:{color};margin:20px 0 8px">{label} ({len(groups[key])})</h3>')
        parts.extend(task_html(t, now, site_url) for t in groups[key])
    return "".join(parts)


# ---------------------------------------------------------------- các loại mail

def build_full(tasks, now, site_url):
    groups = classify(tasks, now)
    pending = [t for g in groups.values() for t in g]
    if not pending:
        return None
    summary = group_summary(pending)
    body = (f'<div style="font-size:13px;color:#555">Theo nhóm: {summary}</div>' if summary else "") + render_sections(
        groups, {"overdue", "today", "soon", "later"}, now, site_url
    )
    urgent = len(groups["overdue"]) + len(groups["today"]) + len(groups["soon"])
    subject = f"[Nhắc việc] {now:%d/%m}: {len(pending)} việc chưa xong"
    if groups["overdue"]:
        subject += f", {len(groups['overdue'])} quá hạn"
    elif urgent:
        subject += f", {urgent} việc gấp"
    return subject, wrap(f"Nhắc việc ngày {now:%d/%m/%Y}", body, site_url)


def build_urgent(tasks, now, site_url):
    groups = classify(tasks, now)
    n_over, n_today = len(groups["overdue"]), len(groups["today"])
    if not n_over and not n_today:
        return None
    parts = []
    if n_over:
        parts.append(f"{n_over} việc quá hạn")
    if n_today:
        parts.append(f"{n_today} việc hạn hôm nay")
    subject = f"[Nhắc việc] ⚠️ {now:%H}h: " + ", ".join(parts)
    body = render_sections(groups, {"overdue", "today"}, now, site_url)
    return subject, wrap(f"Cần xử lý ngay ({now:%H:%M})", body, site_url)


def build_weekly(tasks, now, site_url):
    week_ago = now - timedelta(days=7)
    done_week = []
    for t in tasks:
        if not is_done(t) or not t.get("doneAt"):
            continue
        try:
            done_at = datetime.fromisoformat(t["doneAt"].replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            continue
        if done_at >= week_ago:
            done_week.append(t)
    groups = classify(tasks, now)
    overdue = groups["overdue"]
    today = now.date()
    def due_soon(t):
        dls = [t] + [i for i in items(t) if not i.get("done")]
        return any((d := days_left(x, today)) is not None and 0 <= d <= 7 for x in dls)

    next_week = sorted([t for t in tasks if not is_done(t) and due_soon(t)], key=eff_deadline)
    open_all = [t for g in groups.values() for t in g]
    if not done_week and not open_all:
        return None

    def stat(n, label, color):
        return (
            f'<td style="border:1px solid #e5e7eb;border-radius:8px;padding:10px;text-align:center">'
            f'<div style="font-size:22px;font-weight:bold;color:{color}">{n}</div>'
            f'<div style="font-size:12px;color:#555">{label}</div></td>'
        )

    body = (
        '<table cellspacing="6" style="width:100%;margin-top:8px"><tr>'
        + stat(len(done_week), "Đã xong tuần này", "#16a34a")
        + stat(len(overdue), "Đang quá hạn", "#dc2626")
        + stat(len(next_week), "Hạn trong 7 ngày tới", "#ea580c")
        + stat(len(open_all), "Tổng việc chưa xong", "#111")
        + "</tr></table>"
    )
    summary = group_summary(done_week)
    if done_week:
        body += '<h3 style="color:#16a34a;margin:20px 0 8px">✅ Đã xong tuần này</h3>'
        if summary:
            body += f'<div style="font-size:13px;color:#555;margin-bottom:6px">Theo nhóm: {summary}</div>'
        body += "".join(
            f'<div style="font-size:14px;padding:2px 0">✓ {html.escape(t.get("title", ""))}'
            + (f' <span style="color:#888">· {html.escape(group_of(t))}</span>' if group_of(t) else "")
            + "</div>"
            for t in done_week
        )
    if overdue:
        body += '<h3 style="color:#dc2626;margin:20px 0 8px">🔴 Đang quá hạn</h3>'
        body += "".join(task_html(t, now, site_url) for t in overdue)
    if next_week:
        body += '<h3 style="color:#ea580c;margin:20px 0 8px">📅 Tuần tới</h3>'
        body += "".join(task_html(t, now, site_url) for t in next_week)
    subject = f"[Nhắc việc] Báo cáo tuần {(now - timedelta(days=6)):%d/%m}–{now:%d/%m}: xong {len(done_week)}, quá hạn {len(overdue)}"
    return subject, wrap("Báo cáo tuần", body, site_url)


def pick_mode(now):
    mode = (os.environ.get("MODE") or "auto").strip().lower()
    if mode in ("full", "urgent", "weekly"):
        return mode
    if now.hour < 9:
        return "full"
    if now.weekday() == 6 and 20 <= now.hour < 22:
        return "weekly"
    return "urgent"


# ---------------------------------------------------------------- gửi

def check_secrets():
    """Làm sạch và kiểm tra secrets, báo lỗi dễ hiểu mà không in giá trị ra log."""
    raw_user = os.environ.get("GMAIL_USER", "")
    raw_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    user = "".join(raw_user.split())
    password = "".join(raw_pass.split())
    to = "".join((os.environ.get("MAIL_TO") or "").split()) or user

    problems = []
    if not user:
        problems.append("Thiếu secret GMAIL_USER.")
    elif "=" in user or user.count("@") != 1 or not user.isascii():
        problems.append(
            "GMAIL_USER không phải một địa chỉ email hợp lệ. Ô Secret chỉ được chứa đúng địa chỉ, "
            "ví dụ ten@gmail.com (không ghi 'GMAIL_USER =')."
        )
    if not password:
        problems.append("Thiếu secret GMAIL_APP_PASSWORD.")
    elif not (len(password) == 16 and password.isascii() and password.isalpha()):
        problems.append(
            f"GMAIL_APP_PASSWORD sau khi bỏ dấu cách có {len(password)} ký tự"
            f"{'' if password.isascii() else ', có ký tự không phải ASCII'}"
            f"{', có chứa dấu =' if '=' in password else ''}. "
            "App Password của Gmail phải đúng 16 chữ cái. Ô Secret chỉ được chứa đúng mã đó."
        )
    if problems:
        print("LỖI CẤU HÌNH SECRETS:")
        for p in problems:
            print(" - " + p)
        print("Sửa tại: repo → Settings → Secrets and variables → Actions → bấm vào secret → Update.")
        sys.exit(1)
    if raw_user != user or raw_pass.replace(" ", "") != password:
        print("Lưu ý: đã tự bỏ dấu xuống dòng hoặc khoảng trắng thừa trong secrets.")
    return user, password, to


def send(subject, body):
    user, password, to = check_secrets()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Nhắc việc <{user}>"
    msg["To"] = to
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        try:
            s.login(user, password)
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected) as e:
            print(f"LỖI ĐĂNG NHẬP GMAIL: {e}")
            print(
                "Kiểm tra: (1) GMAIL_USER đúng là tài khoản đã tạo App Password; "
                "(2) App Password còn hiệu lực (chưa bị xóa); "
                "(3) tài khoản đã bật xác minh 2 bước."
            )
            sys.exit(1)
        s.sendmail(user, [a for a in to.split(",") if a], msg.as_string())
    print(f"Đã gửi mail tới {to}: {subject}")


def main():
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(TZ)
    if os.environ.get("NOW"):  # chỉ dùng khi chạy thử
        now = datetime.fromisoformat(os.environ["NOW"]).replace(tzinfo=TZ)
    site_url = (os.environ.get("SITE_URL") or "").strip()
    tasks = load_tasks()
    mode = pick_mode(now)
    print(f"Chế độ: {mode} ({now:%A %d/%m %H:%M})")

    built = {"full": build_full, "urgent": build_urgent, "weekly": build_weekly}[mode](tasks, now, site_url)
    if not built:
        print("Không có gì cần nhắc ở chế độ này, không gửi mail.")
        return
    subject, body = built
    if dry_run:
        print(subject)
        print(body)
        return
    send(subject, body)


if __name__ == "__main__":
    main()
