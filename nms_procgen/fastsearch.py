# numpy seed search for designs w/ many pinned parts. runs generator.py's RNG for
# millions of seeds at once, group by group, dropping fails early. hits re-checked
# w/ the exact generator (matches()).
# WARN: must stay in lockstep w/ generator.py. if the generator maths changes, this does too.
import time

import numpy as np

from . import textures
from .generator import all_parts, explain, generate, option_weight, parse_seed, resolve_root
from .mbin import gamedata_dir, load_descriptor, ref_to_descriptor

U = np.uint64
K, M32, S16, S32, S33 = U(0x5A76F899), U(0xFFFFFFFF), U(16), U(32), U(33)
C1, C2 = U(0x64DD81482CBD31D7), U(0xE36AA5C613612997)


def _state(seeds):
    lo, hi = seeds & M32, seeds >> S32
    return np.where(lo == 0, U(1), lo), (((lo << S16) | (lo >> S16)) & M32) ^ hi ^ lo


def _step(s0, s1):
    t = s0 * K + s1
    return t & M32, t >> S32


def _child(s0, s1):
    s0, s1 = _step(s0, s1)
    a = s0
    s0, s1 = _step(s0, s1)
    v = (s0 << S32) | a
    v = (v ^ (v >> S33)) * C1
    v = (v ^ (v >> S33)) * C2
    return s0, s1, v ^ (v >> S33)


def _compile(groups, want, avoid, gamedata):
    """Static per-group data; subtrees without constraints compile to []."""
    plan = []
    for g in groups:
        opts = g["opts"]
        w = [option_weight(o) for o in opts]
        if not sum(w):
            continue
        allowed = [j for j, o in enumerate(opts) if o["id"] in want]
        banned = [j for j, o in enumerate(opts) if o["id"] in avoid]
        subs = []
        for j, o in enumerate(opts):
            if (allowed and j not in allowed) or j in banned:
                continue
            kids = [_compile(k, want, avoid, gamedata) for k in o["kids"]]
            refs = []
            for r in o["refs"]:
                path = ref_to_descriptor(r, gamedata)
                refs.append(_compile(load_descriptor(path, gamedata), want, avoid, gamedata) if path else [])
            if any(kids) or any(refs):
                subs.append((j, kids + refs))
        steps = np.array([2 * (len(o["kids"]) + len(o["refs"])) for o in opts])
        plan.append((np.cumsum(w).astype(np.uint64), U(sum(w)), np.array(allowed, dtype=np.int64),
                     np.array(banned, dtype=np.int64), steps, subs))
    return plan if any(p[2].size or p[3].size or p[5] for p in plan) else []


def _eval(plan, s0, s1):
    """Boolean mask of seeds (given as RNG states of this list) meeting the plan."""
    ok = np.ones(len(s0), bool)
    idx = np.arange(len(s0))
    for cum, tot, allowed, banned, steps, subs in plan:
        s0, s1 = _step(s0, s1)
        pick = np.searchsorted(cum, (s0 * tot) >> S32, side="right")
        good = np.ones(len(idx), bool)
        if allowed.size:
            good &= np.isin(pick, allowed)
        if banned.size:
            good &= ~np.isin(pick, banned)
        for j, sub_plans in subs:
            sel = np.nonzero(good & (pick == j))[0]
            if not sel.size:
                continue
            a0, a1, sub = s0[sel], s1[sel], np.ones(sel.size, bool)
            for sp in sub_plans:  # kid lists, then references; each takes two steps
                a0, a1, child = _child(a0, a1)
                if sp:
                    sub &= _eval(sp, *_state(child))
            good[sel] = sub
        ok[idx[~good]] = False
        idx, s0, s1, n = idx[good], s0[good], s1[good], steps[pick[good]]
        if not idx.size:
            break
        for k in range(int(n.max())):
            t0, t1 = _step(s0, s1)
            act = n > k
            s0, s1 = np.where(act, t0, s0), np.where(act, t1, s1)
    return ok


