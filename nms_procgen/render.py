"""Ship previews composed from per-part renders (data/renders/<ship>/).

Each render is a full-frame image of one part, so stacking the parts a seed
picks gives the whole ship. Sentinel renders come from nms.center.
"""
import functools
import io
import json
import os

from PIL import Image, ImageOps

from .generator import part_ids

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "renders")


@functools.lru_cache(maxsize=None)
def _index(ship):
    path = os.path.join(ROOT, ship, "index.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


@functools.lru_cache(maxsize=1024)
def _layer(ship, filename):
    return Image.open(os.path.join(ROOT, ship, filename)).convert("RGBA")


def available(ship):
    return bool(_index(ship))


def render_parts(parts, ship="sentinel", size=None, mirror=False):
    """PIL image of the given part ids stacked in order, or None if nothing to draw.
    Index entries are filenames, or {"file", "requires"} drawn only when every
    required (parent) part is also present."""
    index, canvas, present = _index(ship), None, set(parts)
    for pid in parts:
        for entry in index.get(pid, []):
            filename, requires = (entry, ()) if isinstance(entry, str) else (entry["file"], entry.get("requires", ()))
            if not all(r in present for r in requires):
                continue
            layer = _layer(ship, filename)
            canvas = canvas or Image.new("RGBA", layer.size, (0, 0, 0, 0))
            if layer.size == canvas.size:
                canvas.alpha_composite(layer)
    if canvas is None:
        return None
    box = canvas.getbbox()
    img = canvas.crop(box) if box else canvas
    if mirror:
        img = ImageOps.mirror(img)
    if size:
        img.thumbnail((size, size))
    return img


def to_png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@functools.lru_cache(maxsize=256)
def seed_png(seed, ship="sentinel", size=512, mirror=False):
    img = render_parts(part_ids(seed, ship), ship, size, mirror)
    return to_png(img) if img else None
