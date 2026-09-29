"""Apply and undo guitarcade patches.

The pristine archive is copied to <name>.psarc.orig the first time a game is
patched, and every later patch rebuilds from that backup. Re-running with
different numbers therefore never compounds, and "restore" is just a copy.
"""
import shutil
import tempfile
from pathlib import Path

from . import paths, psarc, sevenzip


class PatchError(RuntimeError):
    pass


def live_path(game, game_dir):
    return paths.guitarcade(game_dir) / game.psarc


def backup_path(game, game_dir):
    return live_path(game, game_dir).with_suffix(".psarc.orig")


def status(game, game_dir):
    """'stock', 'patched' or 'missing' for this game's archive."""
    live, orig = live_path(game, game_dir), backup_path(game, game_dir)
    if not live.is_file():
        return "missing"
    if not orig.is_file():
        return "stock"
    try:
        if live.stat().st_size == orig.stat().st_size and \
                live.read_bytes() == orig.read_bytes():
            return "stock"
    except OSError:
        return "missing"
    return "patched"


def apply(game, values, game_dir, log=None):
    """Patch *game* in *game_dir* with *values*. Returns summary lines."""
    log = log or (lambda _m: None)
    sevenzip.require()
    live, orig = live_path(game, game_dir), backup_path(game, game_dir)
    if not live.is_file():
        raise PatchError("%s not found.\nLooked for: %s" % (game.psarc, live))

    values = game.clean(values)

    if not orig.is_file():
        log("Saving a pristine backup of %s" % game.psarc)
        shutil.copy2(live, orig)

    log("Reading %s" % orig.name)
    names, payloads, manifest_md5 = psarc.read_all(orig)
    try:
        idx = names.index(game.inner)
    except ValueError:
        raise PatchError("%s does not contain %s - is this a stock archive?"
                         % (orig.name, game.inner))

    with tempfile.TemporaryDirectory(prefix="rseasy-") as td:
        td = Path(td)
        inner_7z = td / "inner.7z"
        work = td / "work"
        work.mkdir()
        inner_7z.write_bytes(payloads[idx])

        log("Unpacking the inner archive")
        sevenzip.unpack(inner_7z, work)

        log("Editing game data")
        summary = game.apply(work, values)

        members = sevenzip.members_of(work)
        if len(members) != game.members:
            raise PatchError(
                "expected %d files inside %s, found %d - refusing to repack"
                % (game.members, game.inner, len(members)))

        log("Repacking")
        out_7z = td / "out.7z"
        sevenzip.pack(out_7z, work, members)
        payloads[idx] = out_7z.read_bytes()

    log("Rebuilding and verifying %s" % game.psarc)
    psarc.write_verified(live, names, payloads, manifest_md5)
    log("Done")
    return summary


def restore(game, game_dir, log=None):
    """Put the stock archive back. Returns True if anything changed."""
    log = log or (lambda _m: None)
    live, orig = live_path(game, game_dir), backup_path(game, game_dir)
    if not orig.is_file():
        log("No backup for %s - it was never patched" % game.psarc)
        return False
    shutil.copy2(orig, live)
    log("Restored stock %s" % game.psarc)
    return True
