"""Логика оповещений: что пора показать пользователю (без GUI, легко тестируется)."""
from __future__ import annotations

import datetime as dt


def due_reminders(events, now, default_lead, seen: set, grace_minutes=5):
    """События, у которых наступило время напоминания и о которых ещё не сообщали.

    Ключ в seen = (id события, минуты до начала), поэтому несколько напоминаний
    одного события срабатывают по отдельности. Возвращает [(event, minutes_left)].
    """
    out = []
    for e in events:
        if e["all_day"]:
            continue
        leads = e["leads"] or ([default_lead] if e["use_default"] else [])
        left = (e["start"] - now).total_seconds() / 60
        if left < -grace_minutes:
            continue
        for lead in leads:
            key = (e["id"], lead)
            if left <= lead and key not in seen:
                seen.add(key)
                out.append((e, max(0, round(left))))
                break  # одно уведомление за проход на событие
    return out


def new_mail(messages, seen: set, first_run: bool):
    """Новые непрочитанные письма. При первом запуске только запоминаем (без шума)."""
    fresh = [m for m in messages if m["id"] not in seen]
    seen.update(m["id"] for m in messages)
    return [] if first_run else fresh


def reminder_text(event, minutes_left):
    when = event["start"].astimezone().strftime("%H:%M")
    if minutes_left <= 0:
        return f"Сейчас: {event['summary']} ({when})"
    return f"Через {minutes_left} мин: {event['summary']} ({when})"
