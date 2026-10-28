"""Guild chat to Discord, peer to peer: apps hearing each other's readings agree on one post."""
import guild_relay as g


def test_guild_codes():
    assert g.guild_key(" abcd efgh jklm ") == "ABCD-EFGH-JKLM" == g.guild_key("ABCD-EFGH-JKLM")
    assert g.guild_key("ABCD-EFGH-1234") == ""  # 1 isn't in codes
    assert g.guild_key("MapleGuild") == ""  # a guild's name doesn't join: only its code
    assert g.guild_key("two words") == "" and g.guild_key("") == ""
    assert len(g.new_code()) == 14 and g.guild_key(g.new_code())
    assert g.bot_invite("MTIzNDU2Nzg5MDEyMzQ1Njc4.x.y").endswith("client_id=123456789012345678&scope=bot&permissions=66560")


def test_only_the_guild_can_read_its_channel():
    a, b = g.Seal("ABCD-EFGH-JKLM"), g.Seal("ABCD-EFGH-JKLN")
    blob = a.seal({"t": "hi"})
    assert a.open(blob) == {"t": "hi"} and b.open(blob) is None and a.topic != b.topic
    assert b"hi" not in blob  # sealed, not just encoded


class Net:
    """Stands in for the brokers: what one app says, every app hears (each once)."""

    def __init__(self):
        self.apps, self.posted = [], []

    def app(self, reader, share=True, source="guild", tab=False, admin=None):
        got = []
        peer = g.GuildPeer("ABCD-EFGH-JKLM", reader, got.append, share, tab, source, admin=admin,
                           cfg={"webhook": "https://discord.com/api/webhooks/1/x"}, connect=False,
                           post=lambda url, user, text: self.posted.append((user, text)))
        peer.say = lambda data, retain=False, sub="chat", p=peer: [
            other.heard(p.seal.seal({**data, "id": str(len(self.posted)) + reader + str(id(data)), "from": reader}),
                        now=self.now) for other in self.apps if other is not p]
        peer.got = got
        self.apps.append(peer)
        return peer

    now = 100.0


def msg(text, kind="guild", name="Rowan", stamp="18:49"):
    return {"kind": kind, "name": name, "body": text, "stamp": stamp}


def test_three_members_reading_one_message_post_it_once():
    net = Net()
    a, b, c = net.app("pc-bbb"), net.app("pc-aaa"), net.app("pc-ccc")
    a.send(msg("anyone up for zakurn tonight?"), now=100)  # read a little differently
    b.send(msg("anyone up for zakum tonight?"), now=100.4)
    c.send(msg("anyone up for zakum tonight?"), now=101)
    assert sum(p.decide(now=102) for p in net.apps) == 0  # still waiting for readings
    assert sum(p.decide(now=104) for p in net.apps) == 1  # one post, by one app
    assert net.posted == [("Rowan · guild", "anyone up for zakum tonight?")]  # the wording most saw
    a.send(msg("anyone up for zakum tonight?"), now=110)  # read again later: already decided
    assert sum(p.decide(now=120) for p in net.apps) == 0


def test_the_lowest_id_among_those_who_saw_it_posts():
    net = Net()
    a, _ = net.app("pc-aaa"), net.app("pc-bbb", share=False)  # the second doesn't share: never the poster
    a.send(msg("gl everyone"), now=100)
    for p in net.apps:
        p.decide(now=104)
    assert net.posted == [("Rowan · guild", "gl everyone")]


def test_only_the_chosen_kind_is_ever_shared():
    net = Net()
    a, b = net.app("pc-aaa"), net.app("pc-bbb")
    for kind in ("map", "whisper", "buddy", "party", "mega", "system"):
        a.send(msg("secret", kind=kind), now=100)  # only guild chat ever goes
    assert all(not p.matcher.pending for p in net.apps)
    net.app("pc-ccc", source="whisper").send(msg("test whisper", kind="whisper"), now=100)
    assert not b.matcher.pending  # not even when asked to
    a.send(msg("zakum at 8"), now=100)
    assert b.matcher.pending


def test_the_discord_tab_and_guildcode_through_the_admins_app():
    net = Net()
    admin = net.app("pc-adm", share=False, admin={"name": "Nimbus", "webhook": "https://discord.com/api/webhooks/1/x",
                                                   "webhook_id": "1", "channel_id": "555", "bot": "token"})
    member = net.app("pc-mem", share=False, tab=True)
    pages = [[{"id": "10", "content": "old", "author": {"username": "x"}}],
             [{"id": "11", "content": "see you at 8!", "author": {"global_name": "Pippa"}},
              {"id": "12", "content": "gl everyone", "webhook_id": "1", "author": {}},  # our own relayed line
              {"id": "13", "content": "!guildcode", "author": {"username": "newbie"}}]]
    admin.read = lambda token, channel, after: pages.pop(0)
    member.say({"t": "hi", "share": False, "tab": True})  # a member wants the Discord tab
    admin.read_discord(now=100)  # the first look: only marks where to start
    admin.read_discord(now=103)
    assert [(m[1]["name"], m[1]["body"]) for m in member.got if m[0] == "msg"] == [("Pippa", "see you at 8!")]
    assert net.posted and "ABCD-EFGH-JKLM" in net.posted[-1][1]  # the answer to !guildcode, in the channel


def test_a_closed_guild_stops_sharing():
    net = Net()
    a = net.app("pc-aaa")
    net.app("pc-adm", share=False, admin={"name": "N", "webhook": "https://discord.com/api/webhooks/1/x"}).close_guild()
    a.send(msg("after closing"), now=100)
    assert not a.matcher.pending
