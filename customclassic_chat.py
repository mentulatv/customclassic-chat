"""CustomClassic Chat: a modern chat panel over the game's own chat box, without the megaphones.

It sits exactly inside the game's chat box (its tab strip is the box's top line) and shows the
same chat sorted into tabs: All (everything but megaphones), Whisper, Party, Buddy and Mega
(the megaphones, kept apart instead of lost). A red dot marks a tab with messages you haven't
seen; on All you see everything else as it arrives. A received whisper plays a soft chime. It
scrolls like the game's chat: arrows, a draggable thumb, the track and the mouse wheel.

How it reads: Windows hands over pictures of the game window itself (Windows Graphics
Capture, as OBS's window capture uses), so the panel can cover the game's chat and still read
it; the chat lines are read with text recognition (reader.py). The game window is
found by its title: its process is never opened and nothing is sent to the game. Nothing
leaves this PC. The panel stays up while the game is open, and hides while it's minimised.

See-through: clicking ◐ on the tab strip makes the messages 90% see-through and lets clicks
through, so the game's own chat shows and can be clicked; clicking it again makes them solid.

    start.bat                   (or: pythonw customclassic_chat.py)
    Ctrl+Alt+F5   (if switched on in Settings → Position) move and resize; press again to keep it
    Ctrl+Alt+F3   reset position: back on the game's chat box, fitted again
    Ctrl+Alt+F6   hide / show
    Ctrl+Alt+F7   quit

    python customclassic_chat.py --demo                       made-up messages, to try the tabs (reads nothing)
    python customclassic_chat.py --replay shot1.png ...       read saved screenshots and print what goes where

Settings: chat.json holds the panel's place (relative to the game window) and the options in DEFAULTS.
"""
from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import uuid
from collections import deque

import guild_relay
import twitch_chat
from pathlib import Path

# packaged as an .exe, your settings, history and caches live next to it (the program's own
# files are in its _internal folder); run from source, next to this file
HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "chat.json"
CACHE_DIR = HERE / "cache"
DEFAULTS = {
    "reading_speed": "fastest",  # how eagerly the chat is read: "fastest", "balanced" or "light" (ReadPace)
    "font_px": None,          # message text size in pixels; None: sized from the game's chat lines
    "font_family": "Verdana", # the messages' font, one of FONTS (Settings → Look)
    "font_bold": False,       # the messages in bold
    "min_lines": 3,           # fewer lines in the game's chat (minimised, one or two): megaphones arriving together
                              # may scroll away unread, and a quiet ⚠ shows until clicked
    "history": 20000,         # messages kept in memory at most
    "keep_hours": 12,         # chat history kept between restarts, in hours; 0 keeps it forever
    "timestamps": "seconds",  # "seconds" [18:16:05], "minutes" [18:16] or "off"
    "opacity": 1.0,           # the panel's opacity when ◐ is off
    "solid_text": True,       # below full opacity only the background fades: the text stays solid, with a shadow
    "panel_bg": None,         # background colour; None: CustomClassic Chat's dark blue
    "colors": {},             # text colour per chat type (map, whisper, party, buddy, system, mega); empty: the game's
    "see_through": False,     # ◐ clicked on: the messages see-through and click-through until clicked off
    "peek_alpha": 0.1,        # how opaque they are then: 0.1 is 90% see-through
    "whisper_sound": True, "volume": 0.4,
    # map chat and megaphones padded with spacers (@@@@@@) to fill the chat, left out by what they're about
    "hide_padded": ["trade", "party", "other"],
    "system_messages": True,  # the game's own notes in All (out of MP, shop closed, play time); False hides them
    "watch": [],              # the watch list: words and items to look out for in megaphones (see watch.py)
    "watch_map": False,       # also look in map chat, not only megaphones
    "watch_sound": True, "watch_popup": True,  # a hit chimes and pops up a note by the panel
    "ignore_names": [],       # your character names: their name tags behind the chat aren't chat
    "names_url": None,        # where item names come from; None: the public price site
    "custom_tab": {"on": True, "name": "Custom", "kinds": ["whisper", "party", "buddy"]},  # a tab of your own
    "twitch_on": False,       # opt in: a Twitch channel's chat in a Twitch tab
    "twitch_channel": "",     # which channel
    "twitch_in_all": False,   # its chat in All too
    "relay_code": "",         # opt in: the guild's code (guild chat to Discord peer to peer, the channel back)
    "relay_tab": False,       # the guild's Discord channel in the Guild tab
    "relay_reader": "",       # this install's random id among the guild's apps (no name)
    "relay_cfg": {},          # guild code -> the guild's details as last heard (its name and Discord webhook)
    "relay_admin": {},        # guild code -> guilds set up from here: name, webhook, and the Discord bot token if any
    "guild_login": "",        # this app's login from the bot's magic link (/chatlink): to type in the Guild tab
    "game_name": "",          # your character's name, as last read from the game's status bar: what you type goes under it
    "tab": "All",
    "settings_page": "Appearance",  # the settings section open last
    "menu_close_s": 10,       # the right-click menu closes after this many seconds (0: stays until clicked away)
    "adjust_hotkey": False,   # Ctrl+Alt+F5 moves and resizes too (otherwise: right-click → Move or resize…)
    "update_check": True,     # ask GitHub now and then whether a newer version is out, and say so
    "box": None,              # the chat lines relative to the game window: dx, dy (from its bottom), w, h, line, cw, ch
    "extra": 0,               # pixels the panel reaches above the game's chat (dragged with the ≡ grip)
    "unlocked": False,        # placed anywhere you like instead of on the game's chat (it still reads the game's chat)
    "free": None,             # where it sits then, on screen: left, top, width, height
    "windows": [],            # extra overlays: each its place ("free"), see-through, own tab and panes (splits)
    "main_panes": [],         # the main chat's splits, top down: each its tab and share of the height
    "normal_windows": [],     # chats in regular windows (title bar, minimise, close): each its tab and place
}
MEGAPHONES = {"megaphone", "super_megaphone", "item_megaphone"}
TABS = [("All", {"map", "whisper", "party", "buddy", "guild", "other", "system", "status"}),
        ("Whisper", {"whisper", "status"}), ("Party", {"party", "status"}), ("Buddy", {"buddy", "guild", "status"}),
        ("Mega", {"mega", "status"}),
        ("Watch", {"watch"})]  # Watch: the lines your watch list caught, whatever chat they came from
# what the custom tab can show, as Settings lists them
CUSTOM_KINDS = [("map", "Map chat"), ("whisper", "Whispers"), ("party", "Party"), ("buddy", "Buddy"), ("guild", "Guild"),
                ("twitch", "Twitch chat"), ("discord", "Discord"),
                ("mega", "Megaphones"), ("system", "System messages"), ("watch", "Watch list catches")]
COLORS = {"guild": "#c8b4ff", "discord": "#8ea1f0", "guildsay": "#9fe3b8", "twitch": "#bf94ff", "map": "#ffffff", "whisper": "#00ff00", "party": "#ff8fc7", "buddy": "#ff9900", "other": "#c8d2e4",
          "mega": "#f2a7cf", "system": "#ffafaf", "status": "#ffc24b"}  # the game's own where measured; notes in amber
# the game's own pop-ups that appear over the chat box: CustomClassic Chat steps aside while one is up
POPUP = re.compile(r"(?i)\b(?:party|guild|alliance|family)\s+invit\w*\s+from\b|\b(?:trade|friend|buddy)\s+request\s+from\b"
                   r"|\binvited\s+you\b")
# the game's chat-type list: "/To All(/s)", "/To Buddy(/b)", "/To Group(/gr)", "/To Party(/p)" ... (its words
# often run on into the chat line beside them, and "All" can read as "AlI"); the shortcut in brackets after
# the name tells it from someone typing "/to buddy" in chat
CHAT_MENU = re.compile(r"(?i)/\s*to\s*(?:a[l1i|]{2}|buddy|group|party|guild|alliance|spouse|expedition)\s*\("
                       r"|\(\s*/\s*(?:s|b|gr|p|g|a)\s*\)")


def chat_menu_open(read) -> bool:
    """The game's chat-type list is open over its chat: one of its entries is read there. Like a
    pop-up, the panel steps aside to show it."""
    return any(CHAT_MENU.search(ln.text) for ln in read)


PANEL, STRIP, TAB, TAB_ON, INK, SOFT, DOT = "#111827", "#0b1120", "#1c2740", "#2f5597", "#eef3fb", "#8f9db5", "#ff4b4b"
WARN = "#ffc24b"
SOFT_INK = "#c8d2e4"  # the second line of a note
SHADOW = "#000000"  # behind solid text (pure black: the see-through colour is a near-black of its own)


def overlay_key() -> str:
    import overlay
    return overlay.KEY_COLOR
GOLD = "#ffd24a"  # the watch list's star and dot
ADJUST, ADJUST_EDGE = "#2f6fe0", "#9fc2ff"  # adjust mode: the banner, the outline and corner handles
SB_TRACK, SB_BUTTON, SB_ARROW, SB_THUMB, SB_EDGE = "#e3e8ef", "#a9c8ee", "#1f4f8f", "#8ea3c2", "#5b7fb4"  # as the game's
FONT = "Verdana"
# the fonts on offer for the messages (Settings → Look): hand-picked, all in every Windows, as
# (family, kind)
FONTS = [("Verdana", "sans serif"), ("Segoe UI", "sans serif"), ("Tahoma", "sans serif"),
         ("Georgia", "serif"), ("Times New Roman", "serif"), ("Consolas", "monospace"), ("Courier New", "monospace")]
HOTKEYS = {2: 0x75, 3: 0x76, 4: 0x72}  # Ctrl+Alt+F6 hide, F7 quit, F3 fit again
HK_ADJUST_KEY, ADJUST_VK = 5, 0x74  # Ctrl+Alt+F5 move and resize: only when switched on in Settings
RECHECK_S = 5  # seconds between looks at whether the game's chat was resized
HK_EDIT, HK_HIDE, HK_QUIT, HK_FIT = 1, 2, 3, 4

# [21:16], and OCR's "[21:16j", "16 : 39]" (the [ lost)
_STAMP = r"^[^\w\[({]{0,3}(?:(?:[\[({]\s?)?(?P<time>\d{1,2}\s?[:.;]\s?\d{2})\s?[\])}jlI|1]?)?\s*"
_NAME = r"(?P<name>(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{2,13})"  # at least one letter: "16" of a lost "[16:39]" isn't one
_MSG = re.compile(_STAMP + r"(?:\[[^\]]{1,25}\]\s*)?"                                       # a medal
                  + _NAME + r"\s*(?:\[(?P<where>[^\]]{1,24})\]\s*)?"  # a whisper's world-channel: "Name[Windia-15]>> hi"
                  + r"(?P<sep><<|>>|«|»|[:;])\s?(?P<body>.*)$")
_LOOSE = re.compile(_STAMP + _NAME + r"[^:;]{0,14}[:;]\s?(?P<body>.*)$")  # "Tarvin CH22 : S> ..."


# ------------------------------------------------------------------ what goes where


def parse(text: str, loose: bool = False) -> dict | None:
    """{name, body, sep} of "[21:16] Rowan : hi" or "[21:15]Nimbi<< hi"; loose also takes a
    megaphone's channel badge between the name and the colon. None for other text."""
    m = _MSG.match(text.strip()) or (_LOOSE.match(text.strip()) if loose else None)
    if not m or not m.group("body").strip():
        return None
    out = {"name": m.group("name"), "body": m.group("body").strip(), "sep": m.groupdict().get("sep") or ":",
           "time": real_time(m.group("time"))}
    if m.groupdict().get("where"):  # a received whisper's "[Windia-15]"
        out["where"] = m.group("where")
    return out


def real_time(text: str | None) -> str | None:
    """'16:43' from a time stamp as read ('16 : 43', '16.43'); None unless it's a real time of day."""
    m = re.fullmatch(r"(\d{1,2})\s?[:.;]\s?(\d{2})", text or "")
    return f"{int(m[1]):02d}:{m[2]}" if m and int(m[1]) < 24 and int(m[2]) < 60 else None


# ------------------------------------------------------------------ the game scene behind the chat
# The game's chat box is see-through, so whatever walks behind it gets read too: monster name
# tags ("Lv. 6] Slime"), character names, damage numbers. Chat text is told apart by where it
# sits and what it looks like.

MOB_TAG = re.compile(r"\s*\[?\s*Lv\s*[.,]?\s*\d{1,3}\s*\].*$", re.I)  # "Lv. 6] Slime" and all after it
SENTENCE_TAIL = re.compile(r"^(?P<keep>.*[.!?)])\s*(?P<tail>[^.!?)]*)$")


def trim_scene(lines, pitch: float) -> list:
    """Drop the scene from what was read. A chat line starts at the box's left edge, and its
    wrapped lines a little indented (about 1.3 lines' height); text further in is the scene.
    Within a row, chat text runs on without big gaps: a few words after a wide gap (a name
    tag) end the line, and so does a bare number much taller than the chat text (a damage
    number; a tall box of words is the mouse pointer over the chat). Longer text after a gap
    is the chat itself, with a stretch the reader missed (under the pointer, say). A
    megaphone's own band can't tell: its channel badge and item link sit on boxes of their
    own colour."""
    out = []
    for ln in lines:
        if ln.left > pitch * 2.5:
            continue
        parts = sorted(ln.parts or [], key=lambda q: q[0])
        keep = parts[:1]
        for i, q in enumerate(parts[1:], 1):
            tall = q[3] - q[2] > (keep[0][3] - keep[0][2]) * 1.4
            rest = " ".join(r[4] for r in parts[i:])
            if (q[0] - keep[-1][1] > pitch * 2 and len(rest) <= 16) or (tall and re.fullmatch(r"[\d\s.,]+", q[4])):
                break
            keep.append(q)
        if parts and len(keep) < len(parts):
            ln.text = " ".join(q[4] for q in keep)
            ln.right = int(max(q[1] for q in keep)) + 1
        out.append(ln)
    return out


def _garbled(text: str) -> bool:
    words = re.findall(r"[^\W_]+", text)
    return len(words) >= 3 and sum(len(w) == 1 for w in words) / len(words) >= 0.4  # stray single letters


SPACER_KINDS = {"map", "other", "mega"}  # where crowded maps get lines padded out to fill the chat


def padded(body: str) -> bool:
    """A line padded with spacers to take up more of the chat ("...scroll@@@@@@@@@@@@"). Text
    recognition reads a row of @ partly as Q or O, so a long run of one symbol counts, and so does
    a long word of at most two characters with a symbol among them ("@QQQ@QQQQ"), or of one
    character only. A drawn-out word ("cashhhhhhhh") doesn't."""
    if re.search(r"([^\w\s])\1{5,}", body):
        return True
    for word in body.split():
        if len(word) >= 8 and (len(set(word)) == 1 or (len(set(word)) <= 2 and re.search(r"[^\w]", word))):
            return True
    return False


PARTY_AD = re.compile(r"(?i)\b(?:[a-z]?pq|lf[gm]?\d*|party|pt|need\s*\d*\s*more|join|recruit\w*|leech\w*|"
                      r"carry|exp\s*share|boss\s*run|zak(?:um)?\s*run|\d\s*/\s*6)\b")
TRADE_AD = re.compile(r"(?i)(?:\b[sbt]\s*>|\bwt[sbt]\b|\bsell\w*|\bbuy\w*|\bc\s*/\s*o\b|\b\d+(?:[.,]\d+)?\s*(?:k|m|mil|b)\b)")
PADDED_KINDS = [("trade", "Buying and selling"), ("party", "Party quests and parties"), ("other", "Everything else")]


def padded_kind(body: str) -> str:
    """What a padded line is about: "trade" (buying or selling: S>, B>, a price), "party"
    (party quests and parties: LF KPQ, need 2 more) or "other". A party ad wins unless it also
    buys or sells (a price alone can be a PQ's fee)."""
    marker = re.search(r"(?i)\b[sbt]\s*>|\bwt[sbt]\b|\bsell|\bbuy", body)
    if PARTY_AD.search(body) and not marker:
        return "party"
    return "trade" if TRADE_AD.search(body) else ("party" if PARTY_AD.search(body) else "other")


def clean_body(kind: str, body: str, ignore: list[str]) -> str:
    """A message without the scene that got read into it: a monster's name tag, a name tag
    of your own characters, a system message's stray tail ("...use this skill.Snail")."""
    body = MOB_TAG.sub("", body).strip()
    if kind == "system":
        m = SENTENCE_TAIL.match(body)
        if m and m["tail"] and len(m["tail"].split()) <= 4:
            body = m["keep"]
        # garble after the message: scenery read as letters ("skill. l7 e t s te e ae iat er.")
        sentences = re.split(r"(?<=[.!?])\s+", body)
        while len(sentences) > 1 and _garbled(sentences[-1]):
            sentences.pop()
        body = " ".join(sentences)
    names = {n.lower() for n in ignore if n}
    words = body.split()
    while words and words[-1].strip(".,!?").lower() in names:
        words.pop()
    body = " ".join(words)
    if kind in ("map", "other") and re.fullmatch(r"[\d\s.,]*\d{3}[\d\s.,]*", body):
        return ""  # a damage number
    return body


def kind_of(line, backgrounds: dict | None = None) -> str | None:
    """A line's kind, or None to leave it out. The colours decide; a line whose colours are
    unknown but that sits on a solid band is a megaphone. A known chat colour wins over the
    band: map chat over a plain stretch of the game scene looks like a band too. System lines
    ("You have left the party.", "[Friend] X has logged in.") are kept; the "[Notice] beware of
    scams" broadcasts and the gachapon announcements on their red band are left out."""
    src = line.source
    if src == "notice":
        if "[notice]" in line.text.lower().replace(" ", ""):
            return None
        red = (backgrounds or {}).get("notice")
        if line.band and red and line.bg and _closest(line.bg, red) and \
                sum((a - b) ** 2 for a, b in zip(line.bg, _closest(line.bg, red))) ** 0.5 < 45:
            return None
        return "system"
    if src in MEGAPHONES:
        return "mega"
    if src == "whisper":
        return "whisper"
    if src == "guild":  # only with a guild colour of its own (config: [colors] guild): shared with a relay
        return "guild"
    if src in ("buddy", "buddy_guild"):
        return "buddy"
    if src == "party":
        return "party"
    if src == "general":
        return "map"
    return "mega" if line.band else "other"


SPACER_RUN = re.compile(r"[@QqOo0④α]{3,}")


def without_spacers(text: str) -> str:
    """A line without its spacer padding (@@@@@@), which text recognition reads a little
    differently every time (@QQ@④QQ, OOOOOOOO): runs of those symbols, unless a short run of
    only 0's and O's (a price, "100k" read as "1O0k", or a word)."""
    def drop(m):
        run = m.group()
        return run if set(run) <= {"0", "O", "o"} and len(run) < 6 else " "
    return SPACER_RUN.sub(drop, text)


# spacers: @ runs (also read as Q, O, 0, ④, ①...), and runs of other symbols
PAD_RUN = re.compile(r"[@QqOo0α①-⑳]{3,}|[@①-⑳]{2,}|[~=*#$\-_.!]{4,}")
PAD_ENDS = re.compile(r"^[\s.~=*\-_@]{2,}|[\s#~@*①-⑳]+$")  # "....S> hat", "75k~", "quick#"


