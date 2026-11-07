"""A collection: the problem report plus a minute of the chat, for improving the reading on setups
other than ours. Every 2 s a picture of the chat area (its scrollbar and the frame under it
included) with what was found and read in it and how long that took, two pictures of the whole
game window, the player's note and display settings, and this PC's processor and memory.
Sent with Upload to customclassic.chat (customclassic-server's collect service), or saved on the
desktop. Opened from Settings → Problem report…, the Start menu, or CustomClassicChat.exe --report.

In the zip: meta.json (version, note, display, screen, processor), report.txt (the problem
report), samples.jsonl (one line per picture: box found, line pitch, lines read with their
confidence, messages made, seconds taken), chat-NNN.png, game-NNN.png, settings and logs."""
from __future__ import annotations

import ctypes
import io
import json
import platform
import sys
import threading
import time
import traceback
import zipfile

import customclassic_chat as mc
import reader as core
import updates
from report import Report, desktop

UPLOAD_URL = "https://customclassic.chat/api/collect"
SAMPLES, EVERY_S, MINUTE = 30, 2.0, 60.0   # a picture every 2 s for a minute (fewer on a slow PC)
FIND_EVERY = 5         # the chat searched for in full on every 5th picture; between, its box is kept (as the app does)
MAX_MB = 38            # the upload service takes 40: over this, the whole game pictures are left out


def pc_details() -> dict:
    """The processor, its threads and the memory: why reading is slow on one PC and not another."""
    import os
    import winreg
    out: dict = {"threads": os.cpu_count()}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            out["cpu"] = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except OSError:
        out["cpu"] = platform.processor()

    class Mem(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("x1", ctypes.c_ulonglong), ("x2", ctypes.c_ulonglong),
                    ("x3", ctypes.c_ulonglong), ("x4", ctypes.c_ulonglong), ("x5", ctypes.c_ulonglong)]
    m = Mem()
    m.len = ctypes.sizeof(Mem)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        out["ram_gb"] = round(m.total / 2**30, 1)
    return out


def png(img) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


