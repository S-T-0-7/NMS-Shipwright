"""NomNom-style save edits beyond ships and inventories: knowledge unlocks, multi-tools,
frigates, companions, and raw JSON access. All functions work on a readable save dict."""
from __future__ import annotations

import functools
import json
import os
import random

from . import gamefiles, gamemeta, items
from .gamefiles import array, cstr, i32, read

CLASSES = ("C", "B", "A", "S")
RACES = {0: "Gek", 1: "Vy'keen", 2: "Korvax", 4: "Atlas", 8: "Autophage"}  # KnownWordGroups Races[] index
FRIGATE_STATS = ("Combat", "Exploration", "Mining", "Diplomacy", "Fuel burn rate", "Fuel capacity", "Speed",
                 "Extra loot", "Repair", "Invulnerable", "Stealth")
FRIGATE_CLASSES = ("Combat", "Exploration", "Mining", "Diplomacy", "Support", "Normandy", "DeepSpace",
                   "DeepSpaceCommon", "Pirate", "GhostShip")


def _ps(readable):
    return readable["BaseContext"]["PlayerStateData"]


# -------------------------------------------------------------- knowledge --

@functools.lru_cache(maxsize=1)
def word_groups() -> dict:
    """{group id: race index} for every learnable alien word."""
    meta = gamemeta.exe_meta()
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "tables"),
                               ["metadata/reality/tables/nms_dialog_gcalienspeechtable.mbin*"], "NMSARC.MetadataEtc.pak")
    path = os.path.join(folder, "nms_dialog_gcalienspeechtable.mbin")
    table, row = meta.layout("cGcAlienSpeechTable"), meta.layout("cGcAlienSpeechEntry")
    b, f = read(path), row.fields
    base, n = array(b, 0x20 + table.off("Table"))
    out = {}
    for k in range(n):
        o = base + k * row.size
        g = cstr(b, o + f["Group"]["offset"], f["Group"]["size"])
        race = i32(b, o + f["Race"]["offset"])
        if g and race in RACES:
            out.setdefault(g, race)
    return out


@functools.lru_cache(maxsize=1)
def recipes() -> dict:
    """{recipe id: is cooking} for every refiner and nutrient-processor recipe."""
    meta = gamemeta.exe_meta()
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "tables"),
                               ["metadata/reality/tables/nms_reality_gcrecipetable.mbin*"], "NMSARC.Precache.pak")
    row = meta.element(meta.layout("cGcRecipeTable"), "Table")
    b = read(os.path.join(folder, "nms_reality_gcrecipetable.mbin"))
    base, n = array(b, 0x20)
    out = {}
    for k in range(n):
        o = base + k * row.size
        rid = cstr(b, o + row.off("Id"), row.fields["Id"]["size"])
        if rid:
            out[rid] = bool(b[o + row.off("Cooking")])
    return out


# unlock group -> (label, save list, how to pick its ids)
UNLOCKS = {
    "tech": ("Technology blueprints", "KnownTech", lambda i: _learnable_tech(i)),
    "products": ("Crafting recipes", "KnownProducts", lambda i: _learnable_product(i)),
    "base": ("Base building parts", "KnownProducts", lambda i: i.get("source") == "base"),
    "customisation": ("Ship customisation parts", "KnownProducts", lambda i: i.get("source") == "customisation"),
    "refiner": ("Refiner recipes", "KnownRefinerRecipes", None),
    "cooking": ("Cooking recipes", "KnownRefinerRecipes", None),
}


def _unlock_ids(group: str) -> list:
    if group in ("refiner", "cooking"):
        return sorted(r for r, cook in recipes().items() if cook == (group == "cooking"))
    pick = UNLOCKS[group][2]
    return sorted(i["id"] for i in items.catalogue().values() if pick(i))


def knowledge(readable) -> dict:
    ps, groups = _ps(readable), word_groups()
    known = {w["Group"].lstrip("^"): w["Races"] for w in ps.get("KnownWordGroups", [])}
    words = {}
    for g, race in groups.items():
        r = words.setdefault(RACES[race], [0, 0])
        r[1] += 1
        if race < len(known.get(g, [])) and known[g][race]:
            r[0] += 1
    cat = items.catalogue()
    kt, kp = set(ps.get("KnownTech", [])), set(ps.get("KnownProducts", []))
    tech = [i for i in cat.values() if _learnable_tech(i)]
    prods = [i for i in cat.values() if _learnable_product(i)]
    out = {"words": words, "groups": []}
    for g, (label, key, _) in UNLOCKS.items():
        ids, have = _unlock_ids(g), set(ps.get(key, []))
        out["groups"].append({"group": g, "label": label, "known": sum("^" + i in have for i in ids), "total": len(ids)})
    return out


def _learnable_product(it):
    return it["type"] == "Product" and it.get("craftable") and it.get("source", "main") == "main"


def _learnable_tech(it):
    return it["type"] == "Technology" and not it["id"].startswith(("T_", "UT_")) and not it.get("core")


