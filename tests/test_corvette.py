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


def has_game():
    try:
        from nms_save import gamepath
        return bool(gamepath.require())
    except Exception:
        return False


HAB = "MODELS/COMMON/SPACECRAFT/BIGGS/MODULES/PARTS/HAB_D_1X2_CORE.SCENE.MBIN"

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



@unittest.skipUnless(has_game(), "needs No Man's Sky installed")
class StructuralTurns(unittest.TestCase):
    """20 structural variants a family, 5 models between them, and the variant names the turn.

    Looking "_NE1" up as a part of its own found nothing, so 486 of 854 modules drew as
    nothing at all -- a corvette built out of them came back full of holes. The turn is read
    off the placement scenes, which name the side of every socket, and these check it against
    both of the files that know: the socket positions and the mesh.
    """

    @classmethod
    def setUpClass(cls):
        from nms_procgen import corvette_parts, model3d
        cls.cp, cls.m = corvette_parts, model3d

    @staticmethod
    def _ry(degrees):
        import math
        import numpy as np
        t = math.radians(degrees)
        return np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])

    def _socket_points(self, module_id):
        import numpy as np
        return sorted(tuple(np.round(np.array(m).reshape(4, 4).T[:3, 3], 3) + 0.0)
                      for _, _, m in self.cp.snaps_for(module_id))

    def test_a_variant_is_its_base_shape_turned_by_exactly_that_much(self):
        """The strong one. Turn the base variant's sockets by what turn_for says and every
        socket has to land on one of the variant's own, to 3 decimal places -- position and
        all, not just which side it is on. 648 variants, no exceptions."""
        import numpy as np
        fams = {}
        for mid in self.cp.catalogue():
            family, variant = self.cp._split(mid)
            if family and family.startswith("STR"):
                fams.setdefault(family, []).append(variant)
        checked, wrong = 0, []
        for family, variants in sorted(fams.items()):
            for variant in variants:
                mid = "B_%s_%s" % (family, variant)
                shape, _ = self.cp.str_shape(variant)
                base = "B_%s_%s" % (family, self.cp.str_variant(shape, 0))
                here, there = self._socket_points(base), self._socket_points(mid)
                if not here or not there:
                    continue
                turned = sorted(tuple(np.round(p, 3) + 0.0)
                                for p in np.array(here) @ self._ry(self.cp.turn_for(mid)).T)
                checked += 1
                if turned != there:
                    wrong.append(mid)
        self.assertGreater(checked, 600, "most of the catalogue is structural")
        self.assertEqual(wrong, [])

    def test_the_turned_mesh_reaches_the_faces_the_game_joins_it_by(self):
        """The independent one: the sockets came from the placement scene, this is the model.

        A wedge that takes a neighbour on its E and N has to be solid against x=+3 and z=-3
        and cut away from the other two. The 2 faces are different sizes -- 7.2 across against
        5.2 -- so it is which faces the mesh reaches at all that has to line up.
        """
        import numpy as np
        faces = {"E": (0, 3.0), "W": (0, -3.0), "N": (2, -3.0), "S": (2, 3.0)}
        wrong = []
        for family in ("STR_A", "STR_B", "STR_D", "STR_K", "STR_AE"):
            for variant in ("N", "E", "S", "W", "NE", "NE1", "NE2", "NE3",
                            "NW", "NW1", "NW2", "NW3"):
                mid = "B_%s_%s" % (family, variant)
                drawn = self.cp.draw_for(mid)
                if mid not in self.cp.catalogue() or not drawn:
                    continue
                model = self.m.corvette_model([(s, (0, 0, 0), (0, 1, 0), (0, 0, 1), turn)
                                               for s, turn in drawn])
                p = np.concatenate([g[0] for g in model["groups"].values()])
                reached = set()
                for name, (axis, plane) in faces.items():
                    near = p[np.abs(p[:, axis] - plane) < 0.15]
                    if len(near) > 2 and np.ptp(near[:, 2 if axis == 0 else 0]) > 0.05:
                        reached.add(name)
                joins = {k[-1] for k, io, _ in self.cp.snaps_for(mid)
                         if io == "in" and k[-1] in "NESW"}
                if reached != joins:
                    wrong.append((mid, sorted(joins), sorted(reached)))
        self.assertEqual(wrong, [])

    def test_the_shape_and_the_turn_name_the_variant_back(self):
        for variant in ("N", "E", "S", "W", "NE", "NE1", "NE2", "NE3",
                        "NETB", "NETB1", "NWTB2", "NW3"):
            shape, quarters = self.cp.str_shape(variant)
            self.assertEqual(self.cp.str_variant(shape, quarters), variant)

    def test_ne_is_a_shape_and_not_a_compass_letter(self):
        """"NE" in "NESW" is true, because that is a substring test. Taken as a cardinal it
        made every plain wedge draw the flat block and mirror to the wrong module."""
        self.assertEqual(self.cp.str_shape("NE"), ("NE", 0))
        self.assertEqual(self.cp.str_shape("N"), ("N", 0))
        self.assertTrue(self.cp.scenes_for("B_STR_D_NE")[0].upper().endswith("NE_3.SCENE.MBIN"))

    def test_the_z_airlocks_are_the_plain_ones_facing_the_other_way(self):
        """B_ALK_Z_A carries B_ALK_A's sockets with in and out swapped, which is a half turn.

        C is the odd one: the plain B_ALK_C is a 4-way hub with 20 sockets while B_ALK_Z_C is
        the same NS hatch as the others, so its half turn follows the family rather than being
        measured off the pair.
        """
        import numpy as np
        for letter in "ABD":
            plain, zed = "B_ALK_%s" % letter, "B_ALK_Z_%s" % letter
            turned = sorted(tuple(np.round(p, 3) + 0.0) for p in
                            np.array(self._socket_points(plain)) @ self._ry(180).T)
            self.assertEqual(turned, self._socket_points(zed))
            self.assertEqual(self.cp.turn_for(zed), 180.0)
            self.assertEqual(self.cp.scenes_for(zed), self.cp.scenes_for(plain))
        self.assertEqual(self.cp.turn_for("B_ALK_Z_C"), 180.0)

    def test_a_shape_with_no_reflection_is_not_given_one(self):
        """handed() used to answer for any structural module, which is only right when the
        shape itself can mirror.

        Turning the flat block E reflects to turning it W -- but only while the block is
        symmetric in X. 16 of the 71 families carry one that is not, and 4 turns of an
        asymmetric shape can never produce its reflection, so for those the catalogue holds
        no mirror at all and the honest answer is None. This measures it rather than trusting
        the list: reflect each model and look for its opposite number vertex by vertex.
        """
        import numpy as np
        tol = 0.12

        def cloud(mid):
            model = self.m.corvette_model([(s, (0, 0, 0), (0, 1, 0), (0, 0, 1), t)
                                           for s, t in self.cp.draw_for(mid)])
            p = np.concatenate([g[0] for g in model["groups"].values()]).astype(np.float32)
            return np.unique(np.round(p, 2), axis=0)

        def reflects(a, b):
            """Does every vertex of a sit on one of mirrored b, and the other way about?"""
            flip = b.copy()
            flip[:, 0] *= -1
            for one, two in ((a, flip), (flip, a)):
                for point in one:
                    if float(np.min(np.linalg.norm(two - point, axis=1))) > tol:
                        return False
            return True

        asymmetric = sorted(self.cp.UNMIRRORED["N"])
        self.assertEqual(len(asymmetric), 16)
        for family in asymmetric[:4] + ["STR_K", "STR_A", "STR_D"]:
            mid = "B_%s_N" % family
            flat = cloud(mid)
            mirrors = reflects(flat, flat)
            self.assertEqual(mirrors, family not in self.cp.UNMIRRORED["N"],
                             "%s symmetric=%s but the table says otherwise" % (mid, mirrors))
            twin = self.cp.handed().get("B_%s_E" % family)
            self.assertEqual(twin, None if not mirrors else "B_%s_W" % family)

    def test_a_wedge_and_its_opposite_really_are_reflections(self):
        """The other half of the same question: NE is paired with NW on the strength of the
        models being reflections, so at least spot-check that they are."""
        import numpy as np
        for family in ("STR_D", "STR_K", "STR_AE"):
            clouds = []
            for shape in ("NE", "NW"):
                model = self.m.corvette_model(
                    [(s, (0, 0, 0), (0, 1, 0), (0, 0, 1), t)
                     for s, t in self.cp.draw_for("B_%s_%s" % (family, shape))])
                p = np.concatenate([g[0] for g in model["groups"].values()])
                clouds.append(np.unique(np.round(p.astype(np.float32), 2), axis=0))
            here, there = clouds
            there = there.copy()
            there[:, 0] *= -1
            for point in here[::7]:
                self.assertLess(float(np.min(np.linalg.norm(there - point, axis=1))), 0.12,
                                "%s: NE is not the reflection of NW" % family)

    def test_the_build_menu_does_not_offer_an_invisible_part(self):
        """A model named in the parts table is not always a model the game ships.

        B_LND_D asks for LANDINGGEAR_LEG_D, which is in the table and in no pak, and sat in
        the menu drawing nothing at all when you placed it.
        """
        self.assertTrue(self.cp.scenes_for("B_LND_D"), "the table does name a model for it")
        self.assertFalse(self.cp.drawable("B_LND_D"), "and the game does not ship it")
        self.assertFalse(self.cp.drawable("B_TRU_I"), "ZENGINEI is a scene with no mesh in it")
        self.assertTrue(self.cp.drawable("B_TUR_A"))
        offered = [m for m, row in self.cp.catalogue().items()
                   if row["in_menu"] and self.cp.drawable(m)]
        self.assertNotIn("B_LND_D", offered)
        self.assertGreater(len(offered), 150)

    def test_a_mirror_is_never_a_module_that_does_not_exist(self):
        cat = self.cp.catalogue()
        strays = sorted({v for v in self.cp.handed().values() if v not in cat})
        self.assertEqual(strays, [])

    def test_everything_but_the_interior_now_draws(self):
        """What is left is the pieces whose part the row genuinely does not determine: a wall,
        a door or a stairway is chosen by the hab it stands in and the way it runs, and the
        row records neither."""
        left = sorted(m for m in self.cp.catalogue() if not self.cp.scenes_for(m))
        self.assertTrue(all(m.startswith(("B_WALL_", "B_DOOR", "B_STAIRS")) for m in left), left)
        drawn = sum(1 for m in self.cp.catalogue() if self.cp.scenes_for(m))
        self.assertGreater(drawn, 800, "was 338 while the turned variants resolved to nothing")

    def test_a_turn_rides_along_with_the_placement(self):
        """corvette_model takes the turn as a 5th item, and a module without one is untouched."""
        plain = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1])])["bounds"]
        same = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1], 0)])["bounds"]
        turned = self.m.corvette_model([(HAB, [0, 0, 0], [0, 1, 0], [0, 0, 1], -90)])["bounds"]
        self.assertEqual(plain, same)
        self.assertAlmostEqual(turned[1][0], plain[1][2], places=3, msg="x and z swap")
        self.assertAlmostEqual(turned[1][1], plain[1][1], places=3, msg="height is untouched")




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
        self.assertEqual(h.get("B_STR_AK_NETB"), "B_STR_AK_NWTB")
        self.assertIsNone(h.get("B_STR_D_N"), "north faces front: it has no opposite side")

    def test_a_turned_wedge_mirrors_to_the_opposite_turn_not_the_same_number(self):
        """Reflecting turns a piece the other way, so the numbers do not pair off straight.

        This test used to ask for B_STR_K_NE3 -> B_STR_K_NW3 and got it, which is wrong and
        was wrong in a way nothing caught: a mirrored wedge came out at the right handedness
        and the wrong angle. The placement scenes settle it -- B_STR_K_NE3 attaches by its E
        and S faces, and the module that attaches by the reflection of those, W and S, is
        B_STR_K_NW1.
        """
        h = self.cp.handed()
        for a, b in (("NE", "NW"), ("NE1", "NW3"), ("NE2", "NW2"), ("NE3", "NW1")):
            self.assertEqual(h.get("B_STR_K_" + a), "B_STR_K_" + b)
            self.assertEqual(h.get("B_STR_K_" + b), "B_STR_K_" + a)
        self.assertEqual(h.get("B_STR_AK_NETB1"), "B_STR_AK_NWTB3")

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

if __name__ == "__main__":
    unittest.main()
