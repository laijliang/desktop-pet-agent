"""PetDex-format pet discovery and spritesheet loader.

Manifest discovery does NOT require a running QApplication.
Frame slicing (QPixmap) is deferred to :func:`load_frames_for` which
must be called after a QApplication exists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .paths import CODEX_PETS_DIR, IDLE_FRAMES_DIR, LOCAL_PETS_DIR

from .pet_models import (
    PETDEX_COLS,
    PETDEX_FRAME_H,
    PETDEX_FRAME_W,
    PETDEX_STATE_DEFS,
    PetManifest,
    PetSpriteState,
)

logger = logging.getLogger("desktop-pet-agent")

BUILTIN_SUMI_ID = "sumi"


# ---------------------------------------------------------------------------
# discovery — no QApplication needed
# ---------------------------------------------------------------------------

def discover_pets() -> list[PetManifest]:
    """Return manifests for all available pets (builtin + Codex + local)."""
    pets: list[PetManifest] = [build_sumi_manifest()]
    seen = {BUILTIN_SUMI_ID}
    for directory in (CODEX_PETS_DIR, LOCAL_PETS_DIR):
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            manifest = read_pet_folder(entry)
            if manifest is None:
                continue
            if manifest.id in seen:
                continue
            seen.add(manifest.id)
            pets.append(manifest)
    return pets


def read_pet_folder(root: Path) -> PetManifest | None:
    """Parse pet.json and return manifest metadata (no frame slicing)."""
    pet_json = root / "pet.json"
    if not pet_json.is_file():
        return None
    try:
        data = json.loads(pet_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("failed to parse pet.json in %s", root)
        return None

    pet_id = str(data.get("id") or data.get("name") or root.name).strip()
    display_name = str(data.get("displayName") or data.get("display_name") or pet_id)
    description = str(data.get("description") or "")
    author = str(data.get("author") or "")

    spritesheet_name = (
        data.get("spritesheetPath") or data.get("spritesheet") or "spritesheet.webp"
    )
    spritesheet_path = root / spritesheet_name
    if not spritesheet_path.is_file():
        spritesheet_path = next(
            (p for p in sorted(root.glob("spritesheet.*")) if p.suffix in (".webp", ".png")),
            None,
        )
    if spritesheet_path is None or not spritesheet_path.is_file():
        logger.warning("no spritesheet found in %s", root)
        return None

    src = _classify_source(root)

    # Read per-pet cell dimensions and columns from pet.json, falling back to PetDex defaults
    cell_width = int(data.get("cellWidth", PETDEX_FRAME_W))
    cell_height = int(data.get("cellHeight", PETDEX_FRAME_H))
    columns = int(data.get("columns", PETDEX_COLS))

    # Build duration lookup from standard PetDex definitions
    default_duration: dict[str, int] = {
        name: dur for name, _, dur in PETDEX_STATE_DEFS
    }

    states: dict[str, PetSpriteState] = {}
    raw_states = data.get("states")
    if isinstance(raw_states, dict) and raw_states:
        for state_name, info in raw_states.items():
            if not isinstance(info, dict):
                continue
            row = int(info.get("row", 0))
            frames = int(info.get("frames", 0))
            if frames <= 0:
                continue
            duration_ms = int(info.get("durationMs") or info.get("duration_ms")
                              or default_duration.get(state_name, 1000))
            states[state_name] = PetSpriteState(
                row=row, frames=frames, duration_ms=duration_ms
            )
    else:
        for row_idx, (state_name, frame_count, duration_ms) in enumerate(PETDEX_STATE_DEFS):
            states[state_name] = PetSpriteState(
                row=row_idx, frames=frame_count, duration_ms=duration_ms
            )

    return PetManifest(
        id=pet_id,
        display_name=display_name,
        description=description,
        author=author,
        source=src,
        spritesheet_path=str(spritesheet_path),
        states=states,
        cell_width=cell_width,
        cell_height=cell_height,
        columns=columns,
    )


def build_sumi_manifest() -> PetManifest:
    """Return manifest for the builtin Sumi pet."""
    state = PetSpriteState(row=0, frames=11, duration_ms=1980)
    return PetManifest(
        id=BUILTIN_SUMI_ID,
        display_name="Sumi",
        description="内置桌宠 Sumi",
        source="builtin",
        spritesheet_path=str(IDLE_FRAMES_DIR),
        states={"idle": state},
    )


# ---------------------------------------------------------------------------
# frame slicing — requires QApplication
# ---------------------------------------------------------------------------

def load_frames_for(manifest: PetManifest) -> dict[str, list]:
    """Load & slice the spritesheet into per-state QPixmap lists.

    Must be called after a QApplication exists.
    """
    from PySide6.QtGui import QImage, QPixmap  # noqa: F811

    if manifest.id == BUILTIN_SUMI_ID:
        return {"idle": _load_sumi_frames()}

    image = QImage(manifest.spritesheet_path)
    if image.isNull():
        return {}

    result: dict[str, list] = {}
    for state_name, s in manifest.states.items():
        frames: list = []
        for col in range(min(s.frames, manifest.columns)):
            x = col * manifest.cell_width
            y = s.row * manifest.cell_height
            cell = image.copy(x, y, manifest.cell_width, manifest.cell_height)
            frames.append(QPixmap.fromImage(cell))
        if frames:
            result[state_name] = frames
    return result


def _load_sumi_frames() -> list:
    """Load legacy per-frame PNGs (frame_000.png … frame_010.png)."""
    from PySide6.QtGui import QImage, QPixmap  # noqa: F811

    frames: list = []
    for i in range(11):
        path = IDLE_FRAMES_DIR / f"frame_{i:03d}.png"
        img = QImage(str(path))
        if img.isNull():
            pm = QPixmap(64, 64)
            pm.fill()
        else:
            pm = QPixmap.fromImage(img)
        frames.append(pm)
    return frames


# ---------------------------------------------------------------------------
# frame slicing — PIL (no Qt dependency, used by native PetWindow)
# ---------------------------------------------------------------------------

def load_frames_as_pil(manifest: PetManifest) -> dict[str, list]:
    """Load & slice the spritesheet into per-state PIL Image lists (RGBA).

    Does NOT require QApplication.  Used by the native Win32 PetWindow.
    """
    from PIL import Image as PILImage

    if manifest.id == BUILTIN_SUMI_ID:
        return {"idle": _load_sumi_frames_pil()}

    try:
        sheet = PILImage.open(manifest.spritesheet_path).convert("RGBA")
    except Exception:
        return {}

    result: dict[str, list] = {}
    for state_name, s in manifest.states.items():
        frames: list = []
        for col in range(min(s.frames, manifest.columns)):
            x = col * manifest.cell_width
            y = s.row * manifest.cell_height
            cell = sheet.crop((
                x, y,
                x + manifest.cell_width,
                y + manifest.cell_height,
            ))
            frames.append(cell)
        if frames:
            result[state_name] = frames
    return result


def _load_sumi_frames_pil() -> list:
    """Load Sumi idle frames as PIL Images (RGBA)."""
    from PIL import Image as PILImage

    frames: list = []
    for i in range(11):
        path = IDLE_FRAMES_DIR / f"frame_{i:03d}.png"
        try:
            img = PILImage.open(path).convert("RGBA")
            frames.append(img)
        except Exception:
            frames.append(PILImage.new("RGBA", (32, 32), (32, 212, 137, 255)))
    return frames


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _classify_source(root: Path) -> str:
    root_s = str(root.resolve())
    codex_s = str(CODEX_PETS_DIR.resolve())
    local_s = str(LOCAL_PETS_DIR.resolve())
    if root_s.startswith(codex_s):
        return "codex"
    if root_s.startswith(local_s):
        return "imported"
    return "imported"
