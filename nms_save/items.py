"""Every item the game knows (substances, products, technology), read from the game's tables,
and inventory editing on a readable save (the same edits NomNom makes).

Inventories are addressed by a path from PlayerStateData, e.g. "Inventory",
"ShipOwnership.3.Inventory_TechOnly", "Multitools.0.Store" (see list_inventories).
"""
from __future__ import annotations

import functools
import os
import re

from . import gamefiles, gamemeta, quests
from .gamefiles import array, cstr, i32, read

TABLES = {  # save InventoryType -> (table file, table class, row class)
    "Substance": ("nms_reality_gcsubstancetable.mbin", "cGcSubstanceTable", "cGcRealitySubstanceData"),
    "Product": ("nms_reality_gcproducttable.mbin", "cGcProductTable", "cGcProductData"),
    "Technology": ("nms_reality_gctechnologytable.mbin", "cGcTechnologyTable", "cGcTechnology"),
}
EXTRA_PRODUCTS = {  # more product tables, tagged so they can be unlocked as a group
    "base": "nms_basepartproducts.mbin",            # base building parts
    "customisation": "nms_modularcustomisationproducts.mbin",  # ship / vehicle customisation parts
}
STACK_BASE = {"Substance": 9999, "Product": 10}  # the game rescales MaxAmount for the inventory's stack group
_MARKUP = re.compile(r"<[^>]*>")
PS = ("BaseContext", "PlayerStateData")


class ItemError(ValueError):
    pass


def _english(loc_id: str) -> str:
    return _MARKUP.sub("", quests.strings().get(loc_id, "")).strip()


@functools.lru_cache(maxsize=1)
def catalogue() -> dict:
    """{id: {"id", "type", "name", "stack", "charge", "chargeable", "upgrade", "group"}} for every item."""
    meta = gamemeta.exe_meta()
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "tables"),
                               [f"metadata/reality/tables/{t[0]}*" for t in TABLES.values()]
                               + [f"metadata/reality/tables/{f}*" for f in EXTRA_PRODUCTS.values()],
                               "NMSARC.MetadataEtc.pak")
    out = {}
    sources = {v: k for k, v in EXTRA_PRODUCTS.items()}
    tables = [(k, *v) for k, v in TABLES.items()] + [("Product", f, "cGcProductTable", "cGcProductData")
                                                     for f in EXTRA_PRODUCTS.values()]
    for kind, fname, table_cls, row_cls in tables:
        path = os.path.join(folder, fname)
        if not os.path.exists(path):
            continue
        b, table, row = read(path), meta.layout(table_cls), meta.layout(row_cls)
        base, n = array(b, 0x20 + table.off("Table"))
        f = row.fields
        for k in range(n):
            o = base + k * row.size
            iid = cstr(b, o + f["ID"]["offset"], f["ID"]["size"])
            if not iid:
                continue
            name = (_english(cstr(b, o + f["Name"]["offset"], f["Name"]["size"]))
                    or _english(cstr(b, o + f["NameLower"]["offset"], f["NameLower"]["size"]))
                    or iid.replace("_", " ").title())
            it = {"id": iid, "type": kind, "name": name.title() if name.isupper() else name}
            if kind == "Technology":
                it.update(charge=i32(b, o + f["ChargeAmount"]["offset"]),
                          chargeable=bool(b[o + f["Chargeable"]["offset"]]),
                          upgrade=bool(b[o + f["Upgrade"]["offset"]]), core=bool(b[o + f["Core"]["offset"]]),
                          group=_english(cstr(b, o + f["Group"]["offset"], f["Group"]["size"])))
            else:
                it["stack"] = max(1, STACK_BASE[kind] * i32(b, o + f["StackMultiplier"]["offset"]))
                if kind == "Product":
                    it["craftable"] = bool(b[o + f["IsCraftable"]["offset"]])
                if kind == "Substance":
                    it["stack"] = STACK_BASE[kind]
            it["source"] = sources.get(fname, "main")
            out.setdefault(iid, it)
    if not out:
        raise ItemError("item tables not found in the game files")
    return out


