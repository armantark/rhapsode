"""PyInstaller spec for the Tauri backend sidecar."""

# ruff: noqa: F821

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
backend_dir = Path(SPECPATH)
src_dir = backend_dir / "src"

hiddenimports = [
    "alembic.runtime.migration",
    "sqlalchemy.dialects.sqlite",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "multipart",
    "fugashi",
    "unidic_lite",
    "rhapsode.app",
    "rhapsode.migrations",
    "rhapsode.resources",
    "rhapsode.desktop",
]

a = Analysis(
    [str(src_dir / "rhapsode" / "cli.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[
        (str(backend_dir / "alembic.ini"), "."),
        (str(backend_dir / "alembic"), "alembic"),
        *collect_data_files("unidic_lite"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="rhapsode-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
