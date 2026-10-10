"""NMS Shipwright Setup -- per-user installer and uninstaller (no admin rights needed).

Built into "NMS Shipwright Setup.exe" by `python scripts/build_app.py`, with the app folder
embedded as app.zip. Installing copies the app to %LOCALAPPDATA%\\Programs\\NMS Shipwright (or
a chosen folder), adds Desktop / Start menu shortcuts and an entry in Settings > Apps, and
copies this program next to the app as Uninstall.exe.

    "NMS Shipwright Setup.exe"                 wizard
    "NMS Shipwright Setup.exe" /S [/D=folder]  silent install
    Uninstall.exe --uninstall                   remove (asks first; /S for silent)
"""
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import winreg
import zipfile
from pathlib import Path

NAME = "NMS Shipwright"
EXE = f"{NAME}.exe"
PUBLISHER = "NMS Shipwright"
VERSION = "1.8.3"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NMSShipwright"
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / NAME
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / NAME  # game-file cache the app builds
DESKTOP = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop" / f"{NAME}.lnk"
START_MENU = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "app.zip"


def app_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True, text=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return EXE.lower() in out.lower()


def installed_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def shortcut(lnk: Path, target: Path):
    lnk.parent.mkdir(parents=True, exist_ok=True)
    q = lambda p: str(p).replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(target)}';"
          f"$s.WorkingDirectory='{q(target.parent)}';$s.IconLocation='{q(target)},0';$s.Description='{NAME}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def install(folder: Path, desktop=True, start_menu=True, progress=lambda f: None):
    folder = Path(folder)
    if folder.name != NAME and folder.exists() and any(folder.iterdir()) and not (folder / EXE).exists():
        folder = folder / NAME  # never spread the app over a folder that holds other things
    if app_running():
        raise RuntimeError(f"{NAME} is running. Close it and try again.")
    old = installed_dir()
    for d in {folder, old} - {None}:  # replace an earlier version cleanly (keeps the game-file cache)
        if (d / EXE).exists():
            shutil.rmtree(d / "_internal", ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE) as z:
        items = z.infolist()
        for i, item in enumerate(items):
            z.extract(item, folder)
            if i % 25 == 0:
                progress(i / len(items))
    uninstaller = BUNDLE.parent / "Uninstall.exe"  # small build of this program without the app inside
    shutil.copy2(uninstaller if uninstaller.exists() else sys.executable, folder / "Uninstall.exe")
    exe = folder / EXE
    if start_menu:
        shortcut(START_MENU, exe)
    if desktop:
        shortcut(DESKTOP, exe)
    size_kb = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, kind, value in (("DisplayName", winreg.REG_SZ, NAME), ("DisplayVersion", winreg.REG_SZ, VERSION),
                                  ("Publisher", winreg.REG_SZ, PUBLISHER), ("DisplayIcon", winreg.REG_SZ, f"{exe},0"),
                                  ("InstallLocation", winreg.REG_SZ, str(folder)),
                                  ("UninstallString", winreg.REG_SZ, f'"{folder / "Uninstall.exe"}" --uninstall'),
                                  ("QuietUninstallString", winreg.REG_SZ, f'"{folder / "Uninstall.exe"}" --uninstall /S'),
                                  ("EstimatedSize", winreg.REG_DWORD, size_kb),
                                  ("NoModify", winreg.REG_DWORD, 1), ("NoRepair", winreg.REG_DWORD, 1)):
            winreg.SetValueEx(k, name, 0, kind, value)
    progress(1.0)
    return exe


def uninstall(remove_data: bool):
    folder = installed_dir() or Path(sys.executable).parent
    if app_running():
        raise RuntimeError(f"{NAME} is running. Close it and try again.")
    for lnk in (DESKTOP, START_MENU):
        lnk.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(folder / "_internal", ignore_errors=True)
    (folder / EXE).unlink(missing_ok=True)
    if remove_data:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    # this program is folder/Uninstall.exe: remove it once it has exited, then the folder only if now empty
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & del /f /q "{folder / "Uninstall.exe"}" & rmdir "{folder}"',
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, cwd=os.environ.get("TEMP", "C:\\"))


# ---------------------------------------------------------------------- UI --