def unpadded(body: str) -> str:
    """A padded line as it's shown: the spacers padding it out gone, and those between items
    ("WG @@@@@@ Maple-Stein Head @@@@@@ Trash NX") a dot. Zeros in a number stay, and so does a
    short run of O's (a word, or "1O0k")."""
    def sub(m):
        run, at = m.group(), m.start()
        if set(run) <= {"0"} and at and body[at - 1].isdigit():
            return run
        if set(run) <= {"0", "O", "o"} and len(run) < 6:
            return run
        return " · "
    text = re.sub(r"\s*(?:·\s*)+", " · ", PAD_RUN.sub(sub, body))
    text = re.sub(r" · \S{1,2}$", "", text.strip(" ·"))  # a stray character read after the padding
    return PAD_ENDS.sub("", text).strip(" ·") or body


class Dedupe:
    """The chat shows each line for many reads, and text recognition reads it a little
    differently now and then ("CHO1" / "CH01"): a line close to one seen recently is not new."""

    def __init__(self, minutes: float = 20, compare_last: int = 120):
        self.minutes, self.compare_last = minutes, compare_last
        self.recent: deque[tuple[float, str]] = deque()
        self.looked = self.fresh = 0  # lines asked about, and how many of them were new, ever

    def seed(self, messages, now: float) -> None:
        """Lines already read before a restart (kept in the history as they were read): the
        game's chat still shows them, and they aren't new again."""
        for m in messages:
            if m.get("raw") and now - m.get("at", 0) < self.minutes * 60:
                self.recent.append((m["at"], re.sub(r"[^a-z0-9]", "", without_spacers(m["raw"]).lower())))

    def is_new(self, text: str, now: float) -> bool:
        from rapidfuzz import fuzz
        key = re.sub(r"[^a-z0-9]", "", without_spacers(text).lower())
        self.looked += 1
        while self.recent and self.recent[0][0] < now - self.minutes * 60:
            self.recent.popleft()
        for _, seen in list(self.recent)[-self.compare_last:]:
            if key == seen or (len(key) > 8 and fuzz.ratio(key, seen) >= 92):
                return False
        self.recent.append((now, key))
        self.fresh += 1
        return True


def hex_color(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb[:3])


def _closest(rgb, options):
    """The listed colour nearest to the one seen; a name may list several ([[r, g, b], ...])."""
    options = options if options and isinstance(options[0], (list, tuple)) else [options]
    if not rgb:
        return options[0]
    return min(options, key=lambda o: sum((a - b) ** 2 for a, b in zip(rgb, o)))


def style_for(line, kind: str, colors: dict, backgrounds: dict) -> tuple[str | None, str | None]:
    """The game's own look for a line: (text colour, band colour or None). The colours
    measured for its chat type win, so text recognition's guess doesn't make one whisper a
    slightly different green from the next; a type not measured yet keeps the colour seen."""
    src = line.source
    fg = _closest(line.color, colors[src]) if src in colors else line.color
    bg = None
    if kind == "mega" and line.band:
        bg = _closest(line.bg, backgrounds[src]) if src in backgrounds else line.bg
    return (hex_color(fg) if fg else None), (hex_color(bg) if bg else None)


def messages_from(lines, dedupe: Dedupe, now: float, palette: tuple[dict, dict] | None = None,
                  ignore: list[str] = ()) -> list[dict]:
    """New messages from one read of the chat, oldest first, each with the game's colours when
    a palette (config.toml's [colors] and [backgrounds]) is given. The time shown is your own
    clock: the game's runs on server time, and text recognition garbles it now and then."""
    out = []
    stamp = re.compile(_STAMP)
    # the game shows time stamps: then every chat line has one, and a line without is the scene
    stamped = any(real_time((stamp.match(ln.text.strip()) or {"time": None})["time"]) for ln in lines)
    for ln in lines:
        kind = kind_of(ln, palette[1] if palette else None)
        if not kind:
            continue
        p = parse(ln.text, loose=kind == "mega")
        if kind == "system":  # no speaker: the line itself, without its time stamp
            m = stamp.match(ln.text.strip())
            body = ln.text.strip()[m.end():].strip()
            p = {"name": "", "body": body, "sep": "", "time": real_time(m["time"])} if body else None
        if p:
            p["body"] = clean_body(kind, p["body"], ignore)
            # (a megaphone sits on its own band, which the scene can't fake: a garbled stamp is fine)
            if (stamped and not p["time"] and kind != "mega") or not p["body"]:
                p = None
        if not p or not dedupe.is_new(ln.text, now):
            continue
        fg, bg = style_for(ln, kind, *palette) if palette else (None, None)
        msg = {"kind": kind, "time": time.strftime("%H:%M", time.localtime(now)), "name": p["name"],
               "body": p["body"], "at": now, "to": None, "fg": fg, "bg": bg, "raw": ln.text,
               "stamp": p.get("time")}  # the game's own time stamp: server time, the same on every screen
        if kind == "whisper" or p["sep"] in ("<<", ">>", "«", "»"):
            msg["kind"] = "whisper"
            msg["to"] = p["sep"] in ("<<", "«")  # "Name<< hi" is one you sent, "Name[Windia-15]>> hi" one you got
            ch = re.search(r"(\d{1,2})\s*$", p.get("where") or "")
            if ch:
                msg["ch"] = int(ch[1])  # the sender's channel, to find them
        out.append(msg)
    return out


STAMP_FORMATS = {"seconds": "%H:%M:%S", "minutes": "%H:%M", "off": None}


def line_text(msg: dict, stamps: str = "seconds") -> str:
    """A message as one chat line. The time is CustomClassic Chat's own clock when the line was read,
    so it's there even when the game shows no time stamps."""
    who = msg["name"]
    if msg["kind"] == "whisper":
        who = f"{'To' if msg['to'] else 'From'} {msg['name']}" + (f" (ch {msg['ch']})" if msg.get("ch") else "")
    text = f"{who} : {msg['body']}" if who else msg["body"]
    fmt = STAMP_FORMATS.get(stamps, "%H:%M:%S")
    return f"[{time.strftime(fmt, time.localtime(msg['at']))}] {text}" if fmt else text


HISTORY_FILE = HERE / "chat_history.jsonl"


def load_history(path: Path, keep_hours: float, now: float) -> list[dict]:
    """Messages saved by earlier runs, within the kept hours (all of them when keep_hours is 0)."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if not keep_hours or now - m.get("at", 0) <= keep_hours * 3600:
                    out.append(m)
    except OSError:
        pass
    return out


def write_atomic(path: Path, text: str) -> None:
    """Write a whole file at once: a crash halfway leaves the old one, not half a new one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def prune_history(path: Path, keep_hours: float, now: float) -> None:
    """Drop saved messages older than the kept hours (nothing when they're kept forever)."""
    if keep_hours and path.exists():
        kept = load_history(path, keep_hours, now)
        write_atomic(path, "".join(json.dumps(m) + "\n" for m in kept))


def save_message(path: Path, msg: dict) -> None:
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg) + "\n")
    except OSError:
        pass


def custom_name(custom: dict | None) -> str | None:
    """The custom tab's name when it's on: its own, unless empty or a fixed tab's."""
    if not custom or not custom.get("on"):
        return None
    name = (custom.get("name") or "").strip()[:12]
    taken = {n.lower() for n, _ in TABS} | {"twitch"}
    return name if name and name.lower() not in taken else "Custom"


def tabs_for(custom: dict | None, twitch: bool = False, twitch_in_all: bool = False,
             discord: bool = False) -> list[tuple[str, set]]:
    """The tabs: the fixed ones, a Twitch tab after Mega when a channel is set (its chat in All
    too if asked), a Guild tab for the guild relay's channel, and the custom tab before Watch
    when it's on. Map chat brings the lines of no known chat type along, as All does."""
    tabs = [(n, k | {"twitch"} if n == "All" and twitch and twitch_in_all else k) for n, k in TABS]
    if twitch:
        tabs.insert(5, ("Twitch", {"twitch", "status"}))
    if discord:  # the guild's own tab: its Discord channel, what members type here, and the game's guild chat
        tabs.insert(len(tabs) - 1, ("Guild", {"discord", "guildsay", "guild", "status"}))
    name = custom_name(custom)
    if name:
        picked = set(custom.get("kinds") or [])
        tabs.insert(len(tabs) - 1, (name, picked | {"status"} | ({"other"} if "map" in picked else set())))
    return tabs


def shows(kinds: set, msg: dict) -> bool:
    """Whether a tab of these kinds shows the message: "watch" stands for the watch list's catches."""
    return msg["kind"] in kinds or bool("watch" in kinds and msg.get("watch"))


class ChatLog:
    """Messages in tabs, and which tabs hold messages you haven't seen."""

    def __init__(self, history: int = 400, tab: str = "All", tabs: list | None = None):
        self.messages: deque[dict] = deque(maxlen=history)
        self.tabs, self.tab, self.unread = [], "All", {}
        self.set_tabs(tabs or TABS, tab)
        self.hidden: set[str] = set()  # kinds not shown (kept, so showing them again brings them back)
        self.hide_padded: set[str] = set()  # lines padded with spacers left out, by what they're about (kept too)

    def set_tabs(self, tabs: list, tab: str | None = None) -> None:
        """New tabs (the custom tab changed): unread marks kept where the tab still exists."""
        self.tabs = tabs
        self.unread = {name: self.unread.get(name, False) for name, _ in tabs}
        want = tab or self.tab
        self.tab = want if want in self.unread else "All"

    def kinds(self, tab: str | None = None) -> set:
        return dict(self.tabs)[tab or self.tab]

    def view_of(self, tab: str = "All") -> "ChatLog":
        """Another window's view of the same messages: its own tab and unread marks, the same
        chat (and the same hidden kinds). Hand it each new message with notice()."""
        view = ChatLog(tab=tab, tabs=self.tabs)
        view.messages, view.hidden, view.hide_padded = self.messages, self.hidden, self.hide_padded
        return view

    def add(self, msg: dict) -> None:
        self.messages.append(msg)
        self.notice(msg)

    def notice(self, msg: dict) -> None:
        """Mark the tabs a new message landed in, where it isn't in view."""
        if msg["kind"] == "status" or msg["kind"] in self.hidden or msg.get("padded") in self.hide_padded:
            return  # nothing to miss
        showing = self.kinds()
        for name, kinds in self.tabs:
            if name == self.tab or not shows(kinds, msg):
                continue
            # a dot where it isn't in view; a watch-list catch always marks the tabs collecting them
            if not shows(showing, msg) or (msg.get("watch") and "watch" in kinds):
                self.unread[name] = True

    def select(self, tab: str) -> None:
        self.tab, self.unread[tab] = tab, False

    def visible(self) -> list[dict]:
        kinds = self.kinds() - self.hidden
        return [m for m in self.messages if shows(kinds, m) and m.get("padded") not in self.hide_padded]


# ------------------------------------------------------------------ where the panel goes


def to_relative(box: dict, line: float, client: dict) -> dict:
    """Stored relative to the game window's bottom-left, where the chat box is anchored."""
    return {"dx": box["left"], "dy": client["height"] - box["top"], "w": box["width"], "h": box["height"],
            "line": round(line, 1), "cw": client["width"], "ch": client["height"], "bar": box.get("bar")}


def from_relative(rel: dict, client: dict) -> dict | None:
    """Screen rect of the message area for a game window, or None when the window changed size."""
    if not rel or (rel["cw"], rel["ch"]) != (client["width"], client["height"]):
        return None
    return {"left": client["left"] + rel["dx"], "top": client["top"] + client["height"] - rel["dy"],
            "width": rel["w"], "height": rel["h"]}


def strip_height(line: float) -> int:
    return max(16, round(line * 0.85))


def bar_width(line: float) -> int:
    """The game's scrollbar width (divider and track) when it couldn't be measured: about 1.1 lines."""
    return max(12, round(line * 1.1))


def thumb(total: int, in_view: int, scroll: int, height: int, button: int) -> tuple[int, int]:
    """(top, height) of the scrollbar's thumb in the track between the two arrow buttons. Its
    size is the share of the tab's messages in view; at the bottom when showing the newest.
    `scroll` counts messages up from the newest."""
    track = max(1, height - 2 * button)
    if total <= in_view or total == 0:
        return button, track
    size = max(min(track, button), round(track * in_view / total))
    frac = (total - in_view - scroll) / (total - in_view)  # 1 at the newest, 0 at the oldest
    return button + round((track - size) * max(0.0, min(1.0, frac))), size


def scroll_at(top: int, total: int, in_view: int, height: int, button: int, size: int) -> int:
    """The scroll position for a thumb dragged to `top`."""
    track = max(1, height - 2 * button)
    frac = max(0.0, min(1.0, (top - button) / max(1, track - size)))
    return round((1 - frac) * max(0, total - in_view))


def panel_rect(read: dict, extra: int, bar: int = 0) -> dict:
    """The panel: the game's chat lines reaching `extra` pixels higher, and `bar` pixels wider
    so its own scrollbar lies exactly over the game's. It grows upward from the bottom, like
    the game's chat; it never gets smaller than the game's chat, which it has to cover."""
    extra = max(0, int(extra))
    return {"left": read["left"], "top": read["top"] - extra, "width": read["width"] + int(bar),
            "height": read["height"] + extra}


def anchored(read: dict, line: float, bar: int = 0) -> dict:
    """The panel on the game's chat: its lines, starting about half a line below their top, so
    the game's own resize edge above them stays free and easy to grab (the panel follows the
    new size)."""
    a = max(6, round(line * 0.6))
    return {"left": read["left"], "top": read["top"] + a, "width": read["width"] + int(bar),
            "height": read["height"] - a}


CLOSED_LINE = re.compile(r"^\S{2,13}\s?:\s*\S")  # "Name : text" in the typing bar: the game's chat is closed


def chat_closed(bar_read) -> bool:
    """The game's chat closed completely: it then shows its newest message inside the typing bar
    under where the chat was ("Name : text"), where an open chat has the chat-type button."""
    return any(CLOSED_LINE.match(ln.text.strip()) for ln in bar_read)


def short_chat(read, bottom: float, left: float, right: float, line: float) -> int:
    """A chat too short for find_lines (one or two lines, where a time stamp may not be read):
    how many rows are stacked right above its bottom, one line apart."""
    rows = sorted((ln for ln in read if left - line <= ln.left <= right and ln.bottom <= bottom + line * 0.5),
                  key=lambda ln: -ln.top)
    top, n = None, 0
    for ln in rows:
        edge = bottom if top is None else top
        if edge - ln.bottom > line * 0.8:
            break
        top, n = ln.top, n + 1
    return n


def chat_lines(read: dict | None, line: float) -> int:
    """How many lines the game's chat shows."""
    return round(read["height"] / line) if read and line else 0


class CoverWatch:
    """Is the game drawing something over its chat (a party invite, a notice)? Then most of
    the time-stamped lines usually seen there are gone; two reads like that in a row and the
    panel steps aside until they're back. Only ordinary reads count towards "usual", so a
    window that stays up a while can't lower it."""

    def __init__(self, keep: int = 20):
        self.counts: deque[int] = deque(maxlen=keep)
        self.low_reads = 0

    def covered(self, stamped: int) -> bool:
        usual = sorted(self.counts)[len(self.counts) // 2] if self.counts else 0
        low = usual >= 2 and stamped < max(1, usual * 0.4)
        if low:
            self.low_reads += 1
        else:
            self.low_reads = 0
            self.counts.append(stamped)
        return self.low_reads >= 2


def resized(current: dict, found: dict, line: float, history: deque) -> dict | None:
    """The game's chat with its new height, if it was resized. Only the height changes: the
    chat grows upward from its bottom, and its width stays. The top followed is the second
    tallest of the recent looks: a partly hidden top line that text recognition sees one time
    and not the next can't make it flicker, and one stray read above the chat can't grow it."""
    history.append(found["top"])
    if len(history) < 2:
        return None
    target = sorted(history)[1]
    if abs(target - current["top"]) <= line * 0.5:
        return None
    bottom = current["top"] + current["height"]
    return {**current, "top": target, "height": bottom - target}


def pointer_away(rect: tuple, pt: tuple) -> int:
    """How far the pointer is outside a rect (left, top, right, bottom): 0 on it."""
    left, top, right, bottom = rect
    return max(left - pt[0], pt[0] - right, top - pt[1], pt[1] - bottom, 0)


def close_menu_when_left(open_: threading.Event, after_s: float = 10, far: int = 120, pointer=None) -> None:
    """While a right-click menu is open (open_ set): close it, as Escape would, once the pointer
    has moved well away from it (more than `far` pixels) or it has been up `after_s` seconds
    (0: no time limit). A left click outside closes it anyway, as Windows menus do."""
    import ctypes
    import ctypes.wintypes as wt
    u32 = ctypes.windll.user32
    u32.FindWindowW.restype = ctypes.c_void_p

    def cursor():
        pt = wt.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    pointer = pointer or cursor
    start, menu = time.time(), None
    while open_.is_set():
        time.sleep(0.05)
        h = u32.FindWindowW("#32768", None)  # the class of Windows' pop-up menus
        if not h or not u32.IsWindowVisible(ctypes.c_void_p(h)):
            if menu:
                return  # closed
            continue
        menu = h
        r = wt.RECT()
        u32.GetWindowRect(ctypes.c_void_p(h), ctypes.byref(r))
        rect = (r.left, r.top, r.right, r.bottom)
        if pointer_away(rect, pointer(rect)) > far or (after_s and time.time() - start > after_s):
            u32.PostMessageW(ctypes.c_void_p(h), 0x0100, 0x1B, 0)  # WM_KEYDOWN Escape
            return


def on_screen(r: dict) -> bool:
    """Whether a rect on screen is on one of the monitors (not off the edge, or on one unplugged since)."""
    import ctypes
    import ctypes.wintypes as wt
    rect = wt.RECT(int(r["left"]), int(r["top"]), int(r["left"] + r["width"]), int(r["top"] + r["height"]))
    u32 = ctypes.windll.user32
    u32.MonitorFromRect.restype = ctypes.c_void_p
    return bool(u32.MonitorFromRect(ctypes.byref(rect), 0))  # MONITOR_DEFAULTTONULL


def rescued(free: dict, area: dict) -> dict:
    """An unlocked panel whose tab strip (where it's dragged from) is off every monitor comes
    back to the middle of `area` (the game window or the main screen), no bigger than it."""
    w, h = min(free["width"], area["width"]), min(free["height"], area["height"])
    return {"left": area["left"] + (area["width"] - w) // 2, "top": area["top"] + (area["height"] - h) // 2,
            "width": w, "height": h}


def inside(x: int, y: int, r: dict | None) -> bool:
    return bool(r) and r["left"] <= x < r["left"] + r["width"] and r["top"] <= y < r["top"] + r["height"]


def load_settings() -> dict:
    opts = json.loads(json.dumps(DEFAULTS))
    try:
        opts.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return opts


def save_settings(opts: dict) -> None:
    write_atomic(SETTINGS_FILE, json.dumps({k: opts.get(k) for k in DEFAULTS}, indent=1))


# ------------------------------------------------------------------ the game window


def game_geometry() -> dict | None:
    """The game window: hwnd, its client area on screen, and where that client area sits in
    the captured picture (which covers the whole window, frame included)."""
    import ctypes
    import ctypes.wintypes as wt
    import reader as core
    win = core.find_game_window()
    if not win:
        return None
    r = wt.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(win["hwnd"]), 9, ctypes.byref(r), ctypes.sizeof(r)):
        ctypes.windll.user32.GetWindowRect(wt.HWND(win["hwnd"]), ctypes.byref(r))  # DWMWA_EXTENDED_FRAME_BOUNDS failed
    return {"hwnd": win["hwnd"], "client": {k: win[k] for k in ("left", "top", "width", "height")},
            "ox": win["left"] - r.left, "oy": win["top"] - r.top}


