"""EXIF embedding for scanned film frames.

Ported from the standalone ``analog_import`` CLI. Maps a metadata dict (using the
Lightme/Logbook JSON key names) to EXIF bytes via piexif, and writes a source
image to a destination with that EXIF embedded:

* JPEGs are copied byte-for-byte and the EXIF block is spliced in, so pixels are
  never re-encoded.
* TIFFs are round-tripped through Pillow with their original compression
  preserved.
* 16-bit colour TIFFs (48-bit RGB) are instead round-tripped through tifffile,
  because Pillow has no 16-bit-per-channel RGB mode and would truncate them to
  8 bits on open. tifffile can't write EXIF/GPS sub-IFDs, so the same metadata is
  flattened into the top-level (IFD0) TIFF tags, which standard readers accept.

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
import tifffile
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


def _build_exif_ifds(
    entry: dict[str, Any],
) -> tuple[dict[int, Any], dict[int, Any], dict[int, Any]]:
    """Build the ``(0th, Exif, GPS)`` tag dicts (piexif tag-code keys) for *entry*."""
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

    return zeroth, exif, gps


def build_exif(entry: dict[str, Any]) -> bytes:
    """Assemble EXIF bytes from a metadata *entry* dict.

    Args:
        entry: Metadata using the Lightme/Logbook JSON key names (``Make``,
            ``Model``, ``DateTimeOriginal``, ``FNumber``, ``LensModel``, ``Notes``,
            GPS fields, etc.). Missing keys are simply skipped.

    Returns:
        EXIF bytes suitable for :func:`piexif.insert` or Pillow's ``exif=`` arg.
    """
    zeroth, exif, gps = _build_exif_ifds(entry)
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


# IFD0 / EXIF-IFD pointer tags — never flattened (no value of their own), plus
# tags tifffile writes itself via dedicated imwrite arguments below.
_TIFF_POINTER_TAGS = {330, 34665, 34853, 40965}
_TIFF_MANAGED_TAGS = {270, 305}  # ImageDescription, Software


def _to_extratag(code: int, value: Any, tiff_type: int) -> tuple | None:
    """Convert a piexif ``(code, value)`` tag to a tifffile ``extratags`` entry."""
    if tiff_type == piexif.TYPES.Ascii:
        text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)
        text = text.rstrip("\x00")
        return (code, 2, len(text) + 1, text, True)
    if tiff_type == piexif.TYPES.Undefined:
        data = bytes(value)
        return (code, 7, len(data), data, True)
    if tiff_type in (piexif.TYPES.Short, piexif.TYPES.Long, piexif.TYPES.SShort, piexif.TYPES.SLong):
        return (code, tiff_type, 1, int(value), True)
    if tiff_type in (piexif.TYPES.Rational, piexif.TYPES.SRational):
        return (code, tiff_type, 1, (int(value[0]), int(value[1])), True)
    return None


def _exif_extratags(zeroth: dict[int, Any], exif: dict[int, Any]) -> list[tuple]:
    """Flatten the 0th + EXIF tag dicts into tifffile ``extratags`` (IFD0 level).

    tifffile cannot write the nested EXIF sub-IFD, so the EXIF-IFD tags are written
    directly into IFD0. This is valid per TIFF/EP and read by exiftool/Lightroom/
    Pillow. Pointer tags and the tags tifffile writes itself are skipped.
    """
    extratags = []
    for table, ifd in (("Image", zeroth), ("Exif", exif)):
        for code, value in ifd.items():
            if code in _TIFF_POINTER_TAGS or code in _TIFF_MANAGED_TAGS:
                continue
            tag = _to_extratag(code, value, piexif.TAGS[table][code]["type"])
            if tag is not None:
                extratags.append(tag)
    return extratags


def _high_bit_description(entry: dict[str, Any]) -> str | None:
    """Build the ImageDescription, appending GPS as text (no GPS sub-IFD here)."""
    parts = []
    if desc := entry.get("Description"):
        parts.append(str(desc))
    lat, lon = entry.get("GPSLatitude"), entry.get("GPSLongitude")
    if lat and lon:
        parts.append(f"GPS: {lat}, {lon}")
    return "\n".join(parts) or None


def _write_tiff_16bit_if_high(src: Path, dst: Path, entry: dict[str, Any]) -> bool:
    """Write *src* via tifffile if it is a >8-bit multi-channel TIFF; else no-op.

    Returns ``True`` when it handled the file. These are the scans Pillow truncates
    to 8 bits on open (e.g. 48-bit RGB); 16-bit grayscale (one sample) returns
    ``False`` so it stays on the lossless Pillow path.
    """
    with tifffile.TiffFile(src) as tf:
        page = tf.pages[0]
        if not (page.dtype is not None and page.dtype.itemsize > 1 and page.samplesperpixel > 1):
            return False
        _write_tiff_16bit(page, dst, entry)
        return True


def _write_tiff_16bit(page: tifffile.TiffPage, dst: Path, entry: dict[str, Any]) -> None:
    """Write a >8-bit multi-channel TIFF *page* to *dst*, preserving bit depth.

    Pixels are round-tripped losslessly via tifffile (Pillow would truncate to
    8 bits); the ICC profile and resolution are carried over, and *entry*'s
    metadata is flattened into IFD0 tags.
    """
    arr = page.asarray()
    icc_tag = page.tags.get("InterColorProfile")
    icc = icc_tag.value if icc_tag is not None else None

    zeroth, exif, _gps = _build_exif_ifds(entry)
    kwargs: dict[str, Any] = {
        "photometric": "rgb" if arr.ndim == 3 and arr.shape[2] >= 3 else "minisblack",
        "metadata": None,  # suppress tifffile's JSON ImageDescription
        "extratags": _exif_extratags(zeroth, exif),
        "software": entry.get("Software") or False,
    }
    if icc:
        kwargs["iccprofile"] = icc
    if (compression := _tiff_compression(page)) is not None:
        kwargs["compression"] = compression
    if description := _high_bit_description(entry):
        kwargs["description"] = description
    if (res := _tiff_resolution(page)) is not None:
        kwargs["resolution"], kwargs["resolutionunit"] = res
    tifffile.imwrite(dst, arr, **kwargs)


# Source compression → a codec tifffile can write without the imagecodecs package.
# Uncompressed stays uncompressed; everything else (LZW, PackBits, …) falls back to
# deflate so output never balloons relative to a compressed source.
_DEFLATE = "adobe_deflate"
_TIFF_COMPRESSION = {1: None, 8: _DEFLATE, 32946: _DEFLATE}


def _tiff_compression(page: tifffile.TiffPage) -> str | None:
    """Return a writable tifffile compression codec matching *page*'s source."""
    return _TIFF_COMPRESSION.get(int(page.compression), _DEFLATE)


