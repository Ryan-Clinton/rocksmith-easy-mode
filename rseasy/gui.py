"""Tkinter front end.

Tkinter is used because it ships with Python on Windows and macOS, so the
only install step there is Python itself. On Linux it is one package
(python3-tk). Every panel degrades gracefully: the window still opens and
explains itself when the game, 7-Zip or the cable is missing.

Long jobs (repacking a psarc takes a few seconds) run on a worker thread and
report back through a queue, so the window never freezes.
"""
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import audio, config, games, paths, patcher, sevenzip

PAD = 10
GREY = "#6b6b6b"


# ---------------------------------------------------------------------------

class ScrollFrame(ttk.Frame):
    """A frame that scrolls vertically when its contents outgrow the window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._bar_shown = False

        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        # Wheel support, bound while the pointer is over this widget only.
        self.canvas.bind("<Enter>", lambda _e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda _e: self._wheel(False))

    def _on_body(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_bar()

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._sync_bar()

    def _sync_bar(self):
        """Show the scrollbar only when there is something to scroll to."""
        need = self.body.winfo_reqheight() > self.canvas.winfo_height()
        if need and not self._bar_shown:
            self.bar.pack(side="right", fill="y")
            self._bar_shown = True
        elif not need and self._bar_shown:
            self.bar.pack_forget()
            self._bar_shown = False

    def _wheel(self, on):
        if on:
            self.canvas.bind_all("<Button-4>", self._up)
            self.canvas.bind_all("<Button-5>", self._down)
            self.canvas.bind_all("<MouseWheel>", self._mouse)
        else:
            for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                self.canvas.unbind_all(seq)

    def _up(self, _e):
        self.canvas.yview_scroll(-2, "units")

    def _down(self, _e):
        self.canvas.yview_scroll(2, "units")

    def _mouse(self, e):
        self.canvas.yview_scroll(-1 * (e.delta // 40 or (1 if e.delta < 0 else -1)),
                                 "units")


class KnobRow:
    """One slider: bold label, nudge buttons, live value and plain-English hint."""

    def __init__(self, parent, knob, row, on_change):
        self.knob = knob
        self.on_change = on_change
        self._busy = False
        self.var = tk.DoubleVar(value=knob.default)

        head = ttk.Frame(parent)
        head.grid(row=row * 2, column=0, sticky="ew", padx=PAD, pady=(8, 0))
        head.columnconfigure(1, weight=1)

        ttk.Label(head, text=knob.label, font=("TkDefaultFont", 10, "bold")
                  ).grid(row=0, column=0, sticky="w")

        controls = ttk.Frame(head)
        controls.grid(row=0, column=2, sticky="e")
        ttk.Button(controls, text="◀", width=2,
                   command=lambda: self.nudge(-1)).pack(side="left")
        self.scale = ttk.Scale(controls, from_=knob.lo, to=knob.hi,
                               orient="horizontal", length=260,
                               variable=self.var, command=self._moved)
        self.scale.pack(side="left", padx=4)
        ttk.Button(controls, text="▶", width=2,
                   command=lambda: self.nudge(1)).pack(side="left")
        self.value = ttk.Label(controls, width=6, anchor="e")
        self.value.pack(side="left", padx=(6, 0))

        self.hint = ttk.Label(parent, text="", foreground=GREY, wraplength=680,
                              justify="left")
        self.hint.grid(row=row * 2 + 1, column=0, sticky="w",
                       padx=PAD + 4, pady=(0, 2))
        self.refresh()

    def get(self):
        return self.knob.coerce(self.var.get())

    def set(self, v):
        self._busy = True
        try:
            self.var.set(self.knob.coerce(v))
        finally:
            self._busy = False
        self.refresh()

    def nudge(self, direction):
        self.set(self.get() + direction * self.knob.step)
        if self.on_change:
            self.on_change()

    def _moved(self, _v):
        if self._busy:
            return
        self.set(self.var.get())        # snap the thumb to the knob's step
        if self.on_change:
            self.on_change()

    def refresh(self):
        v = self.get()
        stock = " = stock" if v == self.knob.stock else ""
        self.value.configure(text=games.num(v))
        self.hint.configure(text="%s%s" % (self.knob.hint(v), stock))


# ---------------------------------------------------------------------------

class GamePanel(ttk.Frame):
    """Sliders and buttons for one Guitarcade minigame."""

    def __init__(self, parent, app, game):
        super().__init__(parent)
        self.app = app
        self.game = game

        top = ttk.Frame(self)
        top.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.status = ttk.Label(top, text="", font=("TkDefaultFont", 10, "bold"))
        self.status.pack(side="left")
        ttk.Label(top, text=game.psarc, foreground=GREY).pack(side="right")

        scroller = ScrollFrame(self)
        scroller.pack(fill="both", expand=True, pady=(4, 0))
        body = scroller.body
        body.columnconfigure(0, weight=1)

        saved = app.cfg["guitarcade"].get(game.slug) or game.defaults()
        self.rows = {}
        for i, knob in enumerate(game.knobs):
            r = KnobRow(body, knob, i, self._changed)
            r.set(saved.get(knob.key, knob.default))
            self.rows[knob.key] = r

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=PAD, pady=(6, 4))
        self.apply_btn = ttk.Button(btns, text="Apply to the game",
                                    command=self.do_apply)
        self.apply_btn.pack(side="left")
        ttk.Button(btns, text="Beginner defaults",
                   command=lambda: self.load(game.defaults())).pack(
                       side="left", padx=(6, 0))
        ttk.Button(btns, text="Stock values",
                   command=lambda: self.load(game.stock())).pack(
                       side="left", padx=(6, 0))
        self.restore_btn = ttk.Button(btns, text="Put the stock game back",
                                      command=self.do_restore)
        self.restore_btn.pack(side="right")

        self.log = tk.Text(self, height=5, wrap="word", state="disabled",
                           relief="flat", background="#f4f4f4")
        self.log.pack(fill="x", padx=PAD, pady=(0, PAD))
        self.refresh_status()

    # -- helpers ------------------------------------------------------------

    def values(self):
        return self.game.clean({k: r.get() for k, r in self.rows.items()})

    def load(self, values):
        for k, r in self.rows.items():
            if k in values:
                r.set(values[k])
        self._changed()

    def _changed(self):
        # max_fret can never sit below min_fret; keep the sliders honest.
        if "min_fret" in self.rows and "max_fret" in self.rows:
            lo = self.rows["min_fret"].get()
            if self.rows["max_fret"].get() < lo:
                self.rows["max_fret"].set(lo)

    def say(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def refresh_status(self):
        d = self.app.game_dir
        if d is None:
            text, colour = "Rocksmith not found - see the Setup tab", "#a03030"
        else:
            st = patcher.status(self.game, d)
            text, colour = {
                "patched": ("Patched - your settings are live", "#2a7a2a"),
                "stock": ("Stock - nothing applied yet", GREY),
                "missing": ("%s is missing from the game" % self.game.psarc,
                            "#a03030"),
            }[st]
        self.status.configure(text=text, foreground=colour)
        ok = d is not None and patcher.status(self.game, d) != "missing"
        self.apply_btn.configure(state="normal" if ok else "disabled")
        self.restore_btn.configure(
            state="normal" if ok and patcher.status(self.game, d) == "patched"
            else "disabled")

    # -- actions ------------------------------------------------------------

    def do_apply(self):
        d = self.app.game_dir
        if d is None:
            return
        values = self.values()
        self.load(values)
        self.clear_log()
        self.app.busy(True)

        def work(log):
            return patcher.apply(self.game, values, d, log=log)

        def done(summary, error):
            self.app.busy(False)
            if error:
                self.say("FAILED: %s" % error)
                messagebox.showerror("Could not patch %s" % self.game.name,
                                     str(error), parent=self)
            else:
                for line in summary:
                    self.say(line)
                self.app.cfg["guitarcade"][self.game.slug] = values
                config.save(self.app.cfg)
                self.say("Saved. Restart Rocksmith to pick this up.")
            self.refresh_status()

        self.app.run_bg(work, self.say, done)

    def do_restore(self):
        d = self.app.game_dir
        if d is None:
            return
        if not messagebox.askyesno(
                "Put the stock game back?",
                "This restores the unmodified %s.\n\nYour slider positions are "
                "kept, so you can re-apply them at any time." % self.game.name,
                parent=self):
            return
        self.clear_log()
        try:
            if not patcher.restore(self.game, d, log=self.say):
                self.say("Nothing to undo - this game was never patched.")
        except (OSError, patcher.PatchError) as e:
            messagebox.showerror("Could not restore", str(e), parent=self)
        self.refresh_status()


# ---------------------------------------------------------------------------

class CablePanel(ttk.Frame):
    """Realtone cable input level."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.backend = audio.backend()

        head = ttk.Frame(self)
        head.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.status = ttk.Label(head, text="",
                                font=("TkDefaultFont", 10, "bold"))
        self.status.pack(side="left")
        ttk.Button(head, text="Refresh", command=self.refresh).pack(side="right")

        ttk.Label(self, wraplength=700, justify="left", foreground=GREY,
                  text="The cable's gain control spans -8 dB to +10 dB, so "
                       "unity is about %d%% - not 50%%. Anything above that is "
                       "boost, which is what makes Rocksmith's calibration say "
                       "an active-pickup instrument is too loud."
                       % audio.UNITY_PCT
                  ).pack(fill="x", padx=PAD, pady=(6, 0))

        box = ttk.LabelFrame(self, text="  How is it plugged in?  ")
        box.pack(fill="x", padx=PAD, pady=PAD)
        self.preset_widgets = {}
        for i, p in enumerate(audio.PRESETS):
            row = ttk.Frame(box)
            row.pack(fill="x", padx=PAD, pady=4)
            btn = ttk.Button(row, text=p.label, width=34,
                             command=lambda k=p.key: self.use(k))
            btn.pack(side="left")
            lbl = ttk.Label(row, width=22, foreground=GREY)
            lbl.pack(side="left", padx=(8, 0))
            ttk.Button(row, text="Save current here", width=17,
                       command=lambda k=p.key: self.save_current(k)
                       ).pack(side="right")
            self.preset_widgets[p.key] = (btn, lbl)
            ttk.Label(box, text=p.help, foreground=GREY, wraplength=700,
                      justify="left").pack(fill="x", padx=PAD + 6, pady=(0, 6))

        custom = ttk.LabelFrame(self, text="  Try a level  ")
        custom.pack(fill="x", padx=PAD, pady=(0, PAD))
        inner = ttk.Frame(custom)
        inner.pack(fill="x", padx=PAD, pady=PAD)
        self.custom = tk.DoubleVar(value=44)
        ttk.Scale(inner, from_=0, to=100, orient="horizontal", length=380,
                  variable=self.custom, command=lambda _v: self.show_custom()
                  ).pack(side="left")
        self.custom_label = ttk.Label(inner, width=24)
        self.custom_label.pack(side="left", padx=PAD)
        ttk.Button(inner, text="Set", command=self.set_custom).pack(side="right")

        self.note = ttk.Label(self, wraplength=700, justify="left",
                              foreground=GREY)
        self.note.pack(fill="x", padx=PAD, pady=(0, PAD))

        self.show_custom()
        self.refresh()

    def refresh(self):
        for p in audio.PRESETS:
            pct = self.app.cfg["input"][p.key]
            self.preset_widgets[p.key][1].configure(text=audio.describe(pct))
        if not self.backend.cable_present():
            self.status.configure(text="Realtone cable not detected",
                                  foreground="#a03030")
            self.note.configure(text=self.backend.why())
            return
        pct = self.backend.get_percent()
        self.status.configure(
            text="Cable at %s" % audio.describe(pct if pct is not None else 0),
            foreground="#2a7a2a")
        self.note.configure(
            text="" if self.backend.can_set else self.backend.why())

    def show_custom(self):
        self.custom_label.configure(text=audio.describe(self.custom.get()))

    def use(self, key):
        self.apply_level(self.app.cfg["input"][key], audio.BY_KEY[key].label)

    def set_custom(self):
        self.apply_level(int(round(self.custom.get())), "custom level")

    def apply_level(self, pct, label):
        if not self.backend.can_set:
            messagebox.showinfo(
                "Set it by hand",
                "%s wants %s\n\n%s" % (label, audio.describe(pct),
                                       self.backend.why()),
                parent=self)
            return
        try:
            self.backend.set_percent(pct)
        except audio.NotAvailable as e:
            messagebox.showerror("Could not set the level", str(e), parent=self)
            self.refresh()
            return
        msg = self.backend.persist() if self.app.cfg.get("persist_level") else None
        self.refresh()
        self.note.configure(text="%s set to %s.  %s"
                                 % (label, audio.describe(pct), msg or ""))

    def save_current(self, key):
        pct = self.backend.get_percent()
        if pct is None:
            pct = int(round(self.custom.get()))
        self.app.cfg["input"][key] = int(pct)
        config.save(self.app.cfg)
        self.refresh()
        self.note.configure(text="Saved %s as \"%s\"."
                                 % (audio.describe(pct), audio.BY_KEY[key].label))


