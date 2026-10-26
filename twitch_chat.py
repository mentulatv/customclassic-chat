"""Twitch chat for CustomClassic Chat: a channel's chat, read anonymously by its name.

Twitch lets anyone read a channel's chat as a guest ("justinfan" + a number) over its chat
server, so no login, key or app is needed, and nothing is ever sent to the chat. Messages
arrive with the chatter's display name and name colour.
"""

from __future__ import annotations

import random
import re
import socket
import ssl
import threading
import time

HOST, PORT = "irc.chat.twitch.tv", 6697  # Twitch chat over TLS
CHANNEL = re.compile(r"^[a-z0-9_]{3,25}$")
IRC = re.compile(r"^(?:@(?P<tags>\S+) )?(?::(?P<prefix>\S+) )?(?P<cmd>\S+)(?: (?P<params>.*))?$")
# Twitch's colours for chatters who never picked one
DEFAULT_COLORS = ["#ff4b4b", "#4b7bff", "#3fc33f", "#b22222", "#ff7f50", "#9acd32", "#ff4500", "#2e8b57",
                  "#daa520", "#d2691e", "#5f9ea0", "#1e90ff", "#ff69b4", "#8a2be2", "#00ff7f"]


def channel_name(text: str) -> str:
    """The channel from what was typed: "MentulaTV", "#mentulatv" or a twitch.tv link."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(?:https?://)?(?:www\.)?twitch\.tv/", "", t).strip("#/ ")
    return t if CHANNEL.match(t) else ""


def unescape(v: str) -> str:
    return v.replace("\\s", " ").replace("\\:", ";").replace("\\r", "").replace("\\n", " ").replace("\\\\", "\\")


def parse(line: str) -> dict | None:
    """One line from Twitch's chat server: {tags, prefix, cmd, params, text}."""
    m = IRC.match(line)
    if not m:
        return None
    tags = {}
    for part in (m["tags"] or "").split(";"):
        if part:
            k, _, v = part.partition("=")
            tags[k] = unescape(v)
    params, text = m["params"] or "", None
    if " :" in params:
        params, text = params.split(" :", 1)
    elif params.startswith(":"):
        params, text = "", params[1:]
    return {"tags": tags, "prefix": m["prefix"] or "", "cmd": m["cmd"], "params": params.split(), "text": text}


def readable(color: str) -> str:
    """A chatter's colour, lightened when it's too dark to read on the dark panel."""
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError):
        return "#bf94ff"
    light = 0.299 * r + 0.587 * g + 0.114 * b
    if light < 110:  # mix towards white until it reads
        t = (110 - light) / (255 - light)
        r, g, b = (round(v + (255 - v) * t) for v in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def message(msg: dict, now: float) -> dict | None:
    """A chat message as CustomClassic Chat shows it, or None for anything else."""
    if msg["cmd"] != "PRIVMSG" or msg["text"] is None:
        return None
    tags, text = msg["tags"], msg["text"]
    login = msg["prefix"].split("!", 1)[0]
    if text.startswith("\x01ACTION ") and text.endswith("\x01"):  # /me
        text = text[8:-1]
    color = tags.get("color") or DEFAULT_COLORS[sum(map(ord, login)) % len(DEFAULT_COLORS)]
    return {"kind": "twitch", "time": time.strftime("%H:%M", time.localtime(now)),
            "name": tags.get("display-name") or login, "body": text.strip(), "at": now, "to": None,
            "fg": readable(color), "bg": None}


class TwitchChat:
    """Reads one channel's chat in the background and hands each message to `put`. It
    reconnects by itself, waiting longer each time the connection drops."""

    def __init__(self, channel: str, put):
        self.channel, self.put = channel, put
        self.stopped = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self) -> None:
        self.stopped.set()

    def run(self) -> None:
        backoff, said = 1, None
        while not self.stopped.is_set():
            sock = None
            try:
                raw = socket.create_connection((HOST, PORT), timeout=15)
                sock = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
                sock.settimeout(1)  # wake up every second to see whether to stop
                nick = f"justinfan{random.randint(10000, 99999)}"
                sock.sendall(f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nPASS SCHMOOPIIE\r\nNICK {nick}\r\n"
                             f"JOIN #{self.channel}\r\n".encode())
                buf, heard = b"", time.time()
                while not self.stopped.is_set():
                    try:
                        data = sock.recv(8192)
                    except (socket.timeout, ssl.SSLWantReadError):
                        if time.time() - heard > 360:  # Twitch pings every ~5 minutes
                            raise ConnectionError("no word from Twitch")
                        continue
                    if not data:
                        raise ConnectionError("Twitch closed the connection")
                    heard, buf = time.time(), buf + data
                    *lines, buf = buf.split(b"\r\n")
                    for line in (ln.decode("utf-8", "replace") for ln in lines):
                        if line.startswith("PING"):
                            sock.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                            continue
                        msg = parse(line)
                        if not msg:
                            continue
                        if msg["cmd"] == "ROOMSTATE" and said != "joined":
                            said, backoff = "joined", 1
                            self.put(("status", f"Twitch: reading #{self.channel}'s chat."))
                        elif msg["cmd"] == "RECONNECT":
                            raise ConnectionError("Twitch asked to reconnect")
                        else:
                            m = message(msg, time.time())
                            if m and m["body"]:
                                self.put(("msg", m))
            except Exception as e:
                if not self.stopped.is_set() and said != "lost":
                    said = "lost"
                    self.put(("status", f"Twitch: lost #{self.channel}'s chat ({e.__class__.__name__}); trying again."))
            finally:
                try:
                    sock and sock.close()
                except Exception:
                    pass
            self.stopped.wait(backoff)
            backoff = min(backoff * 2, 60)
