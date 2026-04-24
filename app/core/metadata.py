from datetime import datetime
from pathlib import Path

import exifread
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser

from app.models.photo_file import PhotoFile

PHOTO_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp",
    "tif", "tiff", "heic", "heif",
    "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2", "raf", "pef", "srw",
}
VIDEO_EXTENSIONS = {
    "mp4", "mov", "avi", "mkv", "wmv", "m4v", "3gp", "mts", "m2ts",
}
SUPPORTED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"
_EXIF_DATE_KEYS = ["EXIF DateTimeOriginal", "Image DateTime", "EXIF DateTimeDigitized"]


def _parse_exif_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, _EXIF_DATE_FMT)
    except ValueError:
        return None


def _extract_photo_metadata(path: Path) -> tuple[datetime | None, str | None, str | None]:
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        date_taken = None
        for key in _EXIF_DATE_KEYS:
            tag = tags.get(key)
            if tag is not None:
                date_taken = _parse_exif_date(str(tag))
                if date_taken is not None:
                    break

        make = str(tags["Image Make"]).strip() if "Image Make" in tags else None
        model = str(tags["Image Model"]).strip() if "Image Model" in tags else None
        return date_taken, make, model
    except Exception:
        return None, None, None


def _extract_video_metadata(path: Path) -> tuple[datetime | None, str | None, str | None]:
    try:
        parser = createParser(str(path))
        if not parser:
            return None, None, None
        with parser:
            metadata = extractMetadata(parser)
        if metadata is None:
            return None, None, None
        date = metadata.get("creation_date")
        return date, None, None
    except Exception:
        return None, None, None


def extract_metadata(path: Path) -> PhotoFile:
    ext = path.suffix.lstrip(".").lower()
    if ext in VIDEO_EXTENSIONS:
        date_taken, camera_make, camera_model = _extract_video_metadata(path)
    else:
        date_taken, camera_make, camera_model = _extract_photo_metadata(path)
    return PhotoFile(
        source_path=path,
        extension=ext,
        date_taken=date_taken,
        camera_make=camera_make,
        camera_model=camera_model,
        resolved_dest=None,
        has_metadata=date_taken is not None,
    )
