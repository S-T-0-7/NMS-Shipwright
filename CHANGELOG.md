# Changelog

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