# ---------------------------------------------------------------------------

class SetupPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        grid = ttk.Frame(self)
        grid.pack(fill="x", padx=PAD, pady=PAD)
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Rocksmith 2014", font=("TkDefaultFont", 10, "bold")
                  ).grid(row=0, column=0, sticky="w")
        self.game_var = tk.StringVar()
        game_entry = ttk.Entry(grid, textvariable=self.game_var,
                               state="readonly")
        game_entry.grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Button(grid, text="Browse...", command=self.browse).grid(
            row=0, column=2, sticky="e")
        ttk.Button(grid, text="Search again", command=self.research).grid(
            row=1, column=2, sticky="e", pady=(4, 0))

        for i, (name, value) in enumerate(self.facts(), start=2):
            ttk.Label(grid, text=name, font=("TkDefaultFont", 10, "bold")
                      ).grid(row=i, column=0, sticky="w", pady=(8, 0))
            ttk.Label(grid, text=value, wraplength=520, justify="left").grid(
                row=i, column=1, sticky="w", padx=PAD, pady=(8, 0))

        self.hint = ttk.Label(self, wraplength=700, justify="left",
                              foreground=GREY)
        self.hint.pack(fill="x", padx=PAD, pady=(0, PAD))
        self.refresh()

    def facts(self):
        sz = sevenzip.find()
        return [
            ("7-Zip", sz or "NOT FOUND - repacking will not work"),
            ("Settings file", str(config.config_file())),
            ("Input backend", audio.backend().name),
            ("Python", "%d.%d on %s" % (sys.version_info[0],
                                        sys.version_info[1], sys.platform)),
        ]

    def refresh(self):
        d = self.app.game_dir
        self.game_var.set(str(d) if d else
                          "not found - use Browse to point at it")
        if d is None:
            self.hint.configure(
                text="Looked in these places:\n%s" % paths.describe_search())
        elif not sevenzip.find():
            self.hint.configure(
                text=sevenzip.SevenZipMissing.__doc__ or
                "7-Zip is needed to repack the game archives.")
        else:
            self.hint.configure(text="Everything needed was found.")

    def browse(self):
        d = filedialog.askdirectory(
            title="Select the Rocksmith2014 folder",
            initialdir=str(self.app.game_dir or Path.home()), parent=self)
        if not d:
            return
        if not paths.is_game_dir(d):
            messagebox.showerror(
                "Not the right folder",
                "That folder has no \"guitarcade\" subfolder, so it is not a "
                "Rocksmith 2014 install.\n\nLook for a folder called "
                "Rocksmith2014 inside steamapps/common.", parent=self)
            return
        self.app.cfg["game_dir"] = str(d)
        config.save(self.app.cfg)
        self.app.rescan()

    def research(self):
        self.app.cfg["game_dir"] = None
        config.save(self.app.cfg)
        self.app.rescan()


# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.title("Rocksmith Easy Mode")
        self.minsize(720, 520)
        self.geometry("780x720")
        self._theme()

        self.game_dir = paths.find_game(cfg.get("game_dir"))

        # Packed before the notebook and anchored to the bottom, so the
        # expanding notebook can never squeeze it off the window.
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=8, pady=6)
        self.status = ttk.Label(bar, text="", foreground=GREY)
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.panels = []
        for g in games.ALL:
            p = GamePanel(self.nb, self, g)
            self.nb.add(p, text=g.name)
            self.panels.append(p)
        self.cable = CablePanel(self.nb, self)
        self.nb.add(self.cable, text="Cable Level")
        self.setup = SetupPanel(self.nb, self)
        self.nb.add(self.setup, text="Setup")

        self._q = queue.Queue()
        self.after(120, self._drain)
        self._set_status()

    def _theme(self):
        style = ttk.Style(self)
        for want in ("vista", "clam", "aqua"):
            if want in style.theme_names():
                style.theme_use(want)
                break

    def _set_status(self):
        if self.game_dir is None:
            self.status.configure(text="Rocksmith not found")
        else:
            bits = ["%s: %s" % (g.name, patcher.status(g, self.game_dir))
                    for g in games.ALL]
            self.status.configure(text="   |   ".join(bits))

    def rescan(self):
        self.game_dir = paths.find_game(self.cfg.get("game_dir"))
        for p in self.panels:
            p.refresh_status()
        self.setup.refresh()
        self.cable.refresh()
        self._set_status()

    def busy(self, on):
        if on:
            self.progress.pack(side="right")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        for p in self.panels:
            for child in p.winfo_children():
                if isinstance(child, ttk.Frame):
                    for b in child.winfo_children():
                        if isinstance(b, ttk.Button):
                            b.configure(state="disabled" if on else "normal")
        if not on:
            for p in self.panels:
                p.refresh_status()

    def run_bg(self, work, on_log, on_done):
        """Run *work(log)* off the main thread; log lines and the result come
        back through the queue so only the main thread touches widgets."""
        def thread():
            try:
                result = work(lambda m: self._q.put(("log", on_log, m)))
                self._q.put(("done", on_done, (result, None)))
            except Exception as e:                    # noqa: BLE001
                traceback.print_exc()
                self._q.put(("done", on_done, (None, e)))
        threading.Thread(target=thread, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, fn, payload = self._q.get_nowait()
                if kind == "log":
                    fn(payload)
                else:
                    fn(*payload)
                    self._set_status()
        except queue.Empty:
            pass
        self.after(120, self._drain)


def run(cfg=None):
    app = App(cfg or config.load())
    app.mainloop()
    return 0
