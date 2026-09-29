"""Tests that need no Rocksmith install, plus a live round-trip if one is found.

    python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rseasy import audio, config, games, paths, patcher, psarc, sevenzip  # noqa: E402


class TestPsarc(unittest.TestCase):
    """build() and read_all() must be exact inverses - a patch rides on it."""

    def test_round_trip(self):
        names = ["a/one.txt", "b/two.bin", "empty.dat"]
        payloads = [b"hello" * 5000, bytes(range(256)) * 400, b""]
        md5 = bytes(range(16))
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.psarc"
            psarc.write_verified(p, names, payloads, md5)
            got_names, got_payloads, got_md5 = psarc.read_all(p)
        self.assertEqual(got_names, names)
        self.assertEqual(got_payloads, payloads)
        self.assertEqual(got_md5, md5)

    def test_multi_block_payload(self):
        """A payload larger than one 64k block must survive intact."""
        names = ["big.bin"]
        payloads = [os.urandom(psarc.BLOCK * 3 + 17)]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.psarc"
            psarc.write_verified(p, names, payloads, bytes(16))
            self.assertEqual(psarc.read_all(p)[1], payloads)

    def test_rejects_non_psarc(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nope.psarc"
            p.write_bytes(b"NOTAPSARC" + bytes(64))
            with self.assertRaises(ValueError):
                psarc.read(p)


class TestKnobs(unittest.TestCase):
    def test_clamped_to_range(self):
        k = games.BY_SLUG["ducks"].knob("max_fret")
        self.assertEqual(k.coerce(999), k.hi)
        self.assertEqual(k.coerce(-5), k.lo)

    def test_integer_knobs_stay_integers(self):
        k = games.BY_SLUG["ducks"].knob("rainbow_every")
        self.assertIsInstance(k.coerce(2.6), int)
        self.assertEqual(k.coerce(2.6), 3)

    def test_max_fret_cannot_sit_below_min(self):
        g = games.BY_SLUG["ducks"]
        v = g.clean({"min_fret": 9, "max_fret": 3})
        self.assertEqual(v["max_fret"], 9)

    def test_clean_ignores_junk(self):
        g = games.BY_SLUG["saloon"]
        v = g.clean({"spawn": "nonsense", "bogus": 1})
        self.assertEqual(v["spawn"], g.knob("spawn").default)
        self.assertNotIn("bogus", v)

    def test_defaults_are_the_playtested_ones(self):
        """These are the values that actually worked - guard against drift."""
        self.assertEqual(games.BY_SLUG["saloon"].defaults(),
                         {"spawn": 5.0, "speed": 2.0})
        self.assertEqual(games.BY_SLUG["ducks"].defaults(), {
            "spawn": 5.0, "speed": 7.0, "wall": 20.0, "ramp": 3.0,
            "rainbow_speed": 3.0, "rainbow_every": 1, "rainbow_bounces": 1,
            "min_fret": 1, "max_fret": 12,
        })

    def test_every_knob_has_a_hint(self):
        for g in games.ALL:
            for k in g.knobs:
                self.assertTrue(k.hint(k.default))
                self.assertTrue(k.hint(k.stock))


class TestAudio(unittest.TestCase):
    def test_documented_db_values(self):
        """The numbers the README and the old shell scripts quote."""
        for pct, db in ((0, -8.0), (22, -4.1), (32, -2.2), (81, 6.6), (100, 10.0)):
            self.assertAlmostEqual(audio.pct_to_db(pct), db, places=1,
                                   msg="%d%%" % pct)

    def test_unity_is_not_fifty_percent(self):
        self.assertEqual(audio.UNITY_PCT, 44)
        self.assertIn("unity", audio.describe(44))
        self.assertIn("boost", audio.describe(50))
        self.assertIn("cut", audio.describe(32))

    def test_steps_stay_in_range(self):
        for pct in (-50, 0, 50, 100, 500):
            self.assertTrue(0 <= audio.pct_to_step(pct) <= audio.STEPS)


class TestConfig(unittest.TestCase):
    def test_legacy_conf_is_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / "rocksmith-input.conf"
            legacy.write_text("GUITAR_DIRECT=100\nBASS_DIRECT=32\n")
            real = config.LEGACY_CONF
            try:
                config.LEGACY_CONF = legacy
                self.assertEqual(config.defaults()["input"]["bass_direct"], 32)
            finally:
                config.LEGACY_CONF = real

    def test_load_survives_a_corrupt_file(self):
        real = config.config_file
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "config.json"
            bad.write_text("{ not json at all")
            try:
                config.config_file = lambda: bad
                self.assertEqual(config.load()["guitarcade"]["saloon"],
                                 games.BY_SLUG["saloon"].defaults())
            finally:
                config.config_file = real


GAME_DIR = paths.find_game(None)


@unittest.skipIf(GAME_DIR is None, "no Rocksmith 2014 install found")
@unittest.skipIf(sevenzip.find() is None, "7-Zip not installed")
class TestLivePatch(unittest.TestCase):
    """Patch the real game, read the values back, then put it as it was."""

    def setUp(self):
        self.before = {g.slug: patcher.status(g, GAME_DIR) for g in games.ALL}

    def tearDown(self):
        for g in games.ALL:
            if self.before[g.slug] == "patched":
                patcher.apply(g, config.load()["guitarcade"][g.slug], GAME_DIR)
            elif self.before[g.slug] == "stock":
                patcher.restore(g, GAME_DIR)

    def test_values_reach_the_archive(self):
        import re
        g = games.BY_SLUG["saloon"]
        patcher.apply(g, {"spawn": 4, "speed": 2}, GAME_DIR)
        self.assertEqual(patcher.status(g, GAME_DIR), "patched")

        names, payloads, _ = psarc.read_all(patcher.live_path(g, GAME_DIR))
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "i.7z").write_bytes(payloads[names.index(g.inner)])
            sevenzip.unpack(td / "i.7z", td / "w")
            xb = (td / "w" / g.xblock).read_text(errors="replace")
            lua = (td / "w" / g.pool).read_text(errors="replace")
        # speed 2 halves the stock 125, 1000
        self.assertIn("62.5, 500", xb)
        self.assertIn("0.5) * 4", lua)

    def test_restore_gives_back_the_stock_bytes(self):
        g = games.BY_SLUG["saloon"]
        patcher.apply(g, g.defaults(), GAME_DIR)
        patcher.restore(g, GAME_DIR)
        self.assertEqual(patcher.status(g, GAME_DIR), "stock")
        live = patcher.live_path(g, GAME_DIR).read_bytes()
        orig = patcher.backup_path(g, GAME_DIR).read_bytes()
        self.assertEqual(live, orig)


if __name__ == "__main__":
    unittest.main(verbosity=2)
