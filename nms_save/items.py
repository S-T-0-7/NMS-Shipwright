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
            "class": inv.get("Class", {}).get("InventoryClass", ""), "slots": slots}


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
    expand                   unlock every slot of the grid
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
    elif op == "expand":
        have = {(v["X"], v["Y"]) for v in inv["ValidSlotIndices"]}
        w, h = inv.get("Width") or 10, inv.get("Height") or 12
        inv["Width"], inv["Height"] = w, h
        inv["ValidSlotIndices"] += [{"X": i, "Y": j} for j in range(h) for i in range(w) if (i, j) not in have]
    else:
        raise ItemError(f"unknown operation {op!r}")
    return get_inventory(readable, path)


def search_items(query: str, kind: str = "", limit: int = 60) -> list[dict]:
    q = query.strip().lower()
    rows = [it for it in catalogue().values() if (not kind or it["type"] == kind)
            and (not q or q in it["name"].lower() or q in it["id"].lower())]
    rows.sort(key=lambda it: (not it["name"].lower().startswith(q), it["name"]))
    return rows[:limit]
