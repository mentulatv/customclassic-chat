import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import customclassic_chat as mc  # noqa: E402
from reader import Line  # noqa: E402


def line(text, source="general", band=False):
    return SimpleNamespace(text=text, source=source, band=band)


def test_parse_chat_lines():
    assert mc.parse("[21:16] Rowan : e") == {"name": "Rowan", "body": "e", "sep": ":", "time": "21:16"}
    assert mc.parse("[21: 15]Nimbi<< hi there")["sep"] == "<<"
    assert mc.parse("[21:16j Bob1 : yo")["name"] == "Bob1"  # OCR read ] as j
    assert mc.parse("16 : 39]Bramble CH22 : B>Gloves Attack 60% 750K", loose=True)["name"] == "Bramble"  # [ lost
    assert mc.parse("16 : 39]Bramble CH22 : B>Gloves", loose=True)["time"] == "16:39"
    assert mc.parse("[12:01][Beginner] Kim : hello")["name"] == "Kim"  # a medal before the name
    assert mc.parse("Please beware of scams") is None and mc.parse("[21:16] Rowan :") is None
    # a megaphone's channel badge sits between the name and the colon
    assert mc.parse("[21:17]Tarvin CH22 : S> 60% earring INT") is None
    assert mc.parse("[21:17]Tarvin CH22 : S> 60% earring INT", loose=True)["name"] == "Tarvin"


def test_what_goes_where():
    assert mc.kind_of(line("x", "super_megaphone", band=True)) == "mega"
    assert mc.kind_of(line("x", "unknown", band=True)) == "mega"  # unknown colours on a band
    # your own map chat over a plain stretch of scenery reads as a band: its white text decides
    assert mc.kind_of(line("[17:31] Hollo : test", "general", band=True)) == "map"
    assert mc.kind_of(line("[Notice] Please beware of scams", "notice")) is None
    assert [mc.kind_of(line("x", s)) for s in ("whisper", "buddy_guild", "party", "general", "unknown")] == \
        ["whisper", "buddy", "party", "map", "other"]


def test_new_messages_only_and_whisper_direction():
    d = mc.Dedupe()
    frame = [line("[21:16] Rowan : e"), line("[21:17]Tarvin CH22 : S> 60% earring INT 100k", "super_megaphone", True),
             line("[21:18]Nimbi>> are you selling?", "whisper"), line("[21:18]Nimbi<< yes 100k", "whisper")]
    msgs = mc.messages_from(frame, d, 1000.0)
    assert [(m["kind"], m["name"], m["to"]) for m in msgs] == [
        ("map", "Rowan", None), ("mega", "Tarvin", None), ("whisper", "Nimbi", False), ("whisper", "Nimbi", True)]
    assert mc.line_text(msgs[2]).endswith("From Nimbi : are you selling?")
    # the next read shows the same lines, one read a little differently: only the new one counts
    again = [line("[21:16] Rowan : e"), line("[21:18]Nimbi>> are you se1ling?", "whisper"), line("[21:19] Kim : hi all")]
    assert [m["name"] for m in mc.messages_from(again, d, 1001.0)] == ["Kim"]


def msg(kind, name="X"):
    return {"kind": kind, "name": name, "body": "hi", "time": "17:00", "at": 0, "to": None}


def test_tabs_and_red_dots():
    log = mc.ChatLog()
    for k in ("map", "mega", "whisper", "party"):
        log.add(msg(k))
    # on All everything but megaphones shows: only Mega, holding what All leaves out, gets a dot
    assert [m["kind"] for m in log.visible()] == ["map", "whisper", "party"]
    assert log.unread == {"All": False, "Whisper": False, "Party": False, "Buddy": False, "Mega": True, "Watch": False}
    log.select("Whisper")
    log.add(msg("map"))
    log.add(msg("buddy"))
    log.add(msg("whisper"))
    assert log.unread == {"All": True, "Whisper": False, "Party": False, "Buddy": True, "Mega": True, "Watch": False}
    log.select("Buddy")
    assert not log.unread["Buddy"] and log.unread["All"] and [m["kind"] for m in log.visible()] == ["buddy"]
    log.select("Mega")
    assert [m["kind"] for m in log.visible()] == ["mega"]
    # what the watch list caught: a gold dot on Watch, and only those lines there
    log.add({**msg("mega", "Pebbles"), "watch": ["mentions mushmom"]})
    assert log.unread["Watch"]
    log.select("Watch")
    assert [m["name"] for m in log.visible()] == ["Pebbles"] and not log.unread["Watch"]


def test_panel_follows_the_game_window():
    client = {"left": 0, "top": 0, "width": 2560, "height": 1440}
    box = {"left": 481, "top": 1128, "width": 1086, "height": 103}
    rel = mc.to_relative(box, 25.0, client)
    assert mc.from_relative(rel, client) == box
    moved = dict(client, left=100, top=50)
    assert mc.from_relative(rel, moved) == dict(box, left=581, top=1178)
    assert mc.from_relative(rel, dict(client, height=1080)) is None  # resized: fit again
    assert mc.inside(500, 1150, box) and not mc.inside(500, 1100, box)
    assert mc.strip_height(25.0) == 21


