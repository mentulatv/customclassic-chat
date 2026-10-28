<img src="docs/logo.png" alt="CustomClassic Chat: a customizable chat and smega blocker" width="460">

# CustomClassic Chat

**A customizable chat and smega blocker for MapleStory Classic World.**

A modern chat panel that sits exactly inside the game's own chat box and keeps the
**megaphones out of your chat**. Map chat, whispers, party and buddy
chat stay readable; megaphones get their own tab instead of flooding everything else.

![CustomClassic Chat over the game's chat box: the All tab with map chat, whispers, buddy and party chat, and dots on Mega and Watch](docs/chat-all.png)

![The Mega tab with megaphones on their coloured bands, and a watch-list catch: a gold note above the chat and a star on the line](docs/chat-mega-watch.png)

<sub>Screenshots use invented players and chat over a blurred game scene.</sub>

- **Tabs** like modern MapleStory: All (everything but megaphones), Whisper, Party, Buddy, Mega
  and Watch, plus **a tab of your own** showing just the chat types you pick. A red dot marks
  a tab with messages you haven't seen.
- **Looks like the game:** megaphones on their pink, teal or gold band, green whispers,
  orange buddy chat, white map chat. Text size, colours, opacity and time stamps are adjustable.
- **Fits the game's chat box by itself** at any resolution or Windows scaling, follows the
  window when it moves or resizes, and follows the chat when you make it taller. It never
  covers the typing bar or the chat-target button, and it steps aside when the game shows
  a party invite or trade request over the chat. It stays up while the game is open, even
  behind other windows, and hides while the game is minimised.
- **Scrolls like the game's chat**, with its own scrollbar lying over the game's.
- **Chat history** is kept between restarts: 12 hours by default, or forever.
- **Watch list:** a chime and a pop-up when a megaphone mentions something you're after
  ("mushmom", "Work Gloves"). It can also check that someone is selling, and that the price
  is within a range you set.
- **Split the chat and add windows:** a second pane on top of the chat with its own tabs
  (Mega above, All below), or extra chat windows anywhere on screen, even outside the game.
- **See-through toggle (◐):** the messages turn 90% see-through and clicks go to the game's
  own chat underneath, until you click ◐ again.
- **Leaves the scenery out:** the game's chat box is see-through, so monster name tags,
  damage numbers and character names behind it are filtered out, not shown as chat.

Windows 10/11 only. The game has to run **windowed** or **borderless**.

> **Disclaimer.** CustomClassic Chat is third-party software, not made or endorsed by Nexon. It
> interacts with the game only in the way considered safe for such tools: it **reads what's
> on screen** with text recognition (OCR), much like a screen recorder or streaming software
> sees the game. It never opens the game's process, never reads or changes game memory or
> files, never touches the game's network traffic, and never sends any input to the game.
> Even so, Nexon's terms don't allow third-party programs, so no tool can promise your
> account is safe: **use it at your own risk.**

---

## Download

**[⬇ CustomClassicChat-win64.zip](https://github.com/mentulatv/customclassic-chat/releases/latest/download/CustomClassicChat-win64.zip)**
(the latest version, about 110 MB; nothing to install)

1. Unzip it anywhere, for example `Documents\CustomClassicChat`.
2. Start the game, then double-click **`CustomClassicChat.exe`**. CustomClassic Chat waits for the game, finds
   its chat box and settles into it. Its blue speech-bubble icon appears in the taskbar's
   notification area (bottom right, maybe behind the **^** arrow).

> Windows may say "Windows protected your PC", because the program isn't code-signed.
> Click **More info → Run anyway**.

Want to look around first? **`CustomClassic Chat demo.bat`** shows made-up messages without reading
anything. To update, unzip a newer version over the old folder: your settings and chat history
(`chat.json`, `chat_history.jsonl`) stay.

**Updates:** CustomClassic Chat asks GitHub at start and twice a day which version is the
latest, and when there's a newer one a note says so ("Your version 1.4.0 · new version 1.5.0")
with **Download**, which opens the release page here. It never downloads or installs anything
by itself. The tray menu's **Check for updates** asks right away; untick **Check for updates**
at the bottom of the settings sidebar to stop it asking.

**Game settings:** any resolution and **UI Size** work; **1280×720 or larger** is recommended,
since smaller windows make the chat text tiny to read. Run the game **windowed**: an overlay
can't draw over a fullscreen game, so in the "(Full Screen)" resolutions the panel may not show.
Change the UI Size or resolution and CustomClassic Chat fits itself again within a few seconds.

### Running from source

Install **Python 3.11 or newer** ([python.org](https://www.python.org/downloads/), tick "Add
python.exe to PATH"), download this repository, double-click **`setup.bat`** once, then
**`start.bat`** (`start.bat --demo` for the demo). `build.bat` makes the .exe and the zip.

## Using it

**The tab row**

| | |
|---|---|
| **≡** (left end) | Drag up or down to make the panel taller or shorter, like the game's chat. |
| Tabs | Click to switch. A red dot means unread messages; a gold dot on Watch means your watch list caught something. |
| **◐** (right end) | See-through: messages 90% see-through and click-through until clicked again. |
| **+** (next to ◐) | Split the chat: a second pane on top with its own tabs (shown while it isn't split). |
| **⚠** (amber) | Only when the game's chat is minimised or shows one or two lines: megaphones arriving together may scroll away unread. Make the game's chat taller, or click ⚠ to hide it. |

**Scrolling:** the arrows (hold to keep going), the track, dragging the thumb, or the mouse
wheel. New messages don't pull you down while you're reading back.

**Tray icon:** left click shows or hides the panel. Right click: Show / hide, Adjust
position, Unlocked (place it anywhere), Reset position, Split the chat, New chat window,
See-through, Settings…, Quit.

**Right-click any chat window** for Split the chat, New chat window, Close this window,
See-through, Adjust position and Settings…. The menu closes when you click elsewhere, move the
pointer well away from it, or after 10 seconds (Settings → Chat details; 0 keeps it open).

**Split the chat:** click **+** at the right end of the tab row (or right-click, the tray menu,
or Settings → Tabs & windows). A second pane appears on
top of the chat, as wide as it and moving with it, with its own row of tabs: Mega to start with,
so megaphones sit above and your chat below. Drag the **divider bar** between the two to give one
more room and the other less; drag the split's ≡ to make the whole thing taller. Click its ✕ to
close it. A tab open in one pane gets no unread dot in the other.

**More chat windows:** tray menu or Settings → Tabs & windows → **Add a chat window**. Each window
has its own tab and ◐, and goes anywhere you drag it: next to the game, on another screen. It
starts in adjust mode; press Ctrl+Alt+F5 to keep it where it is (Ctrl+Alt+F5 later moves all
windows again). Click its ✕ to close it. Windows and splits are remembered between restarts.

**Somewhere else entirely:** tick **Unlocked** (tray menu or Settings → Position) and drag the
panel anywhere, even off the game window or onto another monitor; drag its corner to resize,
then press Ctrl+Alt+F5 to keep it there. It still reads the game's own chat. If it ever ends up
out of reach, **Reset position** (tray menu, Settings, or Ctrl+Alt+F3) puts it back on the
game's chat box, and a panel left on a monitor that's gone comes back to the middle by itself.

**Hotkeys**

| Keys | Action |
|---|---|
| Ctrl+Alt+F5 | Adjust: drag to move, drag any edge or corner to resize, press again to save |
| Ctrl+Alt+F3 | Reset position: back on the game's chat box, fitted again |
| Ctrl+Alt+F6 | Hide / show |
| Ctrl+Alt+F7 | Quit |

## Settings

Right-click the tray icon → **Settings…**. Changes apply right away and are remembered.

<img src="docs/settings-appearance.png" alt="Settings, Appearance: text size, panel opacity, solid text" width="49%"> <img src="docs/settings-chat.png" alt="Settings, Chat: time stamps, what to leave out, character names, whisper chime" width="49%">

<img src="docs/settings-watch-list.png" alt="Settings, Watch list: words and items to look out for, and how to be told" width="49%">

The sidebar comes in three layers, most vital first:

**Basics**, what everyone sets:
- **Appearance:** text size (or match the game's), the panel's opacity, and **Keep the text
  solid** (only the background fades; the text gets a shadow)
- **Position:** on the game's chat, or **unlocked** to go anywhere, and **Reset position**
- **Chat:** time stamps (with seconds, without, or off; from CustomClassic Chat's own clock),
  leaving out the game's system messages and **lines padded with spacers**
  (`S> claw 60 @@@@@@@@@@@@`), your character names (so their name tags behind the chat are left
  out), and the whisper chime
- **Watch list**

**Extras**, features to turn on:
- **Tabs & windows:** a tab of your own (its name, and which of map chat, whispers, party,
  buddy/guild, megaphones, system messages and watch-list catches it shows), splitting the
  chat, and extra chat windows
- **Twitch** and **Guild ↔ Discord** (below)

**Advanced**, finer choices with good defaults:
- **Look:** the font (seven hand-picked: sans serif, serif and monospace) and **bold**, the
  colours of the background and of each chat type, and how see-through ◐ makes the messages
- **Chat details:** how many hours of history to keep (or forever), which kinds of spacer lines
  to leave out (buying and selling, party quests and parties, everything else; left-out lines
  are kept, so unticking brings them back), and when the right-click menu closes
- **Own guild setup** (below)

## Twitch chat (opt-in)

Settings → Twitch → tick **Show Twitch chat**, type the channel's name (or paste its
twitch.tv link) and press **Use**. Its chat shows in a **Twitch** tab, each chatter in their
own name colour, and in All too if you tick **Show it in All too**. The custom tab can show it
as well. CustomClassic Chat reads the chat as a guest, the way anyone can watch a channel's chat
without logging in: no account, key or password, and it never writes in the chat.

## Guild ↔ Discord (opt-in, peer to peer)

Your guild's chat in your guild's Discord channel, and that channel back in a **Guild** tab where
members can type to it, with **no server of anyone's in between** for the chat: the members' own
apps share it with each other.

**[Step-by-step guide, with pictures →](docs/guild-setup.md)**

**Setting up (once, by the server's admins):** *Settings → Guild ↔ Discord → Add the bot to
your server* (choose **Add to Server**), then type `/bind` in the channel for guild
chat. The bot makes the **guild code** (`ABCD-EFGH-JKLM`) and posts and pins it there. Only admins
can `/bind` and `/unbind`. Guilds that would rather not use the shared bot can use *Own guild
setup* (Advanced) with a webhook and, optionally, their own bot.

**Joining:** the pinned post or `/guildcode` in the guild's Discord, then *Settings → Guild ↔
Discord*: enter the code, **Join**, and tick **Share my chat** and/or **Show a Guild tab**.

**Typing in the Guild tab:** `/chatlink` in the guild's Discord gives a link that logs your app in
as your Discord name (signed by the bot, so others see a ✓). Click the line at the bottom of the
Guild tab, type, **Enter**.

**How it works:** the apps meet on a channel at two free public message brokers (MQTT, the kind
smart-home devices use), named and encrypted from the guild code: only members can find or read
it, the brokers just pass sealed messages along, and with two of them one being down doesn't
matter. Every app announces the lines it reads with the game's own time stamp (server time, the
same on every screen). After a few seconds every app has heard everyone's reading of a message,
matches them up the same way (same minute, same speaker, nearly the same text) and agrees on the
best wording (text recognition's slips, like "rn" for "m", lose) and on who posts it: the member
with the lowest id among those who read it. That one app posts it; the others stay quiet. More
members sharing means fewer gaps, never more copies. The bot (or, in an own setup, the admin's
app) keeps the guild's details on the channel for new members and reads the Discord channel for
everyone's Guild tab.

**What is sent:** only the one kind of chat chosen, with the speaker's name and the game's time
stamp: guild chat, or, to try it before the game has guild chat, map chat or whispers (posts say
which). Never anything else, and nothing is ever typed into the game. Ask your guild first.

> The game doesn't have guild chat yet. Until it does, CustomClassic Chat looks for it in old
> MapleStory's guild purple, so it's picked up the day it shows up if the colour stayed the same.
> If it didn't, the real colour (`guild = [r, g, b]` under `[colors]`), measured from one
> screenshot, is the one thing left to set.

## Watch list

Settings… → **Watch list** → **Add…**. Each entry is a word or an item name:

- **A word** ("mushmom", "mano") fires on any megaphone that mentions it. Close spellings
  count, because text recognition sometimes reads "mushmom" as "mushrnom". Tick "This exact
  word only" to turn that off. Words under 5 letters always need the whole word.
- **An item** ("Work Gloves") gets name suggestions as you type, along with the shorthands
  chat uses for it ("wg"). You can then add conditions:
  - someone is **selling** it (S>), not buying
  - it costs **between** two prices you set, each (like `400k` and `1.5m`). Leave one side
    empty for no limit there: just a highest price, or just a lowest (handy to skip "1k"
    joke offers).

A hit plays a three-note chime, pops up a gold note above the chat for 12 seconds (click it
to open the Watch tab), and marks the line with a gold ★. The same entry and the same player
alert at most once every 10 minutes. You can also have it look in map chat, and turn the
chime or pop-up off.

Item names (the game's own) and their shorthands come from the
[Maple Price Index](https://mapleprice.mentula.tv); no prices come with them, the only prices
are the ones you type. CustomClassic Chat downloads the list once an hour and keeps a copy in
`cache/names.json`, so it still works offline.
That download (and, if you opt in, the Twitch chat you chose) is the only thing CustomClassic Chat
fetches. Your game chat never leaves your PC.

## How it works

About once a second, CustomClassic Chat asks Windows for a picture of the game window through
Windows Graphics Capture (the same way OBS's window capture works) and reads the chat lines
with [RapidOCR](https://github.com/RapidAI/RapidOCR). Because it reads the game window itself,
covering the game's chat doesn't stop it from reading. Each line's colours tell the chat types
apart: megaphones sit on a coloured band, whispers are green, and so on.

The chat box is measured in pixels: the line spacing from the text rows, the right edge where
the megaphone bands meet the game's scrollbar, and the bottom from the frame line above the
typing bar. That's why it fits at any resolution or scaling.

The game window is found by its title ("MapleStory"). Only window titles and positions are
asked for; the game's process is never opened.

## Files

| File | |
|---|---|
| `customclassic_chat.py` | the panel, tabs and the reading loop |
| `settings_ui.py` | the settings window |
| `twitch_chat.py` | Twitch chat, read as a guest |
| `guild_relay.py` | guild chat to Discord, peer to peer |
| `reader.py` | text recognition and chat colours |
| `watch.py` | the watch list |
| `trade_parser.py`, `data/` | reads prices in megaphones (from the Maple Price Index) |
| `overlay.py` | the always-on-top overlay window and hotkeys |
| `chat.json` | your settings (made on first run) |
| `chat_history.jsonl` | the kept chat history (stays on your PC) |

Chat colours were measured on the Windia world. If a chat type shows in the wrong tab, copy
`config.example.toml` to `config.toml` and adjust the colours there.

## If something's off

- **Nothing shows up:** the game's chat box needs to show some lines. With the game in front,
  press Ctrl+Alt+F3.
- **It sits slightly wrong, or you can't find it:** tray icon → Reset position (or
  Ctrl+Alt+F3), or adjust it by hand with Ctrl+Alt+F5.
- **A yellow border around the game** (Windows 10): that's Windows showing a window is being
  captured. Windows 11 hides it.
- **Odd words in the chat:** see "Your character names" in Settings. Send a screenshot in an
  issue for anything else.

Try changes without the game: `python customclassic_chat.py --replay screenshot.png` prints which tab
each chat line of a saved screenshot lands in. Tests: `python -m pytest`.

## Roadmap

- **Chatting back on Twitch**: logging in with Twitch to write in its chat from CustomClassic Chat (the guild's Discord already works, from the Guild tab)

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Nexon. MapleStory is a trademark of Nexon.
