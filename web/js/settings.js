// Settings, kept in this browser and shared by the main page and its chat windows.
const KEY = "ccc.settings";
const DEFAULTS = { fontSize: 14, timestamps: true, region: null, autoFind: true, panes: null };

export const settings = { ...DEFAULTS, ...read() };

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
