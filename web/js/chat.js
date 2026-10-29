// The chat window: shares the game's window, reads its chat a few times a second, and shows it
// in tabs, split into panes. Everything stays in this browser.
import * as R from "./reader.js";
import { settings, saveSettings, onSettings } from "./settings.js";

const TABS = {
  All: new Set(["map", "whisper", "party", "buddy", "other", "system"]),
  Whisper: new Set(["whisper"]), Buddy: new Set(["buddy"]), Mega: new Set(["mega"]), Map: new Set(["map"]),
};
const COLOURS = { map: "#ffffff", whisper: "#00ff00", buddy: "#ff9900", mega: "#f2a7cf", system: "#ffafaf", other: "#c8d2e4" };
const $ = s => document.querySelector(s);
const video = document.createElement("video");
video.muted = true; video.playsInline = true;
const work = document.createElement("canvas");
const wctx = work.getContext("2d", { willReadFrequently: true });
let stream = null, busy = false, lastRead = null, readMs = 0;
const dedupe = new R.Dedupe(), rowCache = new Map();
let log = loadLog();
for (const m of log) dedupe.isNew(m.raw || m.body);

// ---------------------------------------------------------------- the log

function loadLog() {
  try { return JSON.parse(localStorage.getItem("ccc.log") || "[]"); } catch { return []; }
}
function keepLog() {
  log = log.slice(-500);
  try { localStorage.setItem("ccc.log", JSON.stringify(log)); } catch {}
}

// ---------------------------------------------------------------- sharing the game

async function share() {
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
  } catch {
    status("Sharing was cancelled. Click Share game window and pick MapleStory's window.");
    return;
  }
  video.srcObject = stream;
  await video.play();
  stream.getVideoTracks()[0].addEventListener("ended", () => { stream = null; showStart(); status("Sharing stopped."); });
  showStart();
  status("Looking for the game's chat…");
  const since = Date.now();
  const first = setInterval(() => {  // found by itself, or picked by hand after 10 s
    if (!stream || found || (settings.autoFind === false && settings.region)) clearInterval(first);
    else if (Date.now() - since > 10000) { clearInterval(first); pickRegion(); }
  }, 500);
}

// ---------------------------------------------------------------- the chat box, found by itself

const full = document.createElement("canvas");
const fctx = full.getContext("2d", { willReadFrequently: true });
let found = false;

