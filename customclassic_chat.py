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
    Ctrl+Alt+F5   adjust: drag to move, drag any edge or corner to resize; press again to save
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
    "interval_s": 0.7,        # seconds between reads of the chat
    "font_px": None,          # message text size in pixels; None: sized from the game's chat lines
    "min_lines": 3,           # fewer lines in the game's chat (minimised, one or two): megaphones arriving together
                              # may scroll away unread, and a quiet ⚠ shows until clicked
    "history": 20000,         # messages kept in memory at most
    "keep_hours": 12,         # chat history kept between restarts, in hours; 0 keeps it forever
    "timestamps": "seconds",  # "seconds" [18:16:05], "minutes" [18:16] or "off"
    "opacity": 1.0,           # the panel's opacity when ◐ is off
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
    "relay_share": False,     # share the guild chat this app reads with the guild's other apps
    "relay_source": "guild",  # what's shared: "guild"; "map" or "whisper" only to test before the game has guild chat
    "relay_tab": False,       # the guild's Discord channel in the Guild tab
    "relay_reader": "",       # this install's random id among the guild's apps (no name)
    "relay_cfg": {},          # guild code -> the guild's details as last heard (its name and Discord webhook)
    "relay_admin": {},        # guild code -> guilds set up from here: name, webhook, and the Discord bot token if any
    "guild_login": "",        # this app's login from the bot's magic link (/chatlink): to type in the Guild tab
    "game_name": "",          # your character's name, shown with your Discord name on what you type (if they differ)
    "tab": "All",
    "settings_page": "Appearance",  # the settings section open last
    "menu_close_s": 10,       # the right-click menu closes after this many seconds (0: stays until clicked away)
    "box": None,              # the chat lines relative to the game window: dx, dy (from its bottom), w, h, line, cw, ch
    "extra": 0,               # pixels the panel reaches above the game's chat (dragged with the ≡ grip)
    "unlocked": False,        # placed anywhere you like instead of on the game's chat (it still reads the game's chat)
    "free": None,             # where it sits then, on screen: left, top, width, height
    "windows": [],            # extra chat windows: each its tab, place ("free") and see-through
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
# often run on into the chat line beside them, and "All" can read as "AlI")
CHAT_MENU = re.compile(r"(?i)/\s*to\s*(?:a[l1i|]{2}|buddy|group|party|guild|alliance|spouse|expedition)\b"
                       r"|\(\s*/\s*(?:s|b|gr|p|g|a)\s*\)")


def chat_menu_open(read) -> bool:
    """The game's chat-type list is open over its chat: one of its entries is read there. Like a
    pop-up, the panel steps aside to show it."""
    return any(CHAT_MENU.search(ln.text) for ln in read)


PANEL, STRIP, TAB, TAB_ON, INK, SOFT, DOT = "#111827", "#0b1120", "#1c2740", "#2f5597", "#eef3fb", "#8f9db5", "#ff4b4b"
WARN = "#ffc24b"
GOLD = "#ffd24a"  # the watch list's star and dot
ADJUST, ADJUST_EDGE = "#2f6fe0", "#9fc2ff"  # adjust mode: the banner, the outline and corner handles
SB_TRACK, SB_BUTTON, SB_ARROW, SB_THUMB, SB_EDGE = "#e3e8ef", "#a9c8ee", "#1f4f8f", "#8ea3c2", "#5b7fb4"  # as the game's
FONT = "Verdana"
HOTKEYS = {1: 0x74, 2: 0x75, 3: 0x76, 4: 0x72}  # Ctrl+Alt+F5 adjust, F6 hide, F7 quit, F3 fit again
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


class Dedupe:
    """The chat shows each line for many reads, and text recognition reads it a little
    differently now and then ("CHO1" / "CH01"): a line close to one seen recently is not new."""

    def __init__(self, minutes: float = 20, compare_last: int = 120):
        self.minutes, self.compare_last = minutes, compare_last
        self.recent: deque[tuple[float, str]] = deque()

    def seed(self, messages, now: float) -> None:
        """Lines already read before a restart (kept in the history as they were read): the
        game's chat still shows them, and they aren't new again."""
        for m in messages:
            if m.get("raw") and now - m.get("at", 0) < self.minutes * 60:
                self.recent.append((m["at"], re.sub(r"[^a-z0-9]", "", m["raw"].lower())))

    def is_new(self, text: str, now: float) -> bool:
        from rapidfuzz import fuzz
        key = re.sub(r"[^a-z0-9]", "", text.lower())
        while self.recent and self.recent[0][0] < now - self.minutes * 60:
            self.recent.popleft()
        for _, seen in list(self.recent)[-self.compare_last:]:
            if key == seen or (len(key) > 8 and fuzz.ratio(key, seen) >= 92):
                return False
        self.recent.append((now, key))
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
        pystray.MenuItem("Adjust position", send("hotkey", HK_EDIT)),
        pystray.MenuItem("Unlocked (place it anywhere)", send("unlock", None), checked=lambda item: app.opts["unlocked"]),
        pystray.MenuItem("Reset position", send("hotkey", HK_FIT)),
        pystray.MenuItem("Split the chat", send("split", None)),
        pystray.MenuItem("New chat window", send("window", None)),
        pystray.MenuItem("See-through", send("see_through", None), checked=lambda item: app.opts["see_through"]),
        pystray.MenuItem("Settings…", send("settings", None)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", send("hotkey", HK_QUIT)),
    )
    icon = pystray.Icon("CustomClassicChat", icon_image(32), "CustomClassic Chat", menu)  # the tray shows it small
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def frame_image(frame, x0: int, y0: int, x1: int, y1: int):
    from PIL import Image
    crop = frame[max(0, y0):max(0, y1), max(0, x0):max(0, x1), :3][:, :, ::-1]  # BGRA -> RGB
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


