# exact reimpl of NMS procedural part selection. reversed from NMS.exe (selector +
# weighted picker, 2026-09 build), verified vs nms.center previews (test_vectors.json).
#  - RNG: 32-bit mul-with-carry, mult 0x5A76F899. 64-bit seed -> s0=lo32 (1 if 0),
#    s1 = rot16(lo32) ^ hi32 ^ lo32.
#  - per group: 1 step, r=(s0*total_weight)>>32, cumulative pick. opts weigh 20,
#    "xRARE"=1, "xNEVER"=0.
#  - each nested list + refpaths of the picked opt walked w/ own child seed (2 steps -> mix64).
#  - group skipped if any of its opt ids already chosen anywhere in the model.
# WARN: this must match the game bit-for-bit. dont "clean up" the maths.
import random

from .mbin import gamedata_dir, load_descriptor, ref_to_descriptor

M32 = 0xFFFFFFFF
M64 = (1 << 64) - 1
MWC_MULT = 0x5A76F899

_SC = "models/common/spacecraft/"
ROOTS = {
    "fighter": _SC + "fighters/fighter_proc.descriptor.mbin",
    "hauler": _SC + "dropships/dropship_proc.descriptor.mbin",
    "explorer": _SC + "scientific/scientific_proc.descriptor.mbin",
    "shuttle": _SC + "shuttle/shuttle_proc.descriptor.mbin",
    "exotic": _SC + "s-class/s-class_proc.descriptor.mbin",
    "living": _SC + "s-class/bioparts/bioship_proc.descriptor.mbin",
    "solar": _SC + "sailship/sailship_proc.descriptor.mbin",
    "sentinel": _SC + "sentinelship/sentinelship_proc.descriptor.mbin",
    "freighter": _SC + "industrial/freighter_proc.descriptor.mbin",
    "capital_freighter": _SC + "industrial/capitalfreighter_proc.descriptor.mbin",
}


def mix64(v):
    v = (v ^ (v >> 33)) * 0x64DD81482CBD31D7 & M64
    v = (v ^ (v >> 33)) * 0xE36AA5C613612997 & M64
    return v ^ (v >> 33)


class MWC:
    __slots__ = ("s0", "s1")

    def __init__(self, seed):
        lo, hi = seed & M32, (seed >> 32) & M32
        self.s0 = lo or 1   # WARN: lo==0 -> 1, game does this. dont drop it.
        self.s1 = (((lo << 16) | (lo >> 16)) & M32) ^ hi ^ lo

    def next(self):
        t = self.s0 * MWC_MULT + self.s1
        self.s0, self.s1 = t & M32, t >> 32
        return self.s0

    def child_seed(self):
        a = self.next()
        return mix64((self.next() << 32) | a)


def option_weight(opt):
    name = opt["name"]
    if "xRARE" in name:
        return 1
    if "xNEVER" in name:
        return 0
    return 20


def stored_id(part_id):
    """How the game records a chosen part: a trailing 'LOD<digit>' is cut and
    the rest upper-cased (_NOSEB_BASELOD0 -> _NOSEB_BASE)."""
    i = part_id.find("LOD")
    if i >= 0 and len(part_id) - i == 4 and part_id[i + 3].isdigit():
        return part_id[:i].upper()
    return part_id


_SIZES = {}  # id(option) -> options in its subtree incl. itself (trees are cached, ids stable)


def _opt_size(opt, gamedata):
    size = _SIZES.get(id(opt))
    if size is None:
        size = 1 + sum(_list_size(kid, gamedata) for kid in opt["kids"])
        for ref in opt["refs"]:
            path = ref_to_descriptor(ref, gamedata)
            if path:
                size += _list_size(load_descriptor(path, gamedata), gamedata)
        _SIZES[id(opt)] = size
    return size


def _list_size(groups, gamedata):
    return sum(_opt_size(o, gamedata) for g in groups for o in g["opts"])


def _select(groups, seed, out, seen, gamedata, depth=0, trace=None, pos=0):
    # pos (trace only): options before this list in full-tree pre-order; nms.center
    # labels each option "<Name>_<1-based pre-order index>".
    rng = MWC(seed)
    for g in groups:
        start = pos
        if trace is not None:
            pos += sum(_opt_size(o, gamedata) for o in g["opts"])
        weights = [option_weight(o) for o in g["opts"]]
        total = sum(weights)
        # WARN: game skips (no RNG step, no recursion) a group w/ nothing to pick OR any
        # opt already chosen elsewhere. the "no RNG step" part is load-bearing, keep it.
        if not total or any(o["id"] in seen for o in g["opts"]):
            continue
        r = (rng.next() * total) >> 32
        for j, (opt, w) in enumerate(zip(g["opts"], weights)):
            if r < w:
                break
            r -= w
        sid = stored_id(opt["id"])
        if sid not in seen:
            seen.add(sid)
            out.append((g["type"], sid))
        child_pos = 0
        if trace is not None:
            child_pos = start + sum(_opt_size(o, gamedata) for o in g["opts"][:j]) + 1
            trace.append((depth, g["type"], opt["id"], [o["id"] for o in g["opts"] if o is not opt],
                          f"{opt['name']}_{child_pos}"))
        for kid in opt["kids"]:
            _select(kid, rng.child_seed(), out, seen, gamedata, depth + 1, trace, child_pos)
            if trace is not None:
                child_pos += _list_size(kid, gamedata)
        for ref in opt["refs"]:
            child = rng.child_seed()
            path = ref_to_descriptor(ref, gamedata)
            if path:
                sub = load_descriptor(path, gamedata)
                _select(sub, child, out, seen, gamedata, depth + 1, trace, child_pos)
                if trace is not None:
                    child_pos += _list_size(sub, gamedata)
    return out


