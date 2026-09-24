"""Locate and edit ship entries inside a deobfuscated save JSON tree.

Confirmed against a real save (current game version, 2026): ships live at
    BaseContext -> PlayerStateData -> ShipOwnership   (a list, one slot per
    ship the player owns; empty slots have no Resource.Filename).

Each populated entry looks like:
    {
        "Name": "",                       # player-given nickname, if any
        "Resource": {
            "Filename": "MODELS/COMMON/SPACECRAFT/<CATEGORY>/<MODEL>.SCENE.MBIN",
            "Seed": [true, "0xA547AB958C97E439"],   # [flag, hex seed string]
            ...
        },
        "Inventory": {...}, "Location": {...}, ...
    }

Two very different kinds of entries show up under the same Filename shape:
  - Procedurally generated ships: Filename ends in "_PROC.SCENE.MBIN".
    Their visual look IS driven by Seed -- swapping the seed string swaps
    the look next time the game (re)generates the model.
  - Fixed/reward ships (expedition rewards, "Golden Vector", etc.):
    Filename points at one specific hardcoded model
    (e.g. FIGHTERCLASSICGOLD.SCENE.MBIN). Seed on these is a small
    inventory-slot id (0x0, 0x1, ...), NOT a visual seed -- editing it
    does nothing to the look.
"""
from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass

SHIP_PATH = ("BaseContext", "PlayerStateData", "ShipOwnership")

SEED_RE = re.compile(r"^0x[0-9A-Fa-f]+$")


def is_valid_seed(seed: str) -> bool:
    """True if `seed` is a '0x' + hex-digits string the game can parse as a
    64-bit value. Rejects things like '0xTESTNOTHEX' that merely start
    with '0x' but aren't valid hex.
    """
    return bool(SEED_RE.match(str(seed))) and int(seed, 16) <= 0xFFFFFFFFFFFFFFFF

# Best-effort label from the model folder. Not authoritative -- just for
# display -- since the in-game "Class" (C/B/A/S) rating isn't a plain field
# on this entry (it's derived from installed tech/stats elsewhere).
_CATEGORY_LABELS = {
    "FIGHTERS": "Fighter",
    "SCIENTIFIC": "Explorer",
    "DROPSHIPS": "Hauler",
    "SENTINELSHIP": "Sentinel",
    "SOLAR": "Solar",
    "EXOTIC": "Exotic",
    "SHUTTLE": "Shuttle",
    "LIVING": "Living Ship",
}


class ShipLookupError(ValueError):
    pass


# The one fixed-model slot the community has actually found a way to make
# procedural: the "gShip - Gumsk's Custom Ships" mod (NexusMods #1891)
# repurposes this exact model into a 70+-entry procedural list, selected
# by seed. Without that PAK installed, seeding it does nothing, same as
# any other fixed model -- see scripts/import_gship.py.
GOLDEN_VECTOR_FILENAME = "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTERCLASSICGOLD.SCENE.MBIN"


@dataclass
class Ship:
    index: int
    name: str
    filename: str
    seed_flag: bool
    seed: str
    is_procedural: bool
    is_golden_vector: bool
    category_guess: str
    raw: dict  # the original (still-mutable) dict this Ship was read from

    def describe(self) -> str:
        if self.is_procedural:
            tag = ""
        elif self.is_golden_vector:
            tag = "  [FIXED MODEL -- vanilla seed edit does nothing; the gShip mod unlocks 70+ seeded looks here]"
        else:
            tag = "  [FIXED MODEL -- seed edit will do nothing visual]"
        label = self.name.strip() or "(unnamed)"
        return (
            f"[{self.index}] {label} -- {self.category_guess} "
            f"seed={self.seed}{tag}"
        )