def item(iid: str) -> dict:
    """Catalogue entry for a save id ("^FUEL1" or "FUEL1"; procedural ids like "^UP_LAS3#12345" too).

    Falls back to the raw id if the game's tables cannot be read, so inventories stay editable
    even when a game update breaks the catalogue.
    """
    key = iid.lstrip("^").split("#")[0]
    try:
        known = catalogue().get(key)
    except Exception:
        known = None
    return known or {"id": key, "type": "", "name": key.replace("_", " ").title()}


# ------------------------------------------------------------ inventories --

def _ps(readable):
    d = readable
    for k in PS:
        d = d[k]
    return d


def _resolve(readable, path: str) -> dict:
    d = _ps(readable)
    for part in path.split("."):
        d = d[int(part)] if isinstance(d, list) else d[part]
    if not isinstance(d, dict) or "Slots" not in d:
        raise ItemError(f"{path} is not an inventory")
    return d


FRIENDLY = {"Inventory": "Exosuit", "Inventory_TechOnly": "Exosuit technology", "Inventory_Cargo": "Exosuit cargo",
            "FreighterInventory": "Freighter", "FreighterInventory_TechOnly": "Freighter technology",
            "FreighterInventory_Cargo": "Freighter cargo", "ChestMagicInventory": "Base salvage capsule",
            "ChestMagic2Inventory": "Base salvage capsule 2", "CookingIngredientsInventory": "Nutrient processor",
            "CorvetteStorageInventory": "Corvette storage", "FishPlatformInventory": "Fishing rig",
            "FishBaitBoxInventory": "Bait box", "FoodUnitInventory": "Food unit"}
PART = {"Inventory": "", "Inventory_TechOnly": " technology", "Inventory_Cargo": " cargo", "Store": ""}


def list_inventories(readable) -> list[dict]:
    """Every editable inventory with a friendly name: [{path, name, group, used, slots, width, height}]."""
    ps, out = _ps(readable), []

    def add(path, name, group, inv):
        if inv.get("Width", 0) and inv.get("Height", 0) or inv.get("Slots"):
            out.append({"path": path, "name": name, "group": group, "used": len(inv.get("Slots", [])),
                        "slots": len(inv.get("ValidSlotIndices", [])), "width": inv.get("Width", 0),
                        "height": inv.get("Height", 0), "class": inv.get("Class", {}).get("InventoryClass", "")})
    for key in ("Inventory", "Inventory_TechOnly", "Inventory_Cargo"):
        if key in ps:
            add(key, FRIENDLY[key], "Exosuit", ps[key])
    for i, s in enumerate(ps.get("ShipOwnership", [])):
        if not s.get("Resource", {}).get("Filename"):
            continue
        label = s.get("Name") or f"Ship {i}"
        for key in ("Inventory", "Inventory_TechOnly", "Inventory_Cargo"):
            if key in s:
                add(f"ShipOwnership.{i}.{key}", label + PART[key], "Starships", s[key])
    for key in ("FreighterInventory", "FreighterInventory_TechOnly", "FreighterInventory_Cargo"):
        if key in ps:
            add(key, FRIENDLY[key], "Freighter", ps[key])
    for i, m in enumerate(ps.get("Multitools", [])):
        if m.get("Resource", {}).get("Filename") or m.get("Store", {}).get("Slots"):
            add(f"Multitools.{i}.Store", m.get("Name") or f"Multi-tool {i + 1}", "Multi-tools", m["Store"])
    for i, v in enumerate(ps.get("VehicleOwnership", [])):
        if not v.get("Resource", {}).get("Filename"):
            continue
        label = v.get("Name") or VEHICLES.get(i, f"Exocraft {i}")
        for key in ("Inventory", "Inventory_TechOnly"):
            if key in v:
                add(f"VehicleOwnership.{i}.{key}", label + PART[key], "Exocraft", v[key])
    for n in range(1, 11):
        key = f"Chest{n}Inventory"
        if key in ps:
            add(key, f"Storage container {n - 1}", "Base storage", ps[key])
    for key in ("ChestMagicInventory", "ChestMagic2Inventory", "CookingIngredientsInventory", "CorvetteStorageInventory",
                "FishPlatformInventory", "FishBaitBoxInventory", "FoodUnitInventory"):
        if key in ps:
            add(key, FRIENDLY[key], "Base storage", ps[key])
    return [x for x in out if x["slots"] or x["used"]]


