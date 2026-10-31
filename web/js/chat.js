// A chat window. The main one shares the game's window and reads its chat a few times a second;
// extra windows (chat.html?w=2) show the same chat, each with its own tabs and splits. The chat
// is filtered as the desktop app does it: megaphones to their own tab, spacer padding cleaned,
// lines read twice dropped, and the watch list looking out for what you're after. Everything
// stays in this browser.
import * as R from "./reader.js";
import { settings, saveSettings, onSettings } from "./settings.js";
import { GuildPeer, guildCode } from "./guild.js";
import { twitchChat, channelName } from "./twitch.js";
import * as F from "./filters.js";

const WIN = new URLSearchParams(location.search).get("w") || "main";  // which window this is
const MAIN = WIN === "main";
// the tabs, in this order: the game's chat first, then the guild's, then Twitch
const TABS = {
  All: new Set(["map", "whisper", "party", "buddy", "guild", "other", "system"]),
  Whisper: new Set(["whisper"]), Buddy: new Set(["buddy", "guild"]), Mega: new Set(["mega"]), Map: new Set(["map"]),
  Watch: null, Custom: null,
  Guild: new Set(["guild", "guildsay", "discord"]), Twitch: new Set(["twitch"]),
};
const COLOURS = { map: "#ffffff", whisper: "#00ff00", buddy: "#ff9900", mega: "#f2a7cf", system: "#ffafaf", other: "#c8d2e4",
  guild: "#c8b4ff", guildsay: "#9fe3b8", discord: "#8ea1f0", twitch: "#bf94ff" };
const DEFAULT_PANES = [{ tab: "Mega", grow: 1 }, { tab: "All", grow: 2 }];
const $ = s => document.querySelector(s);

// which messages a tab shows
function shows(tab, m) {
  if (tab === "Watch") return !!m.watch;
  if (tab === "Custom") return (settings.custom?.kinds || []).includes(m.kind) || (m.watch && settings.custom?.kinds?.includes("watch"));
  if (tab === "All" && m.kind === "twitch") return settings.twitchInAll;
  return TABS[tab]?.has(m.kind);
}
// left out by the chat options (kept in the log, so changing them brings them back)
const leftOut = m => (settings.hideSystem && m.kind === "system") || (m.padded && settings.hidePadded?.includes(m.padded));
const tabName = t => t === "Custom" ? settings.custom?.name || "Custom" : t;
const tabsShown = () => Object.keys(TABS).filter(t =>
  (t !== "Guild" || settings.guildCode) && (t !== "Twitch" || settings.twitchChannel) && (t !== "Custom" || settings.custom?.on));

// ---------------------------------------------------------------- the log, shared by every window

let log = loadLog();
function loadLog() {
  try { return JSON.parse(localStorage.getItem("ccc.log") || "[]"); } catch { return []; }
}
function keepLog() {
  const hours = settings.keepHours, since = hours ? Date.now() - hours * 3600000 : 0;
  log = log.filter(m => m.at >= since).slice(-800);
  try { localStorage.setItem("ccc.log", JSON.stringify(log)); } catch {}
}

// what the filter did this session, said at the top so it's plain the chat is being cleaned
const counts = { mega: 0, cleaned: 0, repeats: 0, watch: 0 };
function filterNote() {
  const bits = [`${counts.mega} megaphones to Mega`, `${counts.cleaned} spacer lines cleaned`, `${counts.repeats} repeats dropped`];
  if (counts.watch) bits.push(`${counts.watch} watch-list hits`);
  $("#filter").textContent = "Chat filter on · " + bits.join(" · ");
}

// ---------------------------------------------------------------- the main window: sharing the game

const video = document.createElement("video");
video.muted = true; video.playsInline = true;
const work = document.createElement("canvas"), wctx = work.getContext("2d", { willReadFrequently: true });
const full = document.createElement("canvas"), fctx = full.getContext("2d", { willReadFrequently: true });
let stream = null, busy = false, lastRead = null, found = false, rowsSeen = 0;
const dedupe = new R.Dedupe(), rowCache = new Map();
for (const m of log) dedupe.isNew(m.raw || m.body);

