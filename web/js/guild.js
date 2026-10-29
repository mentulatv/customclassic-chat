// Guild chat ↔ Discord, the same way the Windows app does it (guild_relay.py): the members' apps
// meet on a channel at two free public message brokers, named and encrypted from the guild code.
// Each shares the guild lines it reads; all of them match the readings up alike and the member
// with the lowest id posts each message to the guild's Discord webhook. The shared bot keeps the
// guild's details on the channel and passes the Discord channel's messages along.
import { ratio } from "./reader.js";

const MQTT = "https://cdn.jsdelivr.net/npm/mqtt@5.10.1/dist/mqtt.min.js";
const BROKERS = ["wss://broker.emqx.io:8084/mqtt", "wss://broker.hivemq.com:8884/mqtt"];
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const BOT_KEY = "3e9sP7ifaw8Yi7safdCydoBAuGHuqjlRx_7Tmm748s4";  // the shared bot's public key: it signs /chatlink logins
const HOLD = 3000, KEEP = 900000, SAME_TEXT = 88, SAME_NAME = 80;
const WEBHOOK = /^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/(\d{5,25})\/([\w-]{20,120})$/;
const enc = new TextEncoder(), dec = new TextDecoder();

// "abcd efgh jklm", "ABCD-EFGH-JKLM"… as ABCD-EFGH-JKLM; "" when it isn't a guild code
export function guildCode(text) {
  const t = (text || "").toUpperCase().replace(/[\s-]/g, "");
  return /^[A-Z2-9]{12}$/.test(t) && [...t].every(c => ALPHABET.includes(c)) ? `${t.slice(0, 4)}-${t.slice(4, 8)}-${t.slice(8)}` : "";
}

export function readerId() {
  return "web-" + [...crypto.getRandomValues(new Uint8Array(8))].map(b => b.toString(16).padStart(2, "0")).join("");
}

// plain text for Discord: no pings
export function clean(text) {
  return String(text).replace(/@(everyone|here)/g, "@​$1").replace(/<(@[!&]?|#)(\d+)>/g, "<$1​$2>")
    .replace(/\s+/g, " ").trim().slice(0, 1900);
}

// the name a typed message goes under: the character's, with the Discord name when it isn't the same person
export function who(game, discord) {
  game = clean(game || "").slice(0, 20); discord = clean(discord || "").slice(0, 32);
  if (!game || !discord) return game || discord || "?";
  const g = game.toLowerCase(), d = discord.toLowerCase();
  return g.includes(d) || d.includes(g) ? game : `${game} - @${discord}`;
}

const webhookName = n => n.replace(/@/g, "＠").replace(/#/g, "＃").replace(/discord/gi, m => m.replace(/o/g, "ο").replace(/O/g, "Ο")).slice(0, 80);

// ---------------------------------------------------------------- the guild's key, from its code

async function sealFor(code) {
  const base = await crypto.subtle.importKey("raw", enc.encode(code.replace(/-/g, "")), "PBKDF2", false, ["deriveBits"]);
  const raw = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: enc.encode("customclassic-chat guild"), iterations: 200000, hash: "SHA-256" }, base, 256));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array([...enc.encode("topic:"), ...raw])));
  const topic = "ccchat/" + [...digest].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
  const key = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
  const aad = enc.encode(topic);
  return {
    topic,
    async seal(data) {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad }, key, enc.encode(JSON.stringify(data))));
      const out = new Uint8Array(12 + ct.length); out.set(iv); out.set(ct, 12);
      return out;
    },
    async open(blob) {
      try {
        const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(0, 12), additionalData: aad }, key, blob.slice(12));
        return JSON.parse(dec.decode(pt));
      } catch { return null; }  // not this guild's: someone else's, or junk
    },
  };
}

// ---------------------------------------------------------------- logins from the bot (/chatlink)

const b64 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(-s.length & 3)), c => c.charCodeAt(0));