def explain(seed, ship="fighter", gamedata=None):
    """Every pick as (depth, group_type, part_id, [alternatives]); depth = nesting under parent part."""
    trace = []
    _select(load_descriptor(resolve_root(ship, gamedata), gamedata), parse_seed(seed), [], set(),
            gamedata, 0, trace)
    return trace


def parse_seed(seed):
    return (int(seed, 16) if isinstance(seed, str) else int(seed)) & M64


def resolve_root(ship, gamedata=None):
    """Ship alias (see ROOTS), a save-file scene filename, or a descriptor path."""
    if ship.lower() in ROOTS:
        return ROOTS[ship.lower()]
    if ship.lower().endswith(".scene.mbin"):
        path = ref_to_descriptor(ship, gamedata)
        if not path:
            raise ValueError(f"{ship} has no procedural descriptor (fixed model)")
        return path
    return ship


def generate(seed, ship="fighter", gamedata=None):
    """Parts the game picks for `seed`: [(group_type, part_id), ...] in walk order."""
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    return _select(root, parse_seed(seed), [], set(), gamedata)


def part_ids(seed, ship="fighter", gamedata=None):
    return [pid for _, pid in generate(seed, ship, gamedata)]


def all_parts(ship="fighter", gamedata=None):
    """{group_type: [part_id, ...]} for every part reachable from the ship root."""
    found = {}

    def rec(groups):
        for g in groups:
            ids = found.setdefault(g["type"], [])
            for o in g["opts"]:
                if o["id"] not in ids:
                    ids.append(o["id"])
                    for kid in o["kids"]:
                        rec(kid)
                    for ref in o["refs"]:
                        path = ref_to_descriptor(ref, gamedata)
                        if path:
                            rec(load_descriptor(path, gamedata))

    rec(load_descriptor(resolve_root(ship, gamedata), gamedata))
    return found


def describe_tree(ship="fighter", gamedata=None):
    """Indented text listing of the ship's option tree (weights shown when not 20)."""
    lines = []

    def rec(groups, depth):
        for g in groups:
            lines.append("  " * depth + f"{g['type']}  ({len(g['opts'])} options)")
            for o in g["opts"]:
                w = option_weight(o)
                lines.append("  " * depth + f"  - {o['id']}" + (f"  [weight {w}/20]" if w != 20 else ""))
                for kid in o["kids"]:
                    rec(kid, depth + 2)
                for ref in o["refs"]:
                    path = ref_to_descriptor(ref, gamedata)
                    if path:
                        rec(load_descriptor(path, gamedata), depth + 2)

    rec(load_descriptor(resolve_root(ship, gamedata), gamedata), 0)
    return lines


def search(ship="fighter", want=(), avoid=(), limit=5, max_tries=1_000_000, rng=None,
           gamedata=None):
    """Random-seed search for ships containing every part in `want` and none in
    `avoid`. Yields (seed, [(group_type, part_id), ...]) up to `limit` times."""
    want, avoid = set(want), set(avoid)
    known = {pid for ids in all_parts(ship, gamedata).values() for pid in ids}
    unknown = (want | avoid) - known
    if unknown:
        raise ValueError(f"unknown part ids for {ship}: {sorted(unknown)}")
    rng = rng or random.Random()
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    found = 0
    for _ in range(max_tries):
        seed = rng.getrandbits(64)
        parts = _select(root, seed, [], set(), gamedata)
        ids = {pid for _, pid in parts}
        if want <= ids and not avoid & ids:
            yield seed, parts
            found += 1
            if found >= limit:
                return


# nms.center type letters whose part numbering is the full pre-order tree (verified
# identical, 272 options, 2026-09-13). Its fighter list is a curated subset instead.
NMSCENTER_LETTERS = {"N": "sentinel"}


def preorder_options(ship="fighter", gamedata=None):
    """Every option in full-tree pre-order (an option, then its nested lists, then its
    referenced descriptors). nms.center labels option i (0-based) "<Name>_<i+1>"."""
    out = []

    def rec(groups):
        for g in groups:
            for o in g["opts"]:
                out.append(o)
                for kid in o["kids"]:
                    rec(kid)
                for ref in o["refs"]:
                    path = ref_to_descriptor(ref, gamedata)
                    if path:
                        rec(load_descriptor(path, gamedata))

    rec(load_descriptor(resolve_root(ship, gamedata), gamedata))
    return out


def decode_nmscenter_command(cmd, gamedata=None):
    """nms.center's bot search command ("custom:N,1,28,65,...,C3,...") ->
    (ship, [part ids], [trailing colour/texture tokens]). The leading numbers are
    part numbers; parsing stops at the first non-number token."""
    tokens = [t.strip() for t in cmd.strip().split(",") if t.strip()]
    letter = tokens[0].split(":")[-1].strip().upper()
    ship = NMSCENTER_LETTERS.get(letter)
    if not ship:
        raise ValueError(f"nms.center type letter {letter!r} not supported yet "
                         f"(supported: {', '.join(NMSCENTER_LETTERS)})")
    opts = preorder_options(ship, gamedata)
    ids = []
    for i, t in enumerate(tokens[1:], 1):
        if not t.isdigit():
            return ship, ids, tokens[i:]
        if not 1 <= int(t) <= len(opts):
            raise ValueError(f"part number {t} outside 1..{len(opts)}")
        ids.append(opts[int(t) - 1]["id"])
    return ship, ids, []
