"""Export the saved weekly practice schedule as an iCalendar event."""

from datetime import date, datetime, timedelta, timezone


def escape_text(value):
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(value):
    lines, current = [], ""
    length = 0
    for character in value:
        size = len(character.encode("utf-8"))
        if length + size > 75:
            lines.append(current)
            current, length = " ", 1
        current += character
        length += size
    return "\r\n".join([*lines, current])


def calendar_file(owner, schedule, tasks):
    if not schedule:
        raise ValueError("请先保存每周练习安排，再导出日历")
    days = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Piano AI Coach//Practice Calendar//ZH",
        "CALSCALE:GREGORIAN",
    ]
    projects = tasks or [{"id":"schedule", "title":"钢琴练习", "detail":"", "weekdays":[]}]
    for task in projects:
        selected = sorted(set(schedule["weekdays"]) & set(task.get("weekdays") or schedule["weekdays"]))
        if not selected:
            continue
        start = date.fromisoformat(schedule["start_date"])
        try:
            while start.weekday() not in selected:
                start += timedelta(days=1)
            end = start + timedelta(days=1)
        except OverflowError:
            raise ValueError("请调整练习开始日期后再导出") from None
        last = schedule.get("end_date")
        if last and start.isoformat() > last:
            continue
        recurrence = "RRULE:FREQ=WEEKLY;WKST=MO;BYDAY=" + ",".join(days[index] for index in selected)
        if last:
            recurrence += ";UNTIL=" + last.replace("-", "")
        identifier = task.get("id", "schedule")
        lines.extend([
            "BEGIN:VEVENT", f"UID:piano-practice-{owner}-{identifier}@piano.local",
            "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "DTSTART;VALUE=DATE:" + start.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + end.strftime("%Y%m%d"),
            recurrence, "SUMMARY:" + escape_text(task["title"]), "DESCRIPTION:" + escape_text(task["detail"]),
            "TRANSP:TRANSPARENT", "END:VEVENT",
        ])
    if "BEGIN:VEVENT" not in lines:
        raise ValueError("当前日期范围内没有练习日，请调整日期或星期后再导出")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold_line(line) for line in lines) + "\r\n").encode("utf-8")
