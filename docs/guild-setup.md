# Guild ↔ Discord setup

Guild chat goes to a channel in your guild's Discord, and that channel shows in a **Guild** tab
where members can type back.

> The game doesn't have guild chat yet. The Guild tab already works, and guild chat is shared as
> soon as it appears.

## Admins (once)

1. **Add the bot:** Settings → Guild ↔ Discord → **Add the bot to your server**. Choose
   **Add to Server** (not *Add to My Apps*).
2. **Bind it:** type `/bind` and your guild's name in the guild chat channel. The bot pins the
   guild code there.

For a private channel, give the bot **View Channel**, **Send Messages**, **Read Message History**
and **Manage Messages**.

| Command | |
|---|---|
| `/bind` | Bind the guild to this channel (also moves it, keeping its code). Admins. |
| `/rename` | Change the guild's name; the code stays. Admins. |
| `/unbind` | Stop. Admins. |
| `/guildcode` | Show the code (only you see it). |
| `/chatlink` | Link your Discord name. |

![Settings → Guild ↔ Discord](settings-guild.png)

## Members

1. Type `/guildcode` in the guild's Discord channel.
2. Settings → Guild ↔ Discord: paste the code, press **Join**.
3. Tick **Show a Guild tab**. Click its bottom line to type; messages go under your character's name.

**Optional:** `/chatlink` adds your Discord name (`QuestGuy - @mentula ✓`). Open the link it gives
you while the app runs. It lasts 90 days.

## If something's off

| Problem | Fix |
|---|---|
| `/bind` doesn't show up | Re-add the bot with **Add to Server**; commands can take a minute. |
| *"Waiting for the guild's details…"* | Give it a minute; check the code with `/guildcode`. |
| Nothing from Discord in the Guild tab | Give the bot the channel permissions above. |
| *"port 47321 is taken"* | Close the program using it and restart the app. |
| The login link doesn't work | It expired: `/chatlink` again. |

## Privacy

- Only guild chat is sent, with the speaker's name and time. Nothing is typed into the game.
- Messages are encrypted with the guild code and pass through public relays that can't read them.
- Anyone with the code can read and post: keep it in the guild. If it leaks, `/unbind` and `/bind` again.
