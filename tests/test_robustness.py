"""Game-update robustness: caches tied to the game build, extraction stamps, graceful failures.

    python tests/test_robustness.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        os.environ["NMS_TOOL_CACHE"] = self.dir
        for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen", "webapp"))]:
            del sys.modules[mod]
        from nms_save import gamefiles, gameversion
        self.gamefiles, self.gameversion = gamefiles, gameversion
        gamefiles.CACHE = self.dir
        gameversion.BUILD_FILE = os.path.join(self.dir, "build.json")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("NMS_TOOL_CACHE", None)
        sys.modules.pop("hgpaktool", None)  # tests that fake it must not leave it behind


class BuildTracking(Base):
    def test_new_build_drops_caches_derived_from_the_old_one(self):
        gv = self.gameversion
        os.makedirs(os.path.join(self.dir, "models"))
        with open(os.path.join(self.dir, "models", "a.npz"), "wb") as f:
            f.write(b"x")
        gv.build_id = lambda: {"exe": [1, 1], "paks": 1}
        self.assertTrue(gv.check()["first_run"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "models", "a.npz")), "same build keeps the cache")

        gv.check.cache_clear()
        gv.build_id = lambda: {"exe": [2, 2], "paks": 1}
        state = gv.check()
        self.assertTrue(state["changed"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "models")), "a game update drops derived caches")

    def test_missing_game_is_reported_clearly(self):
        gv = self.gameversion
        gv.exe_path = lambda: os.path.join(self.dir, "nope", "NMS.exe")
        with self.assertRaises(gv.GameDataError) as err:
            gv.build_id()
        self.assertIn("Game data", str(err.exception))


class Extraction(Base):
    def _fake_pak(self):
        calls = []

        class FakePak:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract(self, filters):
                calls.append(tuple(filters))
                for f in filters:
                    yield f.replace("*", ""), b"data"

        sys.modules["hgpaktool"] = type("m", (), {"HGPAKFile": FakePak})
        with open(os.path.join(self.dir, "NMSARC.Test.pak"), "wb") as f:
            f.write(b"pak")
        self.gamefiles.banks = lambda: self.dir
        return calls

    def test_two_callers_can_share_a_folder(self):
        calls = self._fake_pak()
        dest = os.path.join(self.dir, "tables")
        self.gamefiles.extract(dest, ["one.mbin*"], "NMSARC.Test.pak")
        self.gamefiles.extract(dest, ["two.mbin*"], "NMSARC.Test.pak")
        self.assertTrue(os.path.exists(os.path.join(dest, "one.mbin")), "the second caller kept the first one's file")
        self.assertTrue(os.path.exists(os.path.join(dest, "two.mbin")))
        self.gamefiles.extract(dest, ["one.mbin*"], "NMSARC.Test.pak")
        self.assertEqual(len(calls), 2, "an unchanged game is not read again")

    def test_a_deleted_copy_is_extracted_again_next_run(self):
        """Within one run the check is remembered; a restart repairs a cache someone deleted from."""
        calls = self._fake_pak()
        dest = os.path.join(self.dir, "tables")
        self.gamefiles.extract(dest, ["one.mbin*"], "NMSARC.Test.pak")
        os.remove(os.path.join(dest, "one.mbin"))
        self.gamefiles.extract(dest, ["one.mbin*"], "NMSARC.Test.pak")
        self.assertEqual(len(calls), 1, "repeat calls in one run do not re-check every file")
        self.gamefiles._VERIFIED.clear()  # as if the app were restarted
        self.gamefiles.extract(dest, ["one.mbin*"], "NMSARC.Test.pak")
        self.assertEqual(len(calls), 2)
        self.assertTrue(os.path.exists(os.path.join(dest, "one.mbin")))

    def test_nothing_found_says_what_to_do(self):
        class Empty:
            def __init__(self, path):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract(self, filters):
                return iter(())

        self._fake_pak()
        sys.modules["hgpaktool"] = type("m", (), {"HGPAKFile": Empty})
        with self.assertRaises(self.gamefiles.GameFileError) as err:
            self.gamefiles.extract(os.path.join(self.dir, "t"), ["missing.mbin*"], "NMSARC.Test.pak")
        self.assertIn("Re-read game files", str(err.exception))


class GracefulFailure(Base):
    def test_unknown_item_falls_back_to_its_id(self):
        from nms_save import items
        it = items.item("^NOT_A_REAL_ITEM")
        self.assertEqual(it["id"], "NOT_A_REAL_ITEM")
        self.assertEqual(it["name"], "Not A Real Item")

    def test_item_names_survive_unreadable_game_tables(self):
        from nms_save import items
        items.catalogue.cache_clear()
        broken = lambda: (_ for _ in ()).throw(items.ItemError("tables unreadable"))
        items.catalogue, real = broken, items.catalogue
        try:
            self.assertEqual(items.item("^FUEL1")["name"], "Fuel1")
        finally:
            items.catalogue = real

    def test_unreadable_exe_names_the_cause(self):
        from nms_save import gamemeta
        path = os.path.join(self.dir, "NMS.exe")
        with open(path, "wb") as f:
            f.write(b"not a program")
        with self.assertRaises(gamemeta.MetaError) as err:
            gamemeta.ExeMeta(path)
        self.assertIn("could not be read", str(err.exception))

    def test_save_with_a_stray_non_utf8_byte_still_decodes(self):
        # a customer's save carried a byte that is not valid UTF-8; strict decode used to crash
        # with "'utf-8' codec can't decode byte 0x80". It must decode and round-trip instead.
        import json
        from nms_save import codec
        raw = b'{"a":"name ab\x80cd","n":5}\x00'
        text, chunked, nul = codec.decode(raw)
        self.assertEqual(json.loads(text)["n"], 5)
        reraw = codec.encode(json.dumps(json.loads(text), separators=(",", ":")), chunked, nul)
        self.assertEqual(json.loads(codec.decode(reraw)[0])["n"], 5)


class ShipModels(unittest.TestCase):
    """The viewer must never end up with an invisible ship."""

    def setUp(self):
        os.environ.pop("NMS_TOOL_CACHE", None)  # these need the real copies of the game files
        for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen", "webapp"))]:
            del sys.modules[mod]
        from nms_procgen import model3d
        self.m = model3d
        self.real = model3d._material_class
        try:
            model3d.ship_meshes(0xA547AB958C97E439, "fighter")
        except Exception as e:
            self.skipTest(f"game files not available: {e}")

    def tearDown(self):
        self.m._material_class = self.real

    def _classes(self):
        return {m[3] for m in self.m.ship_meshes(0xA547AB958C97E439, "fighter")}

    def test_unreadable_materials_still_draw_the_hull(self):
        self.m._material_class = lambda material: (None, "")
        self.assertTrue(self._classes() & {"paint", "metal", "secondary"})

    def test_materials_that_all_claim_to_be_invisible_are_not_trusted(self):
        for pretend in (12, 14, 59, 70):  # decal, mask, shadow-only, volume
            self.m._material_class = lambda material, k=pretend: (k, "")
            self.assertTrue(self._classes(), f"class {pretend} hid the whole ship")

    def test_index_buffers_stay_inside_their_mesh(self):
        """The "16 bit indices" flag lies on some ships; a wrong width draws a black mess."""
        for ship, parts, seed in (("sentinel", ["_PIT_A"], 0), ("sentinel", None, 0x1234567890ABCDEF),
                                  ("fighter", None, 0xA547AB958C97E439)):
            model = self.m.ship_model(seed, ship, parts)
            for cls, (pos, idx) in model["groups"].items():
                self.assertTrue(len(idx) % 3 == 0, f"{ship} {cls} has a partial triangle")
                self.assertLess(int(idx.max()), len(pos), f"{ship} {cls} points outside its own vertices")

    def test_a_half_finished_design_shows_a_whole_ship(self):
        """Picking one part must not hide every group the design has not chosen yet."""
        full = len(self.m.ship_meshes(0, "sentinel", []))
        one = self.m.ship_meshes(0, "sentinel", ["_PIT_A"])
        other = self.m.ship_meshes(0, "sentinel", ["_PIT_C"])
        self.assertGreater(len(one), 20, "one pick left almost nothing to draw")
        self.assertGreater(full, 20)
        self.assertNotEqual([m[1] for m in one], [m[1] for m in other], "the pick changed nothing")

    def test_lower_detail_copies_are_left_out(self):
        for name in ("BodyLOD1", "WingsALOD2", "SUB3_Wings_GLOD3"):
            self.assertNotEqual(self.m.LOD_SUFFIX.search(name).group(1), "0")
        self.assertIsNone(self.m.LOD_SUFFIX.search("Body"))
        self.assertEqual(self.m.LOD_SUFFIX.search("WingsALOD0").group(1), "0")

    def test_every_ship_that_deploys_can_be_flown(self):
        """Not just the Sentinel: each type with a gear or wing anim must offer a flying pose."""
        from nms_procgen import anim
        for ship in ("sentinel", "fighter", "explorer", "shuttle"):
            self.assertTrue(self.m.ship_model("0x1", ship)["posable"], f"{ship} should fly")
        # A ship whose anim does not line up with its scene is left parked rather than guessed at;
        # a freighter never takes off at all.
        for ship in ("freighter", "living", "hauler", "solar"):
            self.assertFalse(self.m.ship_model("0x1", ship)["posable"],
                             f"{ship} has nothing it can be shown flying with")

    def test_the_flying_pose_bends_a_ship_without_breaking_it(self):
        """Flying moves the gear and wings only -- it must not tip, grow or tear the ship."""
        from nms_procgen import anim
        span = lambda p: float(numpy.linalg.norm(p.max(0) - p.min(0)))
        for ship in ("sentinel", "fighter", "explorer", "shuttle"):
            landed = self.m.ship_model("0x1", ship)
            self.assertTrue(landed["posable"], f"{ship} should offer a flying pose")
            flight = self.m.ship_model("0x1", ship, flying=True)
            lp = numpy.concatenate([p for p, _ in landed["groups"].values()])
            fp = numpy.concatenate([p for p, _ in flight["groups"].values()])
            self.assertEqual(lp.shape, fp.shape, f"{ship}: the pose changed the mesh itself")
            self.assertTrue(numpy.isfinite(fp).all(), f"{ship}: the flying pose broke vertices")
            moved = numpy.linalg.norm(fp - lp, axis=1)
            # Some ships only fold a small gear away, so what matters is that a part of the ship
            # visibly moves, not how much of it does.
            self.assertGreater(moved.max(), 0.1, f"{ship} did not move at all")
            self.assertGreater((moved > 1e-3).mean(), 0.002, f"{ship} barely moved a vertex")
            # An anim read in its own axes would turn the whole ship over and throw parts off; a
            # real deploy only folds pieces in, so the ship keeps its size.
            self.assertLess(span(fp), span(lp) * 1.4, f"{ship}: flying tipped it over or tore it apart")
            self.assertLess(moved.max(), span(lp), f"{ship}: a part flew off on its own")


class Designs(unittest.TestCase):
    """Saved designs: files that are checked before use, and seeds that really build the design."""

    def setUp(self):
        os.environ.pop("NMS_TOOL_CACHE", None)
        for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen", "webapp"))]:
            del sys.modules[mod]
        try:
            from webapp.routes import designer
        except Exception as e:
            self.skipTest(f"app not importable here: {e}")
        self.designs = designer

    def test_bad_design_files_are_refused(self):
        for bad in ({"ship": "banana", "want": ["_PIT_A"]}, {"ship": "sentinel", "want": ["_NOT_A_PART"]},
                    {"ship": "sentinel", "want": []}, ["not", "a", "design"]):
            with self.assertRaises(ValueError):
                self.designs.clean_design(bad)

    def test_a_known_seed_is_only_used_if_it_still_builds_the_design(self):
        d = next(x for x in self.designs.read_designs() if x["id"] == "dark_unicorn")
        self.assertEqual(self.designs.matching_seed(d["ship"], d["want"], d["seeds"]), d["seeds"][0])
        self.assertIsNone(self.designs.matching_seed(d["ship"], d["want"], ["0x1", "0x2"]))


class ShipEquipment(unittest.TestCase):
    """A ship must carry the parts, mark and class of the type it actually is."""

    FIGHTER = "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN"
    SENTINEL = "MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN"

    def setUp(self):
        for mod in [m for m in list(sys.modules) if m.startswith("nms_save")]:
            del sys.modules[mod]
        from nms_save import ships
        self.ships = ships

    def _save(self, filename, tech):
        def inv(ids):
            return {"Slots": [{"Type": {"InventoryType": "Technology"}, "Id": "^" + i, "Amount": 1, "MaxAmount": 1,
                               "DamageFactor": 0.0, "FullyInstalled": True, "Index": {"X": n, "Y": 0}}
                              for n, i in enumerate(ids)],
                    "ValidSlotIndices": [{"X": x, "Y": y} for y in range(3) for x in range(6)],
                    "Class": {"InventoryClass": "C"},
                    "BaseStatValues": [{"BaseStatID": "^SHIP_DAMAGE", "Value": 1.0}]}
        entry = {"Name": "", "Resource": {"Filename": filename, "Seed": [True, "0x1"]},
                 "Inventory": inv([]), "Inventory_TechOnly": inv(tech), "Inventory_Cargo": inv([])}
        return {"BaseContext": {"PlayerStateData": {"ShipOwnership": [entry]}}}, entry

    def _ids(self, entry):
        return sorted(s["Id"].lstrip("^") for s in entry["Inventory_TechOnly"]["Slots"])

    def _stats(self, entry):
        return [s["BaseStatID"].lstrip("^") for s in entry["Inventory"]["BaseStatValues"]]

    def test_a_sentinel_gets_interceptor_parts_and_the_interceptor_mark(self):
        save, entry = self._save(self.SENTINEL, ["LAUNCHER", "SHIPJUMP1", "SHIPSHIELD", "SHIPGUN1"])
        self.assertTrue(self.ships.wrong_core_tech(entry), "fighter parts on a sentinel are a fault")
        self.ships.set_core_tech(save, 0, True)
        self.assertEqual(self._ids(entry), ["HYPERDRIVE_ROBO", "LAUNCHER_ROBO", "LIFESUP_ROBO",
                                            "SHIPGUN_ROBO", "SHIPJUMP_ROBO", "SHIPSHIELD_ROBO"])
        self.assertIn("ROBOT_SHIP", self._stats(entry), "the game's interceptor mark")
        self.assertEqual(entry["Inventory"]["Class"]["InventoryClass"], "S")
        self.assertEqual(self.ships.wrong_core_tech(entry), [])

    def test_turning_one_back_into_a_starship_undoes_all_of_it(self):
        save, entry = self._save(self.SENTINEL, ["LAUNCHER", "SHIPJUMP1"])
        self.ships.set_core_tech(save, 0, True)
        entry["Resource"]["Filename"] = self.FIGHTER
        self.ships.set_core_tech(save, 0, False)
        self.assertNotIn("LIFESUP_ROBO", self._ids(entry), "no Pilot Interface on an ordinary ship")
        self.assertNotIn("ROBOT_SHIP", self._stats(entry))
        self.assertEqual(self.ships.wrong_core_tech(entry), [])

    def test_stats_stay_inside_what_the_game_rolls(self):
        save, entry = self._save(self.FIGHTER, ["LAUNCHER"])
        try:
            now = self.ships.ship_stats(save, 0)
        except Exception as e:
            self.skipTest(f"game files not available: {e}")
        self.assertTrue(now["stats"], "a fighter has stats")
        first = now["stats"][0]
        with self.assertRaises(ValueError):
            self.ships.set_ship_stats(save, 0, {first["id"]: first["max"] + 50})
        best = self.ships.set_ship_stats(save, 0, ship_class="S", best=True)
        self.assertEqual(best["class"], "S")
        for st in best["stats"]:
            self.assertEqual(st["value"], st["max"], f"{st['name']} should be at its best")

    def test_a_missing_part_is_not_called_a_fault(self):
        """A starter ship with no hyperdrive is the player's business, not a fault to fix."""
        save, entry = self._save(self.FIGHTER, ["LAUNCHER", "SHIPJUMP1"])
        self.assertEqual(self.ships.wrong_core_tech(entry), [])

    def test_a_sentinel_recolour_snaps_to_the_only_palette_the_game_draws(self):
        """The game renders only the metallic palette on an interceptor; any other set shows
        its default colour instead. A sentinel recolour must land in SHIP_METALLIC so it shows."""
        for filename, want in ((self.SENTINEL, "SHIP_METALLIC"), (self.FIGHTER, "FREIGHTER")):
            save, _ = self._save(filename, [])
            save["BaseContext"]["PlayerStateData"]["CharacterCustomisationData"] = [{} for _ in range(26)]
            got = self.ships.set_ship_paint(save, 0, primary=(1.0, 1.0, 1.0), palette_id="FREIGHTER")
            self.assertEqual(got["palette"], want)