def _closure(root, want, gamedata):
    """want plus every ancestor option of each wanted id (all occurrences)."""
    out = set(want)

    def rec(groups, path):
        for g in groups:
            for o in g["opts"]:
                if o["id"] in want:
                    out.update(path)
                for kid in o["kids"]:
                    rec(kid, path + [o["id"]])
                for r in o["refs"]:
                    p = ref_to_descriptor(r, gamedata)
                    if p:
                        rec(load_descriptor(p, gamedata), path + [o["id"]])

    rec(root, [])
    return out


def matches(seed, ship, want, avoid, gamedata=None):
    """Exact check of the same semantics using the real generator."""
    for _depth, _gtype, pid, alts, _label in explain(seed, ship, gamedata):
        if pid in avoid or (pid not in want and any(a in want for a in alts)):
            return False
    return True


def fast_search(ship="fighter", want=(), avoid=(), limit=5, max_seeds=10 ** 11, batch=1 << 20,
                time_limit=None, rng=None, stats=None, should_stop=None, gamedata=None, look=None):
    """Yields (seed, [(group_type, part_id), ...]) for seeds meeting want/avoid and `look`
    ({"primary"/"secondary"/"undercoat": colour indices, "mode": hull texture modes}).
    If given, stats (a dict) receives 'tested' and 'seconds'; should_stop() is
    polled between batches to cancel."""
    known = {pid for ids in all_parts(ship, gamedata).values() for pid in ids}
    unknown = (set(want) | set(avoid)) - known
    if unknown:
        raise ValueError(f"unknown part ids for {ship}: {sorted(unknown)}")
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    want, avoid = _closure(root, set(want), gamedata), set(avoid)
    plan = _compile(root, want, avoid, gamedata)
    rng = rng or np.random.default_rng()
    stats = {} if stats is None else stats
    stats.update(tested=0, seconds=0.0)
    t0, found = time.time(), 0
    with np.errstate(over="ignore"):
        while (stats["tested"] < max_seeds and not (time_limit and time.time() - t0 > time_limit)
               and not (should_stop and should_stop())):
            seeds = rng.integers(0, np.iinfo(np.uint64).max, size=batch, dtype=np.uint64, endpoint=True)
            st = _state(seeds)
            mask = _eval(plan, *st) if plan else np.ones(len(seeds), bool)
            if look:
                mask &= textures.look_mask(*st, look)
            hits = seeds[mask] if (plan or look) else seeds[:1]
            stats["tested"] += batch
            stats["seconds"] = time.time() - t0
            for s in map(int, hits):
                if matches(s, ship, want, avoid, gamedata) and (not look or textures.look_matches(s, look)):
                    found += 1
                    yield s, generate(s, ship, gamedata)
                    if found >= limit:
                        return


def make_filter(ship, want=(), avoid=(), gamedata=None, look=None):
    """check(seeds) -> the seeds meeting want/avoid (vectorised pre-filter, exact confirmation)."""
    known = {pid for ids in all_parts(ship, gamedata).values() for pid in ids}
    unknown = (set(want) | set(avoid)) - known
    if unknown:
        raise ValueError(f"unknown part ids for {ship}: {sorted(unknown)}")
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    want, avoid = _closure(root, set(want), gamedata), set(avoid)
    plan = _compile(root, want, avoid, gamedata)

    def check(seeds):
        if not seeds:
            return []
        arr = np.array(seeds, dtype=np.uint64)
        with np.errstate(over="ignore"):
            st = _state(arr)
            mask = _eval(plan, *st) if plan else np.ones(len(arr), bool)
            if look:
                mask &= textures.look_mask(*st, look)
        return [s for s, ok in zip(seeds, mask) if ok and matches(s, ship, want, avoid, gamedata)
                and (not look or textures.look_matches(s, look))]
    return check


def fast_accepts(seeds, ship, want=(), avoid=(), gamedata=None):
    """Vectorised accept mask for given seeds (used to validate against the exact generator)."""
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    want, avoid = _closure(root, set(want), gamedata), set(avoid)
    plan = _compile(root, want, avoid, gamedata)
    arr = np.array([parse_seed(s) for s in seeds], dtype=np.uint64)
    with np.errstate(over="ignore"):
        return _eval(plan, *_state(arr)) if plan else np.ones(len(arr), bool)
