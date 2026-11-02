"""CustomClassic Chat's chat log: every message read, one file a day in the "chat log" folder,
kept for good. This window shows a day at a time, or what a search finds in all of them."""

from __future__ import annotations

import os
import time
import tkinter as tk

import customclassic_chat as mc
from settings_ui import BG, BORDER, INK, SIDE, SOFT, UI, button, entry, label

MAX_FOUND = 2000  # search results shown at most, newest first


def day_name(path) -> str:
    """'Today', 'Yesterday' or 'Mon 31 Oct 2026' for a day file."""
    day = time.strptime(path.stem, "%Y-%m-%d")
    today = time.strftime("%Y-%m-%d")
    if path.stem == today:
        return "Today"
    if path.stem == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)):
        return "Yesterday"
    return time.strftime("%a %d %b %Y", day)


def search(folder, words: str, limit: int = MAX_FOUND) -> list[dict]:
    """Messages holding all the words (any case, in the name or the text), newest first."""
    want = words.lower().split()
    found = []
    for path in mc.log_days(folder):
        for m in reversed(mc.read_jsonl(path)):
            text = f"{m.get('name', '')} {m.get('body', '')}".lower()
            if all(w in text for w in want):
                found.append(m)
                if len(found) >= limit:
                    return found
    return found


class LogWindow:
    def __init__(self, app):
        self.app, self.folder = app, mc.LOG_DIR
        top = self.top = tk.Toplevel(app.root)
        top.title("CustomClassic Chat log")
        top.configure(bg=BG)
        top.geometry("900x560")
        top.attributes("-topmost", True)
        try:
            top.iconbitmap(str(app.icon_path()))
        except (tk.TclError, AttributeError):
            pass
        bar = tk.Frame(top, bg=BG, padx=10, pady=8)
        bar.pack(fill="x")
        label(bar, "Search", bg=BG).pack(side="left")
        self.words = tk.StringVar()
        box = entry(bar, self.words, 32)
        box.pack(side="left", padx=8)
        box.bind("<Return>", lambda e: self.find())
        button(bar, "Find", self.find, primary=True).pack(side="left")
        button(bar, "Open the folder", self.open_folder).pack(side="right")
        self.note = label(bar, "", soft=True, bg=BG)
        self.note.pack(side="left", padx=10)
        body = tk.Frame(top, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.days = tk.Listbox(body, bg=SIDE, fg=INK, selectbackground=mc.TAB_ON, selectforeground=INK,
                               relief="flat", highlightthickness=1, highlightbackground=BORDER, width=18,
                               font=(UI, 10), activestyle="none", exportselection=False)
        self.days.pack(side="left", fill="y")
        self.days.bind("<<ListboxSelect>>", lambda e: self.show_day())
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.text = tk.Text(body, bg=app.opts["panel_bg"] or mc.PANEL, fg=INK, wrap="word", relief="flat", padx=8,
                            pady=6, yscrollcommand=scroll.set, highlightthickness=0, font=app.font)
        self.text.pack(side="left", fill="both", expand=True, padx=(8, 0))
        scroll.configure(command=self.text.yview)
        self.paths = mc.log_days(self.folder)
        for p in self.paths:
            self.days.insert("end", day_name(p))
        if self.paths:
            self.days.selection_set(0)
            self.show_day()
        else:
            self.fill([], "Nothing saved yet: the chat is saved here as it's read.")
        box.focus_set()

    def fill(self, messages: list[dict], empty: str = "", dated: bool = False) -> None:
        t, opts = self.text, self.app.opts
        t.configure(state="normal")
        t.delete("1.0", "end")
        for m in messages:
            kind = m.get("kind") if m.get("kind") in mc.COLORS else "other"
            fg = opts["colors"].get(kind) or m.get("fg") or mc.COLORS[kind]
            tag = f"{fg}|{m.get('bg') or ''}"
            t.tag_configure(tag, foreground=fg, background=m.get("bg") or "")
            day = time.strftime("%d %b ", time.localtime(m["at"])) if dated else ""
            t.insert("end", day + mc.line_text(dict(m, kind=kind), "seconds") + "\n", tag)
        if not messages and empty:
            t.insert("end", empty, mc.SOFT)
            t.tag_configure(mc.SOFT, foreground=SOFT)
        t.configure(state="disabled")

    def show_day(self) -> None:
        picked = self.days.curselection()
        if not picked:
            return
        messages = mc.read_jsonl(self.paths[picked[0]])
        self.fill(messages, "Nothing that day.")
        self.note.configure(text=f"{len(messages)} messages")
        self.text.see("end")

    def find(self) -> None:
        words = self.words.get().strip()
        if not words:
            self.show_day()
            return
        found = search(self.folder, words)
        self.days.selection_clear(0, "end")
        self.fill(list(reversed(found)), f"Nothing with “{words}”.", dated=True)
        more = " (the newest)" if len(found) >= MAX_FOUND else ""
        self.note.configure(text=f"{len(found)} found{more}")
        self.text.see("end")

    def open_folder(self) -> None:
        open_folder(self.folder)


def open_folder(folder=mc.LOG_DIR) -> None:
    folder.mkdir(exist_ok=True)
    os.startfile(folder)


def open_window(app) -> None:
    """The chat log window; a second open brings the first to the front."""
    win = getattr(app, "log_window", None)
    if win is not None and win.top.winfo_exists():
        win.top.deiconify()
        win.top.lift()
        return
    app.log_window = LogWindow(app)
