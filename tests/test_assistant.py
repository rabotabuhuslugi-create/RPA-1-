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