async function share() {
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
  } catch {
    status("Sharing was cancelled. Click Share game window and pick MapleStory's window.");
    return;
  }
  video.srcObject = stream;
  await video.play();
  stream.getVideoTracks()[0].addEventListener("ended", () => { stream = null; showStart(); status("Sharing stopped."); warn(""); });
  showStart();
  status("Looking for the game's chat…");
  const since = Date.now();
  const first = setInterval(() => {  // found by itself, or picked by hand after 10 s
    if (!stream || found || (settings.autoFind === false && settings.region)) clearInterval(first);
    else if (Date.now() - since > 10000) { clearInterval(first); pickRegion(); }
  }, 500);
}

function showStart() {
  $("#share").hidden = !MAIN || !!stream;
  $("#pick").hidden = !MAIN || !stream;
}

// every few seconds: where the game's chat is now (it may have been resized), from its scrollbar
function findChat() {
  if (!stream || settings.autoFind === false || video.readyState < 2) return;
  const vw = video.videoWidth, vh = video.videoHeight;
  if (full.width !== vw || full.height !== vh) { full.width = vw; full.height = vh; }
  fctx.drawImage(video, 0, 0);
  const box = R.findChat(fctx.getImageData(0, 0, vw, vh));
  if (!box) {
    if (found) warn("Can't see the game's chat: it's closed or covered. Open it so it can be read.");
    found = false;
    return;
  }
  const region = { x: box.x / vw, y: box.y / vh, w: box.w / vw, h: box.h / vh };
  const r = settings.region, px = (a, b, n) => Math.abs(a - b) * n > 2;
  if (!r || px(r.x, region.x, vw) || px(r.y, region.y, vh) || px(r.w, region.w, vw) || px(r.h, region.h, vh)) {
    saveSettings({ region });
    lastRead = null;
  }
  if (!found) status("Found the game's chat. Reading…");
  found = true;
}

function pickRegion() {
  if (!stream) return;
  const dlg = $("#picker"), cv = $("#picker canvas"), ctx = cv.getContext("2d");
  const vw = video.videoWidth, vh = video.videoHeight;
  const scale = Math.min(1, (innerWidth - 40) / vw, (innerHeight - 120) / vh);
  cv.width = Math.round(vw * scale); cv.height = Math.round(vh * scale);
  let box = settings.region ? { ...settings.region } : null, from = null;
  const draw = () => {
    ctx.drawImage(video, 0, 0, cv.width, cv.height);
    if (box) {
      ctx.strokeStyle = "#4f80e0"; ctx.lineWidth = 2;
      ctx.strokeRect(box.x * cv.width, box.y * cv.height, box.w * cv.width, box.h * cv.height);
    }
  };
  draw();
  const at = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  cv.onpointerdown = e => { from = at(e); cv.setPointerCapture(e.pointerId); };
  cv.onpointermove = e => {
    if (!from) return;
    const [x, y] = at(e);
    box = { x: Math.min(x, from[0]), y: Math.min(y, from[1]), w: Math.abs(x - from[0]), h: Math.abs(y - from[1]) };
    draw();
  };
  cv.onpointerup = () => { from = null; };
  $("#picker-auto").onclick = () => { saveSettings({ autoFind: true }); findChat(); dlg.close(); };
  $("#picker-ok").onclick = () => {
    if (box && box.w > 0.05 && box.h > 0.02) {
      saveSettings({ region: box, autoFind: false });  // picked by hand: kept, not looked for
      lastRead = null;
      status("Reading the chat…");
    }
    dlg.close();
  };
  $("#picker-again").onclick = draw;
  dlg.showModal();
}

// ---------------------------------------------------------------- reading

