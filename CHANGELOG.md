# Changelog

## 1.8.6

- **Fly button**: the ship viewer now shows a ship landed or flying -- landing legs tucking up
  into the hull, a Sentinel spreading its wings. It is under the My Ships viewer and the Designer
  preview. Works for Sentinel interceptors, Fighters, Explorers and Shuttles; ships it cannot do
  yet simply show no button.
- The movement is read out of the game's own takeoff animations, so the flying shape is the
  game's rather than a guess.
- **Ship guns are drawn now**, under the wing and pointing forward. They were missing before.
- A parked ship looks exactly as it did, so nothing changes until you press Fly.
- **Paint every part of a ship.** Recolour offered a body colour and a trim, and quietly wrote
  that trim into all four of the game's other paint slots -- so signage, small signs and the
  tertiary trim were forced to one colour. The game gives a ship **five** paint slots and draws a
  different handful of them per ship, so Recolour now asks which ones your ship actually draws
  and offers exactly those, each named for what it paints: body, markings, signage, small signs,
  trim. A Sentinel interceptor puts its two on different layers from every other ship, so it
  gets **body** and **trim**, or just the whole ship on seeds with no second colour.
- **Recolour works on Sentinel interceptors, in any paint set.** 1.8.5 forced them to the
  metallic set, believing the game drew nothing else on an interceptor. It does: an interceptor
  painted from the Freighter set comes out that colour, **including true black**, which the
  metallic set has not got. Every set is offered again for every ship. An unpainted interceptor
  is also not "default red" as the old note claimed -- it wears the colour its seed gives it,
  which runs from black through orange to near-white.

- **"Where to find it in the game" no longer invents a star system.** A seed can be run back
  through the generator to the system that made it, but nothing in a seed says how far back that
  system is, so the search tries thousands of distances and any one of them can land on an address
  that merely looks real. Better than one seed in ten was given a home it never had -- fly there
  and a different ship is parked at it. Every candidate is now generated and checked before you
  are shown it, and the app says what is actually waiting: "Waiting at the space station as a
  hauler", "Waiting at the crash site as a sentinel interceptor". 45 of 400 random seeds used to
  be handed a system; of 3,000 put through the new check, none were.
- **Says when a Sentinel seed paints over your paint.** One interceptor seed in four draws an
  opaque layer of its own on top of the base coat, coloured from the seed and not settable from
  a save, so the ship keeps the colour it had however you paint it. That is the long-standing
  "Sentinels won't repaint" complaint, and it is a quarter of seeds rather than all of them.
  Recolour says so above the colours and the Designer marks those seeds **SEED COLOUR ONLY**,
  so you can pick one of the three in four that builds the same ship and paints properly.

- **Smaller download.** The build was shipping the static library and C headers from the
  emulator package -- 50 MB of what you would link a C program against, sitting next to the
  library the app actually loads and opened by nothing. The Windows installer drops from 27 MB
  to 23 MB, and the Linux AppImage loses its own copy of the same thing. The Linux build is
  also packed with xz rather than zstd: a little slower to unpack the first time it runs, and
  smaller to download.

- **The Designer can insist on a seed you can paint.** Which overlay an interceptor wears comes
  off a single draw from its seed, and so do its parts, so the two are tied together: a Stinger
  top flap paints on 58% of seeds against 92% with no top flap. Tick **Only seeds I can paint**
  and the search skips the rest -- it costs nothing, being four more numbers per seed.

- **Quests read as quests now**, not as mission ids. The game names a storyline rather than its
  steps -- all six steps of "Alone Amidst the Stars" share that one title -- so every row used to
  say `ACT1_STEP3`. Each step is now labelled with the line the game writes into your log when you
  reach it, with the id kept as a tag underneath, and a storyline's heading carries its subtitle.
  Names the game fills in as you play ("Trade Surge: %SYSTEM% System") were being thrown away
  whole for having a blank in them, which cost 46 quests their name; they are back. The internal
  helper quests the game never names keep their id as written rather than being dressed up.
- **The 3D viewer's buttons moved onto the model.** The angles are one control in the bottom
  corner, and spin and landed/flying are icons in the top corner that light up when they are on,
  so the ship gets the whole box. The New ship preview has them too, which it never did.
