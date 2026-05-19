from __future__ import annotations

from pathlib import Path

import platformdirs

# ---- app root (the Agent/ directory containing src/) ----
# In dev:  src/desktop_pet_agent/paths.py  → parents[2] = Agent/
# In packaged app the whole tree is flattened so we use the module location as anchor.
APP_ROOT = Path(__file__).resolve().parents[2]

# ---- user data (config, reminders, checkpoint) ----
DATA_DIR = Path(
    platformdirs.user_data_dir("DesktopPetAgent", appauthor=False, ensure_exists=True)
)
CONFIG_PATH = DATA_DIR / "config.json"
REMINDERS_PATH = DATA_DIR / "reminders.json"
PROACTIVE_DB_PATH = DATA_DIR / "proactive.db"

# ---- .env search paths (tried in order) ----
CWD_ENV_PATH = Path.cwd() / ".env"
HOME_ENV_PATH = Path.home() / ".desktop-pet-agent.env"
APP_ENV_PATH = APP_ROOT / ".env"

# ---- sprite assets ----
IDLE_FRAMES_DIR = APP_ROOT / "Idle (32x32)_frames"

# ---- pet directories (Codex / PetDex) ----
CODEX_PETS_DIR = Path.home() / ".codex" / "pets"
LOCAL_PETS_DIR = DATA_DIR / "pets"
