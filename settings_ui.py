"""CustomClassic Chat's settings window: a sidebar of sections, each a page of cards.

Every change applies as it's made (the panel's own methods do the work and save), so there is
no Save button: Done just closes the window. The pages follow what a player looks for:
how it looks, where it sits, what the chat shows, the tabs, Twitch and the watch list.
"""

from __future__ import annotations

import threading
import tkinter as tk

import guild_relay
import twitch_chat

# the settings window's own palette, in the panel's dark blues
BG, SIDE, CARD, FIELD = "#111827", "#0b1120", "#172033", "#0b1120"
BORDER, ACCENT, ACCENT_HI = "#2a3654", "#3d6fd1", "#4f80e0"
INK, SOFT, WARN = "#eef3fb", "#8f9db5", "#ffc24b"
UI = "Segoe UI"
# the sidebar, most vital first: what everyone sets, features to turn on, and finer choices
SECTIONS = [("Basics", ["Appearance", "Position", "Chat", "Watch list"]),
            ("Extras", ["Tabs & windows", "Twitch", "Guild ↔ Discord"]),
            ("Advanced", ["Look", "Chat details", "Own guild setup"])]
PAGES = [name for _, names in SECTIONS for name in names]
RENAMED = {"Tabs": "Tabs & windows", "Guild": "Guild ↔ Discord", "Discord": "Guild ↔ Discord",
           "Guild setup": "Guild ↔ Discord",
           "Own setup": "Own guild setup", "Advanced": "Look"}
GUIDE = "https://github.com/mentulatv/customclassic-chat/blob/main/docs/guild-setup.md"
OWN_SETUP_GUIDE = GUIDE + "#own-setup-advanced-without-the-shared-bot"


# ------------------------------------------------------------------ widgets in one style


def button(parent, text: str, command, primary: bool = False, width: int | None = None) -> tk.Button:
    bg, hi = (ACCENT, ACCENT_HI) if primary else (BORDER, "#34446a")
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=INK, activebackground=hi, activeforeground=INK,
                  relief="flat", bd=0, padx=12, pady=4, font=(UI, 9), cursor="hand2", highlightthickness=0)
    if width:
        b.configure(width=width)
    b.bind("<Enter>", lambda e: b.configure(bg=hi))
    b.bind("<Leave>", lambda e: b.configure(bg=bg))
    return b


def entry(parent, var: tk.StringVar, width: int = 24) -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width, bg=FIELD, fg=INK, insertbackground=INK, relief="flat",
                    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=(UI, 10))


def check(parent, text: str, var: tk.BooleanVar, command=None) -> tk.Checkbutton:
    return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=CARD, fg=INK, selectcolor=FIELD,
                          activebackground=CARD, activeforeground=INK, highlightthickness=0, bd=0, font=(UI, 10),
                          anchor="w", cursor="hand2")


def radio(parent, text: str, var: tk.Variable, value, command) -> tk.Radiobutton:
    return tk.Radiobutton(parent, text=text, variable=var, value=value, command=command, bg=CARD, fg=INK,
                          selectcolor=FIELD, activebackground=CARD, activeforeground=INK, highlightthickness=0,
                          bd=0, font=(UI, 10), anchor="w", cursor="hand2")


def label(parent, text: str, soft: bool = False, size: int = 10, bold: bool = False, bg: str = CARD,
          wrap: int = 0) -> tk.Label:
    return tk.Label(parent, text=text, bg=bg, fg=SOFT if soft else INK, anchor="w", justify="left",
                    font=(UI, size, "bold") if bold else (UI, size), wraplength=wrap)


