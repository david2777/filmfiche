"""Tests for the half-frame splitter core (app/core/half_frame.py)."""

from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from app.core.half_frame import (
    crop_to_aspect,
    detect_seam_x,
    process_file,
    split_image,
)

_GAP = (580, 620)  # uniform gap band columns in the synthetic scan


def _make_scan(path: Path | None = None, w: int = 1200, h: int = 800) -> Image.Image:
    """Build a synthetic half-frame scan: two noisy halves + a uniform gap band.

    Left half is dark noise, right half is bright noise (so the two are
    distinguishable), and the central gap band is a constant value (zero vertical
    variance) so the detector should land inside it.
    """
    rng = np.random.default_rng(0)
    arr = np.empty((h, w, 3), dtype=np.uint8)
    arr[:, : _GAP[0]] = rng.normal(80, 40, (h, _GAP[0], 3)).clip(0, 255).astype(np.uint8)
    arr[:, _GAP[1]:] = rng.normal(200, 40, (h, w - _GAP[1], 3)).clip(0, 255).astype(np.uint8)
    arr[:, _GAP[0]: _GAP[1]] = 128
    img = Image.fromarray(arr)
    if path is not None:
        img.save(path)
    return img


# ---------------------------------------------------------------------------
# detect_seam_x
# ---------------------------------------------------------------------------

def test_detect_seam_lands_in_gap():
    gray = np.asarray(_make_scan().convert("L"))
    seam = detect_seam_x(gray)
    assert _GAP[0] <= seam <= _GAP[1]


def test_detect_seam_narrow_image_falls_back_to_center():
    gray = np.zeros((10, 3), dtype=np.uint8)
    assert detect_seam_x(gray) == 1


# ---------------------------------------------------------------------------
# crop_to_aspect
# ---------------------------------------------------------------------------

def test_crop_to_aspect_too_wide():
    out = crop_to_aspect(Image.new("RGB", (1000, 1000)), (3, 4))
    assert out.size == (750, 1000)


def test_crop_to_aspect_too_tall():
    out = crop_to_aspect(Image.new("RGB", (300, 1000)), (3, 4))
    assert out.size == (300, 400)


def test_crop_to_aspect_already_correct_is_noop():
    img = Image.new("RGB", (600, 800))
    assert crop_to_aspect(img, (3, 4)) is img


# ---------------------------------------------------------------------------
# split_image
# ---------------------------------------------------------------------------

def test_split_image_halves_are_3x4():
    img = _make_scan()
    left, right = split_image(img, seam_x=600)
    for half in (left, right):
        w, h = half.size
        assert abs(w / h - 0.75) < 0.01


def test_split_image_gap_drops_pixels_each_side():
    img = Image.new("RGB", (1000, 800))
    left, right = split_image(img, seam_x=500, gap=20, aspect=(1, 1))
    # left spans 0..480, right spans 520..1000; both cropped to square.
    assert left.size == (480, 480)
    assert right.size == (480, 480)


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------

def test_process_file_writes_a_and_b(tmp_path):
    src = tmp_path / "scan.jpg"
    _make_scan(src)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out)

    assert left_path == out / "scan-a.jpg"
    assert right_path == out / "scan-b.jpg"
    assert left_path.exists() and right_path.exists()


def test_process_file_left_is_darker_than_right(tmp_path):
    """The -a output is the (dark) left half, -b the (bright) right half."""
    src = tmp_path / "scan.jpg"
    _make_scan(src)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out)

    with Image.open(left_path) as a, Image.open(right_path) as b:
        assert np.asarray(a).mean() < np.asarray(b).mean()
        for half in (a, b):
            w, h = half.size
            assert abs(w / h - 0.75) < 0.01


def test_process_file_center_mode_splits_at_middle(tmp_path):
    src = tmp_path / "scan.png"
    _make_scan(src, w=1000, h=800)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out, mode="center")

    # Middle split of a 1000px-wide scan → each half 500px, cropped to 3:4.
    with Image.open(left_path) as a:
        w, h = a.size
        assert abs(w / h - 0.75) < 0.01
    assert left_path.suffix == ".png" and right_path.suffix == ".png"


# ---------------------------------------------------------------------------
# 16-bit TIFF bit-depth preservation
# ---------------------------------------------------------------------------

def _make_scan_16bit_rgb(path: Path, *, icc: bytes | None = None, w: int = 1200, h: int = 800):
    """Write a synthetic 48-bit (16-bit/channel) RGB half-frame scan via tifffile."""
    rng = np.random.default_rng(0)
    arr = np.empty((h, w, 3), dtype=np.uint16)
    arr[:, : _GAP[0]] = (rng.random((h, _GAP[0], 3)) * 20000 + 5000).astype(np.uint16)
    arr[:, _GAP[1]:] = (rng.random((h, w - _GAP[1], 3)) * 20000 + 40000).astype(np.uint16)
    arr[:, _GAP[0]: _GAP[1]] = 30000  # uniform gap band
    extratags = [(34675, 7, len(icc), icc, True)] if icc else []
    tifffile.imwrite(path, arr, photometric="rgb", extratags=extratags)


def test_process_file_preserves_16bit_rgb(tmp_path):
    """48-bit RGB TIFFs keep their full bit depth (Pillow would truncate to 8)."""
    src = tmp_path / "colour.tif"
    _make_scan_16bit_rgb(src)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out)

    for p in (left_path, right_path):
        with tifffile.TiffFile(p) as tf:
            page = tf.pages[0]
            arr = page.asarray()
            assert arr.dtype == np.uint16
            assert page.bitspersample == 16
            assert page.samplesperpixel == 3
            h2, w2 = arr.shape[:2]
            assert abs(w2 / h2 - 0.75) < 0.01
            # Real 16-bit detail survives (values above the 8-bit-truncation range).
            assert int(arr.max()) > 255


def test_process_file_carries_icc_for_16bit_rgb(tmp_path):
    src = tmp_path / "colour.tif"
    icc = b"FAKE-ICC-PROFILE" * 8
    _make_scan_16bit_rgb(src, icc=icc)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out)

    for p in (left_path, right_path):
        with tifffile.TiffFile(p) as tf:
            tag = tf.pages[0].tags.get("InterColorProfile")
            assert tag is not None and tag.value == icc


def test_process_file_preserves_16bit_grayscale(tmp_path):
    """16-bit grayscale stays on the (lossless) Pillow path and keeps its depth."""
    src = tmp_path / "bw.tif"
    rng = np.random.default_rng(1)
    arr = (rng.random((800, 1200)) * 65535).astype(np.uint16)
    arr[:, _GAP[0]: _GAP[1]] = 30000
    Image.fromarray(arr).save(src)
    out = tmp_path / "out"

    left_path, right_path = process_file(src, out)

    for p in (left_path, right_path):
        with Image.open(p) as im:
            assert im.mode == "I;16"
            assert int(np.asarray(im).max()) > 255
