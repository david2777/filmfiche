"""Tests for the film tagger core (app/core/tagger.py) and model (film_frame.py)."""

from pathlib import Path

import piexif
import pytest
from PIL import Image

from app.core.tagger import (
    build_exif,
    normalize_entry,
    output_path,
    write_image,
)
from app.models.film_frame import (
    FilmFrame,
    build_full_entry,
    frames_from_json,
)

_USER_COMMENT_PREFIX = b"UNICODE\x00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg(path: Path) -> Path:
    Image.new("RGB", (8, 8), color=(120, 90, 200)).save(path, format="JPEG")
    return path


def _make_tiff(path: Path) -> Path:
    Image.new("RGB", (8, 8), color=(30, 160, 70)).save(path, format="TIFF")
    return path


def _sample_entry() -> dict:
    return {
        "Make": "Olympus",
        "Model": "OM-2n",
        "DateTimeOriginal": "2026:05:05 20:04:14",
        "FNumber": 1.8,
        "LensModel": "Zuiko 50mm",
        "Notes": "test note",
        "ReelName": "1003",
        "ImageNumber": 1,
    }


# ---------------------------------------------------------------------------
# build_exif / write_image
# ---------------------------------------------------------------------------

def test_build_exif_round_trip_jpeg(tmp_path):
    """EXIF assembled by build_exif survives a JPEG write and reads back."""
    src = _make_jpeg(tmp_path / "scan.jpg")
    dst = tmp_path / "out.jpg"

    write_image(src, dst, build_exif(_sample_entry()))

    loaded = piexif.load(str(dst))
    assert loaded["0th"][piexif.ImageIFD.Make] == b"Olympus"
    assert loaded["0th"][piexif.ImageIFD.Model] == b"OM-2n"
    assert loaded["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2026:05:05 20:04:14"
    assert loaded["Exif"][piexif.ExifIFD.LensModel] == b"Zuiko 50mm"

    num, den = loaded["Exif"][piexif.ExifIFD.FNumber]
    assert num / den == pytest.approx(1.8, abs=1e-3)

    comment = loaded["Exif"][piexif.ExifIFD.UserComment]
    assert comment.startswith(_USER_COMMENT_PREFIX)
    text = comment[len(_USER_COMMENT_PREFIX):].decode("utf-16-be")
    assert "Notes: test note" in text
    assert "ReelName: 1003" in text


def test_build_exif_jpeg_pixels_unchanged(tmp_path):
    """JPEG export copies pixel bytes verbatim (only EXIF is spliced in)."""
    src = _make_jpeg(tmp_path / "scan.jpg")
    dst = tmp_path / "out.jpg"

    write_image(src, dst, build_exif(_sample_entry()))

    with Image.open(src) as a, Image.open(dst) as b:
        assert a.tobytes() == b.tobytes()


def test_write_image_tiff(tmp_path):
    """TIFF export embeds EXIF and stays a readable TIFF."""
    src = _make_tiff(tmp_path / "scan.tif")
    dst = tmp_path / "out.tif"

    write_image(src, dst, build_exif(_sample_entry()))

    assert dst.exists()
    with Image.open(dst) as img:
        assert img.format == "TIFF"
        exif = img.getexif()
    assert str(exif.get(piexif.ImageIFD.Make, "")).startswith("Olympus")


def test_write_image_rejects_unsupported(tmp_path):
    """A non-JPEG/TIFF source raises ValueError."""
    src = tmp_path / "scan.png"
    Image.new("RGB", (8, 8)).save(src, format="PNG")
    with pytest.raises(ValueError):
        write_image(src, tmp_path / "out.png", build_exif(_sample_entry()))


def test_build_exif_gps(tmp_path):
    """GPS strings are parsed into rationals and a ref byte."""
    src = _make_jpeg(tmp_path / "scan.jpg")
    dst = tmp_path / "out.jpg"
    entry = {
        "GPSLatitude": "34deg 9' 37.89\" N",
        "GPSLatitudeRef": "North",
        "GPSLongitude": "118deg 22' 31.86\" W",
        "GPSLongitudeRef": "West",
    }
    write_image(src, dst, build_exif(entry))

    gps = piexif.load(str(dst))["GPS"]
    assert gps[piexif.GPSIFD.GPSLatitudeRef] == b"N"
    assert gps[piexif.GPSIFD.GPSLongitudeRef] == b"W"
    assert gps[piexif.GPSIFD.GPSLatitude][0] == (34, 1)


# ---------------------------------------------------------------------------
# output_path
# ---------------------------------------------------------------------------

def test_output_path_naming(tmp_path):
    """Output path follows {reel}-{document}/{reel}-{number:04d}{ext}."""
    dest = output_path(tmp_path, "1003", "Kodak Gold 200", 7, ".JPG")
    assert dest == tmp_path / "1003-Kodak_Gold_200" / "1003-0007.jpg"


# ---------------------------------------------------------------------------
# normalize_entry
# ---------------------------------------------------------------------------

def test_normalize_entry_parses_fraction_shutter():
    out = normalize_entry({"ExposureTime": "1/125"})
    assert out["ExposureTime"] == pytest.approx(1 / 125)


def test_normalize_entry_drops_blanks():
    out = normalize_entry({"FNumber": "", "Notes": "   ", "LensModel": "50mm"})
    assert "FNumber" not in out
    assert "Notes" not in out
    assert out["LensModel"] == "50mm"


def test_normalize_entry_keeps_zero_exposure():
    out = normalize_entry({"ExposureTime": 0})
    assert out["ExposureTime"] == 0.0


# ---------------------------------------------------------------------------
# build_full_entry
# ---------------------------------------------------------------------------

def test_build_full_entry_merges_and_defaults():
    frame = FilmFrame(Path("x.jpg"), {"ImageNumber": 4, "LensModel": "50mm"})
    entry = build_full_entry(frame, {"Make": "Olympus", "ReelName": "1003"})

    assert entry["Make"] == "Olympus"
    assert entry["LensModel"] == "50mm"
    assert entry["ImageUniqueID"] == "1003_4"
    # Reel-level defaults are applied.
    assert entry["Software"] == "Filmfiche"
    assert entry["SensitivityType"] == 3
    assert entry["FileSource"] == 1


def test_build_full_entry_frame_overrides_globals():
    frame = FilmFrame(Path("x.jpg"), {"ImageNumber": 1, "Software": "Custom"})
    entry = build_full_entry(frame, {"ReelName": "1003", "Software": "Filmfiche"})
    assert entry["Software"] == "Custom"


# ---------------------------------------------------------------------------
# frames_from_json
# ---------------------------------------------------------------------------

def _json_entries() -> list[dict]:
    return [
        {
            "Make": "Olympus",
            "Model": "OM-2n",
            "ReelName": "1003",
            "DocumentName": "Kodak Gold 200",
            "SpectralSensitivity": "Kodak Gold 200",
            "ISO": 200,
            "ImageNumber": 1,
            "DateTimeOriginal": "2026:05:05 20:04:14",
            "FNumber": 1.8,
            "LensModel": "Zuiko 50mm",
            "Notes": "first",
        },
        {
            "Make": "Olympus",
            "Model": "OM-2n",
            "ReelName": "1003",
            "DocumentName": "Kodak Gold 200",
            "ImageNumber": 2,
            "DateTimeOriginal": "2026:05:06 06:38:37",
            "FNumber": 2.8,
            "Notes": "second",
        },
    ]


def test_frames_from_json_pairs_by_order():
    frames = [FilmFrame(Path(f"{i}.jpg")) for i in range(2)]
    globals_dict, out, warning = frames_from_json(_json_entries(), frames)

    assert warning is None
    assert globals_dict["Make"] == "Olympus"
    assert globals_dict["ReelName"] == "1003"
    assert globals_dict["SpectralSensitivity"] == "Kodak Gold 200"
    assert globals_dict["ISO"] == 200
    # Reel-level keys are not copied into per-frame entries.
    assert "Make" not in out[0].entry
    assert out[0].entry["DateTimeOriginal"] == "2026:05:05 20:04:14"
    assert out[0].entry["Notes"] == "first"
    assert out[1].entry["FNumber"] == 2.8


def test_frames_from_json_warns_on_mismatch():
    frames = [FilmFrame(Path("0.jpg"))]
    _, out, warning = frames_from_json(_json_entries(), frames)
    assert warning is not None
    assert out[0].entry["ImageNumber"] == 1


def test_frames_from_json_rejects_non_list():
    with pytest.raises(ValueError):
        frames_from_json({"not": "a list"}, [])
