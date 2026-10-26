# numpy seed search for designs w/ many pinned parts. runs generator.py's RNG for
# millions of seeds at once, group by group, dropping fails early. hits re-checked
# w/ the exact generator (matches()). spreads over worker processes when asked.
# WARN: must stay in lockstep w/ generator.py. if the generator maths changes, this does too.
import atexit
import os
import threading
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


def _seed_of(s0, s1):
    """_state run backwards: the seed that starts the RNG at (s0, s1).

    Every state with s0 >= 1 comes from exactly one seed, so drawing states straight out
    of the generator covers seeds just as evenly and saves unpacking one per test.
    """
    return (((((s0 << S16) | (s0 >> S16)) & M32) ^ s1 ^ s0) << S32) | s0


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
    """Static per-group data; subtrees without constraints compile to [].

    A group becomes two small tables rather than a search: `lut` turns the scaled draw
    straight into the option it landed on, and `okv` says whether that option is one we
    will take. Two gathers beat searchsorted plus isin by a wide margin over a million
    seeds at a time, and the tables are only ever a few hundred entries long.
    """
    plan = []
    for g in groups:
        opts = g["opts"]
        w = [option_weight(o) for o in opts]
        total = sum(w)
        if not total:
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
        lut = np.searchsorted(np.cumsum(w), np.arange(total), side="right").astype(np.int16)
        okv = None
        if allowed or banned:
            okv = np.array([(not allowed or j in allowed) and j not in banned for j in range(len(opts))])
        steps = np.array([2 * (len(o["kids"]) + len(o["refs"])) for o in opts])
        plan.append((lut, U(total), okv, steps, subs))
    return plan if any(p[2] is not None or p[4] for p in plan) else []


def _eval(plan, s0, s1):
    """Boolean mask of seeds (given as RNG states of this list) meeting the plan."""
    ok = np.ones(len(s0), bool)
    idx = np.arange(len(s0))
    for lut, tot, okv, steps, subs in plan:
        s0, s1 = _step(s0, s1)
        pick = lut[(s0 * tot) >> S32]
        good = okv[pick] if okv is not None else np.ones(len(idx), bool)
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


class _Scanner:
    """One compiled search: the vectorised pass over random seeds, plus the exact check."""

    def __init__(self, ship="fighter", want=(), avoid=(), gamedata=None, look=None,
                 paintable=False, overlay=None):
        known = {pid for ids in all_parts(ship, gamedata).values() for pid in ids}
        unknown = (set(want) | set(avoid)) - known
        if unknown:
            raise ValueError(f"unknown part ids for {ship}: {sorted(unknown)}")
        root = load_descriptor(resolve_root(ship, gamedata), gamedata)
        self.ship, self.gamedata, self.look = ship, gamedata, look
        self.want, self.avoid = _closure(root, set(want), gamedata), set(avoid)
        self.plan = _compile(root, self.want, self.avoid, gamedata)
        self.paint = bool(paintable) and ship == "sentinel"  # only interceptors have the choice
        self.overlay = list(overlay or ()) if ship == "sentinel" else []
        self.filtering = bool(self.plan or look or self.paint or self.overlay)

    def batch(self, rng, size):
        """Survivors of the vectorised pass, and how many got the parts but not the colour.

        That second number is the one worth having when a search comes back empty: a design
        whose parts turn up often and never in the colour asked for is not a slow search,
        it is a combination the game cannot make, and saying so beats searching all night.
        """
        # One random number per seed, split in half: the two halves are the RNG state, and
        # _seed_of turns a survivor back into its seed. (A zero low half is the one state no
        # seed starts at; it is one in four billion and the exact check drops it.)
        v = rng.integers(0, np.iinfo(np.uint64).max, size=size, dtype=np.uint64, endpoint=True)
        s0, s1 = v & M32, v >> S32
        with np.errstate(over="ignore"):
            if not self.filtering:  # nothing asked for: one seed a batch, as it always was
                return [int(_seed_of(s0[0], s1[0]))], 0
            mask = _eval(self.plan, s0, s1) if self.plan else np.ones(size, bool)
            if self.look:
                mask &= textures.look_mask(s0, s1, self.look)
            near = int(mask.sum()) if (self.paint or self.overlay) else 0
            if self.paint:
                mask &= textures.paintable_mask(s0, s1)
            if self.overlay:
                mask &= textures.overlay_mask(s0, s1, self.overlay)
            return [int(x) for x in _seed_of(s0[mask], s1[mask])], near

    def confirm(self, seed):
        return (matches(seed, self.ship, self.want, self.avoid, self.gamedata)
                and (not self.look or textures.look_matches(seed, self.look))
                and (not self.paint or textures.hull_takes_paint(seed, self.ship))
                and (not self.overlay or textures.overlay_of(seed) in self.overlay))


# Batches are kept small on purpose. A million seeds at a time is 8 MB an array, which
# falls out of cache and leaves every worker waiting on memory; at 65536 the whole pass
# stays in L2 and eight workers go nearly eight times as fast as one. Measured on a
# 7840HS: 17 M seeds/s a core at 2^19, 19 M at 2^16, and 104 M across 12 workers.
WORKER_BATCH = 1 << 16