def _dig(obj, path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            raise ShipLookupError(
                f"Expected key {key!r} not found (path so far: {'.'.join(path)}). "
                "Save format may have changed -- check data/mapping.json is current."
            )
        obj = obj[key]
    return obj


def _category_guess(filename: str) -> str:
    parts = filename.upper().split("/")
    for part in parts:
        if part in _CATEGORY_LABELS:
            return _CATEGORY_LABELS[part]
    return "Unknown"


def list_ships(readable_json: dict) -> list[Ship]:
    """Return every populated ship slot (empty slots are skipped)."""
    entries = _dig(readable_json, SHIP_PATH)
    ships = []

    for i, entry in enumerate(entries):
        resource = entry.get("Resource", {})
        filename = resource.get("Filename", "") or ""
        if not filename:
            continue  # empty slot

        seed_field = resource.get("Seed", [True, "0x0"])
        seed_flag, seed_value = seed_field[0], seed_field[1]

        ships.append(
            Ship(
                index=i,
                name=entry.get("Name", "") or "",
                filename=filename,
                seed_flag=bool(seed_flag),
                seed=str(seed_value),
                is_procedural="_PROC.SCENE.MBIN" in filename.upper(),
                is_golden_vector=filename.upper() == GOLDEN_VECTOR_FILENAME,
                category_guess=_category_guess(filename),
                raw=entry,
            )
        )

    return ships


def set_ship_seed(readable_json: dict, index: int, new_seed: str) -> Ship:
    """Overwrite the seed of ShipOwnership[index] in place.

    Returns the updated Ship for confirmation. Does NOT touch Filename --
    that's what makes this reversible/safe: the ship stays the same
    inventory slot and category, only the procedural look changes.
    """
    entries = _dig(readable_json, SHIP_PATH)
    if not entries:
        raise ShipLookupError("This save has no ship slots at all -- unexpected for a real save.")
    if not (0 <= index < len(entries)):
        raise ShipLookupError(f"No ship slot {index} (valid range: 0..{len(entries) - 1})")

    entry = entries[index]
    resource = entry.get("Resource")
    if resource is None or not resource.get("Filename"):
        raise ShipLookupError(f"Slot {index} is empty -- nothing to reseed")

    if not is_valid_seed(new_seed):
        raise ValueError(f"Seed must be '0x' + hex digits (a 64-bit value); got {new_seed!r}")

    seed_field = resource.get("Seed", [True, "0x0"])
    resource["Seed"] = [seed_field[0], new_seed]

    filename = resource["Filename"]
    is_procedural = "_PROC.SCENE.MBIN" in filename.upper()
    is_golden_vector = filename.upper() == GOLDEN_VECTOR_FILENAME
    if not is_procedural:
        import warnings

        if is_golden_vector:
            warnings.warn(
                f"Slot {index} ({filename}) is the Golden Vector slot: a vanilla "
                "install ignores its seed. Install the gShip mod (see "
                "scripts/import_gship.py) to unlock 70+ seeded looks here."
            )
        else:
            warnings.warn(
                f"Slot {index} ({filename}) is a fixed-model ship, "
                "not a procedural one -- its seed does not control appearance."
            )

    return Ship(
        index=index,
        name=entry.get("Name", "") or "",
        filename=filename,
        seed_flag=bool(resource["Seed"][0]),
        seed=str(resource["Seed"][1]),
        is_procedural=is_procedural,
        is_golden_vector=is_golden_vector,
        category_guess=_category_guess(filename),
        raw=entry,
    )


CUSTOMISATION_PATH = ("BaseContext", "PlayerStateData", "CharacterCustomisationData")


def customisation_index(slot: int) -> int:
    """CharacterCustomisationData entry for a ship slot. The 26 customisation
    types include 12 "SHIP" palettes at 3-8 and 17-22 (ship slots 0-5, 6-11)."""
    if not 0 <= slot < 12:
        raise ShipLookupError(f"ship slot {slot} has no customisation entry (0-11)")
    return 3 + slot if slot < 6 else 17 + slot - 6


def _set_customisation_paint(readable_json: dict, slot: int, rgba, palette_id: str = "SHIP") -> None:
    """Starship-Outfitting-style paint for one ship slot. The game snaps each colour
    to the nearest entry of the palette named by PaletteID (SHIP has no black)."""
    entries = _dig(readable_json, CUSTOMISATION_PATH)
    data = entries[customisation_index(slot)].setdefault("CustomData", {})
    data["PaletteID"] = "^" + palette_id
    data["Colours"] = [{"Palette": {"Palette": "Paint", "ColourAlt": alt}, "Colour": list(rgba)}
                       for alt in ("Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4")]


PAINT_ALTS = ("Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4")


def _populated_entry(readable_json: dict, slot: int) -> dict:
    entries = _dig(readable_json, SHIP_PATH)
    if not (0 <= slot < len(entries)) or not entries[slot].get("Resource", {}).get("Filename"):
        raise ShipLookupError(f"No populated ship at slot {slot}")
    return entries[slot]


@functools.lru_cache(maxsize=1)
def _palettes() -> dict:
    """{palette id: [[r, g, b], ...]} -- the game's paint sets, as 64 slots each."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "palettes", "customisation.json")
    with open(path) as f:
        return {k: v["colours"] for k, v in json.load(f)["palettes"].items()}


def palette_index(palette_id: str, rgb) -> int:
    """Which slot of `palette_id` this colour is (the nearest one, if it is not exact).

    The game stores a paint as an index into a palette. Storing -1 with a loose RGB instead
    leaves the ship to be repainted after it is built, which shows as a flash of its own
    colours, and is not what other players are sent.
    """
    try:
        colours = _palettes()[palette_id]
    except (KeyError, OSError, ValueError):
        return -1
    rgb = [float(c) for c in rgb][:3]
    return min(range(len(colours)), key=lambda i: sum((a - b) ** 2 for a, b in zip(colours[i], rgb)))


def set_ship_paint(readable_json: dict, slot: int, primary=(0.0, 0.0, 0.0), accent=None,
                   palette_id: str = "FREIGHTER", primary_index: int | None = None,
                   accent_index: int | None = None) -> dict:
    """Paint a ship the way Starship Outfitting stores it: a palette and an index into it.

    In-game each colour snaps to the nearest colour of `palette_id`; FREIGHTER contains
    true black, SHIP does not. Returns the indices written.
    """
    _populated_entry(readable_json, slot)
    accent = primary if accent is None else accent
    if primary_index is None:
        primary_index = palette_index(palette_id, primary)
    if accent_index is None:
        accent_index = palette_index(palette_id, accent)
    colours = _palettes().get(palette_id) or []
    if 0 <= primary_index < len(colours):  # use the palette's own colour, not one a click away
        primary = colours[primary_index]
    if 0 <= accent_index < len(colours):
        accent = colours[accent_index]
    data = _dig(readable_json, CUSTOMISATION_PATH)[customisation_index(slot)].setdefault("CustomData", {})
    data["PaletteID"] = "^" + palette_id
    data["Colours"] = [{"Palette": {"Palette": "Paint", "ColourAlt": alt,
                                    "Index": int(primary_index if alt == "Primary" else accent_index)},
                        "Colour": [float(c) for c in (primary if alt == "Primary" else accent)][:3] + [1.0]}
                       for alt in PAINT_ALTS]
    return {"palette": palette_id, "primary_index": int(primary_index), "accent_index": int(accent_index)}


def get_ship_paint(readable_json: dict, slot: int):
    """{"palette": id, "primary": rgb, "accent": rgb} if the slot has stored paint, else None."""
    if not 0 <= slot < 12:
        return None
    data = _dig(readable_json, CUSTOMISATION_PATH)[customisation_index(slot)].get("CustomData", {})
    cols = {c["Palette"]["ColourAlt"]: c["Colour"][:3] for c in data.get("Colours", [])
            if c.get("Palette", {}).get("Palette") == "Paint"}
    if not cols:
        return None
    idx = {c["Palette"]["ColourAlt"]: c["Palette"].get("Index", -1) for c in data.get("Colours", [])
           if c.get("Palette", {}).get("Palette") == "Paint"}
    return {"palette": data.get("PaletteID", "^").lstrip("^"), "primary": cols.get("Primary"),
            "accent": cols.get("Alternative1", cols.get("Primary")),
            "primary_index": idx.get("Primary", -1), "accent_index": idx.get("Alternative1", -1)}


FREIGHTER_MODELS = {"freighter": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTER_PROC.SCENE.MBIN",
                    "capital_freighter": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/CAPITALFREIGHTER_PROC.SCENE.MBIN"}


def get_freighter(readable_json: dict) -> dict:
    ps = readable_json["BaseContext"]["PlayerStateData"]
    cf = ps.get("CurrentFreighter") or {}
    return {"filename": cf.get("Filename", ""), "seed": (cf.get("Seed") or [False, ""])[1],
            "home": (ps.get("CurrentFreighterHomeSystemSeed") or [False, ""])[1]}


def set_freighter(readable_json: dict, kind: str, seed: str, home_ua: int | None = None) -> None:
    """Give the player's freighter a procedural model and seed. The home system seed (a
    universe address) drives its colours, so pass the system the freighter was found in."""
    if kind not in FREIGHTER_MODELS:
        raise ValueError(f"unknown freighter type {kind!r}")
    if not is_valid_seed(seed):
        raise ValueError(f"invalid seed {seed!r}")
    ps = readable_json["BaseContext"]["PlayerStateData"]
    cf = ps.get("CurrentFreighter")
    if not cf or not cf.get("Filename"):
        raise ValueError("this save has no freighter")
    cf["Filename"] = FREIGHTER_MODELS[kind]
    cf["Seed"] = [True, f"0x{int(seed, 16):X}"]
    if home_ua is not None:
        ps["CurrentFreighterHomeSystemSeed"] = [True, f"0x{home_ua:X}"]


def set_ship_name(readable_json: dict, slot: int, name: str) -> None:
    _populated_entry(readable_json, slot)["Name"] = name


# The built-in parts a ship is born with, by kind of ship. Sentinel interceptors use their own
# version of every part, and one part no other ship has (the Pilot Interface). Pairs line up so a
# ship that changes type keeps the same equipment in its own flavour; None means "no counterpart".
CORE_TECH = (("LAUNCHER", "LAUNCHER_ROBO"), ("SHIPJUMP1", "SHIPJUMP_ROBO"), ("HYPERDRIVE", "HYPERDRIVE_ROBO"),
             ("SHIPSHIELD", "SHIPSHIELD_ROBO"), ("SHIPGUN1", "SHIPGUN_ROBO"), (None, "LIFESUP_ROBO"))
SENTINEL_MODEL = "SENTINELSHIP_PROC"
ROBOT_STAT = "ROBOT_SHIP"  # the ship stat the game puts on interceptors and on nothing else


def is_sentinel(filename: str) -> bool:
    return SENTINEL_MODEL in (filename or "").upper()


def core_tech_for(sentinel: bool) -> list:
    """Ids of the parts a ship of this kind comes with."""
    return [(b if sentinel else a) for a, b in CORE_TECH if (b if sentinel else a)]


def _tech_ids(entry: dict) -> set:
    return {str(s.get("Id", "")).lstrip("^") for key in ("Inventory_TechOnly", "Inventory")
            for s in entry.get(key, {}).get("Slots", [])}


def wrong_core_tech(entry: dict) -> list:
    """Parts fitted to this ship that belong to the other kind of ship.

    Only those: a ship with a part missing is the player's own business (a starter ship has no
    hyperdrive yet), while a sentinel carrying a Photon Cannon can only have come from an editor.
    """
    sentinel = is_sentinel(entry.get("Resource", {}).get("Filename", ""))
    wrong = sorted(_tech_ids(entry) & set(core_tech_for(not sentinel)))
    marked = any(str(s.get("BaseStatID", "")).lstrip("^") == ROBOT_STAT
                 for s in (entry.get("Inventory", {}).get("BaseStatValues") or []))
    if sentinel != marked:  # the game's own "this is an interceptor" mark
        wrong.append("the interceptor mark is missing" if sentinel else "it is still marked as an interceptor")
    return wrong


def _install(inv: dict, item: str, amount: int) -> bool:
    """Put `item` in the first free slot of `inv`. False if the grid is full."""
    used = {(s["Index"]["X"], s["Index"]["Y"]) for s in inv.get("Slots", []) if "Index" in s}
    free = next(((v["X"], v["Y"]) for v in inv.get("ValidSlotIndices", []) if (v["X"], v["Y"]) not in used), None)
    if not free:
        return False
    inv["Slots"].append({"Type": {"InventoryType": "Technology"}, "Id": "^" + item,
                         "Amount": amount, "MaxAmount": amount, "DamageFactor": 0.0,
                         "FullyInstalled": True, "AddedAutomatically": False,
                         "Index": {"X": free[0], "Y": free[1]}})
    return True


def set_core_tech(readable_json: dict, slot: int, sentinel: bool) -> list:
    """Give the ship in `slot` the built-in parts its type really has.

    A ship copied from another one carries that ship's parts, so a sentinel would fly with a
    Photon Cannon and a Pulse Engine instead of a Sentinel Cannon and a Luminance Engine. Parts
    with a counterpart are swapped in place; the rest are added or taken out.
    Returns what changed as (old id or "(none)", new id or "(removed)").
    """
    entry = _populated_entry(readable_json, slot)
    swap = {(a if sentinel else b): (b if sentinel else a)
            for a, b in CORE_TECH if a and b}
    drop = {i for i in core_tech_for(not sentinel) if i not in swap}  # no counterpart on this ship
    charge = {}
    try:  # full charge for what we install, from the game's own table
        from .items import catalogue
        charge = {k: v.get("charge") or 0 for k, v in catalogue().items()}
    except Exception:  # the game files are optional here
        pass
    done = []
    for key in ("Inventory_TechOnly", "Inventory"):
        for s in list(entry.get(key, {}).get("Slots", [])):
            old = str(s.get("Id", "")).lstrip("^")
            if old in swap:
                new = swap[old]
                s["Id"] = "^" + new
                s["Amount"] = s["MaxAmount"] = charge.get(new, s.get("MaxAmount", 0)) or s.get("MaxAmount", 0)
                s["DamageFactor"] = 0.0
                s["FullyInstalled"] = True
                done.append((old, new))
            elif old in drop:
                entry[key]["Slots"].remove(s)
                done.append((old, "(removed)"))
    # Anything this kind of ship has and this one still lacks: a copied ship may have had no
    # hyperdrive at all, and only interceptors have a Pilot Interface.
    have = _tech_ids(entry)
    tech = entry.get("Inventory_TechOnly") or {}
    for item in core_tech_for(sentinel):
        if item not in have and _install(tech, item, charge.get(item, 0)):
            done.append(("(none)", item))
    for key in ("Inventory_TechOnly", "Inventory", "Inventory_Cargo"):
        inv = entry.get(key)
        if not isinstance(inv, dict):
            continue
        if sentinel and "Class" in inv:  # every interceptor is S class
            inv["Class"]["InventoryClass"] = "S"
        # The game marks an interceptor with a stat of its own; without it a ship with sentinel
        # parts is still treated as an ordinary starship.
        stats = inv.get("BaseStatValues")
        if isinstance(stats, list):
            robot = [s for s in stats if str(s.get("BaseStatID", "")).lstrip("^") == ROBOT_STAT]
            if sentinel and not robot:
                stats.append({"BaseStatID": "^" + ROBOT_STAT, "Value": 1.0})
                if key == "Inventory":
                    done.append(("(none)", ROBOT_STAT))
            elif not sentinel and robot:
                for s in robot:
                    stats.remove(s)
                if key == "Inventory":
                    done.append((ROBOT_STAT, "(removed)"))
    return done


SHIP_INVENTORIES = ("Inventory", "Inventory_TechOnly", "Inventory_Cargo")


def _stat_rows(entry: dict) -> list:
    """The stats the game rolls for this ship's type and class, with their ranges."""
    from .items import CLASS_ORDER, _ship_row, stat_ranges
    row = _ship_row(entry.get("Resource", {}).get("Filename", ""))
    name = (entry.get("Inventory", {}).get("Class", {}) or {}).get("InventoryClass") or "C"
    cls = CLASS_ORDER.index(name) if name in CLASS_ORDER else 0
    by_class = stat_ranges()["ships"].get(row, {})
    return by_class.get(cls) or by_class.get(max(by_class, default=0), [])


