"""
Shared pytest fixtures that build a temporary directory of synthetic test images.

Scenarios covered
-----------------
full_exif      – JPEG with DateTimeOriginal + Make + Model
date_only      – JPEG with DateTimeOriginal but no camera tags
no_exif        – JPEG with no EXIF at all
wrong_date_fmt – JPEG with a malformed date string
png_no_exif    – PNG (no EXIF support in most encoders) — tests extension handling
raf_with_exif  – Fujifilm RAF v2 with embedded JPEG EXIF
mov_with_date  – Minimal QuickTime file with a Mac-epoch creation_time
"""

import io
import struct
from datetime import datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_exif() -> dict:
    """Return a minimal piexif structure with empty sub-dicts."""
    return {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}


def _make_jpeg(path: Path, exif_dict: dict | None) -> Path:
    """Save a 1×1 RGB JPEG to *path*, optionally embedding *exif_dict*."""
    img = Image.new("RGB", (1, 1), color=(100, 149, 237))
    kwargs = {}
    if exif_dict is not None:
        kwargs["exif"] = piexif.dump(exif_dict)
    img.save(path, format="JPEG", **kwargs)
    return path


def _make_png(path: Path) -> Path:
    """Save a 1×1 RGB PNG (no EXIF) to *path*."""
    img = Image.new("RGB", (1, 1), color=(255, 165, 0))
    img.save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Individual file fixtures  (each writes to pytest's tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture()
def jpeg_full_exif(tmp_path) -> Path:
    """JPEG with DateTimeOriginal, Make, and Model."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2023:06:15 10:30:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    return _make_jpeg(tmp_path / "full_exif.jpg", exif)


@pytest.fixture()
def jpeg_date_only(tmp_path) -> Path:
    """JPEG with DateTimeOriginal but no camera tags."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2021:12:01 08:00:00"
    return _make_jpeg(tmp_path / "date_only.jpg", exif)


@pytest.fixture()
def jpeg_no_exif(tmp_path) -> Path:
    """JPEG with no EXIF data at all."""
    return _make_jpeg(tmp_path / "no_exif.jpg", None)


@pytest.fixture()
def jpeg_wrong_date_fmt(tmp_path) -> Path:
    """JPEG with a malformed date string."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"not-a-date"
    exif["0th"][piexif.ImageIFD.Make] = b"Sony"
    exif["0th"][piexif.ImageIFD.Model] = b"A7 IV"
    return _make_jpeg(tmp_path / "wrong_date.jpg", exif)


@pytest.fixture()
def png_no_exif(tmp_path) -> Path:
    """PNG file — no EXIF, tests extension handling."""
    return _make_png(tmp_path / "image.png")


def _make_raf(path: Path, exif_dict: dict | None) -> Path:
    """Build a minimal Fujifilm RAF v2 binary with an embedded JPEG."""
    jpeg_buf = io.BytesIO()
    img = Image.new("RGB", (1, 1), color=(100, 149, 237))
    kwargs = {"exif": piexif.dump(exif_dict)} if exif_dict else {}
    img.save(jpeg_buf, format="JPEG", **kwargs)
    jpeg_data = jpeg_buf.getvalue()

    jpeg_offset = 128
    header = (
        b"FUJIFILMCCD-RAW "          # 16  magic
        + b"0200"                     #  4  version
        + b"\x00" * 8                 #  8  camera model ID
        + b"\x00" * 32                # 32  camera model string
        + b"0100"                     #  4  directory version
        + b"\x00" * 20                # 20  unknown
        + struct.pack(">II",          #  8  JPEG offset + size
                      jpeg_offset, len(jpeg_data))
        + b"\x00" * 16                # 16  CFA fields (offset/size x 2)
        + b"\x00" * 20                # 20  trailing padding
    )                                 # = 128 bytes total
    assert len(header) == 128
    path.write_bytes(header + jpeg_data)
    return path


@pytest.fixture()
def raf_with_exif(tmp_path) -> Path:
    """Fujifilm RAF v2 file with DateTimeOriginal, Make, and Model."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2022:09:10 07:15:00"
    exif["0th"][piexif.ImageIFD.Make] = b"FUJIFILM"
    exif["0th"][piexif.ImageIFD.Model] = b"X-T5"
    return _make_raf(tmp_path / "test.raf", exif)


def _atom(fourcc: bytes, data: bytes) -> bytes:
    """Wrap *data* in an ISO-BMFF/QuickTime atom (size + fourcc + payload)."""
    return struct.pack(">I", 8 + len(data)) + fourcc + data


def _mvhd_atom(mac_epoch_seconds: int) -> bytes:
    """Build a minimal ``mvhd`` atom carrying the given Mac-epoch creation time."""
    identity_matrix = struct.pack(
        ">9i",
        0x00010000, 0, 0,
        0, 0x00010000, 0,
        0, 0, 0x40000000,
    )
    mvhd_data = (
        b"\x00\x00\x00\x00"
        + struct.pack(">II", mac_epoch_seconds, mac_epoch_seconds)
        + struct.pack(">II", 600, 0)
        + struct.pack(">I", 0x00010000)
        + struct.pack(">H", 0x0100)
        + b"\x00" * 10
        + identity_matrix
        + b"\x00" * 24
        + struct.pack(">I", 1)
    )
    return _atom(b"mvhd", mvhd_data)


def _make_mov(path: Path, mac_epoch_seconds: int) -> Path:
    """Build a minimal QuickTime file (ftyp + moov/mvhd) with the given creation time."""
    ftyp = _atom(b"ftyp", b"qt  " + struct.pack(">I", 0) + b"qt  ")
    moov = _atom(b"moov", _mvhd_atom(mac_epoch_seconds))
    path.write_bytes(ftyp + moov)
    return path


def _make_mov_apple_meta(
    path: Path, make: str, model: str, creationdate: str, mac_epoch_seconds: int
) -> Path:
    """Build a MOV with an Apple-style ``moov/meta`` keys/ilst metadata table."""
    key_names = [
        b"com.apple.quicktime.make",
        b"com.apple.quicktime.model",
        b"com.apple.quicktime.creationdate",
    ]
    entries = b"".join(
        struct.pack(">I", 8 + len(name)) + b"mdta" + name for name in key_names
    )
    keys_atom = _atom(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", len(key_names)) + entries)

    def item(index: int, value: str) -> bytes:
        # data atom = type(4, 1 == UTF-8) + locale(4) + value
        data_atom = _atom(b"data", struct.pack(">II", 1, 0) + value.encode("utf-8"))
        return struct.pack(">I", 8 + len(data_atom)) + struct.pack(">I", index) + data_atom

    ilst_atom = _atom(b"ilst", item(1, make) + item(2, model) + item(3, creationdate))
    # QuickTime `meta` has no version/flags prefix (unlike MP4).
    meta_atom = _atom(b"meta", keys_atom + ilst_atom)
    moov = _atom(b"moov", _mvhd_atom(mac_epoch_seconds) + meta_atom)
    ftyp = _atom(b"ftyp", b"qt  " + struct.pack(">I", 0) + b"qt  ")
    path.write_bytes(ftyp + moov)
    return path


def _make_mov_fuji_udta(path: Path, info: str, mac_epoch_seconds: int) -> Path:
    """Build a MOV with a Fujifilm-style ``moov/udta`` ``©inf`` description atom."""
    text = info.encode("utf-8")
    inf_atom = _atom(b"\xa9inf", struct.pack(">H", len(text)) + b"\x00\x00" + text)
    moov = _atom(b"moov", _mvhd_atom(mac_epoch_seconds) + _atom(b"udta", inf_atom))
    ftyp = _atom(b"ftyp", b"qt  " + struct.pack(">I", 0) + b"qt  ")
    path.write_bytes(ftyp + moov)
    return path


_MAC_1960 = 1_767_225_600  # 1960-01-01 00:00:00 UTC in Mac epoch seconds


@pytest.fixture()
def mov_with_date(tmp_path) -> Path:
    """Minimal QuickTime MOV with a 1960-01-01 creation date."""
    return _make_mov(tmp_path / "test.mov", _MAC_1960)


@pytest.fixture()
def mov_apple_meta(tmp_path) -> Path:
    """MOV with Apple ``moov/meta`` make/model and a tz-aware creation date.

    The mvhd date is deliberately 1960 so the test proves the precise
    ``com.apple.quicktime.creationdate`` takes priority over the container date.
    """
    return _make_mov_apple_meta(
        tmp_path / "iphone.mov",
        make="Apple",
        model="iPhone 17 Pro",
        creationdate="2026-05-09T15:08:49-0700",
        mac_epoch_seconds=_MAC_1960,
    )


@pytest.fixture()
def mov_fuji_udta(tmp_path) -> Path:
    """MOV with a Fujifilm ``©inf`` description and a 1960-01-01 container date."""
    return _make_mov_fuji_udta(
        tmp_path / "fuji.mov",
        info="FUJIFILM DIGITAL CAMERA X-S20",
        mac_epoch_seconds=_MAC_1960,
    )


# ---------------------------------------------------------------------------
# Composite fixture: a source directory with all scenarios
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_source_dir(tmp_path) -> Path:
    """
    A source directory containing one file per scenario plus a nested subdir.

    Layout
    ------
    source/
        full_exif.jpg       – Canon EOS R5, 2023-06-15
        date_only.jpg       – no camera, 2021-12-01
        no_exif.jpg         – no metadata
        wrong_date.jpg      – Sony A7 IV, bad date string
        image.png           – PNG, no EXIF
        subdir/
            nested.jpg      – Nikon Z6, 2020-03-22  (tests recursive walk)
    """
    src = tmp_path / "source"
    src.mkdir()

    # full_exif
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2023:06:15 10:30:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    _make_jpeg(src / "full_exif.jpg", exif)

    # date_only
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2021:12:01 08:00:00"
    _make_jpeg(src / "date_only.jpg", exif)

    # no_exif
    _make_jpeg(src / "no_exif.jpg", None)

    # wrong_date
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"not-a-date"
    exif["0th"][piexif.ImageIFD.Make] = b"Sony"
    exif["0th"][piexif.ImageIFD.Model] = b"A7 IV"
    _make_jpeg(src / "wrong_date.jpg", exif)

    # png
    _make_png(src / "image.png")

    # nested subdir
    subdir = src / "subdir"
    subdir.mkdir()
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2020:03:22 14:45:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Nikon"
    exif["0th"][piexif.ImageIFD.Model] = b"Z6"
    _make_jpeg(subdir / "nested.jpg", exif)

    return src
