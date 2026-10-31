"""CustomClassic Chat's watch list: words and items to look out for in megaphones.

An entry is a word or an item name. On its own it fires on any megaphone that mentions it
(close spellings count, so "mushrnom" from a blurry read still finds "mushmom", unless the
entry asks for the exact word). Give it a condition (sellers only, or a price range you set)
and it reads the megaphone like the price site does: its own parser (trade_parser.py) finds
what's sold or bought at what price. Item names and the shorthands chat uses for them come
from the price site's /api/names (kept for an hour in cache/names.json, so it works offline
from the last copy); prices are only ever the ones you type.

Nothing here touches the game: it only looks at messages CustomClassic Chat already read.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from rapidfuzz import fuzz, process

# packaged as an .exe, your settings, history and caches live next to it (the program's own
# files are in its _internal folder); run from source, next to this file
HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
NAMES_FILE = HERE / "cache" / "names.json"
NAMES_URL = "https://customclassic.chat/api/names"
NAMES_EVERY = 3600
FUZZY = 88  # how close a spelling must be to count
REPEAT_S = 600  # the same entry and player alert once per 10 minutes


def norm(text: str) -> str:
    """The price server's own name normaliser (app.items.norm), kept in step by hand."""
    n = text.lower().replace("&", " and ")
    n = re.sub(r"[\-_/]", " ", n)
    n = re.sub(r"[^a-z0-9%: ]+", "", n)
    n = n.replace(":", " ")
    return re.sub(r"\s+", " ", n).strip()


def _plural_free(n: str) -> str:
    return n[:-1] if n.endswith("s") and len(n) > 3 else n


def money(v: int | float | None) -> str:
    if v is None:
        return "?"
    for size, suf in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if v >= size:
            return f"{v / size:.3g}{suf}"
    return str(int(v))


def parse_price(text: str) -> int | None:
    """'2.5m', '400k', '1,200,000' as mesos; None when it isn't a price."""
    m = re.fullmatch(r"\s*([\d.,]+)\s*([kmb]?)\s*", (text or "").lower())
    if not m:
        return None
    raw, suf = m.groups()
    try:
        v = float(raw.replace(",", "")) if suf or raw.count(".") <= 1 else float(raw.replace(".", "").replace(",", ""))
    except ValueError:
        return None
    return round(v * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[suf]) or None


# ------------------------------------------------------------------ item names


class Catalog:
    """The price server's item names and the other ways chat writes them."""

    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.by_norm: dict[str, dict] = {}
        for it in self.items:
            self.by_norm.setdefault(norm(it["name"]), it)
        for it in self.items:
            for a in it.get("aliases") or []:
                self.by_norm.setdefault(norm(a), it)
        self.keys = list(self.by_norm)

    @classmethod
    def load(cls, url: str = NAMES_URL, cache: Path = NAMES_FILE, fetch=None) -> "Catalog":
        """The cached copy while it's under an hour old, else a fresh one (the stale copy if
        the server can't be reached; none at all just means names aren't suggested)."""
        try:
            fresh = time.time() - cache.stat().st_mtime < NAMES_EVERY
            items = json.loads(cache.read_text(encoding="utf-8"))["items"]
        except (OSError, ValueError, KeyError):
            fresh, items = False, None
        if not fresh:
            try:
                data = (fetch or _fetch)(url)
                items = data["items"]
                cache.parent.mkdir(exist_ok=True)
                cache.write_text(json.dumps(data), encoding="utf-8")
            except Exception:  # offline or the server's down: keep what we have
                pass
        return cls(items)

    def resolve(self, text: str) -> dict | None:
        """The catalog item a name means: exact, an alias, a plural, or a close spelling.
        Names with numbers in them (scroll %, stats) only match exactly."""
        n = norm(text)
        if not n:
            return None
        hit = self.by_norm.get(n) or self.by_norm.get(_plural_free(n))
        if hit or re.search(r"\d", n) or len(n) < 5 or not self.keys:
            return hit
        best = process.extractOne(n, self.keys, scorer=fuzz.ratio, score_cutoff=FUZZY)
        return self.by_norm[best[0]] if best else None

    def suggest(self, text: str, limit: int = 8) -> list[str]:
        """Item names for what's typed so far: starting with it, then containing it, then close."""
        n = norm(text)
        if not n:
            return []
        names = sorted({it["name"] for it in self.items})
        first = [x for x in names if norm(x).startswith(n)]
        inside = [x for x in names if n in norm(x) and x not in first]
        alias = [it["name"] for k, it in self.by_norm.items() if k.startswith(n) and it["name"] not in first + inside]
        out = list(dict.fromkeys(first + inside + alias))
        if len(out) < limit and len(n) >= 3:
            close = process.extract(n, names, scorer=fuzz.partial_ratio, processor=norm, limit=limit, score_cutoff=80)
            out += [c[0] for c in close if c[0] not in out]
        return out[:limit]


def _fetch(url: str) -> dict:
    import httpx

    r = httpx.get(url, timeout=10, follow_redirects=True)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ entries