def ship_stats(readable_json: dict, slot: int) -> dict:
    """A ship's stat bonuses, with what the game would roll for a ship like it."""
    entry = _populated_entry(readable_json, slot)
    have = {str(s.get("BaseStatID", "")).lstrip("^"): s.get("Value", 0.0)
            for s in (entry.get("Inventory", {}).get("BaseStatValues") or [])}
    cls = (entry.get("Inventory", {}).get("Class", {}) or {}).get("InventoryClass") or "C"
    rows = [{**r, "value": round(float(have.get(r["id"], 0.0)), 2)} for r in _stat_rows(entry)]
    return {"slot": slot, "class": cls, "stats": rows, "sentinel": is_sentinel(entry["Resource"]["Filename"])}


def set_ship_stats(readable_json: dict, slot: int, values: dict | None = None, ship_class: str | None = None,
                   best: bool = False) -> dict:
    """Set a ship's stat bonuses (and its class). Values outside what the game rolls are refused.

    All three of a ship's inventories carry the same list, so all three are written.
    """
    from .items import CLASS_ORDER
    entry = _populated_entry(readable_json, slot)
    if ship_class:
        if ship_class not in CLASS_ORDER:
            raise ValueError(f"class must be one of {', '.join(CLASS_ORDER)}")
        for key in SHIP_INVENTORIES:
            inv = entry.get(key)
            if isinstance(inv, dict) and "Class" in inv:
                inv["Class"]["InventoryClass"] = ship_class
    rows = {r["id"]: r for r in _stat_rows(entry)}  # ranges for the class it is now
    wanted = {r["id"]: r["max"] for r in rows.values()} if best else {}
    for k, v in (values or {}).items():
        k = str(k).lstrip("^")
        if k not in rows:
            raise ValueError(f"{k} is not a stat this ship has")
        v = float(v)
        lo, hi = rows[k]["min"], rows[k]["max"]
        if not lo <= v <= hi:
            raise ValueError(f"the game gives a ship like this a {rows[k]['name']} bonus between {lo} and {hi}")
        wanted[k] = v
    for key in SHIP_INVENTORIES:
        stats = entry.get(key, {}).get("BaseStatValues")
        if not isinstance(stats, list):
            continue
        by_id = {str(s.get("BaseStatID", "")).lstrip("^"): s for s in stats}
        for k, v in wanted.items():
            if k in by_id:
                by_id[k]["Value"] = float(v)
            else:
                stats.append({"BaseStatID": "^" + k, "Value": float(v)})
    return ship_stats(readable_json, slot)


