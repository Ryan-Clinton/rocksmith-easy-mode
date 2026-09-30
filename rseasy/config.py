"""Persisted settings: where the game is, knob values, input presets."""
import json
import os
import re
import sys
from pathlib import Path

from . import audio, games

APP = "rocksmith-easy"
# The shell scripts this app replaces kept the cable presets here.
LEGACY_CONF = Path.home() / ".config" / "rocksmith-input.conf"
LEGACY_KEYS = {
    "GUITAR_DIRECT": "guitar_direct",
    "BASS_DIRECT": "bass_direct",
    "GUITAR_LOOP": "guitar_loop",
    "BASS_LOOP": "bass_loop",
}


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP


def config_file():
    return config_dir() / "config.json"


def _migrate_legacy():
    """Pull cable presets out of the old rocksmith-input.conf, if it exists."""
    out = {}
    if not LEGACY_CONF.is_file():
        return out
    try:
        text = LEGACY_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for shell_key, key in LEGACY_KEYS.items():
        m = re.search(r"^%s=(\d+)" % shell_key, text, re.M)
        if m:
            out[key] = int(m.group(1))
    return out


def defaults():
    presets = {p.key: p.default for p in audio.PRESETS}
    presets.update(_migrate_legacy())
    return {
        "game_dir": None,
        "guitarcade": {g.slug: g.defaults() for g in games.ALL},
        "input": presets,
        "persist_level": True,
        # Windows: whether to hold the cable level while Rocksmith runs, and
        # the last level set (None until one is).
        "hold": True,
        "hold_level": None,
    }


def load():
    cfg = defaults()
    try:
        raw = json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    if isinstance(raw.get("game_dir"), str):
        cfg["game_dir"] = raw["game_dir"]
    if isinstance(raw.get("persist_level"), bool):
        cfg["persist_level"] = raw["persist_level"]
    if isinstance(raw.get("hold"), bool):
        cfg["hold"] = raw["hold"]
    hl = raw.get("hold_level")
    if isinstance(hl, (int, float)) and not isinstance(hl, bool) and 0 <= hl <= 100:
        cfg["hold_level"] = int(round(hl))
    for g in games.ALL:
        saved = (raw.get("guitarcade") or {}).get(g.slug)
        if isinstance(saved, dict):
            cfg["guitarcade"][g.slug] = g.clean(saved)
    for p in audio.PRESETS:
        v = (raw.get("input") or {}).get(p.key)
        if isinstance(v, (int, float)) and 0 <= v <= 100:
            cfg["input"][p.key] = int(round(v))
    return cfg


def save(cfg):
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = config_file().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, config_file())
    return config_file()
