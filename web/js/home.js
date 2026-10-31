// The main page: open the chat window, the Windows download, and the settings.
import { settings, saveSettings, onSettings, exportSetup, importSetup } from "./settings.js";
import { guildCode, loginFrom, checkLogin } from "./guild.js";
import { channelName } from "./twitch.js";
import { PADDED_KINDS, Catalog, parsePrice, entryLabel } from "./filters.js";

const $ = s => document.querySelector(s);
const KINDS = [["map", "Map chat"], ["whisper", "Whispers"], ["party", "Party"], ["buddy", "Buddy"], ["guild", "Guild"],
  ["mega", "Megaphones"], ["system", "System messages"], ["watch", "Watch list catches"], ["twitch", "Twitch chat"], ["discord", "Discord"]];
const GAME = { map: "#ffffff", whisper: "#00ff00", buddy: "#ff9900", mega: "#f2a7cf", system: "#ffafaf", guild: "#c8b4ff", twitch: "#bf94ff" };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const typing = el => document.activeElement === el;

// the Windows app's latest version, from its GitHub releases (each a version of its own)
fetch("https://api.github.com/repos/mentulatv/customclassic-chat/releases/latest").then(r => r.json()).then(r => {
  if (r.tag_name) $("#download").textContent = `Download for Windows (${r.tag_name})`;
}).catch(() => {});

$("#open").onclick = () => window.open("chat.html", "ccc-chat", "popup,width=620,height=460");

// a /chatlink link opened on this site: …/#login=…
const fromLink = loginFrom(location.hash);
if (fromLink) { saveSettings({ login: fromLink }); history.replaceState(null, "", location.pathname); }

// ---------------------------------------------------------------- showing the settings

function checks(host, items, isOn, onChange) {
  host.innerHTML = "";
  for (const [key, text] of items) {
    const l = document.createElement("label"), c = document.createElement("input");
    c.type = "checkbox"; c.checked = isOn(key); c.onchange = () => onChange(key, c.checked);
    l.append(c, " " + text);
    host.append(l);
  }
}

