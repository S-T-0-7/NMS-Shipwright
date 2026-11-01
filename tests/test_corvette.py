"""Corvette layouts: modules are free transforms, and a slot is a pair of files."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nms_save import corvette


def a_save():
    """A save holding one planet base and one corvette carrying just its hull."""
    return {"BaseContext": {"PlayerStateData": {"PersistentPlayerBases": [
        {"BaseType": {"PersistentBaseTypes": "HomePlanetBase"}, "Objects": []},
        {"BaseType": {"PersistentBaseTypes": "PlayerShipBase"}, "Objects": [
            {"Timestamp": 10, "ObjectID": "^U_PARAGON", "UserData": 4294967296000000,
             "Position": [0.0, 0.0, 0.0], "Up": [0.0, 1.0, 0.0], "At": [0.0, 0.0, 1.0]}]}]}}}


class Layouts(unittest.TestCase):
    def setUp(self):
        self.save = a_save()
        found = corvette.layouts(self.save)
        self.assertEqual(len(found), 1, "only the ship base counts as a corvette")
        self.entry = found[0]

    def test_a_module_can_go_anywhere_at_any_angle(self):
        obj = corvette.place(self.entry, "B_TUR_A", (10.5, 9.0, 27.0), yaw=30)
        self.assertEqual(obj["ObjectID"], "^B_TUR_A", "the caret is added for us")
        self.assertEqual(obj["Position"], [10.5, 9.0, 27.0])
        self.assertAlmostEqual(obj["At"][0], 0.5, places=6)
        self.assertEqual(obj["Timestamp"], 11, "placed after everything already there")
        self.assertEqual(obj["UserData"], corvette.MODULE_USER_DATA)
        self.assertEqual(len(corvette.modules(self.entry)), 2)

    def test_a_placed_module_can_be_moved_and_turned_again(self):
        obj = corvette.place(self.entry, "^B_HAB_D", (0, 12, 0))
        corvette.move(obj, (1.25, -3.5, 0.75), yaw=90)
        self.assertEqual(obj["Position"], [1.25, -3.5, 0.75])
        self.assertAlmostEqual(obj["At"][0], 1.0, places=6)
        self.assertAlmostEqual(obj["At"][2], 0.0, places=6)

    def test_the_hull_stays_put(self):
        with self.assertRaises(ValueError):
            corvette.remove(self.entry, corvette.modules(self.entry)[0])
        spare = corvette.place(self.entry, "B_GEN_6", (0, 6, 0))
        corvette.remove(self.entry, spare)
        self.assertEqual(len(corvette.modules(self.entry)), 1, "only the hull is left")

    def test_a_save_with_no_corvette_yields_nothing(self):
        empty = {"BaseContext": {"PlayerStateData": {"PersistentPlayerBases": []}}}
        self.assertEqual(corvette.layouts(empty), [])
        self.assertEqual(corvette.layouts({}), [], "a save we cannot read is not a crash")


class Halves(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_both_halves_of_a_slot_are_found(self):
        for n in ("save.hg", "save2.hg", "save3.hg", "save4.hg"):
            open(os.path.join(self.d, n), "wb").close()
        for name, want in (("save3.hg", "save4.hg"), ("save4.hg", "save3.hg"),
                           ("save.hg", "save2.hg"), ("save2.hg", "save.hg")):
            got = [os.path.basename(p) for p in corvette.halves(os.path.join(self.d, name))]
            self.assertEqual(got, [name, want], "a slot is a pair, starting from %s" % name)

    def test_a_missing_half_is_not_invented(self):
        p = os.path.join(self.d, "save5.hg")
        open(p, "wb").close()
        self.assertEqual(corvette.halves(p), [p], "save6.hg does not exist yet")


if __name__ == "__main__":
    unittest.main()
