# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — run: pyinstaller build.spec

Portable build — no hardcoded paths.  Uses the directory containing this file as root.
"""

from pathlib import Path

# SPECPATH is provided by PyInstaller — absolute path to the directory containing this spec.
_ROOT = Path(SPECPATH)
_SRC = _ROOT / "src"
_FRAMES = _ROOT / "Idle (32x32)_frames"

a = Analysis(
    [str(_ROOT / "main.py")],
    pathex=[str(_SRC)],
    binaries=[],
    datas=[] if not _FRAMES.exists() else [
        (str(_FRAMES), "Idle (32x32)_frames"),
    ],
    hiddenimports=[
        "tavily",
        "platformdirs",
        "mcp",
        "dotenv",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "email", "http", "xml", "pydoc"],
    no_warnings=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    a.zipfiles,
    name="DesktopPetAgent",
    icon=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    upx=True,
    upx_exclude=[],
)
