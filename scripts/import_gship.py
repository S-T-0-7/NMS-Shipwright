"""Import the gShip seed table into data/real_ships.csv.

gShip ("Gumsk's Custom Ships", https://www.nexusmods.com/nomanssky/mods/1891)
is a real, actively-maintained community mod (29k+ unique downloads as of
writing) that makes the "Golden Vector" reward-ship slot procedural and
attaches 70+ hand-built custom ship models to it (X-Wing, Enterprise,
TARDIS, Klingon Bird of Prey, Cylon Raider, ...), each keyed by a specific
seed value documented on the mod page.

This is real, working "edit the existing ship via a mod" -- not a seed
search, an actual PAK data mod -- but it's a GAME-files mod, not a
save-file trick: it requires the user to download gShip's .pak from
NexusMods themselves (we don't auto-download third-party files) and drop
it in <NMS install>/GAMEDATA/PCBANKS/MODS/.

Without that mod installed, these seeds do exactly what any other seed on
a fixed-model slot does: nothing visually (see nms_save/ships.py's
FIXED MODEL warning) -- they only work on the Golden Vector slot,
and only once gShip's PAK is present.

Seed table transcribed from the mod page (version 5.2.9.0a, checked
2026-09-11). Re-run this script after checking the mod page again if
Gumsk has added more ships since.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nms_save import catalog  # noqa: E402

MOD_NAME = "gShip - Gumsk's Custom Ships (NexusMods #1891)"

# (seed, description) -- seed 0x1 is the vanilla Golden Vector itself, kept
# here for completeness/documentation even though it needs no mod.
GSHIP_TABLE = [
    ("0x1", "Golden Vector (vanilla default)"),
    ("0x3", "Serenity - from Firefly/Serenity"),
    ("0x2D", "Serenity Gold - from Firefly/Serenity"),
    ("0x3E", "Serenity Two-Tone - from Firefly/Serenity"),
    ("0x1F", "N1 Mando - from Star Wars"),
    ("0x69", "Razor Crest - from Star Wars"),
    ("0x22", "X-Wing Dark - from Star Wars"),
    ("0xB", "X-Wing White - from Star Wars"),
    ("0x5", "Jedi Interceptor Yellow - from Star Wars"),
    ("0x6", "Jedi Interceptor Green - from Star Wars"),
    ("0x47", "Jedi Interceptor Red - from Star Wars"),
    ("0x30", "Jedi Interceptor Blue - from Star Wars"),
    ("0x52", "Jedi Interceptor Orange - from Star Wars"),
    ("0x62", "TIE Silencer - from Star Wars"),
    ("0x34", "TIE Phantom - from Star Wars"),
    ("0x4E", "TIE Defender - from Star Wars"),
    ("0x57", "TIE Advanced - from Star Wars"),
    ("0x1B", "TIE Interceptor - from Star Wars"),
    ("0x25", "TIE Interceptor Red - from Star Wars"),
    ("0x4B", "TIE Hunter - from Star Wars"),
    ("0xA", "Droid Tri-Fighter - from Star Wars"),
    ("0x5D", "Imperial Shuttle - from Star Wars"),
    ("0x1D", "Sith Fury Interceptor - from Star Wars"),
    ("0x67", "Slave I Firespray - from Star Wars"),
    ("0x6D", "Slave I Firespray UA - from Star Wars"),
    ("0xF", "Y-Wing B-Type - from Star Wars"),
    ("0x27", "X-70B Phantom - from Star Wars"),
    ("0x60", "X-70B Phantom x2.5 Size - from Star Wars"),
    ("0x20", "E-Wing - from Star Wars"),
    ("0x32", "V-Wing - from Star Wars"),
    ("0x65", "A-Wing - from Star Wars"),
    ("0x3B", "Enterprise D - from Star Trek"),
    ("0x84", "Defiant - from Star Trek"),
    ("0x46", "Danube Shuttle - from Star Trek"),
    ("0x37", "Federation Attack Fighter - from Star Trek"),
    ("0x16", "Klingon Bird of Prey - from Star Trek"),
    ("0x12", "Batwing - from Arkham Knights"),
    ("0x3D", "Milano - from Marvel"),
    ("0x29", "Milano Captain Marvel Variant - from Marvel"),
    ("0x19", "Viper Mk II - from Battlestar Galactica"),
    ("0x8", "Cylon Raider - from Battlestar Galactica"),
    ("0x7", "Star Fury - from Babylon 5"),
    ("0x9", "Shadow - from Babylon 5"),
    ("0x6E", "Whitestar - from Babylon 5"),
    ("0x70", "Swordfish II - from Cowboy Bebop"),
    ("0x28", "Gundam Sazabi"),
    ("0x66", "Gundam Sazabi Blue"),
    ("0x44", "Gundam Sazabi Pink"),
    ("0x7D", "Space Dart I - from LEGO"),
    ("0x10", "Space Scooter - from LEGO"),
    ("0xD", "Phantom - from Halo"),
    ("0x2F", "Pelican - from Halo"),
    ("0xC", "Pelican White - from Halo"),
    ("0x64", "T.A.R.D.I.S. - from Doctor Who"),
    ("0x4E", "Hocotate Rocket - from Pikmin"),  # note: mod page lists this seed twice (also TIE Defender); as documented
    ("0x6B", "Cosmo Zero - from Space Battleship Yamato"),
    ("0x24", "Cosmo Tiger II - from Space Battleship Yamato"),
    ("0x42", "Max - from Flight of the Navigator"),
    ("0x3F", "Samus Aran's Gunship - from Metroid"),
    ("0x2B", "Arwing - from Star Fox"),
    ("0x2", "Star Viper"),
    ("0x4", "Blade Starship"),
    ("0x36", "SR71 Blackbird"),
    ("0x39", "Malovsky Gunship"),
    ("0x5E", "Molnia Racer"),
    ("0x56", "Avem de Paradiso"),
    ("0x40", "Unitron"),
    ("0xE", "Unitron Black and Blue"),
    ("0x18", "Atlas Core"),
    ("0x54", "Police / Sentinel Ship"),
    ("0x26", "Gaseous Sentience (WEIRDOBJECT5)"),
    ("0x5B", "Drone"),
    ("0x49", "Living Metalloid (WEIRDOBJECT2)"),
    ("0x4D", "Corrupted Drone"),
    ("0x11", "Dyson Lens"),
    ("0x50", "Stellar Intelligence (WEIRDOBJECT3)"),
    ("0x72", "Ironbound Relic (SPACEGYROSCOPE)"),
]


def main():
    added = skipped = 0
    for seed, description in GSHIP_TABLE:
        ok = catalog.add_row(
            seed,
            type="Golden Vector Mod",
            description=description,
            source="gShip mod page",
            requires_mod=MOD_NAME,
        )
        if ok:
            added += 1
        else:
            skipped += 1

    print(f"[DONE] Added {added} gShip entries, skipped {skipped} already-present.")
    print("Reminder: these only work once gShip's PAK is installed in")
    print("<NMS install>/GAMEDATA/PCBANKS/MODS/, and only on a ship whose")
    print("Filename is FIGHTERCLASSICGOLD.SCENE.MBIN (the Golden Vector slot).")


if __name__ == "__main__":
    main()
