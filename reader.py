"""Reading MapleStory's chat from a picture of the game window.

Text recognition (RapidOCR) finds the chat lines; each line's colours tell the chat types
apart: the text colour for map chat, whispers, buddy and party chat, and the solid band
behind megaphones. Only pixels are looked at: the game's process, memory, files and network
traffic are never touched, and nothing is ever sent to the game.

The colours below were measured on Windia (Classic World). A config.toml next to this file
can change them: [colors] for the text, [backgrounds] for megaphone bands (see README).
"""
from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.toml"

SPEAKER = re.compile(r"^\W{0,4}(?:\[[^\]]{1,25}\]\s*)?[A-Za-z0-9]{3,13}\s*[:;]\s")

# Classic World starts every message with the time, e.g. "[20:08]Fennick CH12 : S> ..."
# OCR may add spaces or garble it: "[20: 12]", "(21:15]", "[21:20j", "16:39j" (no [)
TIMESTAMP = re.compile(r"^\W{0,3}(?:[\[({]\s?\d{1,2}\s?[:.;]\s?\d{2}|\d{1,2}\s?[:.;]\s?\d{2}\s?[\])}jlI|]"
                       r"|\[(?=[^\]]*\d[^\]]*\d)[^\]]{3,8}\])")

MEGAPHONES = {"megaphone", "super_megaphone", "item_megaphone"}

# Whispers: "[21:15]nimbi<< hi" (sent), "Name>> hi" (received).
WHISPER = re.compile(r"^\W{0,3}(?:\[\s?\d{1,2}\s?[:.;]\s?\d{2}\s?\]\s*)?[A-Za-z0-9]{2,13}\s*(?:<<|>>|«|»)")

REREAD_BELOW = 0.8  # lines read with less confidence get their row OCR'd again on its own

FIND_SCALE = 1.5  # zoom for finding the chat box in the lower game window (reading the chat itself uses `scale`)



def starts_message(text: str) -> bool:
    return bool(TIMESTAMP.match(text) or SPEAKER.match(text))


COLORS = {  # the text colour of each chat type; a type may list several
    "item_megaphone": [[9, 69, 76], [70, 39, 6]],
    "super_megaphone": [119, 0, 66],
    "buddy_guild": [255, 153, 0],
    "whisper": [0, 255, 0],
    "notice": [[255, 175, 175], [255, 255, 0]],  # system text: pink, yellow
    "general": [255, 255, 255],  # map chat
}
BACKGROUNDS = {  # the band behind megaphone text
    "item_megaphone": [[83, 208, 190], [224, 173, 1]],  # teal or gold, item name in [brackets]
    "super_megaphone": [206, 155, 177],  # pink, with a channel badge
    "notice": [151, 66, 57],  # red band: gachapon / crate announcements
}


@dataclass
class Config:
    scale: float = 2.5  # text recognition reads enlarged text better; 2.5 suits the chat font at 1080p
    min_confidence: float = 0.55
    colors: dict = field(default_factory=lambda: dict(COLORS))
    backgrounds: dict = field(default_factory=lambda: dict(BACKGROUNDS))
    color_tolerance: int = 45

    @classmethod
    def load(cls, path: Path = CONFIG) -> "Config":
        """The built-in colours, with any from config.toml on top."""
        cfg = cls()
        if path.exists():
            c = tomllib.loads(path.read_text(encoding="utf-8"))
            colors = dict(c.get("colors", {}))
            cfg.color_tolerance = int(colors.pop("tolerance", cfg.color_tolerance))
            cfg.colors.update(colors)
            cfg.backgrounds.update(c.get("backgrounds", {}))
            cfg.scale = float(c.get("scale", cfg.scale))
            cfg.min_confidence = float(c.get("min_confidence", cfg.min_confidence))
        return cfg



@dataclass
class Line:
    text: str
    conf: float
    top: int
    bottom: int
    left: int
    right: int = 0
    color: tuple[int, int, int] | None = None  # the text
    bg: tuple[int, int, int] | None = None  # behind the text
    band: bool = False  # bg is a solid coloured band (megaphones), not the game scene
    source: str = "unknown"
    parts: list | None = None  # the OCR boxes it was joined from: (left, right, top, bottom, text), left to right



