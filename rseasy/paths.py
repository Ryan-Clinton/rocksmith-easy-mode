"""Locate the Rocksmith 2014 install on Windows and Linux."""
import os
import re
import sys
from pathlib import Path

APPID = "221680"
FOLDER = "Rocksmith2014"


def _steam_roots():
    """Candidate Steam root directories, most likely first."""
    roots = []
    if sys.platform == "win32":
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                roots.append(Path(base) / "Steam")
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
    else:
        home = Path.home()
        roots += [
            home / ".steam/debian-installation",   # Ubuntu/Debian steam package
            home / ".local/share/Steam",           # Valve's own installer
            home / ".steam/steam",
            home / ".steam/root",
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",  # flatpak
            home / "snap/steam/common/.local/share/Steam",                 # snap
        ]
    return roots


def _library_dirs(root):
    """Every steamapps dir reachable from a Steam root, via libraryfolders.vdf."""
    out = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        # Both the old flat form and the newer nested form quote the path.
        for path in re.findall(r'"path"\s*"([^"]+)"', text):
            out.append(Path(path.replace("\\\\", "\\")) / "steamapps")
    return out


def find_game(extra=None):
    """Return the Rocksmith2014 directory, or None.

    *extra* is checked first, so a saved override always wins.
    """
    if extra:
        p = Path(extra).expanduser()
        if is_game_dir(p):
            return p
    seen = set()
    for root in _steam_roots():
        if not root.is_dir():
            continue
        for apps in _library_dirs(root):
            cand = apps / "common" / FOLDER
            if cand in seen:
                continue
            seen.add(cand)
            if is_game_dir(cand):
                return cand
    return None


def is_game_dir(p):
    """True if *p* looks like a Rocksmith 2014 install we can patch."""
    p = Path(p)
    return (p / "guitarcade").is_dir()


def guitarcade(game_dir):
    return Path(game_dir) / "guitarcade"


def describe_search():
    """Human-readable list of where find_game() looked, for error messages."""
    lines = []
    for root in _steam_roots():
        mark = "found" if root.is_dir() else "not there"
        lines.append("  %-60s (%s)" % (root, mark))
    return "\n".join(lines)
