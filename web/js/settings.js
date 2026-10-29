// Settings, kept in this browser and shared by the main page and its chat windows.
const KEY = "ccc.settings";
const DEFAULTS = { fontSize: 14, timestamps: true, region: null, autoFind: true, panes: null,
  twitchChannel: "", twitchInAll: false, guildCode: "", guildShare: true, gameName: "", login: "", readerId: "", guildCfg: null };

export const settings = { ...DEFAULTS, ...read() };

// kept for good: a browser short on space may otherwise clear a site's storage (and the guild code with it)
navigator.storage?.persist?.().catch(() => {});

// the setup (not the chat) as one line, to take to another browser or keep somewhere safe
const PORTABLE = ["fontSize", "timestamps", "panes", "twitchChannel", "twitchInAll", "guildCode", "guildShare", "gameName", "login"];
export function exportSetup() {
  return "ccc1:" + btoa(unescape(encodeURIComponent(JSON.stringify(Object.fromEntries(PORTABLE.map(k => [k, settings[k]]))))));
}
export function importSetup(text) {
  const m = /ccc1:([A-Za-z0-9+/=]+)/.exec(text || "");
  if (!m) return false;
  try {
    const data = JSON.parse(decodeURIComponent(escape(atob(m[1]))));
    saveSettings(Object.fromEntries(PORTABLE.filter(k => k in data).map(k => [k, data[k]])));
    return true;
  } catch { return false; }
}

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}

export function saveSettings(changes) {
  Object.assign(settings, changes);
  try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch {}
}

// another window changed them (the main page's settings, say)
export function onSettings(fn) {
  addEventListener("storage", e => {
    if (e.key !== KEY) return;
    Object.assign(settings, DEFAULTS, read());
    fn(settings);
  });
}