def read_loop(app) -> None:
    """Reads the chat from pictures of the game window; finds the chat box when asked."""
    import reader as core
    cfg = core.Config.load()
    reader, dedupe, palette = core.Reader(cfg), Dedupe(), (cfg.colors, cfg.backgrounds)
    dedupe.seed(list(app.log.messages), time.time())  # what the game's chat still shows from before a restart
    capture, hwnd, last_error = None, None, ""
    last_check, tops, watch, lost = time.time(), deque(maxlen=6), CoverWatch(), 0
    while not app.stop.is_set():
        t0 = time.time()
        try:
            game = app.game
            if not game:
                if capture:
                    capture.stop()
                    capture, hwnd = None, None
            else:
                if game["hwnd"] != hwnd or (capture and capture.closed):
                    if capture:
                        capture.stop()
                    capture, hwnd = GameCapture(game["hwnd"]), game["hwnd"]
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
                    if r:
                        img = frame_image(frame, ox + r["left"], oy + r["top"], ox + r["left"] + r["width"],
                                          oy + r["top"] + r["height"])
                        if img:
                            read = reader.read(img)
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
                    if r and not app.want_fit and not app.msgs.edit and t0 - last_check > RECHECK_S:
                        # the game's chat resized? look at a band from well above it to just below it
                        last_check, line = t0, app.line
                        x0, y0 = max(0, int(r["left"] - line)), max(0, int(r["top"] - line * 8))
                        x1 = min(c["width"], int(r["left"] + r["width"] + line))
                        y1 = min(c["height"], int(r["top"] + r["height"] + line * 0.5))
                        img = frame_image(frame, ox + x0, oy + y0, ox + x1, oy + y1)
                        found = find_lines(img, reader) if img else None
                        lost = 0 if found else lost + 1
                        if found and abs(found[1] - app.line) > app.line * 0.2:
                            app.want_fit = True  # the game's UI Size changed: the lines are another size, fit afresh
                        elif found:
                            box = {**found[0], "left": found[0]["left"] + x0, "top": found[0]["top"] + y0}
                            new = resized(r, box, app.line, tops)
                            if new:
                                app.events.put(("fit", to_relative({**new, "bar": app.bar_px}, app.line, c)))
                        elif lost >= 3 and not app.covered:
                            app.want_fit, lost = True, 0  # no chat where it should be for 15 s: look for it afresh
        except Exception as e:  # keep reading through a bad frame; say so once
            error = f"Skipped a read ({e.__class__.__name__}: {e})"[:120]
            if error != last_error:
                app.events.put(("status", error))
            last_error = error
        app.stop.wait(max(0.2, app.opts["interval_s"] - (time.time() - t0)))
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


