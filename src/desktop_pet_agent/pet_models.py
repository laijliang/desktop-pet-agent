"""Pet manifest & sprite state models for PetDex-format pets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceKind = Literal["builtin", "codex", "imported"]


# PetDex standard spritesheet grid
PETDEX_FRAME_W = 192
PETDEX_FRAME_H = 208
PETDEX_COLS = 8
PETDEX_ROWS = 9


@dataclass
class PetSpriteState:
    row: int
    frames: int
    duration_ms: int


@dataclass
class PetManifest:
    id: str
    display_name: str
    description: str = ""
    author: str = ""
    source: SourceKind = "builtin"
    spritesheet_path: str = ""
    states: dict[str, PetSpriteState] = field(default_factory=dict)
    cell_width: int = PETDEX_FRAME_W
    cell_height: int = PETDEX_FRAME_H
    columns: int = PETDEX_COLS

# Standard PetDex animation definitions
# row index → (state_name, frames, duration_ms)
PETDEX_STATE_DEFS: list[tuple[str, int, int]] = [
    ("idle",          6, 1100),
    ("running-right", 8, 1060),
    ("running-left",  8, 1060),
    ("waving",        4, 700),
    ("jumping",       5, 840),
    ("failed",        8, 1220),
    ("waiting",       6, 1010),
    ("running",       6, 820),
    ("review",        6, 1030),
]

# Map Agent app-level statuses → PetDex animation states
AGENT_STATUS_TO_PETDEX: dict[str, str] = {
    "idle":      "idle",
    "thinking":  "waiting",
    "reminding": "review",
    "paused":    "idle",
}