VEHICLES = {0: "Roamer", 1: "Nomad", 2: "Colossus", 3: "Pilgrim", 4: "Nautilon", 5: "Minotaur", 6: "Nautilon (unused)"}


@functools.lru_cache(maxsize=1)
def inventory_caps() -> dict:
    """Slot limits from the game's inventory table.

    {"ship": {type: {"general": (C, B, A, S), "tech": (...)}}, "weapon": (C, B, A, S)}.
    Ship rows are the game's ship-type numbers (see systemgen.CLASS_NAMES); 5 and 11 are unused.
    """
    import struct
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "invtable"), ["*inventorytable*"], "NMSARC.GLOBALS.pak")
    b = read(os.path.join(folder, "inventorytable.mbin"))
    m = gamemeta.exe_meta()
    table = m.layout("cGcInventoryTable")
    if not table.matches(b):
        raise ItemError("the game's inventory table is not the layout this version expects")
    row = m.element(table, "ShipInventoryMaxUpgradeSize")
    base = 0x20 + table.off("ShipInventoryMaxUpgradeSize")
    ships = {}
    for i in range(12):
        q = base + i * row.size
        got = {name: struct.unpack_from("<4i", b, q + row.fields[field]["offset"])
               for name, field in (("general", "MaxInventoryCapacity"), ("tech", "MaxTechInventoryCapacity"))}
        if any(got["general"]):
            ships[i] = got
    weapon = struct.unpack_from("<4i", b, 0x20 + table.off("WeaponInventoryMaxUpgradeSize"))
    return {"ship": ships, "weapon": weapon}


@functools.lru_cache(maxsize=1)
def stat_ranges() -> dict:
    """Stat ranges the game rolls within, from its own table.

    {"ships": {type row: {class 0-3: [{"id", "name", "min", "max"}]}}}, names from the game's text.
    """
    import struct
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "invtable"), ["*inventorytable*"], "NMSARC.GLOBALS.pak")
    b = read(os.path.join(folder, "inventorytable.mbin"))
    m = gamemeta.exe_meta()
    table = m.layout("cGcInventoryTable")
    if not table.matches(b):
        raise ItemError("the game's inventory table is not the layout this version expects")
    # The game's table points agility at the hyperdrive text, so that one gets a name here.
    names = {"SHIP_AGILE": "Manoeuvrability"}
    stat = m.element(table, "BaseStats")
    base, n = array(b, 0x20 + table.off("BaseStats"))
    for k in range(n):
        o = base + k * stat.size
        names.setdefault(cstr(b, o, 16), _english(cstr(b, o + stat.off("LocID"), 16)))
    per_ship = m.element(table, "ShipBaseStatsData")
    per_class = m.element(per_ship, "BaseStatsPerClass")
    entry = m.element(per_class, "BaseStats")
    start = 0x20 + table.off("ShipBaseStatsData")
    ships = {}
    for row in range(12):
        classes = {}
        for cls in range(4):
            at, count = array(b, start + row * per_ship.size + cls * per_class.size)
            rows = []
            for k in range(count):
                o = at + k * entry.size
                sid = cstr(b, o, 16)
                mx, _mxa, mn, _mna = struct.unpack_from("<ffff", b, o + entry.off("Max"))
                if sid and mx and sid != "ROBOT_SHIP":  # that one is a marker, not a stat
                    rows.append({"id": sid, "name": names.get(sid) or sid.replace("_", " ").title(),
                                 "min": round(mn, 2), "max": round(mx, 2)})
            if rows:
                classes[cls] = rows
        if classes:
            ships[row] = classes
    return {"ships": ships}


