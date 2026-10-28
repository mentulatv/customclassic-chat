"""The shared bot's own parts (no real Discord): what it remembers, and what members' apps hear from it."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
import ccchat_bot as b  # noqa: E402
import guild_relay as gr  # noqa: E402

HOOK = "https://discord.com/api/webhooks/123456789012/" + "a" * 40


def test_setting_up_a_guild_and_members_hearing_it(tmp_path):
    store, channels = b.Store(tmp_path / "bot.sqlite3"), b.Channels(connect=False)
    key = b.guild_key_for(store)
    store.add("server-1", "chan-1", key, "Nimbus", HOOK, "123456789012")
    channels.put_cfg(store.by_channel("chan-1"))
    got = []
    member = gr.GuildPeer(key, "pc-aaa", got.append, True, True, "map", connect=False)
    for topic, blob in channels.sent:
        member.heard(blob)
    assert member.cfg["webhook"] == HOOK and member.cfg["has_bot"] and member.cfg["name"] == "Nimbus"
    channels.discord_message(key, "Pippa", "see you at 8! @everyone")
    member.heard(channels.sent[-1][1])
    assert [(m[1]["name"], m[1]["body"]) for m in got if m[0] == "msg"] == [("Pippa", "see you at 8! @\u200beveryone")]
    other = gr.GuildPeer(gr.new_code(), "pc-zzz", [].append, True, True, "map", connect=False)
    other.heard(channels.sent[0][1])  # another guild can't read it
    assert not other.cfg.get("webhook")


def test_only_guild_codes_join(tmp_path):
    store = b.Store(tmp_path / "bot.sqlite3")
    key = b.guild_key_for(store)
    assert gr.guild_code(key) == key  # a fresh code, never a guild's name
    assert gr.guild_key("Nimbus") == "" and gr.guild_key("name:nimbus") == ""
    assert gr.guild_key(" abcd efgh jkmn ") == "ABCD-EFGH-JKMN"


def test_closing_and_what_goes_to_the_tab(tmp_path):
    channels = b.Channels(connect=False)
    member = gr.GuildPeer("ABCD-EFGH-JKLM", "pc-aaa", [].append, True, False, "map", connect=False)
    channels.close("ABCD-EFGH-JKLM")
    member.heard(channels.sent[-1][1])
    assert member.cfg == {"closed": True}
    row = {"webhook_id": "42"}
    person = SimpleNamespace(content="hi", author=SimpleNamespace(bot=False), webhook_id=None)
    relayed = SimpleNamespace(content="gl", author=SimpleNamespace(bot=True), webhook_id=42)
    assert b.should_pass_on(person, row) and not b.should_pass_on(relayed, row)
    assert b.invite_link("123").startswith("https://discord.com/oauth2/authorize?client_id=123&scope=bot%20applications.commands")
