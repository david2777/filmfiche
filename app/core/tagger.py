"""EXIF embedding for scanned film frames.

Ported from the standalone ``analog_import`` CLI. Maps a metadata dict (using the
Lightme/Logbook JSON key names) to EXIF bytes via piexif, and writes a source
image to a destination with that EXIF embedded:

* JPEGs are copied byte-for-byte and the EXIF block is spliced in, so pixels are
  never re-encoded.
* TIFFs are round-tripped through Pillow with their original compression
  preserved.

The dict-based interface is deliberately identical to the JSON schema so the same
entry can be imported, edited, and written back without translation.
"""
from __future__ import annotations

import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

import piexif
from PIL import Image

# Extensions the tagger can read and write metadata into.
TAG_EXTS = {".jpg", ".jpeg", ".tif", ".tiff"}
JPEG_EXTS = {".jpg", ".jpeg"}
TIFF_EXTS = {".tif", ".tiff"}

# Keys whose values may arrive as user-friendly strings (e.g. ``"1/125"``) and
# must be coerced to a number before piexif sees them.
_NUMERIC_KEYS = {"ExposureTime", "FNumber", "MaxApertureValue", "FocalLength"}


# ---------------------------------------------------------------------------
# EXIF assembly (ported verbatim from analog_import/metadata.py)
# ---------------------------------------------------------------------------

def _rational(value: float, max_denom: int = 1_000_000) -> tuple[int, int]:
    if value == 0:
        return (0, 1)
    f = Fraction(value).limit_denominator(max_denom)
    return (f.numerator, f.denominator)


_GPS_RE = re.compile(
    r"""(?P<deg>\d+)\s*deg\s*(?P<min>\d+)'\s*(?P<sec>[\d.]+)"\s*[NSEW]?""",
    re.IGNORECASE,
)


def _parse_gps(coord: str) -> list[tuple[int, int]]:
    m = _GPS_RE.search(coord)
    if not m:
        raise ValueError(f"unparseable GPS coord: {coord!r}")
    d = int(m["deg"])
    mi = int(m["min"])
    s = float(m["sec"])
    return [_rational(d), _rational(mi), _rational(s, 10_000)]


def _ascii(value: Any) -> bytes:
    return str(value).encode("utf-8", errors="replace")


def _user_comment(value: str) -> bytes:
    # ExifIFD.UserComment requires a charset prefix.
    return b"UNICODE\x00" + value.encode("utf-16-be")


def build_exif(entry: dict[str, Any]) -> bytes:
    """Assemble EXIF bytes from a metadata *entry* dict.

    Args:
        entry: Metadata using the Lightme/Logbook JSON key names (``Make``,
            ``Model``, ``DateTimeOriginal``, ``FNumber``, ``LensModel``, ``Notes``,
            GPS fields, etc.). Missing keys are simply skipped.

    Returns:
        EXIF bytes suitable for :func:`piexif.insert` or Pillow's ``exif=`` arg.
    """
    zeroth: dict[int, Any] = {}
    exif: dict[int, Any] = {}
    gps: dict[int, Any] = {}

    if v := entry.get("Make"):
        zeroth[piexif.ImageIFD.Make] = _ascii(v)
    if v := entry.get("Model"):
        zeroth[piexif.ImageIFD.Model] = _ascii(v)
    if v := entry.get("Software"):
        zeroth[piexif.ImageIFD.Software] = _ascii(v)
    if v := entry.get("Description"):
        zeroth[piexif.ImageIFD.ImageDescription] = _ascii(v)
    if v := entry.get("DocumentName"):
        zeroth[piexif.ImageIFD.DocumentName] = _ascii(v)

    if v := entry.get("DateTimeOriginal"):
        exif[piexif.ExifIFD.DateTimeOriginal] = _ascii(v)
        exif[piexif.ExifIFD.DateTimeDigitized] = _ascii(v)
        zeroth[piexif.ImageIFD.DateTime] = _ascii(v)

    if (v := entry.get("ExposureTime")) is not None:
        exif[piexif.ExifIFD.ExposureTime] = _rational(float(v))
    if (v := entry.get("FNumber")) is not None:
        exif[piexif.ExifIFD.FNumber] = _rational(float(v))
    if (v := entry.get("MaxApertureValue")) is not None:
        exif[piexif.ExifIFD.MaxApertureValue] = _rational(float(v))
    if (v := entry.get("FocalLength")) is not None:
        exif[piexif.ExifIFD.FocalLength] = _rational(float(v))
    if (v := entry.get("FocalLengthIn35mmFormat")) is not None:
        exif[piexif.ExifIFD.FocalLengthIn35mmFilm] = int(v)
    if (v := entry.get("ISO")) is not None:
        exif[piexif.ExifIFD.ISOSpeedRatings] = int(v)
    if (v := entry.get("ISOSpeed")) is not None:
        exif[piexif.ExifIFD.ISOSpeed] = int(v)
    if (v := entry.get("SensitivityType")) is not None:
        exif[piexif.ExifIFD.SensitivityType] = int(v)
    if (v := entry.get("FileSource")) is not None:
        # FileSource is an UNDEFINED single-byte tag.
        exif[piexif.ExifIFD.FileSource] = bytes([int(v)])
    if v := entry.get("LensMake"):
        exif[piexif.ExifIFD.LensMake] = _ascii(v)
    if v := entry.get("LensModel"):
        exif[piexif.ExifIFD.LensModel] = _ascii(v)
    if v := entry.get("SpectralSensitivity"):
        exif[piexif.ExifIFD.SpectralSensitivity] = _ascii(v)
    if v := entry.get("ImageUniqueID"):
        exif[piexif.ExifIFD.ImageUniqueID] = _ascii(v)

    # Combine Notes + UserComment into the UserComment field so neither is lost.
    comment_parts = []
    if v := entry.get("Notes"):
        comment_parts.append(f"Notes: {v}")
    if v := entry.get("UserComment"):
        comment_parts.append(str(v))
    if v := entry.get("ReelName"):
        comment_parts.append(f"ReelName: {v}")
    if (v := entry.get("ImageNumber")) is not None:
        comment_parts.append(f"ImageNumber: {v}")
    if comment_parts:
        exif[piexif.ExifIFD.UserComment] = _user_comment("\n\n".join(comment_parts))

    lat = entry.get("GPSLatitude")
    lon = entry.get("GPSLongitude")
    if lat and lon:
        lat_ref = (entry.get("GPSLatitudeRef") or lat)[0].upper()
        lon_ref = (entry.get("GPSLongitudeRef") or lon)[0].upper()
        gps[piexif.GPSIFD.GPSLatitude] = _parse_gps(lat)
        gps[piexif.GPSIFD.GPSLatitudeRef] = lat_ref.encode("ascii")
        gps[piexif.GPSIFD.GPSLongitude] = _parse_gps(lon)
        gps[piexif.GPSIFD.GPSLongitudeRef] = lon_ref.encode("ascii")
        gps[piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)

    exif_dict = {"0th": zeroth, "Exif": exif, "GPS": gps, "1st": {}, "thumbnail": None}
    return piexif.dump(exif_dict)


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------