function grab() {
  const r = settings.region, vw = video.videoWidth, vh = video.videoHeight;
  const x = Math.round(r.x * vw), y = Math.round(r.y * vh), w = Math.round(r.w * vw), h = Math.round(r.h * vh);
  if (w < 20 || h < 10) return null;
  if (work.width !== w || work.height !== h) { work.width = w; work.height = h; lastRead = null; }
  wctx.drawImage(video, x, y, w, h, 0, 0, w, h);
  return wctx.getImageData(0, 0, w, h);
}

// changed since the last read? A new line moves every line up, which changes many pixels a lot
function changed(a, b) {
  if (!a || a.data.length !== b.data.length) return true;
  let n = 0, total = 0;
  for (let i = 0; i < a.data.length; i += 16) {
    total++;
    if (Math.max(Math.abs(a.data[i] - b.data[i]), Math.abs(a.data[i + 1] - b.data[i + 1]), Math.abs(a.data[i + 2] - b.data[i + 2])) > 60) n++;
  }
  return n / total > 0.01;
}

function rowKey(img, a, b) {  // a row's lettering, to read each row once while it scrolls up
  let k = `${b - a}:`, bits = 0, n = 0;
  for (let y = a; y < b; y++) for (let x = 0; x < img.width; x += 2) {
    const i = (y * img.width + x) * 4;
    bits = (bits << 1) | ((img.data[i] + img.data[i + 1] + img.data[i + 2]) > 520 ? 1 : 0);
    if (++n % 24 === 0) { k += bits.toString(36); bits = 0; }
  }
  return k;
}

async function readOnce() {
  if (!stream || !settings.region || busy || video.readyState < 2) return;
  const img = grab();
  if (!img || !changed(lastRead, img)) return;
  busy = true;
  const t0 = performance.now();
  try {
    const { rows } = R.rowsOf(img);
    rowsSeen = rows.length;
    const lines = [];
    for (const [a, b] of rows) {
      const key = rowKey(img, a, b);
      let text = rowCache.get(key);
      if (text === undefined) {
        text = await R.recognise(work, 0, a, img.width, b - a);
        rowCache.set(key, text);
        if (rowCache.size > 600) rowCache.delete(rowCache.keys().next().value);
      }
      const colours = R.rowColours(img, a, b);
      lines.push({ text, colours, band: colours.band, bg: colours.bg });
    }
    take(merge(lines));
    lastRead = img;
    status(`Reading: ${rows.length} rows, ${Math.round(performance.now() - t0)} ms a read`);
    // a long megaphone takes two lines: under 3 and a couple arriving together scroll away unread
    warn(rows.length && rows.length < 3 && settings.dismissed !== rows.length
      ? `The game's chat shows only ${rows.length} line${rows.length > 1 ? "s" : ""}: make it at least 3 lines tall (4 or more is best).` : "");
  } catch (e) {
    status("Couldn't read the chat for a moment: " + e.message);
  }
  busy = false;
}

// wrapped rows join the message above; a row whose start scrolled away is left out
function merge(lines) {
  const stamped = lines.some(l => R.STAMP.test(l.text)), out = [];
  for (const ln of lines) {
    if (!ln.text) continue;
    if (stamped ? R.STAMP.test(ln.text) : R.parse(ln.text)) { out.push({ ...ln }); continue; }
    const prev = out[out.length - 1];
    if (prev) prev.text = R.joinWrapped(prev.text, ln.text);
  }
  return out;
}

const rgb = c => c ? `rgb(${c.join(",")})` : null;
const ignored = name => (settings.ignoreNames || []).some(n => n && name.toLowerCase().includes(n.toLowerCase()));

