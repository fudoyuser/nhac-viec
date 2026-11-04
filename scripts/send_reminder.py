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

def load_data():
    """Trả về (tasks, exams). Dữ liệu cũ là một mảng việc; dữ liệu mới là {"groups", "tasks", "exams"}."""
    if not TASKS_FILE.exists():
        print(f"Chưa có file {TASKS_FILE} (chưa thêm việc nào trên website).")
        return [], []
    with open(TASKS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, []
    return data.get("tasks", []), data.get("exams", [])


def load_tasks():
    return load_data()[0]


def items(t):
    return t.get("items") if isinstance(t.get("items"), list) else []


# ----- Đo bằng số lượng (trang, tập, phút…) — giống hệt logic trên website -----
DEFAULT_STEP = {"trang": 10, "phút": 5, "tập": 1, "chương": 1, "bài": 1, "giờ": 1, "km": 1, "câu": 5}


def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def fmt_num(n):
    n = round(n * 10) / 10
    return (str(int(n)) if n == int(n) else str(n)).replace(".", ",")


def default_step(unit):
    return DEFAULT_STEP.get((unit or "").strip().lower(), 1)


def is_count(t):
    return t.get("measure") == "count" and num(t.get("total")) > 0


def has_sub(t):
    return is_count(t) and isinstance(t.get("sub"), dict) and num(t["sub"].get("total")) > 0


def step_of(t):
    return num(t.get("step")) if num(t.get("step")) > 0 else default_step(t.get("unit"))


def sub_step_of(t):
    s_ = t.get("sub") or {}
    return num(s_.get("step")) if num(s_.get("step")) > 0 else default_step(s_.get("unit"))


def count_value(t):
    frac = 0.0
    if has_sub(t) and num(t.get("current")) < num(t.get("total")):
        frac = min(1.0, num(t["sub"].get("current")) / num(t["sub"]["total"]))
    return min(num(t.get("total")), num(t.get("current")) + frac)


def sub_label(t):
    unit = t.get("unit") or ""
    n = min(int(num(t.get("current"))) + 1, int(-(-num(t.get("total")) // 1)))
    return f"{unit[:1].upper()}{unit[1:]} {n}"


def pace_text(t, now):
    """Nhịp độ cần đạt để kịp deadline và có đang chậm không."""
    if not is_count(t) or is_done(t) or not t.get("deadline"):
        return ""
    unit = html.escape(t.get("unit") or "")
    remaining = num(t["total"]) - count_value(t)
    d = days_left(t, now.date())
    if d is None:
        return ""
    if d < 0:
        return f'<b style="color:#dc2626">Đã quá hạn, còn {fmt_num(remaining)} {unit}</b>'
    per = remaining / (d + 1)
    per_txt = str(int(-(-per // 1))) if per >= 1 else fmt_num(per)
    text = f"📈 Cần ~{per_txt} {unit}/ngày để kịp deadline"
    try:
        start = date.fromisoformat(t.get("startDate") or "")
        total_days = (date.fromisoformat(t["deadline"]) - start).days + 1
        elapsed = (now.date() - start).days
    except ValueError:
        return text
    if total_days > 0 and elapsed > 0:
        sv = num(t.get("startValue"))
        expected = sv + (num(t["total"]) - sv) * elapsed / total_days
        gap = expected - count_value(t)
        if gap >= max(0.5, step_of(t) / 2):
            g = str(int(-(-gap // 1))) if gap >= 1 else fmt_num(gap)
            text += f' · <b style="color:#dc2626">Đang chậm {g} {unit} so với kế hoạch</b>'
        else:
            text += ' · <b style="color:#16a34a">Đúng tiến độ ✓</b>'
    return text


def progress_of(t):
    if is_count(t):
        if num(t.get("current")) >= num(t.get("total")):
            return 100
        return min(99, int(count_value(t) / num(t["total"]) * 100))
    it = items(t)
    if it:
        if item_task_done(t):
            return 100
        return min(99, round(sum(1 for i in it if i.get("done")) / len(it) * 100))
    try:
        return max(0, min(100, int(float(t.get("progress") or 0))))
    except ValueError:
        return 0


def item_task_done(t):
    """Việc có việc con chỉ xong khi đã bấm ✓ Xong (done = true), không tự xong khi tích hết việc con.
    Dữ liệu cũ (chưa có cờ done) mà đã tích hết việc con và có doneAt thì vẫn coi là xong."""
    it = items(t)
    if t.get("done") is True:
        return True
    return t.get("done") is None and bool(t.get("doneAt")) and bool(it) and all(i.get("done") for i in it)


def is_done(t):
    if not is_count(t) and items(t):
        return item_task_done(t)
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
    return min(cands, key=lambda i: i["deadline"] + (i.get("time") or "99:99")) if cands else None


def status_of(t, now):
    """Mức gấp của cả việc = gấp nhất giữa deadline chính và deadline các việc con chưa xong."""
    if is_done(t):
        return "done"
    s = status_at(t.get("deadline"), parse_time(t), remind_of(t), now)
    it = urgent_item(t)
    if it:
        si = status_at(it["deadline"], parse_time(it), remind_of(t), now)
        if STATUS_RANK[si] < STATUS_RANK[s]:
            s = si
    return s


def eff_deadline(t):
    main = (t.get("deadline") or "9999-99-99") + (t.get("time") or "99:99")
    it = urgent_item(t)
    sub = it["deadline"] + (it.get("time") or "99:99") if it else "9999-99-99"
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


def item_late(i, now):
    d = days_left(i, now.date())
    tm = parse_time(i)
    return d is not None and (d < 0 or (d == 0 and tm is not None and now.time() > tm))


def due_text(i, now):
    d = days_left(i, now.date())
    tm = parse_time(i)
    at = f" {i['time']}" if tm else ""
    if d < 0:
        return f"quá hạn {-d} ngày · {fmt_date(i['deadline'])}{at}"
    if d == 0:
        return f"quá hạn từ {i['time']} hôm nay" if tm and now.time() > tm else f"hạn hôm nay{at}"
    return f"còn {d} ngày · {fmt_date(i['deadline'])}{at}"


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
        late = item_late(it, now)
        sub = due_text(it, now)
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
            color = "#9ca3af" if i.get("done") else "#dc2626" if item_late(i, now) else "#ea580c" if d == 0 else "#6b7280"
            at = f" {i['time']}" if parse_time(i) else ""
            return f' <span style="color:{color};font-size:12px">📅 {fmt_date(i["deadline"])[:5]}{at}</span>'

        lines = "".join(
            f'<div style="font-size:13px;color:{"#9ca3af" if i.get("done") else "#333"}">'
            f'{"☑" if i.get("done") else "☐"} {html.escape(i.get("text", ""))}{due(i)}</div>'
            for i in it
        )
        checklist = f'<div style="margin-top:4px">{lines}</div>'
    buttons = ""
    if site_url and t.get("id"):
        tid = quote(str(t["id"]))
        if is_count(t):
            plus_text = f"+{fmt_num(step_of(t))} {html.escape(t.get('unit') or '')}"
        elif any(not i.get("done") for i in it):
            plus_text = "☑ Tích việc con tiếp theo"
        elif it:
            plus_text = ""  # đã tích hết việc con: chỉ còn nút Xong cả việc
        else:
            plus_text = "+25%"
        sub_btn = ""
        if has_sub(t):
            sub_btn = button(
                f"{site_url}?act=splus&id={tid}",
                f"+{fmt_num(sub_step_of(t))} {html.escape(t['sub'].get('unit') or '')}",
            )
        buttons = (
            '<div style="margin-top:8px">'
            + (button(f"{site_url}?act=plus&id={tid}", plus_text) if plus_text else "")
            + sub_btn
            + button(f"{site_url}?act=done&id={tid}", "✓ Xong cả việc" if it and not is_count(t) else "✓ Xong", primary=True)
            + "</div>"
        )
    count_html = ""
    if is_count(t):
        unit = html.escape(t.get("unit") or "")
        count_html = (
            f'<div style="font-size:14px;margin-top:6px">{"Đã xong" if has_sub(t) else "Đang ở"} <b>{fmt_num(num(t.get("current")))}</b>'
            f' / {fmt_num(num(t["total"]))} {unit}</div>'
        )
        if has_sub(t) and not is_done(t):
            sub = t["sub"]
            count_html += (
                f'<div style="font-size:14px">▶ {html.escape(sub_label(t))}: <b>{fmt_num(num(sub.get("current")))}</b>'
                f' / {fmt_num(num(sub["total"]))} {html.escape(sub.get("unit") or "")}</div>'
            )
        pace = pace_text(t, now)
        if pace:
            count_html += f'<div style="font-size:13px;color:#555;margin-top:2px">{pace}</div>'

    return (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin-bottom:8px">'
        + (f"<div>{tags}</div>" if tags else "")
        + f'<b>{html.escape(t.get("title", ""))}</b><br>'
        + f'<span style="font-size:13px;color:#555">{when_text(t, now)}</span>'
        + (f'<div style="font-size:13px;color:#444;margin-top:4px">{html.escape(note)}</div>' if note else "")
        + checklist
        + count_html
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
    return subject, f"Nhắc việc ngày {now:%d/%m/%Y}", body


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
    return subject, f"Cần xử lý ngay ({now:%H:%M})", body


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
    return subject, "Báo cáo tuần", body


# ---------------------------------------------------------------- lịch thi

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]


def exam_date(e):
    try:
        return date.fromisoformat(e.get("date") or "")
    except ValueError:
        return None


def exam_start(e):
    d = exam_date(e)
    if not d:
        return None
    tm = parse_time(e) or datetime.min.time()
    return datetime.combine(d, tm, tzinfo=TZ)


def exam_end(e):
    d = exam_date(e)
    if not d:
        return None
    if parse_time(e):
        return exam_start(e) + timedelta(minutes=num(e.get("duration")))
    return datetime.combine(d, datetime.max.time(), tzinfo=TZ)


def exam_state(e, now):
    """past (đã thi) · now (đang thi) · today · soon (≤3 ngày) · upcoming · nodate"""
    d = exam_date(e)
    if not d:
        return "nodate"
    if now > exam_end(e):
        return "past"
    if parse_time(e) and now >= exam_start(e):
        return "now"
    left = (d - now.date()).days
    if left == 0:
        return "today"
    return "soon" if left <= 3 else "upcoming"


def exam_countdown(e, now):
    st = exam_state(e, now)
    if st == "now":
        return "✍️ Đang thi"
    left = (exam_date(e) - now.date()).days
    if left == 0:
        if not parse_time(e):
            return "⏰ Thi hôm nay"
        mins = max(0, int((exam_start(e) - now).total_seconds() // 60))
        return f"⏰ Hôm nay · còn {str(mins // 60) + ' giờ ' if mins >= 60 else ''}{mins % 60} phút"
    if left == 1:
        return "⏳ Ngày mai thi"
    return f"⏳ Còn {left} ngày"


def exam_html(e, now):
    d = exam_date(e)
    st = exam_state(e, now)
    color = {"today": "#ea580c", "now": "#ea580c", "soon": "#dc2626"}.get(st, "#7c3aed")
    when = f"📅 {WEEKDAY_VI[d.weekday()]}, {d:%d/%m/%Y}"
    if parse_time(e):
        when += f" · {e['time']}"
    if num(e.get("duration")):
        when += f" ({fmt_num(num(e['duration']))} phút)"
    tags = (tag(e["term"], "#ede9fe", "#5b21b6") if e.get("term") else "") + (tag(e["form"], "#f3f4f6", "#374151") if e.get("form") else "")
    info = " · ".join(x for x in [
        f"📍 Phòng {html.escape(e['room'])}" if e.get("room") else "",
        f"🎫 SBD {html.escape(e['seat'])}" if e.get("seat") else "",
    ] if x)
    pl = [i for i in (e.get("plan") or []) if isinstance(i, dict)]
    plan_html = ""
    if pl:
        done_n = sum(1 for i in pl if i.get("done"))
        late = [i for i in pl if not i.get("done") and (dl := days_left(i, now.date())) is not None and dl < 0]
        plan_html = f'<div style="font-size:13px;color:#555;margin-top:6px">Ôn tập {done_n}/{len(pl)}'
        if late:
            plan_html += f' · <b style="color:#dc2626">{len(late)} phần trễ</b>'
        plan_html += "</div>"
        for i in [i for i in pl if not i.get("done")][:3]:
            dl = days_left(i, now.date())
            c = "#dc2626" if dl is not None and dl < 0 else "#ea580c" if dl == 0 else "#6b7280"
            due = f' <span style="color:{c};font-size:12px">📅 {fmt_date(i["deadline"])[:5]}</span>' if dl is not None else ""
            plan_html += f'<div style="font-size:13px">☐ {html.escape(i.get("text", ""))}{due}</div>'
        plan_html += bar(round(done_n / len(pl) * 100))
    note = (e.get("note") or "").strip()
    return (
        f'<div style="border:1px solid #e5e7eb;border-left:4px solid {color};border-radius:8px;padding:10px 12px;margin-bottom:8px">'
        + (f"<div>{tags}</div>" if tags else "")
        + f'<b style="font-size:16px">{html.escape(e.get("subject", ""))}</b>'
        + f'<div style="font-size:14px;margin-top:2px">{when}</div>'
        + f'<div style="font-size:15px;font-weight:bold;color:{color};margin-top:2px">{exam_countdown(e, now)}</div>'
        + (f'<div style="font-size:14px;color:#555">{info}</div>' if info else "")
        + (f'<div style="font-size:13px;color:#444;margin-top:4px">🎒 {html.escape(note)}</div>' if note else "")
        + plan_html
        + "</div>"
    )


def exam_section(mode, exams, now):
    """Phần lịch thi trong mail: (tiền tố tiêu đề, html) hoặc None."""
    live = [e for e in exams if exam_state(e, now) not in ("past", "nodate")]
    live.sort(key=lambda e: exam_start(e))
    today = [e for e in live if exam_date(e) == now.date() and exam_state(e, now) == "today"]  # chưa bắt đầu thi
    tomorrow = [e for e in live if (exam_date(e) - now.date()).days == 1]
    if mode == "full":
        show, title = [e for e in live if (exam_date(e) - now.date()).days <= 14], "📝 Lịch thi 14 ngày tới"
    elif mode == "weekly":
        show, title = [e for e in live if (exam_date(e) - now.date()).days <= 7], "📝 Lịch thi tuần tới"
    else:  # urgent: thi hôm nay, và từ 18h thì nhắc cả môn thi ngày mai
        show, title = today + (tomorrow if now.hour >= 18 else []), "📝 Sắp thi"
    if not show:
        return None

    def names(lst):
        return ", ".join(e.get("subject", "") + (f" {e['time']}" if parse_time(e) else "") for e in lst)

    if today:
        prefix = f"📝 Hôm nay thi {names(today)}"
    elif tomorrow and (mode != "urgent" or now.hour >= 18):
        prefix = f"📝 Mai thi {names(tomorrow)}"
    else:
        first = show[0]
        prefix = f"📝 Còn {(exam_date(first) - now.date()).days} ngày thi {first.get('subject', '')}"
    body = f'<h3 style="color:#7c3aed;margin:20px 0 8px">{title} ({len(show)})</h3>' + "".join(exam_html(e, now) for e in show)
    return prefix, body


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
    tasks, exams = load_data()
    mode = pick_mode(now)
    print(f"Chế độ: {mode} ({now:%A %d/%m %H:%M})")

    built = {"full": build_full, "urgent": build_urgent, "weekly": build_weekly}[mode](tasks, now, site_url)
    ex = exam_section(mode, exams, now)
    if not built and not ex:
        print("Không có gì cần nhắc ở chế độ này, không gửi mail.")
        return
    if built:
        subject, title, body = built
        if ex:
            subject = subject.replace("[Nhắc việc] ", f"[Nhắc việc] {ex[0]} · ", 1)
            body = ex[1] + body
    else:
        subject, title, body = f"[Nhắc việc] {ex[0]}", "Lịch thi", ex[1]
    exam_link = f"{site_url}?tab=exams" if ex and site_url else ""
    body = wrap(title, body, site_url)
    if exam_link:
        body = body.replace("Mở danh sách việc</a></p>", f"Mở danh sách việc</a>{button(exam_link, '📝 Mở lịch thi')}</p>", 1)
    if dry_run:
        print(subject)
        print(body)
        return
    send(subject, body)


if __name__ == "__main__":
    main()
