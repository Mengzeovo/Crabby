"""Build a platform-specific backend runtime and runtime manifest.

This script is intentionally thin: it standardizes the PyInstaller command and
produces the manifest shape consumed by the Obsidian plugin runtime installer.
Run it on each target platform to produce that platform's executable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
DIST_DIR = ROOT / "dist" / "backend-runtime"


def platform_key() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "win32"
    if system == "darwin":
        return "darwin"
    if system == "linux":
        return "linux"
    raise SystemExit(f"Unsupported platform: {platform.system()}")


def executable_name() -> str:
    return "life-assistant-backend.exe" if platform_key() == "win32" else "life-assistant-backend"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime(version: str) -> Path:
    out_dir = DIST_DIR / version / platform_key()
    work_dir = ROOT / "build" / "backend-runtime"
    pyinstaller_dist = ROOT / "dist" / "pyinstaller"
    out_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "life-assistant-backend",
        "--paths",
        str(SERVER_DIR),
        "--workpath",
        str(work_dir),
        "--distpath",
        str(pyinstaller_dist),
        str(SERVER_DIR / "main.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    built_name = executable_name()
    built_path = pyinstaller_dist / built_name
    if not built_path.is_file():
        raise SystemExit(f"Expected PyInstaller output was not created: {built_path}")

    target = out_dir / built_name
    shutil.copy2(built_path, target)
    return target


def write_manifest(version: str, executable: Path, release_base_url: str) -> Path:
    asset_name = executable.name
    url = f"{release_base_url.rstrip('/')}/{asset_name}" if release_base_url else asset_name
    manifest = {
        "version": version,
        "platforms": {
            platform_key(): {
                "url": url,
                "sha256": sha256_file(executable),
                "executableName": asset_name,
            },
        },
    }
    path = executable.parent / "runtime-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--release-base-url",
        default="",
        help="Base URL where the executable will be hosted in a GitHub Release.",
    )
    args = parser.parse_args()

    executable = build_runtime(args.version)
    manifest = write_manifest(args.version, executable, args.release_base_url)
    print(f"Built backend runtime: {executable}")
    print(f"Wrote runtime manifest: {manifest}")


if __name__ == "__main__":
    main()
