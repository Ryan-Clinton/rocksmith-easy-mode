# Changelog

## Unreleased

- Patched games never submit scores to the online leaderboards: the
  single score-report call is removed from every patched game. Local high
  scores still work.
- Windows build: a ready-to-run `RocksmithEasyMode.exe`, built by GitHub
  Actions and attached to each release.
- Apply and Restore now say "close Rocksmith first" when the game is
  running, instead of failing with "Access is denied" on Windows. A failed
  swap no longer leaves a `.psarc.new` file behind.
- Sliders snap to their steps, so values read 1.5 rather than 1.3294572,
  and the Saloon target gap reads "5x the stock gap between targets".
- Each slider says which way is which: faster / slower, fewer / more,
  low / high.
- Windows: the cable level is now set automatically, in dB, through the
  Windows Core Audio API, instead of asking you to set it by hand. Rocksmith
  resets it to 17% at every launch, so the app holds the level while it is
  open, putting it back whenever it changes (`input --hold` on the command
  line).
- Cable presets split by pickup type: guitar or bass with passive pickups,
  active pickups, or from an amp's effects loop. Saved levels and old
  command-line names (`bass-direct`, `guitar-direct`) carry over.
- 7-Zip no longer flashes a console window when run from the Windows app.
- Tests run on every push, on Windows and Linux, Python 3.8 to 3.13.

## 1.0.0

- First release.
- Ducks ReDucks: gap between ducks, duck speed, wall-of-doom speed,
  difficulty build-up, rainbow duck speed, kills per rainbow duck, rainbow
  duck bounces and fret range.
- String Skip Saloon: gap between targets and target travel speed.
- Beginner defaults from four rounds of playtesting.
- Real Tone cable level in dB and percent, with presets. Linux sets it
  through ALSA; other platforms get the number to enter by hand.
- Steam install detection, including extra library folders and Flatpak and
  Snap installs.
- Automatic backup of the original archives, and one-click restore.
- Tkinter GUI and a full command line.