def card(page, title: str, hint: str = "") -> tk.Frame:
    """A box of related settings with a heading and a line saying what they do."""
    outer = tk.Frame(page, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    outer.pack(fill="x", pady=(0, 12))
    body = tk.Frame(outer, bg=CARD, padx=16, pady=12)
    body.pack(fill="x")
    label(body, title, bold=True).pack(fill="x")
    if hint:
        label(body, hint, soft=True, size=9, wrap=470).pack(fill="x", pady=(1, 0))
    inner = tk.Frame(body, bg=CARD)
    inner.pack(fill="x", pady=(8, 0))
    return inner


def slider(parent, var: tk.IntVar, low: int, high: int, command, unit: str = "") -> tk.Frame:
    """A slider with its value shown at the right end."""
    row = tk.Frame(parent, bg=CARD)
    shown = label(row, f"{var.get()}{unit}", soft=True)

    def moved(v):
        shown.configure(text=f"{int(float(v))}{unit}")
        command(v)
    tk.Scale(row, from_=low, to=high, variable=var, command=moved, orient="horizontal", showvalue=False, length=360,
             bg=ACCENT, troughcolor=FIELD, activebackground=ACCENT_HI, highlightthickness=0, bd=0,  # bg: the thumb
             sliderrelief="flat", sliderlength=18, width=12, cursor="hand2").pack(side="left")
    shown.configure(width=6)
    shown.pack(side="left", padx=(10, 0))
    return row


# ------------------------------------------------------------------ the window


class SettingsWindow:
    def __init__(self, app):
        self.app, self.opts = app, app.opts
        top = self.top = tk.Toplevel(app.root)
        top.title("CustomClassic Chat settings")
        top.configure(bg=BG)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        try:
            top.iconbitmap(str(app.icon_path()))
        except Exception:
            pass
        # the chat windows keep themselves on top of the game: while this is open they stay under it
        import overlay
        top.update_idletasks()
        overlay.set_ceiling(top)
        top.bind("<Destroy>", lambda e: e.widget is top and overlay.set_ceiling(None), add="+")

        side = tk.Frame(top, bg=SIDE, width=180)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        label(side, "Settings", size=13, bold=True, bg=SIDE).pack(fill="x", padx=18, pady=(18, 12))
        self.nav: dict[str, tk.Label] = {}
        for section, names in SECTIONS:
            label(side, section.upper(), soft=True, size=8, bold=True, bg=SIDE).pack(fill="x", padx=18, pady=(8, 2))
            for name in names:
                item = tk.Label(side, text=name, bg=SIDE, fg=SOFT, anchor="w", font=(UI, 10), padx=18, pady=4,
                                cursor="hand2")
                item.pack(fill="x")
                item.bind("<Button-1>", lambda e, n=name: self.show(n))
                item.bind("<Enter>", lambda e, n=name: n != self.page and self.nav[n].configure(fg=INK))
                item.bind("<Leave>", lambda e, n=name: n != self.page and self.nav[n].configure(fg=SOFT))
                self.nav[name] = item
        done = button(side, "Done", top.destroy, primary=True)
        done.pack(side="bottom", fill="x", padx=18, pady=18)
        label(side, "Changes apply right away.", soft=True, size=8, bg=SIDE, wrap=150).pack(side="bottom", padx=18,
                                                                                            fill="x")
        import updates
        check_updates = tk.BooleanVar(value=self.opts["update_check"])
        tick = check(side, "Check for updates", check_updates,
                     lambda: app.set_opt("update_check", check_updates.get()))
        tick.configure(bg=SIDE, activebackground=SIDE, font=(UI, 8), fg=SOFT)
        tick.pack(side="bottom", fill="x", padx=16)
        label(side, f"Version {updates.VERSION}", soft=True, size=8, bg=SIDE).pack(side="bottom", padx=18, fill="x")

        self.content = tk.Frame(top, bg=BG, padx=24, pady=20, width=560, height=600)
        self.content.pack(side="left", fill="both", expand=True)
        self.content.pack_propagate(False)
        self.pages: dict[str, tk.Frame] = {}
        builders = {"Appearance": self.appearance, "Position": self.position, "Chat": self.chat,
                    "Watch list": self.watch_list, "Tabs & windows": self.tabs, "Twitch": self.twitch,
                    "Guild ↔ Discord": self.discord, "Look": self.look,
                    "Chat details": self.chat_details, "Own guild setup": self.own_setup}
        for name, build in builders.items():
            page = tk.Frame(self.content, bg=BG)
            label(page, name, size=15, bold=True, bg=BG).pack(fill="x", pady=(0, 14))
            build(page)
            self.pages[name] = page
        self.page = None
        last = RENAMED.get(self.opts.get("settings_page"), self.opts.get("settings_page"))
        self.show(last if last in PAGES else PAGES[0])
        top.bind("<Escape>", lambda e: top.destroy())
        self.place()

    def show(self, name: str) -> None:
        if self.page:
            self.pages[self.page].pack_forget()
            self.nav[self.page].configure(bg=SIDE, fg=SOFT, font=(UI, 10))
        self.page = name
        self.pages[name].pack(fill="both", expand=True)
        self.nav[name].configure(bg=CARD, fg=INK, font=(UI, 10, "bold"))
        self.opts["settings_page"] = name

    def place(self) -> None:
        """Above the panel, and always on the screen."""
        top, app = self.top, self.app
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        x = max(0, min(app.root.winfo_x() + 20, sw - top.winfo_width() - 10))
        y = max(0, min(app.strip.root.winfo_y() - top.winfo_height() - 20, sh - top.winfo_height() - 60))
        top.geometry(f"+{x}+{y}")

    # pages ------------------------------------------------------------------

    def appearance(self, page) -> None:
        app, opts = self.app, self.opts
        c = card(page, "Text size", "The messages' size in pixels, or the same size as the game's own chat.")
        size = tk.IntVar(value=opts["font_px"] or app.auto_px())
        row = slider(c, size, 9, 32, lambda v: app.set_text_size(int(float(v))), " px")
        row.pack(fill="x")
        button(c, "Match the game's text", lambda: (app.set_text_size(None), size.set(app.auto_px()))).pack(
            anchor="w", pady=(8, 0))

        c = card(page, "Transparency", "How much of the game shows through the panel.")
        opacity = tk.IntVar(value=round(opts["opacity"] * 100))

        def set_opacity(v):
            opts["opacity"] = round(int(float(v)) / 100, 2)
            app.set_opt("opacity", opts["opacity"])
            app.apply_see_through()
        label(c, "Panel opacity", soft=True, size=9).pack(fill="x")
        slider(c, opacity, 30, 100, set_opacity, "%").pack(fill="x", pady=(0, 6))
        solid = tk.BooleanVar(value=opts["solid_text"])

        def set_solid():
            app.set_opt("solid_text", solid.get())
            app.apply_see_through()
            app.render()
        check(c, "Keep the text solid: only the background fades (the text gets a shadow)", solid,
              set_solid).pack(fill="x", pady=(8, 0))

    def colour_of(self, key: str) -> str:
        from customclassic_chat import COLORS, PANEL
        return (self.opts["panel_bg"] or PANEL) if key == "panel_bg" else (self.opts["colors"].get(key) or COLORS[key])

    def paint_swatches(self) -> None:
        for key, sw in self.swatches.items():
            sw.delete("all")
            sw.create_rectangle(1, 1, 17, 17, fill=self.colour_of(key), outline=SOFT)

    def pick(self, key: str) -> None:
        self.app.pick_colour(key)
        self.paint_swatches()

    def reset_colours(self) -> None:
        self.app.reset_colours()
        self.paint_swatches()

    def position(self, page) -> None:
        app = self.app
        c = card(page, "Where the panel sits",
                 "On the game's chat box it follows the game window and fits its chat. Unlocked, you can put it "
                 "anywhere, even off the game or on another screen; it still reads the game's chat.")
        unlocked = app.settings_vars["unlocked"] = tk.BooleanVar(value=self.opts["unlocked"])
        radio(c, "On the game's chat box", unlocked, False, lambda: app.set_unlocked(False)).pack(fill="x")
        radio(c, "Unlocked: anywhere I put it", unlocked, True, lambda: app.set_unlocked(True)).pack(fill="x")
        label(c, "When unlocking, drag the panel where you want it and its corner to resize, then press "
                 "Ctrl+Alt+F5 to keep it there.", soft=True, size=9, wrap=470).pack(fill="x", pady=(6, 0))

        c = card(page, "Reset position",
                 "Lost the panel, or moved it off the chat by accident? This puts it back on the game's chat box. "
                 "Ctrl+Alt+F3 does the same.")
        button(c, "Reset position", lambda: (app.reset_position(), unlocked.set(False))).pack(anchor="w")

    def chat(self, page) -> None:
        app, opts = self.app, self.opts
        from customclassic_chat import PADDED_KINDS
        c = card(page, "Time stamps", "Time stamps come from CustomClassic Chat's own clock.")
        stamps = tk.StringVar(value=opts["timestamps"])
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        for value, text in (("seconds", "18:16:05"), ("minutes", "18:16"), ("off", "No time stamps")):
            radio(row, text, stamps, value, lambda: app.set_opt("timestamps", stamps.get())).pack(side="left",
                                                                                                 padx=(0, 16))
        c = card(page, "Leave out", "Lines you'd rather not see. Left-out lines are kept, so ticking a box "
                                    "off brings them back.")
        system = tk.BooleanVar(value=not opts["system_messages"])

        def set_system():
            app.log.hidden = {"system"} if system.get() else set()
            app.scroll = 0
            app.set_opt("system_messages", not system.get())
        check(c, "The game's system messages (out of MP, shop closed, play time…)", system, set_system).pack(fill="x")
        padded = tk.BooleanVar(value=bool(opts["hide_padded"]))

        def set_padded():  # all kinds at once; Chat details picks them one by one
            chosen = [k for k, _ in PADDED_KINDS] if padded.get() else []
            app.log.hide_padded = set(chosen)
            app.scroll = 0
            app.set_opt("hide_padded", chosen)
        check(c, "Lines padded with spacers to fill the chat (@@@@@@)", padded, set_padded).pack(fill="x", pady=(4, 0))
        label(c, "Your character names, comma separated (their name tags behind the chat aren't chat):",
              soft=True, size=9, wrap=470).pack(fill="x", pady=(10, 2))
        names = tk.StringVar(value=", ".join(opts["ignore_names"]))

        def set_names(*_):
            app.set_opt("ignore_names", [n.strip() for n in names.get().split(",") if n.strip()])
        entry(c, names, 40).pack(anchor="w", ipady=2)
        names.trace_add("write", set_names)

        c = card(page, "Sound")
        sound = tk.BooleanVar(value=opts["whisper_sound"])
        check(c, "Chime when a whisper arrives", sound, lambda: app.set_opt("whisper_sound", sound.get())).pack(
            fill="x")
    def tabs(self, page) -> None:
        app, opts = self.app, self.opts
        from customclassic_chat import CUSTOM_KINDS
        custom = {"on": False, "name": "Custom", "kinds": [], **(opts["custom_tab"] or {})}
        on = tk.BooleanVar(value=custom["on"])
        name = tk.StringVar(value=custom["name"])
        picked = {k: tk.BooleanVar(value=k in custom["kinds"]) for k, _ in CUSTOM_KINDS}

        def changed(*_):
            app.set_custom_tab({"on": on.get(), "name": name.get().strip()[:12] or "Custom",
                                "kinds": [k for k, _ in CUSTOM_KINDS if picked[k].get()]})
        c = card(page, "A tab of your own", "A tab showing just the chat you pick, next to the game's own tabs.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        check(row, "Show it, named", on, changed).pack(side="left")
        entry(row, name, 14).pack(side="left", padx=8, ipady=2)
        name.trace_add("write", changed)
        label(c, "It shows:", soft=True, size=9).pack(fill="x", pady=(10, 2))
        grid = tk.Frame(c, bg=CARD)
        grid.pack(fill="x")
        for i, (k, text) in enumerate(CUSTOM_KINDS):
            check(grid, text, picked[k], changed).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 30), pady=1)

        c = card(page, "Split the chat", "A second pane on top with its own tabs, say Mega above and All below.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        button(row, "Split the chat", app.add_split, primary=True).pack(side="left")
        note = label(row, "", soft=True, size=9)
        note.pack(side="left", padx=(12, 0))

        def show_splits():
            n = sum(1 for w in app.windows if w.docked)
            note.configure(text="Not split." if not n else f"Split into {n + 1} panes.")
        show_splits()

        c = card(page, "Extra chat windows", "More windows anywhere on screen, each with its own tab; right-click one to close it.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        button(row, "Add a chat window", app.add_window, primary=True).pack(side="left")
        count = label(row, "", soft=True, size=9)
        count.pack(side="left", padx=(12, 0))

        def show_count():
            n = sum(1 for w in app.windows if not w.docked)
            count.configure(text="No extra windows yet." if not n else f"{n} extra window{'s' if n != 1 else ''} open.")
        app.settings_vars["windows"] = lambda: count.winfo_exists() and (show_count(), show_splits())
        show_count()

    def twitch(self, page) -> None:
        app, opts = self.app, self.opts
        on = tk.BooleanVar(value=opts["twitch_on"])
        channel = tk.StringVar(value=opts["twitch_channel"])
        in_all = tk.BooleanVar(value=opts["twitch_in_all"])
        c = card(page, "Twitch chat", "A Twitch channel's chat in its own tab. It's read as a guest, the way "
                                      "anyone can watch a channel's chat: no login, and it never writes in the chat.")
        note = label(c, "", soft=True, size=9)

        def use(*_):
            name = twitch_chat.channel_name(channel.get())
            if channel.get().strip() and not name:
                note.configure(text="That isn't a Twitch channel name (letters, numbers and _).", fg=WARN)
                return
            channel.set(name)
            app.set_twitch(on.get(), name, in_all.get())
            if app.twitch_channel():
                note.configure(text=f"Reading #{name}'s chat.", fg=SOFT)
            elif on.get():
                note.configure(text="Type the channel's name, then press Use.", fg=WARN)
            else:
                note.configure(text="Off.", fg=SOFT)
        check(c, "Show Twitch chat", on, use).pack(fill="x")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        label(row, "Channel").pack(side="left")
        field = entry(row, channel, 22)
        field.pack(side="left", padx=8, ipady=2)
        field.bind("<Return>", use)
        button(row, "Use", use).pack(side="left")
        check(c, "Show it in All too", in_all, use).pack(fill="x", pady=(8, 0))
        note.pack(fill="x", pady=(6, 0))
        note.configure(text=f"Reading #{app.twitch_channel()}'s chat." if app.twitch_channel() else
                       "Off. Tick Show Twitch chat to turn it on.")

    def discord(self, page) -> None:
        """Guild ↔ Discord on one page: joining with the guild code (the guild chat this app reads is
        then shared), an optional Discord identity on what you type, and (for the server's admins)
        binding the bot to the guild's channel."""
        app, opts, top = self.app, self.opts, self.top
        code = self.discord_code = tk.StringVar(value=guild_relay.key_label(opts["relay_code"]))
        tab = tk.BooleanVar(value=opts["relay_tab"])
        c = card(page, "1. Join your guild", "Get the code with /guildcode in your guild's Discord. Joined, your "
                                             "guild chat goes to the guild's Discord channel.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        label(row, "Guild code").pack(side="left")
        field = entry(row, code, 18)
        field.pack(side="left", padx=8, ipady=2)
        note = label(c, "", soft=True, size=9, wrap=470)
        waiting = label(c, "", size=9, wrap=470)
        waiting.configure(fg=WARN)
        if not app.guild_colour_known():
            waiting.configure(text="The game doesn't have guild chat yet: it's shared as soon as it does.")

        def show_status():
            key = guild_relay.guild_key(code.get())
            if not key:
                note.configure(text="Not in a guild's chat." if not code.get().strip() else
                               "That isn't a guild code (it looks like ABCD-EFGH-JKLM).", fg=SOFT)
                return
            cfg = opts["relay_cfg"].get(key) or opts["relay_admin"].get(key) or {}
            peer = app.relay
            if not peer:
                note.configure(text="Press Join.", fg=SOFT)
                return
            online = peer.members()
            name = cfg.get("name") or peer.cfg.get("name")
            where = f"{name} · " if name else "Waiting for the guild's details… · "
            no_bot = (" · no bot, so no Discord messages here"
                      if peer.tab and peer.cfg.get("webhook") and not peer.cfg.get("has_bot") else "")
            note.configure(text=where + f"{online} app{'s' if online != 1 else ''} online · {peer.shared} shared, "
                                f"{peer.posted} posted from here" + no_bot +
                           (f". Problem: {peer.error}." if peer.error else ""), fg=WARN if peer.error else SOFT)

        def use(*_):
            key = guild_relay.guild_key(code.get())
            if code.get().strip() and not key:
                show_status()
                return
            app.set_relay(key, tab.get())
            code.set(guild_relay.key_label(key))
            note.configure(text="Joining…" if app.relay else "", fg=SOFT)
        button(row, "Join", use).pack(side="left")
        field.bind("<Return>", use)
        check(c, "Show a Guild tab (the Discord channel, and typing to it)", tab, use).pack(fill="x", pady=(8, 0))
        waiting.pack(fill="x", pady=(6, 0))
        note.pack(fill="x", pady=(4, 0))

        def tick():  # the status kept current while the window is open
            if top.winfo_exists():
                show_status()
                show_identity()
                top.after(3000, tick)

        c = card(page, "2. Your Discord identity (optional)",
                 "What you type goes under your character's name. To add your Discord name (✓): /chatlink in "
                 "your guild's Discord, then open its link.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        who = label(row, "", size=9, wrap=380)
        who.pack(side="left")

        def show_identity():
            claims = guild_relay.check_login(opts["guild_login"]) if opts["guild_login"] else None
            game = app.game_name()
            if claims:
                days = max(0, int((claims["exp"] - __import__("time").time()) // 86400))
                who.configure(text=f"You type as {guild_relay.who(game or '?', claims['name'])} ✓ "
                                   f"({days} days left).", fg=INK)
            else:
                ran_out = " (your Discord identity ran out: /chatlink again)" if opts["guild_login"] else ""
                who.configure(text=(f"You type as {game}{ran_out}." if game else
                                    "Your character's name is read from the game's status bar."), fg=SOFT)

        def remove():
            app.set_opt("guild_login", "")
            if app.relay:
                app.relay.login = ""
            out.pack_forget()
            show_identity()
        out = button(row, "Remove", remove)
        if opts["guild_login"]:  # nothing to remove otherwise
            out.pack(side="right")
        tick()

        # ---- 3. the server's admins, once
        c = card(page, "Set up your guild's Discord (admins, once)",
                 "Add the bot, then type /bind in the guild's channel: it pins the code there.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        invite = guild_relay.shared_bot_invite()
        if invite:
            button(row, "Add the bot to your server", lambda: __import__("webbrowser").open(invite),
                   primary=True).pack(side="left")
        button(row, "Guide", lambda: __import__("webbrowser").open(GUIDE)).pack(side="left", padx=(8, 0))
        button(row, "Without the shared bot…", lambda: __import__("webbrowser").open(OWN_SETUP_GUIDE)).pack(
            side="left", padx=(8, 0))

    def own_setup(self, page) -> None:
        """A guild run from this PC: a webhook, optionally its own bot, and how members join."""
        app, opts, top = self.app, self.opts, self.top
        hook, bot, gname = tk.StringVar(), tk.StringVar(), tk.StringVar()
        c = card(page, "1. A webhook for the channel", "In the Discord channel for guild chat: Edit Channel → "
                                                       "Integrations → Webhooks → New Webhook → Copy Webhook URL.")
        f = entry(c, hook, 52)
        f.configure(show="•")  # a secret: anyone holding it can post in the channel
        f.pack(anchor="w", ipady=2)
        c = card(page, "2. Your own bot (optional)", "For the Guild tab and !guildcode without the shared bot: "
                                                     "discord.com/developers → New Application → Bot, copy its token, "
                                                     "switch on Message Content Intent. It stays on this PC.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        f = entry(row, bot, 34)
        f.configure(show="•")
        f.pack(side="left", ipady=2)
        invite = button(row, "Add the bot to your server", lambda: None)

        def show_invite(*_):
            link = guild_relay.bot_invite(bot.get())
            if link:
                invite.configure(command=lambda: __import__("webbrowser").open(link))
                invite.pack(side="left", padx=(8, 0))
            else:
                invite.pack_forget()
        bot.trace_add("write", show_invite)
        current = guild_relay.guild_key(opts["relay_code"])
        mine = opts["relay_admin"].get(current)
        bot_note = label(c, "", soft=True, size=9, wrap=470)
        if mine:  # a guild run from here: its bot can be added or changed without making a new guild
            def bot_checked(out):
                if isinstance(out, Exception):
                    bot_note.configure(text=str(out), fg=WARN)
                    return
                opts["relay_admin"][current] = {**mine, "bot": bot.get().strip()}
                app.set_opt("relay_admin", opts["relay_admin"])
                app.start_relay()
                bot.set("")
                bot_note.configure(text=f"{out} now reads the channel for {mine.get('name', 'the guild')}'s Discord "
                                        "tab, and answers !guildcode, while this app runs.", fg=INK)

            def use_bot():
                if not bot.get().strip():
                    bot_note.configure(text="Paste the bot's token first.", fg=WARN)
                    return
                bot_note.configure(text="Checking the bot with Discord…", fg=SOFT)

                def work():
                    try:
                        out = guild_relay.check_bot(bot.get(), mine.get("channel_id", ""))
                    except Exception as e:  # shown as it is
                        out = e
                    top.after(0, lambda: top.winfo_exists() and bot_checked(out))
                threading.Thread(target=work, daemon=True).start()
            button(row, f"Use this bot for {mine.get('name', 'the guild')}", use_bot, primary=True).pack(
                side="left", padx=(8, 0))
            if mine.get("bot"):
                bot_note.configure(text="This guild has a bot. Paste another token to change it.")
        bot_note.pack(fill="x", pady=(4, 0))
        c = card(page, "3. The guild", "")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        label(row, "Guild name").pack(side="left")
        entry(row, gname, 18).pack(side="left", padx=8, ipady=2)
        label(c, "Members join with a guild code made for it.", soft=True, size=9, wrap=470).pack(fill="x",
                                                                                                pady=(4, 0))
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x")
        made = label(page, "", soft=True, size=9, wrap=520, bg=BG)

        def created(out):
            if isinstance(out, Exception):
                made.configure(text=str(out) or "Something went wrong; try again.", fg=WARN)
                return
            key = out.pop("code")
            opts["relay_admin"] = {**opts["relay_admin"], key: out}
            hook.set("")
            bot.set("")
            app.set_relay(key, opts["relay_tab"])
            self.discord_code.set(guild_relay.key_label(key))  # the Guild page shows the new guild too
            top.clipboard_clear()
            top.clipboard_append(guild_relay.key_label(key))
            made.configure(text=f"Done. Members join with {guild_relay.key_label(key)} (copied); how to join is posted "
                                "in the channel. Keep this app running now and then: it keeps the guild's details "
                                "on the channel for new members" + (", and reads Discord for the Guild tab." if
                                                                     out.get("bot") else "."), fg=INK)

        def create():
            current = guild_relay.guild_key(opts["relay_code"])
            if current in opts["relay_admin"] and not made.cget("text").startswith("You already"):
                made.configure(text=f"You already run the guild {opts['relay_admin'][current].get('name', '')} "
                                    f"({guild_relay.key_label(current)}). Press Create again to make another one "
                                    "anyway; members of the old one stay on the old one.", fg=WARN)
                return
            if len(gname.get().strip()) < 2 or not hook.get().strip():
                made.configure(text="Paste the webhook link and type the guild's name.", fg=WARN)
                return
            made.configure(text="Setting it up…", fg=SOFT)

            def work():
                try:
                    out = guild_relay.create_guild(gname.get(), hook.get(), bot.get())
                except Exception as e:  # shown as it is
                    out = e
                top.after(0, lambda: top.winfo_exists() and created(out))
            threading.Thread(target=work, daemon=True).start()
        button(row, "Create", create, primary=True).pack(side="left")

        def close():
            key = guild_relay.guild_key(opts["relay_code"])
            if app.relay and key in opts["relay_admin"]:
                app.relay.close_guild()
                opts["relay_admin"] = {k: v for k, v in opts["relay_admin"].items() if k != key}
                app.set_relay("", False)
                self.discord_code.set("")
                made.configure(text="Closed: members' apps stop sending to it.", fg=SOFT)
        if guild_relay.guild_key(opts["relay_code"]) in opts["relay_admin"]:
            button(row, "Close this guild", close).pack(side="left", padx=(8, 0))
        made.pack(fill="x", pady=(8, 0))

    def look(self, page) -> None:
        """Finer choices for how the chat looks: font, weight, colours, how see-through ◐ makes it."""
        import customclassic_chat as mc
        app, opts = self.app, self.opts
        c = card(page, "Font", "The messages' font. Bold reads better over a busy game.")
        family = tk.StringVar(value=opts["font_family"] if opts["font_family"] in dict(mc.FONTS) else mc.FONT)
        bold = tk.BooleanVar(value=opts["font_bold"])

        def use():
            app.set_font(family.get(), bold.get())
        grid = tk.Frame(c, bg=CARD)
        grid.pack(fill="x")
        for i, (name, kind) in enumerate(mc.FONTS):  # two columns, each font shown in itself
            r = radio(grid, name, family, name, use)
            r.configure(font=(name, 10))
            r.grid(row=i % 4, column=2 * (i // 4), sticky="w")
            label(grid, kind, soft=True, size=9).grid(row=i % 4, column=2 * (i // 4) + 1, sticky="w", padx=(8, 28))
        check(c, "Bold", bold, use).pack(fill="x", pady=(8, 0))

        c = card(page, "Colours", "Click a colour to change it. The text colours start as the game's own.")
        grid = tk.Frame(c, bg=CARD)
        grid.pack(fill="x")
        self.swatches: dict[str, tk.Canvas] = {}
        keys = [("panel_bg", "Background"), ("map", "Map"), ("whisper", "Whisper"), ("party", "Party"),
                ("buddy", "Buddy"), ("system", "System"), ("mega", "Mega"), ("twitch", "Twitch")]
        for i, (key, text) in enumerate(keys):
            cell = tk.Frame(grid, bg=CARD, cursor="hand2")
            cell.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 18), pady=3)
            sw = tk.Canvas(cell, width=18, height=18, bg=CARD, highlightthickness=0, cursor="hand2")
            sw.pack(side="left")
            name = label(cell, text)
            name.pack(side="left", padx=(6, 0))
            for w in (cell, sw, name):
                w.bind("<Button-1>", lambda e, k=key: self.pick(k))
            self.swatches[key] = sw
        self.paint_swatches()
        button(c, "Reset to default colours", self.reset_colours).pack(anchor="w", pady=(10, 0))

        c = card(page, "See-through with ◐", "How see-through ◐ on the tab row makes the messages.")
        see = tk.IntVar(value=round((1 - opts["peek_alpha"]) * 100))

        def set_see(v):
            opts["peek_alpha"] = round(1 - int(float(v)) / 100, 2)
            app.set_opt("peek_alpha", opts["peek_alpha"])
            app.apply_see_through()
        slider(c, see, 50, 95, set_see, "%").pack(fill="x")

    def chat_details(self, page) -> None:
        """Finer choices for the chat: how long it's kept, which spacer lines, the right-click menu."""
        app, opts = self.app, self.opts
        from customclassic_chat import PADDED_KINDS
        c = card(page, "History", "The chat is kept between restarts.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        label(row, "Keep the last").pack(side="left")
        hours = tk.StringVar(value=str(opts["keep_hours"] or 12))
        forever = tk.BooleanVar(value=not opts["keep_hours"])

        def set_keep(*_):
            try:
                h = max(1, int(float(hours.get())))
            except ValueError:
                return
            app.set_opt("keep_hours", 0 if forever.get() else h)
        tk.Spinbox(row, from_=1, to=720, width=5, textvariable=hours, command=set_keep, bg=FIELD, fg=INK,
                   insertbackground=INK, buttonbackground=BORDER, relief="flat", highlightthickness=1,
                   highlightbackground=BORDER, highlightcolor=ACCENT, font=(UI, 10)).pack(side="left", padx=6)
        hours.trace_add("write", set_keep)
        label(row, "hours").pack(side="left")
        check(row, "Keep it forever", forever, set_keep).pack(side="left", padx=(18, 0))

        c = card(page, "Spacer lines", "Lines padded with spacers to fill the chat (@@@@@@): which kinds to leave out.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        spacers = {k: tk.BooleanVar(value=k in (opts["hide_padded"] or [])) for k, _ in PADDED_KINDS}

        def set_spacers():
            chosen = [k for k, _ in PADDED_KINDS if spacers[k].get()]
            app.log.hide_padded = set(chosen)
            app.scroll = 0
            app.set_opt("hide_padded", chosen)
        for k, text in PADDED_KINDS:
            check(row, text, spacers[k], set_spacers).pack(side="left", padx=(0, 16))
        c = card(page, "Right-click menu")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        label(row, "Close the right-click menu after").pack(side="left")
        secs = tk.StringVar(value=str(opts["menu_close_s"] or 0))

        def set_secs(*_):
            try:
                app.set_opt("menu_close_s", max(0, int(float(secs.get()))))
            except ValueError:
                pass
        tk.Spinbox(row, from_=0, to=120, width=4, textvariable=secs, command=set_secs, bg=FIELD, fg=INK,
                   insertbackground=INK, buttonbackground=BORDER, relief="flat", highlightthickness=1,
                   highlightbackground=BORDER, highlightcolor=ACCENT, font=(UI, 10)).pack(side="left", padx=6)
        secs.trace_add("write", set_secs)
        label(row, "seconds (0: until clicked away)", soft=True, size=9).pack(side="left")

    def watch_list(self, page) -> None:
        app, opts = self.app, self.opts
        c = card(page, "Look out for", "A chime and a note when a megaphone mentions one of these. Items can "
                                       "have conditions: sellers only, and a price range you set.")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x")
        box = tk.Listbox(row, height=7, bg=FIELD, fg=INK, selectbackground=ACCENT, selectforeground=INK,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, relief="flat",
                         bd=0, font=(UI, 10), activestyle="none")
        box.pack(side="left", fill="both", expand=True)

        def refresh():
            box.delete(0, "end")
            for e in app.watcher.entries:
                box.insert("end", ("  ★  " if e.on else "  ○  ") + e.label() + ("" if e.on else "   (off)"))
            if not app.watcher.entries:
                box.insert("end", "  Nothing yet: press Add…")

        def chosen():
            sel = box.curselection()
            return sel[0] if sel and app.watcher.entries else None

        def edit(i=None):
            WatchEntryDialog(app, self.top, i, refresh)

        def remove():
            i = chosen()
            if i is not None:
                app.save_watch([e for k, e in enumerate(app.watcher.entries) if k != i])
                refresh()

        def toggle():
            i = chosen()
            if i is not None:
                app.watcher.entries[i].on = not app.watcher.entries[i].on
                app.save_watch(app.watcher.entries)
                refresh()
                box.selection_set(i)
        side = tk.Frame(row, bg=CARD)
        side.pack(side="left", fill="y", padx=(10, 0))
        button(side, "Add…", edit, primary=True, width=9).pack(pady=(0, 4))
        for text, cmd in (("Edit…", lambda: chosen() is not None and edit(chosen())), ("On / off", toggle),
                          ("Remove", remove)):
            button(side, text, cmd, width=9).pack(pady=(0, 4))
        box.bind("<Double-Button-1>", lambda e: chosen() is not None and edit(chosen()))
        refresh()

        c = card(page, "When it finds one")
        for key, text in (("watch_sound", "Chime"), ("watch_popup", "Pop up a note above the chat"),
                          ("watch_map", "Also look in map chat, not only megaphones")):
            var = tk.BooleanVar(value=opts[key])

            def set_flag(k=key, v=var):
                app.set_opt(k, v.get())
                app.watcher.kinds = set(app.watch_kinds())
            check(c, text, var, set_flag).pack(fill="x")


class WatchEntryDialog:
    """Add or change one watch-list entry: a word or an item (names suggested from the price
    site's catalog), and the conditions for items."""

    def __init__(self, app, parent, index: int | None, done):
        w, self.app = app.watch, app
        old = app.watcher.entries[index] if index is not None else w.Entry("")
        dlg = self.top = tk.Toplevel(parent)
        dlg.title("Watch for…")
        dlg.configure(bg=BG, padx=20, pady=18)
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.transient(parent)
        try:
            dlg.iconbitmap(str(app.icon_path()))
        except Exception:
            pass

        c = card(dlg, "A word or an item", "Start typing for item names, and the shorthands chat uses for them.")
        text = tk.StringVar(value=old.text)
        field = entry(c, text, 44)
        field.pack(fill="x", ipady=3)
        hints = tk.Listbox(c, height=5, bg=FIELD, fg=INK, selectbackground=ACCENT, highlightthickness=1,
                           highlightbackground=BORDER, relief="flat", bd=0, font=(UI, 9), activestyle="none")
        hints.pack(fill="x", pady=(4, 0))
        known = label(c, "", soft=True, size=9, wrap=420)
        known.pack(fill="x", pady=(6, 0))

        def typed(*_):
            hints.delete(0, "end")
            for name in app.watcher.catalog.suggest(text.get()):
                if name.lower() != text.get().strip().lower():
                    hints.insert("end", name)
            item = app.watcher.catalog.resolve(text.get())
            if item:
                also = f"; also finds {', '.join(item['aliases'][:4])}" if item.get("aliases") else ""
                known.configure(text=f"Item: {item['name']}{also}")
            elif not app.watcher.catalog.items:
                known.configure(text="Item names aren't loaded (no connection yet): matched as written.")
            else:
                known.configure(text="Not a known item name: matched as a word.")
        text.trace_add("write", typed)
        hints.bind("<<ListboxSelect>>", lambda e: hints.curselection() and text.set(hints.get(hints.curselection()[0])))
        typed()
        exact = tk.BooleanVar(value=old.exact)
        check(c, "This exact word only (no close spellings)", exact).pack(fill="x", pady=(6, 0))

        c = card(dlg, "Only when…", "These read the megaphone's price the way the price site does. Leave a "
                                    "price empty for no limit on that side.")
        sellers = tk.BooleanVar(value=old.sellers_only)
        check(c, "Someone is selling it (S>), not buying", sellers).pack(fill="x")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        label(row, "It costs between").pack(side="left")
        low = tk.StringVar(value=w.money(old.min_price) if old.min_price else "")
        top = tk.StringVar(value=w.money(old.max_price) if old.max_price else "")
        entry(row, low, 8).pack(side="left", padx=6, ipady=2)
        label(row, "and").pack(side="left")
        entry(row, top, 8).pack(side="left", padx=6, ipady=2)
        label(row, "mesos each", soft=True, size=9).pack(side="left")
        label(c, "Like 400k, 1.5m or 250000.", soft=True, size=9).pack(fill="x", pady=(4, 0))

        problem = label(dlg, "", bg=BG, size=9)
        problem.configure(fg=WARN)
        problem.pack(fill="x")

        def save():
            name = text.get().strip()
            lo = w.parse_price(low.get()) if low.get().strip() else None
            hi = w.parse_price(top.get()) if top.get().strip() else None
            if not name:
                problem.configure(text="Type a word or an item name.")
                return
            if (low.get().strip() and not lo) or (top.get().strip() and not hi):
                problem.configure(text="Prices should look like 1.5m, 400k or 250000.")
                return
            if lo and hi and lo > hi:
                lo, hi = hi, lo  # typed the other way round
            item = app.watcher.catalog.resolve(name)
            new = w.Entry(item["name"] if item and (sellers.get() or lo or hi) else name,
                          exact.get(), sellers.get(), hi, lo, old.on)
            entries = list(app.watcher.entries)
            if index is None:
                entries.append(new)
            else:
                entries[index] = new
            app.save_watch(entries)
            done()
            dlg.destroy()
        row = tk.Frame(dlg, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        button(row, "Save", save, primary=True, width=9).pack(side="right")
        button(row, "Cancel", dlg.destroy, width=9).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        field.focus_set()
