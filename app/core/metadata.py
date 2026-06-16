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


# Containers that use the ISO base-media / QuickTime atom layout and may carry
# an Apple-style `moov/meta` keys table or a QuickTime `moov/udta` block.
_QUICKTIME_EXTENSIONS = {"mov", "qt", "mp4", "m4v", "3gp", "3g2"}


def _iter_atoms(fh, start: int, end: int):
    """Yield ``(atom_type, content_start, content_end)`` for atoms in ``[start, end)``.

    Only 8/16-byte headers are read and payloads are seeked past, so this stays
    cheap on large files where the metadata atoms are tiny next to the media data.
    """
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            break
        size = int.from_bytes(header[0:4], "big")
        atom_type = header[4:8]
        header_len = 8
        if size == 1:  # 64-bit extended size follows the type
            ext = fh.read(8)
            if len(ext) < 8:
                break
            size = int.from_bytes(ext, "big")
            header_len = 16
        elif size == 0:  # atom runs to the end of its parent
            size = end - pos
        if size < header_len:
            break
        yield atom_type, pos + header_len, pos + size
        pos += size


def _find_atom(fh, start: int, end: int, target: bytes) -> tuple[int, int] | None:
    """Return ``(content_start, content_end)`` of the first ``target`` atom, or ``None``."""
    for atom_type, content_start, content_end in _iter_atoms(fh, start, end):
        if atom_type == target:
            return content_start, content_end
    return None


def _meta_children(fh, start: int, end: int):
    """Yield child atoms of a ``meta`` atom, handling the MP4/QuickTime split.

    In ISO-BMFF (MP4) ``meta`` is a FullBox with a 4-byte version/flags prefix;
    in QuickTime (MOV) it has none. Detect which by checking whether the bytes at
    ``start`` already look like a known child atom header.
    """
    fh.seek(start)
    head = fh.read(8)
    if len(head) >= 8 and head[4:8] in (b"hdlr", b"keys", b"ilst", b"mhdr"):
        child_start = start
    else:
        child_start = start + 4
    yield from _iter_atoms(fh, child_start, end)


def _parse_meta_keys(fh, start: int, end: int) -> list[str]:
    """Return the ordered key names from an Apple metadata ``keys`` atom."""
    fh.seek(start)
    payload = fh.read(end - start)
    if len(payload) < 8:
        return []
    count = int.from_bytes(payload[4:8], "big")
    keys: list[str] = []
    pos = 8
    for _ in range(count):
        if pos + 8 > len(payload):
            break
        entry_size = int.from_bytes(payload[pos:pos + 4], "big")
        if entry_size < 8 or pos + entry_size > len(payload):
            break
        # entry = size(4) + namespace(4) + key string
        keys.append(payload[pos + 8:pos + entry_size].decode("latin1"))
        pos += entry_size
    return keys


def _parse_meta_ilst(fh, start: int, end: int, keys: list[str]) -> dict[str, str]:
    """Map key name -> value string for the items in an ``ilst`` atom."""
    values: dict[str, str] = {}
    for atom_type, content_start, content_end in _iter_atoms(fh, start, end):
        index = int.from_bytes(atom_type, "big")  # 1-based index into keys
        if not 1 <= index <= len(keys):
            continue
        data = _find_atom(fh, content_start, content_end, b"data")
        if data is None:
            continue
        fh.seek(data[0])
        payload = fh.read(data[1] - data[0])
        if len(payload) < 8:
            continue
        # data payload = type(4) + locale(4) + value
        text = payload[8:].decode("utf-8", "replace").strip("\x00").strip()
        if text:
            values[keys[index - 1]] = text
    return values


def _parse_udta(fh, start: int, end: int) -> dict[bytes, str]:
    """Decode the QuickTime user-data (``©``-prefixed) text atoms in ``udta``."""
    out: dict[bytes, str] = {}
    for atom_type, content_start, content_end in _iter_atoms(fh, start, end):
        if atom_type[0:1] != b"\xa9":
            continue
        fh.seek(content_start)
        payload = fh.read(content_end - content_start)
        # QuickTime text atom = length(2) + language(2) + text
        if len(payload) >= 4:
            text_len = int.from_bytes(payload[0:2], "big")
            raw = payload[4:4 + text_len] if 0 < text_len <= len(payload) - 4 else payload[4:]
        else:
            raw = payload
        text = raw.decode("utf-8", "replace").strip("\x00").strip()
        if text:
            out[atom_type] = text
    return out