- **One set of buttons across the app**: icons on the ones worth an icon, a single highlighted
  button for whatever a panel is really for, and red for anything that throws work away (Remove
  this ship, Remove my paint, Empty slot), so they stop all looking equally safe.
- The Designer's three rows of buttons are grouped and labelled, with installing a design into
  your save set apart as its own step, and the seed search says which of its two searches is
  which. Inventory separates the bulk fixes from the slot count. The menu carries page icons.

## 1.8.5

- The Designer preview no longer **jumps back to the default angle** every time you pick a part --
  it keeps the angle and zoom you set, so you can line up a front-only part and add pieces without
  the view snapping around. Double-click resets it, and there are now **angle buttons** (Front,
  Side, Top, Back, 3/4, Spin) under the preview, the same as the My Ships viewer.
- The **version number** now shows at the bottom of the left-hand menu, so after an update you can
  tell at a glance which build you have installed.
- **Find a ship by colour**: Design & Find now takes a colour as well as parts, for Sentinel
  interceptors too, and "Find in game" returns the real systems whose ship is that colour, with the
  portal glyphs to fly there and claim it. A Sentinel's colour comes from its seed, so this is how
  you get, say, a white interceptor -- search for one and go find it. The system scan also reaches a
  bit further out.
- **Sentinel recolour** actually shows up now. The game only draws the metallic palette on an
  interceptor -- colours from any other paint set are saved but never rendered, so the ship kept
  its default red/orange. Recolour now uses metallic paints for Sentinels, and says so.
- **Linux support**: there is now a Linux build (an AppImage) alongside the Windows installer, both
  attached to each release. It finds No Man's Sky through Steam/Proton -- including the save inside
  the game's Proton prefix -- and opens in your browser instead of a native window.
- Notifications float on their own layer now, so a pop-up no longer pushes the page around, and the
  app has had a visual tidy-up (cleaner cards, buttons and spacing).

## 1.8.4

- Fixed **seed search**: it was crashing with an internal error for every ship that has a colour
  seed (fighter, hauler, explorer, shuttle, exotic, solar), so no design search could run. It works
  again.
- Tech the tool fits to a ship (making or converting one -- especially to a Sentinel interceptor)
  is now marked as known in your save, so the game keeps it instead of stripping it the next time
  the save loads.
- New installer: smaller download (about 25 MB instead of 60) and a standard Windows setup, with a
  proper entry in Settings > Apps and a clean uninstaller. The app itself is unchanged.

## 1.8.3

- **Starborn Phoenix**: the special ship now appears in the New ship type list (My Ships -> New
  ship) marked with a ★, and spawns exactly as it is -- its own model, S-class stats and tech.
- Exotic ships now build correctly: the **Royal** and **Squid** families render as separate ships
  instead of the squid showing on top of everything, so exotics can be designed part by part like
  any other type. (The game truncates part names, which the 3D view was not accounting for.)
- **Remove ship**: a ship page now has a Remove button (under More) to empty its slot. A backup is
  made first; undo it from Save > Backups.
- Fixed an error when choosing the game-data folder (an internal name was not in scope). The folder
  was still set, but it popped an error.

## 1.8.2

- Fixed a crash on opening some saves -- a save carrying a byte that is not valid UTF-8 would fail
  with "'utf-8' codec can't decode byte 0x80". Such saves now load and edit normally.
- The New ship panel has a **Cancel** button (and an ✕) to close it without making any changes.

## 1.8.1

- New ship (My Ships → New ship): you can now pick **any** slot, not just empty ones -- choosing a
  slot that already holds a ship replaces it and keeps its inventory & tech. "Copy inventory & tech
  from" is optional now: leave it on **Standard** for a fresh, empty ship instead of a copy.
- Fixed the **Game data → Choose...** button, which did nothing when clicked. It now opens the
  folder picker.
- Ship parts read clearly everywhere: tidy labels for every ship type (no more raw ids), and named
  shapes for the distinct parts (solar sails, hauler cockpits and wings, and more).
- Picking a part in the Designer now fills the preview instead of showing it tiny inside the whole
  ship.

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