def test_panel_grows_upward_and_follows_a_resized_game_chat():
    read = {"left": 485, "top": 1161, "width": 1131, "height": 151}
    # the ≡ grip makes it taller from the bottom up, like the game's chat; never smaller than the game's chat
    assert mc.panel_rect(read, 80) == {"left": 485, "top": 1081, "width": 1131, "height": 231}
    assert mc.panel_rect(read, -50) == read
    from collections import deque
    # the game's chat made taller: taken once two looks agree, keeping its bottom and width
    looks = deque(maxlen=6)
    taller = dict(read, top=1085, width=900)  # the lines found inside are shorter: the width stays
    assert mc.resized(read, taller, 39.0, looks) is None
    assert mc.resized(read, taller, 39.0, looks) == dict(read, top=1085, height=227)
    # a top line that's seen one look and not the next doesn't make it flicker
    looks = deque(maxlen=6)
    flicker = [dict(read, top=1161 - 40 * (i % 2)) for i in range(6)]
    results = [mc.resized(read, f, 39.0, looks) for f in flicker]
    assert results[:3] == [None, None, None]
    # made smaller: only once nearly all the recent looks agree (half a minute)
    looks = deque([1161] * 6, maxlen=6)
    smaller = dict(read, top=1200)
    assert [mc.resized(read, smaller, 39.0, looks) for _ in range(4)] == [None] * 4
    assert mc.resized(read, smaller, 39.0, looks) == dict(read, top=1200, height=112)


def test_lines_keep_the_games_colours():
    colors = {"super_megaphone": [119, 0, 66], "item_megaphone": [[9, 69, 76], [70, 39, 6]],
              "whisper": [0, 255, 0], "buddy_guild": [255, 153, 0], "general": [255, 255, 255]}
    backgrounds = {"item_megaphone": [[83, 208, 190], [224, 173, 1]], "super_megaphone": [206, 155, 177]}
    seen = lambda src, color, bg=None, band=False: SimpleNamespace(source=src, color=color, bg=bg, band=band)  # noqa: E731
    # a gold item megaphone stays gold, a teal one teal, whatever shade text recognition saw
    assert mc.style_for(seen("item_megaphone", (72, 41, 9), (220, 170, 5), True), "mega", colors, backgrounds) == \
        ("#462706", "#e0ad01")
    assert mc.style_for(seen("item_megaphone", (10, 70, 70), (80, 200, 185), True), "mega", colors, backgrounds) == \
        ("#09454c", "#53d0be")
    assert mc.style_for(seen("super_megaphone", (120, 3, 60), (200, 150, 170), True), "mega", colors, backgrounds) == \
        ("#770042", "#ce9bb1")
    assert mc.style_for(seen("whisper", (10, 240, 20)), "whisper", colors, backgrounds) == ("#00ff00", None)
    # map chat over plain scenery that looked like a band gets no band
    assert mc.style_for(seen("general", (250, 250, 250), (90, 90, 90), True), "map", colors, backgrounds) == \
        ("#ffffff", None)
    # a type not measured yet (party) keeps the colour it was seen in
    assert mc.style_for(seen("unknown", (255, 128, 192)), "other", colors, backgrounds) == ("#ff80c0", None)


def test_lines_the_game_chat_shows():
    assert mc.chat_lines({"height": 122}, 16.2) == 8 and mc.chat_lines({"height": 33}, 16.2) == 2
    assert mc.chat_lines(None, 16.2) == 0
    assert mc.DEFAULTS["min_lines"] == 3  # the ⚠ only for a minimised chat or one or two lines


def test_line_pitch_and_where_the_scrollbar_starts():
    # (top, bottom, left, right, text, confidence) as text recognition returns them: 16 px apart, 13 px tall,
    # a wrapped line without a time stamp in the middle, and one line read as two boxes
    rows = [(0, 13, 10, 300, "[16:40] A : hi", 0.9), (16, 29, 10, 300, "[16:41] B : a long one", 0.9),
            (32, 45, 30, 200, "that wraps", 0.9), (48, 61, 10, 120, "[16:42] C :", 0.9), (48, 61, 130, 300, "yo", 0.9),
            (64, 77, 10, 300, "[16:43] D : x", 0.9)]
    assert mc.line_pitch(rows) == 16.0
    assert mc.line_pitch([(0, 20, 0, 50, "one row", 0.9)]) == 25.0 and mc.line_pitch([]) == 24.0
    import numpy as np
    backgrounds = {"super_megaphone": [206, 155, 177], "item_megaphone": [[83, 208, 190], [224, 173, 1]]}
    arr = np.zeros((80, 420, 3), dtype=np.uint8) + 40  # dark game scene
    arr[16:30, 10:350] = (206, 155, 177)  # a super megaphone's pink band up to x=350, then the scrollbar
    arr[20:26, 40:120:3] = (119, 0, 66)  # its text: thin strokes with band showing between
    arr[64:78, 10:350] = (83, 208, 190)  # a teal item megaphone
    arr[:, 350:364] = (235, 235, 240)  # the scrollbar's track
    arr[:, 380:420] = (206, 155, 177)  # pink quick-slot buttons further right
    arr[16:30, 160:200] = (250, 250, 250)  # a white channel badge on the pink line
    arr[64:78, 220:300] = (250, 250, 250)  # and a long white item name on the teal one, ending at 300
    # from the end of the longest line's text (x=300), every band line shows only its band up to the scrollbar
    assert mc.band_right(arr, [7.5, 23.5, 40.5, 71.5], 10, 300, 420, backgrounds) == 350
    assert mc.band_right(arr, [7.5, 40.5], 10, 300, 420, backgrounds) is None  # no band in view


