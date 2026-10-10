"""Build "NMS Shipwright.exe" (PyInstaller, one folder) and its installer "NMS Shipwright Setup.exe".

    python scripts/build_app.py                 # app + dist/NMS Shipwright Setup.exe
    python scripts/build_app.py --no-installer  # app only
    python scripts/build_app.py --shortcuts     # also point Desktop / Start menu shortcuts at dist/ (development)

The app lands in dist/NMS Shipwright/. It needs no Python, only the Edge WebView2
runtime that Windows 10/11 already ship. Copies of game files it extracts go to
%LOCALAPPDATA%/NMS Shipwright/gamecache, so rebuilding keeps them.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "NMS Shipwright"
STACK = 16 * 1024 * 1024
# (source, folder inside the app). Nothing from the game is shipped: the ship part data is copied
# out of the player's own install the first time it is needed.
DATA = [
    ("webapp/static", "webapp/static"),
    ("data/palettes", "data/palettes"),
    ("data/special_ships", "data/special_ships"),
    ("data/mapping.json", "data"),
    ("nms_procgen/names", "nms_procgen/names"),
    ("nms_procgen/designs", "nms_procgen/designs"),
    ("nms_procgen/test_vectors.json", "nms_procgen"),
]


def make_icon(path):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), 48, fill=(14, 16, 20, 255))
    d.ellipse((58, 58, 198, 198), fill=(232, 84, 62, 255))
    d.polygon([(128, 70), (176, 170), (128, 148), (80, 170)], fill=(255, 255, 255, 255))
    img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


def build(console=False):
    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    icon = work / "app.ico"
    make_icon(icon)
    args = [sys.executable, "-m", "PyInstaller", str(ROOT / "nms_editor.py"), "--name", NAME, "--noconfirm", "--clean",
            "--console" if console else "--windowed", "--onedir", "--icon", str(icon), "--distpath", str(ROOT / ("dist-debug" if console else "dist")),
            "--workpath", str(work), "--specpath", str(work),
            "--collect-all", "unicorn", "--collect-all", "hgpaktool", "--collect-submodules", "webview",
            "--exclude-module", "PIL", "--exclude-module", "pandas", "--exclude-module", "tkinter",
            "--hidden-import", "webapp.app", "--paths", str(ROOT)]
    for src, dest in DATA:
        if not (ROOT / src).exists():
            print(f"skipping {src} (not in this checkout)")  # e.g. the scraped ship catalogue
            continue
        args += ["--add-data", f"{ROOT / src}{os.pathsep}{dest}"]
    subprocess.run(args, check=True, cwd=ROOT)
    exe = ROOT / ("dist-debug" if console else "dist") / NAME / f"{NAME}.exe"
    if not exe.exists():
        sys.exit("build failed: exe not found")
    fix_pe(exe)
    return exe


def fix_pe(exe, size=STACK):
    # stack -> 16MB (emu overflows 2MB) + strip CFG (kills proc when unicorn hits JIT'd code).
    # WARN: dont remove, else packaged app dies w/ exit 127, no err.
    import pefile
    pe = pefile.PE(str(exe))
    pe.OPTIONAL_HEADER.SizeOfStackReserve = size
    pe.OPTIONAL_HEADER.DllCharacteristics &= ~0x4000  # IMAGE_DLLCHARACTERISTICS_GUARD_CF
    pe.OPTIONAL_HEADER.CheckSum = pe.generate_checksum()
    data = pe.write()
    pe.close()
    exe.write_bytes(data)


def build_installer(app_exe):
    """Zip the app folder into a one-file Setup.exe (see scripts/installer.py) plus a small Uninstall.exe."""
    import zipfile
    work, app_dir = ROOT / "build", app_exe.parent
    bundle = work / "app.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in app_dir.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(app_dir))
    common = [sys.executable, "-m", "PyInstaller", str(ROOT / "scripts" / "installer.py"), "--noconfirm", "--onefile",
              "--windowed", "--icon", str(work / "app.ico"), "--workpath", str(work / "installer"),
              "--specpath", str(work / "installer"), "--add-data", f"{work / 'app.ico'}{os.pathsep}."]
    subprocess.run(common + ["--name", "Uninstall", "--distpath", str(work / "installer")], check=True, cwd=ROOT)
    subprocess.run(common + ["--name", f"{NAME} Setup", "--distpath", str(ROOT / "dist"),
                             "--add-data", f"{bundle}{os.pathsep}.",
                             "--add-data", f"{work / 'installer' / 'Uninstall.exe'}{os.pathsep}."], check=True, cwd=ROOT)
    setup = ROOT / "dist" / f"{NAME} Setup.exe"
    bundle.unlink()
    return setup


def shortcuts(exe):
    places = [Path(os.environ["USERPROFILE"]) / "Desktop",
              Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    for folder in places:
        lnk = folder / f"{NAME}.lnk"
        ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
              f"$s.TargetPath = '{exe}'; $s.WorkingDirectory = '{exe.parent}'; $s.IconLocation = '{exe},0'; $s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        print("shortcut:", lnk)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-installer", action="store_true")
    ap.add_argument("--shortcuts", action="store_true", help="point Desktop / Start menu shortcuts at dist/ instead of installing")
    ap.add_argument("--console", action="store_true", help="debug build with a console window (dist-debug/)")
    a = ap.parse_args()
    exe = build(a.console)
    print("built:", exe)
    if a.shortcuts and not a.console:
        shortcuts(exe)
    if not (a.no_installer or a.console):
        print("installer:", build_installer(exe))