class GameCapture:
    """The latest picture of the game window (BGRA), at most every 400 ms."""

    def __init__(self, hwnd: int):
        from windows_capture import WindowsCapture
        self.lock = threading.Lock()
        self.frame = None
        self.closed = False
        try:
            cap = WindowsCapture(cursor_capture=False, draw_border=False, minimum_update_interval=400, window_hwnd=hwnd)
        except Exception:  # Windows 10 can't turn the yellow capture border off
            cap = WindowsCapture(cursor_capture=False, minimum_update_interval=400, window_hwnd=hwnd)

        @cap.event
        def on_frame_arrived(frame, control):
            with self.lock:
                self.frame = frame.frame_buffer.copy()  # the buffer is only valid during this call

        @cap.event
        def on_closed():
            self.closed = True

        self.control = cap.start_free_threaded()

    def latest(self):
        with self.lock:
            return self.frame

    def stop(self) -> None:
        try:
            self.control.stop()
        except Exception:
            pass


def make_chime(path: Path, notes, volume: float) -> None:
    """A soft chime as a .wav: sine notes a little apart, each with a quick attack and decay."""
    import math
    import struct
    import wave
    rate, dur, gap = 44100, 0.35, 0.07
    total = int(rate * (dur + gap * (len(notes) - 1)))
    samples = [0.0] * total
    for i, freq in enumerate(notes):
        start = int(rate * gap * i)
        for n in range(int(rate * dur)):
            t = n / rate
            env = min(1.0, t / 0.005) * math.exp(-t * 9)
            samples[start + n] += (math.sin(2 * math.pi * freq * t) + 0.2 * math.sin(4 * math.pi * freq * t)) * env
    peak = max(abs(s) for s in samples) or 1
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * volume * 32767)) for s in samples))


# a generic maple leaf on a 100x100 grid (stem at the bottom), symmetric about x = 50
LEAF_RIGHT = [(50, 4), (57, 19), (64, 15), (61, 37), (74, 25), (77, 32), (90, 29), (85, 44), (94, 50), (72, 64),
              (75, 72), (54, 69), (54, 90)]
LEAF = LEAF_RIGHT + [(100 - x, y) for x, y in reversed(LEAF_RIGHT)]
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def icon_image(size: int = 64):
    """The app's icon: a maple leaf on the blue chat bubble, with "CC" under it from 48 pixels up
    (smaller, the letters would only blur). Drawn four times larger and shrunk, for smooth edges."""
    from PIL import Image, ImageDraw, ImageFont
    k = 4
    s = size * k / 64
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(12.5 * s, 46 * s), (8.5 * s, 63.5 * s), (32 * s, 47.5 * s)], fill="#9db1d3")  # the tail's outline
    d.rounded_rectangle((2 * s, 5 * s, 62 * s, 50 * s), radius=12 * s, fill="#2f5597", outline="#9db1d3",
                        width=max(1, round(2 * s)))
    d.polygon([(14 * s, 45 * s), (10.5 * s, 60 * s), (29.5 * s, 47 * s)], fill="#2f5597")  # bubble and tail: one shape
    letters = size >= 48
    x0, y0, x1, y1 = (17 * s, 7 * s, 47 * s, 37 * s) if letters else (12 * s, 7.5 * s, 52 * s, 47.5 * s)
    d.polygon([(x0 + (x1 - x0) * x / 100, y0 + (y1 - y0) * y / 100) for x, y in LEAF], fill="#f28c28",
              outline="#b44d12", width=max(1, round(1.2 * s)))
    if letters:
        font = None
        for name in ("segoeuib.ttf", "arialbd.ttf", "verdanab.ttf"):
            try:
                font = ImageFont.truetype(name, round(15 * s))
                break
            except OSError:
                pass
        font = font or ImageFont.load_default()
        w = d.textlength("CC", font=font)
        d.text((32 * s - w / 2, 33 * s), "CC", font=font, fill="#ffffff", stroke_width=max(1, round(0.6 * s)),
               stroke_fill="#1d3a6b")
    return img.resize((size, size), Image.LANCZOS)


def save_icon(path: Path) -> Path:
    """The icon as a .ico, each size drawn for itself (the small ones without the letters)."""
    path.parent.mkdir(exist_ok=True)
    images = {n: icon_image(n) for n in ICON_SIZES}
    images[256].save(path, format="ICO", sizes=[(n, n) for n in ICON_SIZES],
                     append_images=[images[n] for n in ICON_SIZES if n != 256])
    return path


