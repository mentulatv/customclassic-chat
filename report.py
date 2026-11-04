"""A problem report: what CustomClassic Chat sees of the game, step by step, in one zip on the
desktop for a player to send when it doesn't read their chat. From Settings → Problem report…,
the Start menu's "CustomClassic Chat problem report", or:

    CustomClassicChat.exe --report

It looks the way the app does (window titles, a picture of the game's window, text recognition
on it) and never opens the game's process. In the zip: report.txt (what was found, and what to
try), a picture of the game window, the settings without the guild login or Discord details,
and the app's error logs."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io
import json
import platform
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path

import customclassic_chat as mc
import reader as core
import updates

SECRET = {"relay_admin", "relay_cfg", "guild_login", "relay_code", "relay_reader"}  # logins, webhooks, bot tokens


def desktop() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(0, 0x10, 0, 0, buf) == 0:  # CSIDL_DESKTOPDIRECTORY
        return Path(buf.value)
    return Path.home() / "Desktop"


def maple_windows() -> list[dict]:
    """Every top-level window with "maple" in its title: is the game's the one the app looks for?"""
    u32 = ctypes.windll.user32
    found = []
    title = ctypes.create_unicode_buffer(128)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        u32.GetWindowTextW(hwnd, title, 128)
        if "maple" in title.value.lower():
            r = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(r))
            found.append({"title": title.value, "visible": bool(u32.IsWindowVisible(hwnd)),
                          "minimised": bool(u32.IsIconic(hwnd)), "client": f"{r.right}x{r.bottom}"})
        return True
    u32.EnumWindows(each, 0)
    return found


class Report:
    def __init__(self, step=print):
        self.step = step  # each step's name, as it starts (the window shows it)
        self.lines: list[str] = []
        self.files: dict[str, bytes] = {}
        self.advice: list[str] = []

    def say(self, text: str = "") -> None:
        self.lines.append(text)

    def run(self) -> None:
        for name, part in (("About this PC", self.about), ("Looking for the game's window", self.window),
                           ("Taking a picture of the game", self.picture), ("Finding the chat", self.chat),
                           ("Adding the settings and logs", self.logs)):
            self.step(name)
            self.say(f"== {name} ==")
            try:
                if part() is False:
                    break  # nothing after it can work
            except Exception:
                self.say("FAILED:\n" + traceback.format_exc())
            self.say()

    def about(self) -> None:
        u32 = ctypes.windll.user32
        self.say(f"CustomClassic Chat {updates.VERSION} ({'installed .exe' if getattr(sys, 'frozen', False) else 'from source'})")
        self.say(f"Folder: {mc.HERE}")
        try:
            probe = mc.HERE / "report.tmp"
            probe.write_text("x")
            probe.unlink()
            self.say("Folder writable: yes")
        except OSError as e:
            self.say(f"Folder writable: NO ({e})")
            self.advice.append("The app can't save in its folder: install it with the installer, or unzip it somewhere "
                               "of your own (Documents, Desktop) instead of Program Files.")
        self.say(f"Windows: {platform.platform()} (build {sys.getwindowsversion().build})")
        self.say(f"Run as administrator: {'yes' if ctypes.windll.shell32.IsUserAnAdmin() else 'no'}")
        self.say(f"Screens: {u32.GetSystemMetrics(80)}, all together {u32.GetSystemMetrics(78)}x{u32.GetSystemMetrics(79)}, "
                 f"scaling {round(u32.GetDpiForSystem() / 96 * 100)}%")

    def window(self):
        windows = maple_windows()
        for w in windows:
            self.say(f"Window {w['title']!r}: {w['client']}, {'visible' if w['visible'] else 'hidden'}"
                     f"{', minimised' if w['minimised'] else ''}")
        self.game = mc.game_geometry()
        if not self.game:
            self.say("The game's window: NOT FOUND (the app looks for a visible window titled exactly "
                     f"{core.GAME_TITLE!r}, not minimised)")
            self.advice.append("Start the game (windowed or borderless), and don't minimise it.")
            return False
        self.say(f"The game's window: found, {self.game['client']['width']}x{self.game['client']['height']} "
                 f"at {self.game['client']['left']},{self.game['client']['top']}")

    def picture(self):
        cap = mc.GameCapture(self.game["hwnd"])
        frame, start = None, time.time()
        while frame is None and time.time() - start < 8:
            time.sleep(0.2)
            frame = cap.latest()
        cap.stop()
        if frame is None:
            self.say("Picture of the game: NONE in 8 seconds")
            self.advice.append("Windows gave no picture of the game. If the game runs as administrator, run "
                               "CustomClassic Chat as administrator too (right-click it → Run as administrator). "
                               "Fullscreen: switch the game to windowed (Alt+Enter).")
            return False
        c = self.game["client"]
        img = mc.frame_image(frame, self.game["ox"], self.game["oy"], self.game["ox"] + c["width"],
                             self.game["oy"] + c["height"])
        self.frame, self.img = frame, img
        brightness = sum(img.convert("L").resize((64, 36)).getdata()) / (64 * 36)
        self.say(f"Picture of the game: {frame.shape[1]}x{frame.shape[0]}, brightness {brightness:.0f} of 255")
        if brightness < 3:
            self.advice.append("The picture of the game is black: switch the game to windowed or borderless (Alt+Enter), "
                               "not fullscreen.")
        out = io.BytesIO()
        img.save(out, "PNG")
        self.files["game.png"] = out.getvalue()

    def chat(self):
        c = self.game["client"]
        top = int(c["height"] * 0.35)
        lower = self.img.crop((0, top, c["width"], c["height"]))
        reader = core.Reader(core.Config.load())
        stamps = core.chat_box_in(lower, reader)
        bar = core.chat_box_by_scrollbar(lower)
        self.say(f"Chat found by its time stamps: {stamps or 'no (the game shows no time stamps, or none were read)'}")
        self.say(f"Chat found by its scrollbar: {bar or 'no'}")
        found = mc.find_lines(lower, reader)
        if not found:
            self.say("The chat: NOT FOUND")
            self.advice.append("The chat box wasn't found: open the game's chat so it shows at least 3 lines, close "
                               "windows over it (Options, inventory), and keep the scrollbar on its right in sight.")
            return
        box, pitch = found
        self.say(f"The chat: {box}, lines {pitch:.1f} pixels apart (in the picture's lower part, from y={top})")
        crop = lower.crop((box["left"], box["top"], box["left"] + box["width"], box["top"] + box["height"]))
        out = io.BytesIO()
        crop.save(out, "PNG")
        self.files["chat.png"] = out.getvalue()
        lines = reader.read(crop, chat=True)
        self.say(f"Lines read: {len(lines)}")
        for ln in lines:
            self.say(f"   {ln.text}")
        cfg = core.Config.load()
        msgs = mc.messages_from(lines, mc.Dedupe(), time.time(), (cfg.colors, cfg.backgrounds))
        self.say(f"Messages made of them: {len(msgs)}")
        for m in msgs:
            self.say(f"   {m['kind']:>8} {m.get('name') or '':<13} {m['body']}")
        if lines and not msgs:
            self.advice.append("Lines were read but none counted as chat: send this report.")

    def logs(self) -> None:
        try:
            opts = json.loads(mc.SETTINGS_FILE.read_text(encoding="utf-8"))
            self.files["settings.json"] = json.dumps({k: "(left out)" if k in SECRET else v for k, v in opts.items()},
                                                     indent=1).encode()
            self.say(f"Settings: {len(opts)} (guild login and Discord details left out)")
        except (OSError, ValueError) as e:
            self.say(f"Settings: none yet ({e.__class__.__name__})")
        for name, path, tail in (("errors.log", mc.ERROR_LOG, 40000), ("crash.log", mc.HERE / "crash.log", 40000),
                                 ("config.toml", mc.HERE / "config.toml", 20000),
                                 ("reading.jsonl", mc.READ_STATS, 20000)):
            if path.exists():
                self.files[name] = path.read_bytes()[-tail:]
                self.say(f"{name}: added")

    def save(self, folder: Path) -> Path:
        path = folder / f"CustomClassic Chat report {time.strftime('%Y-%m-%d %H.%M')}.zip"
        text = "\n".join(self.lines)
        if self.advice:
            text = "What to try:\n" + "\n".join(f"- {a}" for a in self.advice) + "\n\n" + text
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.txt", text)
            for name, data in self.files.items():
                z.writestr(name, data)
        return path


