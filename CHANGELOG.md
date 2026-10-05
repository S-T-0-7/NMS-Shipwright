# Changelog

## 1.8.0 — first public release

Renamed to **NMS Shipwright**. Design, find and edit No Man's Sky ships, recolour them, and edit
your save -- everything read from your own copy of the game, nothing bundled. Works with the game
update of 1 October 2026.

## 1.7.7

- Works with the No Man's Sky update of 1 October 2026 (game build 88,545,352). The tool noticed
  the new build, re-read the game's files and re-found the generator addresses by itself; nothing
  in it needed changing for the new version.
- Fixed the deep health check, which could not reach the system generator after the code was
  split into modules.
- The nine known ships the generator is checked against are now part of the test suite, so a
  future update that changes how ships are built will be caught straight away.

## 1.7.6

- Changing a ship you already own is no longer hidden: "Change its parts" sits next to the seed on
  the ship's page, instead of inside the "More" section.
- Editing a ship now points "Into your save" at that same ship, so a seed you find replaces it
  rather than adding another one.
- Pinning all of a ship's parts makes the search hopeless (one ship in billions), so editing offers
  **Make it searchable**: it sets the fiddliest details back to "Any", cheapest first, until a
  result should take about two minutes. Those parts may come out different.

## 1.7.4

- Paint is now stored the way the game stores it: a palette and the index of the colour inside it.
  It used to store index -1 with a loose RGB value, which left the game to repaint the ship after
  building it -- visible in game as a flash of the ship's own colours before the paint appears.

## 1.7.3

- Ship stats (damage, shield, hyperdrive, manoeuvrability) can be read and edited on the ship page,
  along with the ship's class.
- The ranges come from the game's own table, per ship type and class, and edits outside them are
  refused: a class C fighter's damage bonus is 8 to 15, an S-class one's 70 to 90.
- "Best possible" sets every stat to the highest the game would ever roll for that ship and class.

## 1.7.2

- Inventories can gain and lose slots, not just "unlock everything": type a number and press Set,
  or click a cell to add or remove that one slot.
- The limits come from the game's own inventory table, per ship type and class: a C-class fighter
  tops out at 50 general slots, an S-class hauler at 120, multi-tools at 21 to 60, and so on.
- "Max" now fills to the game's real maximum instead of the visible grid.
- A slot holding something cannot be removed by accident: empty it first.

## 1.7.1

- Sentinel ships made by the tool now get the **Pilot Interface** (interceptors have one and no
  other ship does) and the game's own **interceptor mark**, the ROBOT_SHIP ship stat. Without that
  mark the game treats a ship with sentinel parts as an ordinary starship.
- Turning an interceptor back into a normal ship removes both again.
- The "wrong parts" warning on a ship page now only fires for parts belonging to the other kind of
  ship. A ship simply missing a part (a starter ship with no hyperdrive) is not a fault.

## 1.7.0 — first public release

The app now works on anyone's PC, and ships nothing that belongs to Hello Games or to anyone else.

- **Finds No Man's Sky by itself**: Steam (including games installed on other drives), GOG and the
  Microsoft Store. If your copy is somewhere unusual, Save → Game data has a folder picker.
- **No game data is included in the download.** Ship parts, item tables, models and text are read
  out of your own install the first time they are needed, and again after a game update.
- Ship pictures come from the built-in 3D viewer, so no part images are bundled either.
- The download is smaller: 66 MB instead of 90 MB.

### Ships
- The Designer preview now starts empty and adds each part as you pick it, instead of showing a
  complete ship from the start.
- Sentinel chin parts use the community chart names: Jowls, Block, Grill, Winch, Riot, and the
  Stolas, Clipper, Fang and Venom teeth. The chin lives under the "Wings" mid-section, which is now
  labelled so it is findable.
- New sentinel ships get interceptor equipment (Anti-Gravity Well, Luminance Engine, Crimson Core,
  Aeron Shield, Sentinel Cannon) and S class, instead of a copy of the donor ship's parts. Ships
  made before this can be fixed with "Fit its own parts" on the ship page.
- "Put in my save" works from every seed result: a new ship slot, or replacing one you own,
  changing the ship type when needed. The save is read back afterwards to prove the ship is there.
- Designs can be saved to files and opened again, and installed straight into a save.

### Searching
- The time limit is optional; searches run until you stop them.
- A live estimate shows the real speed and how long a result should take, from the odds of the
  design, weighted the way the game weights rare parts.

### Colours
- Recolour rebuilt: Body and Trim, every colour named, only the paint sets that apply to ships,
  and the 3D preview updates as you click.

### Robustness
- Copies of game files read while the game is updating are no longer treated as complete.
- Sharper shading, so flat panels no longer come out smeared.
- 18 automated tests, including a check that the app works with nothing bundled.
