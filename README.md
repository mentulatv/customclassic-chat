<img src="docs/logo.png" alt="CustomClassic Chat: a customizable chat and smega blocker" width="460">

# CustomClassic Chat

**A customizable chat and smega blocker for MapleStory Classic World.** It sits inside the game's
chat box and moves megaphones to their own tab, so map chat, whispers, party and buddy chat stay
readable.

![CustomClassic Chat over the game's chat box: the All tab with map chat, whispers, buddy and party chat, and dots on Mega and Watch](docs/chat-all.png)

![The Mega tab with megaphones on their coloured bands, and a watch-list catch: a gold note above the chat and a star on the line](docs/chat-mega-watch.png)

<sub>Screenshots use invented players and chat over a blurred game scene.</sub>

- **Tabs:** All (everything but megaphones), Whisper, Party, Buddy, Mega, Watch, and one of your own.
- **Looks like the game**, and follows the game's chat box as you move or resize it.
- **Watch list:** a chime when a megaphone mentions what you're after, optionally only sellers in your price range.
- **Splits and extra windows:** megaphones above, chat below, or a chat window beside the game.
- **Twitch chat** and **guild chat ↔ Discord**, both opt-in.
- **History** kept between restarts.

> **Disclaimer.** Third-party software, not made or endorsed by Nexon. It only **reads what's on
> screen** (text recognition, like a screen recorder sees the game). It never opens the game's
> process, reads or changes its memory or files, touches its network traffic, or sends input.
> Nexon's terms still don't allow third-party programs: **use it at your own risk.**

## Download

**[⬇ CustomClassicChat-win64.zip](https://github.com/mentulatv/customclassic-chat/releases/latest/download/CustomClassicChat-win64.zip)**
(Windows 10/11, nothing to install)

1. Unzip it anywhere.
2. Start the game (**windowed** or **borderless**), then run **`CustomClassicChat.exe`**.

If Windows says "Windows protected your PC", click **More info → Run anyway** (the program isn't
code-signed). `CustomClassic Chat demo.bat` shows it with made-up chat.

**Updating:** the app tells you when a new version is out. Unzip it over the old folder; your
settings and history stay.

## Using it

| | |
|---|---|
| **≡** or right-click | The menu: new chat window, split, see-through, move or resize, settings. |
| **◐** | See-through: clicks go to the game until you click ◐ again. |
| **Tabs** | Click to switch. Drag the tab row up or down to resize from the top. |
| **Corner grip** | Resize (extra windows). |
| **⚠** | The game's chat is too short (under 3 lines) or closed, so lines could be missed. |

To resize the game's own chat, drag its top edge: the chat steps aside while you drag and follows.

**Tray icon:** left-click shows or hides the chat; right-click for the menu and **Quit**.

| Hotkey | |
|---|---|
| Ctrl+Alt+F3 | Reset position |
| Ctrl+Alt+F6 | Hide / show |
| Ctrl+Alt+F7 | Quit |
| Ctrl+Alt+F5 | Move and resize (turn on in Settings → Position) |

## Settings

Right-click the tray icon → **Settings…**. Changes apply right away.

<img src="docs/settings-appearance.png" alt="Settings, Appearance: text size, panel opacity, solid text" width="49%"> <img src="docs/settings-watch-list.png" alt="Settings, Watch list: words and items to look out for, and how to be told" width="49%">

- **Basics:** text size and opacity, position, time stamps and what to leave out, watch list.
- **Extras:** your own tab, windows and splits, Twitch, Guild ↔ Discord.
- **Advanced:** font and colours, history length, reading speed.

**Reading speed** (Advanced → Performance): the chat is only read when it changes. **Fastest**
(the default) reads every change; **Balanced** and **Light** use a little less CPU but can miss
lines in heavy spam like Kerning PQ. A taller game chat helps more than any speed.

## Twitch chat

Settings → Twitch → tick **Show Twitch chat** and enter the channel. Read as a guest: no account
or login.

## Guild ↔ Discord

Guild chat goes to your guild's Discord channel, and that channel shows in a **Guild** tab where
members can type back.

- **Admins:** Settings → Guild ↔ Discord → **Add the bot to your server**, then `/bind` in the channel.
- **Members:** `/guildcode` in Discord, then enter the code in Settings → Guild ↔ Discord → **Join**.

**[Setup guide →](docs/guild-setup.md)**

> The game doesn't have guild chat yet. It's picked up as soon as it appears.

## Privacy

- Your game chat stays on your PC, except guild chat once you join a guild (encrypted, members only).
- It downloads item names from the [Maple Price Index](https://mapleprice.mentula.tv) for the watch
  list, and Twitch chat if you turn it on. Nothing else.

## If something's off

- **Nothing shows:** the game's chat needs a few lines showing. Press Ctrl+Alt+F3.
- **Wrong place:** tray → **Reset position**, or right-click → **Move or resize…**.
- **Chat in the wrong tab:** copy `config.example.toml` to `config.toml` and adjust the colours.
- **A yellow border around the game** (Windows 10): Windows marks captured windows; Windows 11 doesn't.
- Anything else: open an issue with a screenshot.

## From source

Python 3.11+: run `setup.bat` once, then `start.bat` (`--demo` for the demo). `build.bat` makes the
zip; `python -m pytest` runs the tests.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Nexon. MapleStory is a trademark of Nexon.
