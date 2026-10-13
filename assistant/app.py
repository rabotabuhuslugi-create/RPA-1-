"""Настольный помощник: календарь, задачи, Google Диск, почта + уведомления.

Запуск:  python -m assistant.app
"""
from __future__ import annotations

import calendar
import datetime as dt
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

import yaml

from .google_api import Google
from .notifier import notify
from .watcher import due_reminders, new_mail, reminder_text

DEFAULTS = {
    "credentials_file": "credentials.json",
    "token_file": "token.json",
    "calendar_poll_seconds": 60,
    "mail_poll_seconds": 120,
    "default_lead_minutes": 10,
    "events_days_ahead": 31,
    "always_on_top": False,
    "drive_folders": [],  # [{name: "Договоры", id: "<id папки>"}]
}
MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
          "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


BG, CARD, ACCENT, INK, MUTED = "#0a0a0f", "#14161d", "#3b82f6", "#e8eefc", "#8793ab"
TAB_COLORS = {"Календарь": "#1d4ed8", "Задачи": "#2563eb", "Диск": "#3b82f6", "Почта": "#60a5fa"}


def apply_theme(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=BG)
    st.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=CARD)
    st.configure("TLabel", background=BG, foreground=INK)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("Title.TLabel", font=("Segoe UI Black", 20, "bold"), foreground=INK)
    st.configure("Accent.TLabel", font=("Segoe UI Black", 20, "bold"), foreground=ACCENT)
    st.configure("Month.TLabel", font=("Segoe UI", 13, "bold"), background=CARD)
    st.configure("TButton", background=ACCENT, foreground="white", borderwidth=0,
                 padding=(12, 6), font=("Segoe UI", 10, "bold"))
    st.map("TButton", background=[("active", "#2563eb")])
    st.configure("TEntry", fieldbackground=CARD, foreground=INK, insertcolor=INK, padding=5)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    st.configure("TNotebook.Tab", background="#1a1d27", foreground=INK, padding=(18, 8),
                 font=("Segoe UI", 10, "bold"), borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
    st.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=28, borderwidth=0)
    st.configure("Treeview.Heading", background="#1e2a4a", foreground=INK,
                 font=("Segoe UI", 10, "bold"), relief="flat", padding=5)
    st.map("Treeview", background=[("selected", "#1e3a8a")], foreground=[("selected", "white")])


def load_config(path="assistant_config.yaml") -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        cfg.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return cfg


