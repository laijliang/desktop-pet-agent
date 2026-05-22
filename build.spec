# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — run: pyinstaller build.spec

Portable build — no hardcoded paths.  Uses the directory containing this file as root.
"""

from pathlib import Path

# SPECPATH is provided by PyInstaller — absolute path to the directory containing this spec.
_ROOT = Path(SPECPATH)
_SRC = _ROOT / "src"
_FRAMES = _ROOT / "Idle (32x32)_frames"
_UI_DIR = _SRC / "desktop_pet_agent" / "ui_webview"

ui_datas = []
if _UI_DIR.is_dir():
    for f in _UI_DIR.iterdir():
        if f.is_file():
            ui_datas.append((str(f), f"desktop_pet_agent/ui_webview"))

a = Analysis(
    [str(_ROOT / "main.py")],
    pathex=[str(_SRC)],
    binaries=[],
    datas=(
        ui_datas
        + ([] if not _FRAMES.exists() else [(str(_FRAMES), "Idle (32x32)_frames")])
    ),
    hiddenimports=[
        "tavily",
        "platformdirs",
        "mcp",
        "dotenv",
        "webview2",
        "pystray",
        "PIL",
        "win32con",
        "win32gui",
        "win32api",
        "pythoncom",
        "voxe",
        "urllib",
        "json",
        "logging",
        "threading",
        "asyncio",
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
