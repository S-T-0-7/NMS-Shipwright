"""Import nms.center part renders and part names for the editor (personal, local use).

    python scripts/import_nmscenter_assets.py <folder containing FIGHTER.js, DROPSHIP.js, ...>

Each image label is matched to our part ids: directly, with a trailing index
removed, or as parent+child ("WINGSK_A_SUBWINGS_A": child drawn only when the
parent is present). Writes data/renders/<ship>/ and nms_procgen/names/<ship>.json.
Sentinel assets were imported separately (exact tree match) and are left alone.
"""
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nms_procgen import preorder_options  # noqa: E402

TYPES = {"FIGHTER": "fighter", "DROPSHIP": "hauler", "EXPLORER": "explorer", "SHUTTLE": "shuttle",
         "ROYAL": "exotic", "BIOSHIP": "living", "SOLAR": "solar"}
VIEWS = {"LEFT", "RIGHT"}


def their_labels(text):
    """nms.center's own pre-order option labels ("<Name>_<n>") from its DESCRIPTOR tree."""
    i = text.find('DATA[THIS_TYPE]["DESCRIPTOR"]')
    if i < 0:
        return []
    j, depth = text.index("[", text.index("=", i)), 0
    for k in range(j, len(text)):
        depth += text[k] == "["
        depth -= text[k] == "]"
        if depth == 0:
            break
    out = []

    def walk(node):
        if isinstance(node, list):
            if node and node[0] == "TkResourceDescriptorData":
                out.append(node[1])
            for x in node:
                walk(x)

    walk(json.loads(re.sub(r",\s*\]", "]", text[j:k + 1])))
    return out


def match(label, ids, by_number=None):
    tokens = label.split("_")
    if tokens[-1] in VIEWS:
        tokens = tokens[:-1]
    if by_number is not None and len(tokens) == 1 and tokens[0].isdigit():  # "EXPLORER_6_LEFT" style
        pid = by_number.get(int(tokens[0]))
        return (pid, []) if pid else None
    candidates = [tokens] + ([tokens[:-1]] if len(tokens) > 1 and tokens[-1].isdigit() else [])
    for toks in candidates:
        whole = "_".join(toks)
        if whole in ids:
            return ids[whole], []
        for i in range(1, len(toks)):
            parent, child = "_".join(toks[:i]), "_".join(toks[i:])
            if parent in ids and child in ids:
                return ids[child], [ids[parent]]
    return None


def import_type(text, prefix, ship):
    ids, by_name = {}, {}
    for o in preorder_options(ship):
        ids.setdefault(o["id"].lstrip("_").upper(), o["id"])
        key = o["name"].upper()
        by_name[key] = o["id"] if key not in by_name else None  # None = ambiguous name
    # numbered labels point into nms.center's own (possibly older) tree: number -> name -> our id
    by_number = {n: by_name.get(re.sub(r"_\d+$", "", lab).upper()) for n, lab in enumerate(their_labels(text), 1)}
    out_dir = os.path.join(ROOT, "data", "renders", ship)
    os.makedirs(out_dir, exist_ok=True)
    index, unmatched = {}, []
    for m in re.finditer(r'\["%s_([A-Z0-9_]+)",\s*"([^"]+)"\]' % prefix, text):
        label, data = m.group(1), m.group(2)
        hit = match(label, ids, by_number)
        if not hit:
            unmatched.append(label)
            continue
        with open(os.path.join(out_dir, label + ".png"), "wb") as f:
            f.write(base64.b64decode(data.split(",", 1)[-1]))
        index.setdefault(hit[0], []).append({"file": label + ".png", "requires": hit[1]})
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, indent=0)

    names, i = {}, text.find('DATA[THIS_TYPE]["MAP"]')
    if i >= 0:
        for key, value in re.findall(r'"(_[^"]+?)"\s*:\s*"([^"]*)"', text[i:text.find("}", i)]):
            k = re.sub(r"_\d+$", "", key).lstrip("_").upper()
            if k in ids and value.strip():
                names.setdefault(ids[k], value.strip())
    if names:
        with open(os.path.join(ROOT, "nms_procgen", "names", f"{ship}.json"), "w") as f:
            json.dump([{"id": k, "name": v} for k, v in names.items()], f, indent=0)
    return len(index), sum(map(len, index.values())), len(unmatched), len(names)


def main(folder):
    for prefix, ship in TYPES.items():
        path = os.path.join(folder, prefix + ".js")
        if not os.path.exists(path):
            print(f"{prefix:9} skipped (no {prefix}.js)")
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            parts, images, unmatched, names = import_type(f.read(), prefix, ship)
        print(f"{prefix:9} -> {ship:9} {parts:4} parts, {images:4} images, {unmatched:3} unmatched, {names:3} names")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