def learn_words(readable, races=None) -> int:
    """Teach every word of the given race names (all when None); returns words added."""
    ps, groups = _ps(readable), word_groups()
    want = {i for i, n in RACES.items() if races is None or n in races}
    entries = {w["Group"].lstrip("^"): w for w in ps.setdefault("KnownWordGroups", [])}
    added = 0
    for g, race in groups.items():
        if race not in want:
            continue
        e = entries.get(g)
        if e is None:
            e = entries[g] = {"Group": "^" + g, "Races": [False] * 9}
            ps["KnownWordGroups"].append(e)
        if len(e["Races"]) < 9:
            e["Races"] += [False] * (9 - len(e["Races"]))
        if not e["Races"][race]:
            e["Races"][race] = True
            added += 1
    return added


def learn_all(readable, what: str) -> int:
    """Learn everything of one UNLOCKS group (blueprints, recipes, base parts, ...); returns how many were added."""
    if what not in UNLOCKS:
        raise ValueError(f"unknown unlock group {what!r}")
    ps, key = _ps(readable), UNLOCKS[what][1]
    have = set(ps.setdefault(key, []))
    new = ["^" + i for i in _unlock_ids(what) if "^" + i not in have]
    ps[key] += new
    return len(new)


# ------------------------------------------------------------ multi-tools --

def multitools(readable) -> list[dict]:
    ps = _ps(readable)
    out = []
    for i, m in enumerate(ps.get("Multitools", [])):
        if not (m.get("Resource", {}).get("Filename") or m.get("Store", {}).get("Slots")):
            continue
        out.append({"index": i, "name": m.get("Name", ""), "seed": m.get("Seed", [False, "0x0"])[1],
                    "class": m.get("Store", {}).get("Class", {}).get("InventoryClass", "C"),
                    "model": os.path.basename(m.get("Resource", {}).get("Filename", "")).split(".")[0].title(),
                    "slots": len(m.get("Store", {}).get("ValidSlotIndices", [])), "active": i == ps.get("ActiveMultioolIndex")})
    return out


def edit_multitool(readable, index: int, name=None, seed=None, cls=None):
    m = _ps(readable)["Multitools"][index]
    if name is not None:
        m["Name"] = name[:31]
    if seed is not None:
        s = f"0x{int(str(seed), 0) & (1 << 64) - 1:016X}"
        m["Seed"] = [True, s]
        m.setdefault("Layout", {})["Seed"] = [True, s]
    if cls is not None:
        if cls not in CLASSES:
            raise ValueError("class must be C, B, A or S")
        m["Store"].setdefault("Class", {})["InventoryClass"] = cls


# ---------------------------------------------------------------- frigates --

def frigates(readable) -> list[dict]:
    return [{"index": i, "name": f.get("CustomName", ""), "type": f.get("FrigateClass", {}).get("FrigateClass", ""),
             "class": f.get("InventoryClass", {}).get("InventoryClass", "C"),
             "stats": dict(zip(FRIGATE_STATS, f.get("Stats", []))), "damaged": bool(f.get("DamageTaken")),
             "expeditions": f.get("TotalNumberOfExpeditions", 0), "seed": f.get("ResourceSeed", [0, "0x0"])[1]}
            for i, f in enumerate(_ps(readable).get("FleetFrigates", []))]


def edit_frigate(readable, index: int, name=None, cls=None, stats=None, repair=False, reroll=False):
    f = _ps(readable)["FleetFrigates"][index]
    if name is not None:
        f["CustomName"] = name[:31]
    if cls is not None:
        if cls not in CLASSES:
            raise ValueError("class must be C, B, A or S")
        f.setdefault("InventoryClass", {})["InventoryClass"] = cls
    if stats:
        for k, v in stats.items():
            if k in FRIGATE_STATS:
                f["Stats"][FRIGATE_STATS.index(k)] = int(v)
    if repair:
        f["DamageTaken"], f["NumberOfTimesDamaged"] = 0, 0
    if reroll:
        f["ResourceSeed"] = [True, f"0x{random.getrandbits(64):016X}"]


# -------------------------------------------------------------- companions --

def companions(readable) -> list[dict]:
    out = []
    for i, p in enumerate(_ps(readable).get("Pets", [])):
        if p.get("CreatureID", "^") in ("^", ""):
            continue
        out.append({"index": i, "name": p.get("CustomName", "").lstrip("^"), "creature": p["CreatureID"].lstrip("^").replace("_", " ").title(),
                    "scale": p.get("Scale", 1.0), "predator": p.get("Predator", False),
                    "biome": p.get("Biome", {}).get("Biome", ""), "seed": p.get("CreatureSeed", [0, "0x0"])[1]})
    return out


def edit_companion(readable, index: int, name=None, scale=None):
    p = _ps(readable)["Pets"][index]
    if name is not None:
        p["CustomName"] = name[:31]
    if scale is not None:
        p["Scale"] = max(0.1, min(float(scale), 10.0))


# --------------------------------------------------------------- raw JSON --