class GeneratorVectors(unittest.TestCase):
    """The part generator must keep reproducing known ships after a game update."""

    def test_known_ships_still_come_out_the_same(self):
        os.environ.pop("NMS_TOOL_CACHE", None)
        for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen"))]:
            del sys.modules[mod]
        from nms_procgen.generator import part_ids, stored_id
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "nms_procgen", "test_vectors.json")) as f:
            vectors = json.load(f)
        for t in vectors:
            alias = t.get("aliases", {})          # ids nms.center used before the game renamed them
            want = {stored_id(alias.get(p, p)) for p in t["parts"]}
            try:
                got = set(part_ids(int(str(t["seed"]), 16), t["ship"]))
            except Exception as e:
                self.skipTest(f"game files not available: {e}")
            self.assertLessEqual(want, got, f"{t['seed']} ({t['ship']}) lost {sorted(want - got)}")


class OtherPeoplesPCs(unittest.TestCase):
    """The app has to work on a PC that is not the one it was built on."""

    def setUp(self):
        os.environ.pop("NMS_TOOL_CACHE", None)
        for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen", "webapp"))]:
            del sys.modules[mod]

    def test_the_game_is_found_without_being_told_where_it_is(self):
        from nms_save import gamepath
        os.environ.pop("NMS_DIR", None)
        gamepath.find.cache_clear()
        folder = gamepath.find()
        if not folder:
            self.skipTest("No Man's Sky is not installed here")
        self.assertTrue(gamepath.looks_like_game(folder))

    def test_a_folder_that_is_not_the_game_is_refused(self):
        from nms_save import gamepath
        self.assertFalse(gamepath.looks_like_game(tempfile.gettempdir()))
        with self.assertRaises(gamepath.GamePathError):
            gamepath.save_dir(tempfile.gettempdir())

    def test_part_data_is_taken_from_the_players_own_game(self):
        """Nothing from the game is shipped, so the parts must come out of their install."""
        cache = tempfile.mkdtemp(prefix="nmstest-")
        os.environ["NMS_TOOL_CACHE"] = cache
        try:
            for mod in [m for m in list(sys.modules) if m.startswith(("nms_save", "nms_procgen"))]:
                del sys.modules[mod]
            from nms_procgen import mbin
            mbin._BUNDLED = os.path.join(cache, "not-bundled")  # as in a build others download
            mbin.gamedata_dir.cache_clear()
            from nms_procgen.generator import all_parts
            try:
                groups = all_parts("sentinel")
            except Exception as e:
                self.skipTest(f"game files not available: {e}")
            self.assertIn("_PIT_", groups)
            self.assertTrue(os.path.isdir(os.path.join(cache, "gamedata", "models")))
        finally:
            os.environ.pop("NMS_TOOL_CACHE", None)
            shutil.rmtree(cache, ignore_errors=True)


