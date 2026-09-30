"""Guitarcade minigame definitions: what can be tuned, and how.

Every adjustable value is a Knob, so the GUI can build itself from these
definitions and the CLI can generate its own flags. A Knob's `stock` is the
value that leaves the game untouched; `default` is the setting that actually
worked for an 8-year-old, arrived at over several rounds of playtesting.

All the magic numbers below are the stock values read back out of the
shipped archives, and every patch asserts it matched the expected number of
sites. If Ubisoft ever shipped a different build, the patch fails loudly
instead of writing something half-applied.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Optional


def num(x):
    """Format a float the way the game's XML does - no trailing zeros."""
    return "%g" % round(float(x), 4)


@dataclass
class Knob:
    key: str
    label: str
    help: str
    stock: float
    default: float
    lo: float
    hi: float
    step: float = 0.5
    integer: bool = False
    explain: Optional[Callable[[float], str]] = None

    def coerce(self, v):
        """Clamp to range and snap to the step, so a dragged slider reads
        5.5 rather than 5.4729361."""
        v = float(v)
        v = self.lo + round((v - self.lo) / self.step) * self.step
        v = max(self.lo, min(self.hi, v))
        return int(round(v)) if self.integer else round(v, 4)

    def hint(self, v):
        """One line of plain English for the current value."""
        v = self.coerce(v)
        if self.explain:
            return self.explain(v)
        if v == self.stock:
            return "stock"
        return "%sx" % num(v)


# ---------------------------------------------------------------------------

class Game:
    """A guitarcade minigame that can be patched."""
    name = slug = psarc = inner = ""
    members = 0
    knobs: list = []

    def defaults(self):
        return {k.key: k.default for k in self.knobs}

    def stock(self):
        return {k.key: k.stock for k in self.knobs}

    def knob(self, key):
        for k in self.knobs:
            if k.key == key:
                return k
        raise KeyError(key)

    def clean(self, values):
        """Coerce a dict of raw values into valid, in-range settings."""
        out = self.defaults()
        for k, v in (values or {}).items():
            try:
                out[k] = self.knob(k).coerce(v)
            except (KeyError, TypeError, ValueError):
                pass
        return self.validate(out)

    def validate(self, v):
        return v

    def apply(self, work, v):
        """Edit the unpacked archive in *work*. Return summary lines."""
        raise NotImplementedError

    # -- helpers shared by the concrete games -------------------------------

    @staticmethod
    def _sub(blob, pattern, repl, expect, what):
        blob, n = re.subn(pattern, repl, blob)
        if n != expect:
            raise RuntimeError("%s: expected %d site(s) in the archive, found %d"
                               % (what, expect, n))
        return blob

    @staticmethod
    def _set_prop(blob, prop, value, expect=1):
        return Game._sub(
            blob,
            (r'(name="%s">\s*<set\s*value=")[^"]*(")' % prop).encode(),
            b"\\g<1>%s\\g<2>" % str(value).encode(),
            expect, prop)


# ---------------------------------------------------------------------------

class Saloon(Game):
    name = "String Skip Saloon"
    slug = "saloon"
    psarc = "stringskipsaloon.psarc"
    inner = "gamexblocks/guitarcade/stringskipsaloon.xblock.7z"
    xblock = "gamexblocks/guitarcade/stringskipsaloon.xblock"
    pool = "behaviors/guitarcade/stringskipsaloon/esetpr_patternpoolsystem.lua"
    members = 166

    STOCK_SPEED = (125.0, 1000.0)
    # The lua clamps the gap to a 0.5s floor, so the multiplier goes outside
    # math.max() - inside it would be swallowed at high difficulty.
    DELAY_LINE = b"local delay = math.max(g_currentTimeDelay * delayModification, 0.5)"

    knobs = [
        Knob("spawn", "Gap between targets",
             "The main knob. Targets arrive this many times further apart, "
             "which buys thinking time for the string change without altering "
             "how the game looks or moves.",
             stock=1.0, default=5.0, lo=1.0, hi=15.0, step=0.5,
             explain=lambda v: ("stock spacing" if v == 1 else
                                "%sx the stock gap between targets" % num(v))),
        Knob("speed", "Target travel speed",
             "How much slower each target crosses the screen, i.e. reaction "
             "time per target. Raise this only if the targets themselves are "
             "still going by too fast.",
             stock=1.0, default=2.0, lo=1.0, hi=8.0, step=0.25,
             explain=lambda v: ("stock speed" if v == 1 else
                                "%sx slower across the screen" % num(v))),
    ]

    def apply(self, work, v):
        xp = work / self.xblock
        blob = xp.read_bytes()
        lo, hi = (x / v["speed"] for x in self.STOCK_SPEED)
        blob = self._sub(
            blob, rb'(name="TUN_Speed">\s*<set\s*value=")[^"]*(")',
            b"\\g<1>%s, %s\\g<2>" % (num(lo).encode(), num(hi).encode()),
            1, "TUN_Speed")
        xp.write_bytes(blob)

        pp = work / self.pool
        lua = pp.read_bytes()
        if lua.count(self.DELAY_LINE) != 1:
            raise RuntimeError(
                "spawn-delay line not found exactly once in %s" % self.pool)
        if v["spawn"] != 1.0:
            lua = lua.replace(
                self.DELAY_LINE,
                self.DELAY_LINE + b" * " + num(v["spawn"]).encode())
        pp.write_bytes(lua)

        return [
            "gap between targets   x%s" % num(v["spawn"]),
            "target speed          %s, %s -> %s, %s  (x%s slower)" % (
                num(self.STOCK_SPEED[0]), num(self.STOCK_SPEED[1]),
                num(lo), num(hi), num(v["speed"])),
        ]


