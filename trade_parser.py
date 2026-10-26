"""Turn one chat line (usually OCR output) into trade observations.

A line like

    Bobby : S> 5 att bwg 12m, 60% glove att 3.5m ea  B> ilbis 20m c/o

becomes three observations:

    sell  "bwg"                     variant "+5 ATT"  12,000,000 ask
    sell  "Gloves Attack Scroll: Intermediate"     3,500,000 ask (each)
    buy   "ilbis"                                  20,000,000 bid

Item text is *not* resolved here; Maple Chat's watch list (watch.py) maps it onto the
price site's item names. This is the Maple Price Index server's parser, copied as is.
The parser is deliberately forgiving about OCR noise and slang, and conservative
about what counts as a price (a bare "5" is never a price; "5m" is).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent / "data"

MAX_PRICE = 100_000_000_000  # 100b, anything above is a parse error
MEGAPHONE_SOURCES = {"megaphone", "super_megaphone", "item_megaphone"}


# --------------------------------------------------------------------------- data


@dataclass
class Observation:
    intent: str  # "sell" | "buy"
    item_text: str  # cleaned phrase, or canonical scroll name
    variant: str  # "" | "+5 ATT" | "clean" ...
    price: int  # as written (total if qty > 1 and not "each")
    unit_price: int
    qty: int
    price_kind: str  # ask | bid | buyout | current_offer | starting_bid | range
    from_bracket: bool = False  # item name came from an item-megaphone link
    is_scroll_rule: bool = False
    typed_item: str = ""  # what the player typed, when the link's name replaced it

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ParsedLine:
    player: str | None
    message: str
    is_trade: bool
    observations: list[Observation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "message": self.message,
            "is_trade": self.is_trade,
            "observations": [o.to_dict() for o in self.observations],
            "notes": self.notes,
        }


# ------------------------------------------------------------------ normalisation

_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5"})
_PRICEISH = re.compile(r"(?<![A-Za-z])([0-9OoIl|]*\d[0-9OoIl|]*(?:[.,][0-9OoIl|]+)?)(?=\s*(?:k|kk|m|mil|b|bil)\b)", re.I)


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("：", ":").replace("»", ">>").replace("›", ">").replace("〉", ">").replace("〈", "<")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"[​-‏﻿]", "", t)
    # OCR digit confusions inside obvious prices: "1O.5m" -> "10.5m", "l2m" -> "12m"
    t = _PRICEISH.sub(lambda m: m.group(1).translate(_OCR_DIGIT), t)
    # c/o and b/o variants: "c/0", "c / o", "c\o", "c.o"; a/w (auto-win) is a buyout
    t = re.sub(r"\b([cbs])\s*[/\\.]\s*[o0]\b", lambda m: m.group(1).lower() + "/o", t, flags=re.I)
    t = re.sub(r"\ba{1,2}\s*[/\\]?\s*w\b", "b/o", t, flags=re.I)  # "a/w", "aw", OCR "aAw"
    # "Current offer is 660k", "H/O 400k" (highest offer): what a buyer offered, not an ask
    t = re.sub(r"\b(?:current|highest)\s+offer(?:\s+is)?\b|\bh\s*[/\\]\s*o\b", "c/o", t, flags=re.I)
    # a price glued to the word before it: "piece18k", "Vings30k", "L115K"
    t = re.sub(r"(?<=[A-Za-z])(?=\d+(?:[.,]\d+)?\s?(?:k|m|mil|b)\b)", " ", t, flags=re.I)
    t = re.sub(r"\bs\s*[/\\]\s*b\b", "s/b", t, flags=re.I)
    # OCR slips seen in Windia's chat: "VVTB" (W read as VV), "Intermnediate", "Scrol:"
    t = re.sub(r"\bV{1,2}(?=T[BST]\b)", "W", t, flags=re.I)  # "VVTB", "'VTB"
    t = re.sub(r"\bintermn?e?diat(?:e|)\b", "Intermediate", t, flags=re.I)
    t = re.sub(r"\bScrol(?=[:\s])", "Scroll", t)
    # the game's "Quest Complete" popup can sit on a chat row and be read with it
    t = re.sub(r"\s*\bquest complete\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ speaker split

# Classic World: "[20:08]Fennick ...". OCR: "[20: 12]", "[21:20jOdessa", "[21:211Mirabel" (] read as 1),
# "13:03]lahmao" (no [)
_TIME = r"(?:[\[({]\s?\d{1,2}\s?[:.;]\s?\d{2}\s?[\])}jlI|1]?|\d{1,2}\s?[:.;]\s?\d{2}\s?[\])}jlI|])"
_TIMESTAMP = re.compile(r"^\W{0,3}" + _TIME + r"\s*")
# a second message glued on by OCR: "... 700K [21:20jOdessa CH05 : [Fairy Wand] ...", "NX 1:10 13:13jQuillo"
_EMBEDDED_TIME = re.compile(r"\s+(?=" + _TIME + r"\s?[A-Za-z])")
_SPEAKER = re.compile(
    r"""^\W{0,4}
        (?:(?:\[[^\]]{1,25}\]|<[^>]{1,25}>)\s*)?      # medal / channel tag
        (?P<name>[A-Za-z0-9]{3,13})
        (?:\s*\([^()]{1,20}\))?                        # "Province(House Bandit) : ..."
        \s*(?:\[(?:ch\.?\s*)?\d{1,2}\])?\s*            # optional [Ch.5]
        (?:[:;]\s*                                     # "Name : msg", "Inkwell :yo"
          |\[?(?:(?=[A-Za-z]*\d)[A-Za-z0-9]{2,5}|[Cc][Hh][A-Za-z0-9]{1,3})\]?  # megaphone channel badge (OCR: CHO1, CH12,
           \s*(?:\S{0,2}\s?[:;]|-)?\s+                 # 20HD, co1-, [cwo1, CHOS); its ear icon may read as "-", "1" or "9)"
          |(?:\S{1,6}\s{0,2}){1,2}[:;]\s+)             # any garbled badge when the colon survived ("cwas :", "e cs :")
        (?P<msg>.+)$""",
    re.X,
)


def split_messages(text: str) -> list[str]:
    """One OCR line can hold two chat messages when a time stamp was misread."""
    return [p for p in _EMBEDDED_TIME.split(text) if p.strip()] or [text]


# Classic World whispers: "[21:15]nimbi<< hi" (sent), "Name>> hi" (received). Never stored.
_WHISPER = re.compile(r"^\W{0,3}(?:\[\s?\d{1,2}\s?[:.;]\s?\d{2}\s?\]\s*)?[A-Za-z0-9]{2,13}\s*(?:<<|>>|«|»)")


def is_whisper(text: str) -> bool:
    return bool(_WHISPER.match(text))


def split_speaker(text: str) -> tuple[str | None, str]:
    text = _TIMESTAMP.sub("", text, count=1)
    m = _SPEAKER.match(text)
    if m:
        return m.group("name"), m.group("msg").strip()
    return None, text


_BADGE_CH = re.compile(r"\bch\s?([0-9OoIlS]{1,2})", re.I)
_SHOP_CH = re.compile(r"\bfm\s*(?:ch\.?\s*)?(\d{1,2})\b|\bch\.?\s*(\d{1,2})\s*-?\s*fm\b|\b(\d{1,2})\s*ch\s*fm\b", re.I)


def _channel(text: str | None) -> int | None:
    if not text:
        return None
    n = int(text.translate(_OCR_DIGIT))
    return n if 1 <= n <= 40 else None


def where_said(text: str) -> dict:
    """Where to find a seller: the channel a megaphone was sent from (its "CH12" badge, OCR
    "CHO7"), and the free-market channel the message names ("FM ch 4", "ch 5 fm", "35ch fm")."""
    t = normalize_text(text)
    player, msg = split_speaker(t)
    head = _TIMESTAMP.sub("", t, count=1)
    head = head[: head.rfind(msg)] if player and msg in head else ""
    badge = _BADGE_CH.search(head)
    shop = _SHOP_CH.search(msg)
    return {"channel": _channel(badge.group(1)) if badge else None,
            "fm_channel": _channel(next(g for g in shop.groups() if g)) if shop else None,
            "fm": bool(re.search(r"\bfm\b|free\s*market", msg, re.I))}


# ------------------------------------------------------------------- intent marks

_MARKERS = re.compile(
    r"""(?P<buyq>\b(?:anyone|any1|anybody|who(?:'?s)?)\s+(?:is\s+)?(?:sell(?:ing)?|has|have)\b)
      | (?P<pc>\bP\s*C\s*>+|\bp/c\b|\bprice\s*check(?:ing)?\b)
      | (?P<trade>\bT\s*>+|\bWTT\b|\btrading\b)
      | (?P<sell>\bS\s*>+|\bWTS\b|\bFS\b|\bH\s*>+|\bsell(?:ing|s)?\b|^S\s+(?=[A-Za-z]))   # a lone "S " opening the
      | (?P<buy>\bB\s*>+|\bWTB\b|\bbuy(?:ing|s)?\b|\bLF\b|\bW\s*>+|\blooking\s+for\b|^B\s+(?=[A-Za-z]))  # message lost its ">"
    """,
    re.I | re.X,
)

# ------------------------------------------------------------------------ prices

_SUFFIX = {
    "k": 1_000, "kk": 1_000_000, "m": 1_000_000, "mil": 1_000_000, "mill": 1_000_000,
    "mils": 1_000_000, "million": 1_000_000, "b": 1_000_000_000, "bil": 1_000_000_000,
    "bill": 1_000_000_000, "billion": 1_000_000_000, "meso": 1, "mesos": 1,
}
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+|\d{1,3}(?:\.\d{3}){2,}|\d+(?:[.,]\d+)?)"
_SUF = r"(?P<suf>kk|k|million|mill|mils|mil|m|billion|bill|bil|b|mesos|meso)?"
_EACH = r"(?P<each>\s*(?:/\s*)?(?:ea|each|per|apiece|a\s?pc|/pc)\b)?"
# the suffix must not be the start of a qualifier: "2 b/o 3.2m" is not 2 billion
_PRICE = re.compile(r"(?<![\w.,])" + _NUM + r"\s*" + _SUF + r"(?![A-Za-z0-9%]|/[o0])" + _EACH, re.I)
_QUALS = re.compile(r"c/o|b/o|s/b|\b(?:co|bo|sb)\b", re.I)
_PRICE_CONTEXT = re.compile(r"(?:@|\bfor\b|\bat\b|\bprice\b|\basking\b|c/o|b/o|s/b|\bco\b|\bbo\b)\s*:?\s*$", re.I)
_RANGE = re.compile(
    r"(?P<a>\d+(?:[.,]\d+)?)\s*(?P<sa>k|m|b)?\s*(?:-|~|to)\s*(?P<b>\d+(?:[.,]\d+)?)\s*(?P<sb>k|m|b)\b(?P<each>\s*(?:ea|each)\b)?",
    re.I,
)
_QUAL_KIND = {
    "c/o": "current_offer", "co": "current_offer", "b/o": "buyout", "bo": "buyout",
    "s/b": "starting_bid", "sb": "starting_bid",
}


def _to_number(num: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", num):
        return float(num.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}", num):
        return float(num.replace(".", ""))
    return float(num.replace(",", "."))


_NOT_PRICE_AFTER = re.compile(
    r"\s*(?:%|\+|x\b|pcs?\b|pieces\b|slots?\b|lv\b|lvl\b|levels?\b|"
    r"(?:w\.?att|watk|matk|m\.?att|att|atk|wa|ma|str|dex|int|luk|acc|avoid|avo|speed|spd|jump|hp|mp|wdef|mdef|def)\b)",
    re.I)
_NOT_PRICE_BEFORE = re.compile(r"(?:\bx|\blv|\blvl|\blevel|\bch|\bfm|\broom|\+|#)\s*$", re.I)
_CTX_AFTER = re.compile(r"\s*(?:/\s*)?(?:ea|each|per|mesos?|c/o|b/o|s/b|co|bo|sb)\b", re.I)


def _bare_number_is_price(seg: str, m: re.Match, value: float) -> bool:
    """Is a number without k/m/b a price? Early Classic World prices are small
    ("pure water 850 ea", "bc ore 3299"), so this cannot just be a size cut-off.

    Not a price: followed by a stat/%/slots/x/pcs, preceded by x/lv/ch/fm, or a
    short number at the start of an item ("100 red potion" is a quantity).
    A price: has a thousands separator, sits next to ea/each/mesos/c/o/@/for,
    or is the last thing in the segment (only filler like "pm me" after it).
    """
    before, after, num = seg[: m.start()], seg[m.end():], m.group("num")
    if _NOT_PRICE_AFTER.match(after) or _NOT_PRICE_BEFORE.search(before):
        return False
    if re.fullmatch(r"\d+[.,]\d{1,2}", num):
        return False  # mesos are whole: "c/o 2.5 a/w 2.8m", "NX 18.5 each" lost their m / k
    has_sep = "," in num or num.count(".") >= 2
    per_piece = bool(m.group("each")) or bool(re.match(r"\s*(?:/\s*)?(?:ea|each|per|mesos?)\b", after, re.I))
    ctx = per_piece or bool(_PRICE_CONTEXT.search(before[-14:])) or bool(_CTX_AFTER.match(after))
    if not before.strip() and not has_sep and value < 10_000 and re.match(r"\s+[A-Za-z]", after):
        return False  # leading quantity
    trailing = not re.search(r"[A-Za-z0-9]", _FILLER.sub(" ", after))
    if has_sep or per_piece:
        return value >= 1  # "fragment of magic 99 ea"
    if ctx:
        return value >= 100  # "c/o 2", "@@22", "for 8": a dropped k or m, or noise

    if trailing:
        return value >= 100
    return value >= 10_000


@dataclass
class _Price:
    value: int
    kind: str
    each: bool
    span: tuple[int, int]


def _find_prices(seg: str) -> list[_Price]:
    """Find prices and bind c/o, b/o, s/b qualifiers to them.

    Players write both "c/o 18m b/o 25m" (qualifier first) and "25m b/o 18m c/o"
    (qualifier last). If the first qualifier comes before the first price, every
    qualifier binds to the price after it; otherwise to the price before it.
    """
    out: list[_Price] = []
    taken: list[tuple[int, int]] = []
    for m in _RANGE.finditer(seg):
        mult = _SUFFIX[m.group("sb").lower()]
        a = _to_number(m.group("a")) * _SUFFIX[(m.group("sa") or m.group("sb")).lower()]
        b = _to_number(m.group("b")) * mult
        if 0 < a <= b <= MAX_PRICE:
            out.append(_Price(int((a + b) / 2), "range", bool(m.group("each")), m.span()))
            taken.append(m.span())
    for m in _PRICE.finditer(seg):
        if any(s <= m.start() < e for s, e in taken):
            continue
        num, suf = m.group("num"), (m.group("suf") or "").lower()
        after = seg[m.end("suf") if m.group("suf") else m.end():]
        if suf == "b" and re.match(r"\s*>", after):
            continue  # "[Meat] 1B > Clean Steel Slain": a buy marker with a stray 1, not a billion
        if suf == "kk" or re.match(r"\s*(?:/|per\b|a\b)\s*sets?\b", after, re.I):
            continue  # "150kk" (150k or 150m?) and "white pot 28k/set" (how many?) can't be told
        value = _to_number(num)
        if suf:
            value *= _SUFFIX[suf]
        elif not _bare_number_is_price(seg, m, value):
            continue
        if not (1 <= value <= MAX_PRICE):
            continue
        out.append(_Price(int(round(value)), "ask", bool(m.group("each")), m.span()))
    out.sort(key=lambda p: p.span[0])
    if not out:
        return out

    quals = [q for q in _QUALS.finditer(seg) if not any(p.span[0] <= q.start() < p.span[1] for p in out)]
    if quals:
        leading = quals[0].start() < out[0].span[0]
        for q in quals:
            kind = _QUAL_KIND[q.group(0).lower()]
            if leading:
                target = next((p for p in out if p.span[0] > q.start()), None)
            else:
                target = next((p for p in reversed(out) if p.span[1] <= q.start()), None)
            if target is None:
                continue
            target.kind = kind
            s, e = target.span
            target.span = (min(s, q.start()), max(e, q.end()))
    return out


# ----------------------------------------------------------------- item phrases

_FILLER = re.compile(
    r"""\b(?:pm|pmo|p\.m|msg|message|whisper|/w|w/|hmu|cc|me|fm\s*\d*|ch(?:annel)?\.?\s*\d+|room\s*\d+|
          obo|neg|negotiable|o/o|offers?|offer\?|or\s+best|best\s+offer|cheap|fast|quick|asap|ty|thx|pls|plz|
          only|all|still|now|today|lf\s*buyer|accepting|taking|take|some|my|your|ur|any|anyone|
          ea|each|per|is|are|will|can|nx|bundle|pcs?|pieces?|stack(?:s)?|x\d+|\d+x|
          paying|pay|budget|have|got|offering|need|needed|wanted|want|mesos?|few|more|at|sets?|rank\s*\d+)\b""",
    re.I | re.X,
)
# small words that are filler around an item name but part of names like "Fragment of Magic"
_EDGE_WORDS = re.compile(r"^(?:(?:a|an|the|of|in|on|with|w|and|or|for|set)\s+)+|(?:\s+(?:a|an|the|of|in|on|with|w|and|or|for|set))+$", re.I)
_STAT = r"(?:w\.?att|watk|matk|m\.?att|attack|att|atk|wa|ma|str|dex|int|luk|acc|avoid|avo|speed|spd|jump|hp|mp|wdef|mdef|def|crit)"
_STAT_NAME = {
    "crit": "CRIT", "attack": "ATT",
    "watt": "ATT", "w.att": "ATT", "watk": "ATT", "att": "ATT", "atk": "ATT", "wa": "ATT",
    "matk": "M.ATT", "matt": "M.ATT", "m.att": "M.ATT", "ma": "M.ATT", "str": "STR", "dex": "DEX",
    "int": "INT", "luk": "LUK", "acc": "ACC", "avoid": "AVOID", "avo": "AVOID", "speed": "SPEED",
    "spd": "SPEED", "jump": "JUMP", "hp": "HP", "mp": "MP", "def": "DEF", "wdef": "DEF", "mdef": "MDEF",
}
_VARIANT_STAT = re.compile(r"(?<![\w%])(?P<sign>[+-])?(?P<n>\d{1,3})\s*(?P<stat>" + _STAT + r")\b", re.I)  # "+5 att", "(-3ATT)"
# stat written first: "ATT+2" is +2 ATT; weapon attack of 20+ is the weapon's total ("Olympus WA73", "atk+83")
_VARIANT_STAT_FIRST = re.compile(
    r"\b(?P<stat>w\.?att|watk|wa|atk|att|matk|m\.?att|ma|str|dex|int|luk|crit)\s?(?P<plus>\+)?(?P<n>\d{1,3})\b(?!\s*%)", re.I)
_VARIANT_NOTE = re.compile(r"\((?P<sign>[+-])\s?(?P<n>\d{1,2})\)")  # "(+3)", "(-2)": above or below the usual roll
_VARIANT_PLUS = re.compile(r"(?<![\w+])\+(?P<n>\d{1,2})\b(?!\s*(?:k|m|b|mil)\b|\s*%|\.\d)", re.I)  # "+3 clean slain", "Heckler +4"
_VARIANT_WORDS = re.compile(r"\b(?P<w>clean|perfect|perf|godly|avg|average|untradeable|untrad(?:e)?able|(?:fully\s+)?scrolled)\b", re.I)
# "7 slots", "4/7 slot", "4 upgrades"; not the "5 Slot Coupons" item
_VARIANT_SLOTS = re.compile(r"\b(?:(?P<left>\d{1,2})\s*/\s*)?(?P<n>\d{1,2})\s*(?:slots?|slts?|upgrades?|upgs?)\b(?!\s*coupons?)", re.I)
_LEAD_QTY = re.compile(r"^\(?(?P<n>\d{1,4})\)?\s+(?=[A-Za-z])(?!(?i:slots?|slts?)\b)")  # "100 red potion", "(5) Mokbi"; not "5 Slot Coupons"
_SCROLL_QTY = re.compile(r"^\(?(?P<n>\d{1,4})\)?(?=\s|$)")  # what is left once the scroll name is cut out: "(2)"
_QTY = re.compile(r"(?:\bx\s*(?P<a>\d{1,4})\b|\b(?P<b>\d{1,4})\s*x\b|\b(?P<c>\d{1,4})\s*(?:pcs?|pieces?)\b)", re.I)
_BRACKET = re.compile(r"[\[<«]\s*(?P<item>[A-Za-z0-9][^\]>»\[<]{1,60}?)\s*[\]>»]")


@lru_cache(maxsize=1)
def _scroll_rules() -> dict:
    return json.loads((SEED_DIR / "scroll_rules.json").read_text(encoding="utf-8"))


def _alt(words) -> str:
    return "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))


@lru_cache(maxsize=1)
def _scroll_regexes():
    r = _scroll_rules()
    slots, stats, tiers = _alt(r["slots"]), _alt(r["stats"]), _alt(r["tier_words"])
    pct_first = re.compile(
        rf"\b(?P<pct>\d{{1,3}})\s*%?\s*(?P<slot>{slots})\s+(?:for\s+)?(?P<stat>{stats})\b(?:\s*scrolls?)?", re.I)
    slot_first = re.compile(  # "glove att 60%", and "Ear Str 60" without the % sign
        rf"(?:\bscrolls?\s+(?:for\s+)?)?\b(?P<slot>{slots})\s+(?:for\s+)?(?P<stat>{stats})\s*(?:scrolls?\s*)?(?P<pct>\d{{1,3}})"
        rf"(?:\s*%|\b(?!\s*(?:slots?|slts?|pcs?|x\b|ea\b|each\b|k\b|m\b)))", re.I)
    pct_stat_first = re.compile(  # "60% INT Earring", "EAR 60 DEX"
        rf"\b(?:(?P<pct>\d{{1,3}})\s*%\s*(?P<stat>{stats})\s+(?P<slot>{slots})"
        rf"|(?P<slot2>{slots})\s+(?P<pct2>\d{{1,3}})\s*%?\s+(?P<stat2>{stats}))\b(?:\s*scrolls?)?", re.I)
    tier_form = re.compile(  # "lesser pet speed", "pet speed lesser", "Pet Lesser Speed"
        rf"\b(?:(?P<tier>{tiers})\s+(?P<slot>{slots})\s+(?P<stat>{stats})|(?P<slot2>{slots})\s+(?P<stat2>{stats})\s*(?:scrolls?)?\s*:?\s*(?P<tier2>{tiers})"
        rf"|(?P<slot3>{slots})\s+(?P<tier3>{tiers})\s+(?P<stat3>{stats}))\b(?:\s*scrolls?)?",
        re.I)
    return pct_first, slot_first, pct_stat_first, tier_form


@lru_cache(maxsize=1)
def _shorthand_regex():
    words = _scroll_rules().get("shorthand", {})
    return re.compile(rf"\b(?:{_alt(words)})\b", re.I) if words else None


def expand_shorthand(phrase: str) -> str:
    """'GFA 60%' -> 'glove att 60%' (the "shorthand" table in scroll_rules.json)."""
    rx = _shorthand_regex()
    return rx.sub(lambda m: _scroll_rules()["shorthand"][m.group(0).lower()], phrase) if rx else phrase


def match_scroll(phrase: str) -> tuple[str, tuple[int, int]] | None:
    """'60% glove att' -> ('Gloves Attack Scroll: Intermediate', span)."""
    r = _scroll_rules()
    lower = {k.lower(): v for k, v in r["slots"].items()}
    lstats = {k.lower(): v for k, v in r["stats"].items()}
    ltiers = {k.lower(): v for k, v in r["tier_words"].items()}
    pct_first, slot_first, pct_stat_first, tier_form = _scroll_regexes()
    m1, m2 = pct_first.search(phrase), slot_first.search(phrase)
    # "1 cloak luck scrolls 100%": a number without % in front is a quantity when a % follows
    order = (m2, m1) if m2 and not (m1 and "%" in m1.group(0)) else (m1, m2)
    def g(m, name):  # a regex with alternative word orders numbers its groups: slot, slot2, slot3
        return next(m.group(k) for k in (name, name + "2", name + "3") if k in m.re.groupindex and m.group(k))

    for m in (*order, pct_stat_first.search(phrase)):
        if m:
            pct = str(int(g(m, "pct")))
            if int(pct) not in (1, 2, 3, 5, 10, 15, 30, 50, 60, 65, 70, 100):
                continue
            if "%" not in m.group(0) and int(pct) not in (10, 30, 60, 70, 100):
                continue  # without a % sign only the usual scroll odds count
            slot = lower[g(m, "slot").lower()]
            stat = lstats[g(m, "stat").lower()]
            tier = r["pct_to_tier"].get(pct)
            fmt = r["name_format"] if tier else r["fallback_format"]
            return fmt.format(slot=slot, stat=stat, tier=tier, pct=pct), m.span()
    m = tier_form.search(phrase)
    if m:
        tier = ltiers[g(m, "tier").lower()]
        slot = lower[g(m, "slot").lower()]
        stat = lstats[g(m, "stat").lower()]
        return r["name_format"].format(slot=slot, stat=stat, tier=tier, pct=""), m.span()
    return None


def _extract_variant(phrase: str) -> tuple[str, str]:
    parts: list[str] = []

    def stat(m):
        sign = "-" if m.group("sign") == "-" else "+"  # "-3 ATT": three below the usual roll
        parts.append(f"{sign}{int(m.group('n'))} {_STAT_NAME.get(m.group('stat').lower().replace(' ', ''), m.group('stat').upper())}")
        return " "

    def word(m):
        w = m.group("w").lower()
        w = "scrolled" if w.endswith("scrolled") else w
        parts.append({"perf": "perfect", "average": "avg"}.get(w, "untradeable" if w.startswith("untrad") else w))
        return " "

    def slots(m):
        left = f"{int(m.group('left'))}/" if m.group("left") else ""
        parts.append(f"{left}{int(m.group('n'))} slots")
        return " "

    def stat_first(m):
        name, n = _STAT_NAME.get(m.group("stat").lower().replace(" ", ""), m.group("stat").upper()), int(m.group("n"))
        if n >= 20 and name in ("ATT", "M.ATT"):
            parts.append(f"{name} {n}")  # a weapon's total attack
        elif m.group("plus"):
            parts.append(f"+{n} {name}")
        else:
            return m.group(0)  # "att 5" alone says too little
        return " "

    def note(m):
        parts.append(f"({m.group('sign')}{int(m.group('n'))})")
        return " "

    def plus(m):
        parts.append(f"+{int(m.group('n'))}")
        return " "

    phrase = _VARIANT_STAT.sub(stat, phrase)
    phrase = _VARIANT_STAT_FIRST.sub(stat_first, phrase)
    phrase = _VARIANT_NOTE.sub(note, phrase)
    phrase = _VARIANT_PLUS.sub(plus, phrase)
    phrase = _VARIANT_WORDS.sub(word, phrase)
    phrase = _VARIANT_SLOTS.sub(slots, phrase)
    # stable order: stats first (sorted), then words
    parts = sorted(set(parts), key=lambda p: (p[0] not in "+-", p))
    return ", ".join(parts), phrase


def _clean_item_phrase(phrase: str) -> str:
    p = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", phrase)  # "GentlemanMustache" -> "Gentleman Mustache"
    p = re.sub(r"<3+", " ", p)  # a heart, not a number: "Kumbi 325k :) <3"
    p = _FILLER.sub(" ", p)
    p = re.sub(r"[^A-Za-z0-9'%:\-\. ]+", " ", p)
    p = re.sub(r"(?<!\w)[\-\.:']+|[\-\.:']+(?!\w)", " ", p)
    p = re.sub(r"\s+", " ", p).strip()
    p = _EDGE_WORDS.sub("", p).strip()
    return "" if re.fullmatch(r"(?i)a|an|the|of|in|on|with|w|and|or|for|set", p) else p  # "3 for 580k": no name left


# --------------------------------------------------------------------- segments

_SPLIT = re.compile(r"\s*(?:;|\||\s/\s|\s\+\s|\s&\s|(?<!\d),|,(?!\d)|\s{3,})\s*")


def _segments(block: str) -> list[str]:
    return [s for s in (x.strip(" .!?-~") for x in _SPLIT.split(block)) if s]


_JOINERS = re.compile(r"\b(?:and|or|also|plus|n|&)\b", re.I)


def _parse_segment(seg: str, intent: str) -> tuple[list[Observation], str | None]:
    prices = _find_prices(seg)
    # "earrings 24k and bc ore 3200": item words between two prices start a new item
    for a, b in zip(prices, prices[1:]):
        between = _JOINERS.sub(" ", _QUALS.sub(" ", _FILLER.sub(" ", seg[a.span[1]: b.span[0]])))
        if re.search(r"[A-Za-z]{2,}", between):
            left_obs, left_np = _parse_segment(seg[: a.span[1]], intent)
            right_obs, right_np = _parse_segment(seg[a.span[1]:], intent)
            return left_obs + right_obs, left_np or right_np
    # Words after the last price are notes ("c/o 2.5m a/w 3m - no item trade meso only",
    # "85k COME GRAB") when the item was named before it; stats written there still count.
    tail_variant = ""
    if prices and re.search(r"[A-Za-z]{2,}", _QUALS.sub(" ", seg[: prices[0].span[0]])):
        tail_variant, _ = _extract_variant(seg[prices[-1].span[1]:])
        seg = seg[: prices[-1].span[1]]
    # strip the price text out of the item phrase
    item_part = seg
    for p in reversed(prices):
        item_part = item_part[: p.span[0]] + " " + item_part[p.span[1]:]

    qty = 1
    each_word = bool(re.search(r"\b(?:ea|each|per|apiece)\b", seg, re.I))
    qm = _QTY.search(item_part)
    if qm:
        qty = int(qm.group("a") or qm.group("b") or qm.group("c"))
        item_part = item_part[: qm.start()] + " " + item_part[qm.end():]

    scroll_text = expand_shorthand(item_part)
    scroll = match_scroll(scroll_text)
    if scroll:
        name, span = scroll
        rest = scroll_text[: span[0]] + " " + scroll_text[span[1]:]
        lq = _SCROLL_QTY.match(rest.strip())
        if lq and qty == 1:
            qty = int(lq.group("n"))
        item_text, variant, is_scroll = name, "", True
    else:
        variant, rest = _extract_variant(item_part)
        rest = rest.strip()
        lq = _LEAD_QTY.match(rest)
        if lq and qty == 1:
            qty = int(lq.group("n"))
            rest = rest[lq.end():]
        item_text, is_scroll = _clean_item_phrase(rest), False
    if tail_variant:
        variant = ", ".join(sorted(set(filter(None, variant.split(", ") + tail_variant.split(", "))),
                                   key=lambda p: (p[0] not in "+-", p)))

    qty = max(1, min(qty, 9999))
    if not prices:
        return [], ((item_text, variant, is_scroll) if item_text else None)

    # "c/o 230k a/w 300": a buyout can't be below the current offer, so it lost its k
    offer = next((p.value for p in prices if p.kind == "current_offer"), None)
    for p in prices:
        if p.kind == "buyout" and offer and p.value < offer <= p.value * 1000 <= offer * 10:
            p.value *= 1000

    obs: list[Observation] = []
    for p in prices:
        kind = p.kind
        this_intent = intent
        if kind == "current_offer" and intent == "sell":
            this_intent = "buy"  # c/o is what a buyer offered
        if kind == "ask" and intent == "buy":
            kind = "bid"
        unit = p.value if (p.each or each_word or qty == 1) else max(1, p.value // qty)
        obs.append(Observation(this_intent, item_text, variant, p.value, unit, qty, kind, False, is_scroll))
    return obs, None


# mesos-for-dollars spam megaphones: "Mesos price low to 100K/$6.5 Items hotsale"
_REAL_MONEY = re.compile(r"\$\s?\d|\d\s?\$|\b(?:usd|paypal|venmo|hot\s?sale|www\.|\.com|\.net)\b", re.I)


# ----------------------------------------------------------------------- public


def parse_line(text: str, source: str | None = None) -> ParsedLine:
    """Parse one chat line. ``source`` is the collector's guess at the chat channel."""
    norm = split_messages(normalize_text(text))[0]  # ingest splits glued messages; old stored lines may hold two
    player, msg = split_speaker(norm)
    if _REAL_MONEY.search(msg):
        return ParsedLine(player, msg, False, notes=["real-money ad"])

    msg = re.sub(r"^(?=[A-Za-z][^\[\]<>]{2,60}\])", "[", msg)  # OCR lost the link's "[": "Work Gloves] c/o 1m"
    brackets = [m.group("item").strip() for m in _BRACKET.finditer(msg)]
    body = _BRACKET.sub(" ", msg) if brackets else msg
    body = re.sub(r"\[?\bch(?:annel)?\.?\s*\d{1,2}\b\]?", " ", body, flags=re.I)

    marks = list(_MARKERS.finditer(body))
    blocks: list[tuple[str, str]] = []
    if marks:
        if any(m.lastgroup == "pc" for m in marks) and not any(m.lastgroup in ("sell", "buy", "buyq") for m in marks):
            return ParsedLine(player, msg, False, notes=["price check"])
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            kind = m.lastgroup
            intent = {"sell": "sell", "buy": "buy", "buyq": "buy"}.get(kind)
            chunk = body[m.end():end]
            if intent is None:  # trade / pc chunks carry no meso price we can trust
                continue
            # "S>" immediately followed by another marker: merge into next
            if not chunk.strip() and i + 1 < len(marks):
                continue
            blocks.append((intent, chunk))
        # text before the first marker (e.g. "bwg 12m S>") belongs to the first intent
        pre = body[: marks[0].start()].strip()
        if pre and blocks and _find_prices(pre):
            blocks.insert(0, (blocks[0][0], pre))
    elif (source in MEGAPHONE_SOURCES or brackets) and _find_prices(body):
        blocks.append(("sell", body))  # megaphone ads without "S>" are almost always selling

    observations: list[Observation] = []
    notes: list[str] = []
    bracket_iter = iter(brackets)
    single_bracket = brackets[0] if len(brackets) == 1 else None
    # An item megaphone's [Item] names the first priced item, however the player typed it
    # ("[Ink-and-Wash Painting Name Tag Ring] S> Ink and wash name ring 1.8M"). Later items
    # in the same line ("S> myster palette 100") keep their own words unless they have none.
    bracket_free = single_bracket is not None
    for intent, chunk in blocks:
        segs = _segments(chunk)
        pending = None  # an item named without a price just before: "kfan +8wa fully scrolled, 400k"
        for seg in segs:
            obs, no_price = _parse_segment(seg, intent)
            if no_price:
                notes.append(f"no price: {no_price[0]}")
            use_bracket = bracket_free and bool(obs)
            bracket_free = bracket_free and not obs
            for o in obs:
                weak_phrase = len(o.item_text.replace(" ", "")) < 3
                if weak_phrase and pending and not o.is_scroll_rule:
                    o.item_text, o.variant, o.is_scroll_rule = pending[0], o.variant or pending[1], pending[2]
                elif (weak_phrase or use_bracket) and not o.is_scroll_rule:
                    name = single_bracket or next(bracket_iter, None)
                    if name:
                        o.typed_item = "" if weak_phrase else o.item_text
                        o.item_text, o.from_bracket = name, True
                if len(o.item_text.replace(" ", "")) >= 2:
                    observations.append(o)
                else:
                    notes.append(f"price without item: {o.price}")
            pending = no_price if not obs else None

    is_trade = bool(observations) or any(m.lastgroup in ("sell", "buy", "buyq", "trade") for m in marks)
    return ParsedLine(player, msg, is_trade, observations, notes)


def format_mesos(v: int | float | None) -> str:
    if v is None:
        return "-"
    v = float(v)
    for div, suf in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if v >= div:
            x = v / div
            s = f"{x:.0f}" if x >= 100 else f"{x:.1f}" if x >= 10 else f"{x:.2f}"
            return (s.rstrip("0").rstrip(".") if "." in s else s) + suf
    return f"{int(v)}"
