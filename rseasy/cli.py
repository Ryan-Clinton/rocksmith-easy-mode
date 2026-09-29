"""Command line for rocksmith-easy. Run with no arguments for the GUI."""
import argparse
import sys

from . import audio, config, games, paths, patcher, sevenzip


def flag(key):
    return "--" + key.replace("_", "-")


def resolve_game_dir(cfg, override=None):
    d = paths.find_game(override or cfg.get("game_dir"))
    if d is None:
        sys.exit("Could not find Rocksmith 2014. Looked under:\n%s\n"
                 "Pass --game-dir /path/to/Rocksmith2014 to say where it is."
                 % paths.describe_search())
    return d


# -- info -------------------------------------------------------------------

def cmd_info(args, cfg):
    d = paths.find_game(args.game_dir or cfg.get("game_dir"))
    print("Rocksmith 2014 : %s" % (d or "NOT FOUND"))
    print("7-Zip          : %s" % (sevenzip.find() or "NOT FOUND"))
    print("Config file    : %s" % config.config_file())
    b = audio.backend()
    print("Input backend  : %s" % b.name)
    if b.cable_present():
        pct = b.get_percent()
        print("Realtone cable : plugged in, at %s" % audio.describe(pct))
    else:
        print("Realtone cable : not detected")
    if d:
        print("\nGuitarcade:")
        for g in games.ALL:
            print("  %-20s %s" % (g.name, patcher.status(g, d)))
    return 0


# -- guitarcade -------------------------------------------------------------

def cmd_guitarcade(args, cfg):
    if not args.game:
        d = paths.find_game(args.game_dir or cfg.get("game_dir"))
        if d is None:
            return cmd_info(args, cfg)
        for g in games.ALL:
            print("%-20s %-8s  (%s)" % (g.name, patcher.status(g, d), g.slug))
        return 0

    game = games.BY_SLUG[args.game]
    game_dir = resolve_game_dir(cfg, args.game_dir)

    if args.stock:
        patcher.restore(game, game_dir, log=print)
        return 0

    if args.defaults:
        values = game.defaults()
    else:
        values = dict(cfg["guitarcade"].get(game.slug) or game.defaults())
    for k in game.knobs:
        v = getattr(args, k.key, None)
        if v is not None:
            values[k.key] = v
    values = game.clean(values)

    try:
        summary = patcher.apply(game, values, game_dir, log=print)
    except (patcher.PatchError, sevenzip.SevenZipMissing, RuntimeError) as e:
        sys.exit("\n%s" % e)

    print("\n%s patched" % game.name)
    for line in summary:
        print("  " + line)
    cfg["guitarcade"][game.slug] = values
    config.save(cfg)
    print("\nSettings remembered in %s" % config.config_file())
    print("Put the stock game back with: rocksmith-easy guitarcade %s --stock"
          % game.slug)
    return 0


# -- input ------------------------------------------------------------------

def cmd_input(args, cfg):
    b = audio.backend()
    presets = cfg["input"]

    if args.list or (not args.preset and args.level is None):
        print("Realtone cable input level")
        print("  unity gain is about %d%% - above that is boost\n"
              % audio.UNITY_PCT)
        if b.cable_present():
            print("  now: %s\n" % audio.describe(b.get_percent()))
        else:
            print("  cable not detected\n")
        for p in audio.PRESETS:
            print("  %-14s %-22s %s" % (
                p.key.replace("_", "-"), audio.describe(presets[p.key]),
                p.label))
        if not b.can_set:
            print("\n%s" % b.why())
        return 0

    if args.level is not None:
        pct = max(0, min(100, args.level))
        label = "custom"
    else:
        key = args.preset.replace("-", "_")
        if key not in audio.BY_KEY:
            sys.exit("unknown preset: %s" % args.preset)
        pct = presets[key]
        label = audio.BY_KEY[key].label

    if not b.can_set:
        print("%s -> %s" % (label, audio.describe(pct)))
        print("\n%s" % b.why())
        return 0

    try:
        now = b.set_percent(pct)
    except audio.NotAvailable as e:
        sys.exit(str(e))
    print("%s -> %s" % (label, audio.describe(now if now is not None else pct)))
    if cfg.get("persist_level"):
        msg = b.persist()
        if msg:
            print(msg)

    if args.save_as:
        key = args.save_as.replace("-", "_")
        if key not in audio.BY_KEY:
            sys.exit("unknown preset: %s" % args.save_as)
        cfg["input"][key] = int(pct)
        config.save(cfg)
        print("Saved %d%% as \"%s\"" % (pct, audio.BY_KEY[key].label))
    return 0


# -- gui --------------------------------------------------------------------

def cmd_gui(args, cfg):
    try:
        from .gui import run
    except ImportError as e:
        sys.exit(
            "The GUI needs Tkinter, which this Python does not have (%s).\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Fedora:        sudo dnf install python3-tkinter\n"
            "  Arch:          sudo pacman -S tk\n"
            "  Windows/macOS: Tkinter ships with python.org builds\n\n"
            "Everything works from the command line meanwhile - try "
            "`rocksmith-easy --help`." % e)
    return run(cfg)


# -- wiring -----------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog="rocksmith-easy",
        description="Make Rocksmith 2014 playable for a beginner: gentler "
                    "Guitarcade minigames and a sane Realtone cable level.")
    ap.add_argument("--game-dir", help="path to the Rocksmith2014 folder")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="open the graphical version (the default)")
    sub.add_parser("info", help="show what was found and what is patched")

    gc = sub.add_parser("guitarcade", help="tune a Guitarcade minigame")
    gc.add_argument("game", nargs="?", choices=sorted(games.BY_SLUG),
                    help="which minigame (omit to list status)")
    gc.add_argument("--defaults", action="store_true",
                    help="use the tuned beginner defaults, ignoring saved values")
    gc.add_argument("--stock", action="store_true",
                    help="put the unmodified game back")
    for g in games.ALL:
        grp = gc.add_argument_group("%s (%s)" % (g.name, g.slug))
        for k in g.knobs:
            if any(flag(k.key) == a for a in grp._option_string_actions):
                continue
            grp.add_argument(flag(k.key), type=int if k.integer else float,
                             metavar="N",
                             help="%s [stock %s, default %s]" % (
                                 k.help, games.num(k.stock), games.num(k.default)))

    inp = sub.add_parser("input", help="set the Realtone cable input level")
    inp.add_argument("preset", nargs="?",
                     help="one of: " + ", ".join(
                         p.key.replace("_", "-") for p in audio.PRESETS))
    inp.add_argument("--level", type=int, metavar="PCT",
                     help="set a custom level, 0-100")
    inp.add_argument("--save-as", metavar="PRESET",
                     help="remember the level just set as this preset")
    inp.add_argument("--list", action="store_true", help="show the presets")
    return ap


def main(argv=None):
    ap = build_parser()
    # Shared flags live on the top-level parser; let them appear after the
    # subcommand too, which is what people actually type.
    known, rest = ap.parse_known_args(argv)
    if rest:
        args = ap.parse_args(argv)
    else:
        args = known
    cfg = config.load()
    handlers = {"info": cmd_info, "guitarcade": cmd_guitarcade,
                "input": cmd_input, "gui": cmd_gui, None: cmd_gui}
    return handlers[args.cmd](args, cfg) or 0


if __name__ == "__main__":
    sys.exit(main())