def test_system_lines_and_popups():
    backgrounds = {"notice": [151, 66, 57]}
    notice = lambda text, band=False, bg=None: SimpleNamespace(text=text, source="notice", band=band, bg=bg)  # noqa: E731
    # read from your screenshot: the party line sits on the chat's dark shading, which looks like a band
    assert mc.kind_of(notice("[16:59] You have left the party.", band=True, bg=(40, 32, 30)), backgrounds) == "system"
    assert mc.kind_of(notice("[14:31][Friend] SoulSlayerX has logged in."), backgrounds) == "system"
    assert mc.kind_of(notice("[14:31] [Notice] Please beware of scams"), backgrounds) is None
    assert mc.kind_of(notice("X obtained a Gachapon prize", band=True, bg=(150, 68, 55)), backgrounds) is None
    [m] = mc.messages_from([SimpleNamespace(text="[16:59] You have left the party.", source="notice", band=True,
                                            bg=(40, 32, 30), color=(224, 188, 175))],
                           mc.Dedupe(), 1000.0, ({"notice": [[255, 175, 175], [255, 255, 0]]}, backgrounds))
    assert (m["kind"], m["name"], m["body"], m["fg"]) == ("system", "", "You have left the party.", "#ffafaf")
    # the party invite pop-up's words, as text recognition merged them into the chat rows they cover
    assert mc.POPUP.search(":00]BLOODSHED CHOS : [Blue Jewelry Boots] ch 8 good spaw Party invite from")
    assert mc.POPUP.search("Trade request from Bob1") and mc.POPUP.search("Kim has invited you to a guild")
    assert not mc.POPUP.search("[17:00] Bob1 : anyone want a party? invite me")
    # the chat-type list, as read from the game (entries run on into the chat line beside them)
    menu = [SimpleNamespace(text=t) for t in ("/To AlI(/s) CH19 : S) +28 meba 750k", "/To Group((gr) D FM")]
    assert mc.chat_menu_open(menu) and mc.chat_menu_open([SimpleNamespace(text="/To Party(/p)")])
    assert not mc.chat_menu_open([SimpleNamespace(text=t) for t in ("All", "[17:00] Bob1 : to all party ppl",
                                                                    "Bob1 : guild? /to buddy later")])


def test_steps_aside_when_the_game_covers_its_chat():
    w = mc.CoverWatch()
    assert [w.covered(n) for n in (6, 7, 6, 6, 7)] == [False] * 5  # the usual: six or seven lines
    assert w.covered(1) is False  # one read with few lines: could be anything
    assert w.covered(0) is True  # two in a row: a party invite or a notice is over the chat
    assert [w.covered(0) for _ in range(30)] == [True] * 30  # stays aside however long it's up
    assert w.covered(6) is False  # lines back
    assert mc.CoverWatch().covered(0) is False  # never saw lines yet: nothing to compare with