class ShipTechIsLearned(Base):
    """Tech the tool puts on a ship must be marked known, or the game drops it on load."""

    def _save(self, filename):
        inv = lambda: {"Slots": [], "ValidSlotIndices": [{"X": x, "Y": 0} for x in range(12)],
                       "Class": {"InventoryClass": "C"}, "BaseStatValues": []}
        entry = {"Resource": {"Filename": filename, "Seed": [True, "0x0"]},
                 "Inventory": inv(), "Inventory_TechOnly": inv(), "Inventory_Cargo": inv()}
        return {"BaseContext": {"PlayerStateData": {
            "ShipOwnership": [entry], "KnownTech": [],
            "CharacterCustomisationData": [{} for _ in range(26)]}}}

    def test_sentinel_core_tech_is_added_to_known_tech(self):
        from nms_save import ships
        save = self._save("MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN")
        ships.set_core_tech(save, 0, True)
        known = {k.lstrip("^") for k in save["BaseContext"]["PlayerStateData"]["KnownTech"]}
        self.assertTrue({"HYPERDRIVE_ROBO", "SHIPSHIELD_ROBO", "LIFESUP_ROBO"} <= known)

    def test_special_ship_tech_is_added_to_known_tech(self):
        from nms_save import ships
        save = self._save("")  # empty slot
        special = {"Name": "X", "Resource": {"Filename": "MODELS/X.SCENE.MBIN", "Seed": [True, "0x6"]},
                   "Inventory_TechOnly": {"Slots": [{"Id": "^SHIPLAS1"}, {"Id": "^UP_PULSE3"}]}}
        ships.install_special_ship(save, 0, special)
        known = {k.lstrip("^") for k in save["BaseContext"]["PlayerStateData"]["KnownTech"]}
        self.assertIn("SHIPLAS1", known)
        self.assertIn("UP_PULSE3", known)


