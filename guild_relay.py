"""The guild chat relay, from CustomClassic Chat's side (opt-in, off until turned on in Settings).

A guild's members share one guild code. With "Share my guild chat" on, the guild lines this app
reads go to the relay (with the game's own time stamp: server time, the same on every screen),
which drops the copies other members send of the same message and posts each one to the
guild's Discord channel once. With "Show the Discord channel" on, the channel's messages come
back for a Discord tab. Only guild chat is ever sent: never whispers, party, buddy or map chat.
Nothing is ever typed into the game.
"""

from __future__ import annotations

import queue
import re
import secrets
import threading

RELAY_URL = "https://mapleprice.mentula.tv"
CODE = re.compile(r"^[A-Z2-9]{4}-?[A-Z2-9]{4}$")


def guild_code(text: str) -> str:
    """'abcd-efgh', 'ABCDEFGH' or ' abcd efgh ' as ABCD-EFGH; '' when it isn't a guild code."""
    t = re.sub(r"[\s]", "", (text or "").upper())
    if not CODE.match(t):
        return ""
    t = t.replace("-", "")
    return f"{t[:4]}-{t[4:]}"


def reader_id() -> str:
    """This install's id for the relay: random, no name in it."""
    return "pc-" + secrets.token_hex(8)


def relay_line(msg: dict) -> dict | None:
    """A guild message as the relay takes it, or None for anything that must not go."""
    if msg.get("kind") != "guild" or not msg.get("stamp") or not msg.get("name") or not msg.get("body"):
        return None
    return {"stamp": msg["stamp"], "speaker": msg["name"][:20], "text": msg["body"][:300]}


def _client():
    import httpx
    return httpx.Client(timeout=10, headers={"User-Agent": "CustomClassicChat"})


def create_guild(base: str, name: str, webhook_url: str) -> dict:
    """Set up a relay for a guild from its Discord webhook: {code, admin_key, name}, or raises
    ValueError with the reason to show."""
    with _client() as c:
        r = c.post(f"{base}/api/relay/guilds", json={"name": name, "webhook_url": webhook_url})
    if r.status_code != 200:
        try:
            reason = r.json().get("detail") or r.json().get("error")
        except ValueError:
            reason = None
        raise ValueError(reason or f"The relay said no (error {r.status_code}).")
    return r.json()


def guild_info(base: str, code: str) -> dict | None:
    with _client() as c:
        r = c.get(f"{base}/api/relay/{code}")
    return r.json() if r.status_code == 200 else None


def remove_guild(base: str, code: str, admin_key: str) -> bool:
    with _client() as c:
        return c.post(f"{base}/api/relay/{code}/remove", json={"admin_key": admin_key}).status_code == 200


class RelayClient:
    """Sends this app's guild lines to the relay and, if asked, brings the Discord channel back
    as messages for the Discord tab (handed to `put`, as the chat reader does)."""

    def __init__(self, base: str, code: str, reader: str, put, share: bool, tab: bool):
        self.base, self.code, self.reader, self.put = base, code, reader, put
        self.share, self.tab = share, tab
        self.out: queue.Queue = queue.Queue()
        self.stopped = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self) -> None:
        self.stopped.set()

    def send(self, msg: dict) -> None:
        line = relay_line(msg) if self.share else None
        if line:
            self.out.put(line)

    def run(self) -> None:
        import time
        after, said, last_poll = 0, None, 0.0
        with _client() as c:
            while not self.stopped.wait(1.5):
                lines = []
                while not self.out.empty() and len(lines) < 50:
                    lines.append(self.out.get_nowait())
                try:
                    if lines:
                        c.post(f"{self.base}/api/relay/{self.code}/lines", json={"reader": self.reader, "lines": lines})
                    if self.tab and time.time() - last_poll >= 3:
                        last_poll = time.time()
                        r = c.get(f"{self.base}/api/relay/{self.code}/discord", params={"after": after})
                        if r.status_code == 404:
                            raise LookupError("unknown guild code")
                        data = r.json()
                        for m in data.get("messages", []):
                            after = max(after, m["id"])
                            self.put(("msg", {"kind": "discord", "name": m["author"], "body": m["text"], "at": time.time(),
                                              "time": time.strftime("%H:%M"), "to": None, "fg": None, "bg": None}))
                        if not data.get("discord_tab") and said != "no bot":
                            said = "no bot"
                            self.put(("status", "Discord tab: the relay can't read Discord channels yet (no bot set up)."))
                    if said not in (None, "no bot"):
                        said = None
                        self.put(("status", "Guild relay: connected again."))
                except LookupError:
                    if said != "unknown":
                        said = "unknown"
                        self.put(("status", "Guild relay: the guild code isn't known (removed?). Check Settings → Discord."))
                except Exception:
                    if said != "lost":
                        said = "lost"
                        self.put(("status", "Guild relay: can't reach the relay right now; trying again."))
