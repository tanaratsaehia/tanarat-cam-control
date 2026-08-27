"""Resolves the OS-standard library folders the app saves/browses media in."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths


def _standard_dir(location: QStandardPaths.StandardLocation, fallback: str) -> Path:
    found = QStandardPaths.writableLocation(location)
    return Path(found) if found else Path.home() / fallback


PICTURES_DIR = _standard_dir(QStandardPaths.PicturesLocation, "Pictures")
MOVIES_DIR = _standard_dir(QStandardPaths.MoviesLocation, "Movies")

PHOTOS_DIR = PICTURES_DIR / "CamControl" / "Photos"
TIMELAPSES_DIR = PICTURES_DIR / "CamControl" / "Timelapses"
VIDEOS_DIR = MOVIES_DIR / "CamControl" / "Videos"


def ensure_library_dirs() -> None:
    for directory in (PHOTOS_DIR, TIMELAPSES_DIR, VIDEOS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
