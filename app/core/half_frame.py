"""Split half-frame scans into two cropped photos.

A lab scan of a half-frame negative is a single landscape image holding two
portrait photos side by side, separated by a uniform film-gap band. This module
locates that central seam, splits the scan, crops each half to a target aspect
ratio (3:4 by default), and writes the two photos out.

Seam detection is a 1-D projection-profile problem: each column gets a "detail"
score (vertical variance), and within a central search window the column with the
*lowest* smoothed score is the seam — the gap band is uniform top-to-bottom while
real frame content is textured. Pillow handles I/O and cropping; NumPy handles the
profile maths.

Pillow has no native 16-bit-per-channel RGB image mode, so it silently truncates
48-bit colour TIFF scans to 8 bits on open. Such files (multi-channel, >8-bit) are
instead read, cropped, and written via :mod:`tifffile` in a NumPy pipeline that
preserves full bit depth and the ICC profile. 16-bit grayscale (Pillow ``I;16``)
and all 8-bit formats stay on the Pillow path, which already round-trips losslessly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

SUPPORTED_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}

# Suffixes appended to the original stem for the left / right photo.
LEFT_SUFFIX = "-a"
RIGHT_SUFFIX = "-b"

_DEFAULT_ASPECT = (3, 4)


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Return a moving average of *values* with an odd *window* (edges padded)."""
    if window <= 1 or values.size < window:
        return values
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=np.float64) / window
    padded = np.pad(values, window // 2, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def detect_seam_x(
    gray: np.ndarray, search_frac: float = 0.30, center_bias: float = 0.0
) -> int:
    """Find the x column of the gap between the two half-frames.

    Args:
        gray: ``H×W`` grayscale image array.
        search_frac: Fraction of the width, centered on the middle, to search
            within (e.g. ``0.30`` searches the central 30%). Clamped to ``(0, 1]``.
        center_bias: Strength of a pull toward the exact middle, as a multiple of
            the score's own scale. ``0`` disables it; small values (e.g. ``0.5``)
            help on busy frames where an off-center uniform region could otherwise
            win.

    Returns:
        The absolute column index of the detected seam. Falls back to ``W // 2``
        when the image is too narrow to search.
    """
    h, w = gray.shape[:2]
    if w < 4:
        return w // 2

    search_frac = min(max(search_frac, 1e-3), 1.0)
    half = (w * search_frac) / 2.0
    mid = w / 2.0
    lo = max(0, int(round(mid - half)))
    hi = min(w, int(round(mid + half)))
    if hi - lo < 1:
        return w // 2

    # Per-column vertical variance: low in the uniform gap, high in textured frames.
    scores = gray.astype(np.float64).var(axis=0)
    scores = _smooth(scores, max(3, int(w * 0.01)))

    window = scores[lo:hi]
    if center_bias > 0:
        scale = float(window.max() - window.min()) or 1.0
        cols = np.arange(lo, hi, dtype=np.float64)
        window = window + center_bias * scale * (np.abs(cols - mid) / max(half, 1.0))

    return lo + int(np.argmin(window))


