"""Logins from the bot's magic link, and typing in the Guild tab."""
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
import ccchat_bot as bot  # noqa: E402
import customclassic_chat as mc  # noqa: E402
import guild_relay as g  # noqa: E402

KEY = Ed25519PrivateKey.generate()
PUBLIC = bot.public_key_text(KEY)


def login(name="Rowan", server="555", days=1, key=KEY):
    now = time.time()
    return g.sign_login(key, {"uid": "1", "name": name, "server": server, "iat": now, "exp": now + days * 86400})


def test_only_the_bots_own_logins_count():
    assert g.check_login(login(), PUBLIC)["name"] == "Rowan"
    assert g.check_login(login(days=-1), PUBLIC) is None  # run out
    assert g.check_login(login(key=Ed25519PrivateKey.generate()), PUBLIC) is None  # someone else's key
    body, sig = login().split(".")
    forged = g._b64(b'{"uid":"1","name":"Admin","server":"555","exp":9999999999}')
    assert g.check_login(forged + "." + sig, PUBLIC) is None  # the name changed after signing
    assert g.check_login("junk", PUBLIC) is None and g.check_login(login(), "") is None
    link = bot.login_link(KEY, "1", "Rowan", "555")
    assert link.startswith("http://127.0.0.1:47321/login?t=") and g.check_login(link.split("t=")[1], PUBLIC)


def peers(cfg=None):
    heard, said = [], []
    cfg = cfg or {"webhook": "https://discord.com/api/webhooks/123456789012/" + "a" * 40, "server_id": "555"}
    a = g.GuildPeer("ABCD-EFGH-JKLM", "pc-a", [].append, False, True, connect=False, cfg=cfg, bot_key=PUBLIC,
                    post=lambda url, user, text: said.append((user, text)))
    b = g.GuildPeer("ABCD-EFGH-JKLM", "pc-b", heard.append, False, True, connect=False, cfg=cfg, bot_key=PUBLIC)
    a.say = lambda data, retain=False, sub="chat": b.heard(a.seal.seal({**data, "id": str(time.time()), "from": "pc-a"}))
    return a, b, heard, said


def test_typing_reaches_the_guild_signed():
    a, b, heard, said = peers()
    assert "log in" in a.say_chat("hi")  # no login: nothing goes
    assert not heard
    a.login = login()
    assert a.say_chat("hi all @everyone") == ""
    time.sleep(0.3)  # the post to Discord goes on its own thread
    [(kind, msg)] = heard
    assert (msg["kind"], msg["name"], msg["body"]) == ("guildsay", "Rowan ✓", "hi all @​everyone")
    assert said == [("Rowan · app", "hi all @​everyone")]


def test_what_you_type_shows_once_for_you():
    shown = []
    cfg = {"webhook": "https://discord.com/api/webhooks/123456789012/" + "a" * 40, "server_id": "555"}
    a = g.GuildPeer("ABCD-EFGH-JKLM", "pc-a", shown.append, False, True, connect=False, cfg=cfg, bot_key=PUBLIC,
                    post=lambda url, user, text: None, login=login())
    sent = []
    a.clients = [type("Broker", (), {"publish": lambda self, topic, blob, **kw: sent.append(blob)})()] * 2
    assert a.say_chat("hi") == ""
    for blob in sent:  # both brokers hand it back
        a.heard(blob)
    assert [m[1]["body"] for m in shown if m[0] == "msg"] == ["hi"]


def test_a_faked_or_foreign_login_shows_unverified():
    a, b, heard, _ = peers()
    a.login = login(server="999")  # a login from another Discord server
    b.heard(a.seal.seal({"t": "say", "text": "hi", "login": a.login, "name": "Rowan", "id": "1", "from": "pc-a"}))
    b.heard(a.seal.seal({"t": "say", "text": "hi", "login": "made.up", "name": "Admin", "id": "2", "from": "pc-x"}))
    assert [m[1]["name"] for m in heard] == ["Rowan (unverified)", "Admin (unverified)"]


def test_the_magic_link_reaches_the_app(monkeypatch):
    monkeypatch.setattr(g, "LOGIN_PORT", 47399)
    monkeypatch.setattr(g, "SHARED_BOT_KEY", PUBLIC)
    events = queue.Queue()
    threading.Thread(target=mc.login_listener, args=(events,), daemon=True).start()
    time.sleep(0.5)
    token = login()
    with urllib.request.urlopen(f"http://127.0.0.1:47399/login?t={token}") as r:
        assert r.status == 200 and "logged in as Rowan" in r.read().decode()
    assert events.get(timeout=2) == ("login", token)
    try:
        urllib.request.urlopen("http://127.0.0.1:47399/login?t=made.up")
        assert False, "a made-up login was accepted"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    assert events.empty()
