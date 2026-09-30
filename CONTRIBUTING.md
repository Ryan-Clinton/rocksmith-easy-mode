# Contributing

Bug reports, playtesting notes and ideas for more Guitarcade games are all
welcome. Open an issue.

For a pull request:

- Run `python3 -m unittest discover -s tests -v` first. If Rocksmith and 7-Zip
  are installed, this also patches your real game and puts it back as it was.
- Keep the dependencies to the standard library plus `cryptography`, and the
  code compatible with Python 3.8.
- Every edit to game data should assert how many places it matched (see
  `Game._sub` in `rseasy/games.py`), so an unexpected game build fails loudly.
- Never commit Ubisoft files: no `.psarc` archives, extracted XML or Lua, or
  anything else from the game.

## Releasing

Update `version` in `pyproject.toml` and `rseasy/__init__.py`, and move the
Unreleased notes in `CHANGELOG.md` under the new version number. Then push a
tag:

```sh
git tag v1.0.1 && git push origin v1.0.1
```

The `release` workflow builds the Windows app and attaches it to a draft
release. Check the draft on GitHub, then publish it.