class ChatView:
    """One chat window: its tab strip and messages, its tab, scrolling and see-through. The main
    panel is one (on the game's chat box, or wherever it was unlocked to); extra windows are
    others, each wherever it was put. They all show the same chat, read once."""

    closable = False  # an ✕ on the tab strip (extra windows)

    def build(self, title: str, master=None) -> None:
        overlay = self.app.overlay
        self.msgs = overlay.Overlay(title, 40, 40, 400, 100, master=master, click_through=False)
        self.strip = overlay.Overlay(f"{title} tabs", 40, 20, 400, 20, master=self.msgs.root, click_through=False)
        for w in (self.msgs, self.strip):
            w.canvas.configure(bg=self.opts["panel_bg"] or PANEL)
            w.canvas.bind("<MouseWheel>", self.on_wheel)
        self.strip.canvas.configure(bg=STRIP)
        self.strip.canvas.bind("<ButtonPress-1>", self.on_strip_click)
        self.strip.canvas.bind("<B1-Motion>", self.on_grip_drag)
        self.strip.canvas.bind("<ButtonRelease-1>", self.on_grip_release)
        self.msgs.canvas.bind("<ButtonPress-1>", self.on_press)
        self.msgs.canvas.bind("<B1-Motion>", self.on_drag)
        self.msgs.canvas.bind("<ButtonRelease-1>", self.on_release)
        for w in (self.msgs, self.strip):
            w.canvas.bind("<Motion>", self.on_motion)
            w.canvas.bind("<ButtonRelease-3>", self.menu)  # on release: letting go can't pick an item
        self.scroll = 0            # messages scrolled up from the newest
        self.in_view = 1           # messages that fit at the last drawing
        self.bar = None            # what the mouse is doing on the scrollbar: ("thumb", grab offset) / ("repeat", step)
        self.repeat_id = None
        self.grip = None           # the ≡ grip being dragged: (screen y it started at, extra then, rect then)
        self.drag = None           # moving or resizing in adjust mode
        self._where = None
        import tkinter as tk
        self.typed = tk.StringVar()
        self.input = tk.Entry(self.msgs.root, textvariable=self.typed, bg="#0b1120", fg=INK, insertbackground=INK,
                              relief="flat", highlightthickness=1, highlightbackground="#2a3654",
                              highlightcolor="#3d6fd1", disabledbackground="#0b1120", disabledforeground=SOFT)
        self.input.bind("<Button-1>", self.start_typing)
        self.input.bind("<Return>", self.send_typed)
        self.input.bind("<Escape>", lambda e: self.stop_typing())
        self.input.bind("<FocusOut>", lambda e: self.typing and self.input.after(150, self.check_keyboard))
        self.typing = False

    @property
    def hwnds(self) -> set:
        return {self.msgs.hwnd, self.strip.hwnd}

    def show(self, visible: bool) -> None:
        self.msgs.show(visible or self.msgs.edit)
        self.strip.show(visible or self.msgs.edit)

    def set_edit(self, on: bool) -> bool:
        """Adjust mode on or off; True when it was just ended (time to keep the new place)."""
        if self.msgs.edit == on:
            return False
        ended = self.msgs.toggle_edit()
        self.strip.edit = self.msgs.edit
        self.apply_see_through()  # solid while adjusting
        self.render()
        return ended

    # placing ----------------------------------------------------------------

    def place(self, r: dict) -> None:
        """The whole window inside r: the tab strip as its top line, the messages below it."""
        sh = strip_height(self.line)
        where = (r["left"], r["top"], r["width"], r["height"], sh)
        if where == self._where:
            return
        self._where = where
        self.strip.place(r["left"], r["top"], r["width"], sh)
        self.msgs.place(r["left"], r["top"] + sh, r["width"], max(sh, r["height"] - sh))
        self.render()

    def panel_now(self) -> dict:
        """The window's rect as it sits on screen (tab strip and messages together)."""
        return {"left": self.msgs.root.winfo_x(), "top": self.strip.root.winfo_y(), "width": self.msgs.width,
                "height": self.strip.height + self.msgs.height}

    def placed(self) -> dict:
        """Where the window was last put (Windows reports a move a moment later)."""
        if self._where:
            left, top, width, height, _ = self._where
            return {"left": left, "top": top, "width": width, "height": height}
        return self.panel_now()

    # adjust mode: drag to move, any edge or corner to resize ------------------

    EDGE = 12  # how close to an edge a press resizes rather than moves

    def edit_zone(self, x: int, y: int) -> str:
        """Which part of the window a press at screen (x, y) grabs: "n", "se", "w" ... or "move"."""
        r = self.placed()
        e = self.EDGE
        v = "n" if y - r["top"] < e else ("s" if r["top"] + r["height"] - y < e else "")
        h = "w" if x - r["left"] < e else ("e" if r["left"] + r["width"] - x < e else "")
        return (v + h) or "move"

    CURSORS = {"move": "fleur", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow",
               "w": "sb_h_double_arrow", "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw"}

    def on_motion(self, e) -> None:
        """While adjusting, the pointer shows what a press would do there."""
        if self.msgs.edit:
            cursor = self.CURSORS[self.edit_zone(e.x_root, e.y_root)]
        else:  # the ≡ grip and the tab row's top edge show they resize, like the game chat's top
            on_strip = e.widget is self.strip.canvas
            cursor = "sb_v_double_arrow" if on_strip and (e.x < strip_height(self.line) + 4 or e.y < 4) else ""
        if self.grip:
            return
        for w in (self.msgs, self.strip):
            w.canvas.configure(cursor=cursor)

    def start_edit_drag(self, e) -> None:
        self.drag = (self.edit_zone(e.x_root, e.y_root), e.x_root, e.y_root, self.placed())

    def edit_drag(self, e) -> None:
        """Move, or resize from the edge or corner grabbed; the opposite side stays put."""
        zone, x0, y0, r = self.drag
        dx, dy = e.x_root - x0, e.y_root - y0
        left, top, w, h = r["left"], r["top"], r["width"], r["height"]
        min_w, min_h = 200, 2 * round(self.line) + strip_height(self.line)
        if zone == "move":
            left, top = left + dx, top + dy
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
        self.place({"left": left, "top": top, "width": w, "height": h})

    def keep_on_screen(self, free: dict) -> dict:
        """A place put somewhere that's off every monitor (one unplugged since) comes back to the
        middle of the game window or the main screen."""
        if on_screen({**free, "height": strip_height(self.line)}):
            return free
        game = self.app.game
        area = game["client"] if game else {"left": 0, "top": 0, "width": self.msgs.root.winfo_screenwidth(),
                                            "height": self.msgs.root.winfo_screenheight()}
        return rescued(free, area)

    def apply_see_through(self) -> None:
        """◐ on: the messages see-through, and clicks go to whatever is below. The tab strip
        stays solid and clickable, so ◐ can always be clicked off again."""
        on = bool(self.see_through) and not self.msgs.edit
        self.msgs.set_alpha(self.opts["peek_alpha"] if on else self.opts["opacity"])
        self.strip.set_alpha(self.opts["opacity"])
        self.msgs.through = on
        self.msgs.click_through(on)

    # the tab strip ----------------------------------------------------------

    def tab_spans(self) -> list[tuple[str, int, int]]:
        x, out, pad = strip_height(self.line) + 6, [], 10  # after the ≡ grip
        for name, _ in self.log.tabs:
            w = self.tab_font.measure(name) + 2 * pad
            out.append((name, x, x + w))
            x += w + 3
        return out

    def on_strip_click(self, e) -> None:
        if self.msgs.edit:  # adjusting: the tab row moves the window, its top edge and corners resize it
            self.start_edit_drag(e)
            return
        for name, x0, x1 in self.buttons():
            if x0 - 2 <= e.x < x1 + 2:
                if name == "close":
                    self.close()
                    return
                {"see": self.toggle_see_through, "split": self.app.add_split, "warn": self.dismiss_warning}[name]()
                self.render()
                return
        # anywhere else on the tab row: dragged up or down it resizes, like the game's chat (the ≡ grip
        # too); let go without dragging and it was a click on a tab
        self.grip = (e.y_root, self.opts["extra"], self.panel_now())
        self.grip_moved = False
        self.grip_x = e.x

    GRIP_SLOP = 4  # pixels the pointer moves up or down before a press on the tab row is a resize

    def pick_tab(self, x: int) -> None:
        for name, x0, x1 in self.tab_spans():
            if x0 <= x < x1:
                self.log.select(name)
                self.scroll = 0
                self.tab_chosen(name)
        self.render()

    BUTTON_TEXT = {"close": "✕", "see": "◐", "split": "+"}

    def can_split(self) -> bool:
        return False

    def buttons(self) -> list[tuple[str, int, int]]:
        """The buttons at the right end of the tab strip, right to left, as (name, x0, x1): ✕ on an
        extra window, ◐, + to split the chat (while it isn't), and the ⚠ when there is one."""
        s = self.strip.height - 4
        x = self.strip.width - s - 4
        names = (["close"] if self.closable else []) + ["see"] + (["split"] if self.can_split() else []) + \
            (["warn"] if self.warning() else [])
        out = []
        for name in names:
            out.append((name, x, x + s))
            x -= s + 4
        return out

    def menu(self, e) -> None:
        """Right click on a chat window: split it, more windows, and the window's own settings."""
        import tkinter as tk
        app = self.app
        m = tk.Menu(self.msgs.root, tearoff=0, bg=PANEL, fg=INK, activebackground=TAB_ON, activeforeground=INK)
        split = next((w for w in app.windows if w.docked), None)
        if split is None:
            m.add_command(label="Split the chat (a pane on top)", command=app.add_split)
        else:
            m.add_command(label="Remove the split", command=split.close)
        m.add_command(label="New chat window", command=app.add_window)
        if self.closable and not self.docked:  # a split's own menu already offers removing it
            m.add_command(label="Close this window", command=self.close)
        m.add_separator()
        m.add_command(label=("✓ " if self.see_through else "") + "See-through", command=lambda: (
            self.toggle_see_through(), self.render()))
        m.add_command(label="Adjust position (Ctrl+Alt+F5)", command=lambda: app.on_hotkey(HK_EDIT))
        m.add_command(label="Settings…", command=app.open_settings)
        open_ = threading.Event()
        open_.set()
        threading.Thread(target=close_menu_when_left, args=(open_, float(self.opts["menu_close_s"] or 0)),
                         daemon=True).start()
        try:
            m.tk_popup(e.x_root + 2, e.y_root + 2)  # just off the pointer, so nothing is under it
        finally:
            open_.clear()
            m.grab_release()

    def on_grip_drag(self, e) -> None:
        if self.drag:
            self.edit_drag(e)
            return
        if self.grip and not self.grip_moved:
            if abs(e.y_root - self.grip[0]) < self.GRIP_SLOP:
                return
            self.grip_moved = True
            for w in (self.msgs, self.strip):
                w.canvas.configure(cursor="sb_v_double_arrow")
        if self.grip and self.is_free:  # grows upward from its bottom, like the game's chat
            y0, _, p = self.grip
            bottom = p["top"] + p["height"]
            h = max(2 * round(self.line) + strip_height(self.line), p["height"] + (y0 - e.y_root))
            self.place({**p, "top": bottom - h, "height": h})
        elif self.grip:
            self.grip_on_chat(e)

    def on_grip_release(self, e) -> None:
        self.drag = None
        if self.grip:
            self.grip = None
            for w in (self.msgs, self.strip):
                w.canvas.configure(cursor="")
            if not self.grip_moved:  # a click, not a drag
                if self.grip_x >= strip_height(self.line) + 4:  # (the ≡ grip itself isn't a tab)
                    self.pick_tab(self.grip_x)
                return
            if self.is_free:
                self.keep(self.panel_now())
            save_settings(self.opts)

    # scrolling, like the game's chat ---------------------------------------

    def scroll_to(self, scroll: int) -> None:
        most = max(0, len(self.log.visible()) - max(1, self.in_view))
        self.scroll = max(0, min(most, scroll))

    def on_wheel(self, e) -> None:
        self.scroll_to(self.scroll + max(1, abs(e.delta) // 120) * (1 if e.delta > 0 else -1))
        self.render()

    def bar_hit(self, y: int) -> str:
        """Which part of the scrollbar is at height y: up, down, thumb, page_up or page_down."""
        b, h = self.bar_px, self.msgs.height
        if y < b:
            return "up"
        if y >= h - b:
            return "down"
        top, size = thumb(len(self.log.visible()), self.in_view, self.scroll, h, b)
        return "thumb" if top <= y < top + size else ("page_up" if y < top else "page_down")

    def step(self, part: str) -> None:
        """One step of a held arrow or track click; repeats while the button is held, like the game's."""
        n = {"up": 1, "down": -1, "page_up": max(1, self.in_view - 1), "page_down": -max(1, self.in_view - 1)}[part]
        self.scroll_to(self.scroll + n)
        self.render()
        self.repeat_id = self.msgs.root.after(350 if self.repeat_id is None else 70, self.step, part)

    def on_press(self, e) -> None:
        if self.msgs.edit:
            self.start_edit_drag(e)
            return
        if e.x >= self.msgs.width - self.bar_px:
            part = self.bar_hit(e.y)
            if part == "thumb":
                top, _ = thumb(len(self.log.visible()), self.in_view, self.scroll, self.msgs.height, self.bar_px)
                self.bar = ("thumb", e.y - top)
            else:
                self.bar, self.repeat_id = ("repeat", part), None
                self.step(part)

    def on_release(self, e) -> None:
        if self.repeat_id is not None:
            self.msgs.root.after_cancel(self.repeat_id)
        self.bar, self.repeat_id, self.drag = None, None, None

    def on_drag(self, e) -> None:
        if self.bar and self.bar[0] == "thumb":
            b, total = self.bar_px, len(self.log.visible())
            _, size = thumb(total, self.in_view, self.scroll, self.msgs.height, b)
            self.scroll_to(scroll_at(e.y - self.bar[1], total, self.in_view, self.msgs.height, b, size))
            self.render()
            return
        if self.msgs.edit and self.drag:
            self.edit_drag(e)

    # drawing ----------------------------------------------------------------

    def render(self) -> None:
        self.place_input()
        self.render_strip()
        self.render_messages()

    # the typing line (the Guild tab) ----------------------------------------------

    def input_shown(self) -> bool:
        return self.log.tab == "Guild" and getattr(self.app, "relay", None) is not None

    def input_height(self) -> int:
        return max(20, round(self.line * 1.2)) if self.input_shown() else 0

    def place_input(self) -> None:
        if not self.input_shown():
            self.input.place_forget()
            return
        logged = guild_relay.check_login(self.opts["guild_login"]) if self.opts["guild_login"] else None
        self.input.configure(font=self.font, state="normal" if logged else "disabled")
        if not self.typing and not self.typed.get():
            self.input.configure(fg=SOFT)
            self.typed.set(f"Message the guild as {logged['name']}… (click, type, Enter)" if logged else
                           "To type here, log in: /chatlink in your guild's Discord")
            self.placeholder = True
        self.input.place(x=0, rely=1.0, anchor="sw", relwidth=1.0, width=-self.bar_px, height=self.input_height())

    def start_typing(self, e=None) -> None:
        if str(self.input.cget("state")) == "disabled":
            return
        if getattr(self, "placeholder", False):
            self.typed.set("")
            self.placeholder = False
        self.input.configure(fg=INK)
        self.typing = True
        self.msgs.take_keyboard()  # the keyboard comes here until Enter, Esc or a click elsewhere
        self.input.focus_force()
        self.input.after(120, lambda: self.check_keyboard(handing_over=True))

    def check_keyboard(self, handing_over: bool = False) -> None:
        """Tk says FocusOut for moves inside the app too, and while Windows hands the keyboard
        over: only a keyboard that really went to another window (a click on the game) ends the
        typing. Right after the click, a late hand-over is asked for once more instead."""
        if not self.typing:
            return
        if self.msgs.has_keyboard():
            if self.input.focus_get() is not self.input:
                self.input.focus_force()
        elif handing_over:
            self.msgs.take_keyboard()
            self.input.focus_force()
        else:
            self.stop_typing(refocus=False)  # the keyboard is where the user clicked: leave it there

    def stop_typing(self, refocus: bool = True) -> None:
        if not self.typing:
            return
        self.typing = False
        self.msgs.give_back(refocus)  # and goes back to the game
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

    def render_strip(self) -> None:
        c, h = self.strip.canvas, self.strip.height
        c.delete("all")
        g = h - 4  # the ≡ grip
        c.create_rectangle(4, 2, 4 + g, h - 2, fill=TAB, outline="")
        for i in (-1, 0, 1):
            y = h // 2 + 1 + i * max(3, h // 6)
            c.create_line(8, y, g, y, fill=SOFT, width=2)
        for name, x0, x1 in self.tab_spans():
            on = name == self.log.tab
            c.create_rectangle(x0, 2, x1, h, fill=TAB_ON if on else TAB, outline="")
            c.create_text((x0 + x1) // 2, h // 2 + 1, text=name, fill=INK if on else SOFT, font=self.tab_font)
            if self.log.unread.get(name):
                r = max(3, h // 6)
                c.create_oval(x1 - 2 * r - 2, 3, x1 - 2, 3 + 2 * r, fill=GOLD if name == "Watch" else DOT, outline="")
        for name, x0, x1 in self.buttons():
            if name == "warn":  # quiet: an amber mark, explained once a session; a click puts it away
                c.create_text((x0 + x1) // 2, h // 2 + 1, text="⚠", fill=WARN, font=self.tab_font)
                continue
            on = name == "see" and self.see_through
            c.create_rectangle(x0, 2, x1, h - 2, fill=TAB_ON if on else TAB, outline="")
            c.create_text((x0 + x1) // 2, h // 2 + 1, text=self.BUTTON_TEXT[name], fill=INK if on else SOFT,
                          font=self.tab_font)
        if self.msgs.edit:
            self.draw_adjust(c, self.strip.width, h, bottom=False)

    def render_messages(self) -> None:
        c, w, h = self.msgs.canvas, self.msgs.width, self.msgs.height
        c.delete("all")
        b, pad = self.bar_px, 6
        shown = self.log.visible()
        end = len(shown) - self.scroll
        y, fits = h - 2 - self.input_height(), 0  # above the typing line on the Guild tab
        for m in reversed(shown[:max(0, end)]):
            star = "★ " if m.get("watch") and self.log.tab != "Watch" else ""
            t = c.create_text(pad, 0, anchor="nw", text=star + line_text(m, self.opts["timestamps"]),
                              fill=self.opts["colors"].get(m["kind"]) or m.get("fg") or COLORS[m["kind"]],
                              font=self.font, width=w - 2 * pad - b)
            th = c.bbox(t)[3]
            c.move(t, 0, y - th)
            if m.get("bg"):  # a megaphone's band, as the game draws it
                band = c.create_rectangle(0, y - th, w - b - 1, y, fill=m["bg"], outline="")
                c.tag_lower(band)
            if m.get("watch"):  # caught by the watch list: a gold edge
                c.create_rectangle(0, y - th, 2, y - 1, fill=GOLD, outline="")
            y -= th
            if y < 0:
                break
            fits += 1
        self.in_view = max(1, fits)
        self.render_scrollbar(c, w, h, b, len(shown))

    def render_scrollbar(self, c, w: int, h: int, b: int, total: int) -> None:
        """The game's scrollbar, lying over the game's own: a dark divider, a light track, arrow
        buttons at both ends and a thumb to drag."""
        divider = max(1, round(b / 6))
        c.create_rectangle(w - b, 0, w - b + divider - 1, h - 1, fill="#1a1f2a", outline="")
        x0, b = w - b + divider, b - divider  # the track: arrows and thumb are as wide as it
        c.create_rectangle(x0, 0, w - 1, h - 1, fill=SB_TRACK, outline=SB_EDGE)
        for y0, up in ((0, True), (h - b, False)):
            c.create_rectangle(x0, y0, w - 1, y0 + b - 1, fill=SB_BUTTON, outline=SB_EDGE)
            m, a = x0 + b / 2, b * 0.28
            pts = (m - a, y0 + b * 0.62, m + a, y0 + b * 0.62, m, y0 + b * 0.36) if up else \
                (m - a, y0 + b * 0.38, m + a, y0 + b * 0.38, m, y0 + b * 0.64)
            c.create_polygon(*pts, fill=SB_ARROW, outline="")
        top, size = thumb(total, self.in_view, self.scroll, h, b)
        if total > self.in_view:
            c.create_rectangle(x0 + 2, top, w - 3, top + size - 1, fill=SB_THUMB, outline=SB_EDGE)
        if self.msgs.edit:
            self.draw_adjust(c, w, h, bottom=True)
            # the banner: what to do, and the key that finishes it, big enough to read at a glance
            text = c.create_text(w // 2, h // 2, justify="center", fill="#ffffff", font=self.hint_font,
                                 width=max(120, w - 60),
                                 text="Drag to move  ·  drag an edge or corner to resize\nPress Ctrl+Alt+F5 to save")
            x0, y0, x1, y1 = c.bbox(text)
            box = c.create_rectangle(x0 - 14, y0 - 10, x1 + 14, y1 + 10, fill=ADJUST, outline="#ffffff", width=2)
            c.tag_raise(text, box)

    def draw_adjust(self, c, w: int, h: int, bottom: bool) -> None:
        """Adjust mode's frame: a dashed outline and a handle in each corner of the window (the tab
        strip draws the top ones, the messages the bottom ones)."""
        s = max(10, self.EDGE)
        c.create_line(1, 0 if bottom else 1, 1, h, fill=ADJUST_EDGE, width=2, dash=(6, 3))
        c.create_line(w - 2, 0 if bottom else 1, w - 2, h, fill=ADJUST_EDGE, width=2, dash=(6, 3))
        y = h - 2 if bottom else 1
        c.create_line(0, y, w, y, fill=ADJUST_EDGE, width=2, dash=(6, 3))
        y0 = h - s if bottom else 0
        for x0 in (0, w - s):
            c.create_rectangle(x0, y0, x0 + s - 1, y0 + s - 1, fill="#ffffff", outline=ADJUST, width=2)


class ExtraChat(ChatView):
    """An extra chat window: the same chat, with its own tab, place and see-through. Added from
    the tray menu or Settings, closed with the ✕ on its tab strip; remembered in chat.json."""

    closable = True

    DIV = 7  # a split's divider bar, between it and the chat below

    def __init__(self, app, conf: dict):
        self.app, self.conf = app, conf  # conf: its entry in opts["windows"], saved as it changes
        self.log = app.log.view_of(conf.get("tab") or "All")
        self.build("CustomClassic Chat window", master=app.root)
        self.div = self.div_drag = None
        if self.docked:  # a bar of its own under the split: drag it to move the line between the two
            self.div = app.overlay.Overlay("CustomClassic Chat divider", 40, 40, 400, self.DIV, master=self.msgs.root,
                                           click_through=False)
            c = self.div.canvas
            c.configure(bg=TAB, cursor="sb_v_double_arrow")
            c.bind("<ButtonPress-1>", self.on_div_press)
            c.bind("<B1-Motion>", self.on_div_drag)
            c.bind("<ButtonRelease-1>", self.on_div_release)
            c.bind("<Enter>", lambda e: self.draw_div(True))
            c.bind("<Leave>", lambda e: self.draw_div(False))
            c.bind("<ButtonRelease-3>", self.menu)
        self.apply_see_through()

    # a split's divider --------------------------------------------------------

    def draw_div(self, hot: bool = False) -> None:
        c, w, h = self.div.canvas, self.div.width, self.div.height
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=TAB_ON if hot else TAB, outline="")
        for i in (-1, 0, 1):  # a grip in the middle, like the ≡
            x = w // 2 + i * 10
            c.create_line(x - 3, h // 2, x + 3, h // 2, fill=INK if hot else SOFT, width=2)

    def on_div_press(self, e) -> None:
        self.div_drag = (e.y_root, int(self.conf.get("height") or 120), self.app.placed(), self.app.opts["extra"])

    def on_div_drag(self, e) -> None:
        """Move the line between the split and the chat: one gets taller as the other gets shorter,
        the top of the split and the bottom of the chat stay put. The chat never gets shorter than
        the game's chat it covers (when it sits on it)."""
        if not self.div_drag:
            return
        y0, h0, m0, extra0 = self.div_drag
        app, line, sh = self.app, self.line, strip_height(self.line)
        d = max(sh + 2 * round(line) + self.DIV - h0, e.y_root - y0)
        on_chat = not app.is_free and app.read_rect and app.game
        d = min(d, extra0 if on_chat else m0["height"] - sh - 2 * round(line))
        self.conf["height"] = h0 + d
        if on_chat:
            app.opts["extra"] = extra0 - d
        app.place({**m0, "top": m0["top"] + d, "height": m0["height"] - d})

    def on_div_release(self, e) -> None:
        if self.div_drag:
            self.div_drag = None
            if self.app.is_free:
                self.app.keep(self.app.placed())
            save_settings(self.opts)

    # what the main panel knows, shared
    opts = property(lambda self: self.app.opts)
    line = property(lambda self: self.app.line)
    font = property(lambda self: self.app.font)
    tab_font = property(lambda self: self.app.tab_font)
    hint_font = property(lambda self: self.app.hint_font)
    bar_px = property(lambda self: bar_width(self.app.line))  # its own scrollbar: not over the game's
    is_free = True

    @property
    def see_through(self) -> bool:
        return bool(self.conf.get("see_through"))

    def toggle_see_through(self) -> None:
        self.conf["see_through"] = not self.see_through
        save_settings(self.opts)
        self.apply_see_through()

    def warning(self) -> None:
        return None

    def tab_chosen(self, name: str) -> None:
        self.conf["tab"] = name
        save_settings(self.opts)

    @property
    def docked(self) -> bool:
        """A split: docked on top of the main panel, as wide as it and moving with it."""
        return self.conf.get("dock") == "above"

    def keep(self, rect: dict) -> None:
        if self.docked:  # only its height is its own
            self.conf["height"] = rect["height"]
        else:
            self.conf["free"] = rect
        save_settings(self.opts)

    # a split: its divider under it, as part of it --------------------------------

    def place(self, r: dict) -> None:
        if not self.div:
            return ChatView.place(self, r)
        d = self.DIV
        ChatView.place(self, {**r, "height": r["height"] - d})
        self.div.place(r["left"], r["top"] + r["height"] - d, r["width"], d)
        self.draw_div()

    def panel_now(self) -> dict:
        p = ChatView.panel_now(self)
        return {**p, "height": p["height"] + self.DIV} if self.div else p

    @property
    def hwnds(self) -> set:
        return ChatView.hwnds.fget(self) | ({self.div.hwnd} if self.div else set())

    def show(self, visible: bool) -> None:
        ChatView.show(self, visible)
        if self.div:
            self.div.show(visible)

    def keep_adjusted(self) -> None:
        self.keep(self.panel_now())

    def set_edit(self, on: bool) -> bool:
        return False if self.docked else ChatView.set_edit(self, on)  # a split goes where the panel goes

    def follow(self) -> None:
        if self.docked:
            if not self.grip:
                p = self.app.placed()
                h = int(self.conf.get("height") or 120)
                self.place({"left": p["left"], "top": p["top"] - h, "width": p["width"], "height": h})
            return
        if not self.msgs.edit and not self.grip and self.conf.get("free"):
            free = self.keep_on_screen(self.conf["free"])
            if free != self.conf["free"]:
                self.keep(free)
            self.place(free)

    def close(self) -> None:
        self.app.close_window(self)

    def destroy(self) -> None:
        if self.div:
            self.div.root.destroy()
        self.strip.root.destroy()
        self.msgs.root.destroy()


class ChatPanel(ChatView):
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
        self.read_rect = None      # the chat lines in the game's client coordinates
        self.want_fit = not opts["box"]
        self.user_hidden = False
        self.line = (opts["box"] or {}).get("line") or 24.0
        self.app, self.windows = self, []  # the main panel is a chat window too; extra ones come later
        self.build("CustomClassic Chat")
        self.root = self.msgs.root
        self.dismissed = None      # the game chat's line count when the ⚠ was clicked away
        self.covered = False       # the game is drawing something over its chat: step aside
        self.fit_asked = 0.0
        self.explained = False     # the "chat too small" note, once a session
        self.settings = None
        self.settings_vars: dict = {}  # Settings window controls that change from elsewhere too
        self.set_fonts()
        if not isinstance(opts.get("windows"), list):
            opts["windows"] = []
        self.windows = [ExtraChat(self, conf) for conf in opts["windows"]]
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
        if not demo:
            threading.Thread(target=login_listener, args=(self.events,), daemon=True).start()
        threading.Thread(target=overlay.hotkey_thread, args=(self.events, HOTKEYS), daemon=True).start()
        threading.Thread(target=demo_loop if demo else read_loop, args=(self,), daemon=True).start()
        self.tray = start_tray(self)
        if demo:  # no game: a 4-line panel near the bottom of the main screen
            w, h = 900, round(self.line * 4)
            self.place({"left": (self.root.winfo_screenwidth() - w) // 2, "top": self.root.winfo_screenheight() - h - 160,
                        "width": w, "height": h})
        self.root.after(100, self.pump)
        self.root.after(300, self.follow)
        self.apply_see_through()
        self.render()

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
        """A note just above the panel (and its splits) for 12 seconds; clicking it opens the Watch tab."""
        if self.toast is not None:
            self.toast.root.destroy()
        p = self.stack_now()
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

    @property
    def bar_px(self) -> int:
        """The scrollbar's width: the game's own as measured (divider and track), or a guess."""
        return int((self.opts["box"] or {}).get("bar") or bar_width(self.line))

    def auto_px(self) -> int:
        return max(11, round(self.line * 0.62))  # about the game's own chat text

    def set_fonts(self) -> None:
        import tkinter.font as tkfont
        self.font = tkfont.Font(family=FONT, size=-(self.opts["font_px"] or self.auto_px()))
        self.tab_font = tkfont.Font(family=FONT, size=-max(10, round(self.line * 0.5)))
        self.hint_font = tkfont.Font(family=FONT, size=-max(13, round(self.line * 0.85)), weight="bold")

    def warning(self) -> str | None:
        """Why lines may slip by, if they may: the game's chat is minimised or shows only one
        or two lines. Clicking the ⚠ puts it away until the chat's size changes again."""
        n = chat_lines(self.read_rect, self.line)
        if self.read_rect and n < self.opts["min_lines"] and n != self.dismissed:
            return f"the game's chat shows only {n} line{'s' if n != 1 else ''}"
        return None

    def explain(self, reason: str) -> None:
        self.events.put(("status", f"⚠ Lines may slip by: {reason}, so megaphones arriving together can scroll "
                                   "away unread. Make the game's chat taller to catch them all. Click ⚠ to hide this."))

    # placing ----------------------------------------------------------------

    # what this window does as the main panel ---------------------------------

    @property
    def see_through(self) -> bool:
        return bool(self.opts["see_through"])

    @property
    def is_free(self) -> bool:
        return bool(self.opts["unlocked"])

    def tab_chosen(self, name: str) -> None:
        self.opts["tab"] = name
        save_settings(self.opts)

    def keep(self, rect: dict) -> None:
        self.opts["free"] = rect
        save_settings(self.opts)

    def dismiss_warning(self) -> None:
        self.dismissed = chat_lines(self.read_rect, self.line)  # the ⚠ clicked: put away for this chat size

    def grip_on_chat(self, e) -> None:
        """The ≡ grip on the game's chat: the panel reaches higher than the game's chat, as the game's does."""
        if self.read_rect and self.game:
            y0, extra0, _ = self.grip
            c = self.game["client"]
            top_room = c["top"] + self.read_rect["top"]  # up to the top of the screen
            self.opts["extra"] = max(0, min(top_room, extra0 + (y0 - e.y_root)))
            read = {**self.read_rect, "left": c["left"] + self.read_rect["left"], "top": c["top"] + self.read_rect["top"]}
            self.place(panel_rect(read, self.opts["extra"], self.bar_px))

    def free_rect(self) -> dict:
        """Where an unlocked panel sits: where it was put, or back in view if that's off every monitor."""
        free = self.opts["free"] or self.panel_now()
        kept = self.keep_on_screen(free)
        if kept != free:
            self.keep(kept)
        return kept

    def render(self) -> None:
        """This window and the extra ones (which follow the panel's settings for what they leave out)."""
        views = [self, *self.windows]
        shown = {v.log.tab for v in views}  # a tab open in one of them is in view: no dot for it elsewhere
        for v in views:
            for name in shown:
                if name in v.log.unread:
                    v.log.unread[name] = False
        ChatView.render(self)
        for w in self.windows:
            w.log.hidden, w.log.hide_padded = self.log.hidden, self.log.hide_padded
            w.render()

    def apply_see_through(self) -> None:
        ChatView.apply_see_through(self)
        for w in self.windows:
            ChatView.apply_see_through(w)

    # extra chat windows -------------------------------------------------------

    def add_window(self) -> None:
        """A new chat window showing All, just above the panel, in adjust mode to be dragged where
        it should go (even off the game window)."""
        p = self.panel_now()
        h = max(p["height"], round(self.line * 8))
        conf = {"tab": "All", "see_through": False,
                "free": {"left": p["left"] + 30, "top": max(0, p["top"] - h - 30), "width": p["width"], "height": h}}
        self.opts["windows"].append(conf)
        w = ExtraChat(self, conf)
        self.windows.append(w)
        w.place(w.keep_on_screen(conf["free"]))
        w.set_edit(True)
        save_settings(self.opts)
        self.events.put(("status", "New chat window: drag it anywhere and its corner to resize, then press "
                                   "Ctrl+Alt+F5 to keep it there. Its ✕ closes it."))
        self.settings_changed()

    def add_split(self) -> None:
        """Split the chat: a pane with its own tab row on top of the panel, as wide as it and moving
        with it (Mega to start with, so megaphones sit above the chat). Its ≡ grip sets its height."""
        if not self.can_split():
            self.events.put(("status", "The chat is split already: its pane's ✕ removes the split."))
            return
        conf = {"dock": "above", "tab": "Mega", "see_through": False, "height": round(self.line * 5) + 20}
        self.opts["windows"].append(conf)
        w = ExtraChat(self, conf)
        self.windows.append(w)
        w.follow()
        save_settings(self.opts)
        self.settings_changed()

    def place(self, r: dict) -> None:
        ChatView.place(self, r)
        for w in self.windows:  # splits move with it
            if w.docked:
                w.follow()

    def can_split(self) -> bool:
        """One split at a time: a pane on top of the chat."""
        return not any(w.docked for w in self.windows)

    def stack_now(self) -> dict:
        """The panel with its splits on top: where it all sits on screen."""
        p = self.panel_now()
        top = min([p["top"]] + [w.panel_now()["top"] for w in self.windows if w.docked])
        return {**p, "top": top, "height": p["top"] + p["height"] - top}

    def close_window(self, w: "ExtraChat") -> None:
        self.windows.remove(w)
        self.opts["windows"] = [c for c in self.opts["windows"] if c is not w.conf]
        w.destroy()
        save_settings(self.opts)
        self.settings_changed()

    def settings_changed(self) -> None:
        """The settings window shows how many windows there are: tell it."""
        if self.settings_vars.get("windows"):
            self.settings_vars["windows"]()

    def follow(self) -> None:
        """Keep the panel on the game's chat box (or where it was put, when unlocked), the extra
        windows where they were put, and show them all while the game's window is open (not minimised)."""
        unlocked = self.opts["unlocked"]
        if unlocked and not self.msgs.edit and not self.grip:
            self.place(self.free_rect())
        for w in self.windows:
            w.follow()
        if not self.demo:
            game = game_geometry()
            self.game = game
            rect = from_relative(self.opts["box"], game["client"]) if game else None
            if game and not rect and not self.want_fit and not self.msgs.edit and time.time() - self.fit_asked > 10:
                self.want_fit, self.fit_asked = True, time.time()  # first start, or the game window changed size
            if game and rect and not self.msgs.edit:
                self.line = self.opts["box"]["line"]
                self.read_rect = {"left": rect["left"] - game["client"]["left"],
                                  "top": rect["top"] - game["client"]["top"], "width": rect["width"],
                                  "height": rect["height"]}
                if not unlocked:
                    self.place(panel_rect(rect, self.opts["extra"], self.bar_px))
                reason = self.warning()
                if reason and not self.explained:
                    self.explained = True
                    self.explain(reason)
            # shown as long as the game's window is open, in front or not; minimised to the taskbar
            # (no game window found then), everything hides
            up = bool(game) or self.always_show
            # unlocked, it isn't over the game's chat: nothing there to step aside for
            # (while typing in it, nothing the game draws over its chat sends it away)
            stays = unlocked or self.typing
            visible = bool(up and (rect or unlocked)) and not self.user_hidden and not (self.covered and not stays)
            self.show(visible)
            for w in self.windows:  # a split goes with the panel; a window is never over the game's chat
                w.show(visible if w.docked else up and not self.user_hidden)
        self.root.after(300, self.follow)

    def toggle_see_through(self) -> None:
        self.opts["see_through"] = not self.opts["see_through"]
        save_settings(self.opts)
        self.apply_see_through()

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
                    if data["kind"] in SPACER_KINDS and padded(data["body"]):
                        data["padded"] = padded_kind(data["body"])
                    if data.get("padded") not in self.log.hide_padded:  # left out: no alerts either
                        self.watched(data)
                    if self.relay and not self.demo:
                        self.relay.send(data)  # guild chat only, and only when sharing is on
                    self.log.add(data)
                    for w in self.windows:
                        w.log.notice(data)
                    if not self.demo:
                        save_message(HISTORY_FILE, data)
                    for v in [self, *self.windows]:  # reading history: keep the same lines in view
                        if v.scroll and shows(v.log.kinds(), data):
                            v.scroll_to(v.scroll + 1)
                    changed = True
                    if data["kind"] == "whisper" and not data["to"] and self.opts["whisper_sound"]:
                        import winsound
                        try:
                            winsound.PlaySound(str(self.chime), winsound.SND_FILENAME | winsound.SND_ASYNC)
                        except RuntimeError:
                            pass
                elif kind == "fit":
                    self.opts["box"] = data
                    self.line = data["line"]
                    self.set_fonts()
                    save_settings(self.opts)
                elif kind == "see_through":
                    self.toggle_see_through()
                    changed = True
                elif kind == "unlock":
                    self.set_unlocked(not self.opts["unlocked"])
                    changed = True
                elif kind == "window":
                    self.add_window()
                    changed = True
                elif kind == "split":
                    self.add_split()
                    changed = True
                elif kind == "settings":
                    self.open_settings()
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

    def on_hotkey(self, hk: int) -> None:
        if hk == HK_EDIT:  # adjust every window; pressed again, each keeps where it was put
            views = [self, *self.windows]
            if any(v.msgs.edit for v in views):
                for v in views:
                    if v.set_edit(False):
                        v.keep_adjusted()
            else:
                for v in views:
                    v.set_edit(True)
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

    def keep_adjusted(self) -> None:
        """Adjusting ended: keep the panel where it was put (unlocked), or take it as the game's
        chat box (on the chat)."""
        if self.opts["unlocked"]:
            self.keep(self.panel_now())
        elif self.game:
            c, p = self.game["client"], self.panel_now()
            extra = max(0, min(self.opts["extra"], p["height"] - 2 * round(self.line)))
            box = {"left": p["left"] - c["left"], "top": p["top"] - c["top"] + extra,
                   "width": p["width"] - self.bar_px, "height": p["height"] - extra, "bar": self.bar_px}
            self.opts["box"], self.opts["extra"] = to_relative(box, self.line, c), extra
            save_settings(self.opts)

    def set_unlocked(self, on: bool) -> None:
        """Unlocked: the panel can go anywhere, even off the game window, and it starts in
        adjust mode to be dragged there. It still reads the game's own chat. Locked again, it
        goes back onto the game's chat."""
        if on == bool(self.opts["unlocked"]):
            return
        self.opts["unlocked"] = on
        if on:
            self.opts["free"] = self.opts["free"] or self.panel_now()
            self.set_edit(True)
            self.events.put(("status", "Unlocked: drag the panel anywhere and its corner to resize, then press "
                                       "Ctrl+Alt+F5 to keep it there. Reset position puts it back on the game's chat."))
        else:
            self.set_edit(False)  # leave adjusting without saving it as the game's chat box
        self._where = None
        save_settings(self.opts)
        if self.settings_vars:
            self.settings_vars["unlocked"].set(on)

    def reset_position(self) -> None:
        """Back on the game's chat box, fitted again: for a panel put somewhere it can't be reached,
        or moved off the chat by accident."""
        self.set_unlocked(False)
        self.set_edit(False)
        self.opts["extra"], self.opts["free"], self.user_hidden = 0, None, False
        self.want_fit = True
        self._where = None
        save_settings(self.opts)

    # settings -----------------------------------------------------------------

    def set_text_size(self, px: int | None) -> None:
        self.opts["font_px"] = px
        self.set_fonts()
        self.render()
        save_settings(self.opts)

    def game_name(self) -> str:
        """Your character's name for what you type in the Guild tab: as set, or your first
        character name from the Chat page."""
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
            for v in [self, *self.windows]:
                for w in (v.msgs, v.strip):
                    w.canvas.configure(bg=chosen)
        else:
            self.opts["colors"] = {**self.opts["colors"], key: chosen}
        self.set_opt(key if key == "panel_bg" else "colors", self.opts[key if key == "panel_bg" else "colors"])

    def reset_colours(self) -> None:
        self.opts["colors"], self.opts["panel_bg"] = {}, None
        for v in [self, *self.windows]:
            v.msgs.canvas.configure(bg=PANEL)
            v.strip.canvas.configure(bg=STRIP)
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
        self.log.set_tabs(self.tabs(), new if old and self.log.tab == old else None)
        self.opts["tab"] = self.log.tab
        for w in self.windows:
            w.log.set_tabs(self.tabs(), new if old and w.log.tab == old else None)
            w.conf["tab"] = w.log.tab

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
        """Join the guild's channel set in Settings: when sharing, showing the Guild tab, or as
        the guild's admin (whose app keeps the guild's details there and reads Discord for all)."""
        if self.relay:
            self.relay.stop()
            self.relay = None
        o, code = self.opts, guild_relay.guild_key(self.opts["relay_code"])
        admin = o["relay_admin"].get(code) if code else None
        if code and (o["relay_share"] or o["relay_tab"] or admin) and not self.demo:
            self.relay = guild_relay.GuildPeer(code, o["relay_reader"], self.events.put, o["relay_share"],
                                               o["relay_tab"], o["relay_source"], cfg=o["relay_cfg"].get(code),
                                               admin=admin, login=o["guild_login"])
            self.relay.game_name = self.game_name()

    def set_relay(self, code: str, share: bool, tab: bool, source: str | None = None) -> None:
        self.opts["relay_code"] = guild_relay.guild_key(code)
        self.opts["relay_share"], self.opts["relay_tab"] = share, tab
        if source in dict(guild_relay.SOURCES):
            self.opts["relay_source"] = source
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
    ChatPanel(load_settings(), demo="--demo" in argv, always_show="--always-show" in argv,
              verbose="--verbose" in argv).root.mainloop()


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
