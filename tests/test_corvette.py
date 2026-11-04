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


def has_game():
    try:
        from nms_save import gamepath
        return bool(gamepath.require())
    except Exception:
        return False


HAB = "MODELS/COMMON/SPACECRAFT/BIGGS/MODULES/PARTS/HAB_D_1X2_CORE.SCENE.MBIN"


@unittest.skipUnless(has_game(), "needs No Man's Sky installed")
class Modelling(unittest.TestCase):
    def setUp(self):
        from nms_procgen import model3d
        self.m = model3d

    def test_a_module_is_drawn_where_its_transform_puts_it(self):
        here = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1])])
        there = self.m.corvette_model([(HAB, [10, 12, -4], [0, 1, 0], [0, 0, 1])])
        for axis, shift in enumerate((10, 12, -4)):
            self.assertAlmostEqual(there["bounds"][0][axis] - here["bounds"][0][axis], shift, places=3)

    def test_turning_a_module_turns_its_geometry(self):
        flat = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1])])["bounds"]
        yawed = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [1, 0, 0])])["bounds"]
        self.assertAlmostEqual(yawed[1][0], flat[1][2], places=3, msg="a quarter turn swaps x and z")
        self.assertAlmostEqual(yawed[1][2], flat[1][0], places=3)
        self.assertAlmostEqual(yawed[1][1], flat[1][1], places=3, msg="height is untouched")

    def test_a_module_we_have_no_scene_for_is_left_out(self):
        got = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1]),
                                     ("MODELS/COMMON/SPACECRAFT/BIGGS/NOPE.SCENE.MBIN",
                                      [0, 0, 0], [0, 1, 0], [0, 0, 1])])
        self.assertTrue(got["groups"], "the hab still drew")

    def test_a_scene_with_no_procedural_parts_still_walks(self):
        """_scene_meshes used to trip over an undefined name before it drew anything."""
        self.assertTrue(self.m._scene_meshes(HAB), "the hab's meshes came out")


@unittest.skipUnless(has_game(), "needs No Man's Sky installed")
class ModuleScenes(unittest.TestCase):
    def setUp(self):
        from nms_procgen import corvette_parts
        self.cp = corvette_parts

    def test_the_hull_is_not_looked_up_as_a_module(self):
        self.assertEqual(self.cp.scenes_for("^U_PARAGON"), [self.cp.HULL])

    def test_a_wing_draws_as_a_mirrored_pair(self):
        got = self.cp.scenes_for("^B_WNG_A")
        self.assertEqual(len(got), 2, "left and right: %s" % got)
        self.assertTrue(any(s.endswith("_L.SCENE.MBIN") for s in got))
        self.assertTrue(any(s.endswith("_R.SCENE.MBIN") for s in got))

    def test_a_family_whose_model_is_named_differently_still_resolves(self):
        """The turret is drawn by a gun and the gear by a leg, which no rule would guess."""
        self.assertTrue(any("GUN_A" in s for s in self.cp.scenes_for("^B_TUR_A")))
        self.assertTrue(any("LANDINGGEAR_LEG_A" in s for s in self.cp.scenes_for("^B_LND_A")))

    def test_an_id_we_do_not_know_draws_nothing(self):
        self.assertEqual(self.cp.scenes_for("^B_NOPE_Z"), [])
        self.assertEqual(self.cp.scenes_for("^NONSENSE"), [])

    def test_the_catalogue_carries_the_build_menu_gates(self):
        hab = self.cp.catalogue()["B_HAB_D"]
        self.assertFalse(hab["rotatable"], "the menu refuses to turn a hab")
        self.assertTrue(hab["placement"].endswith(".SCENE.MBIN"))
