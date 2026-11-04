"""Sửa các deadline có vẻ bị nhầm năm trong tasks.json.

Deadline (của việc chính hoặc việc con) cũ hơn hôm nay quá 1 năm sẽ được đổi sang
cùng ngày/tháng của năm hiện tại (giờ Việt Nam). In ra từng thay đổi.

Cách dùng:  python scripts/fix_dates.py data/tasks.json [--dry-run]
"""

import json
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def fix(d, today):
    try:
        old = date.fromisoformat(d)
    except (TypeError, ValueError):
        return None
    if old >= today - timedelta(days=365):
        return None
    try:
        new = old.replace(year=today.year)
    except ValueError:  # 29/02 sang năm không nhuận
        new = old.replace(year=today.year, day=28)
    return new.isoformat()


def main():
    path = sys.argv[1]
    dry = "--dry-run" in sys.argv
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tasks = data if isinstance(data, list) else data.get("tasks", [])

    changes = []
    for t in tasks:
        new = fix(t.get("deadline"), today)
        if new:
            changes.append(f"“{t.get('title')}”: {t['deadline']} → {new}")
            t["deadline"] = new
        for i in t.get("items") or []:
            new = fix(i.get("deadline"), today)
            if new:
                changes.append(f"“{t.get('title')}” › việc con “{i.get('text')}”: {i['deadline']} → {new}")
                i["deadline"] = new

    if not changes:
        print("Không có deadline nào bị nhầm năm.")
        return
    for c in changes:
        print("Sửa:", c)
    if dry:
        print("(chạy thử, chưa ghi file)")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Đã sửa {len(changes)} deadline.")


if __name__ == "__main__":
    main()
