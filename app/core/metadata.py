import io
import struct
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
    """Parse an EXIF date string into a datetime, returning ``None`` on failure."""
    try:
        return datetime.strptime(value, _EXIF_DATE_FMT)
    except ValueError:
        return None


def _extract_photo_metadata(path: Path) -> tuple[datetime | None, str | None, str | None]:
    """Read EXIF tags from a photo file and return ``(date, make, model)``."""
    try:
        if path.suffix.lstrip(".").lower() == "raf":
            # RAF stores the embedded JPEG offset at bytes 84–87 (big-endian).
            # exifread has no RAF parser; extract the JPEG into a BytesIO so that
            # exifread's internal fh.seek(0) lands at the JPEG start, not the RAF header.
            with open(path, "rb") as f:
                f.seek(84)
                jpeg_offset = struct.unpack(">I", f.read(4))[0]
                f.seek(jpeg_offset)
                jpeg_bytes = f.read()
            fh = io.BytesIO(jpeg_bytes)
            tags = exifread.process_file(fh, details=True)
        else:
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
    """Read container metadata from a video file and return ``(date, None, None)``."""
    try:
        parser = createParser(str(path))
        if not parser:
            return None, None, None
        with parser:
            metadata = extractMetadata(parser)
        if metadata is None:
            return None, None, None
        date = metadata.get("creation_date")
        # hachoir anchors the Mac epoch at 1904-01-01 UTC, so strip tzinfo.
        if isinstance(date, datetime) and date.tzinfo is not None:
            date = date.replace(tzinfo=None)
        return date, None, None
    except Exception:
        return None, None, None


def extract_metadata(path: Path) -> PhotoFile:
    """Extract metadata from a photo or video file and return a ``PhotoFile``.

    Args:
        path: Path to the source file.

    Returns:
        A ``PhotoFile`` populated with date, camera, and extension fields.
        ``has_metadata`` is ``True`` only when a date was successfully parsed.
    """
    ext = path.suffix.lstrip(".").lower()
    if ext in VIDEO_EXTENSIONS:
        date_taken, camera_make, camera_model = _extract_video_metadata(path)
    else:
        date_taken, camera_make, camera_model = _extract_photo_metadata(path)
    has_metadata = date_taken is not None
    if date_taken is None:
        date_taken = datetime.fromtimestamp(path.stat().st_mtime)
    return PhotoFile(
        source_path=path,
        extension=ext,
        date_taken=date_taken,
        camera_make=camera_make,
        camera_model=camera_model,
        resolved_dest=None,
        has_metadata=has_metadata,
    )