async function show() {
  $("#timestamps").value = settings.timestamps === true ? "minutes" : settings.timestamps === false ? "off" : settings.timestamps;
  $("#hideSystem").checked = settings.hideSystem;
  checks($("#hidePadded"), PADDED_KINDS, k => settings.hidePadded.includes(k),
    (k, on) => saveSettings({ hidePadded: on ? [...settings.hidePadded, k] : settings.hidePadded.filter(x => x !== k) }));
  if (!typing($("#ignoreNames"))) $("#ignoreNames").value = (settings.ignoreNames || []).join(", ");
  $("#whisperSound").checked = settings.whisperSound !== false;
  $("#keepHours").value = String(settings.keepHours);

  $("#watchList").innerHTML = settings.watch.length ? "" : "<li class='note'>Nothing yet.</li>";
  settings.watch.forEach((e, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="${e.on === false ? "off" : ""}">${esc(entryLabel(e))}</span>`;
    const toggle = document.createElement("button"), del = document.createElement("button");
    toggle.textContent = e.on === false ? "Turn on" : "Turn off"; del.textContent = "Remove";
    toggle.onclick = () => { const w = [...settings.watch]; w[i] = { ...e, on: e.on === false }; saveSettings({ watch: w }); show(); };
    del.onclick = () => { saveSettings({ watch: settings.watch.filter((_, k) => k !== i) }); show(); };
    li.append(toggle, del);
    $("#watchList").append(li);
  });
  $("#watchSound").checked = settings.watchSound !== false;
  $("#watchPopup").checked = settings.watchPopup !== false;
  $("#watchMap").checked = settings.watchMap;

  $("#customOn").checked = settings.custom.on;
  if (!typing($("#customName"))) $("#customName").value = settings.custom.name;
  checks($("#customKinds"), KINDS, k => settings.custom.kinds.includes(k),
    (k, on) => saveSettings({ custom: { ...settings.custom, kinds: on ? [...settings.custom.kinds, k] : settings.custom.kinds.filter(x => x !== k) } }));

  $("#fontSize").value = settings.fontSize; $("#fontSizeOut").textContent = settings.fontSize + " px";
  $("#fontFamily").value = settings.fontFamily;
  $("#bold").checked = settings.bold;
  $("#background").value = settings.background || "#111827";
  $("#colors").innerHTML = "";
  for (const [k, game] of Object.entries(GAME)) {
    const l = document.createElement("label"), c = document.createElement("input");
    c.type = "color"; c.value = settings.colors[k] || game;
    c.onchange = () => saveSettings({ colors: { ...settings.colors, [k]: c.value } });
    l.append(c, " " + KINDS.find(x => x[0] === k)[1]);
    $("#colors").append(l);
  }

  if (!typing($("#guild"))) $("#guild").value = settings.guildCode;
  $("#guildJoin").textContent = settings.guildCode ? "Leave" : "Join";
  $("#guildNote").innerHTML = settings.guildCode
    ? `Joined${settings.guildCfg?.name ? ` <b>${esc(settings.guildCfg.name)}</b>` : ""}: the Guild tab shows its Discord channel.`
    : "Type <b>/guildcode</b> in your guild's Discord channel for the code.";
  $("#guildShare").checked = settings.guildShare !== false;
  if (!typing($("#gameName"))) $("#gameName").value = settings.gameName;
  const claims = settings.login ? await checkLogin(settings.login) : null;
  $("#login").placeholder = claims ? `${claims.name}: added (paste a new link to change it)` : "Paste the link /chatlink gives you (optional)";
  $("#loginNote").textContent = settings.login && !claims ? "That Discord link has run out: /chatlink again." : "";

  if (!typing($("#twitch"))) $("#twitch").value = settings.twitchChannel;
  $("#twitchInAll").checked = settings.twitchInAll;
}

// ---------------------------------------------------------------- changing them

const on = (id, ev, fn) => $(id).addEventListener(ev, fn);
on("#timestamps", "change", e => saveSettings({ timestamps: e.target.value }));
on("#hideSystem", "change", e => saveSettings({ hideSystem: e.target.checked }));
on("#ignoreNames", "change", e => saveSettings({ ignoreNames: e.target.value.split(/[,\s]+/).filter(Boolean).slice(0, 20) }));
on("#whisperSound", "change", e => saveSettings({ whisperSound: e.target.checked }));
on("#keepHours", "change", e => saveSettings({ keepHours: +e.target.value }));
on("#region", "click", () => { saveSettings({ region: null, autoFind: true }); $("#region").textContent = "Done: the chat window looks for it"; });

Catalog.load().then(c => {  // item names, as typed
  on("#watchText", "input", e => {
    $("#itemNames").innerHTML = c.suggest(e.target.value).map(n => `<option value="${esc(n)}">`).join("");
  });
});
on("#watchAdd", "click", () => {
  const text = $("#watchText").value.trim();
  if (!text) return;
  const entry = { text, exact: $("#watchExact").checked, sellers_only: $("#watchSellers").checked,
    min_price: parsePrice($("#watchMin").value), max_price: parsePrice($("#watchMax").value), on: true };
  saveSettings({ watch: [...settings.watch, entry] });
  for (const id of ["#watchText", "#watchMin", "#watchMax"]) $(id).value = "";
  $("#watchExact").checked = $("#watchSellers").checked = false;
  show();
});
on("#watchSound", "change", e => saveSettings({ watchSound: e.target.checked }));
on("#watchPopup", "change", e => saveSettings({ watchPopup: e.target.checked }));
on("#watchMap", "change", e => saveSettings({ watchMap: e.target.checked }));

on("#customOn", "change", e => saveSettings({ custom: { ...settings.custom, on: e.target.checked } }));
on("#customName", "change", e => saveSettings({ custom: { ...settings.custom, name: e.target.value.trim().slice(0, 16) || "Custom" } }));

on("#fontSize", "input", e => { saveSettings({ fontSize: +e.target.value }); $("#fontSizeOut").textContent = e.target.value + " px"; });
on("#fontFamily", "change", e => saveSettings({ fontFamily: e.target.value }));
on("#bold", "change", e => saveSettings({ bold: e.target.checked }));
on("#background", "change", e => saveSettings({ background: e.target.value }));
on("#backgroundReset", "click", () => { saveSettings({ background: "" }); show(); });
on("#colorsReset", "click", () => { saveSettings({ colors: {} }); show(); });

on("#guildJoin", "click", () => {
  if (settings.guildCode) { saveSettings({ guildCode: "", guildCfg: null }); return show(); }
  const code = guildCode($("#guild").value);
  if (!code) { $("#guildNote").textContent = "That isn't a guild code: it looks like ABCD-EFGH-JKLM."; return; }
  saveSettings({ guildCode: code }); show();
});
on("#guildShare", "change", e => saveSettings({ guildShare: e.target.checked }));
on("#gameName", "change", e => saveSettings({ gameName: e.target.value.trim().slice(0, 20) }));
on("#login", "change", async e => {
  const token = loginFrom(e.target.value);
  e.target.value = "";
  if (token && await checkLogin(token)) saveSettings({ login: token });
  else $("#loginNote").textContent = "That isn't a working /chatlink link.";
  show();
});

on("#twitchUse", "click", () => { saveSettings({ twitchChannel: channelName($("#twitch").value) }); show(); });
on("#twitchInAll", "change", e => saveSettings({ twitchInAll: e.target.checked }));

on("#copySetup", "click", async () => {
  const text = exportSetup();
  try { await navigator.clipboard.writeText(text); $("#copySetup").textContent = "Copied"; }
  catch { $("#setup").value = text; $("#setup").select(); }
});
on("#restore", "click", () => { $("#restore").textContent = importSetup($("#setup").value) ? "Restored" : "That isn't a copied setup"; show(); });

onSettings(show);
show();
