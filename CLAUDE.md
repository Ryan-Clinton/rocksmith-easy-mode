# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python 3.8+ app (Tkinter GUI + argparse CLI) that patches Rocksmith 2014's Guitarcade minigame archives to slow them down for beginners, and sets the Real Tone cable's ALSA capture level. Only third-party dependency is `cryptography`; 7-Zip must be on the system. Keep it that way: stdlib + `cryptography` only, 3.8-compatible syntax.

## Commands

```sh
./rocksmith-easy                     # run from checkout (GUI by default; no install needed)
./rocksmith-easy info                # headless: what was found / what is patched
./rocksmith-easy guitarcade ducks --defaults
python3 -m unittest discover -s tests -v                         # all tests
python3 -m unittest tests.test_rseasy.TestKnobs.test_clamped_to_range -v   # single test
```

There is no linter. `pip install .` installs the `rocksmith-easy` entry point (`rseasy.cli:main`).

CI (`.github/workflows/tests.yml`) runs the tests on ubuntu-22.04 (the newest runner that still has 3.8) and Windows, Python 3.8–3.13. Pushing a `v*` tag runs `release.yml`, which uses PyInstaller (`--windowed --onedir`, entry `rocksmith-easy.pyw`) to build `RocksmithEasyMode.exe` and attaches the zip to a **draft** release. The frozen app has no console, so subprocesses must not rely on inherited stdio handles (see `sevenzip.QUIET`). Release steps are in CONTRIBUTING.md.

**Caution:** `TestLivePatch` runs automatically when a Rocksmith install and 7-Zip are found, and it patches the *real* game files (then restores the prior state in `tearDown`). Run the other test classes explicitly if you don't want that.

## Architecture

Everything lives in the `rseasy/` package. The data flow for a patch:

`cli.py` / `gui.py` → `patcher.apply(game, values, game_dir)` → `psarc.read_all` (decrypt TOC, inflate zlib blocks) → `sevenzip.unpack` the inner `.xblock.7z` → `Game.apply(work, values)` edits XML/Lua in place → assert member count → `sevenzip.pack` from an explicit file list → `psarc.write_verified` (rebuild, read back, compare every payload, then replace the live file).

- **`games.py` is the single source of truth for tunables.** Each minigame is a `Game` subclass with a list of `Knob`s (key, label, help, stock, default, lo, hi, step, integer, explain). The GUI builds its sliders and the CLI generates its `--flags` from these definitions, so adding a knob means adding it to `knobs` and handling it in that game's `apply()` — no UI code changes. Register new games in `games.ALL`.
- **Edits must assert their site count.** Use `Game._sub` / `Game._set_prop` with the expected number of matches so a different game build fails loudly instead of half-patching. `Game.members` (166 Saloon, 209 Ducks) is asserted before repacking.
- **Patches always rebuild from the `.psarc.orig` backup**, never from the live file, so repeated patches don't compound and `restore` is just a copy. `patcher.status()` returns `stock` / `patched` / `missing`.
- **Windows locks the game's archives while Rocksmith runs**, so `apply`/`restore` refuse up front if `patcher.game_running()` (tasklist on Windows, `/proc` cmdline scan for Proton on Linux), and turn a `PermissionError` on the final swap into the same "close Rocksmith first" `PatchError`.
- **The inner 7z must contain no directory entries** (they hang the game's loading screen) — `sevenzip.pack` takes an explicit member list; never add `.`.
- **`audio.py`**: cable gain spans −8 to +10 dB over 38 steps (amixer 0..37), so unity ≈ 44%, not 50%. `AlsaBackend` drives `amixer`/`alsactl` on Linux; `ManualBackend` just reports the number elsewhere. Presets live in `audio.PRESETS`.
- **Windows cable level**: `wincoreaudio.py` is ctypes COM (IMMDeviceEnumerator → IAudioEndpointVolume, in dB). Rocksmith resets the level to 17% (−4.5 dB) at every launch, so `audio.LevelHolder` re-applies it each second while the app is open (same approach as RSMods' in-game override, without a DLL).
- **`config.py`**: JSON at `~/.config/rocksmith-easy/config.json` (APPDATA on Windows), with one-time migration from the legacy `~/.config/rocksmith-input.conf`. `load()` must survive a corrupt file.
- **`paths.py`**: Steam library discovery (registry on Windows; native, Flatpak, Snap on Linux; `libraryfolders.vdf`).
- **`gui.py`**: long jobs run on a worker thread reporting through a queue; each panel must degrade gracefully when the game, 7-Zip, or cable is missing.

## Invariants worth preserving

- Knob `default` values are playtested (see README tables) and pinned by `TestKnobs.test_defaults_are_the_playtested_ones`; don't change them casually.
- `Ducks.WALL_COUPLING` must be found exactly once in `esedkp_gamemanager.lua`. That check only confirms the archive is the one expected. Editing that spawn line does nothing, because `esedkp_rainbowduck.lua` re-pins rainbow ducks to the wall every frame, so slowing the wall moves where they spawn. Slowing rainbow ducks also makes them *rarer*. See the README section "The defaults".