// every few seconds: where the game's chat is now (it may have been resized), from its scrollbar
function findChat() {
  if (!stream || settings.autoFind === false || video.readyState < 2) return;
  const vw = video.videoWidth, vh = video.videoHeight;
  if (full.width !== vw || full.height !== vh) { full.width = vw; full.height = vh; }
  fctx.drawImage(video, 0, 0);
  const box = R.findChat(fctx.getImageData(0, 0, vw, vh));
  if (!box) {
    if (found) status("Can't see the game's chat: is it open, and not covered?");
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

function showStart() {
  $("#share").hidden = !!stream;
  $("#pick").hidden = !stream;
}

// ---------------------------------------------------------------- the chat box, picked by dragging

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
  $("#picker-auto").onclick = () => {
    saveSettings({ autoFind: true });
    findChat();
    dlg.close();
  };
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
    if (Math.max(Math.abs(a.data[i] - b.data[i]), Math.abs(a.data[i + 1] - b.data[i + 1]),
      Math.abs(a.data[i + 2] - b.data[i + 2])) > 60) n++;
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
    readMs = performance.now() - t0;
    status(`Reading: ${rows.length} rows, ${Math.round(readMs)} ms a read`);
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

function take(lines) {
  let added = 0;
  for (const ln of lines) {
    const kind = R.kindOf(ln);
    if (!kind) continue;
    let p = R.parse(ln.text);
    if (!p && kind === "system") p = { name: "", body: ln.text.replace(R.STAMP, "").trim(), sep: "" };
    if (!p || !dedupe.isNew(ln.text)) continue;
    const body = ["map", "mega", "other"].includes(kind) ? R.unpadded(p.body) : p.body;
    const msg = { kind: p.sep === "<<" || p.sep === ">>" || p.sep === "«" || p.sep === "»" ? "whisper" : kind,
      name: p.name, body, sent: p.sep === "<<" || p.sep === "«", at: Date.now(), raw: ln.text,
      fg: kind === "mega" || kind === "system" ? rgb(ln.colours.text) : null, bg: kind === "mega" && ln.band ? rgb(ln.bg) : null };
    log.push(msg);
    added++;
  }
  if (added) { keepLog(); render(); }
}
const rgb = c => c ? `rgb(${c.join(",")})` : null;

// ---------------------------------------------------------------- showing it

function line(m) {
  const d = document.createElement("div");
  d.className = "msg";
  const t = new Date(m.at), stamp = settings.timestamps ? `[${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}] ` : "";
  const who = m.kind === "whisper" ? (m.sent ? `To ${m.name}` : `From ${m.name}`) : m.name;
  d.textContent = stamp + (who ? `${who} : ` : "") + m.body;
  d.style.color = m.fg || COLOURS[m.kind] || "#fff";
  if (m.bg) d.style.background = m.bg;
  return d;
}

function render() {
  document.documentElement.style.setProperty("--text", settings.fontSize + "px");
  const host = $("#panes");
  const panes = settings.panes?.length ? settings.panes : [{ tab: "Mega", grow: 1 }, { tab: "All", grow: 2 }];
  // keep each pane's scroll: stuck to the newest unless scrolled up
  const stuck = [...host.querySelectorAll(".list")].map(l => l.scrollTop + l.clientHeight >= l.scrollHeight - 4);
  host.innerHTML = "";
  panes.forEach((pane, i) => {
    if (i) {
      const div = document.createElement("div");
      div.className = "divider";
      div.onpointerdown = e => dragDivider(e, i);
      host.appendChild(div);
    }
    const el = document.createElement("section");
    el.className = "pane"; el.style.flexGrow = pane.grow || 1;
    const bar = document.createElement("nav");
    for (const name of Object.keys(TABS)) {
      const b = document.createElement("button");
      b.textContent = name; b.className = name === pane.tab ? "on" : "";
      b.onclick = () => { panes[i] = { ...pane, tab: name }; saveSettings({ panes }); render(); };
      bar.appendChild(b);
    }
    if (panes.length > 1) {
      const x = document.createElement("button");
      x.textContent = "✕"; x.title = "Remove this split"; x.className = "close";
      x.onclick = () => { panes.splice(i, 1); saveSettings({ panes }); render(); };
      bar.appendChild(x);
    }
    const list = document.createElement("div");
    list.className = "list";
    for (const m of log.filter(m => TABS[pane.tab]?.has(m.kind)).slice(-200)) list.appendChild(line(m));
    el.append(bar, list);
    host.appendChild(el);
    if (stuck[i] !== false) list.scrollTop = list.scrollHeight;
  });
}

function dragDivider(e, i) {
  const panes = settings.panes?.length ? settings.panes : [{ tab: "Mega", grow: 1 }, { tab: "All", grow: 2 }];
  const els = [...document.querySelectorAll(".pane")], a = els[i - 1], b = els[i];
  const ha = a.offsetHeight, hb = b.offsetHeight, y0 = e.clientY;
  const move = ev => {
    const d = Math.max(-ha + 40, Math.min(hb - 40, ev.clientY - y0));
    a.style.flexGrow = ha + d; b.style.flexGrow = hb - d;
  };
  const up = () => {
    removeEventListener("pointermove", move); removeEventListener("pointerup", up);
    els.forEach((el, k) => { panes[k] = { ...panes[k], grow: el.offsetHeight }; });
    saveSettings({ panes });
  };
  addEventListener("pointermove", move); addEventListener("pointerup", up);
}

function split() {
  const panes = settings.panes?.length ? settings.panes : [{ tab: "Mega", grow: 1 }, { tab: "All", grow: 2 }];
  if (panes.length >= 5) return;
  panes.unshift({ tab: "Whisper", grow: 1 });
  saveSettings({ panes });
  render();
}

function status(text) { $("#status").textContent = text; }

// ---------------------------------------------------------------- start

$("#share").onclick = share;
$("#pick").onclick = pickRegion;
$("#split").onclick = split;
$("#clear").onclick = () => { log = []; keepLog(); render(); };
onSettings(render);
showStart();
render();
status("Loading text recognition…");
R.loadModel().then(() => {
  status("Ready. Click Share game window and pick MapleStory's window.");
  setInterval(readOnce, 250);
  setInterval(findChat, 3000);
  setTimeout(findChat, 800);
}).catch(e => status("Couldn't load text recognition: " + e.message));
