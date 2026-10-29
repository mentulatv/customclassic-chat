// Reading the game's chat from pictures of a shared window, in the browser: the chat's rows cut by
// its line spacing, each recognised on its own (PP-OCR's recogniser, no text finder needed), then
// told apart by their colours and cleaned of spacer padding. The same rules as the desktop app.

const ORT = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/";
let session = null, chars = null;
export let engine = "";  // what reads: the graphics card (webgpu) or the processor (wasm)

export async function loadModel(base = "models/") {
  if (session) return;
  await new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = ORT + "ort.webgpu.min.js"; s.onload = ok; s.onerror = fail;
    document.head.appendChild(s);
  });
  ort.env.wasm.wasmPaths = ORT;
  // threads need a cross-origin isolated page (the server's COOP/COEP headers); one otherwise
  ort.env.wasm.numThreads = crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 2) : 1;
  const [model, list] = await Promise.all([
    fetch(base + "rec.onnx").then(r => r.arrayBuffer()),
    fetch(base + "chars.txt").then(r => r.text()),
  ]);
  chars = ["", ...list.split(/\r?\n/), " "];  // 0 is CTC's blank
  if ("gpu" in navigator) {
    try {
      session = await ort.InferenceSession.create(model, { executionProviders: ["webgpu"] });
      engine = "webgpu";
      return;
    } catch { /* no usable graphics card: the processor it is */ }
  }
  session = await ort.InferenceSession.create(model, { executionProviders: ["wasm"] });
  engine = `wasm ×${ort.env.wasm.numThreads}`;
}

// ---------------------------------------------------------------- rows

function edgeProfile(img) {
  // per row: how many sharp brightness steps along it (text has many)
  const { data, width, height } = img, out = new Float32Array(height);
  for (let y = 0; y < height; y++) {
    let n = 0, prev = -1;
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4, l = (data[i] + data[i + 1] + data[i + 2]) / 3;
      if (prev >= 0 && Math.abs(l - prev) > 60) n++;
      prev = l;
    }
    out[y] = n;
  }
  return out;
}

// The rows: the line spacing from how the profile repeats, the first row where the gaps line up.
export function rowsOf(img) {
  const raw = edgeProfile(img), h = raw.length;
  const mean = raw.reduce((a, b) => a + b, 0) / h;
  const prof = raw.map(v => v - mean);
  let pitch = 16, best = -Infinity;
  for (let p = 12; p <= 30 && p < h / 2; p++) {
    let s = 0;
    for (let y = 0; y + p < h; y++) s += prof[y] * prof[y + p];
    s /= h - p;
    if (s > best) { best = s; pitch = p; }
  }
  let phase = 0, low = Infinity;
  for (let o = 0; o < pitch; o++) {
    let s = 0;
    for (let y = o; y < h; y += pitch) s += raw[Math.round(y)];
    if (s < low) { low = s; phase = o; }
  }
  const rows = [];
  for (let y = phase; y + pitch * 0.6 < h; y += pitch) {
    const a = Math.round(y), b = Math.min(h, Math.round(y + pitch));
    let ink = 0;
    for (let k = a; k < b; k++) ink += raw[k];
    if (ink > 20) rows.push([Math.max(0, a - 1), Math.min(h, b + 1)]);
  }
  return { rows, pitch };
}

// ---------------------------------------------------------------- finding the chat box

