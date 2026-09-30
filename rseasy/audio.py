"""Realtone cable input level.

The cable has one onboard capture gain control spanning -8 dB to +10 dB in
38 steps. That 18 dB span is why percentages mislead: UNITY IS ABOUT 44%,
not 50%, and anything above that is boost. An active-pickup bass set to 81%
is being boosted by 6.6 dB, which is what makes Rocksmith's calibration
complain that it is too loud.

On Linux the cable is deliberately hidden from PipeWire (wine needs it as raw
ALSA), so `amixer` is the only place the level can be changed short of the
instrument's volume knob. Windows exposes the same control as the recording
device's Level slider; there the app sets it through the Core Audio API
(see wincoreaudio.py), in dB, since Windows' own percentage is a different
scale.
"""
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

CARD_NAME = "Rocksmith USB Guitar Adapter"
CONTROL = "Mic"
STEPS = 37                  # amixer range is 0..37
DB_MIN, DB_MAX = -8.0, 10.0
UNITY_PCT = round((0 - DB_MIN) / (DB_MAX - DB_MIN) * 100)   # ~44%
# The control is 38 discrete steps, so exact 0 dB is not reachable - step 16
# is simply the closest one to it. Boost/cut is decided by which side of that
# step a value lands on, which is what the hardware actually does.
UNITY_STEP = int(round(STEPS * (0 - DB_MIN) / (DB_MAX - DB_MIN)))


@dataclass
class Preset:
    key: str
    label: str
    default: int
    help: str


PRESETS = [
    Preset("guitar_direct", "Guitar - straight into the cable", 100,
           "Passive pickups want the full +10 dB boost."),
    Preset("bass_direct", "Bass - straight into the cable", 32,
           "An active bass needs a small cut, not a boost. 32% is -2.2 dB; "
           "22% (-4.1 dB) read a shade low and 81% is what makes calibration "
           "say it is too loud."),
    Preset("guitar_loop", "Guitar - from the amp's effects loop", 35,
           "UNTESTED STARTING GUESS. A send is line level, far hotter than "
           "the cable's instrument input, so this starts low."),
    Preset("bass_loop", "Bass - from the amp's effects loop", 30,
           "UNTESTED STARTING GUESS. If even 0% still reads too loud the "
           "cable cannot cut enough on its own - turn the amp's send down or "
           "use a -10 dB loop setting."),
]
BY_KEY = {p.key: p for p in PRESETS}


def pct_to_step(pct):
    return max(0, min(STEPS, int(round(float(pct) / 100 * STEPS))))


def step_to_db(step):
    return DB_MIN + (float(step) / STEPS) * (DB_MAX - DB_MIN)


def pct_to_db(pct):
    return step_to_db(pct_to_step(pct))


def describe(pct):
    """'32%  (-2.2 dB, cut)' - the label that belongs next to a slider."""
    step = pct_to_step(pct)
    db = step_to_db(step)
    if step > UNITY_STEP:
        tag = "boost"
    elif step < UNITY_STEP:
        tag = "cut"
    else:
        tag = "unity"
    return "%d%%  (%+.1f dB, %s)" % (int(round(pct)), db, tag)


class NotAvailable(RuntimeError):
    pass


class Backend:
    """Abstract input-level backend."""
    name = "none"
    can_set = False

    def cable_present(self):
        return False

    def get_percent(self):
        return None

    def set_percent(self, pct):
        raise NotAvailable(self.why())

    def persist(self):
        return None

    def why(self):
        return "Changing the input level is not supported on this platform."


class AlsaBackend(Backend):
    name = "alsa"
    can_set = True

    def _card(self):
        try:
            with open("/proc/asound/cards", encoding="utf-8",
                      errors="replace") as fh:
                for line in fh:
                    if CARD_NAME in line:
                        return line.split()[0]
        except OSError:
            pass
        return None

    def cable_present(self):
        return self._card() is not None

    def _sget(self, card):
        return subprocess.run(["amixer", "-c", card, "sget", CONTROL],
                              capture_output=True, text=True).stdout

    def get_percent(self):
        card = self._card()
        if card is None:
            return None
        m = re.search(r"\[(\d+)%\]", self._sget(card))
        return int(m.group(1)) if m else None

    def set_percent(self, pct):
        card = self._card()
        if card is None:
            raise NotAvailable("The Realtone cable is not plugged in.")
        step = pct_to_step(pct)
        r = subprocess.run(["amixer", "-c", card, "sset", CONTROL, str(step)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise NotAvailable("amixer failed: %s" % r.stderr.strip())
        return self.get_percent()

    def persist(self):
        """Ask alsactl to store the level so it survives replug and reboot.

        Returns a message, or None if it is not possible. Without this the
        cable comes back at +10 dB every time it is unplugged.
        """
        card = self._card()
        if card is None:
            return None
        r = subprocess.run(["sudo", "-n", "alsactl", "store", card],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "Saved - survives replug and reboot."
        return ("Not saved permanently (needs sudo). To make it stick:\n"
                "    sudo alsactl store %s" % card)

    def why(self):
        return "The Realtone cable is not plugged in."


class ManualBackend(Backend):
    """macOS, or Windows when its audio API can't be reached: report the
    number and let the user set it."""
    name = "manual"
    can_set = False

    def why(self):
        if sys.platform == "win32":
            return WINDOWS_BY_HAND
        return ("Setting the level automatically is only implemented for "
                "Linux and Windows. Use your system's recording-level control "
                "and dial in the dB value shown above.")


WINDOWS_BY_HAND = (
    "To set it by hand instead: Settings > System > Sound > More sound "
    "settings > Recording > Rocksmith USB Guitar Adapter > Properties > "
    "Levels, then right-click the slider to switch it to dB and dial in the "
    "dB value shown above. Windows' own percentage is not the same scale.")


class WindowsBackend(Backend):
    """Sets the cable's capture gain through the Windows Core Audio API.

    This is the same control as the Levels slider in the recording device's
    properties, reached through IAudioEndpointVolume with plain ctypes COM
    calls, so there is still nothing to install. The level is set in dB,
    because Windows' own slider percentage is not linear in dB and does not
    match the 38 hardware steps. Windows remembers the level per device, so
    there is nothing to persist.
    """
    name = "windows"
    can_set = True

    def _endpoint(self):
        from . import wincoreaudio
        return wincoreaudio.find_capture_volume("rocksmith")

    def cable_present(self):
        try:
            with self._endpoint() as vol:
                return vol is not None
        except OSError:
            return False

    def get_percent(self):
        try:
            with self._endpoint() as vol:
                if vol is None:
                    return None
                db = vol.get_db()
        except OSError:
            return None
        step = round((db - DB_MIN) / (DB_MAX - DB_MIN) * STEPS)
        return int(round(max(0, min(STEPS, step)) / STEPS * 100))

    def set_percent(self, pct):
        try:
            with self._endpoint() as vol:
                if vol is None:
                    raise NotAvailable("The Realtone cable is not plugged in.")
                lo, hi = vol.get_range()
                vol.set_db(max(lo, min(hi, pct_to_db(pct))))
        except OSError as e:
            raise NotAvailable("Windows would not change the level (%s).\n\n%s"
                               % (e, WINDOWS_BY_HAND))
        return self.get_percent()

    def why(self):
        return "The Realtone cable is not plugged in."


def backend():
    if sys.platform.startswith("linux") and shutil.which("amixer"):
        return AlsaBackend()
    if sys.platform == "win32":
        return WindowsBackend()
    return ManualBackend()
