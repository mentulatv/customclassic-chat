// A Twitch channel's chat, read as a guest ("justinfan" and a number), the way anyone can watch a
// chat without logging in: no account, key or password, and nothing is ever written to it.

// a channel's name out of what was typed: "mentulatv", "#mentulatv" or its twitch.tv link
export function channelName(text) {
  const t = (text || "").trim().toLowerCase().replace(/^https?:\/\/(www\.|m\.)?twitch\.tv\//, "").replace(/^#/, "");
  const m = /^([a-z0-9_]{3,25})(?:[/?#].*)?$/.exec(t);
  return m ? m[1] : "";
}

export function twitchChat(channel, put, status) {
  let ws = null, stopped = false, retry = 2000;
  const open = () => {
    ws = new WebSocket("wss://irc-ws.chat.twitch.tv:443");
    ws.onopen = () => {
      ws.send("CAP REQ :twitch.tv/tags");
      ws.send("PASS SCHMOOPIIE");
      ws.send("NICK justinfan" + (10000 + Math.floor(Math.random() * 89999)));
      ws.send("JOIN #" + channel);
      retry = 2000;
      status(`Twitch: reading #${channel}'s chat.`);
    };
    ws.onmessage = e => {
      for (const line of String(e.data).split("\r\n")) {
        if (!line) continue;
        if (line.startsWith("PING")) { ws.send("PONG" + line.slice(4)); continue; }
        // @tags :user!user@user.tmi.twitch.tv PRIVMSG #channel :text
        const m = /^(?:@(\S+) )?:(\w+)!\S+ PRIVMSG #\w+ :(.*)$/.exec(line);
        if (!m) continue;
        const tags = Object.fromEntries((m[1] || "").split(";").map(kv => kv.split("=")));
        let text = m[3];
        if (text.startsWith("\u0001ACTION ")) text = text.slice(8).replace(/\u0001$/, "");
        put({ kind: "twitch", name: tags["display-name"] || m[2], body: text, fg: tags.color || null, at: Date.now() });
      }
    };
    ws.onclose = () => {
      if (stopped) return;
      status("Twitch: connection lost, trying again…");
      setTimeout(open, retry);
      retry = Math.min(60000, retry * 2);
    };
  };
  open();
  return { stop() { stopped = true; try { ws.close(); } catch {} } };
}