def test_scrollbar_like_the_games():
    # 100 messages, 7 in view, panel 120 px tall, arrow buttons 13 px: the track is 94 px
    assert mc.thumb(100, 7, 0, 120, 13) == (13 + 94 - 13, 13)  # newest in view: thumb at the bottom (min size)
    assert mc.thumb(100, 7, 93, 120, 13) == (13, 13)  # scrolled to the oldest: at the top
    top, size = mc.thumb(10, 5, 0, 120, 13)
    assert size == 47 and top == 13 + 47  # half the messages in view: half the track
    assert mc.thumb(3, 7, 0, 120, 13) == (13, 94)  # everything fits: the thumb fills the track
    # dragging the thumb to a place gives back the scroll position that puts it there
    for scroll in (0, 10, 46, 93):
        t, s = mc.thumb(100, 7, scroll, 120, 13)
        assert abs(mc.scroll_at(t, 100, 7, 120, 13, s) - scroll) <= 2
    assert mc.bar_width(16.2) == 18  # a guess when it couldn't be measured: 3 px divider + 15 px track at 1080p
    # the game's scrollbar right of the bands, as on your screens: a dark divider, then the light track
    import numpy as np
    row = [191] * 8 + [64] * 3 + [215, 215, 219, 227] + [231] * 7 + [227, 219, 215, 215] + [100] * 20
    arr = np.array([[[v, v, v] for v in row]] * 3, dtype=np.uint8)
    assert mc.scrollbar_right(arr, [1], 8) == 8 + 3 + 15  # 1920x1080: 3 + 15 px
    doubled = np.repeat(arr, 2, axis=1)  # 2560x1440: the game draws its interface twice the size
    assert mc.scrollbar_right(doubled, [1], 16) == 16 + 6 + 30
    assert mc.panel_rect({"left": 0, "top": 10, "width": 100, "height": 50}, 0, 18)["width"] == 118
    # down the scrollbar column as on your 1080p screen: track, thumb, down arrow, then the frame line at 261
    col = [(231, 231, 231)] * 89 + [(85, 136, 170)] * 23 + [(17, 85, 136)] * 9 + [(114, 128, 143)] + [(8, 8, 8)] * 2
    arr = np.array([[c] for c in [(153, 153, 72)] * 134 + [(136, 153, 170)] + [(238, 238, 255)] * 12 + col],
                   dtype=np.uint8)
    assert mc.chat_bottom(arr, 0, 200, 16.2) == 147 + 89 + 23 + 9 + 1  # = 269 here: the first near-black row
    assert mc.chat_bottom(arr[:250], 0, 200, 16.2) is None  # no frame line within reach


def test_time_stamps_and_history(tmp_path):
    import time as t
    at = t.mktime((2026, 10, 26, 18, 16, 5, 0, 0, -1))
    m = {"kind": "map", "name": "Hollo", "body": "JPT", "at": at, "to": None}
    assert mc.line_text(m) == "[18:16:05] Hollo : JPT"
    assert mc.line_text(m, "minutes") == "[18:16] Hollo : JPT"
    assert mc.line_text(m, "off") == "Hollo : JPT"
    path = tmp_path / "h.jsonl"
    for hours_ago in (30, 13, 2, 0):
        mc.save_message(path, dict(m, at=at - hours_ago * 3600, body=f"{hours_ago}h"))
    assert [x["body"] for x in mc.load_history(path, 12, at)] == ["2h", "0h"]  # the default 12 hours
    assert len(mc.load_history(path, 0, at)) == 4  # forever
    mc.prune_history(path, 12, at)
    assert [x["body"] for x in mc.load_history(path, 0, at)] == ["2h", "0h"]
    log = mc.ChatLog()
    log.add(dict(m, kind="mega"))
    assert log.unread["Mega"]  # on All, megaphones aren't shown: Mega gets a red dot


def test_icon():
    img = mc.icon_image(32)
    assert img.size == (32, 32) and img.getpixel((16, 16))[3] == 255


def scene_line(text, parts, left=10, band=False, bg=None, color=(255, 255, 255)):
    return Line(text, 0.95, 0, 16, left, max(q[1] for q in parts) if parts else 400, color, bg, band, "general",
                parts=parts)


def test_the_scene_behind_the_chat_is_left_out():
    pitch = 16.0
    rows = [
        scene_line("[18:20] Pippa : hi man Snail", [(10, 150, 0, 16, "[18:20] Pippa : hi man"), (300, 340, 0, 16, "Snail")]),
        scene_line("Hollo", [(220, 290, 0, 16, "Hollo")], left=220),  # a name tag mid-box
        scene_line("prices", [(30, 70, 0, 16, "prices")], left=30),  # a wrapped line, indented
        scene_line("[18:21] Pippa : gl 44512", [(10, 120, 0, 16, "[18:21] Pippa : gl"), (128, 200, -10, 30, "44512")]),
    ]
    kept = mc.trim_scene(rows, pitch)
    assert [ln.text for ln in kept] == ["[18:20] Pippa : hi man", "prices", "[18:21] Pippa : gl"]


def test_scene_words_read_into_messages():
    assert mc.clean_body("system", "You don't have enough MP to use this skill.Snail", []) ==         "You don't have enough MP to use this skill."
    assert mc.clean_body("system", "You cannot use that skill yet. Lv,6]Slime", []) == "You cannot use that skill yet."
    assert mc.clean_body("system", "Please try again lat er. 17 e s  t", []) == "Please try again lat er."
    assert mc.clean_body("system", "Use this skill. l7 e t s te e ae e e iat er.", []) == "Use this skill."
    assert mc.clean_body("system", "You have left the party. It is a good day.", []).endswith("good day.")
    assert mc.clean_body("map", "hi man Hollo", ["hollo"]) == "hi man"
    assert mc.clean_body("map", "44512", []) == "" and mc.clean_body("map", "1", []) == "1"
    assert mc.clean_body("mega", "S> lvl 30 claw 2m", []) == "S> lvl 30 claw 2m"
    # with time stamps on, a line without one is the scene; your own chat still shows
    d = mc.Dedupe()
    got = mc.messages_from([line("[18:20] Pippa : hi Hollo"), line("Slime : 3"), line("[18:21] Hollo : gl")], d, 0.0,
                           ignore=["Hollo"])
    assert [(m["name"], m["body"]) for m in got] == [("Pippa", "hi"), ("Hollo", "gl")]


