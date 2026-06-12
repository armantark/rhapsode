#!/usr/bin/env python3
"""Build the Rhapsode backend PyInstaller sidecar for Tauri externalBin."""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def backend_dir() -> Path:
    return repo_root() / "backend"


def default_target_triple() -> str:
    try:
        output = subprocess.check_output(["rustc", "-Vv"], text=True, stderr=subprocess.STDOUT)
    except (FileNotFoundError, subprocess.CalledProcessError):
        system = platform.system().lower()
        machine = platform.machine().lower()
        if system == "darwin":
            return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
        if system == "windows":
            return "x86_64-pc-windows-msvc"
        if machine in {"arm64", "aarch64"}:
            return "aarch64-unknown-linux-gnu"
        return "x86_64-unknown-linux-gnu"

    match = re.search(r"^host:\s+(\S+)", output, re.MULTILINE)
    if match is not None:
        return match.group(1)
    return default_target_triple()


def sidecar_filename(target_triple: str) -> str:
    suffix = ".exe" if target_triple.endswith("windows-msvc") else ""
    return f"rhapsode-backend-{target_triple}{suffix}"


def run_build(target_triple: str, *, skip_copy: bool) -> Path:
    root = repo_root()
    backend = backend_dir()
    spec_path = backend / "rhapsode-sidecar.spec"
    if not spec_path.exists():
        msg = f"Missing PyInstaller spec: {spec_path}"
        raise FileNotFoundError(msg)

    subprocess.run(
        ["uv", "run", "pyinstaller", str(spec_path), "--noconfirm", "--clean"],
        cwd=backend,
        check=True,
    )

    built_name = "rhapsode-backend.exe" if target_triple.endswith("windows-msvc") else "rhapsode-backend"
    built_path = backend / "dist" / built_name
    if not built_path.exists():
        msg = f"PyInstaller output not found: {built_path}"
        raise FileNotFoundError(msg)

    if skip_copy:
        return built_path

    destination_dir = root / "frontend" / "src-tauri" / "binaries"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / sidecar_filename(target_triple)
    shutil.copy2(built_path, destination)
    destination.chmod(0o755)
    print(f"Copied sidecar to {destination}")
    return destination


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-triple",
        default=default_target_triple(),
        help="Rust target triple suffix used by Tauri externalBin (default: host triple)",
    )
    parser.add_argument(
        "--skip-copy",
        action="store_true",
        help="Only build under backend/dist; do not copy into frontend/src-tauri/binaries",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    destination = run_build(args.target_triple, skip_copy=args.skip_copy)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