def main() -> None:
    """The report in a small window: each step as it goes, then what was found and the file."""
    import subprocess
    import tkinter as tk
    root = tk.Tk()
    root.title("CustomClassic Chat problem report")
    root.configure(bg=mc.PANEL, padx=20, pady=16)
    root.resizable(False, False)
    try:
        root.iconbitmap(mc.save_icon(mc.CACHE_DIR / "customclassic_chat.ico"))
    except Exception:
        pass
    status = tk.Label(root, text="Starting…", bg=mc.PANEL, fg=mc.INK, font=("Segoe UI", 11), anchor="w", justify="left",
                      wraplength=520)
    status.pack(fill="x")
    detail = tk.Label(root, text="Keep the game open, with its chat showing.", bg=mc.PANEL, fg="#8f9db5",
                      font=("Segoe UI", 9), anchor="w", justify="left", wraplength=520)
    detail.pack(fill="x", pady=(6, 0))
    buttons = tk.Frame(root, bg=mc.PANEL)
    buttons.pack(fill="x", pady=(14, 0))
    done: dict = {}

    def work():
        rep = Report(step=lambda name: root.after(0, status.configure, {"text": name + "…"}))
        try:
            rep.run()
            done["path"] = rep.save(desktop())
        except Exception:
            done["error"] = traceback.format_exc()
        done["report"] = rep

    def finish():
        if "report" not in done:
            root.after(200, finish)
            return
        if "error" in done:
            status.configure(text="The report couldn't be saved.")
            detail.configure(text=done["error"][-600:])
        else:
            rep, path = done["report"], done["path"]
            status.configure(text=f"Saved on your desktop: {path.name}")
            tips = "\n".join(f"• {a}" for a in rep.advice) or "Nothing obviously wrong was found."
            detail.configure(text=f"{tips}\n\nSend the file to whoever is helping you. It has a picture of the game "
                                  "window and your settings (without your guild login or Discord details): look "
                                  "inside first if you like.", fg=mc.INK)
            tk.Button(buttons, text="Show the file", command=lambda: subprocess.Popen(["explorer", "/select,", str(path)]),
                      bg="#3d6fd1", fg="white", relief="flat", padx=12, pady=4).pack(side="left")
        tk.Button(buttons, text="Close", command=root.destroy, bg="#26314f", fg="white", relief="flat",
                  padx=12, pady=4).pack(side="left", padx=(8, 0))

    threading.Thread(target=work, daemon=True).start()
    root.after(200, finish)
    root.mainloop()


if __name__ == "__main__":
    main()