def test_system_messages_can_be_hidden():
    log = mc.ChatLog()
    log.hidden = {"system"}
    log.add(msg("system"))
    log.add(msg("map"))
    assert [m["kind"] for m in log.visible()] == ["map"]
    log.hidden = set()  # shown again: the ones read meanwhile are back
    assert [m["kind"] for m in log.visible()] == ["system", "map"]


def test_a_custom_tab_shows_the_chat_types_picked():
    tabs = mc.tabs_for({"on": True, "name": "Friends", "kinds": ["whisper", "buddy", "watch"]})
    assert [name for name, _ in tabs] == ["All", "Whisper", "Party", "Buddy", "Mega", "Friends", "Watch"]
    log = mc.ChatLog(tabs=tabs, tab="Friends")
    log.add(msg("whisper", "Nimbi"))
    log.add(msg("map", "Rowan"))
    log.add({**msg("mega", "Pebbles"), "watch": ["mentions mushmom"]})
    assert [m["name"] for m in log.visible()] == ["Nimbi", "Pebbles"]
    assert log.unread["All"] and log.unread["Watch"] and not log.unread["Friends"]
    assert not log.unread["Mega"]  # that megaphone is in view here already
    # turned off, or renamed: the tabs follow, and the open one falls back to All if it's gone
    log.set_tabs(mc.tabs_for({"on": False}))
    assert log.tab == "All" and "Friends" not in log.unread and log.unread["Watch"]
    assert mc.tabs_for({"on": True, "name": "mega", "kinds": []})[5][0] == "Custom"  # can't take a fixed tab's name
    assert "other" in mc.tabs_for({"on": True, "name": "Local", "kinds": ["map"]})[5][1]


def test_an_unlocked_panel_lost_off_screen_comes_back():
    game = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    back = mc.rescued({"left": 5000, "top": -900, "width": 600, "height": 200}, game)
    assert back == {"left": 660, "top": 440, "width": 600, "height": 200}
    assert mc.rescued({"left": 0, "top": 0, "width": 4000, "height": 3000}, game)["width"] == 1920  # never bigger


def test_lines_padded_with_spacers():
    assert mc.padded("B> all nx 10k S> 60% str earring scroll@@@@@@@@@@@@ @@@@@@@@@@@@@@@@Q@@")
    assert mc.padded("S> claw 60 @QQQ@QQQQQQQQQQQQQQ")  # the @ row as text recognition reads it
    assert mc.padded("S> zak helm ~~~~~~~~~~ pm me") and mc.padded("B> wg QQQQQQQQQQ")
    assert not mc.padded("S>2Crit WG 170K, ne ed cashhhhhhhhhh")  # a drawn-out word
    assert not mc.padded("B> white label ring 800K buy bulks !!! pm me...")
    assert not mc.padded("hahahahaha gl")
    # trades and party ads can be left out apart
    assert mc.padded_kind("B> all nx 10k S> 60% str earring scroll@@@@") == "trade"
    assert mc.padded_kind("LF KPQ 2/6 need 2 more @@@@@@@@") == "party"
    assert mc.padded_kind("lpq lf1 mage @@@@@@") == "party"
    assert mc.padded_kind("selling zhelm 30m, also LF zak run ~~~~~~") == "trade"
    assert mc.padded_kind("KoM guild recruiting @@@@@@") == "party"
    assert mc.padded_kind("hello everyone @@@@@@@@") == "other"
    log = mc.ChatLog()
    log.hide_padded = {"party"}
    log.add({**msg("map", "Forage"), "padded": "trade"})
    log.add({**msg("map", "Kpqer"), "padded": "party"})
    log.add(msg("map", "Njoyer"))
    assert [m["name"] for m in log.visible()] == ["Forage", "Njoyer"]
    log.hide_padded = {"trade", "party"}
    assert [m["name"] for m in log.visible()] == ["Njoyer"]
    log.hide_padded = set()  # shown again: they were kept
    assert [m["name"] for m in log.visible()] == ["Forage", "Kpqer", "Njoyer"]


def test_received_whispers_carry_the_senders_world_and_channel():
    p = mc.parse("[18:49]Nimbi[W/india-15]>> W/hat level are ya?")  # as text recognition read it
    assert (p["name"], p["sep"], p["where"], p["body"]) == ("Nimbi", ">>", "W/india-15", "W/hat level are ya?")
    got = mc.messages_from([line("[18:49]Nimbi[Windia-15]>> what level are ya?", "whisper"),
                            line("[18:50] Nimbi<< like 14", "whisper")], mc.Dedupe(), 0.0)
    assert [(m["kind"], m["to"], m.get("ch")) for m in got] == [("whisper", False, 15), ("whisper", True, None)]
    assert mc.line_text(got[0], "off") == "From Nimbi (ch 15) : what level are ya?"