class Reader:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        from rapidocr import RapidOCR  # imported here so `--help` is instant
        # "error": an empty chat box (game hidden) would otherwise log a warning every frame
        self.engine = RapidOCR(params={"Global.log_level": "error"}) if _rapid_accepts_params() else RapidOCR()

    def read(self, img: Image.Image) -> list[Line]:
        rgb = img.convert("RGB")
        boxes = self._ocr(rgb)
        if not boxes:
            return []
        height = float(np.median([b[1] - b[0] for b in boxes]))
        lines = [ln if ln.conf >= REREAD_BELOW else self._reread(rgb, ln, height) for ln in self._group(boxes)]
        arr = np.asarray(rgb)
        for ln in lines:
            ln.color, ln.bg, ln.band = _line_colors(arr, ln)
            ln.source = self._classify(ln)
        return lines

    def _ocr(self, img: Image.Image) -> list[tuple]:
        """(top, bottom, left, right, text, confidence) boxes in the image's own pixels."""
        s = self.cfg.scale
        big = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS) if s != 1 else img
        res = self.engine(np.asarray(big))
        if res is None or res.boxes is None or res.txts is None:
            return []
        boxes = []
        for box, txt, score in zip(res.boxes, res.txts, res.scores):
            if score < self.cfg.min_confidence or not txt.strip():
                continue
            ys, xs = [p[1] / s for p in box], [p[0] / s for p in box]
            boxes.append((min(ys), max(ys), min(xs), max(xs), txt.strip(), float(score)))
        return boxes

    def _reread(self, rgb: Image.Image, ln: Line, height: float) -> Line:
        """OCR one row on its own. On a busy chat box the detector sometimes draws one tall
        box over two rows and the recogniser returns garbage; the row cropped alone reads cleanly."""
        cy = (ln.top + ln.bottom) / 2
        top, bottom = max(0, int(cy - height * 0.55)), min(rgb.height, int(cy + height * 0.55) + 1)
        row = self._ocr(rgb.crop((0, top, rgb.width, bottom)))
        mid = (bottom - top) / 2
        row = sorted((b for b in row if abs((b[0] + b[1]) / 2 - mid) < height * 0.4), key=lambda b: b[2])
        if not row or min(b[5] for b in row) <= ln.conf:
            return ln
        return Line(text=" ".join(b[4] for b in row), conf=min(b[5] for b in row),
                    top=ln.top, bottom=ln.bottom, left=ln.left, right=ln.right,
                    parts=[(b[2], b[3], b[0] + top, b[1] + top, b[4]) for b in row])

    @staticmethod
    def _group(boxes) -> list[Line]:
        """OCR sometimes splits one chat line into several boxes: join boxes on the same row."""
        rows: list[list] = []
        for b in sorted(boxes, key=lambda b: (b[0] + b[1]) / 2):
            cy, h = (b[0] + b[1]) / 2, b[1] - b[0]
            for row in rows:
                rcy = sum((x[0] + x[1]) / 2 for x in row) / len(row)
                if abs(rcy - cy) < max(4, h * 0.5):
                    row.append(b)
                    break
            else:
                rows.append([b])
        out = []
        for row in rows:
            row.sort(key=lambda b: b[2])
            out.append(Line(
                text=" ".join(b[4] for b in row),
                conf=min(b[5] for b in row),
                top=int(min(b[0] for b in row)), bottom=int(max(b[1] for b in row)),
                left=int(min(b[2] for b in row)), right=int(max(b[3] for b in row)) + 1,
                parts=[(b[2], b[3], b[0], b[1], b[4]) for b in row],
            ))
        out.sort(key=lambda l: l.top)
        return out

    def _classify(self, ln: Line) -> str:
        """A whisper's shape decides first, then a solid band behind the text (megaphones),
        then the text colour."""
        if WHISPER.match(ln.text):
            return "whisper"
        if ln.band and ln.bg:
            name = _nearest(ln.bg, self.cfg.backgrounds, self.cfg.color_tolerance)
            if name:
                return name
        return _nearest(ln.color, self.cfg.colors, self.cfg.color_tolerance) or "unknown"