class CrossPlatformPaths(unittest.TestCase):
    """Game/save discovery must work on Linux (Steam/Proton), not just Windows."""

    def test_looks_like_game_matches_folder_case_insensitively(self):
        from nms_save import gamepath
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "binaries"))            # lower-case, as a Linux install may be
            open(os.path.join(d, "binaries", "nms.exe"), "w").close()
            os.makedirs(os.path.join(d, "gamedata", "pcbanks"))
            self.assertTrue(gamepath.looks_like_game(d))
            self.assertFalse(gamepath.looks_like_game(os.path.join(d, "nope")))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_steam_libraries_includes_extra_drives_from_the_vdf(self):
        from nms_save import gamepath
        steam, extra = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(steam, "steamapps"))
            with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), "w") as f:
                f.write('"libraryfolders"{"0"{"path" "%s"}}' % extra.replace("\\", "\\\\"))
            orig = gamepath._steam_roots
            gamepath._steam_roots = lambda: [steam]
            try:
                libs = gamepath.steam_libraries()
            finally:
                gamepath._steam_roots = orig
            self.assertIn(steam, libs)
            self.assertIn(extra, libs)
        finally:
            shutil.rmtree(steam, ignore_errors=True)
            shutil.rmtree(extra, ignore_errors=True)

    def test_linux_save_roots_point_at_the_proton_prefix(self):
        from nms_save import gamepath, locator
        lib = tempfile.mkdtemp()
        try:
            pfx = os.path.join(lib, "steamapps", "compatdata", "275850", "pfx", "drive_c", "users",
                               "steamuser", "AppData", "Roaming", "HelloGames", "NMS", "st_1")
            os.makedirs(pfx)
            with open(os.path.join(pfx, "save.hg"), "wb") as f:
                f.write(b"x")
            keep_w, keep_libs = locator.WINDOWS, gamepath.steam_libraries
            locator.WINDOWS = False
            gamepath.steam_libraries = lambda: [lib]
            try:
                roots = locator.save_roots()
                saves = locator.find_saves()
            finally:
                locator.WINDOWS, gamepath.steam_libraries = keep_w, keep_libs
            self.assertTrue(any("compatdata" in r for r in roots), roots)
            self.assertEqual([s.slot_name for s in saves], ["save.hg"])
        finally:
            shutil.rmtree(lib, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