CLASS_ORDER = ("C", "B", "A", "S")
SHIP_ROWS = {"INDUSTRIAL": 0, "DROPSHIPS": 1, "FIGHTERS": 2, "SCIENTIFIC": 3, "SHUTTLE": 4, "S-CLASS": 6,
             "BIOPARTS": 7, "SAILSHIP": 8, "SENTINELSHIP": 9, "CORVETTE": 10}


def _ship_row(filename: str) -> int | None:
    parts = (filename or "").upper().split("/")
    return next((SHIP_ROWS[p] for p in parts if p in SHIP_ROWS), None)


def max_slots(readable, path: str, inv: dict) -> int | None:
    """Most slots the game allows in this inventory, or None when the game's tables do not say."""
    name = (inv.get("Class", {}) or {}).get("InventoryClass") or "C"
    cls = CLASS_ORDER.index(name) if name in CLASS_ORDER else 0
    try:
        caps = inventory_caps()
    except Exception:  # without the game files, fall back to whatever the grid allows
        return None
    if path.startswith("Multitools"):
        return caps["weapon"][cls]
    row, kind = None, "tech" if path.endswith("_TechOnly") else "general"
    if path.startswith("ShipOwnership"):
        entry = _resolve_parent(readable, path)
        row = _ship_row((entry.get("Resource", {}) or {}).get("Filename", ""))
    elif path.startswith("FreighterInventory"):
        row = 0
    return caps["ship"].get(row, {}).get(kind, (None,) * 4)[cls] if row is not None else None


def _resolve_parent(readable, path: str) -> dict:
    d = _ps(readable)
    for part in path.split(".")[:-1]:
        d = d[int(part)] if isinstance(d, list) else d[part]
    return d if isinstance(d, dict) else {}


def get_inventory(readable, path: str) -> dict:
    inv = _resolve(readable, path)
    valid = {(v["X"], v["Y"]) for v in inv.get("ValidSlotIndices", [])}
    slots = []
    for s in inv.get("Slots", []):
        it = item(s["Id"])
        slots.append({"x": s["Index"]["X"], "y": s["Index"]["Y"], "id": s["Id"], "name": it["name"],
                      "type": s["Type"]["InventoryType"], "amount": s["Amount"], "max": s["MaxAmount"],
                      "damaged": s.get("DamageFactor", 0) > 0 or not s.get("FullyInstalled", True)})
    return {"path": path, "width": inv["Width"], "height": inv["Height"], "valid": sorted(valid),
            "class": inv.get("Class", {}).get("InventoryClass", ""), "slots": slots,
            "max_slots": max_slots(readable, path, inv)}


def _grid(inv) -> list:
    """Every cell of the grid, row by row, growing it to the usual 10 wide if it is unset."""
    w, h = inv.get("Width") or 10, inv.get("Height") or 1
    return [(i, j) for j in range(h) for i in range(w)]


def _grow_grid(inv, x, y):
    inv["Width"] = max(inv.get("Width") or 0, x + 1)
    inv["Height"] = max(inv.get("Height") or 0, y + 1)


