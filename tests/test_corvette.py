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

    def test_a_whole_build_can_replace_the_modules(self):
        """What the builder posts back: the list is written as given, the hull carried over."""
        corvette.place(self.entry, "B_HAB_D", (0, 3, 9))
        corvette.replace(self.entry, [("B_TUR_A", (1.0, 2.0, 3.0), (0, 1, 0), (1, 0, 0)),
                                      ("^B_LND_A", (0.0, 0.0, 6.0), (0, 1, 0), (0, 0, 1))])
        got = corvette.modules(self.entry)
        self.assertEqual([o["ObjectID"] for o in got], ["^U_PARAGON", "^B_TUR_A", "^B_LND_A"])
        self.assertEqual(got[0]["UserData"], 4294967296000000, "the hull keeps its own user data")
        self.assertEqual(got[1]["Position"], [1.0, 2.0, 3.0])
        self.assertEqual(got[1]["At"], [1.0, 0.0, 0.0], "no snapping, no squaring up")

    def test_a_module_keeps_the_build_time_it_came_with(self):
        """The game maintains these, so a part that was already on the ship keeps its own."""
        corvette.replace(self.entry, [("B_TUR_A", (0, 0, 0), (0, 1, 0), (0, 0, 1), 1793464163),
                                      ("B_LND_A", (0, 0, 6), (0, 1, 0), (0, 0, 1))])
        got = corvette.modules(self.entry)
        self.assertEqual(got[1]["Timestamp"], 1793464163, "carried through untouched")
        self.assertGreater(got[2]["Timestamp"], 10, "a part with none gets a fresh one")

    def test_a_build_cannot_smuggle_in_a_second_hull(self):
        corvette.replace(self.entry, [("^U_PARAGON", (5, 5, 5), (0, 1, 0), (0, 0, 1)),
                                      ("B_TUR_A", (0, 0, 0), (0, 1, 0), (0, 0, 1))])
        ids = [o["ObjectID"] for o in corvette.modules(self.entry)]
        self.assertEqual(ids.count("^U_PARAGON"), 1)
        self.assertEqual(corvette.modules(self.entry)[0]["Position"], [0.0, 0.0, 0.0])

    def test_replacing_with_nothing_leaves_a_bare_hull(self):
        corvette.place(self.entry, "B_HAB_D", (0, 3, 9))
        corvette.replace(self.entry, [])
        self.assertEqual([o["ObjectID"] for o in corvette.modules(self.entry)], ["^U_PARAGON"])

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

    def test_the_hull_draws_nothing(self):
        """It anchors the base rather than being built into it, and the scene named after it is
        the build station's hologram, which would show as a blue ship inside the real one."""
        self.assertEqual(self.cp.scenes_for("^U_PARAGON"), [])

    def test_a_family_whose_model_is_named_differently_still_resolves(self):
        """The turret is drawn by a gun and the gear by a leg, which no rule would guess."""
        self.assertTrue(any("GUN_A" in s for s in self.cp.scenes_for("^B_TUR_A")))
        self.assertTrue(any("LANDINGGEAR_LEG_A" in s for s in self.cp.scenes_for("^B_LND_A")))

    def test_an_id_we_do_not_know_draws_nothing(self):
        self.assertEqual(self.cp.scenes_for("^B_NOPE_Z"), [])
        self.assertEqual(self.cp.scenes_for("^NONSENSE"), [])

    def test_the_style_field_picks_the_model_within_a_part(self):
        """One part holds every thruster; the module's style says which one, J being ZENGINEJ."""
        self.assertTrue(any("ZENGINEJ" in s for s in self.cp.scenes_for("^B_TRU_J")))
        self.assertTrue(any("ZENGINEA" in s for s in self.cp.scenes_for("^B_TRU_A")))

    def test_the_shield_generator_is_solid_geometry(self):
        """Its path says SHIELD, which the effect-shell filter used to throw away."""
        from nms_procgen import model3d
        scenes = self.cp.scenes_for("^B_SHL_A")
        self.assertTrue(scenes)
        self.assertTrue([m for m in model3d._scene_meshes(scenes[0]) if m[0]])

    def test_interior_walls_are_left_out(self):
        """Which wall is drawn depends on the hab and the direction, neither of which is recorded."""
        self.assertEqual(self.cp.scenes_for("^B_WALL_CARG0"), [])

    def test_every_other_module_in_the_build_menu_draws(self):
        from nms_procgen import model3d
        missing = []
        for part, row in self.cp.catalogue().items():
            if not row["in_menu"] or part.startswith(("B_WALL_", "B_STAIRS")) or part == "B_LND_D":
                continue
            drawn = [m for s in self.cp.scenes_for(part) for m in model3d._scene_meshes(s) if m[0]]
            if not drawn:
                missing.append(part)
        self.assertEqual(missing, [])

    def test_a_module_offers_the_sockets_the_game_joins_it_by(self):
        """A thruster bolts on by its BlockS socket, and a hab offers the other half of it."""
        thruster = {(k, io) for k, io, _ in self.cp.snaps_for("B_TRU_A")}
        self.assertIn(("BlockS", "in"), thruster)
        self.assertIn(("RoomN", "out"), thruster)
        self.assertIn(("BlockS", "out"), {(k, io) for k, io, _ in self.cp.snaps_for("B_HAB_D")})

    def test_socket_frames_are_rigid(self):
        """Laying one socket onto another only works if they carry no scale or shear."""
        import numpy as np
        for part in ("B_HAB_D", "B_TUR_A", "B_LND_A"):
            got = self.cp.snaps_for(part)
            self.assertTrue(got, part)
            for kind, io, flat in got:
                r = np.array(flat, float).reshape(4, 4).T[:3, :3]
                self.assertTrue(np.allclose(r @ r.T, np.eye(3), atol=1e-4), f"{part} {kind} {io}")
                self.assertAlmostEqual(float(np.linalg.det(r)), 1.0, places=4)

    def test_the_hull_has_no_sockets(self):
        self.assertEqual(self.cp.snaps_for("U_PARAGON"), ())

    def test_a_handed_module_draws_one_part_and_the_right_one(self):
        """Wings and the lettered connectors come in pairs, and the game keeps a module per side:
        B_WNG_A is the left wing, B_WNG_A_R the right, B_WNG_P_T and _B the top and bottom.

        Taking the side from the family drew the whole family instead, which stood a mirrored
        twin next to every left-hand part and left every right-hand one drawing nothing."""
        for module, part in (("B_WNG_A", "WING_A_L"), ("B_WNG_A_R", "WING_A_R"),
                             ("B_WNG_O_0", "WING_O_0_L"), ("B_WNG_O_2_R", "WING_O_2_R"),
                             ("B_WNG_P_T", "WING_P_T"), ("B_WNG_Y_B", "WING_Y_B"),
                             ("B_CON_L_3", "CONNECTOR_1X1_L_3"),
                             ("B_CON_R_3", "CONNECTOR_1X1_R_3")):
            got = self.cp.scenes_for(module)
            self.assertEqual(len(got), 1, f"{module} draws {len(got)} parts, not one")
            self.assertTrue(got[0].upper().endswith(part + ".SCENE.MBIN"),
                            f"{module} drew {got[0]} rather than {part}")

    def test_mirroring_a_handed_module_swaps_it_for_its_opposite(self):
        """The two sides are separate parts, each authored as the other reflected, so a wing
        mirrored across the ship becomes the other module rather than the same one turned round.
        Top and bottom wings are a vertical pair and have no left-right opposite."""
        h = self.cp.handed()
        self.assertEqual(h.get("B_WNG_A"), "B_WNG_A_R")
        self.assertEqual(h.get("B_WNG_A_R"), "B_WNG_A")
        self.assertEqual(h.get("B_CON_L_1"), "B_CON_R_1")
        self.assertIsNone(h.get("B_WNG_P_T"), "a top wing has no left-right opposite")
        self.assertIsNone(h.get("B_HAB_D"), "a hab is not handed")
        self.assertEqual([k for k, v in h.items() if h.get(v) != k], [],
                         "a pair that does not point back at itself")

    def test_a_leaning_structural_part_is_handed_too(self):
        """The compass suffix says which way a structural piece leans, and the points come in
        mirrored pairs. Missing them put every aerofoil on the far side of a build facing the
        wrong way, because the same _NE part was placed on both sides and an _NE part only ever
        reaches out one way."""
        h = self.cp.handed()
        self.assertEqual(h.get("B_STR_D_NE"), "B_STR_D_NW")
        self.assertEqual(h.get("B_STR_D_NW"), "B_STR_D_NE")
        self.assertEqual(h.get("B_STR_K_NE3"), "B_STR_K_NW3", "the variant number comes along")
        self.assertEqual(h.get("B_STR_AK_NETB"), "B_STR_AK_NWTB")
        self.assertIsNone(h.get("B_STR_D_N"), "north faces front: it has no opposite side")

    def test_the_family_letter_is_not_mistaken_for_a_direction(self):
        """B_STR_E_E is family E facing east. Looking for "_E" anywhere in the id finds the
        family first and mirrors the wrong half of the name."""
        h = self.cp.handed()
        self.assertEqual(h.get("B_STR_E_E"), "B_STR_E_W")
        self.assertEqual(h.get("B_STR_E_W"), "B_STR_E_E")

    def test_every_mirror_points_back_at_its_own_module(self):
        h = self.cp.handed()
        self.assertEqual([k for k, v in h.items() if h.get(v) != k], [])
        self.assertGreater(len(h), 500, "wings, connectors and the leaning structural parts")

    def test_every_module_draws_at_most_one_part(self):
        """A module is one thing. Two scenes for one id means a side or a variant is being
        guessed at, and one of the two lands somewhere it does not belong."""
        several = {m: [s.rsplit("/", 1)[-1] for s in self.cp.scenes_for(m)]
                   for m in self.cp.catalogue() if len(self.cp.scenes_for(m)) > 1}
        self.assertEqual(several, {}, "these modules draw more than one part")

    def test_a_mesh_too_big_for_16_bit_indices_is_read_as_32(self):
        """The turret's gun has 68,416 vertices. Read 16 bits at a time it came out as twice as
        many triangles, each spanning the model, and the gun looked crumpled."""
        import numpy as np
        from nms_procgen import model3d
        scene = self.cp.scenes_for("^B_TUR_A")[0]
        meshes = model3d._scene_meshes(scene)
        geos = model3d._geometry(sorted({g for g, *_ in meshes if g}))
        big = [geos[g][h] for g, h, *_ in meshes if len(geos.get(g, {}).get(h, ([],))[0]) > 65536]
        self.assertTrue(big, "the gun's large mesh is there to check")
        for pos, _, _, idx in big:
            tri = idx.reshape(-1, 3)
            span = np.linalg.norm(pos.max(0) - pos.min(0))
            edge = np.linalg.norm(pos[tri[:, 0]] - pos[tri[:, 1]], axis=1)
            self.assertLess(float(np.median(edge)), span * 0.02,
                            "triangles span the model, so the indices do not fit the vertices")

    def test_the_catalogue_carries_the_build_menu_gates(self):
        hab = self.cp.catalogue()["B_HAB_D"]
        self.assertFalse(hab["rotatable"], "the menu refuses to turn a hab")
        self.assertTrue(hab["placement"].endswith(".SCENE.MBIN"))
