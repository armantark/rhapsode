import os
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

ALLOWED_CATEGORIES = {"reference", "saved_best"}


def store_upload(upload: UploadFile, media_dir: Path) -> tuple[str, int]:
    suffix = Path(upload.filename or "").suffix
    final_path = media_dir / f"{uuid4()}{suffix}"
    temporary_path = final_path.with_suffix(final_path.suffix + ".tmp")
    size = 0
    try:
        with temporary_path.open("wb") as destination:
            while chunk := upload.file.read(1024 * 1024):
                destination.write(chunk)
                size += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, final_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()
    return str(final_path), size


def remove_asset(path: str) -> None:
    Path(path).unlink(missing_ok=True)
