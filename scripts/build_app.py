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
sys.path.insert(0, str(ROOT))
from webapp.version import VERSION  # noqa: E402  (one place for the version; the app shows it too)

NAME = "NMS Shipwright"
WINDOWS = os.name == "nt"
EXE = f"{NAME}.exe" if WINDOWS else NAME  # PyInstaller drops the .exe on Linux
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
    img.save(Path(path).with_suffix(".png"))  # Linux / AppImage wants a PNG


def version_file(orig_filename, description):
    """A version/company resource for the exe, so scanners stop treating an unsigned exe as nameless."""
    v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    txt = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Shikhar Tiwari'),
      StringStruct('FileDescription', '{description}'),
      StringStruct('FileVersion', '{VERSION}.0'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('LegalCopyright', 'Shikhar Tiwari. Open-source; bundles GPL-licensed components.'),
      StringStruct('OriginalFilename', '{orig_filename}'),
      StringStruct('ProductName', '{NAME}'),
      StringStruct('ProductVersion', '{VERSION}.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)"""
    p = ROOT / "build" / (orig_filename + ".version.txt")
    p.parent.mkdir(exist_ok=True)
    p.write_text(txt, encoding="utf-8")
    return str(p)


def build(console=False):
    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    icon = work / "app.ico"
    make_icon(icon)
    args = [sys.executable, "-m", "PyInstaller", str(ROOT / "nms_editor.py"), "--name", NAME, "--noconfirm", "--clean",
            "--console" if console else "--windowed", "--onedir", "--distpath", str(ROOT / ("dist-debug" if console else "dist")),
            "--workpath", str(work), "--specpath", str(work),
            "--collect-all", "unicorn", "--collect-all", "hgpaktool",
            "--exclude-module", "PIL", "--exclude-module", "pandas", "--exclude-module", "tkinter",
            "--hidden-import", "webapp.app", "--paths", str(ROOT)]
    if WINDOWS:  # the native window (WebView2) and exe metadata are Windows-only; Linux uses the browser
        args += ["--icon", str(icon), "--collect-submodules", "webview",
                 "--version-file", version_file(EXE, "NMS Shipwright - No Mans Sky ship designer and save editor")]
    else:
        args += ["--exclude-module", "webview"]
    for src, dest in DATA:
        if not (ROOT / src).exists():
            print(f"skipping {src} (not in this checkout)")  # e.g. the scraped ship catalogue
            continue
        args += ["--add-data", f"{ROOT / src}{os.pathsep}{dest}"]
    subprocess.run(args, check=True, cwd=ROOT)
    exe = ROOT / ("dist-debug" if console else "dist") / NAME / EXE
    if not exe.exists():
        sys.exit("build failed: exe not found")
    if WINDOWS:  # Linux uses the thread stack set in nms_editor.main(); PE/CFG don't apply
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


def find_iscc():
    """Locate the Inno Setup command-line compiler (ISCC.exe)."""
    import shutil
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            cand = Path(base) / "Inno Setup 6" / "ISCC.exe"
            if cand.exists():
                return str(cand)
    return None


def build_installer(app_exe):
    """Compile the Inno Setup installer around the built app folder (installer/nms_shipwright.iss)."""
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup not found. Install it (choco install innosetup, or jrsoftware.org/isdl.php).")
    app_dir = app_exe.parent  # dist/NMS Shipwright
    subprocess.run([iscc, f"/DAppSrc={app_dir}", f"/DOutDir={ROOT / 'dist'}",
                    f"/DIcon={ROOT / 'build' / 'app.ico'}", f"/DAppVer={VERSION}",
                    str(ROOT / "installer" / "nms_shipwright.iss")], check=True, cwd=ROOT)
    setup = ROOT / "dist" / f"{NAME} Setup.exe"
    if not setup.exists():
        sys.exit("installer build failed: Setup.exe not found")
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
        if WINDOWS:
            print("installer:", build_installer(exe))
        else:
            print("app folder:", exe.parent, "-- run scripts/build_appimage.sh to package it")
