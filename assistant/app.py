"""Настольный помощник на весь экран: часы, календарь, задачи, Google Диск, почта.

Запуск:  python -m assistant.app      F11 — полный экран, Esc — выйти из него.
"""
from __future__ import annotations

import calendar
import datetime as dt
import queue
import shutil
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

from .google_api import Google
from .notifier import notify
from .watcher import due_reminders, new_mail, reminder_text

CONFIG_PATH = "assistant_config.yaml"
DEFAULTS = {
    "credentials_file": "credentials.json",
    "token_file": "token.json",
    "calendar_poll_seconds": 60,
    "mail_poll_seconds": 120,
    "default_lead_minutes": 10,
    "events_days_ahead": 31,
    "always_on_top": False,
    "notify_calendar": True,
    "notify_mail": True,
    "drive_folders": [],  # [{name: "Договоры", id: "<id папки>"}]
}
MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
          "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

BG, CARD, ACCENT, INK, MUTED, LINE = "#0a0a0f", "#14161d", "#3b82f6", "#e8eefc", "#8793ab", "#232838"
HEADS = {"cal": "#1d4ed8", "task": "#2563eb", "drive": "#3b82f6", "mail": "#60a5fa"}
F = "Segoe UI"


def load_config(path=CONFIG_PATH) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        cfg.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    Path(path).write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def apply_theme(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=BG)
    st.configure(".", background=BG, foreground=INK, font=(F, 12))
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=CARD)
    st.configure("TLabel", background=BG, foreground=INK)
    st.configure("Card.TLabel", background=CARD, foreground=INK)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("TButton", background=ACCENT, foreground="white", borderwidth=0,
                 padding=(14, 8), font=(F, 12, "bold"))
    st.map("TButton", background=[("active", "#2563eb")])
    st.configure("Ghost.TButton", background="#1e2a4a")
    st.map("Ghost.TButton", background=[("active", "#27386b")])
    st.configure("TEntry", fieldbackground="#1a1d27", foreground=INK, insertcolor=INK, padding=7)
    st.configure("TCombobox", fieldbackground="#1a1d27", foreground=INK, padding=6)
    st.configure("TCheckbutton", background=BG, foreground=INK)
    st.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK,
                 rowheight=36, borderwidth=0, font=(F, 12))
    st.configure("Treeview.Heading", background="#1e2a4a", foreground=INK,
                 font=(F, 11, "bold"), relief="flat", padding=6)
    st.map("Treeview", background=[("selected", "#1e3a8a")], foreground=[("selected", "white")])