def login_listener(events: queue.Queue) -> None:
    """The magic link from the bot (/chatlink) opens http://127.0.0.1:47321/login?t=… in the
    browser: this answers it, on this PC only, and hands the login (if the bot really signed it)
    to the app."""
    import http.server
    import urllib.parse

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            token = urllib.parse.parse_qs(url.query).get("t", [""])[0]
            claims = guild_relay.check_login(token) if url.path == "/login" else None
            if claims:
                events.put(("login", token))
                text = (f"CustomClassic Chat is logged in as {claims['name']}. You can close this tab and type in "
                        "the Guild tab.")
            else:
                text = "That link isn't a working login (it may have run out). Type /chatlink in Discord for a new one."
            page = ("<!doctype html><meta charset=utf-8><title>CustomClassic Chat</title>"
                    "<body style='font:16px Segoe UI,sans-serif;background:#111827;color:#eef3fb;padding:40px'>"
                    f"<p>{text}</p>").encode()
            self.send_response(200 if claims else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    try:
        http.server.HTTPServer(("127.0.0.1", guild_relay.LOGIN_PORT), Answer).serve_forever()
    except OSError:
        events.put(("status", "Logins: port 47321 is taken, so /chatlink links can't reach this app."))


def start_tray(app):
    """An icon in the taskbar's notification area: left click shows or hides the panel, right
    click opens the menu. It never takes the keyboard from the game, as a taskbar button would."""
    try:
        import pystray
    except ImportError:
        return None
    send = lambda *e: (lambda icon, item: app.events.put(e))  # noqa: E731
    menu = pystray.Menu(
        pystray.MenuItem("Show / hide", send("hotkey", HK_HIDE), default=True),
        pystray.MenuItem("Move or resize…", send("hotkey", HK_EDIT)),
        pystray.MenuItem("Unlocked (place it anywhere)", send("unlock", None), checked=lambda item: app.opts["unlocked"]),
        pystray.MenuItem("Reset position", send("hotkey", HK_FIT)),
        pystray.MenuItem("Split the chat", send("split", None)),
        pystray.MenuItem("New chat window", send("window", None)),
        pystray.MenuItem("See-through", send("see_through", None), checked=lambda item: app.opts["see_through"]),
        pystray.MenuItem("Settings…", send("settings", None)),
        pystray.MenuItem("Check for updates", send("check_now", None)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", send("hotkey", HK_QUIT)),
    )
    icon = pystray.Icon("CustomClassicChat", icon_image(32), "CustomClassic Chat", menu)  # the tray shows it small
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


ERROR_LOG = HERE / "errors.log"


def log_error(text: str) -> None:
    """A problem's details, with the time and version, for a bug report (kept short)."""
    import traceback
    import updates
    try:
        old = ERROR_LOG.read_text(encoding="utf-8")[-20000:] if ERROR_LOG.exists() else ""
        ERROR_LOG.write_text(old + f"{time.strftime('%Y-%m-%d %H:%M:%S')} v{updates.VERSION} {text}\n"
                             + traceback.format_exc() + "\n", encoding="utf-8")
    except OSError:
        pass


def frame_image(frame, x0: float, y0: float, x1: float, y1: float):
    from PIL import Image
    x0, y0, x1, y1 = (max(0, int(round(v))) for v in (x0, y0, x1, y1))  # pixels: whole numbers
    crop = frame[y0:y1, x0:x1, :3][:, :, ::-1]  # BGRA -> RGB
    return Image.fromarray(crop.copy()) if crop.size else None


def find_lines(img, reader) -> tuple[dict, float] | None:
    """The chat's message area in a picture of the lower game window (left at the time stamps,
    right just before the game's scrollbar, top and bottom at the lines), and the line pitch."""
    import reader as core
    import numpy as np
    box = core.chat_box_in(img, reader)
    if not box:
        return None
    crop = img.crop((box["left"], box["top"], box["left"] + box["width"], box["top"] + box["height"]))
    old, reader.cfg.scale = reader.cfg.scale, core.FIND_SCALE
    try:
        rows = reader._ocr(crop)
    finally:
        reader.cfg.scale = old
    pitch = line_pitch(rows)
    centers = [box["top"] + (b[0] + b[1]) / 2 for b in rows]
    arr = np.asarray(img.convert("RGB"))
    right = band_right(arr, centers, box["left"], box["left"] + box["width"],
                       min(img.width, int(box["left"] + box["width"] + pitch * 30)), reader.cfg.backgrounds)
    width = (right - box["left"]) if right else box["width"] + round(pitch * 0.5)
    end = scrollbar_right(arr, centers, right) if right else None
    if end:  # the bottom from the scrollbar column: exact even when the newest line wasn't read
        bottom = chat_bottom(arr, (right + 2 * end) // 3, box["top"] + box["height"] // 2, pitch)
        if bottom and bottom > box["top"] + pitch:
            box = {**box, "height": bottom - box["top"]}
    bar = (end - right) if end else None
    if bar and not pitch * 0.8 <= bar <= pitch * 1.6:  # the game's is about 1.15 lines wide: something else was measured
        bar = None
    return {**box, "width": int(width), "bar": bar}, pitch


def scrollbar_right(arr, centers, start: int) -> int | None:
    """Where the game's scrollbar ends: right of the bands comes a thin dark divider, then the
    light track (brightness 215 to 231 across, at every scale the game draws its interface).
    On each chat row, skip the divider and follow the track; the furthest end wins (rows where
    the darker thumb sits end early). None when no track is found."""
    ends = []
    for y in centers:
        row = arr[int(y), start:start + 200].astype(int).mean(axis=1)
        i = 0
        while i < min(len(row), 12) and row[i] < 140:
            i += 1  # the dark divider
        j = i
        while j < len(row) and row[j] >= 200:
            j += 1  # the light track
        if j - i >= 6:
            ends.append(start + j)
    return int(max(ends)) if ends else None


def chat_bottom(arr, x: int, y_mid: int, pitch: float) -> int | None:
    """The chat box's bottom: going down the game's scrollbar from the middle of the chat, the
    first near-black pixel is the box's frame line, right above the typing bar. The scrollbar's
    track, thumb and arrow buttons are never that dark. Text recognition can miss the newest
    line; this can't. None when no frame line is found within reach."""
    for y in range(int(y_mid), min(arr.shape[0], int(y_mid + pitch * 20))):
        if int(arr[y, x, :3].astype(int).sum()) < 90:
            return y
    return None


def line_pitch(rows) -> float:
    """Pixels from one chat line to the next: from the first text row to the last, over the
    rows between (gaps between time stamps alone count a wrapped line twice). With one row,
    its text height plus a quarter."""
    import numpy as np
    if not rows:
        return 24.0
    height = float(np.median([b[1] - b[0] for b in rows]))
    centers = []
    for c in sorted((b[0] + b[1]) / 2 for b in rows):  # boxes on one row are one line
        if not centers or c - centers[-1] > height * 0.5:
            centers.append(c)
    if len(centers) >= 2:
        return round(float(centers[-1] - centers[0]) / (len(centers) - 1), 1)
    return round(height * 1.25, 1)


def band_right(arr, centers, left: int, start: int, stop: int, backgrounds: dict) -> int | None:
    """Where the game's scrollbar starts: megaphone bands are painted from the chat's left edge
    right up to it. Past `start`, the end of the longest line's text, no line has text any more,
    so every line on a band of a megaphone's colour (config.toml's [backgrounds]) shows nothing
    but its band until the scrollbar: the first x where they stop doing so is its edge. The
    quick-slot buttons and the rest of the screen lie beyond, so they are never reached.
    Measured in pixels, so it holds at any resolution or Windows scaling."""
    import numpy as np
    known = [c for v in backgrounds.values() for c in (v if v and isinstance(v[0], list) else [v])]
    rows = []
    for y in centers:
        row = arr[int(y), left:stop].astype(int)
        if len(row) < 20 or start - left >= len(row):
            continue
        band = np.median(row[: max(4, (start - left) // 3)], axis=0)
        if known and min(np.abs(band - np.array(c)).sum() for c in known) > 60:
            continue  # the game scene behind ordinary chat, or UI
        rows.append(np.abs(row[start - left:] - band).sum(axis=1) < 40)
    if not rows:
        return None
    good = np.mean(rows, axis=0) >= 0.8
    run = 0
    for i, ok in enumerate(good):
        run = 0 if ok else run + 1
        if run >= 3:
            return start + i - 2
    return stop


CHAR_NAME = re.compile(r"[A-Za-z0-9]{2,12}")  # MapleStory character names: letters and digits
NAME_EVERY_S = 20  # how often the status bar is read for the character's name
NAME_KNOWN_S = 90  # and once it's known


def character_name(read) -> str:
    """The character's name from the status bar under the game's chat: the line right under
    "LV. 20 Swordsman  HP[…]", e.g. QuestGuy. '' when it isn't there."""
    status = next((ln for ln in read if re.match(r"(?i)\s*lv\b", ln.text)), None)
    if status is None:
        return ""
    below = [ln for ln in read if ln.top > status.top and CHAR_NAME.fullmatch(ln.text.strip())]
    return min(below, key=lambda ln: ln.top).text.strip() if below else ""


TRACK_EVERY_S = 0.15  # how often the game's scrollbar is looked at, to follow its chat's size
RECHECK_SLOW_S = 90  # with its scrollbar in sight, how often text recognition checks the line size
BAR_GRACE_S = 3  # the scrollbar out of sight that long (the chat closed?): text recognition looks again
BAR_HIDDEN_S = 60  # gone for less than this, it's under something, most likely: its size stays meanwhile


def scrollbar_span(frame, x0: int, x1: int, seed_y: int, lo: int, hi: int) -> tuple[int, int] | None:
    """The game's scrollbar beside its chat, from its pixels alone: the left edge of its track is
    one unbroken run of neutral grey (about 200 to 225) from the top arrow down to the bottom one,
    thumb and all (blue where the pointer lights up an arrow button), and beside that run at both
    ends sit the blue arrow buttons; game scenery is practically never like that. (top, bottom) of
    that run through seed_y in the columns x0..x1 (picture pixels, a BGRA picture), the longest;
    None when there's none (the chat closed, or something over it)."""
    import numpy as np
    seg = frame[lo:hi, x0:x1, :3].astype(np.int16)
    s = seed_y - lo
    if seg.size == 0 or not 0 <= s < seg.shape[0]:
        return None
    mx, mn = seg.max(axis=2), seg.min(axis=2)
    grey = (mx - mn <= 6) & (mn >= 185) & (mx <= 240)
    wide = frame[lo:hi, x0:x1 + (x1 - x0) * 2, :3].astype(np.int16)  # and the button area beside it
    blue = (wide[:, :, 0] - wide[:, :, 2]) >= 60  # (blue minus red)
    edge = grey | blue[:, :x1 - x0]  # a lit-up arrow button is blue right to its edge: the run goes on through it
    best = None
    for j in range(grey.shape[1]):
        col = edge[:, j]
        if not col[s]:
            continue
        up = dn = s
        while up > 0 and col[up - 1]:
            up -= 1
        while dn < len(col) - 1 and col[dn + 1]:
            dn += 1
        if grey[up:dn + 1, j].sum() * 2 < dn - up + 1:  # mostly grey, or it's blue scenery
            continue
        reach = max(4, (x1 - x0) * 2)  # about one arrow button, down from the top and up from the bottom
        arrows = blue[up:up + reach, j + 1:].any() and blue[max(up, dn - reach):dn + 1, j + 1:].any()
        if arrows and dn - up >= reach and (best is None or dn - up > best[1] - best[0]):
            best = (up, dn)
    return (best[0] + lo, best[1] + lo) if best else None


def mouse_state() -> tuple[int, int, bool]:
    """Where the mouse pointer is on screen, and whether a button is held down (either one, so
    left-handed mice count too)."""
    import ctypes
    import ctypes.wintypes as wt
    u32 = ctypes.windll.user32
    pt = wt.POINT()
    u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y, bool(u32.GetAsyncKeyState(0x01) & 0x8000 or u32.GetAsyncKeyState(0x02) & 0x8000)


def pointer_near(box: tuple[int, int, int, int]) -> bool:
    """The mouse pointer on or close to a box on screen (left, top, right, bottom). The game draws
    its own pointer, so it shows in pictures of the game: over the scrollbar it hides part of it
    (the hand reaches about 30 pixels right of and below its tip)."""
    x, y, _ = mouse_state()
    left, top, right, bottom = box
    return left - 34 <= x <= right + 12 and top - 34 <= y <= bottom + 12


def dragging_on(box: tuple[int, int, int, int]) -> bool:
    """A mouse button held down with the pointer above a box's bottom and within its width: the
    game's chat being resized from its top edge, most likely (it's dragged up or down from there)."""
    x, y, held = mouse_state()
    left, _, right, bottom = box
    return held and left <= x <= right and y <= bottom


QUICK_S = 3  # after a drag on the game's chat, a new size seen in two pictures in a row is taken
STEADY_LOOKS = 25  # otherwise it has to hold this many pictures (about 10 s): a tooltip passing over
# an end of the scrollbar makes it look shorter for a moment, and that's no resize


def track_loop(app) -> None:
    """Follows the game's chat as it's resized, from its scrollbar's pixels (text recognition
    takes a second or more a look). Its size changes as its top edge is dragged: then the same
    new top and bottom in two pictures in a row moves the chat's box. Without a drag, a new size
    has to hold for seconds first, as something passing over the scrollbar looks like one.
    Pictures with the mouse pointer over the scrollbar are passed over, as it hides part of it.
    The scrollbar gone a while (the chat closed, say), the reading loop's slower checks take over."""
    last, same, looked, quick, error = None, 0, None, 0.0, ""
    keep_pace()  # light work, and the chat should follow at once
    while not app.stop.wait(TRACK_EVERY_S):
        try:
            cap, game, r = app.capture, app.game, app.read_rect
            now = time.time()
            if cap is None or not game or not r or app.want_fit or app.main.edit:
                last, quick = None, now + QUICK_S  # (just fitted afresh: the scrollbar may set it right at once)
                continue
            c, ox, oy, line, bar = game["client"], game["ox"], game["oy"], app.line, app.bar_px
            right, bottom = r["left"] + r["width"], r["top"] + r["height"]
            if dragging_on((c["left"] + r["left"], 0, c["left"] + right + bar, c["top"] + bottom)):
                quick = now + QUICK_S
            frame = cap.latest()
            if frame is None or frame is looked:  # a new picture comes every 400 ms or so: each counts once
                continue
            looked = frame
            if pointer_near((c["left"] + right, c["top"] + r["top"], c["left"] + right + bar, c["top"] + bottom)):
                if now - app.bar_at < BAR_GRACE_S:
                    app.bar_at = now  # still there, most likely: only behind the pointer
                if quick > now:
                    quick = now + QUICK_S  # a drag let go of right there: still to be followed
                last = None
                continue
            span = scrollbar_span(frame, ox + right, ox + right + max(3, bar // 2) + 2, oy + int(bottom - line * 0.5),
                                  oy, oy + min(c["height"], int(bottom + line)))
            if span is None:
                last = None
                continue
            app.bar_at = now
            if app.chat_closed:  # it's open again
                app.events.put(("chat_closed", False))
                quick = now + QUICK_S
            pad = max(1, round(line * 0.12))  # the lines' box sits a hair outside the scrollbar's
            top, bot = span[0] - oy - pad, span[1] - oy + pad
            if abs(top - r["top"]) < 3 and abs(bot - bottom) < 3:
                last, same = None, 0
            elif last == (top, bot):
                same += 1
                if same >= (1 if now < quick else STEADY_LOOKS):
                    box = {"left": r["left"], "top": top, "width": r["width"], "height": bot - top, "bar": bar}
                    app.events.put(("fit", to_relative(box, line, c)))
                    last, same = None, 0
            else:
                last, same = (top, bot), 0
        except Exception as e:
            if str(e) != error:
                error = str(e)
                log_error(f"track: {e.__class__.__name__}: {e}")


LOOK_EVERY_S = 0.2  # how often a new picture of the game is looked at: has its chat changed since it was read?
IDLE_READ_S = 15  # read the chat at least this often, changed or not
# changed: more than this share of its pixels changed by more than this. Measured on a busy chat: a
# new line changed 12% or more of them, an unchanged chat none (1%: room for a scene behind it)
CHANGE_STEP, CHANGE_SHARE = 60, 0.01
READ_STATS = CACHE_DIR / "reading.jsonl"  # what reading costs and how it keeps up, a minute a line


def chat_changed(before, now) -> bool:
    """Has the chat changed between two pictures of it (RGB, int16 arrays)? A new line moves every
    line up, which changes a lot of its pixels a lot; the game's scene behind its see-through
    background changes them a little, or few of them."""
    import numpy as np
    return float((np.abs(now - before).max(axis=2) > CHANGE_STEP).mean()) > CHANGE_SHARE


class ReadPace:
    """How soon the chat is read again after a read, when it has changed meanwhile: soon enough
    that it can't have scrolled a whole chat's worth of lines in between at the busiest rate
    assumed (or seen lately, if busier), and no sooner, so a busy chat isn't read line by line.
    A read finding half a chat of new lines, or none of the last read's (lines were missed,
    most likely), and it reads again right away for a while."""

    # lines a second assumed at the busiest. Fastest is the default: in a busy chat (a 60 s replay of
    # Kerning PQ spam) Balanced read only 12% less often and missed 3 of 47 lines more, Light read
    # 40% less often and missed 11 more; the CPU saved is in not reading an unchanged chat
    BURST = {"fastest": None, "balanced": 3.0, "light": 1.2}
    WRAP = 1.3  # long megaphones take two lines

    def __init__(self) -> None:
        self.arrivals: deque[tuple[float, int]] = deque()  # (when, new lines) of the last 30 s of reads
        self.hurry_until = 0.0

    def note(self, now: float, new: int, shown: int, gap: bool) -> None:
        self.arrivals.append((now, new))
        while self.arrivals and self.arrivals[0][0] < now - 30:
            self.arrivals.popleft()
        if gap or (shown and new >= max(2, shown / 2)):
            self.hurry_until = max(self.hurry_until, now + (60 if gap else 10))

    def rate(self, now: float) -> float:
        """New lines a second, lately."""
        if not self.arrivals:
            return 0.0
        return sum(n for _, n in self.arrivals) / max(10.0, now - self.arrivals[0][0])

    def pause(self, now: float, speed: str, shown: int, read_s: float) -> float:
        burst = self.BURST.get(speed)
        if burst is None or now < self.hurry_until or not shown:
            return 0.0
        return max(0.0, shown / (max(burst, self.rate(now) * 1.5) * self.WRAP) - read_s)


class ReadStats:
    """What reading the chat costs and how well it keeps up, a minute at a time: a line each in
    reading.jsonl (the cache folder) to compare settings by, and the last minute for Settings."""

    def __init__(self, path: Path = READ_STATS) -> None:
        self.path, self.last = path, None
        self.reset(time.time())

    def reset(self, now: float) -> None:
        self.start, self.cpu0 = now, time.process_time()
        self.looks = self.reads = self.new = self.gaps = 0
        self.read_s = 0.0

    def add(self, read_s: float | None = None, new: int = 0, gap: bool = False) -> None:
        """A look at a new picture; with read_s, it was read (taking that long)."""
        self.looks += 1
        if read_s is not None:
            self.reads, self.read_s = self.reads + 1, self.read_s + read_s
            self.new, self.gaps = self.new + new, self.gaps + gap

    def tick(self, now: float, speed: str, shown: int) -> None:
        if now - self.start < 60:
            return
        import os
        span, cpu = now - self.start, time.process_time() - self.cpu0
        self.last = {"at": time.strftime("%Y-%m-%d %H:%M"), "speed": speed, "lines_shown": shown,
                     "looks": self.looks, "reads": self.reads, "read_s": round(self.read_s, 1),
                     "cpu_cores": round(cpu / span, 2), "cpu_pct": round(cpu / span / (os.cpu_count() or 1) * 100, 1),
                     "new_lines": self.new, "gaps": self.gaps}
        try:
            self.path.parent.mkdir(exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 2_000_000:  # a week of play or so: keep the newest
                kept = self.path.read_text(encoding="utf-8").splitlines()[-6000:]
                write_atomic(self.path, "\n".join(kept) + "\n")
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(self.last) + "\n")
        except OSError:
            pass
        self.reset(now)


def read_loop(app) -> None:
    """Reads the chat from pictures of the game window; finds the chat box when asked."""
    import reader as core
    cfg = core.Config.load()
    reader, dedupe, palette = core.Reader(cfg), Dedupe(), (cfg.colors, cfg.backgrounds)
    dedupe.seed(list(app.log.messages), time.time())  # what the game's chat still shows from before a restart
    capture, hwnd, last_error = None, None, ""
    last_check, tops, watch, lost = time.time(), deque(maxlen=6), CoverWatch(), 0
    last_name, names = 0.0, deque(maxlen=3)  # the character's name: the same in the last reads wins
    shorts = deque(maxlen=2)  # a short chat's line count, as counted in the last looks
    odd = 0  # looks in a row with the lines another size than the chat's
    # reading only when the chat changed, paced to how busy it is (ReadPace)
    pace, stats, looked_at = ReadPace(), ReadStats(), None
    base, base_box, last_read, next_read, had = None, None, 0.0, 0.0, 0  # the last read: its picture, box, lines
    import numpy as np
    while not app.stop.is_set():
        t0 = time.time()
        try:
            game = app.game
            if not game:
                if capture:
                    app.capture = None
                    capture.stop()
                    capture, hwnd = None, None
            else:
                if game["hwnd"] != hwnd or (capture and capture.closed):
                    if capture:
                        capture.stop()
                    capture, hwnd = GameCapture(game["hwnd"]), game["hwnd"]
                    app.capture = capture
                frame = capture.latest()
                if frame is not None:
                    c, ox, oy = game["client"], game["ox"], game["oy"]
                    if app.want_fit:
                        top = int(c["height"] * 0.35)
                        img = frame_image(frame, ox, oy + top, ox + c["width"], oy + c["height"])
                        found = find_lines(img, reader) if img else None
                        if found:
                            box, line = found
                            tops.clear()
                            app.events.put(("fit", to_relative({**box, "top": box["top"] + top}, line, c)))
                        app.want_fit = False
                    r = app.read_rect  # client coordinates
                    speed = app.opts["reading_speed"]
                    if r and frame is not looked_at:  # (a new picture comes every 400 ms or so)
                        looked_at = frame
                        img = frame_image(frame, ox + r["left"], oy + r["top"], ox + r["left"] + r["width"],
                                          oy + r["top"] + r["height"])
                        pixels = np.asarray(img, dtype=np.int16) if img else None
                        box = (r["left"], r["top"], r["width"], r["height"])
                        moved = pixels is not None and (base is None or base.shape != pixels.shape or
                                                        chat_changed(base, pixels))
                        if img and ((moved and t0 >= next_read) or t0 - last_read >= IDLE_READ_S):
                            seen0, fresh0, w0 = dedupe.looked, dedupe.fresh, time.perf_counter()
                            read = reader.read(img)
                            read_s = time.perf_counter() - w0
                            # the game drew something over its chat: a party invite or trade request
                            # (its words land among the lines read, before the scene is left out:
                            # the pop-up isn't at the chat's left edge), the chat-type list, or a window
                            # hiding most lines. Lines read under a pop-up carry its words, so they wait
                            # until it's gone.
                            popup = any(POPUP.search(ln.text) for ln in read) or chat_menu_open(read)
                            lines = core.merge_wrapped(trim_scene(read, app.line), img.height, img.width)
                            if not popup:
                                for msg in messages_from(lines, dedupe, t0, palette, app.opts["ignore_names"]):
                                    app.events.put(("msg", msg))
                            stamped = sum(1 for ln in lines if core.TIMESTAMP.match(ln.text))
                            covered = watch.covered(stamped) or popup
                            if covered != app.covered:
                                app.events.put(("covered", covered))
                            # none of the last read's lines still there: some went by unread, most likely
                            seen, fresh = dedupe.looked - seen0, dedupe.fresh - fresh0
                            gap = box == base_box and had > 0 and seen >= 3 and fresh == seen
                            shown, now = chat_lines(r, app.line), time.time()
                            pace.note(now, fresh, shown, gap)
                            next_read = now + pace.pause(now, speed, shown, read_s)
                            base, base_box, last_read, had = pixels, box, t0, seen
                            stats.add(read_s, fresh, gap)
                        else:
                            stats.add()
                        stats.tick(t0, speed, chat_lines(r, app.line))
                        app.read_stats = stats.last
                    # who's playing: the status bar under the chat (once known, only now and then: a new
                    # character means logging out and in again)
                    if r and t0 - last_name > (NAME_KNOWN_S if app.opts["game_name"] else NAME_EVERY_S):
                        last_name = t0
                        img = frame_image(frame, ox + r["left"], oy + r["top"] + r["height"],
                                          ox + r["left"] + r["width"], oy + c["height"])
                        name = character_name(reader.read(img)) if img else ""
                        if name:
                            names.append(name)
                            if names.count(name) >= 2 and name != app.opts["game_name"]:
                                app.events.put(("character", name))
                    seen = t0 - app.bar_at < BAR_GRACE_S  # its scrollbar in sight: its size is followed from that (track_loop)
                    if r and not app.want_fit and not app.main.edit and \
                            t0 - last_check > (RECHECK_SLOW_S if seen else RECHECK_S):
                        # the game's chat resized, or its line size changed? look at a band from well
                        # above it to just below it
                        last_check, line = t0, app.line
                        x0, y0 = max(0, int(r["left"] - line)), max(0, int(r["top"] - line * 8))
                        x1 = min(c["width"], int(r["left"] + r["width"] + line))
                        y1 = min(c["height"], int(r["top"] + r["height"] + line * 0.5))
                        img = frame_image(frame, ox + x0, oy + y0, ox + x1, oy + y1)
                        found = find_lines(img, reader) if img else None
                    if r and not app.want_fit and not app.main.edit and seen and last_check == t0:
                        # with the scrollbar in sight, only the line size is checked here (the UI Size
                        # changed?): the chat's size the scrollbar tells. Off twice in a row, as a busy
                        # chat (megaphones, wrapped lines) can throw one look off
                        if found:
                            odd = odd + 1 if abs(found[1] - app.line) > app.line * 0.2 else 0
                        if odd >= 2:
                            app.want_fit, odd = True, 0
                    elif r and not app.want_fit and not app.main.edit and last_check == t0:
                        # closed completely? its newest line shows in the typing bar under it
                        bar = frame_image(frame, ox + r["left"], oy + r["top"] + r["height"],
                                          ox + r["left"] + r["width"], oy + r["top"] + r["height"] + line * 2)
                        closed = not found and bool(bar) and chat_closed(reader.read(bar))
                        if closed != app.chat_closed:
                            app.events.put(("chat_closed", closed))
                        hidden = not closed and t0 - app.bar_at < BAR_HIDDEN_S
                        if hidden:  # its scrollbar there a moment ago: something's over it (a tooltip, a
                            found = None  # window), most likely; its size stays as the scrollbar told
                        if not found and not closed and img and not hidden:  # one or two lines: find_lines can't tell
                            n = short_chat(reader.read(img), r["top"] + r["height"] - y0, r["left"] - x0,
                                           r["left"] - x0 + r["width"] * 0.6, line)
                            # only a chat too short for find_lines, and the same count twice in a row:
                            # one odd read (a band, a wrap) mustn't shrink the panel
                            shorts.append(n if 0 < n < 3 else 0)
                            if n and shorts.count(n) == 2:  # that many lines, up from its bottom
                                h = round(n * line)
                                found = ({"left": r["left"] - x0, "top": round(r["top"] + r["height"] - y0) - h,
                                          "width": r["width"], "height": h}, app.line)
                        elif found:
                            shorts.clear()
                        lost = 0 if found or closed or hidden else lost + 1
                        if found and abs(found[1] - app.line) > app.line * 0.2:
                            app.want_fit = True  # the game's UI Size changed: the lines are another size, fit afresh
                        elif found:
                            box = {**found[0], "left": found[0]["left"] + x0, "top": found[0]["top"] + y0}
                            new = resized(r, box, app.line, tops)
                            if new:
                                app.events.put(("fit", to_relative({**new, "bar": app.bar_px}, app.line, c)))
                        elif lost >= 3 and not app.covered:
                            app.want_fit, lost = True, 0  # no chat where it should be for 15 s: look for it afresh
        except Exception as e:  # keep reading through a bad frame: say so once in plain words, the
            error = f"{e.__class__.__name__}: {e}"  # details go to errors.log for a bug report
            if error != last_error:
                app.events.put(("status", "Couldn't read the game's chat for a moment; still trying. "
                                          "(Details in errors.log, if you report it.)"))
                log_error(error)
            last_error = error
        app.stop.wait(LOOK_EVERY_S)
    if capture:
        capture.stop()


DEMO = [  # kind, name, text, whisper sent?, (text colour, band colour) as measured on Windia
    ("map", "Rowan", "anyone going to Kerning?", None, ("#ffffff", None)),
    ("mega", "Kestrel", "[Selective 5-slot Coupon] S> 40K CH33 FM", None, ("#462706", "#e0ad01")),
    ("buddy", "Sunnie", "brb food", None, ("#ff9900", None)),
    ("whisper", "Nimbi", "are you still selling the claw 60?", False, ("#00ff00", None)),
    ("mega", "Tarvin", "S> 60% earring INT for 100k ch22 FM", None, ("#770042", "#ce9bb1")),
    ("party", "Corvo", "boss in 2 min, pots ready", None, (None, None)),
    ("mega", "wobbit", "[Work Gloves] c/o 120k, pm me", None, ("#09454c", "#53d0be")),
    ("mega", "Pebbles", "S> mushmom card x5 20k each ch 4", None, ("#770042", "#ce9bb1")),
    ("whisper", "Nimbi", "yes, 200k, meet at FM ch 9", True, ("#00ff00", None)),
    ("map", "Lumen", "gl everyone", None, ("#ffffff", None)),
]


def demo_loop(app) -> None:
    for kind, name, body, to, (fg, bg) in DEMO:
        if app.stop.wait(1.2):
            return
        now = time.time()
        app.events.put(("msg", {"kind": kind, "name": name, "body": body, "to": to, "at": now, "fg": fg, "bg": bg,
                                "time": time.strftime("%H:%M", time.localtime(now))}))


# ------------------------------------------------------------------ the panel


def dragged_rect(zone: str, r: dict, dx: int, dy: int, min_w: int, min_h: int) -> dict:
    """A frame moved (zone "move") or resized from the edge or corner grabbed ("n", "se" ...) by
    (dx, dy): the opposite sides stay put."""
    left, top, w, h = r["left"], r["top"], r["width"], r["height"]
    if zone == "move":
        return {"left": left + dx, "top": top + dy, "width": w, "height": h}
    if "e" in zone:
        w = max(min_w, w + dx)
    if "w" in zone:
        w2 = max(min_w, w - dx)
        left, w = left + w - w2, w2
    if "s" in zone:
        h = max(min_h, h + dy)
    if "n" in zone:
        h2 = max(min_h, h - dy)
        top, h = top + h - h2, h2
    return {"left": left, "top": top, "width": w, "height": h}


class OverlayPane:
    """One pane of an overlay frame: its row (or rows) of tabs, its messages and scrollbar, and on
    the Guild tab a line to type in. Panes stack in their frame, top down, and draw on its canvases."""

    def __init__(self, frame: "ChatFrame", conf: dict, log: "ChatLog"):
        import tkinter as tk
        self.frame, self.conf, self.log = frame, conf, log
        self.y0 = self.h = 0       # where it sits in its frame, in the frame's pixels
        self.scroll = 0            # messages scrolled up from the newest
        self.in_view = 1           # messages that fit at the last drawing
        self.bar = None            # the mouse on its scrollbar: ("thumb", grab offset) / ("repeat", part)
        self.repeat_id = None
        self.warn_band = 0         # the bottom of the warning across its top, when there is one
        self.typed = tk.StringVar()
        self.input = tk.Entry(frame.front.root, textvariable=self.typed, bg="#0b1120", fg=INK, insertbackground=INK,
                              relief="flat", highlightthickness=1, highlightbackground="#2a3654",
                              highlightcolor="#3d6fd1", disabledbackground="#0b1120", disabledforeground=SOFT)
        self.input.bind("<Button-1>", self.start_typing)
        self.input.bind("<Return>", self.send_typed)
        self.input.bind("<Escape>", lambda e: self.stop_typing())
        self.input.bind("<FocusOut>", lambda e: self.typing and self.input.after(150, self.check_keyboard))
        self.typing = self.placeholder = False

    app = property(lambda self: self.frame.app)
    opts = property(lambda self: self.frame.app.opts)

    @property
    def last(self) -> bool:
        """The frame's own pane, at the bottom (the others are splits above it)."""
        return self is self.frame.panes[-1]

    @property
    def first(self) -> bool:
        """The top pane shown: its tab row carries the frame's buttons and corner grip."""
        return self is next((p for p in self.frame.panes if p.h), self.frame.panes[-1])

    # where things are, in the frame's pixels ------------------------------------------

    def strip_rows(self, width: int) -> int:
        return 1 + max((row for *_, row in self.tab_spans(width)), default=0)

    def strip_h(self) -> int:
        return strip_height(self.app.line) * self.strip_rows(self.frame.width)

    def msgs_top(self) -> int:
        return self.y0 + self.strip_h()

    def msgs_bottom(self) -> int:
        return self.y0 + self.h - (0 if self.last else ChatFrame.DIV)

    def buttons(self, width: int) -> list[tuple[str, int, int]]:
        """On the top pane's first row, left to right after the ≡: ◐, and the ⚠ when there is one
        (at the left end, well away from the game chat's resize edge and the corner grip)."""
        if not self.first:
            return []
        f = self.frame
        rh = strip_height(self.app.line)
        s, x = rh - 4, rh + 4
        out = []
        for name in ["see"] + (["warn"] if f.warning() else []):
            out.append((name, x, x + s))
            x += s + 4
        return out

    def tab_spans(self, width: int) -> list[tuple[str, int, int, int]]:
        """The tabs as (name, x0, x1, row): the first row after the ≡ and the buttons, and before
        the corner grip, and when the pane is too narrow for them all, the rest on more rows under it."""
        rh, pad = strip_height(self.app.line), 10
        buttons, f = self.buttons(width), self.frame
        first_end = width - 4 - (f.corner_px() + 4 if self.first and f.can_resize() else 0)
        x, row, out = (max(x1 for *_, x1 in buttons) + 6 if buttons else rh + 6), 0, []  # after the ≡ and buttons
        for name, _ in self.log.tabs:
            w = self.app.tab_font.measure(name) + 2 * pad
            end = first_end if row == 0 else width - 4
            if x + w > end and out and out[-1][3] == row:  # no room left on this row: the next one
                row, x = row + 1, 6
            out.append((name, x, x + w, row))
            x += w + 3
        return out

    def pick_tab(self, x: int, y: int) -> None:
        """A click on its tab row at (x, y), y from the pane's top."""
        row = int(y // strip_height(self.app.line))
        for name, x0, x1, r in self.tab_spans(self.frame.width):
            if x0 <= x < x1 and r == row:
                self.log.select(name)
                self.scroll = 0
                self.conf["tab"] = name
                self.frame.save_panes()
        self.app.render()

    # drawing ------------------------------------------------------------------------

    def draw(self, fc, bc, solid: bool) -> None:
        """This pane on its frame's canvases: fc in front (its text), bc behind (its backgrounds,
        which fade; the same canvas as fc unless the text is kept solid)."""
        if self.h <= 0:
            self.input.place_forget()
            return
        app, f, w = self.app, self.frame, self.frame.width
        rh, sh, y0 = strip_height(app.line), self.strip_h(), self.y0
        # the tab row(s): the ≡ for the menu, on the top pane ◐ and ⚠, the tabs, and the corner grip
        bc.create_rectangle(0, y0, w, y0 + sh, fill=STRIP, outline="")
        g = rh - 4
        bc.create_rectangle(4, y0 + 2, 4 + g, y0 + rh - 2, fill=TAB, outline="")
        for i in (-1, 0, 1):
            y = y0 + rh // 2 + 1 + i * max(3, rh // 6)
            fc.create_line(8, y, g, y, fill=SOFT, width=2)
        for name, x0, x1, row in self.tab_spans(w):
            on, y = name == self.log.tab, y0 + row * rh
            bc.create_rectangle(x0, y + 2, x1, y + rh, fill=TAB_ON if on else TAB, outline="")
            fc.create_text((x0 + x1) // 2, y + rh // 2 + 1, text=name, fill=INK if on else SOFT, font=app.tab_font)
            if self.log.unread.get(name):
                r = max(3, rh // 6)
                fc.create_oval(x1 - 2 * r - 2, y + 3, x1 - 2, y + 3 + 2 * r, fill=GOLD if name == "Watch" else DOT,
                               outline="")
        for name, x0, x1 in self.buttons(w):
            if name == "warn":  # quiet: an amber mark; a click puts the warning away
                fc.create_text((x0 + x1) // 2, y0 + rh // 2 + 1, text="⚠", fill=WARN, font=app.tab_font)
                continue
            on = f.see_through
            bc.create_rectangle(x0, y0 + 2, x1, y0 + rh - 2, fill=TAB_ON if on else TAB, outline="")
            fc.create_text((x0 + x1) // 2, y0 + rh // 2 + 1, text="◐", fill=INK if on else SOFT, font=app.tab_font)
        if self.first and f.can_resize() and not f.edit:  # the corner grip: three diagonal strokes
            x1, s = w - 4, f.corner_px()
            for k in (0.3, 0.6, 0.9):
                fc.create_line(x1 - s * k, y0 + 3, x1, y0 + 3 + s * k, fill=SOFT, width=2)
        # the messages, newest at the bottom, over the typing line on the Guild tab
        top, bottom = self.msgs_top(), self.msgs_bottom()
        b, pad = f.bar_px, 6
        shown = self.log.visible()
        end = len(shown) - self.scroll
        warn = f.warning() if self.first else None  # across the top pane: the game's chat too small, or closed
        warn_h = (app.tab_font.metrics("linespace") + 8) if warn else 0
        if warn and f.collapsed():  # the game's chat closed: that's all there is to say
            shown, warn_h = [], bottom - top
        self.warn_band = top + warn_h
        y, fits = bottom - 2 - self.input_height(), 0
        for m in reversed(shown[:max(0, end)]):
            star = "★ " if m.get("watch") and self.log.tab != "Watch" else ""
            t = fc.create_text(pad, 0, anchor="nw", text=star + line_text(m, self.opts["timestamps"]),
                               fill=self.opts["colors"].get(m["kind"]) or m.get("fg") or COLORS[m["kind"]],
                               font=app.font, width=w - 2 * pad - b)
            th = fc.bbox(t)[3]
            if y - th < top + warn_h:  # no room for all of it: the pane ends here
                fc.delete(t)
                break
            fc.move(t, 0, y - th)
            if m.get("bg"):  # a megaphone's band, as the game draws it: solid with its text, which is dark
                fc.tag_lower(fc.create_rectangle(0, y - th, w - b - 1, y, fill=m["bg"], outline=""), t)
            elif solid:  # a shadow, so solid text reads over whatever shows through behind it
                shade = fc.create_text(pad + 1, y - th + 1, anchor="nw", text=fc.itemcget(t, "text"), fill=SHADOW,
                                       font=app.font, width=w - 2 * pad - b)
                fc.tag_lower(shade, t)
            if m.get("watch"):  # caught by the watch list: a gold edge
                fc.create_rectangle(0, y - th, 2, y - 1, fill=GOLD, outline="")
            y -= th
            fits += 1
        self.in_view = max(1, fits)
        if warn:
            fc.create_rectangle(0, top, w - b - 1, top + warn_h, fill=WARN, outline="")
            fc.create_text(pad, top + 3, anchor="nw", text="⚠ " + warn, fill="#1a1205", font=app.tab_font,
                           width=w - 2 * pad - b)
        self.draw_scrollbar(bc, w, top, bottom, b, len(shown))
        self.place_input()

    def draw_scrollbar(self, c, w: int, top: int, bottom: int, b: int, total: int) -> None:
        """The game's scrollbar, lying over the game's own: a dark divider, a light track, arrow
        buttons at both ends and a thumb to drag."""
        h = bottom - top
        divider = max(1, round(b / 6))
        c.create_rectangle(w - b, top, w - b + divider - 1, bottom - 1, fill="#1a1f2a", outline="")
        x0, b = w - b + divider, b - divider  # the track: arrows and thumb are as wide as it
        c.create_rectangle(x0, top, w - 1, bottom - 1, fill=SB_TRACK, outline=SB_EDGE)
        for y0, up in ((top, True), (bottom - b, False)):
            c.create_rectangle(x0, y0, w - 1, y0 + b - 1, fill=SB_BUTTON, outline=SB_EDGE)
            m, a = x0 + b / 2, b * 0.28
            pts = (m - a, y0 + b * 0.62, m + a, y0 + b * 0.62, m, y0 + b * 0.36) if up else \
                (m - a, y0 + b * 0.38, m + a, y0 + b * 0.38, m, y0 + b * 0.64)
            c.create_polygon(*pts, fill=SB_ARROW, outline="")
        t, size = thumb(total, self.in_view, self.scroll, h, b)
        if total > self.in_view:
            c.create_rectangle(x0 + 2, top + t, w - 3, top + t + size - 1, fill=SB_THUMB, outline=SB_EDGE)

    # scrolling, like the game's chat -------------------------------------------------

    def scroll_to(self, scroll: int) -> None:
        most = max(0, len(self.log.visible()) - max(1, self.in_view))
        self.scroll = max(0, min(most, scroll))

    def wheel(self, delta: int) -> None:
        self.scroll_to(self.scroll + max(1, abs(delta) // 120) * (1 if delta > 0 else -1))
        self.frame.render()

    def bar_hit(self, y: int) -> str:
        """Which part of the scrollbar is at frame height y: up, down, thumb, page_up or page_down."""
        b, top, bottom = self.frame.bar_px, self.msgs_top(), self.msgs_bottom()
        if y < top + b:
            return "up"
        if y >= bottom - b:
            return "down"
        t, size = thumb(len(self.log.visible()), self.in_view, self.scroll, bottom - top, b)
        return "thumb" if top + t <= y < top + t + size else ("page_up" if y < top + t else "page_down")

    def step(self, part: str) -> None:
        """One step of a held arrow or track click; repeats while the button is held, like the game's."""
        n = {"up": 1, "down": -1, "page_up": max(1, self.in_view - 1), "page_down": -max(1, self.in_view - 1)}[part]
        self.scroll_to(self.scroll + n)
        self.frame.render()
        self.repeat_id = self.frame.front.root.after(350 if self.repeat_id is None else 70, self.step, part)

    def press(self, x: int, y: int) -> None:
        """A press on its messages, at frame (x, y): the warning (puts it away) or the scrollbar."""
        w, b = self.frame.width, self.frame.bar_px
        if y < self.warn_band and x < w - b:
            self.frame.dismiss_warning()
            return
        if x >= w - b:
            part = self.bar_hit(y)
            if part == "thumb":
                t, _ = thumb(len(self.log.visible()), self.in_view, self.scroll, self.msgs_bottom() - self.msgs_top(), b)
                self.bar = ("thumb", y - self.msgs_top() - t)
            else:
                self.bar, self.repeat_id = ("repeat", part), None
                self.step(part)

    def drag_thumb(self, y: int) -> None:
        b, total, h = self.frame.bar_px, len(self.log.visible()), self.msgs_bottom() - self.msgs_top()
        _, size = thumb(total, self.in_view, self.scroll, h, b)
        self.scroll_to(scroll_at(y - self.msgs_top() - self.bar[1], total, self.in_view, h, b, size))
        self.frame.render()

    def release(self) -> None:
        if self.repeat_id is not None:
            self.frame.front.root.after_cancel(self.repeat_id)
        self.bar, self.repeat_id = None, None

    # the typing line (the Guild tab) ---------------------------------------------------

    def input_shown(self) -> bool:
        return self.log.tab == "Guild" and getattr(self.app, "relay", None) is not None and not self.frame.collapsed()

    def input_height(self) -> int:
        return max(20, round(self.app.line * 1.2)) if self.input_shown() else 0

    def place_input(self) -> None:
        if not self.input_shown() or self.h <= 0:
            self.input.place_forget()
            return
        app = self.app
        logged = guild_relay.check_login(self.opts["guild_login"]) if self.opts["guild_login"] else None
        game = app.game_name()
        me = guild_relay.who(game, logged["name"]) if logged and game else (logged["name"] if logged else game)
        self.input.configure(font=app.font, state="normal" if me else "disabled")
        if not self.typing and (not self.typed.get() or self.placeholder):
            self.input.configure(fg=SOFT)
            self.typed.set(f"Message the guild as {me}… (click, type, Enter)" if me else
                           "Your character's name is read from the game's status bar…")
            self.placeholder = True
        ih = self.input_height()
        self.input.place(x=0, y=self.msgs_bottom() - ih, width=self.frame.width - self.frame.bar_px, height=ih)

    def start_typing(self, e=None) -> None:
        if str(self.input.cget("state")) == "disabled":
            return
        if self.placeholder:
            self.typed.set("")
            self.placeholder = False
        self.input.configure(fg=INK)
        self.typing = True
        self.frame.front.take_keyboard()  # the keyboard comes here until Enter, Esc or a click elsewhere
        self.input.focus_force()
        self.input.after(120, lambda: self.check_keyboard(handing_over=True))

    def check_keyboard(self, handing_over: bool = False) -> None:
        """Tk says FocusOut for moves inside the app too, and while Windows hands the keyboard
        over: only a keyboard that really went to another window (a click on the game) ends the
        typing. Right after the click, a late hand-over is asked for once more instead."""
        if not self.typing:
            return
        if self.frame.front.has_keyboard():
            if self.input.focus_get() is not self.input:
                self.input.focus_force()
        elif handing_over:
            self.frame.front.take_keyboard()
            self.input.focus_force()
        else:
            self.stop_typing(refocus=False)  # the keyboard is where the user clicked: leave it there

    def stop_typing(self, refocus: bool = True) -> None:
        if not self.typing:
            return
        self.typing = False
        self.frame.front.give_back(refocus)  # and goes back to the game
        if not self.typed.get():
            self.place_input()

    def send_typed(self, e=None) -> None:
        text = self.typed.get().strip()
        if text and self.app.relay:
            problem = self.app.relay.say_chat(text)
            if problem:
                self.app.events.put(("status", f"Not sent: {problem}."))
            else:
                self.typed.set("")
        self.stop_typing()


class ChatFrame:
    """A chat overlay on the game: one window (and a backdrop behind it, for solid text) holding one
    or more panes stacked top down, each with its own tabs. The main chat is one, anchored on the
    game's chat box (or wherever it was unlocked to); extra overlays are others, each wherever it
    was put. Moving or resizing moves or resizes the whole frame; splitting adds a pane inside it."""

    DIV = 7          # the bar between two panes: drag it to share the room
    EDGE = 12        # how close to an edge a press resizes rather than moves, while adjusting
    BAR_SLOP = 4     # pixels a press on the tab row moves up or down before it's a resize
    MAX_PANES = 5
    CURSORS = {"move": "fleur", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow",
               "w": "sb_h_double_arrow", "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw"}

    def __init__(self, app, conf: dict, main: bool = False):
        overlay = app.overlay
        self.app, self.conf, self.main = app, conf, main
        title = "CustomClassic Chat" if main else "CustomClassic Chat window"
        self.front = overlay.Overlay(title, 40, 40, 400, 100, master=None if main else app.root, click_through=False)
        # the backdrop: with solid text, the backgrounds are drawn here and fade, while the window in
        # front stays solid on a see-through background. Clicks between the lines land here too.
        self.back = overlay.Overlay(f"{title} backdrop", 40, 40, 400, 100, master=self.front.root, click_through=False)
        self.back.below = self.front
        self.back.keep_on_top(again=False)
        self.back.show(False)
        self.front.behind.append(self.back)  # back behind the front whenever that's raised
        self.front.own_by(self.back)  # and Windows keeps an owned window in front of its owner, always
        for w in (self.front, self.back):
            c = w.canvas
            c.bind("<ButtonPress-1>", self.on_press)
            c.bind("<B1-Motion>", self.on_drag)
            c.bind("<ButtonRelease-1>", self.on_release)
            c.bind("<Motion>", self.on_motion)
            c.bind("<MouseWheel>", self.on_wheel)
            c.bind("<ButtonRelease-3>", self.on_menu)  # on release: letting go can't pick an item
        for event in ("<ButtonPress>", "<ButtonRelease>"):  # a click raises the clicked window: back behind
            self.back.canvas.bind(event, lambda e: self.restack(), add="+")
        self.handle = None         # the ◐ to click see-through off again (the frame lets clicks through then)
        self.rect = None           # where it was last put, on screen
        self.edit = False          # moving and resizing
        self.visible = False
        self.drag = self.grip = self.div_drag = self.bar_press = self.menu_on_release = None
        if main:  # the main chat: its own pane's tab in opts["tab"], its splits in opts["main_panes"]
            self.own = {"tab": app.opts["tab"]}
            uppers = app.opts.setdefault("main_panes", [])
        else:
            conf.setdefault("id", uuid.uuid4().hex[:12])
            self.own, uppers = conf, conf.setdefault("panes", [])
        self.panes = [OverlayPane(self, c, app.log.view_of(c.get("tab") or "Mega")) for c in uppers]
        self.panes.append(OverlayPane(self, self.own, app.log if main else app.log.view_of(conf.get("tab") or "All")))

    opts = property(lambda self: self.app.opts)

    @property
    def width(self) -> int:
        return int(self.rect["width"]) if self.rect else self.front.width

    @property
    def bar_px(self) -> int:
        """Its scrollbars' width: the main chat's as wide as the game's own, which it lies over."""
        return self.app.bar_px if self.main else bar_width(self.app.line)

    @property
    def see_through(self) -> bool:
        return bool(self.opts["see_through"] if self.main else self.conf.get("see_through"))

    @property
    def closable(self) -> bool:
        return not self.main

    def movable(self) -> bool:
        """Moved and resized freely: an extra overlay, or the main chat once unlocked (on the game's
        chat box it stays there, sized by the game's chat)."""
        return bool(self.opts["unlocked"]) if self.main else True

    is_free = property(movable)

    def can_resize(self) -> bool:
        return self.movable()

    def can_split(self) -> bool:
        return len(self.panes) < self.MAX_PANES

    def corner_px(self) -> int:
        return strip_height(self.app.line) - 4 if self.can_resize() else 0

    def in_corner(self, x: int, y: int) -> bool:
        """(x, y) on the corner grip, at the right end of the top pane's first row (y from its top)."""
        return self.can_resize() and x >= self.width - self.corner_px() - 4 and y < strip_height(self.app.line)

    def warning(self) -> str | None:
        return self.app.warning()

    def dismiss_warning(self) -> None:
        self.app.dismiss_warning()
        self.app.render()

    def collapsed(self) -> bool:
        """The main chat with the game's chat closed: one line saying so."""
        return self.main and self.app.chat_closed and bool(self.app.warning())

    def least(self) -> int:
        """The smallest a pane gets: its tab row, two lines and a divider."""
        return 2 * round(self.app.line) + strip_height(self.app.line) + self.DIV

    def typing(self) -> bool:
        return any(p.typing for p in self.panes)

    def busy(self) -> bool:
        """Being moved or resized by hand right now: nothing else puts it anywhere meanwhile."""
        return bool(self.grip or self.drag or self.div_drag)

    # the panes ------------------------------------------------------------------------

    def save_panes(self) -> None:
        if self.main:
            self.opts["tab"] = self.panes[-1].conf["tab"] if self.panes[-1].conf.get("tab") else self.opts["tab"]
            self.opts["main_panes"] = [p.conf for p in self.panes[:-1]]
        else:
            self.conf["panes"] = [p.conf for p in self.panes[:-1]]
        save_settings(self.opts)

    def heights(self, height: int) -> list[int]:
        """Each pane's height, top down: the splits their share of the frame (as last set), the
        frame's own pane the rest; when they don't all fit, the splits smaller alike."""
        n = len(self.panes)
        if self.collapsed():
            return [0] * (n - 1) + [height]
        least = self.least()
        if height < least * n:  # too small for them all to have their least: alike, then
            even = height // n
            return [even] * (n - 1) + [height - even * (n - 1)]
        want = [max(least, round(height * p.conf["share"]) if p.conf.get("share") else int(p.conf.get("height") or 120))
                for p in self.panes[:-1]]
        room = height - least
        if want and sum(want) > room:
            scale = max(0.0, room - least * len(want)) / max(1, sum(want) - least * len(want))
            want = [least + int((h - least) * scale) for h in want]
        return want + [height - sum(want)]

    def layout(self) -> None:
        y = 0
        for p, h in zip(self.panes, self.heights(self.rect["height"])):
            p.y0, p.h = y, h
            y += h

    def add_pane(self) -> None:
        """Split it: a new pane on top (Mega to start with, so megaphones sit above the chat); the
        frame keeps its size, and the panes share it."""
        if not self.can_split():
            self.app.events.put(("status", "That window has as many panes as fit: right-click one → Remove this split."))
            return
        height = self.rect["height"] if self.rect else 200
        h = min(round(self.app.line * 5) + 20, height // (len(self.panes) + 1))
        conf = {"tab": "Mega", "share": h / max(1, height)}
        self.panes.insert(0, OverlayPane(self, conf, self.app.log.view_of("Mega")))
        self.save_panes()
        self.app.render()
        self.app.settings_changed()

    def remove_pane(self, pane: OverlayPane) -> None:
        """A split taken away: its room goes to the panes left."""
        if pane.last:
            return
        pane.stop_typing()
        pane.input.destroy()
        self.panes.remove(pane)
        self.save_panes()
        self.app.render()
        self.app.settings_changed()

    def pane_at(self, y: int) -> OverlayPane:
        return next((p for p in self.panes if p.h and p.y0 <= y < p.y0 + p.h), self.panes[-1])

    def divider_at(self, y: int) -> int | None:
        """The pane whose divider (along its bottom) is at frame height y."""
        for i, p in enumerate(self.panes[:-1]):
            if p.h and p.y0 + p.h - self.DIV <= y < p.y0 + p.h:
                return i
        return None

    # placing ---------------------------------------------------------------------------

    def place(self, r: dict) -> None:
        """The whole frame inside r (each of its windows puts itself right if it isn't there, which
        it checks with Windows: placed again every round, a window that slipped comes back)."""
        r = {k: int(round(r[k])) for k in ("left", "top", "width", "height")}
        for w in (self.front, self.back):
            w.place(r["left"], r["top"], r["width"], r["height"])
        if r != self.rect:
            self.rect = r
            self.render()

    def placed(self) -> dict:
        return dict(self.rect) if self.rect else {"left": 40, "top": 40, "width": 400, "height": 100}

    def keep(self, r: dict) -> None:
        if self.main:
            self.opts["free"] = r
        else:
            self.conf["free"] = r
        save_settings(self.opts)

    def keep_on_screen(self, free: dict) -> dict:
        """A place put somewhere that's off every monitor (one unplugged since) comes back to the
        middle of the game window or the main screen."""
        if on_screen({**free, "height": strip_height(self.app.line)}):
            return free
        game = self.app.game
        area = game["client"] if game else {"left": 0, "top": 0, "width": self.front.root.winfo_screenwidth(),
                                            "height": self.front.root.winfo_screenheight()}
        return rescued(free, area)

    def follow(self) -> None:
        """An extra overlay: where it was put (unless it's being moved or resized right now)."""
        if not self.edit and not self.busy() and self.conf.get("free"):
            free = self.keep_on_screen(self.conf["free"])
            if free != self.conf["free"]:
                self.keep(free)
            self.place(free)

    def show(self, visible: bool) -> None:
        self.visible = visible
        self.front.show(visible or self.edit)
        self.back.show((visible or self.edit) and self.solid())
        self.update_handle()

    def restack(self) -> None:
        """The backdrop right behind the front window, now and once Windows has finished with a click."""
        self.back.keep_on_top(again=False)
        self.back.root.after(30, lambda: self.back.root.winfo_exists() and self.back.keep_on_top(again=False))

    def destroy(self) -> None:
        for p in self.panes:
            p.stop_typing()
        self.front.root.destroy()  # its backdrop, handle and typing lines with it

    # how it looks ----------------------------------------------------------------------

    def solid(self) -> bool:
        """Solid text: the text in front, its background faded on the backdrop behind it (not
        while adjusting, which shows the frame as one solid piece)."""
        return bool(self.opts["solid_text"]) and not self.edit

    def apply_see_through(self) -> None:
        """◐ on: the frame see-through and clicks going to whatever is below it (a little ◐ of its
        own stays clickable, to turn it off again)."""
        on = self.see_through and not self.edit
        solid = self.solid()
        fade = self.opts["peek_alpha"] if on else self.opts["opacity"]
        self.front.set_alpha(fade if on or not solid else 1.0)
        self.back.set_alpha(fade)
        bg = self.opts["panel_bg"] or PANEL
        self.front.canvas.configure(bg=overlay_key() if solid else bg)
        self.back.canvas.configure(bg=bg)
        self.back.show((self.visible or self.edit) and solid)
        for w in (self.front, self.back):
            w.through = on
            w.click_through(on)
        self.update_handle()

    def toggle_see_through(self) -> None:
        if self.main:
            self.opts["see_through"] = not self.opts["see_through"]
        else:
            self.conf["see_through"] = not self.conf.get("see_through")
        save_settings(self.opts)
        self.apply_see_through()
        self.render()

    def update_handle(self) -> None:
        """While see-through (clicks passing through the frame), a small ◐ over the frame's own stays
        clickable, so it can be turned off again right there."""
        want = self.see_through and not self.edit and self.visible and self.rect is not None
        if not want:
            if self.handle is not None:
                self.handle.show(False)
            return
        first = next((p for p in self.panes if p.first), self.panes[-1])
        see = next((b for b in first.buttons(self.width) if b[0] == "see"), None)
        if see is None:
            return
        if self.handle is None:
            self.handle = self.app.overlay.Overlay("CustomClassic Chat see-through", 0, 0, 10, 10,
                                                   master=self.front.root, click_through=False)
            self.handle.canvas.bind("<ButtonPress-1>", lambda e: self.toggle_see_through())
            self.app.overlay.FRONT.add(self.handle)
        rh = strip_height(self.app.line)
        _, x0, x1 = see
        y = first.y0
        c = self.handle.canvas
        c.delete("all")
        c.configure(bg=TAB_ON)
        c.create_text((x1 - x0) // 2, (rh - 4) // 2, text="◐", fill=INK, font=self.app.tab_font)
        self.handle.place(self.rect["left"] + x0, self.rect["top"] + y + 2, x1 - x0, rh - 4)
        self.handle.show(True)
        self.handle.keep_on_top(again=False)

    def render(self) -> None:
        if not self.rect:
            return
        self.layout()
        solid = self.solid()
        fc = self.front.canvas
        bc = self.back.canvas if solid else fc
        fc.delete("all")
        if bc is not fc:
            bc.delete("all")
        for p in self.panes:
            p.draw(fc, bc, solid)
        w = self.width
        for p in self.panes[:-1]:  # the dividers: drag one to move the line between two panes
            if p.h:
                y = p.y0 + p.h - self.DIV
                fc.create_rectangle(0, y, w, y + self.DIV, fill=TAB, outline="")
                for i in (-1, 0, 1):
                    x = w // 2 + i * 10
                    fc.create_line(x - 3, y + self.DIV // 2, x + 3, y + self.DIV // 2, fill=SOFT, width=2)
        if self.edit:
            self.draw_adjust(fc)
        self.update_handle()

    def draw_adjust(self, c) -> None:
        """Adjusting: a dashed outline round the whole frame, a handle in each corner, and in the
        middle what to do and how to finish."""
        w, h, s = self.rect["width"], self.rect["height"], max(10, self.EDGE)
        for coords in ((1, 1, 1, h), (w - 2, 1, w - 2, h), (0, 1, w, 1), (0, h - 2, w, h - 2)):
            c.create_line(*coords, fill=ADJUST_EDGE, width=2, dash=(6, 3))
        for x0 in (0, w - s):
            for y0 in (0, h - s):
                c.create_rectangle(x0, y0, x0 + s - 1, y0 + s - 1, fill="#ffffff", outline=ADJUST, width=2)
        t = c.create_text(w // 2, h // 2, justify="center", fill="#ffffff", font=self.app.hint_font,
                          width=max(120, w - 60),
                          text="Drag to move  ·  drag an edge or corner to resize\nRight-click → Done to keep it here")
        x0, y0, x1, y1 = c.bbox(t)
        c.tag_raise(t, c.create_rectangle(x0 - 14, y0 - 10, x1 + 14, y1 + 10, fill=ADJUST, outline="#ffffff", width=2))

    # adjusting: drag to move, any edge or corner to resize -------------------------------

    def set_edit(self, on: bool) -> bool:
        """Adjust mode on or off; True when it was just ended (time to keep the new place)."""
        if self.edit == on:
            return False
        self.edit = on
        self.front.edit = self.back.edit = on
        self.apply_see_through()  # solid while adjusting, and taking clicks
        self.show(self.visible)
        self.render()
        return not on

    def edit_zone(self, x: int, y: int) -> str:
        """Which part of the frame a press at screen (x, y) grabs: "n", "se", "w" ... or "move"."""
        r, e = self.placed(), self.EDGE

        def near(d: int) -> bool:
            return 0 <= d < e
        v = "n" if near(y - r["top"]) else ("s" if near(r["top"] + r["height"] - y) else "")
        h = "w" if near(x - r["left"]) else ("e" if near(r["left"] + r["width"] - x) else "")
        return (v + h) or "move"

    # the mouse ---------------------------------------------------------------------------

    def on_motion(self, e) -> None:
        """The pointer shows what a press would do there: move or resize while adjusting, the
        corner grip and the dividers otherwise."""
        if self.grip or self.drag or self.div_drag:
            return
        if self.edit:
            cursor = self.CURSORS[self.edit_zone(e.x_root, e.y_root)]
        elif self.divider_at(e.y) is not None:
            cursor = "sb_v_double_arrow"
        else:
            p = self.pane_at(e.y)
            cursor = "size_ne_sw" if p.first and self.in_corner(e.x, e.y - p.y0) else ""
        for w in (self.front, self.back):
            w.canvas.configure(cursor=cursor)

    def on_press(self, e) -> None:
        if self.edit:
            self.drag = (self.edit_zone(e.x_root, e.y_root), e.x_root, e.y_root, self.placed())
            return
        i = self.divider_at(e.y)
        if i is not None:
            self.div_drag = (e.y_root, i, [p.h for p in self.panes], self.placed())
            return
        p = self.pane_at(e.y)
        y = e.y - p.y0
        if y >= p.strip_h():
            p.press(e.x, e.y)
            return
        rh = strip_height(self.app.line)
        if p.first and self.in_corner(e.x, y):  # the corner grip: resize, the bottom-left corner stays
            self.grip = (e.x_root, e.y_root, self.opts["extra"], self.placed(), "corner")
            return
        if e.x < rh + 4 and y < rh:  # ≡: the menu, opened as the button is let go
            self.menu_on_release = p
            return
        for name, x0, x1 in p.buttons(self.width):
            if x0 - 2 <= e.x < x1 + 2 and y < rh:
                if name == "see":
                    self.toggle_see_through()
                else:
                    self.dismiss_warning()
                return
        # anywhere else on the tab row: dragged up or down (the top pane's) it resizes the frame from
        # the top; let go without dragging and it was a click on a tab
        self.bar_press = (p, e.x, y, e.x_root, e.y_root)

    def on_drag(self, e) -> None:
        if self.drag:
            zone, x0, y0, r = self.drag
            least = self.least()
            self.place(dragged_rect(zone, r, e.x_root - x0, e.y_root - y0, 200, least * len(self.panes)))
            return
        if self.div_drag:
            y0, i, hs, r = self.div_drag
            hs, least = list(hs), self.least()
            d = max(least - hs[i], min(hs[i + 1] - least, e.y_root - y0))
            hs[i] += d
            hs[i + 1] -= d
            for p, h in zip(self.panes[:-1], hs[:-1]):
                p.conf["share"] = h / max(1, r["height"])
                p.conf.pop("height", None)
            self.render()
            return
        press = self.bar_press
        if press and not self.grip:
            if abs(e.y_root - press[4]) < self.BAR_SLOP or not press[0].first:
                return
            self.grip = (press[3], press[4], self.opts["extra"], self.placed(), "top")
        if self.grip:
            x0, y0, extra0, r, how = self.grip
            if not self.movable():  # the main chat on the game's chat: it reaches higher, like the game's
                self.app.reach_to(extra0 + (y0 - e.y_root))
                return
            bottom = r["top"] + r["height"]
            w = r["width"] if how == "top" else max(200, r["width"] + e.x_root - x0)
            h = max(self.least() * len(self.panes), r["height"] + y0 - e.y_root)
            self.place({**r, "top": bottom - h, "height": h, "width": w})
            return
        for p in self.panes:
            if p.bar and p.bar[0] == "thumb":
                p.drag_thumb(e.y)

    def on_release(self, e) -> None:
        if self.menu_on_release is not None:
            p, self.menu_on_release = self.menu_on_release, None
            self.menu(e, p)
            return
        press, self.bar_press = self.bar_press, None
        if press and not self.grip:  # a click on a tab row, not a drag
            press[0].pick_tab(press[1], press[2])
            return
        if self.grip:
            self.grip = None
            if self.movable():
                self.keep(self.placed())
            save_settings(self.opts)
        if self.div_drag:
            self.div_drag = None
            self.save_panes()
        self.drag = None  # (adjusting: the place is kept on Done)
        for p in self.panes:
            p.release()

    def on_wheel(self, e) -> None:
        self.pane_at(e.y).wheel(e.delta)

    def on_menu(self, e) -> None:
        self.menu(e, self.pane_at(e.y))

    def menu(self, e, pane: OverlayPane) -> None:
        """Right click (or the ≡): split it, more windows, see-through, moving it, settings."""
        import tkinter as tk
        import overlay
        app = self.app
        m = tk.Menu(self.front.root, tearoff=0, bg=PANEL, fg=INK, activebackground=TAB_ON, activeforeground=INK)
        if app.adjusting():  # moving and resizing: first, the way to finish
            m.add_command(label="✓ Done: keep it here", command=lambda: app.on_hotkey(HK_EDIT))
            m.add_separator()
        if self.can_split():
            m.add_command(label="Split this window (a pane on top)", command=self.add_pane)
        if not pane.last:
            m.add_command(label="Remove this split", command=lambda: self.remove_pane(pane))
        m.add_cascade(label="New chat window", menu=app.new_window_menu(m))
        m.add_separator()
        m.add_command(label=("✓ " if self.see_through else "") + "See-through", command=self.toggle_see_through)
        if not app.adjusting() and self.movable():
            m.add_command(label="Move or resize…" + (" (Ctrl+Alt+F5)" if self.opts["adjust_hotkey"] else ""),
                          command=lambda: app.on_hotkey(HK_EDIT))
        m.add_command(label="Settings…", command=app.open_settings)
        if self.closable:
            m.add_separator()
            m.add_command(label="Close this window", command=lambda: app.close_frame(self))
        open_ = threading.Event()
        open_.set()
        threading.Thread(target=close_menu_when_left, args=(open_, float(self.opts["menu_close_s"] or 0)),
                         daemon=True).start()
        overlay.HOLD = True  # the chat windows' re-raising waits: the menu stays on top
        try:
            m.tk_popup(e.x_root + 2, e.y_root + 2)  # just off the pointer, so nothing is under it
        finally:
            overlay.HOLD = False
            open_.clear()
            m.grab_release()


class ChatPane:
    """One pane of a normal window: its own row of tabs over its messages."""

    def __init__(self, win: "NormalChat", conf: dict):
        import tkinter as tk
        self.win, self.conf, app = win, conf, win.app
        self.log = app.log.view_of(conf.get("tab") or "All")
        self.frame = tk.Frame(win.paned, bg=PANEL)
        self.bar = tk.Frame(self.frame, bg=STRIP, height=28)  # its tabs flow onto more rows when narrow
        self.bar.pack(fill="x")
        self.bar.bind("<Configure>", lambda e: self.flow())
        self.tab_buttons = []
        body = tk.Frame(self.frame, bg=PANEL)
        body.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.text = tk.Text(body, bg=app.opts["panel_bg"] or PANEL, fg=INK, wrap="word", relief="flat", padx=8,
                            pady=6, cursor="arrow", yscrollcommand=scroll.set, highlightthickness=0, height=4)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=lambda *a: (self.text.yview(*a), self.scrolled()))
        for event in ("<MouseWheel>", "<KeyRelease>", "<ButtonRelease-1>"):  # (the text's own scrolling)
            self.text.bind(event, lambda e: self.text.after_idle(self.scrolled), add="+")
        self.text.bind("<Configure>", lambda e: self.reading or self.text.see("end"))  # laid out, or resized
        for w in (self.text, self.bar):
            w.bind("<Button-3>", lambda e: win.menu(e, self))
        self.drawn = None
        self.reading = False  # scrolled up to read back: new messages keep the view where it is

    def scrolled(self) -> None:
        """Scrolled by hand: reading back unless at the newest messages again."""
        self.reading = self.text.yview()[1] < 0.999

    def pick(self, name: str) -> None:
        self.log.select(name)
        self.conf["tab"] = name
        self.reading = False
        save_settings(self.win.app.opts)
        self.render()

    def flow(self) -> None:
        """The tabs left to right, onto a new row when the next doesn't fit; the bar as tall as that."""
        width = self.bar.winfo_width()
        if width <= 1 or not self.tab_buttons:
            return
        x = y = row_h = 0
        for b in self.tab_buttons:
            w, h = b.winfo_reqwidth(), b.winfo_reqheight()
            if x and x + w > width - 2:
                x, y = 0, y + row_h + 2
            b.place(x=x + 2, y=y + 2)
            x, row_h = x + w + 2, max(row_h, h)
        height = y + row_h + 4
        if int(self.bar.cget("height")) != height:
            self.bar.configure(height=height)

    def render(self) -> None:
        import tkinter as tk
        app = self.win.app
        tabs = [name for name, _ in self.log.tabs]
        if self.drawn != (tuple(tabs), self.log.tab):  # the tab row, when it changed
            for child in self.bar.winfo_children():
                child.destroy()
            self.tab_buttons = []
            for name in tabs:
                on = name == self.log.tab
                b = tk.Button(self.bar, text=name, relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                              bg=TAB_ON if on else TAB, fg=INK if on else SOFT, activebackground=TAB_ON,
                              activeforeground=INK, font=app.tab_font, command=lambda n=name: self.pick(n))
                b.bind("<Button-3>", lambda e: self.win.menu(e, self))
                self.tab_buttons.append(b)
            self.drawn = (tuple(tabs), self.log.tab)
            self.flow()
        t = self.text
        lines = lambda index: int(t.index(index).split(".")[0])  # (one line a message)
        from_end = lines("end-1c") - lines("@0,0") if self.reading else None  # the line read, from the newest
        t.configure(state="normal", font=app.font, bg=app.opts["panel_bg"] or PANEL)
        t.delete("1.0", "end")
        for m in self.log.visible()[-NormalChat.MAX_SHOWN:]:
            fg = app.opts["colors"].get(m["kind"]) or m.get("fg") or COLORS[m["kind"]]
            tag = f"{fg}|{m.get('bg') or ''}"
            t.tag_configure(tag, foreground=fg, background=m.get("bg") or "")
            star = "★ " if m.get("watch") and self.log.tab != "Watch" else ""
            t.insert("end", star + line_text(m, app.opts["timestamps"]) + "\n", tag)
        t.configure(state="disabled")
        if from_end is None:  # the newest messages in view, as a chat does
            t.see("end")
        else:
            t.yview(f"{max(1, lines('end-1c') - from_end)}.0")


class NormalChat:
    """A chat in a regular window, with a title bar (minimise, maximise, close), to keep beside
    the game rather than on it: its own size and place, remembered between restarts. Split, it
    holds panes stacked inside it, each with its own tabs; the line between two can be dragged."""

    MAX_SHOWN = 500  # the newest messages a pane shows

    def __init__(self, app, conf: dict):
        import tkinter as tk
        self.app, self.conf = app, conf
        conf.setdefault("panes", [])  # the panes above the window's own (top first): each its tab
        top = self.top = tk.Toplevel(app.root)
        top.title("CustomClassic Chat")
        top.configure(bg=PANEL)
        try:
            top.iconbitmap(str(app.icon_path()))
        except Exception:
            pass
        top.geometry(conf.get("geometry") or "560x340+120+120")
        top.minsize(260, 140)
        top.protocol("WM_DELETE_WINDOW", lambda: app.close_normal(self))
        top.bind("<Configure>", self.moved)
        self.paned = tk.PanedWindow(top, orient="vertical", sashwidth=7, sashrelief="flat", bg=TAB, bd=0)
        self.paned.pack(fill="both", expand=True)
        self.paned.bind("<ButtonRelease-1>", lambda e: self.keep_sizes())
        self.panes = [ChatPane(self, c) for c in conf["panes"]] + [ChatPane(self, conf)]
        sizes = conf.get("sizes") or []
        for i, pane in enumerate(self.panes):
            self.paned.add(pane.frame, minsize=60, stretch="always",
                           **({"height": sizes[i]} if i < len(sizes) else {}))
        self.render()

    # what the panel hands its windows
    def logs(self) -> list:
        return [pane.log for pane in self.panes]

    @property
    def log(self):  # the window's own pane (the bottom one)
        return self.panes[-1].log

    def moved(self, e=None) -> None:
        if e is not None and e.widget is not self.top or self.top.state() != "normal":
            return
        geometry = self.top.geometry()
        if geometry != self.conf.get("geometry"):
            self.conf["geometry"] = geometry
            save_settings(self.app.opts)

    def keep_sizes(self) -> None:
        """The panes' heights, after the line between two was dragged."""
        self.conf["sizes"] = [pane.frame.winfo_height() for pane in self.panes]
        save_settings(self.app.opts)

    def render(self) -> None:
        for pane in self.panes:
            pane.render()

    def split(self) -> None:
        """A new pane on top, with Mega to start with; the window's size stays, the panes share it."""
        conf = {"tab": "Mega"}
        self.conf["panes"].insert(0, conf)
        pane = ChatPane(self, conf)
        self.panes.insert(0, pane)
        self.paned.add(pane.frame, before=self.panes[1].frame, minsize=60, stretch="always",
                       height=max(60, self.top.winfo_height() // 3))
        pane.render()
        self.top.after(50, self.keep_sizes)

    def remove(self, pane: ChatPane) -> None:
        self.paned.forget(pane.frame)
        pane.frame.destroy()
        self.panes.remove(pane)
        self.conf["panes"] = [p for p in self.conf["panes"] if p is not pane.conf]
        self.top.after(50, self.keep_sizes)

    def menu(self, e, pane: ChatPane) -> None:
        import tkinter as tk
        app = self.app
        m = tk.Menu(self.top, tearoff=0, bg=PANEL, fg=INK, activebackground=TAB_ON, activeforeground=INK)
        m.add_command(label="Split this window (a pane on top)", command=self.split)
        if pane is not self.panes[-1]:
            m.add_command(label="Remove this pane", command=lambda: self.remove(pane))
        m.add_cascade(label="New chat window", menu=app.new_window_menu(m))
        m.add_separator()
        m.add_command(label="Settings…", command=app.open_settings)
        m.add_separator()
        m.add_command(label="Close this window", command=lambda: app.close_normal(self))
        try:
            m.tk_popup(e.x_root + 2, e.y_root + 2)
        finally:
            m.grab_release()


def migrate_windows(opts: dict) -> None:
    """Splits from before frames (separate windows docked on top of another, "dock": "above") become
    panes inside the frame they were on: the main chat's in main_panes, a window's in its panes."""
    windows = opts.get("windows") if isinstance(opts.get("windows"), list) else []
    if not any(w.get("dock") == "above" for w in windows):
        opts["windows"] = windows
        return
    frames = [w for w in windows if w.get("dock") != "above"]
    by_id = {w.get("id"): w for w in frames if w.get("id")}
    main_panes = opts.setdefault("main_panes", [])
    for w in reversed(windows):  # the newest split was on top
        if w.get("dock") != "above":
            continue
        pane = {"tab": w.get("tab") or "Mega"}
        if w.get("share"):
            pane["share"] = w["share"]
        elif w.get("height"):
            pane["height"] = int(w["height"])
        host = by_id.get(w.get("host"))
        (host.setdefault("panes", []) if host is not None else main_panes).append(pane)
    opts["windows"] = frames


class ChatPanel:
    """CustomClassic Chat itself: reads the game's chat (on a thread), keeps the chat, and shows it in
    the main chat (a frame anchored on the game's chat box), in extra overlay frames and in normal
    windows. The tray icon, settings, watch list, Twitch and the guild relay hang off it."""

    def __init__(self, opts: dict, demo: bool = False, always_show: bool = False, verbose: bool = False):
        import overlay
        self.overlay, self.opts, self.demo = overlay, opts, demo
        self.always_show, self.verbose = always_show, verbose
        self.events: queue.Queue = queue.Queue()
        self.log = ChatLog(opts["history"], opts["tab"], self.tabs())
        self.log.hidden = set() if opts["system_messages"] else {"system"}
        if not isinstance(opts["hide_padded"], list):  # an on/off from before the kinds were told apart
            opts["hide_padded"] = [k for k, _ in PADDED_KINDS] if opts["hide_padded"] else []
        self.log.hide_padded = set(opts["hide_padded"])
        if not demo:  # the chat from earlier runs, within the kept hours
            now = time.time()
            prune_history(HISTORY_FILE, opts["keep_hours"], now)
            self.log.messages.extend(load_history(HISTORY_FILE, opts["keep_hours"], now))
        self.stop = threading.Event()
        self.game = None           # set here, read by the reading thread
        self.capture = None        # the game window's pictures, shared by the reading and tracking threads
        self.read_rect = None      # the chat lines in the game's client coordinates
        self.want_fit = not opts["box"]
        self.bar_at = 0.0          # when the game's scrollbar was last seen beside its chat (it's followed by its pixels)
        self.read_stats = None     # the last minute of reading the chat: what it cost, how it kept up (ReadStats)
        self.user_hidden = False
        self.line = (opts["box"] or {}).get("line") or 24.0
        self.frames, self.normal = [], []
        migrate_windows(opts)
        self.main = ChatFrame(self, {}, main=True)
        self.root = self.main.front.root
        self.dismissed = None      # the game chat's line count when the ⚠ was clicked away
        self.covered = False       # the game is drawing something over its chat: step aside
        self.chat_closed = False   # the game's chat is closed completely: say so, and stay
        self.fit_asked = 0.0
        self.edge_held = False     # the game chat's top edge grabbed, and still held: the main chat steps aside
        self.back_at = 0.0         # let go: the main chat back once its new size is seen, or by then
        self.was_held = False      # a mouse button down, last look
        self.explained = False     # the "chat too small" note, once a session
        self.settings = None
        self.settings_vars: dict = {}  # Settings window controls that change from elsewhere too
        self.set_fonts()
        self.frames = [ChatFrame(self, conf) for conf in opts["windows"]]
        self.normal = [NormalChat(self, conf) for conf in opts["normal_windows"]]
        CACHE_DIR.mkdir(exist_ok=True)
        self.chime = CACHE_DIR / f"whisper_{int(opts['volume'] * 100)}.wav"
        if not self.chime.exists():
            make_chime(self.chime, [987.8, 1318.5], max(0.0, min(1.0, opts["volume"])))
        self.watch_chime = CACHE_DIR / f"watch_{int(opts['volume'] * 100)}.wav"  # three rising notes: not a whisper
        if not self.watch_chime.exists():
            make_chime(self.watch_chime, [1046.5, 1318.5, 1568.0], max(0.0, min(1.0, opts["volume"])))
        import watch
        self.watch = watch
        self.watcher = watch.Watcher(watch.load_entries(opts["watch"]), kinds=self.watch_kinds())
        self.toast = None
        threading.Thread(target=self.load_names, daemon=True).start()
        self.twitch = None
        self.start_twitch()
        if not opts.get("relay_reader"):
            opts["relay_reader"] = guild_relay.reader_id()
            save_settings(opts)
        self.relay = None
        self.start_relay()
        self.update_note = None
        if not demo:
            threading.Thread(target=login_listener, args=(self.events,), daemon=True).start()
            self.root.after(15000, self.check_updates)
        threading.Thread(target=overlay.hotkey_thread, args=(self.events, HOTKEYS), daemon=True).start()
        self.adjust_key_taken = False
        if opts["adjust_hotkey"]:
            self.take_adjust_key()
        threading.Thread(target=demo_loop if demo else read_loop, args=(self,), daemon=True).start()
        if not demo:
            threading.Thread(target=track_loop, args=(self,), daemon=True).start()
        self.tray = start_tray(self)
        if demo:  # no game: a 4-line chat near the bottom of the main screen
            w, h = 900, round(self.line * 4)
            self.main.place({"left": (self.root.winfo_screenwidth() - w) // 2,
                             "top": self.root.winfo_screenheight() - h - 160, "width": w, "height": h})
            self.main.show(True)
        self.root.after(100, self.pump)
        self.root.after(300, self.follow)
        if not demo:
            self.root.after(40, self.watch_edge)
        self.apply_see_through()
        self.render()

    # the chat windows, together ---------------------------------------------------------

    def all_frames(self) -> list:
        return [self.main, *self.frames]

    def overlay_panes(self) -> list:
        return [p for f in self.all_frames() for p in f.panes]

    @property
    def scroll(self) -> int:  # the main chat's own pane
        return self.main.panes[-1].scroll

    @scroll.setter
    def scroll(self, value: int) -> None:
        self.main.panes[-1].scroll = value

    def watch_kinds(self) -> tuple:
        return ("mega", "map") if self.opts["watch_map"] else ("mega",)

    def load_names(self) -> None:
        """Item names for the watch list, from the price server, every hour."""
        while not self.stop.is_set():
            self.watcher.catalog = self.watch.Catalog.load(self.opts["names_url"] or self.watch.NAMES_URL)
            if self.stop.wait(self.watch.NAMES_EVERY):
                return

    def save_watch(self, entries: list) -> None:
        self.watcher.entries = entries
        self.opts["watch"] = [e.to_dict() for e in entries]
        save_settings(self.opts)

    def watched(self, msg: dict) -> None:
        """Mark a message the watch list catches, and chime and pop up a note for it."""
        hits = self.watcher.check(msg, msg.get("at"))
        if not hits:
            return
        msg["watch"] = [why for _, why in hits]
        if self.opts["watch_sound"]:
            import winsound
            try:
                winsound.PlaySound(str(self.watch_chime), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except RuntimeError:
                pass
        if self.opts["watch_popup"]:
            self.pop_up(msg)

    def pop_up(self, msg: dict) -> None:
        """A note just above the main chat for 12 seconds; clicking it opens the Watch tab."""
        if self.toast is not None:
            self.toast.root.destroy()
        p = self.main.placed()
        w = max(300, min(560, p["width"] - 20))
        t = self.toast = self.overlay.Overlay("CustomClassic Chat watch", p["left"] + 10, 0, w, 10, master=self.root,
                                              click_through=False)
        c = t.canvas
        c.configure(bg="#2a2208")
        head = c.create_text(10, 8, anchor="nw", text="★ " + "; ".join(msg["watch"]), fill=GOLD, font=self.tab_font,
                             width=w - 20)
        y = c.bbox(head)[3] + 4
        body = c.create_text(10, y, anchor="nw", text=line_text(msg, "off"), fill=INK, font=self.font, width=w - 20)
        h = c.bbox(body)[3] + 10
        c.create_rectangle(0, 0, w - 1, h - 1, outline=GOLD)
        t.place(p["left"] + 10, max(0, p["top"] - h - 8), w, h)
        t.show(True)

        def close(_=None, open_tab=False):
            if self.toast is t:
                self.toast = None
            t.root.destroy()
            if open_tab:
                self.log.select("Watch")
                self.scroll = 0
                self.render()
        c.bind("<ButtonPress-1>", lambda e: close(open_tab=True))
        t.root.after(12000, lambda: t.root.winfo_exists() and close())

    UPDATE_EVERY_MS = 12 * 3600 * 1000

    def check_updates(self, again: bool = True, tell: bool = False) -> None:
        """Ask GitHub, on a thread, whether a newer version is out (at start, then twice a day while
        the setting is on). tell: say so even when this one is the newest (asked from the tray)."""
        import updates
        if tell or self.opts["update_check"]:
            def ask():
                found = []
                updates.check(found.append)
                if found:
                    self.events.put(found[0])
                elif tell:
                    self.events.put(("status", f"CustomClassic Chat {updates.VERSION} is the newest version."))
            threading.Thread(target=ask, daemon=True).start()
        if again:
            self.root.after(self.UPDATE_EVERY_MS, self.check_updates)

    def show_update(self, version: str, page: str) -> None:
        """A note above the main chat until it's answered: the version here and the new one, a link
        to download it from GitHub, and Later (until the app starts again)."""
        import updates
        import webbrowser
        if self.update_note is not None and self.update_note.root.winfo_exists():
            return
        p = self.main.placed()
        w = max(300, min(460, p["width"] - 20))
        t = self.update_note = self.overlay.Overlay("CustomClassic Chat update", p["left"] + 10, 0, w, 10,
                                                    master=self.root, click_through=False)
        c = t.canvas
        c.configure(bg="#10213f")
        head = c.create_text(10, 8, anchor="nw", text="An update is available", fill=INK, font=self.hint_font,
                             width=w - 20)
        y = c.bbox(head)[3] + 4
        body = c.create_text(10, y, anchor="nw", fill=SOFT_INK, font=self.font, width=w - 20,
                             text=f"Your version {updates.VERSION}  ·  new version {version}")
        y = c.bbox(body)[3] + 10
        buttons = []
        x = 10
        for text, fill in (("Download", ADJUST), ("Later", "#2a3654")):
            label = c.create_text(x + 12, y + 5, anchor="nw", text=text, fill=INK, font=self.tab_font)
            x0, y0, x1, y1 = c.bbox(label)
            box = c.create_rectangle(x0 - 12, y0 - 5, x1 + 12, y1 + 5, fill=fill, outline="")
            c.tag_raise(label, box)
            buttons.append((text, (x0 - 12, y0 - 5, x1 + 12, y1 + 5)))
            x = x1 + 24
        h = buttons[0][1][3] + 10
        c.create_rectangle(0, 0, w - 1, h - 1, outline=ADJUST_EDGE)
        t.place(p["left"] + 10, max(0, p["top"] - h - 8), w, h)
        t.show(True)

        def click(e):
            for text, (x0, y0, x1, y1) in buttons:
                if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                    if text == "Download":
                        webbrowser.open(page)
                    if self.update_note is t:
                        self.update_note = None
                    t.root.destroy()
        c.bind("<ButtonPress-1>", click)

    @property
    def bar_px(self) -> int:
        """The game's scrollbar's width: as measured (divider and track), or a guess."""
        return int((self.opts["box"] or {}).get("bar") or bar_width(self.line))

    def auto_px(self) -> int:
        return max(11, round(self.line * 0.62))  # about the game's own chat text

    def set_fonts(self) -> None:
        import tkinter.font as tkfont
        family = self.opts["font_family"] if self.opts["font_family"] in dict(FONTS) else FONT
        self.font = tkfont.Font(family=family, size=-(self.opts["font_px"] or self.auto_px()),
                                weight="bold" if self.opts["font_bold"] else "normal")
        self.tab_font = tkfont.Font(family=FONT, size=-max(10, round(self.line * 0.5)))
        self.hint_font = tkfont.Font(family=FONT, size=-max(13, round(self.line * 0.85)), weight="bold")

    def warning(self) -> str | None:
        """Why lines may slip by, if they may: the game's chat is closed, or shows fewer than 3
        lines (a long megaphone takes two). Clicking the ⚠ (or the warning) puts it away until
        the chat changes again."""
        if self.chat_closed:
            return None if self.dismissed == "closed" else "The game's chat is closed: open it so it can be read"
        n = chat_lines(self.read_rect, self.line)
        if self.read_rect and n < self.opts["min_lines"] and n != self.dismissed:
            return (f"The game's chat shows only {n} line{'s' if n != 1 else ''}: make it at least 3 lines tall "
                    "(4 or more is best)")
        return None

    def explain(self, reason: str) -> None:
        self.events.put(("status", f"⚠ {reason}. Megaphones arriving together may scroll away unread "
                                   "otherwise. Click the warning to hide it."))

    def dismiss_warning(self) -> None:
        # the ⚠ (or the warning) clicked: put away for this chat size, or while it's closed
        self.dismissed = "closed" if self.chat_closed else chat_lines(self.read_rect, self.line)

    # the main chat on the game's chat box --------------------------------------------------

    @property
    def is_free(self) -> bool:
        return bool(self.opts["unlocked"])

    def reach(self, full: dict) -> dict:
        """Higher than the game's chat by what its top bar was dragged up (0: just under the
        chat's top edge, which then stays free for resizing the game's chat itself)."""
        extra = max(0, int(self.opts["extra"]))
        return {**full, "top": full["top"] - extra, "height": full["height"] + extra}

    def main_rect(self, rect: dict) -> dict:
        """The main chat on the game's chat (rect, on screen): just under its top edge (or higher,
        as dragged); with the game's chat closed, one line right above the typing bar."""
        full = self.reach(anchored(rect, self.line, self.bar_px))
        if self.chat_closed and self.warning():
            h = strip_height(self.line) + round(self.line * 1.6)
            full = {**full, "top": full["top"] + full["height"] - h, "height": h}
        return full

    def reach_to(self, extra: int) -> None:
        """The main chat's top bar dragged on the game's chat: it reaches that much higher."""
        if self.read_rect and self.game:
            c = self.game["client"]
            top_room = c["top"] + self.read_rect["top"]  # up to the top of the screen
            self.opts["extra"] = max(0, min(top_room, int(extra)))
            rect = {**self.read_rect, "left": c["left"] + self.read_rect["left"], "top": c["top"] + self.read_rect["top"]}
            self.main.place(self.main_rect(rect))

    def free_rect(self) -> dict:
        """Where an unlocked main chat sits: where it was put, or back in view if that's off every monitor."""
        free = self.opts["free"] or self.main.placed()
        kept = self.main.keep_on_screen(free)
        if kept != free:
            self.main.keep(kept)
        return kept

    def render(self) -> None:
        """Every chat window: overlays and normal windows (which follow the main chat's settings
        for what they leave out). A tab open somewhere is in view: no unread dot for it elsewhere."""
        panes = self.overlay_panes() + [p for w in self.normal for p in w.panes]
        shown = {p.log.tab for p in panes}
        for p in panes:
            for name in shown:
                if name in p.log.unread:
                    p.log.unread[name] = False
            if p.log is not self.log:
                p.log.hidden, p.log.hide_padded = self.log.hidden, self.log.hide_padded
        for f in self.all_frames():
            f.render()
        for w in self.normal:
            w.render()

    def apply_see_through(self) -> None:
        for f in self.all_frames():
            f.apply_see_through()

    def toggle_see_through(self) -> None:  # the tray menu's: the main chat's
        self.main.toggle_see_through()

    # more chat windows ----------------------------------------------------------------

    def new_window_menu(self, parent):
        """New chat window: a regular window (the easy one, beside the game), or an overlay on it."""
        import tkinter as tk
        sub = tk.Menu(parent, tearoff=0, bg=PANEL, fg=INK, activebackground=TAB_ON, activeforeground=INK)
        sub.add_command(label="Normal window (beside the game)", command=self.add_normal_window)
        sub.add_command(label="Overlay on the game", command=self.add_window)
        return sub

    def add_normal_window(self) -> None:
        conf = {"tab": "All"}
        self.opts["normal_windows"].append(conf)
        self.normal.append(NormalChat(self, conf))
        save_settings(self.opts)
        self.settings_changed()

    def close_normal(self, w: "NormalChat") -> None:
        self.normal.remove(w)
        self.opts["normal_windows"] = [c for c in self.opts["normal_windows"] if c is not w.conf]
        w.top.destroy()
        save_settings(self.opts)
        self.settings_changed()

    def add_window(self) -> None:
        """A new overlay showing All, just above the main chat, being adjusted so it can be dragged
        where it should go (even off the game window)."""
        p = self.main.placed()
        h = max(p["height"], round(self.line * 8))
        conf = {"tab": "All", "see_through": False,
                "free": {"left": p["left"] + 30, "top": max(0, p["top"] - h - 30), "width": p["width"], "height": h}}
        self.opts["windows"].append(conf)
        f = ChatFrame(self, conf)
        self.frames.append(f)
        f.apply_see_through()
        f.place(f.keep_on_screen(conf["free"]))
        f.show(True)
        f.set_edit(True)
        save_settings(self.opts)
        self.events.put(("status", "New chat window: drag it anywhere and an edge to resize, then right-click → "
                                   "Done. Right-click → Close this window closes it."))
        self.settings_changed()

    def add_split(self, frame: "ChatFrame | None" = None) -> None:
        """Split a frame (the main chat when none is said): a pane on top, inside it."""
        (frame or self.main).add_pane()

    def close_frame(self, f: "ChatFrame") -> None:
        self.frames.remove(f)
        self.opts["windows"] = [c for c in self.opts["windows"] if c is not f.conf]
        f.destroy()
        save_settings(self.opts)
        self.settings_changed()

    def settings_changed(self) -> None:
        """The settings window shows how many windows and splits there are: tell it."""
        if self.settings_vars.get("windows"):
            self.settings_vars["windows"]()

    # keeping everything where it belongs ----------------------------------------------------

    def follow(self) -> None:
        """Keep the main chat on the game's chat box (or where it was put, when unlocked), the extra
        overlays where they were put, and show them all while the game's window is open (not
        minimised). It runs again and again: one failed round is logged, and the next tries afresh."""
        try:
            self.follow_once()
        except Exception as e:
            if str(e) != getattr(self, "_follow_error", None):
                self._follow_error = str(e)
                log_error(f"follow: {e.__class__.__name__}: {e}")
        self.root.after(300, self.follow)

    def on_edge(self, x: int, y: int) -> bool:
        """(x, y) on screen on the game chat's top edge (just above its lines and scrollbar, not on
        the scrollbar's top arrow), above the main chat on it, within its width."""
        r, game, main = self.read_rect, self.game, self.main
        if not r or not game or self.opts["unlocked"] or not main.visible or main.rect is None:
            return False
        c = game["client"]
        left, top = c["left"] + r["left"], c["top"] + r["top"]
        return left - 4 <= x <= left + r["width"] + self.bar_px + 4 and top - 12 <= y < min(main.rect["top"], top + 4)

    def watch_edge(self) -> None:
        """The game chat's top edge grabbed (a mouse button pressed on it, above the main chat):
        the main chat steps aside until it's let go, so the drag can go on down across it, and
        comes back at the new size."""
        try:
            x, y, held = mouse_state()
            if held and not self.was_held and self.on_edge(x, y):
                self.edge_held = True
                self.main.show(False)
            elif not held and self.edge_held:
                self.edge_held, self.back_at = False, time.time() + 1.2
            self.was_held = held
        except Exception as e:
            log_error(f"edge: {e.__class__.__name__}: {e}")
        self.root.after(40, self.watch_edge)

    def follow_once(self) -> None:
        unlocked, main = self.opts["unlocked"], self.main
        if unlocked and not main.edit and not main.busy():
            main.place(self.free_rect())
        for f in self.frames:
            f.follow()
        if self.demo:
            return
        game = game_geometry()
        self.game = game
        rect = from_relative(self.opts["box"], game["client"]) if game else None
        if game and not rect and not self.want_fit and not main.edit and time.time() - self.fit_asked > 10:
            self.want_fit, self.fit_asked = True, time.time()  # first start, or the game window changed size
        if game and rect and not main.edit:
            self.line = self.opts["box"]["line"]
            self.read_rect = {"left": rect["left"] - game["client"]["left"], "top": rect["top"] - game["client"]["top"],
                              "width": rect["width"], "height": rect["height"]}
            if not unlocked and not main.busy():
                main.place(self.main_rect(rect))
            reason = self.warning()
            if reason and not self.explained:
                self.explained = True
                self.explain(reason)
        # shown as long as the game's window is open, in front or not; minimised to the taskbar (no
        # game window found then), everything hides. Unlocked, it isn't over the game's chat: nothing
        # to step aside for; while typing in it, or with the game's chat closed, it stays
        up = bool(game) or self.always_show
        stays = unlocked or main.typing() or self.chat_closed
        aside = self.edge_held or time.time() < self.back_at  # the game chat being resized from its top edge
        main.show(bool(up and (rect or unlocked)) and not self.user_hidden and not (self.covered and not stays)
                  and not aside)
        for f in self.frames:
            f.show(up and not self.user_hidden)

    # events -----------------------------------------------------------------

    def pump(self) -> None:
        changed = False
        try:
            while True:
                kind, data = self.events.get_nowait()
                if self.verbose:
                    print(time.strftime("%H:%M:%S"), kind, f"{data['kind']:>7} {line_text(data)}" if kind == "msg" else data,
                          flush=True)
                if kind == "msg":
                    if data["kind"] in SPACER_KINDS:
                        if padded(data["body"]):
                            data["padded"] = padded_kind(data["body"])
                        data["body"] = unpadded(data["body"])
                    if data.get("padded") not in self.log.hide_padded:  # left out: no alerts either
                        self.watched(data)
                    if self.relay and not self.demo:
                        self.relay.send(data)  # guild chat only, and only once joined
                    self.log.add(data)
                    for p in self.overlay_panes():
                        if p.log is not self.log:
                            p.log.notice(data)
                    for w in self.normal:
                        for log in w.logs():
                            log.notice(data)
                    if not self.demo:
                        save_message(HISTORY_FILE, data)
                    for p in self.overlay_panes():  # reading back: keep the same lines in view
                        if p.scroll and shows(p.log.kinds(), data):
                            p.scroll_to(p.scroll + 1)
                    changed = True
                    if data["kind"] == "whisper" and not data["to"] and self.opts["whisper_sound"]:
                        import winsound
                        try:
                            winsound.PlaySound(str(self.chime), winsound.SND_FILENAME | winsound.SND_ASYNC)
                        except RuntimeError:
                            pass
                elif kind == "fit":
                    self.opts["box"] = data
                    self.back_at = 0.0  # stepped aside for a resize: its new size is here, back it comes
                    if data["line"] != self.line:
                        self.line = data["line"]
                        self.set_fonts()
                        changed = True
                    save_settings(self.opts)
                elif kind == "see_through":
                    self.toggle_see_through()
                    changed = True
                elif kind == "unlock":
                    self.set_unlocked(not self.opts["unlocked"])
                    changed = True
                elif kind == "window":  # the tray: a normal window, the easy kind
                    self.add_normal_window()
                    changed = True
                elif kind == "split":
                    self.add_split()
                    changed = True
                elif kind == "settings":
                    self.open_settings()
                elif kind == "character":  # the character's name, read from the status bar: who types
                    self.opts["game_name"] = data
                    save_settings(self.opts)
                    if self.relay:
                        self.relay.game_name = data
                elif kind == "update":  # a newer version is out on GitHub
                    self.show_update(*data)
                elif kind == "check_now":  # the tray menu: ask GitHub now, and say if it's up to date
                    self.check_updates(again=False, tell=True)
                elif kind == "login":  # the magic link: this app is logged in as its Discord name
                    self.opts["guild_login"] = data
                    save_settings(self.opts)
                    if self.relay:
                        self.relay.login = data
                    changed = True
                elif kind == "relay_cfg":  # the guild's details, heard on its channel: kept for next time
                    code, cfg = data
                    self.opts["relay_cfg"] = {**self.opts["relay_cfg"], code: cfg}
                    save_settings(self.opts)
                elif kind == "covered":
                    self.covered = data
                elif kind == "chat_closed":
                    self.chat_closed = data
                    changed = True
                elif kind == "status":
                    now = time.time()
                    if (data, ) != getattr(self, "_last_status", (None, ))[:1] or now - self._last_status[1] > 60:
                        self._last_status = (data, now)  # the same note again within a minute: once is enough
                        self.log.add({"kind": "status", "name": "", "body": data, "at": now, "to": None,
                                      "time": time.strftime("%H:%M", time.localtime(now))})
                        changed = True
                elif kind == "hotkey":
                    self.on_hotkey(data)
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self.render()
        self.root.after(100, self.pump)

    def take_adjust_key(self) -> None:
        """Ctrl+Alt+F5 for moving and resizing, once it's switched on (its own thread: a hotkey
        belongs to the thread that registered it)."""
        import overlay
        if not self.adjust_key_taken:
            self.adjust_key_taken = True
            threading.Thread(target=overlay.hotkey_thread, args=(self.events, {HK_ADJUST_KEY: ADJUST_VK}),
                             daemon=True).start()

    def adjusting(self) -> bool:
        return any(f.edit for f in self.all_frames())

    def on_hotkey(self, hk: int) -> None:
        if hk == HK_ADJUST_KEY:  # Ctrl+Alt+F5: only while it's switched on
            if not self.opts["adjust_hotkey"]:
                return
            hk = HK_EDIT
        if hk == HK_EDIT:  # adjust every frame that can move; again (or Done), each keeps where it was put
            frames = [f for f in self.all_frames() if f.movable()]
            if any(f.edit for f in frames):
                for f in frames:
                    if f.set_edit(False):
                        f.keep(f.placed())
            else:
                for f in frames:
                    f.set_edit(True)
        elif hk == HK_FIT:
            self.reset_position()
        elif hk == HK_HIDE:
            self.user_hidden = not self.user_hidden
        elif hk == HK_QUIT:
            self.stop.set()
            if self.twitch:
                self.twitch.stop()
            if self.relay:
                self.relay.stop()
            if self.tray:
                self.tray.stop()
            self.root.destroy()

    def set_unlocked(self, on: bool) -> None:
        """Unlocked: the main chat can go anywhere, even off the game window, and it starts being
        adjusted to be dragged there. It still reads the game's own chat. Locked again, it goes
        back onto the game's chat."""
        if on == bool(self.opts["unlocked"]):
            return
        self.opts["unlocked"] = on
        if on:
            self.opts["free"] = self.opts["free"] or self.main.placed()
            self.main.set_edit(True)
            self.events.put(("status", "Unlocked: drag the chat anywhere and an edge to resize, then right-click → "
                                       "Done. Reset position puts it back on the game's chat."))
        else:
            self.main.set_edit(False)  # leave adjusting without keeping it anywhere
        self.main.rect = None
        save_settings(self.opts)
        if self.settings_vars:
            self.settings_vars["unlocked"].set(on)

    def reset_position(self) -> None:
        """Back on the game's chat box, fitted again: for a chat put somewhere it can't be reached,
        or moved off the chat by accident."""
        self.set_unlocked(False)
        self.main.set_edit(False)
        self.opts["extra"], self.opts["free"], self.user_hidden = 0, None, False
        self.want_fit = True
        self.main.rect = None
        save_settings(self.opts)

    # settings -----------------------------------------------------------------

    def set_text_size(self, px: int | None) -> None:
        self.opts["font_px"] = px
        self.set_fonts()
        self.render()
        save_settings(self.opts)

    def set_font(self, family: str, bold: bool) -> None:
        """The messages' font and weight (Settings → Look)."""
        self.opts["font_family"], self.opts["font_bold"] = family, bold
        self.set_fonts()
        self.render()
        save_settings(self.opts)

    def game_name(self) -> str:
        """Your character's name for what you type in the Guild tab: as read from the game's status
        bar, or your first character name from the Chat page."""
        return self.opts["game_name"].strip() or next(iter(self.opts["ignore_names"]), "")

    def set_opt(self, key: str, value) -> None:
        self.opts[key] = value
        save_settings(self.opts)
        self.render()

    def pick_colour(self, key: str) -> None:
        """A colour picker for the background (panel_bg) or one chat type's text."""
        from tkinter import colorchooser
        now = self.opts["panel_bg"] or PANEL if key == "panel_bg" else self.opts["colors"].get(key) or COLORS[key]
        _, chosen = colorchooser.askcolor(color=now, parent=self.settings, title="CustomClassic Chat colour")
        if not chosen:
            return
        if key == "panel_bg":
            self.opts["panel_bg"] = chosen
            self.apply_see_through()  # the background, on whichever window draws it
        else:
            self.opts["colors"] = {**self.opts["colors"], key: chosen}
        self.set_opt(key if key == "panel_bg" else "colors", self.opts[key if key == "panel_bg" else "colors"])

    def reset_colours(self) -> None:
        self.opts["colors"], self.opts["panel_bg"] = {}, None
        self.apply_see_through()
        save_settings(self.opts)
        self.render()

    def icon_path(self) -> Path:
        return save_icon(CACHE_DIR / "customclassic_chat.ico")

    def open_settings(self) -> None:
        """The settings window (settings_ui.py); a second open brings the first to the front."""
        import settings_ui
        if self.settings is not None and self.settings.winfo_exists():
            self.settings.deiconify()
            self.settings.lift()
            return
        self.settings = settings_ui.SettingsWindow(self).top

    def tabs(self) -> list:
        o = self.opts
        return tabs_for(o["custom_tab"], self.twitch_channel() is not None, o["twitch_in_all"],
                        bool(o["relay_tab"] and guild_relay.guild_key(o["relay_code"])))

    def retab(self, rename: tuple[str | None, str | None] = (None, None)) -> None:
        """The tabs again after a setting changed; a renamed tab that was open stays open."""
        old, new = rename
        for p in self.overlay_panes() + [p for w in self.normal for p in w.panes]:
            p.log.set_tabs(self.tabs(), new if old and p.log.tab == old else None)
            p.conf["tab"] = p.log.tab
        self.opts["tab"] = self.log.tab

    def twitch_channel(self) -> str | None:
        """The Twitch channel to read: only when opted in and a channel is set."""
        name = twitch_chat.channel_name(self.opts["twitch_channel"])
        return name if self.opts["twitch_on"] and name else None

    def start_twitch(self) -> None:
        """Read the Twitch channel set in Settings, if opted in; a new channel replaces the old."""
        if self.twitch:
            self.twitch.stop()
            self.twitch = None
        channel = self.twitch_channel()
        if channel and not self.demo:
            self.twitch = twitch_chat.TwitchChat(channel, self.events.put)

    def guild_colour_known(self) -> bool:
        """Whether guild chat's colour is the game's real one (set in reader.py once the game has
        guild chat, or in config.toml [colors] guild), not old MapleStory's purple standing in."""
        import reader
        return reader.GUILD_CONFIRMED or reader.Config.load().colors.get("guild") != reader.COLORS["guild"]

    def start_relay(self) -> None:
        """Join the guild's channel set in Settings (joined, the guild chat this app reads is shared
        with the guild's other apps, and the Guild tab shows if ticked)."""
        if self.relay:
            self.relay.stop()
            self.relay = None
        o, code = self.opts, guild_relay.guild_key(self.opts["relay_code"])
        admin = o["relay_admin"].get(code) if code else None
        if code and not self.demo:
            self.relay = guild_relay.GuildPeer(code, o["relay_reader"], self.events.put, True,
                                               o["relay_tab"], "guild", cfg=o["relay_cfg"].get(code),
                                               admin=admin, login=o["guild_login"])
            self.relay.game_name = self.game_name()

    def set_relay(self, code: str, tab: bool) -> None:
        self.opts["relay_code"] = guild_relay.guild_key(code)
        self.opts["relay_tab"] = tab
        save_settings(self.opts)
        self.start_relay()
        self.retab()
        self.scroll = 0
        self.render()

    def set_twitch(self, on: bool, channel: str, in_all: bool) -> None:
        before = self.twitch_channel()
        self.opts["twitch_on"], self.opts["twitch_in_all"] = on, in_all
        self.opts["twitch_channel"] = twitch_chat.channel_name(channel)
        if self.twitch_channel() != before:
            self.start_twitch()
        self.retab()
        self.scroll = 0
        save_settings(self.opts)
        self.render()

    def set_custom_tab(self, custom: dict) -> None:
        old = custom_name(self.opts["custom_tab"])
        self.opts["custom_tab"] = custom
        self.retab((old, custom_name(custom)))
        self.scroll = 0
        save_settings(self.opts)
        self.render()


def print_replay(paths: list[Path]) -> None:
    """What each saved screenshot's chat lines become: their kind and the tabs that show them."""
    import reader as core
    from PIL import Image
    reader, dedupe, log = core.Reader(core.Config.load()), Dedupe(), ChatLog()
    for p in paths:
        img, found = Image.open(p).convert("RGB"), None
        if img.height > 400:
            found = find_lines(img.crop((0, int(img.height * 0.35), img.width, img.height)), reader)
            if found:
                b = found[0]
                top = int(img.height * 0.35) + b["top"]
                img = img.crop((b["left"], top, b["left"] + b["width"], top + b["height"]))
        read = reader.read(img)
        pitch = found[1] if found else 16.0
        stamps = [ln for ln in read if core.TIMESTAMP.match(ln.text)]
        if not found and len(stamps) >= 2:  # a crop of the chat as saved: start it at the time stamps, as live
            tops = sorted(ln.top for ln in stamps)
            pitch = float(sorted(b - a for a, b in zip(tops, tops[1:]))[(len(tops) - 1) // 2])
            img = img.crop((max(0, min(ln.left for ln in stamps) - 4), 0, img.width, img.height))
            read = reader.read(img)
        lines = core.merge_wrapped(trim_scene(read, pitch), img.height, img.width)
        print(f"{p.name}:")
        for ln in lines:
            print(f"  {kind_of(ln) or 'left out':>8}  [{ln.source}{', band' if ln.band else ''}] {ln.text}")
        for m in messages_from(lines, dedupe, time.time()):
            log.add(m)
    for name, _ in log.tabs:
        log.select(name)
        print(f"{name} tab:")
        for m in log.visible():
            print(f"  {line_text(m)}")


def main(argv: list[str]) -> None:
    import overlay
    if "--make-icon" in argv:  # for shortcuts: cache/customclassic_chat.ico
        print(save_icon(CACHE_DIR / "customclassic_chat.ico"))
        return
    if "--replay" in argv:
        print_replay([Path(a) for a in argv[argv.index("--replay") + 1:] if not a.startswith("--")])
        return
    if not overlay.single_instance("CustomClassicChatOverlay"):
        message("CustomClassic Chat is already running. Its blue speech-bubble icon is in the taskbar's notification "
                "area (bottom right, maybe behind the ^ arrow).")
        return
    overlay.dpi_aware()
    give_way()
    ChatPanel(load_settings(), demo="--demo" in argv, always_show="--always-show" in argv,
              verbose="--verbose" in argv).root.mainloop()


def give_way() -> None:
    """Text recognition gives way to the game when the computer is busy: this program runs below
    normal priority, all but its windows (this thread), which keep normal priority so the chat
    stays as quick to scroll and click as ever."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass(ctypes.c_void_p(k32.GetCurrentProcess()), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    keep_pace()


def keep_pace() -> None:
    """This thread back up to normal priority within the program's below-normal class."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GetCurrentThread.restype = ctypes.c_void_p
    k32.SetThreadPriority(ctypes.c_void_p(k32.GetCurrentThread()), 2)  # THREAD_PRIORITY_HIGHEST: 6 + 2 = normal's 8


def message(text: str) -> None:
    """A plain Windows message box: the .exe has no console to print to."""
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, "CustomClassic Chat", 0x40)  # MB_ICONINFORMATION


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception:  # without a console a crash would vanish: keep it in crash.log and say so
        import traceback
        (HERE / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        message(f"CustomClassic Chat stopped because of an error. The details are in {HERE / 'crash.log'}.")
