"""The CustomClassic Chat bot: one bot for every guild, an optional extra on top of the
peer-to-peer guild chat (which works without it).

What it does, for each Discord server that invites it:
  /bind        (server admins) binds the bot to the channel it's typed in: creates the channel's
               webhook (members' apps post through it directly), makes the guild code, posts and
               pins how to join, and leaves the guild's details on the guild's encrypted channel
               for members' apps to pick up.
               The same guild name bound again in another channel of the server moves there and
               keeps its code; a guild belongs to its Discord server (another server's guild of
               the same name is another guild, with its own code).
  /rename      (server admins) renames the guild bound to the channel; its code stays.
  /unbind      (server admins) undoes it: members' apps stop sharing, the webhook is removed.
  /guildcode   tells whoever asks the guild code, privately.
  /chatlink    gives whoever asks, privately, a link that logs their CustomClassic Chat in as their
               Discord name, signed by the bot, so they can type in the app's Guild tab and every
               member's app can check it's really them.
  The Guild tab: people's messages in a bound channel are passed, sealed, to the members' apps.

It never sees game chat in the clear: it only seals and publishes on the guild channels it set up.
Run it with DISCORD_BOT_TOKEN set (a .env next to this file works); it keeps its few records in
DATA_DIR/bot.sqlite3.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import ssl
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # guild_relay.py: the app's own sealing and codes
sys.path.insert(0, str(HERE))
import guild_relay as gr  # noqa: E402

log = logging.getLogger("ccchat-bot")
REPUBLISH_S = 600  # each guild's details are put on its channel again this often (brokers can forget)
LOGIN_DAYS = 90  # a /chatlink login lasts this long; then /chatlink again
INVITE_PERMISSIONS = 1024 + 2048 + 65536 + 536870912  # view channel, send, read history, manage webhooks


# ------------------------------------------------------------------ what it remembers


class Store:
    """The set-up guilds: Discord server and channel, the guild's key and name, its webhook."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS guilds(
            channel_id TEXT PRIMARY KEY, server_id TEXT NOT NULL, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            webhook TEXT NOT NULL, webhook_id TEXT NOT NULL, created REAL NOT NULL)""")
        self.db.commit()

    def add(self, server_id: str, channel_id: str, key: str, name: str, webhook: str, webhook_id: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO guilds VALUES (?,?,?,?,?,?,?)",
                            (channel_id, server_id, key, name, webhook, webhook_id, time.time()))
            self.db.commit()

    def by_channel(self, channel_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute("SELECT * FROM guilds WHERE channel_id=?", (channel_id,)).fetchone()

    def by_server(self, server_id: str) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute("SELECT * FROM guilds WHERE server_id=?", (server_id,)).fetchall()

    def by_name(self, server_id: str, name: str) -> sqlite3.Row | None:
        """The guild of this name already bound in this Discord server, if any."""
        with self.lock:
            return self.db.execute("SELECT * FROM guilds WHERE server_id=? AND lower(name)=lower(?)",
                                   (server_id, name.strip())).fetchone()

    def rename(self, channel_id: str, name: str) -> None:
        with self.lock:
            self.db.execute("UPDATE guilds SET name=? WHERE channel_id=?", (name, channel_id))
            self.db.commit()

    def key_taken(self, key: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM guilds WHERE key=?", (key,)).fetchone() is not None

    def remove(self, channel_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM guilds WHERE channel_id=?", (channel_id,))
            self.db.commit()

    def all(self) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute("SELECT * FROM guilds").fetchall()


# ------------------------------------------------------------------ the guild channels


def cfg_of(row) -> dict:
    """A guild's details as members' apps take them (the same fields an admin's app sends, and its
    Discord server, so a login only counts in the guild it came from)."""
    return {"name": row["name"], "webhook": row["webhook"], "webhook_id": row["webhook_id"],
            "channel_id": row["channel_id"], "server_id": row["server_id"], "has_bot": True}


def signing_key(path: Path):
    """The bot's key for signing logins: made on the first start, kept in the data folder (never
    leaves it). Its public half goes into the app (guild_relay.SHARED_BOT_KEY)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
    return key