class App(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.g = Google(cfg["credentials_file"], cfg["token_file"])
        self.ui = queue.Queue()
        self.wake = threading.Event()  # «обновить сейчас»
        self.events, self.tasks, self.drive_items = [], [], []
        self.drive_stack = [("Мой диск", "root")]
        self.seen_rem, self.seen_mail, self.mail_first = set(), set(), True
        self.today = dt.date.today()
        self.month = self.today.replace(day=1)
        self.selected_day = None
        self.fullscreen = False

        self.title("Помощник")
        apply_theme(self)
        self.attributes("-topmost", bool(cfg["always_on_top"]))
        self.geometry("1280x800")
        self._maximize()
        self.bind("<F11>", lambda _e: self._toggle_fullscreen())
        self.bind("<Escape>", lambda _e: self._toggle_fullscreen(False))

        self.status = tk.StringVar(value="")
        self._build_header()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(4, 0))
        body.columnconfigure((0, 1), weight=1, uniform="c")
        body.rowconfigure((0, 1), weight=1, uniform="r")
        self._build_calendar(self._card(body, 0, 0, "📅", "Календарь", "cal", "Google Календарь", self.open_gcal))
        self._build_tasks(self._card(body, 0, 1, "✅", "Задачи", "task", "⟳", self.refresh_tasks))
        self._build_drive(self._card(body, 1, 0, "📁", "Google Диск", "drive", "Открыть Диск",
                                     lambda: webbrowser.open("https://drive.google.com/")))
        self._build_mail(self._card(body, 1, 1, "✉️", "Почта", "mail", "Открыть Gmail",
                                    lambda: webbrowser.open("https://mail.google.com/")))
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", anchor="w").pack(
            fill="x", padx=18, pady=6)

        self._tick()
        self.after(200, self._pump)
        self._spawn(self._calendar_loop)
        self._spawn(self._mail_loop)
        self.refresh_all()
        if not self.g.connected():
            self.after(600, self.open_settings)

    # ---------- окно ----------
    def _maximize(self):
        try:
            self.state("zoomed")  # Windows
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)  # Linux
            except tk.TclError:
                pass

    def _toggle_fullscreen(self, value=None):
        self.fullscreen = (not self.fullscreen) if value is None else value
        self.attributes("-fullscreen", self.fullscreen)

    # ---------- шапка с часами ----------
    def _build_header(self):
        h = ttk.Frame(self)
        h.pack(fill="x", padx=18, pady=(12, 6))
        tk.Label(h, text="✺", font=(F, 40), fg=ACCENT, bg=BG).pack(side="left")
        t = ttk.Frame(h)
        t.pack(side="left", padx=12)
        tk.Label(t, text="МОЙ ПОМОЩНИК", font=("Segoe UI Black", 22, "bold"), fg=INK, bg=BG).pack(anchor="w")
        self.conn_lbl = tk.Label(t, text="", font=(F, 11), fg=MUTED, bg=BG)
        self.conn_lbl.pack(anchor="w")
        btns = ttk.Frame(h)
        btns.pack(side="right")
        ttk.Button(btns, text="⟳  Обновить", style="Ghost.TButton", command=self.refresh_all).pack(side="left", padx=4)
        ttk.Button(btns, text="⛶", style="Ghost.TButton", width=3, command=self._toggle_fullscreen).pack(side="left", padx=4)
        ttk.Button(btns, text="⚙  Настройки", command=self.open_settings).pack(side="left", padx=4)
        c = ttk.Frame(h)
        c.pack(side="right", padx=30)
        self.clock = tk.Label(c, font=("Segoe UI Light", 44), fg=INK, bg=BG)
        self.clock.pack(anchor="e")
        self.date_lbl = tk.Label(c, font=(F, 13), fg=ACCENT, bg=BG)
        self.date_lbl.pack(anchor="e")

    def _tick(self):
        now = dt.datetime.now()
        self.clock.config(text=now.strftime("%H:%M:%S"))
        self.date_lbl.config(text=f"{WEEKDAYS[now.weekday()].capitalize()}, {now.day} {self._month_gen(now.month)} {now.year}")
        if now.date() != self.today:
            self.today = now.date()
            self._draw_month()
        self.after(1000, self._tick)

    @staticmethod
    def _month_gen(m):
        return ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                "сентября", "октября", "ноября", "декабря"][m - 1]

    # ---------- карточки ----------
    def _card(self, parent, r, c, icon, title, key, btn_text, btn_cmd):
        card = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.grid(row=r, column=c, sticky="nsew", padx=7, pady=7)
        head = tk.Frame(card, bg=HEADS[key])
        head.pack(fill="x")
        tk.Label(head, text=icon, font=("Segoe UI Emoji", 30), bg=HEADS[key], fg="white").pack(side="left", padx=(14, 8), pady=6)
        tk.Label(head, text=title.upper(), font=("Segoe UI Black", 17), bg=HEADS[key],
                 fg="#0a0a0f" if key == "mail" else "white").pack(side="left")
        ttk.Button(head, text=btn_text, style="Ghost.TButton", command=btn_cmd).pack(side="right", padx=12, pady=8)
        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        return inner

    def _tree(self, parent, cols, heights=6):
        box = ttk.Frame(parent, style="Card.TFrame")
        box.pack(fill="both", expand=True)
        tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings", height=heights)
        for cid, text, w, stretch in cols:
            tree.heading(cid, text=text)
            tree.column(cid, width=w, stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tree

    # ---------- календарь ----------
    def _build_calendar(self, f):
        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="◀", width=3, style="Ghost.TButton", command=lambda: self._shift_month(-1)).pack(side="left")
        self.month_lbl = ttk.Label(top, style="Card.TLabel", font=(F, 16, "bold"), anchor="center")
        self.month_lbl.pack(side="left", expand=True, fill="x")
        ttk.Button(top, text="Сегодня", style="Ghost.TButton", command=self._go_today).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="▶", width=3, style="Ghost.TButton", command=lambda: self._shift_month(1)).pack(side="right")
        self.grid_frame = tk.Frame(f, bg=CARD)
        self.grid_frame.pack(fill="x", pady=6)
        self.ev_tree = self._tree(f, [("d", "Дата", 70, False), ("t", "Время", 80, False), ("s", "Событие", 300, True)])
        self.ev_tree.bind("<Double-1>", self._open_event)
        self._draw_month()

    def _shift_month(self, d):
        m = self.month.month - 1 + d
        self.month = dt.date(self.month.year + m // 12, m % 12 + 1, 1)
        self._draw_month()

    def _go_today(self):
        self.month = self.today.replace(day=1)
        self.selected_day = self.today
        self._draw_month()
        self._fill_events()

    def _pick_day(self, d):
        self.selected_day = None if self.selected_day == d else d
        self._draw_month()
        self._fill_events()

    def _draw_month(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.month_lbl.config(text=f"{MONTHS[self.month.month - 1]} {self.month.year}")
        busy = {e["start"].astimezone().date() for e in self.events}
        for i in range(7):
            self.grid_frame.columnconfigure(i, weight=1, uniform="d")
            tk.Label(self.grid_frame, text=["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][i], bg=CARD,
                     fg=MUTED, font=(F, 10, "bold")).grid(row=0, column=i)
        for r, week in enumerate(calendar.monthcalendar(self.month.year, self.month.month), 1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = dt.date(self.month.year, self.month.month, day)
                is_today, sel = d == self.today, d == self.selected_day
                bg = ACCENT if is_today else ("#1e3a8a" if sel else "#1a1d27")
                tk.Button(self.grid_frame, text=f"{day}{'•' if d in busy else ''}", bd=0, relief="flat",
                          bg=bg, fg="white" if is_today or sel else (ACCENT if d in busy else INK),
                          activebackground="#2563eb", activeforeground="white", cursor="hand2",
                          font=(F, 12, "bold" if d in busy or is_today else "normal"),
                          command=lambda d=d: self._pick_day(d)).grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

    def _set_events(self, evs):
        self.events = evs
        self._draw_month()
        self._fill_events()
        self.status.set(f"Обновлено {dt.datetime.now():%H:%M} · событий: {len(evs)}")

    def _fill_events(self):
        self.ev_tree.delete(*self.ev_tree.get_children())
        for e in self.events:
            s = e["start"].astimezone()
            if self.selected_day and s.date() != self.selected_day:
                continue
            self.ev_tree.insert("", "end", iid=e["id"], values=(
                s.strftime("%d.%m"), "весь день" if e["all_day"] else s.strftime("%H:%M"), e["summary"]))

    def _open_event(self, _e):
        sel = self.ev_tree.selection()
        for e in self.events:
            if sel and e["id"] == sel[0] and e["link"]:
                webbrowser.open(e["link"])

    def open_gcal(self):
        webbrowser.open("https://calendar.google.com/")

    # ---------- задачи ----------
    def _build_tasks(self, f):
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 6))
        self.task_var, self.due_var = tk.StringVar(), tk.StringVar()
        e = ttk.Entry(row, textvariable=self.task_var, font=(F, 12))
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.add_task())
        ttk.Entry(row, textvariable=self.due_var, width=12, font=(F, 12)).pack(side="left", padx=6)
        ttk.Button(row, text="＋ Добавить", command=self.add_task).pack(side="left")
        ttk.Label(f, text="Срок: ГГГГ-ММ-ДД (необязательно). Двойной клик — выполнено.",
                  style="Muted.TLabel", background=CARD).pack(anchor="w")
        self.task_tree = self._tree(f, [("t", "Задача", 380, True), ("d", "Срок", 100, False)])
        self.task_tree.bind("<Double-1>", lambda _e: self.complete_task())
        self.task_tree.bind("<Delete>", lambda _e: self.delete_task())
        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="✓ Выполнено", command=self.complete_task).pack(side="left")
        ttk.Button(bar, text="🗑 Удалить", style="Ghost.TButton", command=self.delete_task).pack(side="left", padx=6)

    def refresh_tasks(self):
        self._bg(self.g.tasks, self._set_tasks)

    def _set_tasks(self, tasks):
        self.tasks = tasks
        self.task_tree.delete(*self.task_tree.get_children())
        for t in tasks:
            self.task_tree.insert("", "end", iid=t["id"], values=("☐  " + t["title"], t["due"]))

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
    def _build_drive(self, f):
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 6))
        self.pin = ttk.Combobox(row, state="readonly", font=(F, 12))
        self.pin.pack(side="left", fill="x", expand=True)
        self.pin.bind("<<ComboboxSelected>>", lambda _e: self._pinned())
        ttk.Button(row, text="⬆ Вверх", style="Ghost.TButton", command=self.drive_up).pack(side="left", padx=6)
        self._refresh_pins()
        self.path_lbl = ttk.Label(f, style="Muted.TLabel", background=CARD)
        self.path_lbl.pack(anchor="w")
        self.drive_tree = self._tree(f, [("n", "Имя", 380, True), ("m", "Изменён", 100, False)])
        self.drive_tree.bind("<Double-1>", lambda _e: self.drive_open())

    def _refresh_pins(self):
        self.pin["values"] = ["Мой диск"] + [x["name"] for x in self.cfg["drive_folders"]]
        self.pin.current(0)

    def _pinned(self):
        i = self.pin.current()
        self.drive_stack = [("Мой диск", "root")] if i == 0 else [
            (self.cfg["drive_folders"][i - 1]["name"], self.cfg["drive_folders"][i - 1]["id"])]
        self._load_drive()

    def _load_drive(self):
        self.path_lbl.config(text=" / ".join(n for n, _ in self.drive_stack))
        fid = self.drive_stack[-1][1]
        self._bg(lambda: self.g.drive(fid), self._set_drive)

    def _set_drive(self, items):
        self.drive_items = items
        self.drive_tree.delete(*self.drive_tree.get_children())
        for it in items:
            self.drive_tree.insert("", "end", iid=it["id"], values=(
                ("📁  " if it["folder"] else "📄  ") + it["name"], it["modified"]))

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
    def _build_mail(self, f):
        self.mail_count = ttk.Label(f, text="", style="Card.TLabel", font=(F, 14, "bold"))
        self.mail_count.pack(anchor="w", pady=(0, 6))
        self.mail_tree = self._tree(f, [("f", "От", 200, False), ("s", "Тема", 340, True)])
        self.mail_tree.bind("<Double-1>", lambda _e: webbrowser.open("https://mail.google.com/"))

    def _set_mail(self, msgs):
        self.mail_count.config(text=f"Непрочитанных: {len(msgs)}")
        self.mail_tree.delete(*self.mail_tree.get_children())
        for m in msgs:
            self.mail_tree.insert("", "end", iid=m["id"], values=(m["from"].split("<")[0].strip() or m["from"], m["subject"]))

    # ---------- фон ----------
    def _spawn(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _bg(self, fn, then):
        def run():
            try:
                self.ui.put((then, fn(), None))
            except Exception as ex:
                self.ui.put((None, None, ex))
        self._spawn(run)

    def _pump(self):
        try:
            while True:
                cb, res, err = self.ui.get_nowait()
                if err is not None:
                    self.status.set(f"Ошибка: {err}")
                elif cb:
                    cb(res)
        except queue.Empty:
            pass
        self.conn_lbl.config(text="● Google подключён" if self.g.connected() else "○ Google не подключён — нажмите «Настройки»",
                             fg="#60a5fa" if self.g.connected() else MUTED)
        self.after(200, self._pump)

    def refresh_all(self):
        self.wake.set()
        if self.g.connected():
            self.refresh_tasks()
            self._load_drive()

    def _wait(self, seconds):
        self.wake.wait(seconds)
        self.wake.clear()

    def _calendar_loop(self):
        while True:
            if self.g.connected():
                try:
                    evs = self.g.events(days=int(self.cfg["events_days_ahead"]))
                    due = due_reminders(evs, dt.datetime.now(dt.timezone.utc),
                                        int(self.cfg["default_lead_minutes"]), self.seen_rem)
                    if self.cfg["notify_calendar"]:
                        for e, left in due:
                            self.ui.put((lambda _r, e=e, left=left: self._alert("Календарь", reminder_text(e, left)), None, None))
                    self.ui.put((self._set_events, evs, None))
                except Exception as ex:
                    self.ui.put((None, None, ex))
            self._wait(int(self.cfg["calendar_poll_seconds"]) if self.g.connected() else 3)

    def _mail_loop(self):
        while True:
            if self.g.connected():
                try:
                    msgs = self.g.unread_mail()
                    fresh = new_mail(msgs, self.seen_mail, self.mail_first)
                    self.mail_first = False
                    if self.cfg["notify_mail"]:
                        for m in fresh:
                            self.ui.put((lambda _r, m=m: self._alert(f"Почта: {m['from']}", m["subject"]), None, None))
                    self.ui.put((self._set_mail, msgs, None))
                except Exception as ex:
                    self.ui.put((None, None, ex))
            threading.Event().wait(int(self.cfg["mail_poll_seconds"]) if self.g.connected() else 3)

    def _alert(self, title, text):
        if not notify(title, text):
            self.bell()
            messagebox.showinfo(title, text)
        self.status.set(f"{dt.datetime.now():%H:%M} — {title}: {text}")

    # ---------- настройки ----------
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.lift()
            return
        w = self._settings = tk.Toplevel(self, bg=BG)
        w.title("Настройки")
        w.geometry("640x760")
        w.transient(self)
        pad = {"padx": 18, "pady": 4}

        def head(t):
            tk.Label(w, text=t, font=("Segoe UI Black", 14), fg=ACCENT, bg=BG).pack(anchor="w", padx=18, pady=(16, 2))

        head("ПОДКЛЮЧЕНИЕ GOOGLE (календарь, задачи, диск, Gmail)")
        state = tk.StringVar()
        ttk.Label(w, textvariable=state, wraplength=590).pack(anchor="w", **pad)

        def refresh_state():
            has_key = Path(self.cfg["credentials_file"]).exists()
            state.set(("● Подключено. " if self.g.connected() else "○ Не подключено. ") +
                      ("Ключ credentials.json найден." if has_key else "Сначала выберите файл credentials.json (инструкция в assistant/README.md)."))

        def pick_key():
            path = filedialog.askopenfilename(parent=w, title="credentials.json", filetypes=[("JSON", "*.json")])
            if path:
                if Path(path).resolve() != Path(self.cfg["credentials_file"]).resolve():
                    shutil.copy(path, self.cfg["credentials_file"])
                refresh_state()

        def do_connect():
            if not Path(self.cfg["credentials_file"]).exists():
                messagebox.showwarning("Google", "Сначала выберите файл credentials.json", parent=w)
                return
            state.set("Открылся браузер — разрешите доступ и вернитесь сюда…")

            def run():
                try:
                    self.g.connect()
                    self.ui.put((lambda _r: (refresh_state(), self.refresh_all(), self.status.set("Google подключён")), None, None))
                except Exception as ex:
                    self.ui.put((None, None, ex))
            self._spawn(run)

        def do_disconnect():
            self.g.disconnect()
            refresh_state()

        row = ttk.Frame(w)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="1. Выбрать credentials.json", style="Ghost.TButton", command=pick_key).pack(side="left")
        ttk.Button(row, text="2. Подключить Google", command=do_connect).pack(side="left", padx=8)
        ttk.Button(row, text="Отключить", style="Ghost.TButton", command=do_disconnect).pack(side="left")
        ttk.Label(w, text="Gmail подключается тем же входом Google — отдельный пароль почты не нужен.",
                  style="Muted.TLabel", wraplength=590).pack(anchor="w", **pad)
        refresh_state()

        head("УВЕДОМЛЕНИЯ")
        v = {k: tk.BooleanVar(value=bool(self.cfg[k])) for k in ("notify_calendar", "notify_mail", "always_on_top")}
        ttk.Checkbutton(w, text="Напоминания о событиях календаря", variable=v["notify_calendar"]).pack(anchor="w", **pad)
        ttk.Checkbutton(w, text="Уведомления о новых письмах", variable=v["notify_mail"]).pack(anchor="w", **pad)
        ttk.Checkbutton(w, text="Окно всегда поверх других", variable=v["always_on_top"]).pack(anchor="w", **pad)
        n = {k: tk.StringVar(value=str(self.cfg[k])) for k in ("default_lead_minutes", "calendar_poll_seconds", "mail_poll_seconds")}
        for key, label in (("default_lead_minutes", "Предупреждать за (минут)"),
                           ("calendar_poll_seconds", "Проверять календарь каждые (сек)"),
                           ("mail_poll_seconds", "Проверять почту каждые (сек)")):
            r = ttk.Frame(w)
            r.pack(fill="x", **pad)
            ttk.Label(r, text=label, width=34).pack(side="left")
            ttk.Entry(r, textvariable=n[key], width=8).pack(side="left")

        head("ПАПКИ ДИСКА ДЛЯ БЫСТРОГО ДОСТУПА")
        ttk.Label(w, text="По строке: Название|id папки (id — из адреса папки в браузере)", style="Muted.TLabel").pack(anchor="w", **pad)
        folders = tk.Text(w, height=4, bg="#1a1d27", fg=INK, insertbackground=INK, relief="flat", font=(F, 11))
        folders.pack(fill="x", **pad)
        folders.insert("1.0", "\n".join(f"{x['name']}|{x['id']}" for x in self.cfg["drive_folders"]))

        def save():
            try:
                for k, var in n.items():
                    self.cfg[k] = max(1, int(var.get()))
            except ValueError:
                messagebox.showwarning("Настройки", "Числа должны быть целыми", parent=w)
                return
            for k, var in v.items():
                self.cfg[k] = bool(var.get())
            self.cfg["drive_folders"] = [
                {"name": a.strip(), "id": b.strip()} for a, _, b in
                (ln.partition("|") for ln in folders.get("1.0", "end").splitlines()) if a.strip() and b.strip()]
            save_config(self.cfg)
            self.attributes("-topmost", self.cfg["always_on_top"])
            self._refresh_pins()
            self.wake.set()
            w.destroy()

        bar = ttk.Frame(w)
        bar.pack(fill="x", padx=18, pady=18)
        ttk.Button(bar, text="Сохранить", command=save).pack(side="left")
        ttk.Button(bar, text="🔔 Проверить уведомление", style="Ghost.TButton",
                   command=lambda: notify("Помощник", "Уведомления работают")).pack(side="left", padx=8)
        ttk.Button(bar, text="Закрыть", style="Ghost.TButton", command=w.destroy).pack(side="right")


def main():
    App(load_config()).mainloop()


if __name__ == "__main__":
    main()