def set_ship_model(readable_json: dict, slot: int, filename: str, seed: str | None = None) -> None:
    """Change a ship's model/type (Resource.Filename); optionally its seed too.

    Changing between a sentinel and an ordinary ship also swaps the built-in parts, so the
    ship flies with the equipment its own type comes with.
    """
    entry = _populated_entry(readable_json, slot)
    resource = entry["Resource"]
    if seed is not None and not is_valid_seed(seed):
        raise ValueError(f"Seed must be '0x' + hex digits (a 64-bit value); got {seed!r}")
    was, now = is_sentinel(resource.get("Filename", "")), is_sentinel(filename)
    resource["Filename"] = filename
    resource["Seed"] = [True, seed if seed is not None else resource.get("Seed", [True, "0x0"])[1]]
    if was != now or now:
        set_core_tech(readable_json, slot, now)


def create_ship(readable_json: dict, slot: int, filename: str, seed: str, name: str, clone_from: int) -> None:
    """Fill an empty slot with a copy of ship `clone_from` (inventory, tech, layout),
    then give it its own model, seed and name, and no paint. A blank slot has no
    inventory slots at all, so cloning is what makes the new ship usable."""
    import copy

    entries = _dig(readable_json, SHIP_PATH)
    if not (0 <= slot < len(entries)):
        raise ShipLookupError(f"No ship slot {slot} (valid range: 0..{len(entries) - 1})")
    if entries[slot].get("Resource", {}).get("Filename"):
        raise ShipLookupError(f"Slot {slot} already has a ship")
    if not is_valid_seed(seed):
        raise ValueError(f"Seed must be '0x' + hex digits (a 64-bit value); got {seed!r}")
    entry = copy.deepcopy(_populated_entry(readable_json, clone_from))
    entry["Name"] = name
    entry["Resource"].update({"Filename": filename, "Seed": [True, seed], "ProceduralTexture": {"Samplers": []}})
    entries[slot] = entry
    # The copy brought the other ship's built-in parts: give this one the ones its type has.
    set_core_tech(readable_json, slot, is_sentinel(filename))
    clear_ship_paint(readable_json, slot, texture=False)
    legacy = _dig(readable_json, SHIP_PATH[:-1]).get("ShipUsesLegacyColours")
    if isinstance(legacy, list) and slot < len(legacy) and clone_from < len(legacy):
        legacy[slot] = legacy[clone_from]