// The game's chat in a picture of its window, found by its scrollbar: the left edge of the track
// is one unbroken run of neutral grey from the top arrow down to the bottom one, with the blue
// arrow buttons beside it at both ends (game scenery is practically never like that). That gives
// the top, bottom and right of the chat's lines; the left is where the rows' time stamps start.
// {x, y, w, h} in the picture's pixels, or null.
export function findChat(img) {
  const { data, width, height } = img;
  const at = (x, y) => (y * width + x) * 4;
  const grey = (x, y) => {
    const i = at(x, y), r = data[i], g = data[i + 1], b = data[i + 2];
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    return mx - mn <= 6 && mn >= 185 && mx <= 240;
  };
  const blue = (x, y) => { const i = at(x, y); return data[i + 2] - data[i] >= 60; };
  let best = null;
  for (let x = Math.floor(width * 0.1); x < width - 14; x++) {
    let y = Math.floor(height * 0.25);
    while (y < height) {
      if (!grey(x, y)) { y++; continue; }
      const top = y;
      while (y < height && (grey(x, y) || blue(x, y))) y++;
      const bottom = y - 1, len = bottom - top;
      if (len >= 40 && (!best || len > best.len)) {
        const besideBlue = (y0, y1) => {
          for (let yy = Math.max(0, y0); yy <= Math.min(height - 1, y1); yy++)
            for (let xx = x + 1; xx <= x + 12; xx++) if (blue(xx, yy)) return true;
          return false;
        };
        if (besideBlue(top, top + 22) && besideBlue(bottom - 22, bottom)) best = { x, top, bottom, len };
      }
    }
  }
  if (!best) return null;
  const pad = 2, top = best.top - pad, bottom = best.bottom + pad, right = best.x - 1;
  // the left: the first column where most rows have text starting (the time stamps)
  const rows = [];
  for (let y = top; y < bottom; y += 4) rows.push(y);
  let left = 0;
  for (let x = Math.max(0, right - 1400); x < right - 100; x++) {
    let hits = 0;
    for (const y of rows) {
      const i = at(x, y), j = at(x + 1, y);
      const l1 = (data[i] + data[i + 1] + data[i + 2]) / 3, l2 = (data[j] + data[j + 1] + data[j + 2]) / 3;
      if (Math.abs(l1 - l2) > 60) hits++;
    }
    if (hits >= rows.length * 0.5) { left = x; break; }  // stamps: ~65% of rows; the scene beside: under 30%
  }
  left = Math.max(0, left - 3);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

// ---------------------------------------------------------------- recognising a row

const scratch = document.createElement("canvas");

export async function recognise(source, x, y, w, h) {
  const nw = Math.max(8, Math.ceil(48 * w / h));
  scratch.width = nw; scratch.height = 48;
  const ctx = scratch.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, x, y, w, h, 0, 0, nw, 48);
  const px = ctx.getImageData(0, 0, nw, 48).data, n = nw * 48;
  const input = new Float32Array(3 * n);
  for (let i = 0; i < n; i++) {  // BGR, scaled to -1..1, channels first
    input[i] = px[i * 4 + 2] / 127.5 - 1;
    input[n + i] = px[i * 4 + 1] / 127.5 - 1;
    input[2 * n + i] = px[i * 4] / 127.5 - 1;
  }
  const out = await session.run({ x: new ort.Tensor("float32", input, [1, 3, 48, nw]) });
  const t = Object.values(out)[0], [, steps, classes] = t.dims, d = t.data;
  let text = "", prev = 0;
  for (let s = 0; s < steps; s++) {
    let arg = 0, max = -Infinity;
    for (let c = 0, o = s * classes; c < classes; c++) if (d[o + c] > max) { max = d[o + c]; arg = c; }
    if (arg !== prev && arg !== 0) text += chars[arg] || "";
    prev = arg;
  }
  return text.trim();
}

// ---------------------------------------------------------------- colours

// the text colour of each chat type, and the band behind megaphones (as measured on Windia)
const TEXT = {
  mega: [[9, 69, 76], [70, 39, 6], [119, 0, 66]],
  buddy: [[255, 153, 0]], whisper: [[0, 255, 0]], system: [[255, 175, 175], [255, 255, 0]],
  map: [[255, 255, 255]],
};
const BANDS = { mega: [[83, 208, 190], [224, 173, 1], [206, 155, 177]], notice: [[151, 66, 57]] };
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
function nearest(rgb, table, limit = 45) {
  let best = null, d = limit;
  for (const [name, list] of Object.entries(table)) for (const c of list) {
    const e = dist(rgb, c);
    if (e < d) { d = e; best = name; }
  }
  return best;
}

// (text colour, background colour, a solid band behind it): from the start of the row, its middle
export function rowColours(img, a, b) {
  const h = b - a, { data, width } = img, right = Math.min(width, 8 * h), px = [];
  for (let y = a + Math.floor(h / 4); y < b - Math.floor(h / 4); y++)
    for (let x = 0; x < right; x++) { const i = (y * width + x) * 4; px.push([data[i], data[i + 1], data[i + 2]]); }
  if (!px.length) return {};
  const med = k => { const v = px.map(p => p[k]).sort((p, q) => p - q); return v[v.length >> 1]; };
  const bg = [med(0), med(1), med(2)];
  const far = px.map(p => [p, Math.abs(p[0] - bg[0]) + Math.abs(p[1] - bg[1]) + Math.abs(p[2] - bg[2])]);
  const band = far.filter(([, d]) => d < 40).length / far.length >= 0.45;
  const top = Math.max(...far.map(([, d]) => d));
  if (top < 60) return { bg, band };
  const counts = new Map();
  for (const [p, d] of far) if (d >= Math.max(60, top * 0.5)) {
    const k = p.map(v => v / 24 | 0).join(",");
    counts.set(k, (counts.get(k) || []).concat([p]));
  }
  const group = [...counts.values()].sort((p, q) => q.length - p.length)[0];
  const text = [0, 1, 2].map(k => { const v = group.map(p => p[k]).sort((p, q) => p - q); return v[v.length >> 1]; });
  return { text, bg, band };
}

export function kindOf(line) {
  if (/^\W{0,3}(?:\[\s?\d{1,2}\s?[:.;]\s?\d{2}\s?\]\s*)?[A-Za-z0-9]{2,13}\s*(?:<<|>>|«|»)/.test(line.text)) return "whisper";
  if (line.band && line.bg) {
    const b = nearest(line.bg, BANDS);
    if (b === "notice") return null;  // gachapon and crate announcements
    if (b === "mega") return "mega";
  }
  const t = line.text && line.colours.text ? nearest(line.colours.text, TEXT) : null;
  if (t === "system" && /\[notice\]/i.test(line.text.replace(/ /g, ""))) return null;
  return t || (line.band ? "mega" : "other");
}

// ---------------------------------------------------------------- lines into messages

export const STAMP = /^\W{0,3}(?:[\[({]\s?\d{1,2}\s?[:.;]\s?\d{2}|\d{1,2}\s?[:.;]\s?\d{2}\s?[\])}jlI|])/;
const MSG = /^[^\w\[({]{0,3}(?:(?:[\[({]\s?)?(\d{1,2}\s?[:.;]\s?\d{2})\s?[\])}jlI|1]?)?\s*(?:\[[^\]]{1,25}\]\s*)?((?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{2,13})[^:;<>«»]{0,14}?(<<|>>|«|»|[:;])\s?(.*)$/;

export function parse(text) {
  const m = MSG.exec(text.trim());
  if (!m || !m[4].trim()) return null;
  return { stamp: m[1] ? m[1].replace(/\s/g, "").replace(/[.;]/, ":") : null, name: m[2], sep: m[3], body: m[4].trim() };
}

// a wrapped row joins its message: the game wraps by the letter, mid-word
export function joinWrapped(head, tail) {
  const a = head.trimEnd(), b = tail.trimStart();
  if (!a || !b) return a + b;
  return a + (/[.,!?:;)\]]$/.test(a) || /^[(\[]/.test(b) || (/[a-z]$/.test(a) && /^[A-Z]/.test(b)) ? " " : "") + b;
}

// spacer padding (@@@@@@, also read as @QQ@④Q, OOOO, ①) gone; between items, a dot
const PAD_RUN = /[@QqOo0α①-⑳④]{3,}|[@①-⑳④]{2,}|[~=*#$\-_.!]{4,}/g;
export function unpadded(body) {
  let text = body.replace(PAD_RUN, (run, at) => {
    if (/^0+$/.test(run) && at && /\d/.test(body[at - 1])) return run;  // a price's zeros
    if (/^[0Oo]+$/.test(run) && run.length < 6) return run;              // a word, or "1O0k"
    return " · ";
  });
  text = text.replace(/\s*(?:·\s*)+/g, " · ").replace(/^[\s·]+|[\s·]+$/g, "");
  text = text.replace(/ · \S{1,2}$/, "");
  text = text.replace(/^[\s.~=*\-_@]{2,}|[\s#~@*①-⑳]+$/g, "").replace(/^[\s·]+|[\s·]+$/g, "");
  return text || body;
}

// a line seen a moment ago, read a little differently ("CHO1" / "CH01", other spacer junk), isn't new
export class Dedupe {
  constructor(minutes = 20, keep = 150) { this.minutes = minutes; this.keep = keep; this.recent = []; }
  static key(text) {
    return unpadded(text).toLowerCase().replace(/[^a-z0-9]/g, "");
  }
  isNew(text, now = Date.now()) {
    const key = Dedupe.key(text);
    this.recent = this.recent.filter(([t]) => now - t < this.minutes * 60000).slice(-this.keep);
    for (const [, seen] of this.recent) if (key === seen || (key.length > 8 && ratio(key, seen) >= 92)) return false;
    this.recent.push([now, key]);
    return true;
  }
}

// how alike two strings are, 0..100 (like rapidfuzz's ratio)
export function ratio(a, b) {
  if (!a.length && !b.length) return 100;
  const prev = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    let diag = 0;
    for (let j = 1; j <= b.length; j++) {
      const up = prev[j];
      prev[j] = a[i - 1] === b[j - 1] ? diag + 1 : Math.max(prev[j], prev[j - 1]);
      diag = up;
    }
  }
  return 200 * prev[b.length] / (a.length + b.length);
}
