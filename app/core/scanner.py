from collections.abc import Callable
from pathlib import Path

from app.core.metadata import SUPPORTED_EXTENSIONS, extract_metadata
from app.models.scan_result import ScanResult


def _camera_key(make: str | None, model: str | None) -> str:
    """Build a display key for camera_counts from raw make/model strings.

    Args:
        make: Camera manufacturer string, or ``None``.
        model: Camera model string, or ``None``.

    Returns:
        A combined "Make Model" string, or ``"unknown_camera"`` if both are absent.
    """
    parts = " ".join(filter(None, [make, model])).strip()
    return parts if parts else "unknown_camera"


def scan_directory(
    source: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Walk source recursively and extract metadata from every supported file.

    Args:
        source: Root directory to scan.
        progress_callback: Optional callable invoked as (current, total) after
            each file is processed. Designed for QThread signal emission.

    Returns:
        ScanResult populated with all PhotoFile objects, extension_counts,
        and camera_counts.
    """
    paths = [
        p
        for p in source.rglob("*")
        if p.is_file() and p.suffix.lstrip(".").lower() in SUPPORTED_EXTENSIONS
    ]
    total = len(paths)
    result = ScanResult()

    for i, path in enumerate(paths, 1):
        photo = extract_metadata(path)
        result.files.append(photo)
        result.extension_counts[photo.extension] = (
            result.extension_counts.get(photo.extension, 0) + 1
        )
        key = _camera_key(photo.camera_make, photo.camera_model)
        result.camera_counts[key] = result.camera_counts.get(key, 0) + 1
        if progress_callback is not None:
            progress_callback(i, total)

    return result