@dataclass
class Entry:
    text: str  # a word ("mano") or an item name ("Work Gloves")
    exact: bool = False  # only the whole word as written, no close spellings
    sellers_only: bool = False  # only "S>" / selling megaphones
    max_price: int | None = None  # only when it's offered at this or less
    min_price: int | None = None  # only when it's offered at this or more (leaves out "1k" typos and junk)
    on: bool = True

    @property
    def reads_price(self) -> bool:
        return self.sellers_only or bool(self.max_price) or bool(self.min_price)

    def price_range(self) -> str:
        """'100k–1.5m', '≤ 1.5m', '≥ 100k' or ''."""
        lo, hi = self.min_price, self.max_price
        if lo and hi:
            return f"{money(lo)}–{money(hi)}"
        return f"≤ {money(hi)}" if hi else (f"≥ {money(lo)}" if lo else "")

    def label(self) -> str:
        bits = [self.text]
        if self.exact:
            bits.append("exact")
        if self.sellers_only:
            bits.append("sellers")
        if self.price_range():
            bits.append(self.price_range())
        return " · ".join(bits)

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


OCR_LOOKALIKES = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("l", "i")]


def _unblur(n: str) -> str:
    """Letters text recognition mixes up, folded together: 'mushrnom' reads as 'mushmom'."""
    for a, b in OCR_LOOKALIKES:
        n = n.replace(a, b)
    return n


def _has_word(w: str, t: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(w)}s?(?![a-z0-9])", t) is not None


def mentions(word: str, text: str, exact: bool = False) -> bool:
    """Whether the text names the word: as a whole word, or (unless exact) in a spelling
    close enough for blurry text recognition. Short words (under 5 letters) need the whole word."""
    w, t = norm(word), norm(text)
    if not w or not t:
        return False
    if _has_word(w, t):
        return True
    if exact:
        return False
    if _has_word(_unblur(w), _unblur(t)):
        return True
    if len(w) < 5:
        return False
    k, words = w.count(" ") + 1, t.split()  # the same number of words, spelled close enough
    return any(fuzz.ratio(w, " ".join(words[i:i + k])) >= FUZZY for i in range(len(words) - k + 1))


def _parse(name: str, body: str):
    from trade_parser import parse_line

    return parse_line(f"{name or 'x'} : {body}", "megaphone").observations


class Watcher:
    """Checks messages against the watch list and says which entries they hit, at most once
    per entry and player every 10 minutes."""

    def __init__(self, entries: list[Entry], catalog: Catalog | None = None, kinds=("mega",)):
        self.entries = entries
        self.catalog = catalog or Catalog()
        self.kinds = set(kinds)
        self.recent: dict[tuple, float] = {}

    def names_for(self, entry: Entry) -> tuple[list[str], dict | None]:
        item = self.catalog.resolve(entry.text)
        names = [entry.text]
        if item:
            names += [item["name"]] + list(item.get("aliases") or [])
        return list(dict.fromkeys(names)), item

    def check(self, msg: dict, now: float | None = None) -> list[tuple[Entry, str]]:
        """[(entry, why)] for the entries this message hits; [] for none."""
        if msg.get("kind") not in self.kinds or not msg.get("body"):
            return []
        now = time.time() if now is None else now
        hits, obs = [], None
        for e in self.entries:
            if not e.on or not e.text.strip():
                continue
            names, item = self.names_for(e)
            if not e.reads_price:
                if any(mentions(n, msg["body"], e.exact) for n in names):
                    hits.append((e, f"mentions {e.text}"))
                continue
            if obs is None:
                try:
                    obs = _parse(msg.get("name") or "", msg["body"])
                except Exception:
                    obs = []
            why = self._offer(e, names, item, obs)
            if why:
                hits.append((e, why))
        out = []
        for e, why in hits:
            key = (e.text.lower(), (msg.get("name") or "").lower())
            if now - self.recent.get(key, -1e9) >= REPEAT_S:
                self.recent[key] = now
                out.append((e, why))
        return out

    def _offer(self, e: Entry, names: list[str], item: dict | None, obs) -> str | None:
        for o in obs:
            said = [o.item_text, o.typed_item]
            same = any(mentions(n, s, e.exact) for n in names for s in said if s) or (
                item is not None and self.catalog.resolve(o.item_text) is item)
            if not same:
                continue
            if e.sellers_only and o.intent != "sell":
                continue
            if o.price_kind in ("current_offer", "starting_bid") and (e.max_price or e.min_price):
                continue  # an auction's offer so far, not a price you can buy at
            price = o.unit_price or None
            if e.max_price and (not price or price > e.max_price):
                continue
            if e.min_price and (not price or price < e.min_price):
                continue
            verb = "selling" if o.intent == "sell" else "buying"
            where = f" for {money(price)}" + (" each" if o.qty > 1 else "") if price else ""
            return f"{verb} {e.text}{where}"
        return None


def load_entries(raw) -> list[Entry]:
    out = []
    for d in raw or []:
        try:
            out.append(Entry.from_dict(d) if isinstance(d, dict) else Entry(str(d)))
        except TypeError:
            pass
    return out