function take(lines) {
  let added = 0;
  for (const ln of lines) {
    const kind = R.kindOf(ln);
    if (!kind) continue;
    let p = R.parse(ln.text);
    if (!p && kind === "system") p = { name: "", body: ln.text.replace(R.STAMP, "").trim(), sep: "" };
    if (!p) continue;
    if (!dedupe.isNew(ln.text)) { counts.repeats++; continue; }
    let body = p.body, pad = null;
    if (["map", "mega", "other"].includes(kind)) {
      if (F.padded(body)) { pad = F.paddedKind(body); counts.cleaned++; }
      body = R.unpadded(body);
    }
    // your own characters' name tags behind the chat, read into a line, aren't chat
    for (const n of settings.ignoreNames || []) if (n) body = body.replace(new RegExp(`\\s*\\b${n.replace(/\W/g, "")}\\b\\s*$`, "i"), "");
    const sep = p.sep, whisper = ["<<", ">>", "«", "»"].includes(sep);
    const msg = { kind: whisper ? "whisper" : kind, name: p.name, body, sent: sep === "<<" || sep === "«", at: Date.now(),
      raw: ln.text, stamp: p.stamp, padded: pad,
      fg: kind === "mega" || kind === "system" ? rgb(ln.colours.text) : null, bg: kind === "mega" && ln.band ? rgb(ln.bg) : null };
    if (msg.kind === "mega") counts.mega++;
    checkWatch(msg);
    if (msg.kind === "whisper" && !msg.sent && settings.whisperSound !== false) F.chime(F.WHISPER_NOTES, settings.volume);
    log.push(msg);
    if (msg.kind === "guild") guild?.send(msg);  // guild chat only: shared with the guild, if joined
    added++;
  }
  if (added) { keepLog(); render(); }
  filterNote();
}

// ---------------------------------------------------------------- the watch list

let watcher = null;
async function loadWatcher() {
  const catalog = await F.Catalog.load();
  watcher = new F.Watcher(settings.watch || [], catalog, settings.watchMap ? ["mega", "map"] : ["mega"]);
}
function checkWatch(msg) {
  if (!watcher || leftOut(msg)) return;
  const why = watcher.check(msg);
  if (!why.length) return;
  msg.watch = why.join(", ");
  counts.watch++;
  if (settings.watchSound !== false) F.chime(F.WATCH_NOTES, settings.volume);
  if (settings.watchPopup !== false) note(msg);
}
let noteTimer = 0;
function note(msg) {  // a gold note at the top for 12 s; a click opens the Watch tab
  const el = $("#note");
  el.innerHTML = "";
  const what = document.createElement("b"), line = document.createElement("div");
  what.textContent = "★ " + msg.watch;
  line.textContent = `${msg.name} : ${msg.body}`;
  el.append(what, line);
  el.hidden = false;
  el.onclick = () => { el.hidden = true; const p = panes(); p[0] = { ...p[0], tab: "Watch" }; savePanes(p); render(); };
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => { el.hidden = true; }, 12000);
}

// ---------------------------------------------------------------- Twitch and the guild (the main window's)

let pending = false, draft = "";
function addMsg(msg) {  // a message from Twitch or the guild's channel
  log.push(msg);
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; keepLog(); render(); });
}

let twitch = null, guild = null, extrasKey = "";
function startExtras() {
  if (!MAIN) return;
  const key = JSON.stringify([settings.twitchChannel, settings.guildCode, settings.guildShare, settings.login, settings.gameName]);
  if (key === extrasKey) return;
  extrasKey = key;
  twitch?.stop(); twitch = null;
  const channel = channelName(settings.twitchChannel);
  if (channel) twitch = twitchChat(channel, addMsg, extraStatus);
  const code = guildCode(settings.guildCode);
  if (!code) { guild?.stop(); guild = null; return; }
  if (!guild || guild.code !== code || guild.share !== (settings.guildShare !== false)) {
    guild?.stop();
    if (!settings.readerId) saveSettings({ readerId: "web-" + crypto.randomUUID().replace(/-/g, "").slice(0, 16) });
    guild = new GuildPeer({ code, reader: settings.readerId, share: settings.guildShare !== false, tab: true,
      put: addMsg, status: extraStatus, cfg: settings.guildCfg?.code === code ? settings.guildCfg : null });
    guild.onCfg = cfg => saveSettings({ guildCfg: { ...cfg, code } });
  }
  guild.gameName = settings.gameName || "";
  guild.login = settings.login || "";
}

