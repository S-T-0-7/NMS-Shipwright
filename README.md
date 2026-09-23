# NMS Ship Studio

A Windows app for designing, finding and editing No Man's Sky starships, plus a general save
editor. It reads the ship generator out of your own copy of the game, so a seed in the app builds
exactly the ship the game builds.

## What it does

**Ships**
- Design a ship part by part, with a 3D preview that builds up as you choose. Cockpit, wings,
  chin, skirt, thrusters and the rest, named the way the community names them.
- Find a seed that builds your design. The search runs on all cores and tests millions of seeds a
  second, with a live estimate of how long it will take.
- Find that ship in a real star system near you, if you would rather fly to it than edit it in.
- Put a design straight into your save: as a new ship, or over one you already own.
- Recolour any ship, with the game's real paint sets and a live preview.
- Save designs as files and share them.

**Save editing**
- Inventories: add, remove and fill any item, technology or substance, repair and recharge, unlock
  slots.
- Unlock recipes, blueprints, words, milestones, expedition and Twitch rewards.
- Multi-tools, freighters, frigates, companions.
- Export and import the save as JSON, plus a raw editor for anything not covered by a screen.

Every write makes a timestamped backup next to your save first, and is refused while the game is
running, because the game would overwrite it.

## Install

1. Download `NMS Ship Studio Setup.exe` from the [releases page](../../releases).
2. Run it. Windows will warn that it is from an unknown publisher (the app is not code-signed):
   choose **More info → Run anyway**.
3. It installs for your user only, into `%LOCALAPPDATA%\Programs\NMS Ship Studio`, and adds a
   Start menu entry. No admin rights, no Python, nothing else to install.

To remove it: Settings → Apps → NMS Ship Studio, or run `Uninstall.exe` from the install folder.

## First run

The app looks for No Man's Sky by itself (Steam, including extra library drives, GOG and the
Microsoft Store). If your copy is somewhere unusual, open **Save → Game data** and choose the
folder that contains `Binaries\NMS.exe`.

It then reads what it needs out of your game's own archives and keeps the copies in
`%LOCALAPPDATA%\NMS Ship Studio\gamecache`. After a game update it notices and reads them again,
so new parts and items appear without a new version of this app.

## Is this safe to use?

- It never touches the running game, and refuses to write while the game is open.
- It backs up your save before every change.
- It does not modify any game file, so your save is not marked as modded.
- Your save is yours: nothing is uploaded anywhere. The app has no network access at all.

## Building it yourself

Requires Windows, Python 3.11+ and No Man's Sky installed.

```
pip install -r requirements.txt
python scripts/build_app.py          # dist/NMS Ship Studio Setup.exe
python -m unittest tests.test_robustness
```

`python webapp/app.py` runs the same thing in a browser at http://localhost:5000 for development.

## What is not included

No game files are shipped with this app, and none are redistributed. Ship part data, item tables,
3D models and language text are all read from your own installed copy of No Man's Sky at runtime.

The app uses [hgpaktool](https://pypi.org/project/hgpaktool/) to read the game's archives and
[Unicorn](https://www.unicorn-engine.org/) to run the game's own generator code offline.

## Credits and licence

Part names follow the community naming charts (Nerozii's Sentinel Interceptor chart and the
nms.center part lists). Thanks to everyone who mapped those out.

This project is not affiliated with Hello Games. No Man's Sky is their trademark.

Released under the MIT Licence; see [LICENSE](LICENSE).
