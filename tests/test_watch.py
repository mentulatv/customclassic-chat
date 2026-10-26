import json

from watch import Catalog, Entry, Watcher, load_entries, mentions, money, parse_price

ITEMS = [{"name": "Work Gloves", "aliases": ["wg", "work glove", "white wg"]},
         {"name": "Mushmom Card", "aliases": []},
         {"name": "Glove Attack Scroll: Intermediate", "aliases": ["glove att 60"]}]


def mega(body, name="Bob1"):
    return {"kind": "mega", "name": name, "body": body}


def test_words_and_close_spellings():
    assert mentions("mushmom", "S> mushrnom card 5k")  # a blurry read still counts
    assert not mentions("mushmom", "S> mushrnom card 5k", exact=True)
    assert mentions("mano", "selling Mano card") and not mentions("mano", "S> manor key")
    assert mentions("mano", "2 manos left")


def test_the_catalog_knows_aliases_and_spellings(tmp_path):
    cat = Catalog(ITEMS)
    assert cat.resolve("wg")["name"] == "Work Gloves"
    assert cat.resolve("mushmom cards")["name"] == "Mushmom Card"
    assert cat.resolve("work glovs")["name"] == "Work Gloves"
    assert cat.resolve("glove att 10") is None  # numbers only match exactly
    assert cat.suggest("glo")[:2] == ["Glove Attack Scroll: Intermediate", "Work Gloves"]
    cache = tmp_path / "names.json"
    Catalog.load("x", cache, fetch=lambda url: {"items": ITEMS})
    assert Catalog.load("x", cache, fetch=lambda url: 1 / 0).resolve("wg")  # the cached copy
    assert Catalog.load("x", tmp_path / "none.json", fetch=lambda url: 1 / 0).items == []


def test_plain_entries_fire_once_per_player_for_a_while():
    w = Watcher([Entry("mushmom")], Catalog(ITEMS))
    assert [why for _, why in w.check(mega("S> mushmom card 50k"), now=0)] == ["mentions mushmom"]
    assert w.check(mega("S> mushmom card 45k"), now=60) == []  # the same seller again
    assert w.check(mega("S> mushmom card 45k", name="Ann1"), now=60)
    assert w.check(mega("S> mushmom card 45k"), now=700)
    assert w.check({"kind": "map", "name": "Bob1", "body": "mushmom"}, now=9999) == []


def test_item_conditions_read_the_offer():
    w = Watcher([Entry("Work Gloves", sellers_only=True, max_price=1_500_000)], Catalog(ITEMS))
    assert w.check(mega("B> wg 1m"), now=0) == []  # a buyer
    assert w.check(mega("S> wg 1.8m"), now=0) == []  # too dear
    [(_, why)] = w.check(mega("S> clean wg 1.2m ch 5"), now=0)
    assert why == "selling Work Gloves for 1.2m"
    # a price range typed in: between 15k and 30k each
    w = Watcher([Entry("mushmom card", min_price=15_000, max_price=30_000)], Catalog(ITEMS))
    assert w.check(mega("S> mushmom card 38k"), now=0) == []  # above it
    assert w.check(mega("S> mushmom card 1k"), now=0) == []  # below it: a typo or a joke
    assert w.check(mega("S> 10 mushmom cards 200k"), now=0)  # 20k each
    w = Watcher([Entry("wg", min_price=500_000)], Catalog(ITEMS))
    assert w.check(mega("S> wg pm offers"), now=0) == []  # no price, so not in the range
    assert (Entry("x", min_price=15_000, max_price=30_000).label(), Entry("x", min_price=15_000).label(),
            Entry("x", max_price=30_000).label()) == ("x · 15k–30k", "x · ≥ 15k", "x · ≤ 30k")


def test_saved_entries_and_amounts():
    assert load_entries([{"text": "mano", "exact": True, "junk": 1}, "mushmom"]) == [Entry("mano", exact=True), Entry("mushmom")]
    assert load_entries([{"text": "wg", "under_usual": True}]) == [Entry("wg")]  # from before price ranges
    assert json.loads(json.dumps(Entry("x", max_price=5).to_dict()))["max_price"] == 5
    assert (parse_price("2.5m"), parse_price("400k"), parse_price("1,200,000"), parse_price("abc")) == (2_500_000, 400_000, 1_200_000, None)
    assert (money(1_200_000), money(40_000), money(None)) == ("1.2m", "40k", "?")
