"""Почта по IMAP (mail.ru, Яндекс, Gmail, Rambler и др.) — без Google Cloud."""
from __future__ import annotations

import email
import imaplib
from email.header import decode_header, make_header

PRESETS = {
    "mail.ru": "imap.mail.ru", "inbox.ru": "imap.mail.ru", "list.ru": "imap.mail.ru", "bk.ru": "imap.mail.ru",
    "yandex.ru": "imap.yandex.ru", "ya.ru": "imap.yandex.ru", "yandex.com": "imap.yandex.com",
    "gmail.com": "imap.gmail.com", "rambler.ru": "imap.rambler.ru", "outlook.com": "outlook.office365.com",
}


def host_for(address: str) -> str:
    domain = address.rsplit("@", 1)[-1].lower()
    return PRESETS.get(domain, "imap." + domain)


def _dec(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def fetch_unread(address: str, password: str, host: str | None = None, limit: int = 20) -> list[dict]:
    conn = imaplib.IMAP4_SSL(host or host_for(address), 993, timeout=20)
    try:
        conn.login(address, password)
        conn.select("INBOX", readonly=True)
        _typ, data = conn.uid("search", None, "UNSEEN")
        uids = (data[0] or b"").split()[-limit:][::-1]
        out = []
        for uid in uids:
            _t, parts = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            msg = email.message_from_bytes(raw)
            out.append({"id": uid.decode(), "from": _dec(msg["From"]),
                        "subject": _dec(msg["Subject"]) or "(без темы)", "snippet": ""})
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass
