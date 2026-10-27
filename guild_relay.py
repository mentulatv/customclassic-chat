"""Guild chat to Discord, peer to peer (opt-in, off until turned on in Settings).

Nothing to host and no server of anyone's in the middle: the members' own apps meet on a
channel at two free public message brokers (MQTT, as smart-home devices use), named and
encrypted from the guild code, so only members can find it or read it. The brokers only pass
sealed messages along, and with two of them one being down doesn't matter.

- The guild's admin creates the guild in their app: a guild code, plus the guild's Discord
  webhook, which their app leaves on the channel (encrypted, kept by the brokers) for members'
  apps to pick up; each member's app keeps a copy.
- Each app that shares announces the lines it reads, with the game's own time stamp (server
  time, the same on every screen). After a few seconds every app has heard every member's
  reading of a message, matches them up the same way (same minute, same speaker, nearly the
  same text) and agrees on its best wording and on who posts it: the member with the lowest
  id among those who saw it. That one app posts it to the webhook; the others stay quiet. So
  one message is one post, however many members read it.
- The Guild tab: reading Discord takes a bot, and its token stays with the admin; the
  admin's app reads the channel and passes new messages along the same encrypted channel.

Only the one kind of chat chosen to share is ever sent: guild chat (map chat or whispers only
to test, before the game has guild chat). Nothing is ever typed into the game.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import ssl
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field

from rapidfuzz import fuzz

BROKERS = [("broker.emqx.io", 8883), ("broker.hivemq.com", 8883)]  # free public MQTT brokers, over TLS
# the shared CustomClassic Chat bot (bot/ccchat_bot.py): its public application id, for its invite link,
# and the public half of the key it signs logins with (/chatlink), for every app to check them
SHARED_BOT_ID = "1564435368072192102"
SHARED_BOT_KEY = "3e9sP7ifaw8Yi7safdCydoBAuGHuqjlRx_7Tmm748s4"
LOGIN_PORT = 47321  # the magic link opens http://127.0.0.1:47321/login?t=…: this app, on this PC only
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I: easy to read out
CODE = re.compile(r"^[A-Z2-9]{12}$")
WEBHOOK = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/(\d{5,25})/([\w-]{20,120})$")
# what can be shared: guild chat, or, to test before the game has guild chat, map chat or whispers
SOURCES = [("guild", "Guild chat"), ("map", "Map chat (for testing)"), ("whisper", "Whispers (for testing)")]
HOLD = 3.0  # seconds every app waits for the other members' readings of a message
KEEP = 900  # seconds a posted message is remembered, so late readings of it are dropped
SAME_TEXT, SAME_NAME = 88, 80  # how alike two readings must be (0-100) to be one message
DISCORD_API = "https://discord.com/api/v10"


# ------------------------------------------------------------------ the guild code


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def guild_code(text: str) -> str:
    """'abcd efgh jklm', 'ABCD-EFGH-JKLM' … as ABCD-EFGH-JKLM; '' when it isn't a guild code."""
    t = re.sub(r"[\s-]", "", (text or "").upper())
    return f"{t[:4]}-{t[4:8]}-{t[8:]}" if CODE.match(t) and all(c in ALPHABET for c in t) else ""


GUILD_NAME = re.compile(r"^[A-Za-z0-9]{2,16}$")  # MapleStory guild names: letters and digits


def guild_key(text: str) -> str:
    """What a member typed to join, as the key their app uses: a guild code (ABCD-EFGH-JKLM), or,
    for guilds whose admin chose it, the guild's name ("name:mapleguild"); '' for neither."""
    code = guild_code(text)
    if code:
        return code
    t = (text or "").strip()
    t = t[5:] if t.lower().startswith("name:") else t
    return f"name:{t.lower()}" if GUILD_NAME.match(t) else ""


def key_label(key: str) -> str:
    """How a key shows in Settings: the code, or the guild's name."""
    return key[5:] if key.startswith("name:") else key


class Seal:
    """The guild's key, from its code: it names the channel and seals every message on it."""

    def __init__(self, code: str):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.key = hashlib.pbkdf2_hmac("sha256", code.replace("-", "").encode(), b"customclassic-chat guild", 200_000)
        self.aead = AESGCM(self.key)
        self.topic = "ccchat/" + hashlib.sha256(b"topic:" + self.key).hexdigest()[:32]

    def seal(self, data: dict) -> bytes:
        nonce = os.urandom(12)
        return nonce + self.aead.encrypt(nonce, json.dumps(data).encode(), self.topic.encode())

    def open(self, blob: bytes) -> dict | None:
        try:
            return json.loads(self.aead.decrypt(blob[:12], blob[12:], self.topic.encode()))
        except Exception:
            return None  # not sealed with this guild's key: someone else's, or junk


def reader_id() -> str:
    """This install's id among the guild's apps: random, no name in it."""
    return "pc-" + secrets.token_hex(8)


# ------------------------------------------------------------------ what's shared


def relay_line(msg: dict, source: str = "guild") -> dict | None:
    """A message as it's shared, or None for anything that must not go: only the one chat type
    chosen to share (guild chat; map chat or whispers when testing), with the game's stamp."""
    if source not in dict(SOURCES) or msg.get("kind") != source:
        return None
    if not msg.get("stamp") or not msg.get("name") or not msg.get("body"):
        return None
    return {"stamp": msg["stamp"], "speaker": msg["name"][:20], "text": msg["body"][:300], "kind": source}


def clean(text: str) -> str:
    """Plain text for Discord: no pings (@everyone, @here, <@id>)."""
    text = re.sub(r"@(everyone|here)", "@​\\1", text)
    text = re.sub(r"<(@[!&]?|#)(\d+)>", "<\\1​\\2>", text)
    return re.sub(r"\s+", " ", text).strip()[:1900]


def slips(text: str) -> int:
    """How many of text recognition's usual misreadings a text shows ("rn" for m, a digit in a word)."""
    t = text.lower()
    return t.count("rn") + t.count("vv") + t.count("cl") + len(re.findall(r"[a-z][01][a-z]", t))


@dataclass
class Pending:
    """One message being collected from every member's reading of it."""
    stamp: str
    speaker: str
    kind: str
    first: float
    versions: Counter = field(default_factory=Counter)  # each reading's text, how many saw it so
    readers: set = field(default_factory=set)

    def best(self) -> str:
        """What most readers saw; among equals, fewer misreadings, then the longest (not cut off)."""
        return max(self.versions.items(), key=lambda kv: (kv[1], -slips(kv[0]), len(kv[0])))[0]

    def poster(self) -> str:
        """Who posts it: the lowest id among those who read it. Every app works it out alike."""
        return min(self.readers)

    def same(self, stamp: str, speaker: str, text: str, kind: str) -> bool:
        if self.stamp != stamp or self.kind != kind:
            return False
        if self.speaker.lower() != speaker.lower() and fuzz.ratio(self.speaker.lower(), speaker.lower()) < SAME_NAME:
            return False
        best = self.versions.most_common(1)[0][0]
        return text == best or fuzz.ratio(best.lower(), text.lower()) >= SAME_TEXT


class Matcher:
    """Every member's readings, matched into messages. Each app runs one and, hearing the same
    readings, comes to the same messages, wording and poster as all the others."""

    def __init__(self):
        self.pending: list[Pending] = []
        self.posted: deque = deque()  # (Pending, when) for late readings to match
        self.lock = threading.Lock()

    def add(self, reader: str, line: dict, now: float) -> bool:
        """One member's reading; False when it's of a message already decided."""
        stamp, speaker, text, kind = line["stamp"], line["speaker"].strip()[:20], clean(line["text"]), line["kind"]
        if not stamp or not speaker or not text:
            return False
        with self.lock:
            while self.posted and now - self.posted[0][1] > KEEP:
                self.posted.popleft()
            if any(p.same(stamp, speaker, text, kind) for p, _ in self.posted):
                return False
            hit = next((p for p in self.pending if p.same(stamp, speaker, text, kind)), None)
            if hit is None:
                hit = Pending(stamp, speaker, kind, now)
                self.pending.append(hit)
            if reader not in hit.readers:
                hit.readers.add(reader)
                hit.versions[text] += 1
            return True

    def due(self, now: float) -> list[Pending]:
        """Messages whose wait is over, oldest first; from now on they count as decided."""
        with self.lock:
            ready = [p for p in self.pending if now - p.first >= HOLD]
            self.pending = [p for p in self.pending if now - p.first < HOLD]
            self.posted.extend((p, now) for p in ready)
        return ready


