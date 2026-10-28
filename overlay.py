"""Click-through, always-on-top windows on top of the game (deal alerts, CustomClassic Chat).

A borderless Tk window whose KEY_COLOR pixels are see-through, with WS_EX_TRANSPARENT so
every click lands on the window below, re-raised every 2 s because borderless games push
themselves above other topmost windows. Global hotkeys arrive on a queue as
("hotkey", id). In edit mode the window takes clicks, shows a frame and can be dragged.
"""
from __future__ import annotations

import ctypes
import queue
import sys
from ctypes import wintypes

KEY_COLOR = "#010203"  # painted pixels of this colour are see-through
EDIT_BG = "#20242c"

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00080000, 0x00000020, 0x00000080
WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x08000000, 0x00000008
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY = 0x0312
if user32:
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
GWLP_HWNDPARENT = -8  # a top-level window's owner
CEILING = None  # a window (the settings) every Overlay stays under while it's open, rather than on top of it
HOLD = False  # a menu is open: no Overlay re-raises itself over it until it closes
FRONT: set = set()  # Overlays kept in front of the others (adjust mode's banner)


def set_ceiling(window) -> None:
    """Keep every Overlay under this Tk window (None: on top of everything again)."""
    global CEILING
    CEILING = user32.GetAncestor(window.winfo_id(), 2) if window is not None else None


def hotkey_thread(events: queue.Queue, keys: dict[int, int]) -> None:
    """Ctrl+Alt+<key> for each {id: virtual key}; runs a message loop, so start it on a thread."""
    for hk_id, vk in keys.items():
        if not user32.RegisterHotKey(None, hk_id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
            events.put(("status", f"Ctrl+Alt+F{vk - 0x6F} is taken by another app"))
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            events.put(("hotkey", msg.wParam))


def single_instance(name: str) -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, name)
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


class Overlay:
    """The window itself: a canvas to draw on, click-through until edit mode (or never, with
    click_through=False: it then takes clicks but still never takes the keyboard from the game).
    Pass master to make a second window of the same app."""

    def __init__(self, title: str, x: int | None, y: int | None, width: int, height: int,
                 master=None, click_through: bool = True):
        import tkinter as tk
        self.root = tk.Toplevel(master) if master is not None else tk.Tk()
        self.root.title(title)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY_COLOR)
        self.root.attributes("-transparentcolor", KEY_COLOR)
        self.width, self.height = width, height
        x = x if x is not None else self.root.winfo_screenwidth() - width - 24
        y = y if y is not None else 120
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.canvas = tk.Canvas(self.root, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.edit = self.hidden = self.typing = False
        self.through = click_through
        self.below = None  # another Overlay this one stays right behind (a backdrop), instead of on top
        self.behind: list = []  # Overlays that stay right behind this one: put back each time it's raised
        self._grab = None
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
        self.click_through(click_through)
        self.root.after(2000, self.keep_on_top)

    def place(self, x: float, y: float, width: float, height: float) -> None:
        x, y, width, height = (int(round(v)) for v in (x, y, width, height))  # Tk takes whole pixels only
        r = wintypes.RECT()  # where Windows really has it (Tk's own idea can lag behind a new window)
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        if (x, y, width, height) != (r.left, r.top, r.right - r.left, r.bottom - r.top) or                 (width, height) != (self.width, self.height):
            self.width, self.height = width, height
            self.root.geometry(f"{width}x{height}+{x}+{y}")

    def set_alpha(self, alpha: float) -> None:
        self.root.attributes("-alpha", alpha)

    def click_through(self, on: bool) -> None:
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        if self.typing:  # shown again or restyled while typing in it: it keeps the keyboard
            style &= ~WS_EX_NOACTIVATE & ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        self.keep_on_top(again=False)

    def take_keyboard(self) -> None:
        """Let this window have the keyboard for a moment (typing in it): it normally never takes
        it, so the game keeps it. give_back() hands it to whichever window had it before."""
        before = user32.GetForegroundWindow()
        if before != self.hwnd:  # clicked again while typing: still the game's to go back to
            self._before = before
        self.typing = True
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE & ~WS_EX_TRANSPARENT)
        user32.SetForegroundWindow(self.hwnd)  # allowed: the click that started this came to us

    def own_by(self, owner: "Overlay") -> None:
        """Make owner this window's owner: Windows then always keeps this one in front of it."""
        user32.SetWindowLongPtrW(self.hwnd, GWLP_HWNDPARENT, owner.hwnd)

    def has_keyboard(self) -> bool:
        return user32.GetForegroundWindow() == self.hwnd

    def give_back(self, refocus: bool = True) -> None:
        """Back to never taking the keyboard; with refocus, the window that had it gets it again
        (not when the user already clicked somewhere else)."""
        self.typing = False
        self.click_through(self.through and not self.edit)
        before = getattr(self, "_before", None)
        if refocus and before and self.has_keyboard():
            user32.SetForegroundWindow(before)
        self._before = None

    def keep_on_top(self, again: bool = True) -> None:
        if not self.root.winfo_exists():  # closed (a pop-up note): stop
            return
        if HOLD:
            if again:
                self.root.after(2000, self.keep_on_top)
            return
        ceiling = CEILING if CEILING and user32.IsWindow(CEILING) else None
        after = self.below.hwnd if self.below else (ceiling or HWND_TOPMOST)
        user32.SetWindowPos(self.hwnd, after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        for o in self.behind:
            if not o.hidden and o.root.winfo_exists():
                o.keep_on_top(again=False)
        for o in list(FRONT):  # (an adjust banner) back in front of whatever was just raised
            if o is not self and not o.hidden and o.root.winfo_exists():
                user32.SetWindowPos(o.hwnd, ceiling or HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        if again:
            self.root.after(2000, self.keep_on_top)

    def toggle_edit(self) -> bool:
        """Edit mode on or off; True when it was just locked (time to save the position)."""
        self.edit = not self.edit
        self.click_through(self.through and not self.edit)
        return not self.edit

    def toggle_hidden(self) -> None:
        self.show(self.hidden)

    def show(self, visible: bool) -> None:
        if visible == (not self.hidden):
            return
        self.hidden = not visible
        if self.hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.update_idletasks()
            self.hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            self.click_through(self.through and not self.edit)

    def rect(self) -> tuple[int, int, int, int]:
        return self.root.winfo_x(), self.root.winfo_y(), self.width, self.height

    def clear(self, frame_text: str) -> None:
        """Wipe the canvas; in edit mode draw the frame and a hint along the bottom."""
        c = self.canvas
        c.delete("all")
        c.configure(bg=EDIT_BG if self.edit else KEY_COLOR)
        if self.edit:
            c.create_rectangle(1, 1, self.width - 2, self.height - 2, outline="#9db1d3", dash=(4, 3))
            c.create_text(self.width // 2, self.height - 14, fill="#b0bfd9", font=("Verdana", 8), text=frame_text)

    def _press(self, e) -> None:
        if self.edit:
            self._grab = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e) -> None:
        if self.edit and self._grab:
            self.root.geometry(f"+{e.x_root - self._grab[0]}+{e.y_root - self._grab[1]}")
