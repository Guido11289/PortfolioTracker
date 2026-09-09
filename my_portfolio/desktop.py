"""Desktop-wrapper voor de personal extensie.

`degiro_portfolio.desktop.run_desktop()` kan niet direct hergebruikt worden:
hij hardcodet het te starten modulepad als "degiro_portfolio.main:app"
(desktop.py regel ~280). Er is geen parameter om dat te overschrijven.

Dit bestand kopieert daarom de kern van run_desktop(), maar importeert de
platform-specifieke helpers (macOS .app-bundle, dock-icon, signal-handling)
rechtstreeks uit de core `desktop`-module i.p.v. ze te herschrijven.

Let op — dit is een bewuste, expliciete afhankelijkheid van *private*
helpers (onderstreepte namen) uit de core-library. Dat is standaard
kwetsbaar voor interne wijzigingen zonder major-versiebump. De schonere
oplossing op termijn is een upstream-PR die run_desktop() een
`app_module: str = "degiro_portfolio.main:app"` parameter geeft — dan kan
dit hele bestand vervallen. Tot die tijd is dit de pragmatische route om
zonder core-wijzigingen hetzelfde desktop-gedrag te krijgen.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import urllib.request

from degiro_portfolio.desktop import (
    APP_NAME,
    _icon_path,
    _log,
    _set_macos_bundle_name,
    _set_macos_dock_icon,
    _wait_for_ready,
    _reexec_via_macos_bundle_if_needed,
)


def run_desktop(*, port: int = 8000) -> None:
    """Start de personal-app (core + personal routes) als desktop-venster."""
    try:
        import webview
    except ImportError:
        print(
            "Error: pywebview is required for desktop mode.\n"
            "Install it with: pip install pywebview",
            file=sys.stderr,
        )
        sys.exit(1)

    host = "127.0.0.1"
    url = f"http://{host}:{port}/"

    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
    except OSError:
        print(
            f"Error: port {port} is already in use.\n"
            f"Use a different port: python -m my_portfolio.desktop --port {port + 1}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Enige echte verschil met de core-versie: het te starten modulepad.
    server_cmd = [
        sys.executable, "-m", "uvicorn",
        "my_portfolio.server:app",
        "--host", host,
        "--port", str(port),
        "--log-level", "warning",
    ]
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    _log(f"spawning personal server subprocess on {host}:{port}")
    server_process = subprocess.Popen(server_cmd, **popen_kwargs)

    print(f"Starting Personal Portfolio on {url} ...")
    if not _wait_for_ready(host, port):
        print("Warning: server may not be ready yet", file=sys.stderr)

    _set_macos_bundle_name()

    window = webview.create_window(
        APP_NAME,
        url,
        width=1280,
        height=900,
        min_size=(800, 600),
    )

    def _on_closing() -> None:
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"{url}api/shutdown", method="POST"),
                timeout=2,
            )
        except Exception:
            pass

    window.events.closing += _on_closing

    icon_file = _icon_path()
    if icon_file:
        window.events.shown += lambda: _set_macos_dock_icon(icon_file)

    import select

    signal_r, signal_w = os.pipe()
    os.set_blocking(signal_r, False)
    os.set_blocking(signal_w, False)
    signal.signal(signal.SIGINT, lambda *_: None)
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.set_wakeup_fd(signal_w)

    def _signal_watcher() -> None:
        select.select([signal_r], [], [])
        print("\nShutting down...", file=sys.stderr)
        _on_closing()
        try:
            window.destroy()
        except Exception:
            pass

    webview.start(func=_signal_watcher)

    if server_process.poll() is None:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait(timeout=2)

    print("Personal Portfolio closed.")


def main() -> None:
    _reexec_via_macos_bundle_if_needed()
    import argparse
    parser = argparse.ArgumentParser(description="Personal Portfolio Desktop")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_desktop(port=args.port)


if __name__ == "__main__":
    main()