def _aspect_crop_box(
    w: int, h: int, aspect: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    """Return the center-crop box ``(left, top, right, bottom)`` for ``w×h`` → *aspect*.

    Returns ``None`` when ``w×h`` already matches the target ratio. Shared by the
    Pillow and NumPy crop paths so both compute identical geometry.
    """
    aw, ah = aspect
    target = aw / ah
    current = w / h

    if abs(current - target) < 1e-6:
        return None
    if current > target:
        # Too wide — trim left/right.
        new_w = round(h * target)
        left = (w - new_w) // 2
        return (left, 0, left + new_w, h)
    # Too tall — trim top/bottom.
    new_h = round(w / target)
    top = (h - new_h) // 2
    return (0, top, w, top + new_h)


def _split_boxes(
    w: int, h: int, seam_x: int, gap: int, aspect: tuple[int, int]
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Return absolute, aspect-applied crop boxes for the left and right halves."""
    left_edge = max(0, min(seam_x - gap, w))
    right_edge = max(0, min(seam_x + gap, w))
    return (
        _aspect_within(0, 0, left_edge, h, aspect),
        _aspect_within(right_edge, 0, w, h, aspect),
    )


def _aspect_within(
    left: int, top: int, right: int, bottom: int, aspect: tuple[int, int]
) -> tuple[int, int, int, int]:
    """Aspect-crop the region ``(left..right, top..bottom)``, in absolute coords."""
    box = _aspect_crop_box(right - left, bottom - top, aspect)
    if box is None:
        return (left, top, right, bottom)
    bl, bt, br, bb = box
    return (left + bl, top + bt, left + br, top + bb)


def crop_to_aspect(img: Image.Image, aspect: tuple[int, int] = _DEFAULT_ASPECT) -> Image.Image:
    """Center-crop *img* to ``aspect`` (width:height).

    Args:
        img: Source image.
        aspect: Target ``(width, height)`` ratio, e.g. ``(3, 4)`` for portrait.

    Returns:
        The center-cropped image. Returns *img* unchanged if it already matches.
    """
    box = _aspect_crop_box(*img.size, aspect)
    return img if box is None else img.crop(box)


def split_image(
    img: Image.Image,
    seam_x: int,
    *,
    gap: int = 0,
    aspect: tuple[int, int] = _DEFAULT_ASPECT,
) -> tuple[Image.Image, Image.Image]:
    """Split *img* at *seam_x* and crop each side to *aspect*.

    Args:
        img: The full half-frame scan.
        seam_x: Column to split at.
        gap: Pixels to drop on each side of the seam (removes leftover gap band).
        aspect: Target ``(width, height)`` ratio for each photo.

    Returns:
        ``(left, right)`` cropped images.
    """
    left_box, right_box = _split_boxes(*img.size, seam_x, gap, aspect)
    return img.crop(left_box), img.crop(right_box)


def _save_like(src_img: Image.Image, out_img: Image.Image, dst: Path) -> None:
    """Save *out_img* to *dst*, carrying EXIF/ICC from *src_img* where present."""
    save_kwargs: dict = {}
    if exif := src_img.info.get("exif"):
        save_kwargs["exif"] = exif
    if icc := src_img.info.get("icc_profile"):
        save_kwargs["icc_profile"] = icc
    if dst.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs.setdefault("quality", 95)
    out_img.save(dst, **save_kwargs)


# Tag 34675 (ICC profile), TIFF type 7 (UNDEFINED) — see TIFF/EP & ICC.1.
_ICC_TAG = 34675
_ICC_TYPE = 7


def _luma(arr: np.ndarray) -> np.ndarray:
    """Return a 2-D luminance image for seam detection from a 2-D or 3-D array."""
    if arr.ndim == 2:
        return arr
    # ITU-R 601-2 luma, matching Pillow's RGB→L conversion. Alpha is ignored.
    return arr[..., :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])


def _crop_array(arr: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Crop *arr* to ``(left, top, right, bottom)``, returned C-contiguous."""
    left, top, right, bottom = box
    return np.ascontiguousarray(arr[top:bottom, left:right])


def _write_tiff_array(dst: Path, arr: np.ndarray, icc: bytes | None) -> None:
    """Write *arr* to *dst* as a TIFF, preserving dtype and ICC profile."""
    photometric = "rgb" if arr.ndim == 3 and arr.shape[2] >= 3 else "minisblack"
    extratags = []
    if icc:
        extratags.append((_ICC_TAG, _ICC_TYPE, len(icc), icc, True))
    tifffile.imwrite(dst, arr, photometric=photometric, extratags=extratags)


def _split_high_bit_tiff(
    page: tifffile.TiffPage,
    src: Path,
    out_dir: Path,
    *,
    mode: str,
    search_frac: float,
    gap: int,
    aspect: tuple[int, int],
) -> tuple[Path, Path]:
    """Split a >8-bit multi-channel TIFF *page* via NumPy, preserving bit depth."""
    arr = page.asarray()
    icc_tag = page.tags.get("InterColorProfile")
    icc = icc_tag.value if icc_tag is not None else None

    h, w = arr.shape[:2]
    if mode == "center":
        seam_x = w // 2
    else:
        seam_x = detect_seam_x(_luma(arr), search_frac=search_frac)

    left_box, right_box = _split_boxes(w, h, seam_x, gap, aspect)
    left_path = out_dir / f"{src.stem}{LEFT_SUFFIX}{src.suffix}"
    right_path = out_dir / f"{src.stem}{RIGHT_SUFFIX}{src.suffix}"
    _write_tiff_array(left_path, _crop_array(arr, left_box), icc)
    _write_tiff_array(right_path, _crop_array(arr, right_box), icc)
    return left_path, right_path


def process_file(
    src: Path,
    out_dir: Path,
    *,
    mode: str = "auto",
    search_frac: float = 0.30,
    gap: int = 0,
    aspect: tuple[int, int] = _DEFAULT_ASPECT,
) -> tuple[Path, Path]:
    """Split one scan into its ``-a`` (left) and ``-b`` (right) photos.

    Args:
        src: Source scan path.
        out_dir: Directory to write the two outputs into (created if needed).
        mode: ``"auto"`` to detect the seam, ``"center"`` to split at ``W // 2``.
        search_frac: Central search window for ``"auto"`` detection.
        gap: Pixels to drop on each side of the seam.
        aspect: Target ``(width, height)`` ratio for each photo.

    Returns:
        ``(left_path, right_path)`` of the written files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pillow truncates >8-bit colour TIFFs to 8 bits on open, so route those
    # through tifffile/NumPy instead. 16-bit grayscale (Pillow ``I;16``) and all
    # 8-bit formats round-trip losslessly on the Pillow path below.
    if src.suffix.lower() in {".tif", ".tiff"}:
        with tifffile.TiffFile(src) as tf:
            page = tf.pages[0]
            dtype = page.dtype
            if dtype is not None and dtype.itemsize > 1 and page.samplesperpixel > 1:
                return _split_high_bit_tiff(
                    page,
                    src,
                    out_dir,
                    mode=mode,
                    search_frac=search_frac,
                    gap=gap,
                    aspect=aspect,
                )

    with Image.open(src) as img:
        img.load()
        # Split pixels as-is; scans are typically un-rotated and we want the
        # geometry to match exactly what the user sees in the scan.
        w = img.size[0]
        if mode == "center":
            seam_x = w // 2
        else:
            gray = np.asarray(img.convert("L"))
            seam_x = detect_seam_x(gray, search_frac=search_frac)

        left_img, right_img = split_image(img, seam_x, gap=gap, aspect=aspect)

        left_path = out_dir / f"{src.stem}{LEFT_SUFFIX}{src.suffix}"
        right_path = out_dir / f"{src.stem}{RIGHT_SUFFIX}{src.suffix}"
        _save_like(img, left_img, left_path)
        _save_like(img, right_img, right_path)

    return left_path, right_path
