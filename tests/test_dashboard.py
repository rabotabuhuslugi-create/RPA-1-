import json
import urllib.request
from pathlib import Path

from rpa1c.dashboard import serve
from rpa1c.state import State


def _cfg(tmp: Path) -> dict:
    f = {k: str(tmp / k) for k in ("inbox", "processed", "errors", "debug", "state")}
    for p in f.values():
        Path(p).mkdir()
    return {"folders": f, "rpa": {"poll_seconds": 30}, "dashboard": {"host": "127.0.0.1", "port": 0}}


def _call(srv, path, data=None, method="GET"):
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_dashboard_api(tmp_path):
    cfg = _cfg(tmp_path)
    st = State(cfg["folders"]["state"])
    st.set_status(state="working", current="a.pdf", stage="Разбор реквизитов")
    st.add_history({"file": "a.pdf", "status": "loaded", "seconds": 3.0})
    st.add_history({"file": "b.pdf", "status": "error", "error": "x"})
    srv = serve(cfg, st, block=False)
    try:
        code, body = _call(srv, "/api/state")
        d = json.loads(body)
        assert code == 200 and d["stats"]["loaded"] == 1 and d["stats"]["errors"] == 1
        assert d["robot"]["online"] and d["robot"]["current"] == "a.pdf"

        # загрузка + защита от обхода каталогов и неверных расширений
        assert _call(srv, "/api/upload?name=..%2F..%2Fx.pdf", b"%PDF-1", "POST")[0] == 200
        assert (Path(cfg["folders"]["inbox"]) / "x.pdf").exists()
        assert _call(srv, "/api/upload?name=evil.exe", b"MZ", "POST")[0] == 400

        # пауза
        _call(srv, "/api/pause", b"", "POST")
        assert st.paused()
        _call(srv, "/api/resume", b"", "POST")
        assert not st.paused()

        # повтор из errors
        (Path(cfg["folders"]["errors"]) / "b.pdf").write_bytes(b"1")
        assert _call(srv, "/api/retry?name=b.pdf", b"", "POST")[0] == 200
        assert (Path(cfg["folders"]["inbox"]) / "b.pdf").exists()
        assert _call(srv, "/")[0] == 200
    finally:
        srv.shutdown()


def test_check_lists_missing(monkeypatch, capsys):
    from rpa1c import check, config

    xml = '<EntitySet Name="Catalog_Организации"/><EntitySet Name="Document_ПоступлениеТоваровУслуг"/>'

    class R:
        status_code = 200
        text = xml
        def raise_for_status(self): pass

    monkeypatch.setattr(check.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(config, "load", lambda p: {"onec": {
        "base_url": "http://x", "user": "u", "password": "p",
        "counterparty_entity": "Catalog_Контрагенты", "contract_entity": "Catalog_ДоговорыКонтрагентов",
        "document_entity": "Document_ПоступлениеТоваровУслуг",
        "attachment_entity": "Catalog_ПоступлениеТоваровУслугПрисоединенныеФайлы"}})
    monkeypatch.setattr("sys.argv", ["check"])
    assert check.main() == 1
    out = capsys.readouterr().out
    assert "OK       Document_ПоступлениеТоваровУслуг" in out
    assert "Метаданные.Справочники.Контрагенты" in out


def test_create_document_body():
    from datetime import date
    from decimal import Decimal

    from rpa1c.onec import OneC
    from rpa1c.parser import DocData

    o = OneC({"base_url": "http://x", "user": "u", "password": "p", "organization_key": "ORG",
              "warehouse_key": "WH", "department_key": "DEP", "document_entity": "Document_ПриобретениеТоваровУслуг",
              "counterparty_entity": "c", "contract_entity": "k",
              "extra_document_fields": {"ХозяйственнаяОперация": "Другая"}})
    o.find_counterparty = lambda inn, kpp: {"Ref_Key": "CP", "Партнер_Key": "PR"}
    o.find_contract = lambda key: {"Ref_Key": "CT", "ВалютаВзаиморасчетов_Key": "CUR"}
    sent = {}
    o._post = lambda entity, body: sent.update(body) or {"Ref_Key": "D"}
    o.create_document(DocData(number="950", doc_date=date(2026, 9, 18), inn="1", total=Decimal("57600")))
    assert sent["Договор_Key"] == "CT" and sent["Валюта_Key"] == "CUR" and sent["Склад_Key"] == "WH"
    assert sent["Подразделение_Key"] == "DEP" and sent["Партнер_Key"] == "PR"
    assert sent["ХозяйственнаяОперация"] == "Другая"          # config перекрывает значения по умолчанию
    assert sent["НалогообложениеНДС"] == "ПродажаОблагаетсяНДС" and sent["Date"].startswith("2026-09-18")