def default_workers() -> int:
    """Processes for a seed search: three quarters of the cores.

    Past that the gain is in the noise -- the work is memory-bound, not compute-bound --
    and leaving a couple of cores alone keeps the rest of the app responsive.
    """
    return max(1, (os.cpu_count() or 2) * 3 // 4)


_W: dict = {}       # per-process state of the search workers: one compiled search each
_POOL: dict = {}    # the workers outlive any one search, so only the first search waits for them
_POOL_LOCK = threading.Lock()


def _worker_init():
    _W["rng"] = np.random.default_rng()


def _worker_batch(args):
    key, kw, rounds, size = args
    scan = _W.get(key) or _W.setdefault(key, _Scanner(**kw))
    hits, near = [], 0
    for _ in range(rounds):
        got, n = scan.batch(_W["rng"], size)
        hits += got
        near += n
    return rounds * size, hits, near


def _pool(workers):
    """The spawn pool, started once. Each worker compiles a design the first time it sees one."""
    with _POOL_LOCK:
        if _POOL.get("n") != workers:
            if _POOL.get("pool"):
                _POOL["pool"].terminate()
            import multiprocessing as mp
            _POOL.update(n=workers, pool=mp.get_context("spawn").Pool(workers, _worker_init))
        return _POOL["pool"]


@atexit.register
def _close_pool():
    """Shut the workers down on the way out. Left to the garbage collector they go after
    their own pipes have been closed, and Windows prints a handle error for each one."""
    pool = _POOL.pop("pool", None)
    if pool:
        pool.terminate()
        pool.join()


def warm_up(workers: int | None = None):
    """Start the search workers ahead of the first search, which otherwise waits for them."""
    _pool(default_workers() if workers is None else max(1, workers))


def _running(stats, t0, max_seeds, time_limit, should_stop):
    return (stats["tested"] < max_seeds and not (time_limit and time.time() - t0 > time_limit)
            and not (should_stop and should_stop()))


def _one_process(scan, rng, batch, stats, t0, *rest):
    rng = rng or np.random.default_rng()
    while _running(stats, t0, *rest):
        hits, near = scan.batch(rng, batch)
        stats["tested"] += batch
        stats["wrong_colour"] += near
        stats["seconds"] = time.time() - t0
        yield from hits


def _many_processes(kw, workers, batch, stats, t0, *rest):
    """Hand every worker two jobs at a time, so none of them ever sits waiting on us."""
    rounds = max(1, (1 << 23) // batch)  # ~8 M seeds a job: a fraction of a second of work
    job = (repr(sorted(kw.items(), key=str)), kw, rounds, batch)
    pool, pending = _pool(workers), []
    try:
        while True:
            while len(pending) < workers * 2 and _running(stats, t0, *rest):
                pending.append(pool.apply_async(_worker_batch, (job,)))
            if not pending:
                return
            tested, hits, near = pending.pop(0).get()
            stats["tested"] += tested
            stats["wrong_colour"] += near
            stats["seconds"] = time.time() - t0
            yield from hits
    finally:
        for p in pending:  # let the jobs already out there land, so the next search starts clean
            try:
                p.get()
            except Exception:
                pass


def fast_search(ship="fighter", want=(), avoid=(), limit=5, max_seeds=10 ** 11, batch=WORKER_BATCH,
                time_limit=None, rng=None, stats=None, should_stop=None, gamedata=None, look=None,
                paintable=False, overlay=None, workers=1):
    """Yields (seed, [(group_type, part_id), ...]) for seeds meeting want/avoid and `look`
    ({"primary"/"secondary"/"undercoat": colour indices, "mode": hull texture modes}).
    paintable keeps only interceptor seeds whose overlay reads the paint rather than
    colouring itself. If given, stats (a dict) receives 'tested' and 'seconds';
    should_stop() is polled between batches to cancel. When a colour is asked for, stats
    also gets 'wrong_colour': seeds that had every part and the wrong colour anyway.

    workers spreads the search over that many processes, 0 for all but one core. A design
    with twenty parts pinned is one seed in billions and a single core tests about fifteen
    million a second, so the cores are the difference between a wait and an afternoon."""
    kw = dict(ship=ship, want=tuple(want), avoid=tuple(avoid), gamedata=gamedata, look=look,
              paintable=paintable, overlay=overlay)
    scan = _Scanner(**kw)  # also rejects unknown part ids before any process starts
    stats = {} if stats is None else stats
    stats.update(tested=0, seconds=0.0, wrong_colour=0)
    t0, found = time.time(), 0
    n = default_workers() if workers == 0 else max(1, int(workers))
    rest = (max_seeds, time_limit, should_stop)
    candidates = (_many_processes(kw, n, WORKER_BATCH, stats, t0, *rest) if n > 1
                  else _one_process(scan, rng, batch, stats, t0, *rest))
    for s in candidates:
        if scan.confirm(s):
            found += 1
            yield s, generate(s, ship, gamedata)
            if found >= limit:
                return


def make_filter(ship, want=(), avoid=(), gamedata=None, look=None):
    """check(seeds) -> the seeds meeting want/avoid (vectorised pre-filter, exact confirmation)."""
    scan = _Scanner(ship=ship, want=tuple(want), avoid=tuple(avoid), gamedata=gamedata, look=look)

    def check(seeds):
        if not seeds:
            return []
        arr = np.array(seeds, dtype=np.uint64)
        with np.errstate(over="ignore"):
            st = _state(arr)
            mask = _eval(scan.plan, *st) if scan.plan else np.ones(len(arr), bool)
            if look:
                mask &= textures.look_mask(*st, look)
        return [s for s, ok in zip(seeds, mask) if ok and scan.confirm(s)]
    return check


def fast_accepts(seeds, ship, want=(), avoid=(), gamedata=None):
    """Vectorised accept mask for given seeds (used to validate against the exact generator)."""
    root = load_descriptor(resolve_root(ship, gamedata), gamedata)
    want, avoid = _closure(root, set(want), gamedata), set(avoid)
    plan = _compile(root, want, avoid, gamedata)
    arr = np.array([parse_seed(s) for s in seeds], dtype=np.uint64)
    with np.errstate(over="ignore"):
        return _eval(plan, *_state(arr)) if plan else np.ones(len(arr), bool)
