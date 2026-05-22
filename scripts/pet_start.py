"""Sumi pet launcher — 检查是否已运行，未运行则启动。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PORT_FILE = (
    Path.home() / "AppData" / "Local" / "DesktopPetAgent" / "permission_port.txt"
)


def is_running() -> bool:
    return PORT_FILE.exists()


def main() -> int:
    if is_running():
        port = PORT_FILE.read_text().strip()
        print(f"宠物已在运行中 (port {port})")
        return 0

    project_dir = Path(__file__).resolve().parent.parent  # scripts/ → project root
    venv_python = project_dir / ".venv" / "Scripts" / "python.exe"

    if not venv_python.exists():
        print(f"错误: 找不到虚拟环境 {venv_python}")
        return 1

    print("正在启动桌面宠物...")
    subprocess.Popen(
        [str(venv_python), str(project_dir / "main.py")],
        cwd=str(project_dir),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # 等待端口文件出现
    deadline = time.time() + 15
    while time.time() < deadline:
        if PORT_FILE.exists():
            port = PORT_FILE.read_text().strip()
            print(f"桌面宠物已启动 (port {port})")
            return 0
        time.sleep(0.5)

    print("启动超时，请手动运行 main.py 检查报错")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
