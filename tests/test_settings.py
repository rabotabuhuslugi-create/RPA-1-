import yaml

from rpa1c import config as cfgmod, settings


def test_roundtrip_and_password_kept(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = cfgmod.load("config.yaml")
    assert not cfgmod.is_configured(cfg)
    settings.update(cfg, {"base_url": "http://x/odata", "user": " u ", "password": "p",
                          "warehouse_key": "", "post_document": True, "poll_seconds": "45"})
    settings.update(cfg, {"password": ""})  # пустой пароль не затирает
    c2 = cfgmod.load("config.yaml")
    assert cfgmod.is_configured(c2) and c2["onec"]["user"] == "u"
    assert c2["onec"]["warehouse_key"] is None and c2["rpa"]["poll_seconds"] == 45
    assert "has_password" in settings.read(c2) and "password" not in settings.read(c2)
    assert yaml.safe_load(open("config.yaml", encoding="utf-8"))["onec"]["post_document"] is True