let extraNote = "";
function extraStatus(text) { extraNote = text; status($("#status").dataset.main || ""); }

// ---------------------------------------------------------------- showing it

const two = n => String(n).padStart(2, "0");
function stampOf(at) {
  const t = new Date(at), fmt = settings.timestamps === false ? "off" : settings.timestamps === true ? "minutes" : settings.timestamps;
  if (fmt === "off") return "";
  return `[${two(t.getHours())}:${two(t.getMinutes())}${fmt === "seconds" ? ":" + two(t.getSeconds()) : ""}] `;
}

function line(m) {
  const d = document.createElement("div");
  d.className = "msg";
  const who = m.kind === "whisper" ? (m.sent ? `To ${m.name}` : `From ${m.name}`) : m.kind === "discord" ? `${m.name} (Discord)` : m.name;
  d.textContent = (m.watch ? "★ " : "") + stampOf(m.at) + (who ? `${who} : ` : "") + m.body;
  d.style.color = settings.colors?.[m.kind] || readable(m.fg) || COLOURS[m.kind] || "#fff";
  if (m.bg) d.style.background = m.bg;
  if (m.watch) d.title = m.watch;
  return d;
}

// a colour light enough to read on the dark background (Twitch names can be any colour, even dark blue)
function readable(c) {
  const m = /^#([0-9a-f]{6})$/i.exec(c || "");
  if (!m) return c;
  let [r, g, b] = [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16));
  const l = 0.299 * r + 0.587 * g + 0.114 * b;
  if (l >= 110) return c;
  const k = (110 - l) / (255 - l);  // mixed towards white
  [r, g, b] = [r, g, b].map(v => Math.round(v + (255 - v) * k));
  return `rgb(${r},${g},${b})`;
}

// this window's panes: the main window's, or an extra window's own
const panes = () => (MAIN ? settings.panes : settings.windows?.[WIN]?.panes)?.length
  ? structuredClone(MAIN ? settings.panes : settings.windows[WIN].panes) : structuredClone(MAIN ? DEFAULT_PANES : [{ tab: "All", grow: 1 }]);
function savePanes(p) {
  if (MAIN) saveSettings({ panes: p });
  else saveSettings({ windows: { ...(settings.windows || {}), [WIN]: { panes: p } } });
}

function look() {
  const s = document.documentElement.style;
  s.setProperty("--text", settings.fontSize + "px");
  s.setProperty("--chat-font", settings.fontFamily ? `"${settings.fontFamily}", sans-serif` : "inherit");
  s.setProperty("--chat-weight", settings.bold ? "700" : "400");
  s.setProperty("--chat-bg", settings.background || "#111827");
}

function render() {
  look();
  const host = $("#panes"), list = panes();
  const stuck = [...host.querySelectorAll(".list")].map(l => l.scrollTop + l.clientHeight >= l.scrollHeight - 4);
  const typing = document.activeElement?.classList.contains("say");  // (kept typing through a redraw)
  host.innerHTML = "";
  list.forEach((pane, i) => {
    if (i) {
      const div = document.createElement("div");
      div.className = "divider";
      div.onpointerdown = e => dragDivider(e, i);
      host.appendChild(div);
    }
    const el = document.createElement("section");
    el.className = "pane"; el.style.flexGrow = pane.grow || 1;
    const bar = document.createElement("nav");
    for (const name of tabsShown()) {
      const b = document.createElement("button");
      b.textContent = tabName(name); b.className = name === pane.tab ? "on" : "";
      b.onclick = () => { list[i] = { ...pane, tab: name }; savePanes(list); render(); };
      bar.appendChild(b);
    }
    if (list.length > 1) {
      const x = document.createElement("button");
      x.textContent = "✕"; x.title = "Remove this split"; x.className = "close";
      x.onclick = () => { list.splice(i, 1); savePanes(list); render(); };
      bar.appendChild(x);
    }
    const msgs = document.createElement("div");
    msgs.className = "list";
    for (const m of log.filter(m => shows(pane.tab, m) && !leftOut(m)).slice(-200)) msgs.appendChild(line(m));
    el.append(bar, msgs);
    if (pane.tab === "Guild" && settings.guildCode) {  // typing to the guild: its Discord channel and every member's Guild tab
      const input = document.createElement("input");
      input.className = "say";
      input.placeholder = !MAIN ? "Type in the main chat window" : settings.gameName || settings.login
        ? "Type to the guild, Enter to send" : "Put your character's name in Settings to type here";
      input.disabled = !MAIN;
      input.value = draft;
      input.oninput = () => { draft = input.value; };
      input.onkeydown = async e => {
        if (e.key !== "Enter" || !input.value.trim() || !guild) return;
        const why = await guild.sayChat(input.value);
        if (why) extraStatus(why); else { input.value = draft = ""; }
      };
      el.append(input);
    }
    host.appendChild(el);
  });
  // to the newest, once every pane is in (a pane alone is taller, and its scroll would be cut short)
  host.querySelectorAll(".list").forEach((l, i) => { if (stuck[i] !== false) l.scrollTop = l.scrollHeight; });
  const say = host.querySelector(".say");
  if (typing && say) { say.focus(); say.setSelectionRange(draft.length, draft.length); }
}