def message(text, title=NAME, flags=0x40):
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def wizard():
    import tkinter as tk
    from tkinter import filedialog, ttk

    ctypes.windll.shcore.SetProcessDpiAwareness(1) if hasattr(ctypes.windll, "shcore") else None
    root = tk.Tk()
    root.title(f"{NAME} Setup")
    root.resizable(False, False)
    bg, fg, accent, panel = "#0E1014", "#E8EAF0", "#E8543E", "#181B22"
    root.configure(bg=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCheckbutton", background=bg, foreground=fg, font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", bg)])
    style.configure("Bar.Horizontal.TProgressbar", troughcolor=panel, background=accent, bordercolor=panel, lightcolor=accent, darkcolor=accent)
    try:
        root.iconbitmap(str(Path(getattr(sys, "_MEIPASS", ".")) / "app.ico"))
    except tk.TclError:
        pass

    frame = tk.Frame(root, bg=bg, padx=28, pady=24)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=NAME, bg=bg, fg=fg, font=("Segoe UI Semibold", 18)).pack(anchor="w")
    old = installed_dir()
    sub = f"Update the installed copy to version {VERSION}." if old else f"Version {VERSION}: design, find and edit your No Man's Sky ships."
    tk.Label(frame, text=sub, bg=bg, fg="#9AA1AE", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 18))

    tk.Label(frame, text="Install to", bg=bg, fg=fg, font=("Segoe UI", 10)).pack(anchor="w")
    row = tk.Frame(frame, bg=bg)
    row.pack(fill="x", pady=(4, 14))
    folder = tk.StringVar(value=str(old or DEFAULT_DIR))
    tk.Entry(row, textvariable=folder, width=52, bg=panel, fg=fg, insertbackground=fg, relief="flat",
             font=("Segoe UI", 10)).pack(side="left", ipady=5, fill="x", expand=True)

    def browse():
        d = filedialog.askdirectory(initialdir=folder.get())
        if d:
            folder.set(str(Path(d) / NAME) if Path(d).name != NAME else d)
    tk.Button(row, text="Browse...", command=browse, bg=panel, fg=fg, relief="flat", activebackground="#262B35",
              activeforeground=fg, padx=10).pack(side="left", padx=(8, 0), ipady=2)

    desk, start, launch = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    for text, var in (("Desktop shortcut", desk), ("Start menu shortcut", start), (f"Open {NAME} when done", launch)):
        ttk.Checkbutton(frame, text=text, variable=var).pack(anchor="w", pady=1)
    tk.Label(frame, text="Needs no admin rights. Edits your saves only when you press Apply, with a backup first.",
             bg=bg, fg="#6B7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(14, 8))

    bar = ttk.Progressbar(frame, style="Bar.Horizontal.TProgressbar", length=460, mode="determinate")
    bar.pack(fill="x", pady=(4, 12))
    status = tk.Label(frame, text="", bg=bg, fg="#9AA1AE", font=("Segoe UI", 9))
    status.pack(anchor="w")
    buttons = tk.Frame(frame, bg=bg)
    buttons.pack(fill="x", pady=(12, 0))
    go = tk.Button(buttons, text="Update" if old else "Install", bg=accent, fg="white", relief="flat", padx=22, pady=6,
                   activebackground="#C9432F", activeforeground="white", font=("Segoe UI Semibold", 10))
    go.pack(side="right")
    cancel = tk.Button(buttons, text="Cancel", command=root.destroy, bg=panel, fg=fg, relief="flat", padx=16, pady=6,
                       activebackground="#262B35", activeforeground=fg)
    cancel.pack(side="right", padx=8)

    def run():
        go.config(state="disabled")
        cancel.config(state="disabled")
        status.config(text="Installing...")

        def work():
            try:
                exe = install(Path(folder.get()), desk.get(), start.get(),
                              progress=lambda f: root.after(0, bar.config, {"value": f * 100}))
            except Exception as e:  # shown in the window
                root.after(0, lambda: (status.config(text=f"Failed: {e}", fg=accent), go.config(state="normal"),
                                       cancel.config(state="normal")))
                return

            def done():
                status.config(text=f"Installed. Find {NAME} on your Desktop and in the Start menu.", fg="#4ADE80")
                go.config(text="Finish", state="normal", command=root.destroy)
                if launch.get():
                    subprocess.Popen([str(exe)], cwd=str(exe.parent))
                    root.after(800, root.destroy)
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()
    go.config(command=run)
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth() - root.winfo_width()) // 2}+{(root.winfo_screenheight() - root.winfo_height()) // 3}")
    root.mainloop()


def main():
    args = [a.lower() for a in sys.argv[1:]]
    silent = "/s" in args
    if "--uninstall" in args:
        if not silent:
            if message(f"Remove {NAME} from this PC?\n\nYour No Man's Sky saves and their backups are not touched.",
                       flags=0x24) != 6:  # Yes/No
                return
            data = DATA_DIR.exists() and message(
                "Also delete the game data it copied (ship models, colours, quest tables)?\n\n"
                "They are rebuilt automatically if you install again.", flags=0x24) == 6
        else:
            data = False
        try:
            uninstall(data)
        except Exception as e:
            if not silent:
                message(str(e), flags=0x10)
            sys.exit(1)
        if not silent:
            message(f"{NAME} was removed.")
        return
    if silent:
        target = next((a[3:] for a in sys.argv[1:] if a.upper().startswith("/D=")), None)
        install(Path(target) if target else installed_dir() or DEFAULT_DIR)
        return
    wizard()


if __name__ == "__main__":
    main()
