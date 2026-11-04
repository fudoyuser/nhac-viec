"""Thêm lịch thi vào tasks.json (dùng trong workflow "Thêm lịch thi").

Đọc danh sách môn thi dạng JSON từ biến môi trường EXAMS_JSON, thêm vào mục "exams"
của file dữ liệu. Bỏ qua môn đã có (trùng tên môn + ngày thi).

Cách dùng:  EXAMS_JSON='[...]' python scripts/add_exams.py data/tasks.json
"""

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

FIELDS = ("subject", "term", "date", "time", "duration", "room", "seat", "form", "score", "note")


def main():
    path = Path(sys.argv[1])
    new = json.loads(os.environ["EXAMS_JSON"])
    if not isinstance(new, list):
        sys.exit("EXAMS_JSON phải là một danh sách môn thi")

    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if isinstance(data, list):
        data = {"groups": [], "tasks": data}
    data.setdefault("groups", [])
    data.setdefault("tasks", [])
    exams = data.setdefault("exams", [])

    have = {(e.get("subject", "").strip().lower(), e.get("date")) for e in exams}
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for raw in new:
        e = {k: raw.get(k, "") for k in FIELDS}
        e["subject"] = str(e["subject"]).strip()
        try:
            date.fromisoformat(e["date"])
        except (TypeError, ValueError):
            print(f"Bỏ qua (ngày không hợp lệ): {raw}")
            continue
        if not e["subject"]:
            print(f"Bỏ qua (thiếu tên môn): {raw}")
            continue
        key = (e["subject"].lower(), e["date"])
        if key in have:
            print(f"Đã có, bỏ qua: {e['subject']} {e['date']}")
            continue
        e.update(id=uuid.uuid4().hex[:12], plan=raw.get("plan") or [], createdAt=now)
        exams.append(e)
        have.add(key)
        added += 1
        print(f"Thêm: {e['subject']} · {e['date']} {e['time']} · phòng {e['room'] or '-'} · {e['form'] or ''}")

    if added:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã thêm {added} môn thi.")


if __name__ == "__main__":
    main()
