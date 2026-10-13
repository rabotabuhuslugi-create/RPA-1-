import datetime as dt

from assistant.watcher import due_reminders, new_mail, reminder_text

NOW = dt.datetime(2026, 10, 13, 10, 0, tzinfo=dt.timezone.utc)


def ev(id_, minutes, leads=(), use_default=True, all_day=False):
    return {"id": id_, "summary": "Встреча", "start": NOW + dt.timedelta(minutes=minutes),
            "all_day": all_day, "leads": list(leads), "use_default": use_default}


def test_default_lead_and_dedupe():
    seen = set()
    assert due_reminders([ev("a", 30)], NOW, 10, seen) == []
    assert len(due_reminders([ev("a", 8)], NOW, 10, seen)) == 1
    assert due_reminders([ev("a", 8)], NOW, 10, seen) == []


def test_own_reminder_and_skips():
    seen = set()
    assert len(due_reminders([ev("b", 25, leads=[30])], NOW, 10, seen)) == 1
    assert due_reminders([ev("c", 5, use_default=False)], NOW, 10, seen) == []
    assert due_reminders([ev("d", 5, all_day=True)], NOW, 10, seen) == []
    assert due_reminders([ev("e", -30)], NOW, 10, seen) == []


def test_mail_first_run_silent():
    seen = set()
    msgs = [{"id": "1"}, {"id": "2"}]
    assert new_mail(msgs, seen, True) == []
    assert new_mail(msgs + [{"id": "3"}], seen, False) == [{"id": "3"}]


def test_text():
    assert "Через 8 мин" in reminder_text(ev("a", 8), 8)


def test_server_auth_and_config(tmp_path, monkeypatch):
    import json, threading, urllib.error, urllib.request
    monkeypatch.chdir(tmp_path)
    from assistant import server
    core, srv = server.serve(8773)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(path, method="GET", body=None, token=True):
        req = urllib.request.Request("http://127.0.0.1:8773" + path, data=body, method=method,
                                     headers={"X-Token": core.token} if token else {})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    assert call("/api/state", token=False) == 403
    assert call("/api/state") == 200
    body = json.dumps({"drive_folders": [{"name": "A", "id": "ok-1"}, {"name": "B", "id": "a'b"}]}).encode()
    assert call("/api/config", "POST", body) == 200
    assert core.cfg["drive_folders"] == [{"name": "A", "id": "ok-1"}]
    assert call("/api/key", "POST", b'{"x": 1}') == 500
    srv.shutdown()


def test_local_calendar_reminder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from assistant import server
    core = server.Core()
    soon = dt.datetime.now() + dt.timedelta(minutes=5)
    core.add_event({"title": "Тест", "date": soon.date().isoformat(), "time": soon.strftime("%H:%M")})
    core.add_event({"title": "Без времени", "date": soon.date().isoformat()})
    assert len(server.load_local()) == 2  # сохранено на диск
    core.rebuild()
    due = due_reminders(core.events, dt.datetime.now(dt.timezone.utc), 10, set())
    assert [e["summary"] for e, _ in due] == ["Тест"]
    core.delete_event(core.local[0]["id"])
    assert len(server.load_local()) == 1


def test_imap_helpers():
    from assistant.imap_mail import _dec, host_for
    assert _dec("=?utf-8?b?0JHRg9GF0LPQsNC70YLQtdGA0LjRjw==?=") == "Бухгалтерия"
    assert host_for("a@mail.ru") == "imap.mail.ru" and host_for("a@yandex.ru") == "imap.yandex.ru"


def test_local_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from assistant import server
    core = server.Core()
    core.task_add("Позвонить", "2026-10-20")
    tid = core.tasks()[0]["id"]
    core.task_change(tid)
    assert core.tasks() == []


def test_production_calendar_2026():
    from assistant import prodcal
    work = [sum(c != "1" for c in prodcal.builtin(2026, m)) for m in range(1, 13)]
    assert work == [15, 19, 21, 22, 19, 21, 23, 21, 22, 22, 20, 22]  # официально: 247 дней
    assert sum(work) == 247