def test_lines_read_before_a_restart_are_not_new_again():
    first = mc.messages_from([line("[18:50] Nimbi<< like 14", "whisper")], mc.Dedupe(), 1000.0)
    assert first[0]["raw"] == "[18:50] Nimbi<< like 14"
    d = mc.Dedupe()  # restarted: seeded from the kept history
    d.seed(first, 1100.0)
    assert mc.messages_from([line("[18:50] Nimbi<< like 14", "whisper")], d, 1100.0) == []


def test_wrapped_rows_join_where_the_game_broke_them():
    from reader import join_wrapped
    assert join_wrapped("removed the gender-exclusivity for acc", "ounts") == "removed the gender-exclusivity for accounts"
    assert join_wrapped("Aurora Mystery Fashion C", "rate! Congrats!") == "Aurora Mystery Fashion Crate! Congrats!"
    assert join_wrapped("S>This and Earings6", "0%") == "S>This and Earings60%"
    assert join_wrapped("MSCW 10", "% OFF") == "MSCW 10% OFF"
    assert join_wrapped("I'm on it.", "see you") == "I'm on it. see you"
    assert join_wrapped("meet me at", "Henesys") == "meet me at Henesys"


def test_twitch_chat_gets_its_own_tab():
    import twitch_chat
    tabs = mc.tabs_for({"on": True, "name": "Friends", "kinds": ["whisper"]}, twitch=True)
    assert [n for n, _ in tabs] == ["All", "Whisper", "Party", "Buddy", "Mega", "Twitch", "Friends", "Watch"]
    assert "twitch" not in dict(tabs)["All"]
    assert "twitch" in dict(mc.tabs_for(None, twitch=True, twitch_in_all=True))["All"]
    assert mc.custom_name({"on": True, "name": "twitch"}) == "Custom"  # can't take the Twitch tab's name
    assert (twitch_chat.channel_name("https://www.twitch.tv/MentulaTV"), twitch_chat.channel_name("a b")) == ("mentulatv", "")
    line = ("@badge-info=;color=#0A0A0A;display-name=Nimbi;emotes= :nimbi!nimbi@nimbi.tmi.twitch.tv "
            "PRIVMSG #mentulatv :\x01ACTION waves\x01")
    m = twitch_chat.message(twitch_chat.parse(line), 0.0)
    assert (m["kind"], m["name"], m["body"]) == ("twitch", "Nimbi", "waves")
    assert m["fg"] != "#0a0a0a"  # too dark for the panel: lightened


def test_another_window_has_its_own_tab_on_the_same_chat():
    log = mc.ChatLog(tab="Mega")
    side = log.view_of("All")
    msg_map, msg_mega = msg("map", "Rowan"), msg("mega", "Kestrel")
    for m in (msg_map, msg_mega):
        log.add(m)
        side.notice(m)
    assert [m["name"] for m in log.visible()] == ["Kestrel"] and [m["name"] for m in side.visible()] == ["Rowan"]
    assert log.unread["All"] and not side.unread["All"] and side.unread["Mega"]  # each its own dots
    assert len(side.messages) == 2  # one chat: added once, seen in both


def test_the_right_click_menu_closes_once_the_pointer_is_well_away():
    menu = (100, 100, 300, 260)
    assert mc.pointer_away(menu, (150, 200)) == 0  # on it
    assert mc.pointer_away(menu, (350, 200)) == 50  # just beside it: stays open (under 120)
    assert mc.pointer_away(menu, (150, 420)) == 160  # well below it: closes


def test_moving_a_window_keeps_its_size():
    r = {"left": 500, "top": 300, "width": 400, "height": 200}
    assert mc.dragged_rect("move", r, -60, 20, 200, 60) == {"left": 440, "top": 320, "width": 400, "height": 200}
    assert mc.dragged_rect("e", r, 60, 0, 200, 60) == {"left": 500, "top": 300, "width": 460, "height": 200}
    assert mc.dragged_rect("nw", r, 30, -40, 200, 60) == {"left": 530, "top": 260, "width": 370, "height": 240}
    assert mc.dragged_rect("w", r, 300, 0, 200, 60)["width"] == 200  # never narrower than that


def test_old_splits_become_panes_in_their_frames():
    opts = {"windows": [{"tab": "All", "id": "w1", "free": {"left": 1}},
                        {"dock": "above", "tab": "Mega", "height": 90},
                        {"dock": "above", "tab": "Party", "host": "w1", "share": 0.3},
                        {"dock": "above", "tab": "Whisper", "host": "w1", "share": 0.2}]}
    mc.migrate_windows(opts)
    assert opts["windows"] == [{"tab": "All", "id": "w1", "free": {"left": 1},
                                "panes": [{"tab": "Whisper", "share": 0.2}, {"tab": "Party", "share": 0.3}]}]
    assert opts["main_panes"] == [{"tab": "Mega", "height": 90}]