class Collection(Report):
    def __init__(self, note: str = "", display: str = "", whole: bool = True, step=print, progress=lambda i, n: None):
        super().__init__(step)
        self.note, self.display, self.whole, self.progress = note, display, whole, progress
        self.samples: list[dict] = []
        self.stop = False

    def run(self) -> None:
        super().run()  # the report: this PC, the game's window, a picture, the chat, settings and logs
        self.files.pop("game.png", None)  # (the whole game pictures are game-NNN.png, and only when ticked)
        if getattr(self, "game", None) and getattr(self, "img", None) is not None:
            self.step("Recording the chat for a minute")
            self.say("== A minute of the chat ==")
            try:
                self.record()
            except Exception:
                self.say("FAILED:\n" + traceback.format_exc())

    def record(self) -> None:
        cfg = core.Config.load()
        reader, dedupe, palette = core.Reader(cfg), mc.Dedupe(), (cfg.colors, cfg.backgrounds)
        cap = mc.GameCapture(self.game["hwnd"])
        try:
            start = time.time()
            while cap.latest() is None and time.time() - start < 8:
                time.sleep(0.2)
            start = next_at = time.time()
            self.last = None
            for i in range(SAMPLES):
                if self.stop or time.time() - start > MINUTE:
                    break
                time.sleep(max(0.0, next_at - time.time()))
                next_at = time.time() + EVERY_S
                self.progress(min(SAMPLES, int((time.time() - start) / EVERY_S) + 1), SAMPLES)
                self.samples.append(self.sample(i, cap, reader, dedupe, palette))
            if self.whole and self.samples:  # the whole game window at the start and the end
                self.files[f"game-{len(self.samples) - 1:03d}.png"] = png(self.end_img)
        finally:
            cap.stop()
        took = [s["read_s"] for s in self.samples if "read_s" in s]
        found = sum(1 for s in self.samples if s.get("box"))
        self.say(f"Pictures: {len(self.samples)}, chat found in {found}, "
                 f"messages: {sum(len(s.get('messages', [])) for s in self.samples)}"
                 + (f", {sum(took) / len(took):.2f} s a read" if took else ""))

    def sample(self, i: int, cap, reader, dedupe, palette) -> dict:
        s: dict = {"i": i, "at": round(time.time(), 1)}
        game = mc.game_geometry()
        frame = cap.latest()
        if not game or frame is None:
            s["error"] = "no game window" if not game else "no picture"
            return s
        c = game["client"]
        img = mc.frame_image(frame, game["ox"], game["oy"], game["ox"] + c["width"], game["oy"] + c["height"])
        if img is None:
            s["error"] = "empty picture"
            return s
        s["game"] = f"{c['width']}x{c['height']}"
        self.end_img = img
        if self.whole and i == 0:
            self.files["game-000.png"] = png(img)
        top = int(img.height * 0.35)
        lower = img.crop((0, top, img.width, img.height))
        t = time.perf_counter()
        s["scrollbar_box"] = core.chat_box_by_scrollbar(lower)
        if self.last and i % FIND_EVERY and self.last[2] == lower.size:
            found, s["found_by"] = self.last[:2], "kept"
        else:
            found, s["found_by"] = mc.find_lines(lower, reader), "searched"
            self.last = (*found, lower.size) if found else None
        s["find_s"] = round(time.perf_counter() - t, 3)
        if not found:
            return s
        box, pitch = found
        s.update(box={k: (int(v) if v is not None else None) for k, v in box.items()}, pitch=round(pitch, 1),
                 lower_top=top)
        crop = lower.crop((box["left"], box["top"], box["left"] + box["width"], box["top"] + box["height"]))
        pad = int(pitch)  # the picture kept: the chat with a margin, its scrollbar and the frame under it
        right = box["left"] + box["width"] + (box.get("bar") or int(pitch * 1.3)) + pad
        kept = (max(0, box["left"] - pad), max(0, box["top"] - pad), min(lower.width, right),
                min(lower.height, box["top"] + box["height"] + pad * 2))
        self.files[f"chat-{i:03d}.png"] = png(lower.crop(kept))
        s["kept"] = kept  # where that picture sits in the lower part
        t = time.perf_counter()
        lines = reader.read(crop, chat=True)
        s["read_s"] = round(time.perf_counter() - t, 3)
        s["lines"] = [{"text": ln.text, "conf": round(ln.conf, 3), "top": round(ln.top, 1),
                       "bottom": round(ln.bottom, 1)} for ln in lines]
        s["messages"] = [{"kind": m["kind"], "name": m.get("name"), "body": m["body"]}
                         for m in mc.messages_from(lines, dedupe, time.time(), palette)]
        return s

    def meta(self) -> dict:
        u32 = ctypes.windll.user32
        c = self.game["client"] if getattr(self, "game", None) else None
        return {"version": updates.VERSION, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "note": self.note,
                "display": self.display, "game_window": f"{c['width']}x{c['height']}" if c else None,
                "screen": f"{u32.GetSystemMetrics(0)}x{u32.GetSystemMetrics(1)}",
                "scaling": round(u32.GetDpiForSystem() / 96 * 100),
                "windows": f"{platform.release()} build {sys.getwindowsversion().build}",
                "samples": len(self.samples), "every_s": EVERY_S, **pc_details()}

    def pack(self) -> bytes:
        blob = self.zipped()
        if len(blob) > MAX_MB * 2**20:  # a very big screen: the whole game pictures make it too big to upload
            for name in [n for n in self.files if n.startswith("game")]:
                del self.files[name]
            self.say("(the whole game pictures were left out: too big to upload)")
            blob = self.zipped()
        return blob

    def zipped(self) -> bytes:
        text = "\n".join(self.lines)
        if self.advice:
            text = "What to try:\n" + "\n".join(f"- {a}" for a in self.advice) + "\n\n" + text
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("meta.json", json.dumps(self.meta(), indent=1))
            z.writestr("report.txt", text)
            z.writestr("samples.jsonl", "\n".join(json.dumps(s) for s in self.samples))
            for name, data in self.files.items():
                z.writestr(name, data)
        return out.getvalue()


