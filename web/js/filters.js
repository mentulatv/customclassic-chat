// What the chat leaves out, and the watch list: the desktop app's rules (customclassic_chat.py,
// watch.py), ported. Nothing here looks at the game: only at messages already read.
import { ratio } from "./reader.js";

// ---------------------------------------------------------------- lines padded with spacers

// a line padded out to fill the chat ("…scroll@@@@@@@@@@@@"): a long run of one symbol, or a
// long word of one or two characters with a symbol among them ("@QQQ@QQQQ")
export function padded(body) {
  if (/([^\w\s])\1{5,}/.test(body)) return true;
  return body.split(/\s+/).some(w => w.length >= 8 && (new Set(w).size === 1 || (new Set(w).size <= 2 && /[^\w]/.test(w))));
}

const PARTY_AD = /\b(?:[a-z]?pq|lf[gm]?\d*|party|pt|need\s*\d*\s*more|join|recruit\w*|leech\w*|carry|exp\s*share|boss\s*run|zak(?:um)?\s*run|\d\s*\/\s*6)\b/i;
const TRADE_AD = /(?:\b[sbt]\s*>|\bwt[sbt]\b|\bsell\w*|\bbuy\w*|\bc\s*\/\s*o\b|\b\d+(?:[.,]\d+)?\s*(?:k|m|mil|b)\b)/i;
export const PADDED_KINDS = [["trade", "Buying and selling"], ["party", "Party quests and parties"], ["other", "Everything else"]];

// what a padded line is about: "trade", "party" or "other"
export function paddedKind(body) {
  const marker = /\b[sbt]\s*>|\bwt[sbt]\b|\bsell|\bbuy/i.test(body);
  if (PARTY_AD.test(body) && !marker) return "party";
  return TRADE_AD.test(body) ? "trade" : PARTY_AD.test(body) ? "party" : "other";
}

// ---------------------------------------------------------------- the watch list

export function norm(text) {
  return String(text).toLowerCase().replace(/&/g, " and ").replace(/[-_/]/g, " ").replace(/[^a-z0-9%: ]+/g, "")
    .replace(/:/g, " ").replace(/\s+/g, " ").trim();
}
const unblur = n => [["rn", "m"], ["vv", "w"], ["cl", "d"], ["0", "o"], ["1", "l"], ["l", "i"]].reduce((s, [a, b]) => s.split(a).join(b), n);
const hasWord = (w, t) => new RegExp(`(?<![a-z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}s?(?![a-z0-9])`).test(t);

// whether the text names the word: whole, or (unless exact) close enough for blurry reading
export function mentions(word, text, exact = false) {
  const w = norm(word), t = norm(text);
  if (!w || !t) return false;
  if (hasWord(w, t)) return true;
  if (exact) return false;
  if (hasWord(unblur(w), unblur(t))) return true;
  if (w.length < 5) return false;
  const k = w.split(" ").length, words = t.split(" ");
  for (let i = 0; i + k <= words.length; i++) if (ratio(w, words.slice(i, i + k).join(" ")) >= 88) return true;
  return false;
}

export function parsePrice(text) {  // "2.5m", "400k", "1,200,000" as mesos
  const m = /^\s*([\d.,]+)\s*([kmb]?)\s*$/i.exec(text || "");
  if (!m) return null;
  const [, raw, suf] = m;
  const v = suf || (raw.match(/\./g) || []).length <= 1 ? parseFloat(raw.replace(/,/g, "")) : parseFloat(raw.replace(/[.,]/g, ""));
  return Math.round(v * { "": 1, k: 1e3, m: 1e6, b: 1e9 }[suf.toLowerCase()]) || null;
}
export function money(v) {
  if (v == null) return "?";
  for (const [size, suf] of [[1e9, "b"], [1e6, "m"], [1e3, "k"]]) if (v >= size) return +(v / size).toPrecision(3) + suf;
  return String(Math.round(v));
}

// a megaphone's offers, simply: each "S>" / "B>" (or selling / buying) part, with the prices in it
export function offers(body) {
  const parts = [], re = /(?:\b([sbt])\s*[>/<]|\b(wt[sbt])\b|\b(sell\w*|buy\w*))/ig;
  let m, last = null;
  while ((m = re.exec(body))) {
    const word = (m[1] || m[2] || m[3]).toLowerCase();
    const intent = word.startsWith("s") || word === "wts" ? "sell" : word.startsWith("b") || word === "wtb" ? "buy" : "trade";
    if (last) last.text = body.slice(last.at, m.index);
    last = { intent, at: m.index + m[0].length, text: "" };
    parts.push(last);
  }
  if (last) last.text = body.slice(last.at);
  if (!parts.length) parts.push({ intent: "?", text: body });
  return parts.map(p => {
    const prices = [...p.text.matchAll(/(\d+(?:[.,]\d+)?)\s*(k|m|mil|b)\b/ig)]
      .map(x => parsePrice(x[1] + x[2].replace(/mil/i, "m").toLowerCase())).filter(Boolean);
    return { intent: p.intent, text: p.text, price: prices[0] || null, each: /\b(ea|each)\b/i.test(p.text) };
  });
}