def test_the_game_scrollbar_is_found_from_its_pixels():
    import numpy as np
    frame = np.zeros((200, 40, 4), np.uint8)
    frame[:, :, :3] = (20, 50, 90)  # the scene (BGR)
    frame[41:150, 10, :3] = 221     # the scrollbar's edge, top arrow to bottom one
    frame[44:52, 13:20, :3] = (153, 102, 34)    # the blue arrow buttons beside it, top and bottom
    frame[139:147, 13:20, :3] = (153, 102, 34)
    assert mc.scrollbar_span(frame, 6, 16, 140, 0, 200) == (41, 149)
    lit = frame.copy()
    lit[44:52, 10, :3] = (151, 85, 47)  # the pointer on the top arrow lights it up, blue to its edge: the same span
    assert mc.scrollbar_span(lit, 6, 16, 140, 0, 200) == (41, 149)
    frame[60:80, 9:22, :3] = (40, 120, 200)  # a window over its upper part: no top arrow beside the run any more
    assert mc.scrollbar_span(frame, 6, 16, 140, 0, 200) is None
    sky = np.zeros((200, 40, 4), np.uint8)
    sky[:, :, :3] = (230, 160, 90)  # the chat closed, blue sky where its scrollbar was: none
    assert mc.scrollbar_span(sky, 6, 16, 140, 0, 200) is None



def test_the_chat_is_read_only_when_it_changed_and_paced_to_its_speed():
    import numpy as np
    chat = np.zeros((128, 400, 3), np.int16)
    chat[8:20:2, 10:300] = 230  # lines of text
    chat[40:52:2, 10:200] = 230
    assert not mc.chat_changed(chat, chat.copy())
    scene = chat.copy()
    scene[100:110, 350:390] += 90  # a little of the game's scene moving behind the see-through background
    assert not mc.chat_changed(chat, scene)
    moved = np.roll(chat, -16, axis=0)  # a new line: every line moves up one
    assert mc.chat_changed(chat, moved)
    # balanced: soon enough that 8 lines can't scroll away at 3 lines a second (long megaphones take two)
    pace = mc.ReadPace()
    assert abs(pace.pause(100, "balanced", 8, 1.0) - (8 / (3.0 * 1.3) - 1.0)) < 0.01
    assert pace.pause(100, "fastest", 8, 1.0) == 0
    assert pace.pause(100, "light", 8, 1.0) > pace.pause(100, "balanced", 8, 1.0)
    for t in range(80, 100, 2):  # a burst busier than assumed: no waiting longer than it allows
        pace.note(t, 9, 8, False)
    assert pace.pause(100.5, "balanced", 8, 1.0) == 0  # half a chat of new lines at once: read again at once
    pace.hurry_until = 0
    assert pace.pause(100.5, "balanced", 8, 1.0) < 8 / (3.0 * 1.3) - 1.0
    pace = mc.ReadPace()
    pace.note(100, 3, 8, True)  # none of the last read's lines still there: lines were missed, so hurry
    assert pace.pause(130, "light", 8, 1.0) == 0 and pace.pause(170, "light", 8, 1.0) > 0
    dd = mc.Dedupe()
    dd.is_new("[19:38] Rowan : hi", 0)
    dd.is_new("[19:38] Rowan : hi", 1)
    assert (dd.looked, dd.fresh) == (2, 1)


def test_padded_lines_are_shown_without_their_spacers():
    assert mc.unpadded("S> Claw 60% 170k@@@@@@@@@@@@@@@@@@QQQQQ@Q④Q") == "S> Claw 60% 170k"
    assert mc.unpadded("S> +2crit WG @@@@@@@ Maple-Stein Head @@@@@@ Trash NX 16K ea") == \
        "S> +2crit WG · Maple-Stein Head · Trash NX 16K ea"
    assert mc.unpadded("============== B> Clean Emerald Earring!") == "B> Clean Emerald Earring!"
    assert mc.unpadded("S> GFA 60 1000000 @@@@@@@@") == "S> GFA 60 1000000"  # a price keeps its zeros
    assert mc.unpadded("B> Dagger 60% ----145k----") == "B> Dagger 60% · 145k"
    assert mc.unpadded("B> wand 1O0k @@@@") == "B> wand 1O0k"  # 100k read as 1O0k
    # as read in the Free Market
    for read, shown in [
            ("B>FOUNDERS CRATE(11) 275K HALLOWEEN CRATE(11) 375K@QQ@Q@Q@Q@Q@@Q@Q@@Q2",
             "B>FOUNDERS CRATE(11) 275K HALLOWEEN CRATE(11) 375K"),
            ("....S> DemonGoblin Gargoly Wings Witch clothes Witch hat", "S> DemonGoblin Gargoly Wings Witch clothes Witch hat"),
            ("B>6 ATT WORK GLOVES@@", "B>6 ATT WORK GLOVES"),
            ("S> +1 Bazlud 20k quick#", "S> +1 Bazlud 20k quick"),
            ("S> DARK DEVIL HAT 75k~", "S> DARK DEVIL HAT 75k"),
            ("SELL 100% STR OVERALL 65K SCROOLL LESSERR @@@@@ @@ @@", "SELL 100% STR OVERALL 65K SCROOLL LESSERR"),
            ("B>OVERALL 10% SCROLL STR/DEX/INT/LUK 7K EACH@@@@5AUNA23K@QQ①@@@@@",
             "B>OVERALL 10% SCROLL STR/DEX/INT/LUK 7K EACH · 5AUNA23K"),
            ("B>Lv30 Thief Luk Gear @@@@ @@@@", "B>Lv30 Thief Luk Gear"),
            ("S> WHITE LABEL 425K.", "S> WHITE LABEL 425K."),
            ("anyone going to Kerning?", "anyone going to Kerning?"),
            ("cooool, see you @ FM", "cooool, see you @ FM")]:
        assert mc.unpadded(read) == shown, read