class App(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.g = Google(cfg["credentials_file"], cfg["token_file"])
        self.ui = queue.Queue()  # результаты фоновых потоков -> UI
        self.events, self.tasks, self.drive_stack = [], [], [("Мой диск", "root")]
        self.drive_items = []
        self.seen_rem, self.seen_mail, self.mail_first = set(), set(), True
        self.month = dt.date.today().replace(day=1)

        self.title("Помощник")
        self.geometry("600x720")
        apply_theme(self)
        self.attributes("-topmost", bool(cfg["always_on_top"]))
        self.status = tk.StringVar(value="Подключение к Google…")
        head = ttk.Frame(self)
        head.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(head, text="✺", font=("Segoe UI", 30), fg=ACCENT, bg=BG).pack(side="left")
        box = ttk.Frame(head)
        box.pack(side="left", padx=10)
        ttk.Label(box, text="МОЙ ПОМОЩНИК", style="Title.TLabel").pack(anchor="w")
        ttk.Label(box, text="Календарь · Задачи · Диск · Почта", style="Muted.TLabel").pack(anchor="w")
        self.today_lbl = ttk.Label(head, text=dt.date.today().strftime("%d.%m.%Y"), style="Accent.TLabel")
        self.today_lbl.pack(side="right")
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=12)
        self._build_calendar(tabs)
        self._build_tasks(tabs)
        self._build_drive(tabs)
        self._build_mail(tabs)
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", anchor="w").pack(fill="x", padx=16, pady=6)

        self.after(200, self._pump)
        self._spawn(self._calendar_loop)
        self._spawn(self._mail_loop)
        self.refresh_tasks()
        self.open_drive_root()

    # ---------- вкладки ----------
    def _build_calendar(self, tabs):
        f = ttk.Frame(tabs)
        tabs.add(f, text="Календарь")
        head = ttk.Frame(f)
        head.pack(fill="x", pady=6, padx=6)
        ttk.Button(head, text="◀", width=3, command=lambda: self._shift_month(-1)).pack(side="left")
        self.month_lbl = ttk.Label(head, style="Month.TLabel", anchor="center")
        self.month_lbl.pack(side="left", expand=True, fill="x")
        ttk.Button(head, text="▶", width=3, command=lambda: self._shift_month(1)).pack(side="right")
        self.grid_frame = ttk.Frame(f, style="Card.TFrame")
        self.grid_frame.pack(padx=6, pady=4, ipadx=6, ipady=6)
        self.ev_tree = ttk.Treeview(f, columns=("d", "t", "s"), show="headings", height=12)
        for c, t, w in (("d", "Дата", 80), ("t", "Время", 55), ("s", "Событие", 350)):
            self.ev_tree.heading(c, text=t)
            self.ev_tree.column(c, width=w)
        self.ev_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.ev_tree.bind("<Double-1>", self._open_event)
        self._draw_month()

    def _build_tasks(self, tabs):
        f = ttk.Frame(tabs)
        tabs.add(f, text="Задачи")
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        self.task_var, self.due_var = tk.StringVar(), tk.StringVar()
        e = ttk.Entry(row, textvariable=self.task_var)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.add_task())
        ttk.Entry(row, textvariable=self.due_var, width=11).pack(side="left", padx=4)
        ttk.Button(row, text="Добавить", command=self.add_task).pack(side="left")
        ttk.Label(f, text="Срок: ГГГГ-ММ-ДД (необязательно). Двойной клик — выполнено.").pack(anchor="w", padx=6)
        self.task_tree = ttk.Treeview(f, columns=("t", "d"), show="headings")
        self.task_tree.heading("t", text="Задача")
        self.task_tree.heading("d", text="Срок")
        self.task_tree.column("t", width=380)
        self.task_tree.column("d", width=90)
        self.task_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.task_tree.bind("<Double-1>", lambda _e: self.complete_task())
        self.task_tree.bind("<Delete>", lambda _e: self.delete_task())
        ttk.Button(f, text="Обновить", command=self.refresh_tasks).pack(pady=(0, 6))

    def _build_drive(self, tabs):
        f = ttk.Frame(tabs)
        tabs.add(f, text="Диск")
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        names = ["Мой диск"] + [x["name"] for x in self.cfg["drive_folders"]]
        self.pin = ttk.Combobox(row, values=names, state="readonly")
        self.pin.current(0)
        self.pin.pack(side="left", fill="x", expand=True)
        self.pin.bind("<<ComboboxSelected>>", lambda _e: self._pinned())
        ttk.Button(row, text="Вверх", command=self.drive_up).pack(side="left", padx=4)
        self.path_lbl = ttk.Label(f, anchor="w")
        self.path_lbl.pack(fill="x", padx=6)
        self.drive_tree = ttk.Treeview(f, columns=("n", "m"), show="headings")
        self.drive_tree.heading("n", text="Имя")
        self.drive_tree.heading("m", text="Изменён")
        self.drive_tree.column("n", width=400)
        self.drive_tree.column("m", width=90)
        self.drive_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.drive_tree.bind("<Double-1>", lambda _e: self.drive_open())

    def _build_mail(self, tabs):
        f = ttk.Frame(tabs)
        tabs.add(f, text="Почта")
        self.mail_tree = ttk.Treeview(f, columns=("f", "s"), show="headings")
        self.mail_tree.heading("f", text="От")
        self.mail_tree.heading("s", text="Тема")
        self.mail_tree.column("f", width=170)
        self.mail_tree.column("s", width=320)
        self.mail_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.mail_tree.bind("<Double-1>", lambda _e: webbrowser.open("https://mail.google.com/"))

    # ---------- фон ----------
    def _spawn(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _bg(self, fn, then):
        def run():
            try:
                self.ui.put((then, fn(), None))
            except Exception as ex:
                self.ui.put((then, None, ex))
        self._spawn(run)

    def _pump(self):
        try:
            while True:
                cb, res, err = self.ui.get_nowait()
                if err is not None:
                    self.status.set(f"Ошибка: {err}")
                else:
                    cb(res)
        except queue.Empty:
            pass
        self.after(200, self._pump)

    def _calendar_loop(self):
        import time
        while True:
            try:
                evs = self.g.events(days=int(self.cfg["events_days_ahead"]))
                due = due_reminders(evs, dt.datetime.now(dt.timezone.utc),
                                    int(self.cfg["default_lead_minutes"]), self.seen_rem)
                for e, left in due:
                    self.ui.put((lambda _r, e=e, left=left: self._alert("Календарь", reminder_text(e, left)), None, None))
                self.ui.put((self._set_events, evs, None))
            except Exception as ex:
                self.ui.put((None, None, ex))
            time.sleep(int(self.cfg["calendar_poll_seconds"]))

    def _mail_loop(self):
        import time
        while True:
            try:
                msgs = self.g.unread_mail()
                fresh = new_mail(msgs, self.seen_mail, self.mail_first)
                self.mail_first = False
                for m in fresh:
                    self.ui.put((lambda _r, m=m: self._alert(f"Почта: {m['from']}", m["subject"]), None, None))
                self.ui.put((self._set_mail, msgs, None))
            except Exception as ex:
                self.ui.put((None, None, ex))
            time.sleep(int(self.cfg["mail_poll_seconds"]))

    def _alert(self, title, text):
        if not notify(title, text):
            self.bell()
            messagebox.showinfo(title, text)
        self.status.set(f"{dt.datetime.now():%H:%M} — {title}: {text}")

    # ---------- календарь ----------
    def _shift_month(self, d):
        m = self.month.month - 1 + d
        self.month = dt.date(self.month.year + m // 12, m % 12 + 1, 1)
        self._draw_month()

    def _draw_month(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.month_lbl.config(text=f"{MONTHS[self.month.month - 1]} {self.month.year}")
        busy = {e["start"].astimezone().date() for e in self.events}
        for i, n in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
            tk.Label(self.grid_frame, text=n, width=5, anchor="center", bg=CARD, fg=MUTED,
                     font=("Segoe UI", 9, "bold")).grid(row=0, column=i)
        today = dt.date.today()
        for r, week in enumerate(calendar.monthcalendar(self.month.year, self.month.month), 1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = dt.date(self.month.year, self.month.month, day)
                txt = f"{day}•" if d in busy else str(day)
                tk.Label(self.grid_frame, text=txt, width=5, height=2, anchor="center",
                         bg=ACCENT if d == today else CARD,
                         fg="white" if d == today else (ACCENT if d in busy else INK),
                         font=("Segoe UI", 10, "bold" if d in busy or d == today else "normal")
                         ).grid(row=r, column=c, padx=1, pady=1)

    def _set_events(self, evs):
        self.events = evs
        self._draw_month()
        self.ev_tree.delete(*self.ev_tree.get_children())
        for e in evs:
            s = e["start"].astimezone()
            self.ev_tree.insert("", "end", iid=e["id"], values=(
                s.strftime("%d.%m"), "весь день" if e["all_day"] else s.strftime("%H:%M"), e["summary"]))
        self.status.set(f"Обновлено {dt.datetime.now():%H:%M}: событий {len(evs)}")

    def _open_event(self, _e):
        sel = self.ev_tree.selection()
        for e in self.events:
            if sel and e["id"] == sel[0] and e["link"]:
                webbrowser.open(e["link"])

    # ---------- задачи ----------
    def refresh_tasks(self):
        self._bg(self.g.tasks, self._set_tasks)

    def _set_tasks(self, tasks):
        self.tasks = tasks
        self.task_tree.delete(*self.task_tree.get_children())
        for t in tasks:
            self.task_tree.insert("", "end", iid=t["id"], values=(t["title"], t["due"]))

    def add_task(self):
        title = self.task_var.get().strip()
        if not title:
            return
        due = None
        if self.due_var.get().strip():
            try:
                due = dt.date.fromisoformat(self.due_var.get().strip())
            except ValueError:
                messagebox.showwarning("Срок", "Формат срока: ГГГГ-ММ-ДД")
                return
        self.task_var.set("")
        self.due_var.set("")
        self._bg(lambda: self.g.add_task(title, due), lambda _r: self.refresh_tasks())

    def complete_task(self):
        sel = self.task_tree.selection()
        if sel:
            self._bg(lambda: self.g.complete_task(sel[0]), lambda _r: self.refresh_tasks())

    def delete_task(self):
        sel = self.task_tree.selection()
        if sel and messagebox.askyesno("Удалить", "Удалить задачу?"):
            self._bg(lambda: self.g.delete_task(sel[0]), lambda _r: self.refresh_tasks())

    # ---------- диск ----------
    def open_drive_root(self):
        self._load_drive()

    def _pinned(self):
        i = self.pin.current()
        self.drive_stack = [("Мой диск", "root")] if i == 0 else [
            (self.cfg["drive_folders"][i - 1]["name"], self.cfg["drive_folders"][i - 1]["id"])]
        self._load_drive()

    def _load_drive(self):
        fid = self.drive_stack[-1][1]
        self.path_lbl.config(text=" / ".join(n for n, _ in self.drive_stack))
        self._bg(lambda: self.g.drive(fid), self._set_drive)

    def _set_drive(self, items):
        self.drive_items = items
        self.drive_tree.delete(*self.drive_tree.get_children())
        for it in items:
            self.drive_tree.insert("", "end", iid=it["id"], values=(
                ("📁 " if it["folder"] else "📄 ") + it["name"], it["modified"]))

    def drive_open(self):
        sel = self.drive_tree.selection()
        for it in self.drive_items:
            if sel and it["id"] == sel[0]:
                if it["folder"]:
                    self.drive_stack.append((it["name"], it["id"]))
                    self._load_drive()
                elif it["link"]:
                    webbrowser.open(it["link"])

    def drive_up(self):
        if len(self.drive_stack) > 1:
            self.drive_stack.pop()
            self._load_drive()

    # ---------- почта ----------
    def _set_mail(self, msgs):
        self.mail_tree.delete(*self.mail_tree.get_children())
        for m in msgs:
            self.mail_tree.insert("", "end", iid=m["id"], values=(m["from"], m["subject"]))


def main():
    App(load_config()).mainloop()


if __name__ == "__main__":
    main()