// the item names and the shorthands chat uses (the site's /api/names)
export class Catalog {
  constructor(items = []) {
    this.items = items;
    this.byNorm = new Map();
    for (const it of items) if (!this.byNorm.has(norm(it.name))) this.byNorm.set(norm(it.name), it);
    for (const it of items) for (const a of it.aliases || []) if (!this.byNorm.has(norm(a))) this.byNorm.set(norm(a), it);
  }
  static async load() {
    try {
      const cached = JSON.parse(localStorage.getItem("ccc.names") || "null");
      if (cached && Date.now() - cached.at < 3600000) return new Catalog(cached.items);
      const r = await fetch("/api/names");
      const items = (await r.json()).items;
      localStorage.setItem("ccc.names", JSON.stringify({ at: Date.now(), items }));
      return new Catalog(items);
    } catch {
      return new Catalog(JSON.parse(localStorage.getItem("ccc.names") || "{}").items || []);
    }
  }
  resolve(text) {
    const n = norm(text);
    if (!n) return null;
    const hit = this.byNorm.get(n) || this.byNorm.get(n.endsWith("s") && n.length > 3 ? n.slice(0, -1) : n);
    if (hit || /\d/.test(n) || n.length < 5) return hit || null;
    let best = null, score = 88;
    for (const [k, it] of this.byNorm) { const s = ratio(n, k); if (s >= score) { score = s; best = it; } }
    return best;
  }
  suggest(text, limit = 8) {
    const n = norm(text);
    if (!n) return [];
    const names = [...new Set(this.items.map(i => i.name))].sort();
    const first = names.filter(x => norm(x).startsWith(n)), inside = names.filter(x => norm(x).includes(n) && !first.includes(x));
    const alias = [...this.byNorm].filter(([k, it]) => k.startsWith(n)).map(([, it]) => it.name);
    return [...new Set([...first, ...inside, ...alias])].slice(0, limit);
  }
}

// which watch-list entries a message hits: [why], at most once per entry and player every 10 minutes
export class Watcher {
  constructor(entries, catalog, kinds) { this.entries = entries; this.catalog = catalog; this.kinds = new Set(kinds); this.recent = new Map(); }
  namesFor(e) {
    const item = this.catalog.resolve(e.text);
    return [[...new Set([e.text, ...(item ? [item.name, ...(item.aliases || [])] : [])])], item];
  }
  check(msg, now = Date.now()) {
    if (!this.kinds.has(msg.kind) || !msg.body) return [];
    const hits = [];
    for (const e of this.entries) {
      if (e.on === false || !e.text?.trim()) continue;
      const [names, item] = this.namesFor(e);
      if (!(e.sellers_only || e.max_price || e.min_price)) {
        if (names.some(n => mentions(n, msg.body, e.exact))) hits.push([e, `mentions ${e.text}`]);
        continue;
      }
      for (const o of offers(msg.body)) {
        if (!names.some(n => mentions(n, o.text, e.exact)) && !(item && this.catalog.resolve(o.text) === item)) continue;
        if (e.sellers_only && o.intent !== "sell") continue;
        if (e.max_price && (!o.price || o.price > e.max_price)) continue;
        if (e.min_price && (!o.price || o.price < e.min_price)) continue;
        hits.push([e, `${o.intent === "buy" ? "buying" : "selling"} ${e.text}${o.price ? ` for ${money(o.price)}${o.each ? " each" : ""}` : ""}`]);
        break;
      }
    }
    return hits.filter(([e]) => {
      const key = `${e.text.toLowerCase()}|${(msg.name || "").toLowerCase()}`;
      if (now - (this.recent.get(key) || -1e12) < 600000) return false;
      this.recent.set(key, now);
      return true;
    }).map(([, why]) => why);
  }
}

export function entryLabel(e) {
  const bits = [e.text];
  if (e.exact) bits.push("exact");
  if (e.sellers_only) bits.push("sellers");
  if (e.min_price && e.max_price) bits.push(`${money(e.min_price)}–${money(e.max_price)}`);
  else if (e.max_price) bits.push(`≤ ${money(e.max_price)}`);
  else if (e.min_price) bits.push(`≥ ${money(e.min_price)}`);
  return bits.join(" · ");
}

// ---------------------------------------------------------------- sounds

let audio = null;
export function chime(notes, volume = 0.4) {  // soft sine notes a little apart
  try {
    audio ||= new AudioContext();
    const t0 = audio.currentTime;
    notes.forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain(), t = t0 + i * 0.07;
      o.frequency.value = f; o.connect(g); g.connect(audio.destination);
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(volume * 0.3, t + 0.01); g.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
      o.start(t); o.stop(t + 0.36);
    });
  } catch {}
}
export const WHISPER_NOTES = [987.8, 1318.5], WATCH_NOTES = [1046.5, 1318.5, 1568.0];