def _set_slot_count(inv, want: int, cap: int | None):
    """Add or remove slots so the inventory has `want` of them (the game's own maximum applies)."""
    if want < 1:
        raise ItemError("an inventory needs at least one slot")
    if cap and want > cap:
        raise ItemError(f"the game allows at most {cap} slots here")
    width = inv.get("Width") or 10
    height = max(inv.get("Height") or 1, -(-want // width))
    inv["Width"], inv["Height"] = width, height
    order = [(i, j) for j in range(height) for i in range(width)]
    keep = order[:want]
    holding = {(s["Index"]["X"], s["Index"]["Y"]) for s in inv["Slots"]}
    lost = holding - set(keep)
    if lost:
        raise ItemError(f"{len(lost)} slot(s) being removed still hold items -- empty them first")
    inv["ValidSlotIndices"] = [{"X": i, "Y": j} for i, j in keep]


def _slot_at(inv, x, y):
    return next((s for s in inv["Slots"] if s["Index"]["X"] == x and s["Index"]["Y"] == y), None)


def _new_slot(iid: str, x: int, y: int, amount=None) -> dict:
    it = item(iid)
    kind = it["type"]
    if not kind:
        catalogue()  # raises the real reason if the game tables are unreadable
        raise ItemError(f"unknown item {iid!r}")
    if kind == "Technology":
        mx = it.get("charge") or 1
        amt = mx  # built fully charged
    else:
        mx = it["stack"]
        amt = mx if amount is None else max(1, min(int(amount), mx))
    return {"Type": {"InventoryType": kind}, "Id": "^" + it["id"], "Amount": amt, "MaxAmount": mx,
            "DamageFactor": 0.0, "FullyInstalled": True, "AddedAutomatically": False, "Index": {"X": x, "Y": y}}


def edit_inventory(readable, path: str, op: str, **kw) -> dict:
    """Apply one edit; returns the inventory. ops:
    set (x, y, id, amount?)  put an item in a slot (replaces what is there)
    amount (x, y, amount)    change a stack size
    remove (x, y)            empty a slot
    fill                     every stack to its maximum
    recharge                 every technology to full charge
    repair                   fix every damaged slot
    expand                   unlock every slot the game allows
    slots (count)            have exactly this many slots, adding or removing them
    unlock (x, y)            add one slot
    lock (x, y)              remove one slot (it must be empty)
    """
    inv = _resolve(readable, path)
    slots = inv["Slots"]
    x, y = kw.get("x"), kw.get("y")
    if op in ("set", "amount", "remove") and (x is None or y is None):
        raise ItemError("slot coordinates missing")
    if op == "set":
        if not any(v["X"] == x and v["Y"] == y for v in inv["ValidSlotIndices"]):
            raise ItemError("that slot is locked -- use 'Unlock all slots' first")
        old = _slot_at(inv, x, y)
        if old:
            slots.remove(old)
        slots.append(_new_slot(kw["id"], x, y, kw.get("amount")))
    elif op == "amount":
        s = _slot_at(inv, x, y)
        if not s:
            raise ItemError("that slot is empty")
        s["Amount"] = max(0 if s["Type"]["InventoryType"] == "Technology" else 1, int(kw["amount"]))
        s["MaxAmount"] = max(s["MaxAmount"], s["Amount"])
    elif op == "remove":
        s = _slot_at(inv, x, y)
        if s:
            slots.remove(s)
    elif op == "fill":
        for s in slots:
            if s["Type"]["InventoryType"] != "Technology" and s["MaxAmount"] > 0:
                s["Amount"] = s["MaxAmount"]
    elif op == "recharge":
        for s in slots:
            if s["Type"]["InventoryType"] == "Technology" and s["MaxAmount"] > 0:
                s["Amount"] = s["MaxAmount"]
    elif op == "repair":
        for s in slots:
            s["DamageFactor"], s["FullyInstalled"] = 0.0, True
    elif op in ("expand", "slots"):
        cap = max_slots(readable, path, inv)
        want = (cap or len(_grid(inv))) if op == "expand" else int(kw["count"])
        _set_slot_count(inv, want, cap)
    elif op in ("unlock", "lock"):
        valid = inv["ValidSlotIndices"]
        here = next((v for v in valid if (v["X"], v["Y"]) == (x, y)), None)
        if op == "unlock":
            cap = max_slots(readable, path, inv)
            if here:
                raise ItemError("that slot is already there")
            if cap and len(valid) >= cap:
                raise ItemError(f"the game allows at most {cap} slots here")
            _grow_grid(inv, x, y)
            valid.append({"X": x, "Y": y})
        else:
            if not here:
                raise ItemError("that slot is not there")
            if _slot_at(inv, x, y):
                raise ItemError("take the item out of that slot first")
            valid.remove(here)
    else:
        raise ItemError(f"unknown operation {op!r}")
    return get_inventory(readable, path)


def search_items(query: str, kind: str = "", limit: int = 60) -> list[dict]:
    q = query.strip().lower()
    rows = [it for it in catalogue().values() if (not kind or it["type"] == kind)
            and (not q or q in it["name"].lower() or q in it["id"].lower())]
    rows.sort(key=lambda it: (not it["name"].lower().startswith(q), it["name"]))
    return rows[:limit]