def _nearest(color, table: dict, tolerance: int) -> str | None:
    """Closest named colour; a name may list several, e.g. item_megaphone = [[83, 208, 190], [224, 173, 1]]."""
    if not color or not table:
        return None
    best, dist = None, 1e9
    for name, value in table.items():
        for rgb in (value if value and isinstance(value[0], list) else [value]):
            d = sum((a - b) ** 2 for a, b in zip(color, rgb)) ** 0.5
            if d < dist:
                best, dist = name, d
    return best if dist <= tolerance else None



def _rapid_accepts_params() -> bool:
    try:
        import inspect
        from rapidocr import RapidOCR
        return "params" in inspect.signature(RapidOCR.__init__).parameters
    except Exception:
        return False



def _line_colors(arr: np.ndarray, ln: Line):
    """(text colour, background colour, background is a solid band).

    Only the middle rows of the line are used, since OCR boxes overlap the lines above
    and below, and only its start (time stamp and name, drawn in the message's colour),
    since NPC speech bubbles in the scene can end up on the same row. The background is
    the median colour; megaphones sit on a solid band, other chat on the game scene.
    The text is the most common colour among the pixels far from the background, so the
    many pixels of the letters win over scattered bright spots and anti-aliased edges."""
    h = ln.bottom - ln.top
    right = min(ln.right or arr.shape[1], ln.left + 8 * max(h, 1))
    crop = arr[max(0, ln.top + h // 4): ln.bottom - h // 4 + 1, max(0, ln.left): right]
    if crop.size == 0:
        return None, None, False
    px = crop.reshape(-1, 3).astype(int)
    bg = np.median(px, axis=0)
    dist = np.abs(px - bg).sum(axis=1)
    band = bool((dist < 40).mean() >= 0.45)
    bg_rgb = tuple(int(v) for v in bg)
    if dist.max() < 60:
        return None, bg_rgb, band
    far = px[dist >= max(60, dist.max() * 0.5)]
    _, inverse, counts = np.unique(far // 24, axis=0, return_inverse=True, return_counts=True)
    text = far[inverse.reshape(-1) == counts.argmax()]
    return tuple(int(v) for v in np.median(text, axis=0)), bg_rgb, band



def _close(a, b, limit: int = 90) -> bool:
    return a is None or b is None or sum(abs(x - y) for x, y in zip(a, b)) < limit



def join_wrapped(head: str, tail: str) -> str:
    """A message and its wrapped row as one. The game wraps by the letter, mid-word ("Fashion C" /
    "rate!", "acc" / "ounts"), so the two join without a space, except after the end of a
    sentence or a closing bracket, and where a small letter meets a capital ("meet at" / "Henesys")."""
    a, b = head.rstrip(), tail.lstrip()
    if not a or not b:
        return a + b
    if a[-1] in ".,!?:;)]" or b[0] in "([" or (a[-1].islower() and b[0].isupper()):
        return f"{a} {b}"
    return a + b


def merge_wrapped(lines: list[Line], region_height: int, width: int | None = None) -> list[Line]:
    """Join a wrapped line to the message above it. A line that neither starts a message
    nor continues the one above is the tail of a message that scrolled out of the box
    ("Scroll: Intermediate] 90K"): without its start it is dropped. When the chat shows
    time stamps (Classic World does), only a time stamp starts a message. Given the box's
    width, only a line that ran on to near its right edge wrapped: anything under a short
    one is the game scene showing through (a name tag below the chat)."""
    starts = (lambda t: bool(TIMESTAMP.match(t))) if any(TIMESTAMP.match(l.text) for l in lines) else starts_message
    out: list[Line] = []
    for ln in lines:
        if starts(ln.text):
            out.append(ln)
            continue
        prev = out[-1] if out else None
        if (prev and ln.top - prev.bottom < (prev.bottom - prev.top) * 0.9
                and (not width or prev.right >= width * 0.7)
                and _close(prev.color, ln.color)
                and (not (prev.band and ln.band) or _close(prev.bg, ln.bg))):
            prev.text = join_wrapped(prev.text, ln.text)
            prev.bottom = ln.bottom
            if width:  # where its last row ends: whether that one wrapped too
                prev.right = ln.right
    return out



GAME_TITLE = "MapleStory"



def find_game_window() -> dict | None:
    """The game's client area on screen, {left, top, width, height, hwnd}: the largest visible,
    not minimised window titled "MapleStory" in Windows' list of windows. Only window titles
    and positions are asked for; the game's process is never opened."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt
    u32 = ctypes.windll.user32
    found = []
    title = ctypes.create_unicode_buffer(64)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
            return True
        u32.GetWindowTextW(hwnd, title, 64)
        if title.value == GAME_TITLE:
            r = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(r))
            pt = wt.POINT(0, 0)
            u32.ClientToScreen(hwnd, ctypes.byref(pt))
            if r.right > 200 and r.bottom > 200:
                found.append({"left": pt.x, "top": pt.y, "width": r.right, "height": r.bottom, "hwnd": hwnd})
        return True

    u32.EnumWindows(each, 0)
    return max(found, key=lambda w: w["width"] * w["height"]) if found else None



def chat_box_in(img: Image.Image, reader: "Reader", scale: float = FIND_SCALE) -> dict | None:
    """The chat messages' box within an image of the lower game window (see find_chat_region)."""
    old, reader.cfg.scale = reader.cfg.scale, scale  # a coarser read is enough to find the lines
    try:
        boxes = reader._ocr(img.convert("RGB"))  # (top, bottom, left, right, text, confidence)
    finally:
        reader.cfg.scale = old
    stamps = [b for b in boxes if TIMESTAMP.match(b[4])]
    # the chat column: the largest group of time stamps starting at the same x
    columns: list[list[tuple]] = []
    for b in sorted(stamps, key=lambda b: b[2]):
        if columns and b[2] - columns[-1][0][2] <= 12:
            columns[-1].append(b)
        else:
            columns.append([b])
    column = max(columns, key=len, default=[])
    if len(column) < 2:
        return None
    left = min(b[2] for b in column)
    height = float(np.median([b[1] - b[0] for b in column]))

    def row_right(first) -> float:
        """The end of a chat row: follow its text rightward while the gaps are small. Other
        UI on the same rows (shortcut keys, inventory) starts far to the right or left."""
        mid, end = (first[0] + first[1]) / 2, first[3]
        for b in sorted((b for b in boxes if abs((b[0] + b[1]) / 2 - mid) < height * 0.5 and b[2] > first[2]),
                        key=lambda b: b[2]):
            if b[2] - end > height * 4:
                break
            end = max(end, b[3])
        return end

    top, bottom = min(b[0] for b in column), max(b[1] for b in column)
    right = max(row_right(b) for b in column)
    arr = np.asarray(img.convert("RGB"))

    def in_typing_bar(b) -> bool:
        """The typing bar under the chat: its chat-target button ("All", "Party" ...) or text
        typed into its white field, which can sit as close under the last line as a wrap."""
        if re.fullmatch(r"(?i)all|party|buddy|friends?|guild|alliance|whisper|spouse", b[4].strip()):
            return True
        row = arr[int((b[0] + b[1]) / 2), max(0, int(b[2])):int(b[3])].astype(int)
        if not len(row):
            return False
        bg = np.median(row, axis=0)
        return bool(bg.min() > 215 and bg.max() - bg.min() < 25)

    # wrapped lines under the last message: indented a little and packed tight under it
    for b in sorted(boxes, key=lambda b: b[0]):
        if (b not in column and left < b[2] <= left + height * 6 and -height * 0.5 <= b[0] - bottom <= height * 0.3
                and not in_typing_bar(b)):
            bottom, right = b[1], max(right, row_right(b))
    pad = max(2, int(height * 0.3))
    x0, y0 = max(0, int(left - pad)), max(0, int(top - pad))
    return {"left": x0, "top": y0, "width": int(min(img.width - x0, right + 2 * pad - x0)),
            "height": int(min(img.height - y0, bottom + pad - y0))}