def _parse_number(value: Any) -> float | None:
    """Parse a number that may be a fraction string like ``"1/125"``.

    Returns ``None`` when the value is blank or unparseable.
    """
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().rstrip("sS")  # tolerate a trailing "s" on shutter speeds
    if not s:
        return None
    try:
        return float(Fraction(s)) if "/" in s else float(s)
    except (ValueError, ZeroDivisionError):
        return None


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Clean a raw entry before :func:`build_exif`.

    Strips whitespace from strings, drops empty/``None`` values (so the guarded
    ``float()``/``int()`` calls in :func:`build_exif` are never handed ``""``),
    and coerces fractional numeric strings (e.g. a ``"1/125"`` shutter speed) to
    floats.

    Args:
        entry: A raw metadata dict, typically assembled from UI fields.

    Returns:
        A new, cleaned dict safe to pass to :func:`build_exif`.
    """
    out: dict[str, Any] = {}
    for key, value in entry.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if key in _NUMERIC_KEYS:
            num = _parse_number(value)
            if num is None:
                continue
            value = num
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Output naming + writing (ported from analog_import/ingest.py)
# ---------------------------------------------------------------------------

def _sanitize(name: str) -> str:
    return name.replace(" ", "_")


def output_path(
    export_root: Path,
    reel_name: str,
    document_name: str,
    image_number: Any,
    ext: str,
) -> Path:
    """Build the destination path for a tagged frame.

    Mirrors the ``analog_import`` convention:
    ``{export_root}/{reel}-{sanitized_document}/{reel}-{number:04d}{ext}``.

    Args:
        export_root: Parent directory chosen by the user.
        reel_name: Reel identifier (folder + filename prefix).
        document_name: Human label (e.g. film stock); spaces become underscores.
        image_number: Frame number; zero-padded to four digits.
        ext: File extension including the leading dot (lower-cased here).

    Returns:
        The full destination ``Path`` (parent directory not yet created).
    """
    folder = f"{reel_name}-{_sanitize(document_name)}"
    filename = f"{reel_name}-{int(image_number):04d}{ext.lower()}"
    return Path(export_root) / folder / filename


def _write_jpeg(src: Path, dst: Path, exif_bytes: bytes) -> None:
    # Copy bytes so pixels are bit-for-bit identical, then splice EXIF in.
    shutil.copy2(src, dst)
    piexif.insert(exif_bytes, str(dst))


def _write_tiff(src: Path, dst: Path, exif_bytes: bytes) -> None:
    # TIFF EXIF is structured differently from JPEG; round-trip through Pillow,
    # preserving the original compression scheme where possible.
    with Image.open(src) as img:
        img.load()
        compression = img.info.get("compression", "tiff_lzw")
        img.save(dst, format="TIFF", exif=exif_bytes, compression=compression)


def write_image(src: Path, dst: Path, exif_bytes: bytes) -> None:
    """Write *src* to *dst* with *exif_bytes* embedded, creating parent dirs.

    Args:
        src: Source image (``.jpg``/``.jpeg``/``.tif``/``.tiff``).
        dst: Destination path.
        exif_bytes: EXIF block from :func:`build_exif`.

    Raises:
        ValueError: If *src* has an unsupported extension.
    """
    ext = src.suffix.lower()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ext in JPEG_EXTS:
        _write_jpeg(src, dst, exif_bytes)
    elif ext in TIFF_EXTS:
        _write_tiff(src, dst, exif_bytes)
    else:
        raise ValueError(f"unsupported extension: {ext}")