# ------------------------------------------------------------------ logins (magic links from the bot)


def _b64(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_login(private_key, claims: dict) -> str:
    """A login, as the bot makes it: the claims (Discord user id and name, server, expiry), signed."""
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return body + "." + _b64(private_key.sign(body.encode()))


def check_login(token: str, public_key: str = "", now: float | None = None) -> dict | None:
    """The claims of a login the bot signed and that hasn't run out; None for anything else."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = public_key or SHARED_BOT_KEY
    if not key or not token or token.count(".") != 1:
        return None
    body, sig = token.split(".")
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(key)).verify(_unb64(sig), body.encode())
        claims = json.loads(_unb64(body))
    except Exception:
        return None
    if not isinstance(claims, dict) or (now or time.time()) > float(claims.get("exp", 0)):
        return None
    return claims


# ------------------------------------------------------------------ talking to Discord


def check_webhook(url: str) -> dict:
    """The webhook's own details from Discord (its id and channel), or ValueError saying why not."""
    m = WEBHOOK.match(url.strip())
    if not m:
        raise ValueError("That isn't a Discord webhook link (channel settings → Integrations → Webhooks → Copy URL).")
    import httpx
    try:
        r = httpx.get(url.strip(), timeout=10)
    except Exception:
        raise ValueError("Discord couldn't be reached. Try again in a minute.")
    if r.status_code != 200 or r.json().get("id") != m.group(1):
        raise ValueError("Discord doesn't know that webhook. Copy its link again.")
    return {"webhook_id": m.group(1), "channel_id": str(r.json().get("channel_id") or "")}


def post_webhook(url: str, username: str, content: str) -> None:
    import httpx
    payload = {"username": username[:80], "content": content, "allowed_mentions": {"parse": []}}
    for _ in range(3):
        r = httpx.post(url, json=payload, timeout=10)
        if r.status_code == 429:  # Discord's rate limit: wait as long as it says
            time.sleep(min(10.0, float(r.json().get("retry_after", 1))))
            continue
        r.raise_for_status()
        return


def read_channel(bot_token: str, channel_id: str, after: str | None) -> list[dict]:
    import httpx
    url = f"{DISCORD_API}/channels/{channel_id}/messages?limit=50" + (f"&after={after}" if after else "")
    r = httpx.get(url, headers={"Authorization": f"Bot {bot_token}"}, timeout=10)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ one app among the guild's


class GuildPeer:
    """This app on the guild's channel: shares what it reads (if asked), takes part in deciding
    who posts what, posts its share, and brings the Guild tab's messages (if asked). As the
    guild's admin (admin set) it also keeps the guild's details on the channel and, with a bot,
    reads the Discord channel for everyone."""

    def __init__(self, code: str, reader: str, put, share: bool, tab: bool, source: str = "guild",
                 cfg: dict | None = None, admin: dict | None = None, connect=True, post=None, read=None,
                 login: str = "", bot_key: str = ""):
        self.code, self.reader, self.put = code, reader, put
        self.share, self.tab, self.source = share, tab, source
        self.cfg = dict(cfg or {})  # the guild's details as last heard: name, webhook, webhook_id, channel_id
        self.admin = admin  # the admin's own: the same, plus the bot token (never sent anywhere)
        if admin:
            self.cfg = {k: admin[k] for k in ("name", "webhook", "webhook_id", "channel_id") if k in admin}
            self.cfg["has_bot"] = bool(admin.get("bot"))
        self.login = login  # this app's signed login (from the magic link), for typing in the Guild tab
        self.bot_key = bot_key  # the bot's public key (tests give their own)
        self.post = post or post_webhook
        self.read = read or read_channel
        self.seal = Seal(code)
        self.matcher = Matcher()
        self.seen: deque = deque(maxlen=500)  # envelope ids: each message comes from both brokers
        self.peers: dict[str, dict] = {}  # reader -> {at, share, tab}: who's around
        self.discord_after: str | None = None
        self.shared = self.posted = 0  # this session: lines this app shared, messages it posted
        self.error = ""  # the last thing that went wrong posting, to show in Settings
        self.clients: list = []
        self.stopped = threading.Event()
        if connect:
            self.connect()
            threading.Thread(target=self.run, daemon=True).start()

    # the channel ---------------------------------------------------------------

    def connect(self) -> None:
        import paho.mqtt.client as mqtt
        for host, port in BROKERS:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="cc-" + uuid.uuid4().hex[:16])
            c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            c.on_connect = lambda cl, u, f, rc, p=None: cl.subscribe(self.seal.topic + "/#", qos=1)
            c.on_message = lambda cl, u, m: self.heard(m.payload)
            c.reconnect_delay_set(2, 60)
            try:
                c.connect_async(host, port, 30)
                c.loop_start()
                self.clients.append(c)
            except Exception:
                pass

    def say(self, data: dict, retain: bool = False, sub: str = "chat") -> None:
        """Seal a message and hand it to every broker."""
        mid = uuid.uuid4().hex
        self.seen.append(mid)  # the brokers send it back to us too: already handled here
        blob = self.seal.seal({**data, "id": mid, "from": self.reader})
        for c in self.clients:
            try:
                c.publish(f"{self.seal.topic}/{sub}", blob, qos=1, retain=retain)
            except Exception:
                pass

    def heard(self, blob: bytes, now: float | None = None) -> None:
        msg = self.seal.open(blob)
        if not msg or msg.get("id") in self.seen:
            return
        self.seen.append(msg.get("id"))
        now = time.time() if now is None else now
        t = msg.get("t")
        if t == "read" and isinstance(msg.get("line"), dict):  # one member's reading of a line
            line = msg["line"]
            if line.get("kind") in dict(SOURCES) and all(isinstance(line.get(k), str) for k in ("stamp", "speaker", "text")):
                self.matcher.add(str(msg.get("from")), line, now)
        elif t == "cfg" and not self.admin:
            cfg = msg.get("cfg") or {}
            if cfg.get("closed"):
                self.cfg = {"closed": True}
                self.put(("status", "Guild chat to Discord: the guild's admin has closed this guild."))
            elif WEBHOOK.match(str(cfg.get("webhook", ""))) and cfg != self.cfg:
                self.cfg = {k: str(cfg.get(k, ""))[:250] for k in ("name", "webhook", "webhook_id", "channel_id",
                                                                     "server_id")}
                self.cfg["has_bot"] = bool(cfg.get("has_bot"))
                self.put(("relay_cfg", (self.code, dict(self.cfg))))
        elif t == "hi":
            self.peers[str(msg.get("from"))] = {"at": now, "share": bool(msg.get("share")), "tab": bool(msg.get("tab"))}
        elif t == "say" and self.tab:  # a member typed in their Guild tab
            claims = check_login(str(msg.get("login", "")), self.bot_key, now)
            server = self.cfg.get("server_id")
            ok = bool(claims) and (not server or str(claims.get("server")) == server)
            name = str(claims["name"] if ok else msg.get("name", "?"))[:32]
            self.put(("msg", {"kind": "guildsay", "name": name + (" ✓" if ok else " (unverified)"),
                              "body": clean(str(msg.get("text", ""))), "at": now, "time": time.strftime("%H:%M"),
                              "to": None, "fg": None, "bg": None}))
        elif t == "discord" and self.tab:
            self.put(("msg", {"kind": "discord", "name": str(msg.get("author", "?"))[:32], "body": clean(str(msg.get("text", ""))),
                              "at": now, "time": time.strftime("%H:%M"), "to": None, "fg": None, "bg": None}))

    # this app's part ------------------------------------------------------------

    def send(self, msg: dict, now: float | None = None) -> None:
        """A line this app read: shared, if it's the chosen kind and sharing is on."""
        line = relay_line(msg, self.source) if self.share and not self.cfg.get("closed") else None
        if line and self.matcher.add(self.reader, line, time.time() if now is None else now):
            self.shared += 1
            self.say({"t": "read", "line": line})

    def say_chat(self, text: str) -> str:
        """Something typed in the Guild tab: to every member's Guild tab and the guild's Discord
        channel. Returns '' when it went, or why it couldn't."""
        claims = check_login(self.login, self.bot_key)
        if not claims:
            return "log in first: type /chatlink in your guild's Discord"
        text = clean(text)[:400]
        if not text:
            return ""
        self.say({"t": "say", "text": text, "login": self.login, "name": claims["name"]})
        self.put(("msg", {"kind": "guildsay", "name": claims["name"] + " ✓", "body": text, "at": time.time(),
                          "time": time.strftime("%H:%M"), "to": None, "fg": None, "bg": None}))
        if self.cfg.get("webhook"):
            threading.Thread(target=self._post_said, args=(claims["name"], text), daemon=True).start()
        return ""

    def _post_said(self, name: str, text: str) -> None:
        try:
            self.post(self.cfg["webhook"], f"{name} · app", text)
        except Exception as e:
            self.error = f"Discord refused a post ({e.__class__.__name__})"

    def decide(self, now: float | None = None) -> int:
        """Post the messages whose wait is over that are this app's to post."""
        sent = 0
        for p in self.matcher.due(time.time() if now is None else now):
            if p.poster() != self.reader:
                continue
            if not self.cfg.get("webhook"):
                self.error = "the guild's Discord details haven't arrived yet (from its admin's app)"
                continue
            try:
                self.post(self.cfg["webhook"], f"{p.speaker} · {p.kind}", p.best())
                sent += 1
                self.posted += 1
                self.error = ""
            except Exception as e:  # Discord down or the webhook gone: lost, the relay goes on, and says so
                self.error = f"Discord refused a post ({e.__class__.__name__})"
                self.put(("status", f"Guild chat to Discord: {self.error}."))
        return sent

    def wanted_tab(self, now: float) -> bool:
        return self.tab or any(p["tab"] and now - p["at"] < 120 for p in self.peers.values())

    def read_discord(self, now: float) -> None:
        """The admin's app with a bot: new messages in the guild's channel (people's, not the
        guild chat it relays) go out to the members' Guild tabs."""
        if not (self.admin and self.admin.get("bot") and self.cfg.get("channel_id")) or not self.wanted_tab(now):
            return
        try:
            msgs = self.read(self.admin["bot"], self.cfg["channel_id"], self.discord_after)
        except Exception:
            return
        first = self.discord_after is None
        for m in sorted(msgs, key=lambda m: int(m["id"])):
            if self.discord_after and int(m["id"]) <= int(self.discord_after):
                continue
            self.discord_after = m["id"]
            if first or m.get("webhook_id") == self.cfg.get("webhook_id") or not m.get("content"):
                continue  # the first look only marks where to start; and not our own relayed chat
            if m["content"].strip().lower() in ("!guildcode", "!guild code", "!ccchat"):
                self.answer_code()  # a player asking how to join: the answer goes to the channel
                continue
            author = m.get("author") or {}
            self.say({"t": "discord", "author": author.get("global_name") or author.get("username") or "?",
                      "text": m["content"]})

    def answer_code(self) -> None:
        try:
            self.post(self.cfg["webhook"], "CustomClassic Chat", join_text(self.code))
        except Exception:
            pass

    def run(self) -> None:
        last_hi = last_cfg = last_discord = 0.0
        while not self.stopped.wait(0.5):
            now = time.time()
            self.decide(now)
            if now - last_hi > 30:
                last_hi = now
                self.say({"t": "hi", "share": self.share, "tab": self.tab})
            if self.admin and now - last_cfg > 600:
                last_cfg = now
                self.say({"t": "cfg", "cfg": self.cfg}, retain=True, sub="cfg")
            if now - last_discord > 3:
                last_discord = now
                self.read_discord(now)

    def members(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return 1 + sum(1 for r, p in self.peers.items() if r != self.reader and now - p["at"] < 90)

    def close_guild(self) -> None:
        """The admin closes the guild: members' apps stop sharing to it."""
        self.say({"t": "cfg", "cfg": {"closed": True}}, retain=True, sub="cfg")

    def stop(self) -> None:
        self.stopped.set()
        for c in self.clients:
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                pass


def join_text(key: str) -> str:
    how = (f"the guild code **{key}**" if not key.startswith("name:") else
           f"the guild's name, **{key_label(key)}**")
    return (f"To bring your guild chat here and this channel into your game overlay: in CustomClassic Chat, "
            f"Settings → Discord, enter {how}, then tick what you want to share or see.")


def check_bot(token: str, channel_id: str) -> str:
    """The bot's name, once Discord confirms the token works and the bot can read the guild's
    channel; ValueError saying what to do otherwise."""
    import httpx
    headers = {"Authorization": f"Bot {token.strip()}"}
    try:
        me = httpx.get(f"{DISCORD_API}/users/@me", headers=headers, timeout=10)
        if me.status_code == 401:
            raise ValueError("That isn't a working bot token: copy it again (Bot → Reset Token).")
        me.raise_for_status()
        seen = httpx.get(f"{DISCORD_API}/channels/{channel_id}/messages?limit=1", headers=headers, timeout=10)
    except httpx.HTTPError:
        raise ValueError("Discord couldn't be reached. Try again in a minute.")
    if seen.status_code in (403, 404):
        raise ValueError("The bot can't see the channel yet: add it to your server with the button, and let it "
                         "view that channel.")
    if seen.status_code != 200:
        raise ValueError(f"Discord said no ({seen.status_code}).")
    return me.json().get("global_name") or me.json().get("username") or "the bot"


def shared_bot_invite() -> str:
    """The link that adds the shared CustomClassic Chat bot to a Discord server ('' until it exists)."""
    if not SHARED_BOT_ID:
        return ""
    return (f"https://discord.com/oauth2/authorize?client_id={SHARED_BOT_ID}&scope=bot%20applications.commands"
            "&permissions=536939520")  # view channel, send, read history, manage webhooks


def bot_invite(token: str) -> str:
    """The link that adds a bot to a server, worked out from its token (the part before the first
    dot is the bot's id): it asks only to see the channel and read its messages."""
    import base64
    first = token.strip().split(".")[0]
    try:
        bot_id = base64.b64decode(first + "=" * (-len(first) % 4)).decode()
    except Exception:
        return ""
    if not bot_id.isdigit():
        return ""
    return f"https://discord.com/oauth2/authorize?client_id={bot_id}&scope=bot&permissions=66560"  # view + history


def create_guild(name: str, webhook: str, bot: str = "", by_name: bool = False) -> dict:
    """The admin's new guild: {code, name, webhook, webhook_id, channel_id, bot}. Its code is a
    new random one, or (by_name) the guild's own name: easier to share, but anyone who knows the
    name can join. The webhook is checked with Discord, and how to join goes to the channel.
    Raises ValueError."""
    if by_name and not GUILD_NAME.match(name.strip()):
        raise ValueError("To join by the guild's name, type it as it is in the game (letters and digits).")
    info = check_webhook(webhook)
    key = guild_key(name) if by_name else new_code()
    guild = {"code": key, "name": name.strip()[:40], "webhook": webhook.strip(), "bot": bot.strip(), **info}
    post_webhook(guild["webhook"], "CustomClassic Chat", f"Guild chat relay set up for **{clean(name)[:40]}**. "
                 + join_text(key))
    return guild