def upload(blob: bytes, url: str = UPLOAD_URL) -> str:
    """The collection's id on customclassic.chat; raises with the server's reason when refused."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, blob, {"Content-Type": "application/zip",
                                             "User-Agent": f"CustomClassicChat/{updates.VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["id"]
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read()).get("error")
        except Exception:
            reason = None
        raise RuntimeError(reason or f"the server answered {e.code}") from None


def detected_display() -> str:
    u32 = ctypes.windll.user32
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    game = mc.game_geometry()
    if not game:
        return f"Screen {sw}x{sh}"
    c = game["client"]
    full = c["width"] == sw and c["height"] == sh
    return f"Game {c['width']}x{c['height']}{' (fills the screen)' if full else ''}, screen {sw}x{sh}"


def main() -> None:
    """The window: a note and the game's display settings, a minute of recording, then Upload or
    Save on desktop."""
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
    soft, font, field = "#8f9db5", ("Segoe UI", 10), "#1a2336"

    def label(parent, text, fg=mc.INK, size=10, pady=(0, 0)):
        w = tk.Label(parent, text=text, bg=mc.PANEL, fg=fg, font=("Segoe UI", size), anchor="w", justify="left",
                     wraplength=540)
        w.pack(fill="x", pady=pady)
        return w

    def button(parent, text, command, primary=False):
        b = tk.Button(parent, text=text, command=command, bg="#3d6fd1" if primary else "#26314f", fg="white",
                      relief="flat", padx=12, pady=4, font=font, activebackground="#4f80e0", activeforeground="white")
        b.pack(side="left", padx=(0, 8))
        return b

    form = tk.Frame(root, bg=mc.PANEL)
    form.pack(fill="x")
    label(form, "Help make the chat read better on your setup", size=12)
    label(form, "This records the game's chat for one minute: keep the game open with its chat showing, and play "
                "as usual. Nothing is sent until you press Upload.", fg=soft, pady=(4, 10))
    label(form, "What goes wrong? (optional)")
    note = tk.Text(form, height=4, width=64, bg=field, fg=mc.INK, insertbackground=mc.INK, relief="flat",
                   font=font, wrap="word")
    note.pack(fill="x", pady=(2, 10))
    label(form, "The game's display settings (add its resolution, fullscreen or window, and scaling option)")
    display = tk.Entry(form, bg=field, fg=mc.INK, insertbackground=mc.INK, relief="flat", font=font)
    display.insert(0, detected_display())
    display.pack(fill="x", pady=(2, 10), ipady=3)
    whole = tk.BooleanVar(value=True)
    tk.Checkbutton(form, text="Include 2 pictures of the whole game window (needed when the chat isn't found)",
                   variable=whole, bg=mc.PANEL, fg=mc.INK, selectcolor=field, activebackground=mc.PANEL,
                   activeforeground=mc.INK, font=font, anchor="w").pack(fill="x")
    label(form, "It holds pictures of the game's chat (with other players' names and messages), your settings "
                "without your guild login or Discord details, and your PC's details (Windows, screen, processor).",
          fg=soft, size=9, pady=(8, 0))

    status = label(root, "", size=11)
    detail = label(root, "", fg=soft, size=9, pady=(4, 0))
    buttons = tk.Frame(root, bg=mc.PANEL)
    buttons.pack(fill="x", pady=(14, 0))
    state: dict = {}

    def clear_buttons():
        for w in buttons.winfo_children():
            w.destroy()

    def start():
        form.pack_forget()
        clear_buttons()
        col = Collection(note=note.get("1.0", "end").strip(), display=display.get().strip(), whole=whole.get(),
                         step=lambda name: root.after(0, status.configure, {"text": name + "…"}),
                         progress=lambda i, n: root.after(0, detail.configure,
                                                          {"text": f"Picture {i + 1} of {n}: keep playing as usual."}))
        state["col"] = col
        button(buttons, "Stop early", lambda: setattr(col, "stop", True))

        def work():
            try:
                col.run()
                state["blob"] = col.pack()
            except Exception:
                state["error"] = traceback.format_exc()
            state["done"] = True
        threading.Thread(target=work, daemon=True).start()
        root.after(300, finish)

    def finish():
        if not state.get("done"):
            root.after(300, finish)
            return
        clear_buttons()
        if "error" in state:
            status.configure(text="Something went wrong while recording.")
            detail.configure(text=state["error"][-600:])
            button(buttons, "Close", root.destroy)
            return
        col, blob = state["col"], state["blob"]
        took = [s["read_s"] for s in col.samples if "read_s" in s]
        found = sum(1 for s in col.samples if s.get("box"))
        status.configure(text=f"Recorded {len(col.samples)} pictures; the chat was found in {found}.")
        tips = "\n".join(f"• {a}" for a in col.advice)
        detail.configure(text=(tips + "\n\n" if tips else "")
                         + (f"About {sum(took) / len(took):.1f} s a read. " if took else "")
                         + f"Size: {len(blob) / 2**20:.1f} MB. Upload it, or save it on your desktop to look inside first.")
        state["send"] = button(buttons, "Upload", send, primary=True)
        button(buttons, "Save on desktop", save)
        button(buttons, "Close", root.destroy)

    def save():
        path = desktop() / f"CustomClassic Chat collection {time.strftime('%Y-%m-%d %H.%M')}.zip"
        path.write_bytes(state["blob"])
        subprocess.Popen(["explorer", "/select,", str(path)])
        detail.configure(text=f"Saved on your desktop: {path.name}")

    def send():
        state["send"].configure(state="disabled", text="Uploading…")

        def work():
            try:
                state["sent"] = upload(state["blob"])
            except Exception as e:
                state["sent_error"] = str(e) or e.__class__.__name__
            root.after(0, sent)
        threading.Thread(target=work, daemon=True).start()

    def sent():
        if "sent_error" in state:
            state["send"].configure(state="normal", text="Try again")
            detail.configure(text=f"Couldn't upload: {state.pop('sent_error')}. You can save it on your desktop and "
                                  "post it in #bug-reports instead.")
            return
        cid = state["sent"]
        status.configure(text="Uploaded. Thank you!")
        detail.configure(text=f"Its ID is {cid}. Mention it in #bug-reports on the CustomClassic Chat Discord, "
                              "with anything you'd like to add.", fg=mc.INK)
        state["send"].configure(text="Copy the ID", state="normal",
                                command=lambda: (root.clipboard_clear(), root.clipboard_append(cid)))

    button(buttons, "Start (1 minute)", start, primary=True)
    button(buttons, "Close", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
