"""NMS Shipwright -- desktop app.

    python nms_editor.py        (or the "NMS Shipwright" shortcut / exe)

Runs the local backend on a free 127.0.0.1 port and shows it in a native
window (pywebview / Edge WebView2). Without pywebview it opens your browser.
Built into an exe with `python scripts/build_app.py`.
"""
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "NMS Shipwright"
FROZEN = getattr(sys, "frozen", False)
if FROZEN:  # game-file copies live outside the app folder, so rebuilding the app keeps them
    os.environ.setdefault("NMS_TOOL_CACHE", os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())),
                                                         APP_NAME, "gamecache"))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FileBridge:
    """Native Save / Open dialogs for the page (the app window has no download bar)."""

    def _window(self):
        import webview
        return webview.windows[0]

    def pick_folder(self, start=""):
        """Ask for a folder (used to point the tool at the No Man's Sky install)."""
        import webview
        path = self._window().create_file_dialog(webview.FileDialog.FOLDER, directory=start or "")
        if not path:
            return None
        return path[0] if isinstance(path, (list, tuple)) else path

    def save_text(self, suggested_name, text):
        import webview
        path = self._window().create_file_dialog(webview.FileDialog.SAVE, save_filename=suggested_name,
                                                  file_types=("JSON files (*.json)", "All files (*.*)"))
        if not path:
            return None
        path = path[0] if isinstance(path, (list, tuple)) else path
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def open_text(self):
        import webview
        paths = self._window().create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                   file_types=("JSON files (*.json)", "All files (*.*)"))
        if not paths:
            return None
        path = paths[0]
        with open(path, encoding="utf-8") as f:
            return {"name": os.path.basename(path), "text": f.read()}


def main():
    threading.stack_size(16 * 1024 * 1024)  # the game-code emulator needs more than the default thread stack
    from webapp.app import app

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
                     daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    try:
        import webview
    except ImportError:
        print(f"pywebview is not installed -- opening in your browser instead: {url}")
        webbrowser.open(url)
        input("Press Enter here to quit...")
        return
    webview.settings["ALLOW_DOWNLOADS"] = True  # fallback for plain links
    webview.create_window(APP_NAME, url, width=1440, height=920, min_size=(1100, 680), background_color="#0E1014",
                          js_api=FileBridge())
    webview.start()


if __name__ == "__main__":
    try:
        multiprocessing.freeze_support()  # the system scan uses worker processes
    except OSError:  # a worker whose app was closed while it started: nothing to do
        sys.exit(0)
    if sys.stderr:  # console/debug builds: print a traceback even for native crashes
        import faulthandler
        faulthandler.enable()
    main()
