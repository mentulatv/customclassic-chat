# Guild chat to Discord: setup guide

Your guild's in-game chat goes to a channel in your guild's Discord, and that channel comes back
into CustomClassic Chat as a **Guild** tab, where members can type to it too.

> The game doesn't have guild chat yet. Until it does, the Guild tab and typing from the app
> already work, and the game's guild chat is shared as soon as it exists.

There are two parts:

- **[For the server's admins](#for-the-servers-admins-once)**: done once, in Discord, takes a minute.
- **[For every member](#for-members)**: put in the code, and optionally add your Discord identity.

---

## For the server's admins (once)

You need to be an admin of the Discord server, and a text channel for guild chat, for example
`#guild`. If it's a private channel, give the bot **View Channel**, **Send Messages**, **Read
Message History** and **Manage Messages** (to pin the code) there after adding it.

1. **Add the bot.** In CustomClassic Chat: *Settings → Guild ↔ Discord → Add the bot to your
   server* (the last box on the page). Pick your server and choose **Add to Server**. Don't choose *Add to My Apps*:
   that doesn't put the bot in your server.

   ![Settings → Guild ↔ Discord](settings-guild.png)

2. **Bind the bot to the channel.** In the guild chat channel, type `/bind` and your guild's name
   in the game. The bot makes the guild code (like `ABCD-EFGH-JKLM`), then posts and pins in the
   channel how to join. Only the server's admins can `/bind` and `/unbind`.

3. **That's it for members:** the pinned post has the code, and `/guildcode` gives it to anyone
   who asks (only they see the answer). Point them at [For members](#for-members) below.

That's all. Nobody's PC has to stay on. The bot keeps the guild's details available and passes
Discord messages to the members' Guild tabs.

**To stop:** type `/unbind` in the channel. Members' apps stop sharing.

**Renaming:** `/rename` in the bound channel changes the guild's name (if your first choice was
taken in the game, say); the code stays the same. **Moving:** `/bind` with the same guild name in
another channel moves the guild there, also keeping its code.

A guild belongs to its Discord server: a guild of the same name in another server is another
guild, with its own code.

The bot's commands: `/bind`, `/rename` and `/unbind` (admins), `/guildcode` and `/chatlink`
(everyone).

---

## For members

### 1. Join

1. In your guild's Discord channel, type `/guildcode`. Only you see the answer.
2. In CustomClassic Chat: *Settings → Guild ↔ Discord*. Paste the code and press **Join**.
   From then on, the guild chat your app reads goes to the guild's Discord channel (guild chat
   only: nothing else is ever sent).
3. Tick **Show a Guild tab** to see the Discord channel, and what members type, in a Guild tab.

![Settings → Guild ↔ Discord](settings-guild.png)

The line under the boxes shows how it's going: the guild's name, how many members' apps are
online, and how many lines yours has shared.

**Sharing never makes copies.** Every member's app reads the same chat. The apps agree among
themselves which one posts each message, so a message is posted once however many members
share. More members sharing just means fewer gaps.

### 2. Type in the Guild tab

Open the **Guild** tab, click the line at the bottom, type, and press **Enter**. Your message goes
to the Discord channel and to every member's Guild tab under **your character's name**, read from
the game's status bar (under your level), so it follows whichever character you play. **Esc** or
a click on the game gives the keyboard back to the game.

### 3. Your Discord identity (optional)

To show your Discord name too (`QuestGuy - @mentula ✓`; just `mentula ✓` when one name contains
the other):

1. With CustomClassic Chat running, type `/chatlink` in your guild's Discord channel.
2. Open the link it gives you. It opens a page on your own PC that says
   *CustomClassic Chat is logged in as …*. You can close that tab.

The ✓ means the bot vouched for the Discord name. It lasts 90 days; then `/chatlink` again. The
link is yours alone: don't share it. *Settings → Guild ↔ Discord → Remove* takes it off this
PC.

---

## Own setup (advanced, without the shared bot)

If your guild would rather not use the shared bot: *Settings → Own guild setup* (under
Advanced).

1. **A webhook:** in the guild chat channel, *Edit Channel → Integrations → Webhooks → New Webhook
   → Copy Webhook URL*, and paste it.
2. **Your own bot (optional),** for Discord messages in the Guild tab and `!guildcode`:
   discord.com/developers → *New Application → Bot*. Copy its token and switch on **Message
   Content Intent**. The app shows the link that adds it to your server. The token stays on your
   PC.
3. **The guild's name.** Press **Create**: members join with the guild code it makes.

How to join is posted in the channel. With your own bot, Discord messages reach the members only
while your app is running. Discord identities (`/chatlink`) come from the shared bot only.

---

## If something's off

| What you see | What to do |
| --- | --- |
| `/bind` doesn't show up | Make sure the bot is in the server's member list; if not, add it again with **Add to Server**. Commands can take a minute to appear after adding. |
| *"Waiting for the guild's details…"* | The code is right, but no details have come yet. Give it a minute; check the code with `/guildcode`. |
| Nothing from Discord in the Guild tab | The bot can't see the channel (common with private channels): *Edit Channel → Permissions*, add **CustomClassic Chat**, allow **View Channel**, **Send Messages** and **Read Message History**. In an own setup without a bot, Discord messages don't come through at all. |
| Names show *(unverified)* | That message's Discord identity didn't check out (made up, or from another Discord server). |
| *"port 47321 is taken"* | Another program uses the port the login link needs. Close it and start CustomClassic Chat again. |
| The login link page says it isn't a working login | It ran out or was already replaced: `/chatlink` again. |

## Privacy

- **Only guild chat is sent**, with the speaker's name and the game's time stamp. Nothing else on your screen is sent, and
  nothing is ever typed into the game.
- **Encrypted from the code.** The members' apps meet through two free public message relays
  (MQTT). Messages are encrypted with a key made from the guild code, so the relays only pass
  sealed messages along.
- **Who can read and post:** anyone with the code can read the shared chat and post to the
  channel. Keep the code within the guild. If it leaks, `/unbind` and `/bind` again make a new
  one.
