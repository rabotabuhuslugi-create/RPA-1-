"""Тонкая обёртка над Google API: календарь, задачи, диск, почта."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

FOLDER_MIME = "application/vnd.google-apps.folder"


def parse_when(value: dict) -> tuple[dt.datetime, bool]:
    """Календарное start/end -> (aware datetime, весь_день)."""
    if "dateTime" in value:
        return dt.datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")), False
    day = dt.date.fromisoformat(value["date"])
    return dt.datetime.combine(day, dt.time.min).astimezone(), True


class Google:
    def __init__(self, credentials_file="credentials.json", token_file="token.json"):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self._svc: dict = {}

    def _creds(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not self.credentials_file.exists():
                raise FileNotFoundError(
                    f"Нет {self.credentials_file}. Скачайте OAuth-ключ (см. assistant/README.md)")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
            creds = flow.run_local_server(port=0)
        self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _service(self, name, version):
        if name not in self._svc:
            from googleapiclient.discovery import build
            self._svc[name] = build(name, version, credentials=self._creds(), cache_discovery=False)
        return self._svc[name]

    # --- календарь ---
    def events(self, days=14, past_days=0) -> list[dict]:
        now = dt.datetime.now(dt.timezone.utc)
        res = self._service("calendar", "v3").events().list(
            calendarId="primary", singleEvents=True, orderBy="startTime", maxResults=250,
            timeMin=(now - dt.timedelta(days=past_days)).isoformat(),
            timeMax=(now + dt.timedelta(days=days)).isoformat()).execute()
        out = []
        for e in res.get("items", []):
            if e.get("status") == "cancelled" or "start" not in e:
                continue
            start, all_day = parse_when(e["start"])
            rem = e.get("reminders", {})
            leads = [] if rem.get("useDefault", True) else [
                int(o["minutes"]) for o in rem.get("overrides", []) if o.get("method") == "popup"]
            out.append({"id": e["id"], "summary": e.get("summary", "(без названия)"),
                        "start": start, "all_day": all_day, "leads": leads,
                        "use_default": rem.get("useDefault", True),
                        "location": e.get("location", ""), "link": e.get("htmlLink", "")})
        return out

    # --- задачи ---
    def tasks(self, show_completed=False) -> list[dict]:
        svc = self._service("tasks", "v1")
        res = svc.tasks().list(tasklist="@default", showCompleted=show_completed,
                               showHidden=False, maxResults=100).execute()
        return [{"id": t["id"], "title": t.get("title", ""), "due": t.get("due", "")[:10],
                 "done": t.get("status") == "completed"} for t in res.get("items", []) if t.get("title")]

    def add_task(self, title, due: dt.date | None = None):
        body = {"title": title}
        if due:
            body["due"] = f"{due.isoformat()}T00:00:00.000Z"
        return self._service("tasks", "v1").tasks().insert(tasklist="@default", body=body).execute()

    def complete_task(self, task_id):
        self._service("tasks", "v1").tasks().patch(
            tasklist="@default", task=task_id, body={"status": "completed"}).execute()

    def delete_task(self, task_id):
        self._service("tasks", "v1").tasks().delete(tasklist="@default", task=task_id).execute()

    # --- диск ---
    def drive(self, folder_id="root") -> list[dict]:
        res = self._service("drive", "v3").files().list(
            q=f"'{folder_id}' in parents and trashed=false", pageSize=100,
            orderBy="folder,name", fields="files(id,name,mimeType,webViewLink,modifiedTime)").execute()
        return [{"id": f["id"], "name": f["name"], "folder": f["mimeType"] == FOLDER_MIME,
                 "link": f.get("webViewLink", ""), "modified": f.get("modifiedTime", "")[:10]}
                for f in res.get("files", [])]

    # --- почта ---
    def unread_mail(self, limit=20) -> list[dict]:
        svc = self._service("gmail", "v1")
        ids = svc.users().messages().list(userId="me", q="is:unread in:inbox", maxResults=limit
                                          ).execute().get("messages", [])
        out = []
        for m in ids:
            msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                             metadataHeaders=["From", "Subject"]).execute()
            h = {x["name"]: x["value"] for x in msg["payload"].get("headers", [])}
            out.append({"id": m["id"], "from": h.get("From", ""), "subject": h.get("Subject", "(без темы)"),
                        "snippet": msg.get("snippet", "")})
        return out