function dragDivider(e, i) {
  const list = panes(), els = [...document.querySelectorAll(".pane")], a = els[i - 1], b = els[i];
  const ha = a.offsetHeight, hb = b.offsetHeight, y0 = e.clientY;
  const move = ev => {
    const d = Math.max(-ha + 40, Math.min(hb - 40, ev.clientY - y0));
    a.style.flexGrow = ha + d; b.style.flexGrow = hb - d;
  };
  const up = () => {
    removeEventListener("pointermove", move); removeEventListener("pointerup", up);
    els.forEach((el, k) => { list[k] = { ...list[k], grow: el.offsetHeight }; });
    savePanes(list);
  };
  addEventListener("pointermove", move); addEventListener("pointerup", up);
}

function split() {
  const list = panes();
  if (list.length >= 5) return;
  list.unshift({ tab: "Whisper", grow: 1 });
  savePanes(list);
  render();
}

function newWindow() {  // another chat window: the same chat, its own tabs and splits
  const n = Math.max(1, ...Object.keys(settings.windows || {}).map(Number).filter(Boolean)) + 1;
  window.open(`chat.html?w=${n}`, `ccc-chat-${n}`, "popup,width=520,height=380");
}

function status(text) {
  $("#status").dataset.main = text;
  $("#status").textContent = text + (extraNote ? "  ·  " + extraNote : "");
}
function warn(text) {
  const el = $("#warn");
  el.hidden = !text; el.textContent = text ? "⚠ " + text : "";
  el.onclick = () => { el.hidden = true; saveSettings({ dismissed: rowsSeen }); };
}

// ---------------------------------------------------------------- start

$("#share").onclick = share;
$("#pick").onclick = pickRegion;
$("#split").onclick = split;
$("#window").onclick = newWindow;
$("#clear").onclick = () => { log = []; keepLog(); render(); };
addEventListener("storage", e => {  // another window's messages (an extra window shows the main one's)
  if (e.key === "ccc.log" && !MAIN) { log = loadLog(); render(); }
});
onSettings(() => { startExtras(); loadWatcher(); render(); });
document.title = MAIN ? "CustomClassic Chat" : `CustomClassic Chat (${WIN})`;
showStart();
startExtras();
loadWatcher();
render();
filterNote();
if (MAIN) {
  status("Loading text recognition…");
  R.loadModel().then(() => {
    status("Ready. Click Share game window and pick MapleStory's window.");
    setInterval(readOnce, 250);
    setInterval(findChat, 3000);
    setTimeout(findChat, 800);
  }).catch(e => status("Couldn't load text recognition: " + e.message));
} else {
  status("An extra window: it shows what the main chat window reads.");
  $("#filter").hidden = true;
}
