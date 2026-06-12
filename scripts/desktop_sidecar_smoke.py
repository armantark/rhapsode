#!/usr/bin/env python3
"""Smoke-test the packaged backend sidecar without launching Tauri.

Spawns the PyInstaller binary (or falls back to `uv run rhapsode`), waits for
health, verifies passage listing, then shuts down. Skips gracefully when no
sidecar binary exists and RHAPSODE_SMOKE_REQUIRE_SIDECAR is unset.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def host_target_triple() -> str:
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
    return match.group(1) if match else host_target_triple()


def sidecar_path(target_triple: str) -> Path:
    suffix = ".exe" if target_triple.endswith("windows-msvc") else ""
    return (
        repo_root()
        / "frontend"
        / "src-tauri"
        / "binaries"
        / f"rhapsode-backend-{target_triple}{suffix}"
    )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, *, timeout_s: float) -> None:
    url = f"http://127.0.0.1:{port}/api/v1/health"
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
                last_error = f"unexpected status {response.status}"
        except urllib.error.URLError as error:
            last_error = str(error.reason)
        time.sleep(0.25)
    msg = f"health check timed out at {url}: {last_error}"
    raise TimeoutError(msg)


def fetch_passages(port: int) -> list[object]:
    url = f"http://127.0.0.1:{port}/api/v1/passages"
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, list):
        msg = f"expected list from GET /passages, got {type(payload).__name__}"
        raise TypeError(msg)
    return payload


def build_env(data_dir: Path, port: int) -> dict[str, str]:
    db_path = data_dir / "rhapsode.db"
    env = os.environ.copy()
    env.update(
        {
            "RHAPSODE_HOST": "127.0.0.1",
            "RHAPSODE_PORT": str(port),
            "RHAPSODE_DESKTOP": "1",
            "RHAPSODE_DATA_DIR": str(data_dir),
            "RHAPSODE_DATABASE_URL": f"sqlite:///{db_path}",
            "RHAPSODE_MEDIA_DIR": str(data_dir / "media"),
            "RHAPSODE_BACKUP_DIR": str(data_dir / "backups"),
        }
    )
    return env


def spawn_sidecar(binary: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(binary)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def spawn_dev_backend(env: dict[str, str]) -> subprocess.Popen[bytes]:
    backend = repo_root() / "backend"
    return subprocess.Popen(
        ["uv", "run", "rhapsode"],
        cwd=backend,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-triple",
        default=host_target_triple(),
        help="Sidecar filename suffix (default: host triple)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for sidecar health (default: 90)",
    )
    parser.add_argument(
        "--require-sidecar",
        action="store_true",
        help="Fail when the PyInstaller binary is missing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    require_sidecar = args.require_sidecar or os.environ.get("RHAPSODE_SMOKE_REQUIRE_SIDECAR") == "1"
    binary = sidecar_path(args.target_triple)

    if not binary.exists():
        if require_sidecar:
            print(f"missing sidecar binary: {binary}", file=sys.stderr)
            return 1
        print(f"skip: no sidecar at {binary} (set --require-sidecar to fail)")
        return 0

    port = reserve_port()
    with tempfile.TemporaryDirectory(prefix="rhapsode-sidecar-smoke-") as tmp:
        data_dir = Path(tmp)
        env = build_env(data_dir, port)
        process = spawn_sidecar(binary, env)
        try:
            wait_for_health(port, timeout_s=args.timeout)
            passages = fetch_passages(port)
            print(f"health ok on :{port}; passages={len(passages)}")
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