def _date_from_quicktime(meta_values: dict[str, str]) -> datetime | None:
    """Parse ``com.apple.quicktime.creationdate`` (true capture time) if present."""
    raw = meta_values.get("com.apple.quicktime.creationdate")
    if not raw:
        return None
    try:
        date = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Keep local wall-clock time, matching naive EXIF DateTimeOriginal.
    if date.tzinfo is not None:
        date = date.replace(tzinfo=None)
    return date


def _camera_from_quicktime(
    meta_values: dict[str, str], udta_values: dict[bytes, str]
) -> tuple[str | None, str | None]:
    """Resolve camera ``(make, model)`` from QuickTime metadata."""
    make = meta_values.get("com.apple.quicktime.make") or udta_values.get(b"\xa9mak")
    model = meta_values.get("com.apple.quicktime.model") or udta_values.get(b"\xa9mod")
    if not (make and model):
        # Fujifilm (and some others) only write a combined description into
        # `©inf`, e.g. "FUJIFILM DIGITAL CAMERA X-S20". Split it so the values
        # match what the same camera's stills yield via EXIF Make/Model.
        info = udta_values.get(b"\xa9inf")
        if info and " DIGITAL CAMERA " in info:
            inf_make, _, inf_model = info.partition(" DIGITAL CAMERA ")
            make = make or inf_make.strip() or None
            model = model or inf_model.strip() or None
    return make or None, model or None


def _parse_quicktime_metadata(
    path: Path,
) -> tuple[datetime | None, str | None, str | None]:
    """Parse QuickTime/ISO-BMFF atoms for capture date and camera make/model.

    Returns ``(date, make, model)``; any field is ``None`` when not present.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, io.SEEK_END)
            filesize = fh.tell()
            moov = _find_atom(fh, 0, filesize, b"moov")
            if moov is None:
                return None, None, None

            meta_values: dict[str, str] = {}
            udta_values: dict[bytes, str] = {}
            for atom_type, content_start, content_end in _iter_atoms(fh, moov[0], moov[1]):
                if atom_type == b"meta":
                    keys = ilst = None
                    for child, child_start, child_end in _meta_children(fh, content_start, content_end):
                        if child == b"keys":
                            keys = (child_start, child_end)
                        elif child == b"ilst":
                            ilst = (child_start, child_end)
                    if keys and ilst:
                        meta_values = _parse_meta_ilst(
                            fh, ilst[0], ilst[1], _parse_meta_keys(fh, keys[0], keys[1])
                        )
                elif atom_type == b"udta":
                    udta_values = _parse_udta(fh, content_start, content_end)

            date = _date_from_quicktime(meta_values)
            make, model = _camera_from_quicktime(meta_values, udta_values)
            return date, make, model
    except Exception:
        return None, None, None


def _hachoir_creation_date(path: Path) -> datetime | None:
    """Return a video's container creation date via hachoir, or ``None``."""
    try:
        parser = createParser(str(path))
        if not parser:
            return None
        with parser:
            metadata = extractMetadata(parser)
        if metadata is None:
            return None
        date = metadata.get("creation_date")
        if not isinstance(date, datetime):
            return None
        # hachoir anchors the Mac epoch at 1904-01-01 UTC, so strip tzinfo.
        if date.tzinfo is not None:
            date = date.replace(tzinfo=None)
        return date
    except Exception:
        return None


def _extract_video_metadata(path: Path) -> tuple[datetime | None, str | None, str | None]:
    """Read container metadata from a video file and return ``(date, make, model)``.

    QuickTime/ISO-BMFF containers are parsed directly for camera make/model and a
    precise capture date; hachoir supplies the date for other containers and as a
    fallback when no ``com.apple.quicktime.creationdate`` is present.
    """
    qt_date = qt_make = qt_model = None
    if path.suffix.lstrip(".").lower() in _QUICKTIME_EXTENSIONS:
        qt_date, qt_make, qt_model = _parse_quicktime_metadata(path)
    date = qt_date if qt_date is not None else _hachoir_creation_date(path)
    return date, qt_make, qt_model


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