def test_a_padded_line_read_again_is_not_new():
    # its spacers read differently every time: the same line all the same
    dd = mc.Dedupe()
    assert dd.is_new("[00:48] Marokay: B>EARRING LIK 10%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@", 0)
    assert not dd.is_new("[00:48]Marokay: B>EARRING LIK 10%@@@@@@@@@@@@@@@@@@@QQQQQQQQQQQQQQQQQQQQQQQQQQQQQ", 5)
    assert not dd.is_new("[00:48] Marokay : B>EARRING LIK 10%@@@@@@@@@@@@@@@@@@@@@@@@@@@Q@@@@@@@@Q@@@@@QQ@", 9)
    assert dd.is_new("[00:49] Marokay : B>EARRING DEX 60% @@@@@@@@@@@@@@@@@@@@", 12)  # another line: new
    # a price keeps its zeros, also read as O's
    assert mc.without_spacers("S> claw 100k @@@@QQQ@@") .split() == ["S>", "claw", "100k"]
    assert "1O0k" in mc.without_spacers("S> claw 1O0k")


def test_text_recognition_leaves_most_cores_to_the_game():
    import os
    import reader
    assert 1 <= reader.ocr_threads() <= 2
    assert reader.ocr_threads(3) == min(3, os.cpu_count())


def test_guild_chat_switches_on_with_its_colour_alone():
    import guild_relay
    import reader
    cfg = reader.Config()
    # old MapleStory's guild purple stands in until the game has guild chat; nothing else is near it
    assert reader._nearest([196, 184, 250], cfg.colors, cfg.color_tolerance) == "guild"
    for name in ("general", "notice", "buddy_guild", "whisper"):
        for rgb in (cfg.colors[name] if isinstance(cfg.colors[name][0], list) else [cfg.colors[name]]):
            assert reader._nearest(rgb, cfg.colors, cfg.color_tolerance) != "guild", name
    cfg.colors = {**cfg.colors, "guild": [180, 120, 255]}  # the one value to change when the game has guild chat
    assert reader._nearest([182, 118, 250], cfg.colors, cfg.color_tolerance) == "guild"
    line = SimpleNamespace(source="guild", band=False, text="[18:49] Rowan : zakum at 8?")
    [m] = mc.messages_from([line], mc.Dedupe(), 0.0)
    assert (m["kind"], m["stamp"]) == ("guild", "18:49")
    assert guild_relay.relay_line(m) == {"stamp": "18:49", "speaker": "Rowan", "text": "zakum at 8?", "kind": "guild"}
    assert "guild" in dict(mc.TABS)["Buddy"] and "guild" in dict(mc.TABS)["All"]  # shown where buddy chat is
    # buddy chat (and everything else) never goes, whatever is chosen to share
    buddy = {**m, "kind": "buddy"}
    assert all(guild_relay.relay_line(buddy, s) is None for s, _ in guild_relay.SOURCES)
    assert guild_relay.relay_line({**m, "kind": "map"}, "map") is None  # guild chat is the only chat that goes


def test_a_short_or_closed_game_chat_is_noticed():
    row = lambda top, text="[19:38] Rowan : hi", left=20: SimpleNamespace(top=top, bottom=top + 18, left=left, text=text)
    # two lines right above the chat's bottom (128), a name tag far above: two lines
    assert mc.short_chat([row(104), row(87, "Belli : stay"), row(20, "QuestGuy")], 128, 16, 400, 16) == 2
    assert mc.short_chat([row(104)], 128, 16, 400, 16) == 1
    assert mc.short_chat([row(40)], 128, 16, 400, 16) == 0  # nothing stacked on the bottom
    # closed: the newest line shows in the typing bar, where an open chat has its button
    assert mc.chat_closed([SimpleNamespace(text="Y0ungL1nk: S> Devil horns")])
    assert not mc.chat_closed([SimpleNamespace(text="日")]) and not mc.chat_closed([SimpleNamespace(text="All")])
    # the panel starts about half a line below the game chat's top, so its resize edge stays free
    r = mc.anchored({"left": 100, "top": 500, "width": 400, "height": 160}, 16, 18)
    assert 506 <= r["top"] <= 512 and r["top"] + r["height"] == 660 and r["width"] == 418

