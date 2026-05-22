"""SessionStart hook — launch the desktop pet GUI when Claude Code starts."""

import subprocess
import sys
import os
from pathlib import Path


def main():
    # Don't launch if already running (simple PID file check)
    pid_file = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DesktopPetAgent" / "pet.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # check if process exists
            print("[desktop-pet] already running", file=sys.stderr)
            return
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    print("[desktop-pet] launching pet GUI...", file=sys.stderr)
    subprocess.Popen(
        [sys.executable, "-m", "desktop_pet_agent.app_webview"],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    main()