def clear_ship_paint(readable_json: dict, slot: int, texture: bool = True, customisation: bool = True) -> None:
    """Remove stored paint from a ship slot: the texture override and/or the palette paint."""
    if texture:
        _dig(readable_json, SHIP_PATH)[slot].get("Resource", {})["ProceduralTexture"] = {"Samplers": []}
    if customisation:
        data = _dig(readable_json, CUSTOMISATION_PATH)[customisation_index(slot)].setdefault("CustomData", {})
        data["PaletteID"], data["Colours"] = "^", []


# Paint layers of TEXTURES/COMMON/ROBOTS/SENTINELPROC.TEXTURE.MBIN, which the
# sentinel hull material uses. OVERLAY names are nms.center's scheme labels.
SENTINEL_OVERLAYS = {"1": "Orange + White", "2": "Painted + White", "3": "Purple + Painted", "4": "Painted + Painted"}
_SENTINEL_OVERLAY_PALETTE = {"1": ("Rock", "None"), "2": ("Rock", "None"), "3": ("Paint", "None"),
                             "4": ("Paint", "Alternative1")}


def set_sentinel_paint(readable_json: dict, index: int, colour=(0.0, 0.0, 0.0), overlay: str = "4",
                       fixed: str = "1", customisation: bool = True, palette_id: str = "SHIP") -> dict:
    """Store an explicit paint job in a sentinel ship's Resource.ProceduralTexture.

    Painted options (BASE, and OVERLAY "4") get Colour + OverrideColour, so any
    RGB is used -- including pure black, which the in-game ship palette lacks.
    Experimental: no painted ship exists in the reference save, so the layout
    follows the game's cTkProceduralTextureChosenOption structure.
    """
    entries = _dig(readable_json, SHIP_PATH)
    if not (0 <= index < len(entries)) or not entries[index].get("Resource", {}).get("Filename"):
        raise ShipLookupError(f"No populated ship at slot {index}")
    resource = entries[index]["Resource"]
    if "SENTINELSHIP_PROC" not in resource["Filename"].upper():
        raise ShipLookupError(f"Slot {index} is not a procedural sentinel ship; other types use other paint layers")
    if overlay not in SENTINEL_OVERLAYS:
        raise ValueError(f"overlay must be one of {', '.join(SENTINEL_OVERLAYS)}")
    if fixed not in ("1", "2"):
        raise ValueError("fixed must be '1' or '2'")
    rgba = [float(c) for c in colour][:3] + [1.0]

    def option(layer, name, palette, alt, override):  # TkID fields are "^"-prefixed in saves
        return {"Colour": rgba if override else [0.0, 0.0, 0.0, 1.0], "OptionName": "^" + name, "Group": "^",
                "Layer": "^" + layer, "Palette": {"Palette": palette, "ColourAlt": alt}, "OverrideColour": override}

    pal, alt = _SENTINEL_OVERLAY_PALETTE[overlay]
    if customisation:  # the only paint the game applied in tests; snapped to the palette
        _set_customisation_paint(readable_json, index, rgba, palette_id)
    resource["ProceduralTexture"] = {"Samplers": [{"Options": [
        option("FIXED", fixed, "Rock", "None", False),
        option("OVERLAY", overlay, pal, alt, overlay == "4"),
        option("BASE", "1", "Paint", "Primary", True),
    ]}]}
    return resource["ProceduralTexture"]