def public_key_text(key) -> str:
    from cryptography.hazmat.primitives import serialization
    return gr._b64(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def login_link(key, user_id: str, name: str, server_id: str, now: float | None = None) -> str:
    """The magic link: opens the person's own CustomClassic Chat (on their PC) with their login."""
    now = time.time() if now is None else now
    token = gr.sign_login(key, {"uid": user_id, "name": name[:32], "server": server_id, "iat": int(now),
                                "exp": int(now + LOGIN_DAYS * 86400)})
    return f"http://127.0.0.1:{gr.LOGIN_PORT}/login?t={token}"


class Channels:
    """Publishing, sealed, on guilds' encrypted channels: one connection to each broker for all."""

    def __init__(self, connect: bool = True):
        self.seals: dict[str, gr.Seal] = {}
        self.clients: list = []
        self.sent: list = []  # (topic, sealed) when not connected: for tests
        if connect:
            import paho.mqtt.client as mqtt
            for host, port in gr.BROKERS:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ccbot-" + uuid.uuid4().hex[:16])
                c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                c.reconnect_delay_set(2, 60)
                c.on_connect = lambda cl, u, f, rc, p=None, h=host: log.info("relay %s: connected (%s)", h, rc)
                c.on_disconnect = lambda cl, u, f, rc, p=None, h=host: log.warning("relay %s: disconnected (%s)", h, rc)
                c.connect_async(host, port, 30)
                c.loop_start()
                self.clients.append(c)

    def seal(self, key: str) -> gr.Seal:
        if key not in self.seals:
            self.seals[key] = gr.Seal(key)
        return self.seals[key]

    def say(self, key: str, data: dict, sub: str = "chat", retain: bool = False) -> None:
        s = self.seal(key)
        blob = s.seal({**data, "id": uuid.uuid4().hex, "from": "bot"})
        topic = f"{s.topic}/{sub}"
        if not self.clients:
            self.sent.append((topic, blob))
        for c in self.clients:
            info = c.publish(topic, blob, qos=1, retain=retain)
            if info.rc:
                log.warning("relay: a %s message wasn't sent (%s)", data.get("t"), info.rc)

    def put_cfg(self, row) -> None:
        self.say(row["key"], {"t": "cfg", "cfg": cfg_of(row)}, sub="cfg", retain=True)

    def close(self, key: str) -> None:
        self.say(key, {"t": "cfg", "cfg": {"closed": True}}, sub="cfg", retain=True)

    def discord_message(self, key: str, author: str, text: str) -> None:
        self.say(key, {"t": "discord", "author": author[:32], "text": gr.clean(text)})


def guild_key_for(store: Store) -> str:
    """A new guild's key: a fresh random code no other guild has."""
    while True:
        key = gr.new_code()
        if not store.key_taken(key):
            return key


def should_pass_on(message, row) -> bool:
    """A Discord message for the members' Guild tabs: a person's, with words, not the guild's own relayed chat."""
    return bool(message.content) and not message.author.bot and str(message.webhook_id or "") != row["webhook_id"]


# ------------------------------------------------------------------ the bot


def make_bot(store: Store, channels: Channels, key=None):
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    intents.message_content = True  # the Guild tab: needs "Message Content Intent" switched on for the bot
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    async def sync(guild) -> None:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)  # a server gets the commands at once (global ones take up to an hour)

    @client.event
    async def on_ready():
        log.info("connected as %s to %d servers", client.user, len(client.guilds))
        for guild in client.guilds:
            try:
                await sync(guild)
            except Exception as e:
                log.warning("command sync for %s failed: %s", guild.id, e)
        for row in store.all():
            channels.put_cfg(row)
            channel = client.get_channel(int(row["channel_id"]))
            if channel is None or not channel.permissions_for(channel.guild.me).view_channel:
                log.warning("can't see %s's channel %s: its Discord messages won't reach the Guild tabs",
                            row["name"], row["channel_id"])

    @client.event
    async def on_guild_join(guild):
        await sync(guild)

    def is_admin(interaction: discord.Interaction) -> bool:
        return bool(getattr(interaction.user, "guild_permissions", None) and
                    interaction.user.guild_permissions.administrator)

    @tree.command(name="bind", description="Bind CustomClassic Chat to this channel: your guild's chat comes here.")
    @app_commands.describe(guild_name="Your guild's name in the game")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def bind(interaction: discord.Interaction, guild_name: str):
        channel = interaction.channel
        if not is_admin(interaction):
            await interaction.response.send_message("Only the server's admins can bind the bot.", ephemeral=True)
            return
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Type /bind in the text channel where guild chat should go.",
                                                    ephemeral=True)
            return
        can = channel.permissions_for(channel.guild.me)
        if not (can.view_channel and can.read_message_history and can.send_messages):
            await interaction.response.send_message(
                "I can't see this channel, so Discord messages here wouldn't reach the members' Guild tabs. "
                "Edit Channel → Permissions → add CustomClassic Chat → allow View Channel, Send Messages and "
                "Read Message History, then /bind again.", ephemeral=True)
            return
        old = store.by_channel(str(channel.id))
        if old:
            await interaction.response.send_message(
                f"This channel is bound already, for **{old['name']}** ({old['key']}). /unbind first to start over.",
                ephemeral=True)
            return
        # the same guild bound in another channel of this server moves here and keeps its code, so
        # members don't need a new one; another guild's name gets a code of its own
        moving = store.by_name(str(interaction.guild_id), guild_name)
        key = moving["key"] if moving else guild_key_for(store)
        try:
            hook = await channel.create_webhook(name="CustomClassic Chat relay", reason="CustomClassic Chat /bind")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't make a webhook here: give me the Manage Webhooks permission for this channel.", ephemeral=True)
            return
        if moving:
            store.remove(moving["channel_id"])
            try:
                await (await client.fetch_webhook(int(moving["webhook_id"]))).delete(reason="CustomClassic Chat moved")
            except Exception:
                pass
            old = client.get_channel(int(moving["channel_id"]))
            if old is not None:
                try:
                    await old.send(f"**{moving['name']}**'s guild chat moved to {channel.mention}.")
                except discord.HTTPException:
                    pass
        store.add(str(interaction.guild_id), str(channel.id), key, guild_name.strip()[:40], hook.url, str(hook.id))
        channels.put_cfg(store.by_channel(str(channel.id)))
        await interaction.response.send_message(
            f"**{gr.clean(guild_name)[:40]}**'s guild chat now comes to this channel"
            + (f" (moved from <#{moving['channel_id']}>, same code). " if moving else ". ") + gr.join_text(key) +
            " Lost it? Type /guildcode. To type here from the game's overlay: /chatlink.")
        try:  # the code stays at the top of the channel for everyone
            await (await interaction.original_response()).pin(reason="CustomClassic Chat: how to join")
        except discord.HTTPException:
            await interaction.followup.send("Tip: give me Manage Messages in this channel and I'll pin the code "
                                            "next time; members can always get it with /guildcode.", ephemeral=True)

    @tree.command(name="rename", description="Rename the guild bound to this channel; its code stays the same.")
    @app_commands.describe(guild_name="The guild's new name in the game")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def rename(interaction: discord.Interaction, guild_name: str):
        if not is_admin(interaction):
            await interaction.response.send_message("Only the server's admins can rename the guild.", ephemeral=True)
            return
        row = store.by_channel(str(interaction.channel_id))
        if not row:
            await interaction.response.send_message("This channel isn't bound: /bind it first.", ephemeral=True)
            return
        name = guild_name.strip()[:40]
        other = store.by_name(str(interaction.guild_id), name)
        if not name or (other and other["channel_id"] != row["channel_id"]):
            await interaction.response.send_message(
                "Another channel here is bound to a guild of that name." if name else "Type the new name.",
                ephemeral=True)
            return
        store.rename(row["channel_id"], name)
        channels.put_cfg(store.by_channel(row["channel_id"]))  # members' apps show the new name
        await interaction.response.send_message(
            f"Renamed **{row['name']}** to **{gr.clean(name)}**. The guild code stays the same.")

    @tree.command(name="unbind", description="Unbind CustomClassic Chat from this channel: members' apps stop sharing.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def unbind(interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("Only the server's admins can unbind the bot.", ephemeral=True)
            return
        row = store.by_channel(str(interaction.channel_id))
        if not row:
            await interaction.response.send_message("This channel isn't bound.", ephemeral=True)
            return
        channels.close(row["key"])
        store.remove(row["channel_id"])
        try:
            hook = await client.fetch_webhook(int(row["webhook_id"]))
            await hook.delete(reason="CustomClassic Chat /unbind")
        except Exception:
            pass
        await interaction.response.send_message(f"Unbound: **{row['name']}**'s chat no longer comes here.")

    @tree.command(name="guildcode", description="How to join this server's guild chat in CustomClassic Chat.")
    @app_commands.guild_only()
    async def guildcode(interaction: discord.Interaction):
        rows = store.by_server(str(interaction.guild_id))
        if not rows:
            await interaction.response.send_message("Guild chat isn't bound to a channel here yet: an admin can "
                                                    "/bind it.", ephemeral=True)
            return
        here = next((r for r in rows if r["channel_id"] == str(interaction.channel_id)), rows[0])
        await interaction.response.send_message(f"**{here['name']}** (<#{here['channel_id']}>): " + gr.join_text(here["key"]),
                                                ephemeral=True)

    @tree.command(name="chatlink", description="Log your CustomClassic Chat in as you, to type in its Guild tab.")
    @app_commands.guild_only()
    async def chatlink(interaction: discord.Interaction):
        if key is None:
            await interaction.response.send_message("Logins aren't switched on for this bot.", ephemeral=True)
            return
        link = login_link(key, str(interaction.user.id), interaction.user.display_name, str(interaction.guild_id))
        await interaction.response.send_message(
            f"With CustomClassic Chat running on this PC, open this link to log it in as **{interaction.user.display_name}** "
            f"(for {LOGIN_DAYS} days): {link}\nIt's yours alone: don't share it.", ephemeral=True)

    @client.event
    async def on_message(message):
        row = store.by_channel(str(message.channel.id))
        if not row or message.author == client.user:
            return
        if should_pass_on(message, row):
            channels.discord_message(row["key"], message.author.display_name, message.content)
        else:  # why a message in a set-up channel didn't go to the Guild tabs (never what it says)
            log.info("not passed on in %s: words=%s bot=%s webhook=%s", row["name"], bool(message.content),
                     message.author.bot, message.webhook_id)

    async def republish():
        while True:
            await __import__("asyncio").sleep(REPUBLISH_S)
            for row in store.all():
                channels.put_cfg(row)

    @client.event
    async def setup_hook():
        client.loop.create_task(republish())

    return client


def invite_link(app_id: str) -> str:
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands"
            f"&permissions={INVITE_PERMISSIONS}")


def load_env(path: Path) -> None:
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env(HERE / ".env")
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("Set DISCORD_BOT_TOKEN (in bot/.env): the bot's token from discord.com/developers.")
    data = Path(os.environ.get("DATA_DIR", HERE / "data"))
    store = Store(data / "bot.sqlite3")
    key = signing_key(data / "signing.pem")
    log.info("login key (public half, for guild_relay.SHARED_BOT_KEY): %s", public_key_text(key))
    make_bot(store, Channels(), key).run(token, log_handler=None)


if __name__ == "__main__":
    main()
