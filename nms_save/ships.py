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


def set_ship_paint(readable_json: dict, slot: int, primary=(0.0, 0.0, 0.0), accent=None,
                   palette_id: str = "FREIGHTER") -> None:
    """Paint a ship the way Starship Outfitting stores it -- the method the game
    applies (confirmed on sentinels). In-game each colour snaps to the nearest
    colour of `palette_id`; FREIGHTER contains true black, SHIP does not."""
    _populated_entry(readable_json, slot)
    accent = primary if accent is None else accent
    data = _dig(readable_json, CUSTOMISATION_PATH)[customisation_index(slot)].setdefault("CustomData", {})
    data["PaletteID"] = "^" + palette_id
    data["Colours"] = [{"Palette": {"Palette": "Paint", "ColourAlt": alt},
                        "Colour": [float(c) for c in (primary if alt == "Primary" else accent)][:3] + [1.0]}
                       for alt in PAINT_ALTS]


def get_ship_paint(readable_json: dict, slot: int):
    """{"palette": id, "primary": rgb, "accent": rgb} if the slot has stored paint, else None."""
    if not 0 <= slot < 12:
        return None
    data = _dig(readable_json, CUSTOMISATION_PATH)[customisation_index(slot)].get("CustomData", {})
    cols = {c["Palette"]["ColourAlt"]: c["Colour"][:3] for c in data.get("Colours", [])
            if c.get("Palette", {}).get("Palette") == "Paint"}
    if not cols:
        return None
    return {"palette": data.get("PaletteID", "^").lstrip("^"), "primary": cols.get("Primary"),
            "accent": cols.get("Alternative1", cols.get("Primary"))}


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


# A ship is born with one built-in part of each kind. Sentinel interceptors use their own
# versions of all of them; every other ship type uses the ordinary ones.
CORE_TECH = (("LAUNCHER", "LAUNCHER_ROBO"), ("SHIPJUMP1", "SHIPJUMP_ROBO"), ("HYPERDRIVE", "HYPERDRIVE_ROBO"),
             ("SHIPSHIELD", "SHIPSHIELD_ROBO"), ("SHIPGUN1", "SHIPGUN_ROBO"))
SENTINEL_MODEL = "SENTINELSHIP_PROC"


def is_sentinel(filename: str) -> bool:
    return SENTINEL_MODEL in (filename or "").upper()


def wrong_core_tech(entry: dict) -> list:
    """Built-in parts in this ship entry that belong to the other kind of ship."""
    sentinel = is_sentinel(entry.get("Resource", {}).get("Filename", ""))
    wrong = {b if not sentinel else a for a, b in CORE_TECH}
    return [str(s.get("Id", "")).lstrip("^") for key in ("Inventory_TechOnly", "Inventory")
            for s in entry.get(key, {}).get("Slots", []) if str(s.get("Id", "")).lstrip("^") in wrong]


def set_core_tech(readable_json: dict, slot: int, sentinel: bool) -> list:
    """Give the ship in `slot` the built-in parts its type really has.

    A ship copied from another one carries that ship's parts, so a sentinel would fly with a
    Photon Cannon and a Pulse Engine instead of a Sentinel Cannon and a Luminance Engine.
    Returns the swaps made as (old id, new id).
    """
    entry = _populated_entry(readable_json, slot)
    swap = {(a if sentinel else b): (b if sentinel else a) for a, b in CORE_TECH}
    charge = {}
    try:  # full charge for what we install, from the game's own table
        from .items import catalogue
        charge = {k: v.get("charge") or 0 for k, v in catalogue().items()}
    except Exception:  # the game files are optional here
        pass
    done = []
    for key in ("Inventory_TechOnly", "Inventory"):
        for s in entry.get(key, {}).get("Slots", []):
            old = str(s.get("Id", "")).lstrip("^")
            if old in swap:
                new = swap[old]
                s["Id"] = "^" + new
                s["Amount"] = s["MaxAmount"] = charge.get(new, s.get("MaxAmount", 0)) or s.get("MaxAmount", 0)
                s["DamageFactor"] = 0.0
                s["FullyInstalled"] = True
                done.append((old, new))
    if sentinel:
        for key in ("Inventory_TechOnly", "Inventory", "Inventory_Cargo"):  # every interceptor is S class
            inv = entry.get(key)
            if isinstance(inv, dict) and "Class" in inv:
                inv["Class"]["InventoryClass"] = "S"
        # An interceptor always comes with its own hyperdrive; the ship it was copied from
        # may have had none, which would leave it unable to warp.
        have = {str(s.get("Id", "")).lstrip("^") for key in ("Inventory_TechOnly", "Inventory")
                for s in entry.get(key, {}).get("Slots", [])}
        if not have & {"HYPERDRIVE", "HYPERDRIVE_ROBO"}:
            inv = entry.get("Inventory_TechOnly") or {}
            used = {(s["Index"]["X"], s["Index"]["Y"]) for s in inv.get("Slots", []) if "Index" in s}
            free = next(((v["X"], v["Y"]) for v in inv.get("ValidSlotIndices", []) if (v["X"], v["Y"]) not in used), None)
            if free:
                amount = charge.get("HYPERDRIVE_ROBO", 0)
                inv["Slots"].append({"Type": {"InventoryType": "Technology"}, "Id": "^HYPERDRIVE_ROBO",
                                     "Amount": amount, "MaxAmount": amount, "DamageFactor": 0.0,
                                     "FullyInstalled": True, "AddedAutomatically": False,
                                     "Index": {"X": free[0], "Y": free[1]}})
                done.append(("(none)", "HYPERDRIVE_ROBO"))
    return done


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