// the login out of what was pasted: the /chatlink link, or the token itself
export function loginFrom(text) {
  const m = /[?#&](?:t|login)=([\w-]+\.[\w-]+)/.exec(text || "") || /^([\w-]+\.[\w-]+)$/.exec((text || "").trim());
  return m ? m[1] : "";
}

// the claims of a login the bot signed and that hasn't run out; null for anything else
export async function checkLogin(token) {
  if (!token || token.split(".").length !== 2) return null;
  const [body, sig] = token.split(".");
  let claims;
  try { claims = JSON.parse(dec.decode(b64(body))); } catch { return null; }
  if (!claims || Date.now() / 1000 > Number(claims.exp || 0)) return null;
  try {
    const key = await crypto.subtle.importKey("raw", b64(BOT_KEY), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, b64(sig), enc.encode(body)) ? claims : null;
  } catch {
    return { ...claims, unchecked: true };  // this browser can't check the signature
  }
}

// ---------------------------------------------------------------- matching every member's readings

const slips = t => { t = t.toLowerCase(); return (t.match(/rn|vv|cl/g) || []).length + (t.match(/[a-z][01][a-z]/g) || []).length; };

class Pending {
  constructor(stamp, speaker, kind, first) { Object.assign(this, { stamp, speaker, kind, first }); this.versions = new Map(); this.readers = new Set(); }
  best() {  // what most saw; among equals, fewer misreadings, then the longest
    return [...this.versions].sort((a, b) => b[1] - a[1] || slips(a[0]) - slips(b[0]) || b[0].length - a[0].length)[0][0];
  }
  poster() { return [...this.readers].sort()[0]; }
  same(stamp, speaker, text, kind) {
    if (this.stamp !== stamp || this.kind !== kind) return false;
    const a = this.speaker.toLowerCase(), b = speaker.toLowerCase();
    if (a !== b && ratio(a, b) < SAME_NAME) return false;
    const best = [...this.versions].sort((x, y) => y[1] - x[1])[0][0];
    return text === best || ratio(best.toLowerCase(), text.toLowerCase()) >= SAME_TEXT;
  }
}

class Matcher {
  constructor() { this.pending = []; this.posted = []; }
  add(reader, line, now) {
    const stamp = line.stamp, speaker = String(line.speaker).trim().slice(0, 20), text = clean(line.text), kind = line.kind;
    if (!stamp || !speaker || !text) return false;
    this.posted = this.posted.filter(([, t]) => now - t <= KEEP);
    if (this.posted.some(([p]) => p.same(stamp, speaker, text, kind))) return false;
    let hit = this.pending.find(p => p.same(stamp, speaker, text, kind));
    if (!hit) { hit = new Pending(stamp, speaker, kind, now); this.pending.push(hit); }
    if (!hit.readers.has(reader)) { hit.readers.add(reader); hit.versions.set(text, (hit.versions.get(text) || 0) + 1); }
    return true;
  }
  due(now) {
    const ready = this.pending.filter(p => now - p.first >= HOLD);
    this.pending = this.pending.filter(p => now - p.first < HOLD);
    this.posted.push(...ready.map(p => [p, now]));
    return ready;
  }
}

// ---------------------------------------------------------------- this browser among the guild's apps

let mqttLoaded = null;
const loadMqtt = () => mqttLoaded ||= new Promise((ok, fail) => {
  const s = document.createElement("script"); s.src = MQTT; s.onload = ok; s.onerror = fail; document.head.appendChild(s);
});

export class GuildPeer {
  // put(msg) gets messages for the Guild tab; status(text) what to say about the relay
  constructor({ code, reader, share, tab, put, status, cfg }) {
    Object.assign(this, { code, reader, share, tab, put, status });
    this.cfg = cfg || {};
    this.matcher = new Matcher();
    this.seen = [];
    this.peers = new Map();
    this.gameName = ""; this.login = "";
    this.shared = this.posted = 0;
    this.clients = [];
    this.ready = this.start();
  }

  async start() {
    await loadMqtt();
    this.box = await sealFor(this.code);
    for (const url of BROKERS) {
      const c = mqtt.connect(url, { clientId: "cc-" + crypto.randomUUID().replace(/-/g, "").slice(0, 16), reconnectPeriod: 5000, connectTimeout: 10000 });
      c.on("connect", () => { c.subscribe(this.box.topic + "/#", { qos: 1 }); this.connected(); });
      c.on("message", (_t, payload) => this.heard(new Uint8Array(payload)));
      this.clients.push(c);
    }
    this.timer = setInterval(() => this.tick(), 500);
    this.lastHi = 0;
  }

  connected() { this.status(this.cfg.name ? `Guild: ${this.cfg.name}` : "Guild: connected, waiting for the guild's details…"); }

  async say(data, retain = false, sub = "chat") {
    const id = crypto.randomUUID().replace(/-/g, "");
    this.remember(id);
    const blob = await this.box.seal({ ...data, id, from: this.reader });
    for (const c of this.clients) if (c.connected) c.publish(`${this.box.topic}/${sub}`, blob, { qos: 1, retain });
  }

  remember(id) { this.seen.push(id); if (this.seen.length > 500) this.seen.shift(); }

  async heard(blob) {
    const msg = await this.box.open(blob);
    if (!msg || this.seen.includes(msg.id)) return;
    this.remember(msg.id);
    const now = Date.now(), t = msg.t;
    if (t === "read" && msg.line && typeof msg.line === "object") {
      const l = msg.line;
      if (l.kind === "guild" && ["stamp", "speaker", "text"].every(k => typeof l[k] === "string")) this.matcher.add(String(msg.from), l, now);
    } else if (t === "cfg") {
      const cfg = msg.cfg || {};
      if (cfg.closed) { this.cfg = { closed: true }; this.status("Guild: the guild's admins have closed it."); }
      else if (WEBHOOK.test(String(cfg.webhook || ""))) {
        this.cfg = Object.fromEntries(["name", "webhook", "webhook_id", "channel_id", "server_id"].map(k => [k, String(cfg[k] || "").slice(0, 250)]));
        this.status(`Guild: ${this.cfg.name || "joined"}`);
        this.onCfg?.(this.cfg);
      }
    } else if (t === "hi") {
      this.peers.set(String(msg.from), { at: now, share: !!msg.share, tab: !!msg.tab });
    } else if (t === "say" && this.tab) {
      const login = String(msg.login || ""), claims = login ? await checkLogin(login) : null;
      const server = this.cfg.server_id, game = String(msg.game || "");
      const ok = claims && !claims.unchecked && (!server || String(claims.server) === server);
      const name = ok ? who(game, claims.name) + " ✓" : login ? who(game, String(msg.name || "?")) + (claims?.unchecked ? "" : " (unverified)") : clean(game).slice(0, 20) || "?";
      this.put({ kind: "guildsay", name, body: clean(msg.text || ""), at: now });
    } else if (t === "discord" && this.tab) {
      this.put({ kind: "discord", name: String(msg.author || "?").slice(0, 32), body: clean(msg.text || ""), at: now });
    }
  }

  // a guild line this browser read: shared, if sharing is on
  send(msg) {
    if (!this.share || this.cfg.closed || msg.kind !== "guild" || !msg.stamp || !msg.name || !msg.body) return;
    const line = { stamp: msg.stamp, speaker: msg.name.slice(0, 20), text: msg.body.slice(0, 300), kind: "guild" };
    if (this.matcher.add(this.reader, line, Date.now())) { this.shared++; this.say({ t: "read", line }); }
  }

  // typed in the Guild tab: to every member's Guild tab and the Discord channel; "" or why not
  async sayChat(text) {
    const claims = this.login ? await checkLogin(this.login) : null;
    if (!claims && !this.gameName) return "Put your character's name in Settings first.";
    text = clean(text).slice(0, 400);
    if (!text) return "";
    const say = { t: "say", text, game: this.gameName };
    if (claims) Object.assign(say, { login: this.login, name: claims.name });
    await this.say(say);
    const name = claims ? who(this.gameName, claims.name) : this.gameName;
    this.put({ kind: "guildsay", name: name + (claims && !claims.unchecked ? " ✓" : ""), body: text, at: Date.now() });
    if (this.cfg.webhook) this.post(webhookName(name), text).catch(() => this.status("Guild: Discord refused the message."));
    return "";
  }

  async post(username, content) {
    const r = await fetch(this.cfg.webhook, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.slice(0, 80), content, allowed_mentions: { parse: [] } }) });
    if (!r.ok) throw new Error(`Discord said ${r.status}`);
  }

  async tick() {
    const now = Date.now();
    for (const p of this.matcher.due(now)) {
      if (p.poster() !== this.reader || !this.cfg.webhook) continue;
      try { await this.post(`${p.speaker} · ${p.kind}`, p.best()); this.posted++; }
      catch (e) { this.status("Guild: " + e.message); }
    }
    if (now - this.lastHi > 30000) { this.lastHi = now; this.say({ t: "hi", share: this.share, tab: this.tab }); }
  }

  members() {
    const now = Date.now();
    return 1 + [...this.peers].filter(([r, p]) => r !== this.reader && now - p.at < 90000).length;
  }

  stop() {
    clearInterval(this.timer);
    for (const c of this.clients) try { c.end(true); } catch {}
  }
}