def _tiff_resolution(page: tifffile.TiffPage) -> tuple[tuple[float, float], int | None] | None:
    """Return ``((xres, yres), unit)`` from *page* if both resolutions are present."""
    xr = page.tags.get("XResolution")
    yr = page.tags.get("YResolution")
    if xr is None or yr is None:
        return None
    unit = page.tags.get("ResolutionUnit")
    return (_rational_value(xr.value), _rational_value(yr.value)), (unit.value if unit else None)


def _rational_value(value: Any) -> float:
    """Coerce a TIFF rational (``(num, den)`` or scalar) to a float."""
    if isinstance(value, (tuple, list)):
        num, den = value
        return num / den if den else float(num)
    return float(value)


def write_image(src: Path, dst: Path, exif_bytes: bytes, entry: dict[str, Any] | None = None) -> None:
    """Write *src* to *dst* with *exif_bytes* embedded, creating parent dirs.

    Args:
        src: Source image (``.jpg``/``.jpeg``/``.tif``/``.tiff``).
        dst: Destination path.
        exif_bytes: EXIF block from :func:`build_exif`.
        entry: The normalised metadata dict. Required only to preserve bit depth on
            16-bit colour TIFFs (its tags are re-flattened into IFD0); without it
            such files fall back to the 8-bit Pillow path.

    Raises:
        ValueError: If *src* has an unsupported extension.
    """
    ext = src.suffix.lower()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ext in JPEG_EXTS:
        _write_jpeg(src, dst, exif_bytes)
    elif ext in TIFF_EXTS:
        if not (entry is not None and _write_tiff_16bit_if_high(src, dst, entry)):
            _write_tiff(src, dst, exif_bytes)
    else:
        raise ValueError(f"unsupported extension: {ext}")