# ---------------------------------------------------------------------------

class Ducks(Game):
    name = "Ducks ReDucks"
    slug = "ducks"
    psarc = "ducksplus.psarc"
    inner = "gamexblocks/guitarcade/ducksplus.xblock.7z"
    xblock = "gamexblocks/guitarcade/ducksplus.xblock"
    curves = "behaviors/guitarcade/ducksplus/esedkp_difficulty.lua"
    manager = "behaviors/guitarcade/ducksplus/esedkp_gamemanager.lua"
    members = 209

    # Every TUN_Speed pair in the xblock, in file order.
    STOCK_SPEEDS = [(4.0, 7.0), (3.0, 6.0), (7.0, 10.0), (0.3, 4.0)]
    SPEED_LABELS = ["duck", "armour duck", "rainbow duck", "wall of doom"]
    RAINBOW_INDEX, WALL_INDEX = 2, 3
    STOCK_SPAWN = 0.1
    STOCK_RAMP_FULL = 95      # seconds to full intensity at level 1
    CURVE_POINTS = 30
    SPAWN_BANDS = 6
    # Rainbow ducks are pinned to the wall's x position every frame by
    # esedkp_rainbowduck.lua, so a slowed wall puts them far away. Patching
    # the spawn line in the game manager is therefore pointless - the lua
    # re-pins it regardless. The line is still checked for, as a guard that
    # this really is the archive we think it is.
    WALL_COUPLING = b"\t\tpos[1] = wallPos[1]"

    knobs = [
        Knob("spawn", "Gap between ducks",
             "How much longer the pause is before the next duck appears.",
             stock=1.0, default=5.0, lo=1.0, hi=15.0, step=0.5,
             explain=lambda v: "a duck every %ss (stock 0.1s)" % num(0.1 * v)),
        Knob("speed", "Duck speed",
             "How much slower ducks fly away from you. Applies to ordinary "
             "and armoured ducks.",
             stock=1.0, default=7.0, lo=1.0, hi=15.0, step=0.5,
             explain=lambda v: ("stock speed" if v == 1 else
                                "%sx slower" % num(v))),
        Knob("wall", "Wall of doom speed",
             "How much slower the wall closes in. Separate from duck speed "
             "because the wall is the thing that ends the run, and it needs "
             "slowing far harder than the ducks do.",
             stock=1.0, default=20.0, lo=1.0, hi=40.0, step=1.0,
             explain=lambda v: ("stock speed" if v == 1 else
                                "%sx slower" % num(v))),
        Knob("ramp", "Difficulty build-up",
             "How much longer the game takes to get hard. Stock level 1 hits "
             "full intensity after 95 seconds.",
             stock=1.0, default=3.0, lo=1.0, hi=8.0, step=0.5,
             explain=lambda v: "full intensity at %ss (stock 95s)" % num(95 * v)),
        Knob("rainbow_speed", "Rainbow duck speed",
             "How much slower rainbow ducks fly. Careful: slowing these makes "
             "them RARER, because only one can be active at a time and the "
             "meter is frozen until it finishes bouncing.",
             stock=1.0, default=3.0, lo=1.0, hi=10.0, step=0.5,
             explain=lambda v: ("stock speed" if v == 1 else
                                "%sx slower - and rarer" % num(v))),
        Knob("rainbow_every", "Kills per rainbow duck",
             "How many ducks must be shot to earn a rainbow duck.",
             stock=3, default=1, lo=1, hi=8, step=1, integer=True,
             explain=lambda v: ("one after every kill" if v == 1 else
                                "one every %d kills (stock 3)" % v)),
        Knob("rainbow_bounces", "Rainbow duck bounces",
             "How many times a rainbow duck bounces before it vanishes. "
             "Fewer bounces means the next one is allowed sooner.",
             stock=2, default=1, lo=1, hi=6, step=1, integer=True,
             explain=lambda v: "%d bounce%s (stock 2)" % (v, "" if v == 1 else "s")),
        Knob("min_fret", "Lowest fret",
             "The lowest fret a duck can appear on.",
             stock=1, default=1, lo=1, hi=20, step=1, integer=True,
             explain=lambda v: "fret %d" % v),
        Knob("max_fret", "Highest fret",
             "The highest fret a duck can appear on. Stock climbs to 20 as "
             "the game gets harder, which means reaching right up the neck.",
             stock=20, default=12, lo=1, hi=22, step=1, integer=True,
             explain=lambda v: "fret %d (stock tops out at 20)" % v),
    ]

    def validate(self, v):
        if v["max_fret"] < v["min_fret"]:
            v["max_fret"] = v["min_fret"]
        return v

    def apply(self, work, v):
        xp = work / self.xblock
        blob = xp.read_bytes()

        # 1. flight speeds - four TUN_Speed pairs, each with its own factor
        factors = []
        for i in range(len(self.STOCK_SPEEDS)):
            if i == self.WALL_INDEX:
                factors.append(v["wall"])
            elif i == self.RAINBOW_INDEX:
                factors.append(v["rainbow_speed"])
            else:
                factors.append(v["speed"])
        seen = [0]

        def repl(m):
            i = seen[0]
            seen[0] += 1
            lo, hi = self.STOCK_SPEEDS[i]
            f = factors[i]
            return b"%s%s, %s%s" % (m.group(1), num(lo / f).encode(),
                                    num(hi / f).encode(), m.group(2))

        blob = self._sub(blob, rb'(name="TUN_Speed">\s*<set\s*value=")[^"]*(")',
                         repl, len(self.STOCK_SPEEDS), "TUN_Speed")

        # 2. pacing and rainbow economy
        blob = self._set_prop(blob, "TimeBetweenSpawns",
                              num(self.STOCK_SPAWN * v["spawn"]))
        blob = self._set_prop(blob, "ShotsPerRainbow", v["rainbow_every"])
        blob = self._set_prop(blob, "TUN_Bounces", v["rainbow_bounces"])

        # 3. fret range - clamp every {intensity, minFret, maxFret} band
        lo_f, hi_f = v["min_fret"], v["max_fret"]

        def cap(m):
            parts = [x.strip() for x in m.group(2).decode().split(",")]
            if len(parts) != 3:
                return m.group(0)
            hi = max(lo_f, min(int(parts[2]), hi_f))
            return b"%s%s, %d, %d%s" % (m.group(1), parts[0].encode(),
                                        lo_f, hi, m.group(3))

        band = re.search(rb'name="TUN_Spawning"\s*>(.*?)</property>', blob, re.S)
        if not band:
            raise RuntimeError("TUN_Spawning block not found in the xblock")
        inner = self._sub(band.group(1), rb'(<set[^>]*value=")([^"]*)(")', cap,
                          self.SPAWN_BANDS, "TUN_Spawning")
        blob = blob[:band.start(1)] + inner + blob[band.end(1):]
        xp.write_bytes(blob)

        # 4. guard: the rainbow/wall coupling line must still be where we think
        mp = work / self.manager
        if mp.read_bytes().count(self.WALL_COUPLING) != 1:
            raise RuntimeError(
                "rainbow/wall coupling line not found exactly once in %s"
                % self.manager)

        # 5. difficulty ramp - stretch every curve's time axis
        cp = work / self.curves
        src = cp.read_bytes()
        if v["ramp"] != 1.0:
            src = self._sub(
                src, rb'\{\s*([0-9.]+)\s*,',
                lambda m: b"{ %s," % num(float(m.group(1)) * v["ramp"]).encode(),
                self.CURVE_POINTS, "difficulty curve")
        cp.write_bytes(src)

        lines = ["gap between ducks     %ss (stock %s)" % (
            num(self.STOCK_SPAWN * v["spawn"]), num(self.STOCK_SPAWN))]
        for i, (label, (lo, hi)) in enumerate(zip(self.SPEED_LABELS,
                                                  self.STOCK_SPEEDS)):
            f = factors[i]
            lines.append("%-21s %s, %s -> %s, %s  (x%s slower)" % (
                label, num(lo), num(hi), num(lo / f), num(hi / f), num(f)))
        lines += [
            "rainbow duck every    %d kill(s) (stock 3)" % v["rainbow_every"],
            "rainbow bounces       %d (stock 2)" % v["rainbow_bounces"],
            "fret range            %d-%d on every band (stock 1-6 .. 5-20)" % (
                lo_f, hi_f),
            "difficulty ramp       x%s slower - full intensity at %ss" % (
                num(v["ramp"]), num(self.STOCK_RAMP_FULL * v["ramp"])),
        ]
        return lines


ALL = [Saloon(), Ducks()]
BY_SLUG = {g.slug: g for g in ALL}