def get_path(readable, path: str):
    d = readable
    for part in [p for p in path.split(".") if p]:
        d = d[int(part)] if isinstance(d, list) else d[part]
    return d


def set_path(readable, path: str, value_json: str):
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise ValueError("pick a field first")
    parent = get_path(readable, ".".join(parts[:-1]))
    value = json.loads(value_json)
    last = parts[-1]
    old = parent[int(last)] if isinstance(parent, list) else parent[last]
    if type(old) is not type(value) and not (isinstance(old, (int, float)) and isinstance(value, (int, float))):
        raise ValueError(f"{path} holds a {type(old).__name__}, not a {type(value).__name__}")
    if isinstance(parent, list):
        parent[int(last)] = value
    else:
        parent[last] = value


def browse(readable, path: str = "") -> dict:
    """One level of the save tree: children with a short preview, for the raw editor."""
    node = get_path(readable, path)
    if isinstance(node, dict):
        kids = list(node.items())
    elif isinstance(node, list):
        kids = list(enumerate(node))
    else:
        return {"path": path, "value": json.dumps(node), "leaf": True}
    rows = []
    for k, v in kids[:500]:
        kind = "object" if isinstance(v, dict) else "list" if isinstance(v, list) else "value"
        preview = (f"{len(v)} fields" if isinstance(v, dict) else f"{len(v)} items" if isinstance(v, list)
                   else json.dumps(v)[:80])
        rows.append({"key": str(k), "kind": kind, "preview": preview})
    return {"path": path, "leaf": False, "children": rows, "more": max(0, len(kids) - 500)}


# ------------------------------------------------- expedition & season rewards --

REWARD_GROUPS = {  # group -> (label, id prefix, save list that records "already given")
    "expedition": ("Expedition rewards", "EXPD_", "RedeemedSeasonRewards"),
    "twitch": ("Twitch drops", "TWITCH_", "RedeemedTwitchRewards"),
    "special": ("Other special rewards", "SPEC_", "RedeemedSeasonRewards"),
    "shop": ("Quicksilver shop", None, "RedeemedSeasonRewards"),  # ids come from the shop table
}


@functools.lru_cache(maxsize=1)
def shop_specials() -> list:
    """Ids the Quicksilver vendor at the Anomaly sells."""
    meta = gamemeta.exe_meta()
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "tables"),
                               ["metadata/reality/tables/purchaseablespecials.mbin*"], "NMSARC.Precache.pak")
    row = meta.layout("cGcPurchaseableSpecial")
    b = read(os.path.join(folder, "purchaseablespecials.mbin"))
    base, n = array(b, 0x20)
    return [i for i in (cstr(b, base + k * row.size + row.off("ID"), row.fields["ID"]["size"]) for k in range(n)) if i]


def _reward_ids(group: str) -> list:
    cat = items.catalogue()
    if group == "shop":
        return [i for i in shop_specials() if i in cat]
    prefix = REWARD_GROUPS[group][1]
    return sorted(i for i in cat if i.startswith(prefix))


def rewards(readable, group: str = "", query: str = "", limit: int = 400) -> dict:
    """Reward groups with how many are unlocked, and the items of `group` (searchable)."""
    ps, cat = _ps(readable), items.catalogue()
    known = set(ps.get("KnownSpecials", []))
    groups = []
    for g, (label, _, redeem_key) in REWARD_GROUPS.items():
        ids = _reward_ids(g)
        groups.append({"group": g, "label": label, "total": len(ids),
                       "unlocked": sum("^" + i in known for i in ids)})
    out = {"groups": groups, "items": []}
    if group:
        redeemed = set(ps.get(REWARD_GROUPS[group][2], []))
        q = query.strip().lower()
        for i in _reward_ids(group):
            name = cat.get(i, {}).get("name", i)
            if q and q not in name.lower() and q not in i.lower():
                continue
            out["items"].append({"id": i, "name": name, "unlocked": "^" + i in known, "redeemed": "^" + i in redeemed})
        out["shown"], out["items"] = len(out["items"]), out["items"][:limit]
    return out


def set_rewards(readable, group: str, ids=None, unlock: bool | None = None, redeemed: bool | None = None) -> dict:
    """Unlock (or lock) rewards, and mark them as already given or claimable again.

    unlock=True adds them to the save's unlocked specials, so the game treats them as yours.
    redeemed=False removes them from the "already received" list, so a reward can be claimed again.
    """
    ps = _ps(readable)
    redeem_key = REWARD_GROUPS[group][2]
    pick = ["^" + i for i in (ids if ids else _reward_ids(group))]
    known, redeem = ps.setdefault("KnownSpecials", []), ps.setdefault(redeem_key, [])
    changed = 0
    for lst, want in ((known, unlock), (redeem, redeemed)):
        if want is None:
            continue
        have = set(lst)
        if want:
            new = [i for i in pick if i not in have]
            lst += new
            changed += len(new)
        else:
            drop = set(pick) & have
            lst[:] = [i for i in lst if i not in drop]
            changed += len(drop)
    return {"changed": changed}
