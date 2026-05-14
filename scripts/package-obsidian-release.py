"""Package the Obsidian plugin plus backend runtime into a manual install zip.

The resulting archive contains a top-level plugin directory that can be copied
directly into `<vault>/.obsidian/plugins/`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "obsidian-plugin"
SERVER_DIR = ROOT / "server"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "obsidian-plugin"


def host_platform_key() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "win32"
    if system == "darwin":
        return "darwin"
    if system == "linux":
        return "linux"
    raise SystemExit(f"Unsupported platform: {platform.system()}")


def host_arch_key() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x64"
    return machine or "unknown"


def executable_name(platform_key: str) -> str:
    if platform_key == "win32":
        return "crabby-backend.exe"
    return "crabby-backend"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_pyproject_version() -> str:
    with (SERVER_DIR / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def ensure_version_matches(version: str, *, allow_mismatch: bool) -> None:
    versions = {
        "obsidian-plugin/manifest.json": read_json(PLUGIN_DIR / "manifest.json")[
            "version"
        ],
        "obsidian-plugin/package.json": read_json(PLUGIN_DIR / "package.json")[
            "version"
        ],
        "server/pyproject.toml": read_pyproject_version(),
    }
    mismatches = {
        source: found for source, found in versions.items() if found != version
    }
    if mismatches and not allow_mismatch:
        lines = [f"Version mismatch for release {version}:"]
        lines.extend(f"  {source}: {found}" for source, found in mismatches.items())
        lines.append("Pass --allow-version-mismatch to package anyway.")
        raise SystemExit("\n".join(lines))


def run_plugin_build(skip_plugin_build: bool) -> None:
    if skip_plugin_build:
        return
    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    npm = shutil.which(npm_name) or npm_name
    subprocess.run([npm, "run", "build"], cwd=PLUGIN_DIR, check=True)


def default_backend_binary(version: str, platform_key: str) -> Path:
    return (
        ROOT
        / "dist"
        / "backend-runtime"
        / version
        / platform_key
        / executable_name(platform_key)
    )


def ensure_required_file(path: Path, hint: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing required file: {path}\n{hint}")


def ensure_inside(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if os.path.commonpath([str(parent_resolved), str(child_resolved)]) != str(
        parent_resolved,
    ):
        raise SystemExit(f"Refusing to write outside {parent_resolved}: {child_resolved}")


def reset_dir(path: Path, allowed_parent: Path) -> None:
    ensure_inside(allowed_parent, path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_plugin_files(plugin_stage_dir: Path) -> None:
    for filename in ["manifest.json", "main.js"]:
        shutil.copy2(PLUGIN_DIR / filename, plugin_stage_dir / filename)

    styles_path = PLUGIN_DIR / "styles.css"
    if styles_path.is_file():
        shutil.copy2(styles_path, plugin_stage_dir / "styles.css")


def copy_backend_runtime(
    plugin_stage_dir: Path,
    backend_binary: Path,
    version: str,
    platform_key: str,
) -> str:
    relative_executable = PurePosixPath(
        "backend",
        version,
        platform_key,
        backend_binary.name,
    )
    runtime_dir = plugin_stage_dir / "runtime"
    target = runtime_dir / Path(*relative_executable.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backend_binary, target)

    current_mode = target.stat().st_mode
    target.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(relative_executable)


def write_runtime_state(
    plugin_stage_dir: Path,
    version: str,
    platform_key: str,
    executable_path: str,
) -> None:
    runtime_dir = plugin_stage_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "mode": "production",
        "version": version,
        "platform": platform_key,
        "executablePath": executable_path,
    }
    (runtime_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )


def zip_dir(source_dir: Path, output_zip: Path, archive_root: str) -> None:
    if output_zip.exists():
        output_zip.unlink()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            arcname = PurePosixPath(archive_root, *path.relative_to(source_dir).parts)
            archive.write(path, str(arcname))


def parse_args() -> argparse.Namespace:
    manifest_version = read_json(PLUGIN_DIR / "manifest.json")["version"]
    platform_key = host_platform_key()
    arch_key = host_arch_key()

    parser = argparse.ArgumentParser(
        description=(
            "Create a manual-install Obsidian plugin zip with the backend "
            "runtime bundled."
        ),
    )
    parser.add_argument("--version", default=manifest_version)
    parser.add_argument("--platform", default=platform_key)
    parser.add_argument("--arch", default=arch_key)
    parser.add_argument(
        "--backend-binary",
        type=Path,
        help=(
            "Path to the prebuilt backend binary. Defaults to "
            "dist/backend-runtime/<version>/<platform>/..."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--plugin-dir-name",
        default=read_json(PLUGIN_DIR / "manifest.json")["id"],
        help="Top-level directory name inside the zip.",
    )
    parser.add_argument(
        "--skip-plugin-build",
        action="store_true",
        help="Use the existing obsidian-plugin/main.js instead of running npm run build.",
    )
    parser.add_argument(
        "--allow-version-mismatch",
        action="store_true",
        help="Do not fail if plugin/backend version metadata differs from --version.",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Keep the temporary staging directory next to the output zip.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    version = args.version
    platform_key = args.platform
    backend_binary = (
        args.backend_binary.resolve()
        if args.backend_binary
        else default_backend_binary(version, platform_key)
    )
    output_dir = args.output_dir.resolve()
    staging_root = output_dir / ".staging"
    plugin_stage_dir = staging_root / args.plugin_dir_name
    output_zip = (
        output_dir / f"{args.plugin_dir_name}-{version}-{platform_key}-{args.arch}.zip"
    )

    ensure_version_matches(version, allow_mismatch=args.allow_version_mismatch)
    run_plugin_build(args.skip_plugin_build)
    ensure_required_file(PLUGIN_DIR / "manifest.json", "Run from the repository root.")
    ensure_required_file(PLUGIN_DIR / "main.js", "Run: cd obsidian-plugin && npm run build")
    ensure_required_file(
        backend_binary,
        "Build it first, for example: "
        f"cd server && uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version {version}",
    )

    reset_dir(staging_root, output_dir)
    plugin_stage_dir.mkdir(parents=True, exist_ok=True)

    copy_plugin_files(plugin_stage_dir)
    executable_path = copy_backend_runtime(
        plugin_stage_dir,
        backend_binary,
        version,
        platform_key,
    )
    write_runtime_state(plugin_stage_dir, version, platform_key, executable_path)
    zip_dir(plugin_stage_dir, output_zip, args.plugin_dir_name)

    if not args.keep_staging:
        shutil.rmtree(staging_root)

    print(f"Packaged Obsidian plugin release: {output_zip}")
    print(f"Manual install target: <vault>/.obsidian/plugins/{args.plugin_dir_name}/")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
