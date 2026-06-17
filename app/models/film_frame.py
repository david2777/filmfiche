"""Per-frame film metadata model and the global/per-item key split.

A :class:`FilmFrame` is one scanned image plus a dict of *per-item* EXIF values
keyed exactly like the Lightme/Logbook JSON schema. Reel-wide values (camera
make/model, film stock, ISO) live separately as a *globals* dict and are merged
into every frame at export time via :func:`build_full_entry`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.tagger import normalize_entry

# Entered once for the whole reel and merged into every frame at export.
GLOBAL_KEYS = (
    "Make",
    "Model",
    "ReelName",
    "DocumentName",
    "SpectralSensitivity",
    "Description",
    "ISO",
    "ISOSpeed",
    "SensitivityType",
    "FileSource",
    "Software",
)

# Edited per frame in the table.
PER_ITEM_KEYS = (
    "ImageNumber",
    "DateTimeOriginal",
    "LensMake",
    "LensModel",
    "FNumber",
    "MaxApertureValue",
    "ExposureTime",
    "FocalLength",
    "FocalLengthIn35mmFormat",
    "GPSLatitude",
    "GPSLatitudeRef",
    "GPSLongitude",
    "GPSLongitudeRef",
    "Notes",
    "ImageUniqueID",
)

# Sensible reel-level defaults matching the analog_import / Logbook output.
_DEFAULT_GLOBALS: dict[str, Any] = {
    "SensitivityType": 3,   # REI (recommended exposure index)
    "FileSource": 1,        # film scanner
    "Software": "Filmfiche",
}


def _is_set(value: Any) -> bool:
    return value is not None and value != ""


@dataclass
class FilmFrame:
    """A single scanned frame and its per-item metadata.

    Attributes:
        source_path: Path to the source image (``.jpg``/``.jpeg``/``.tif``/``.tiff``).
        entry: Per-item EXIF values keyed by :data:`PER_ITEM_KEYS`.
    """

    source_path: Path
    entry: dict[str, Any] = field(default_factory=dict)


def build_full_entry(frame: FilmFrame, globals_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge reel globals with a frame's per-item values into one EXIF entry.

    Reel defaults are applied first, then the supplied *globals_dict*, then the
    frame's own values (which win on conflict). ``ImageUniqueID`` defaults to
    ``"{ReelName}_{ImageNumber}"`` when not already present.

    Args:
        frame: The frame whose per-item values to use.
        globals_dict: Reel-wide values (camera, film, ISO, …).

    Returns:
        A cleaned dict ready for :func:`~app.core.tagger.build_exif`.
    """
    merged: dict[str, Any] = dict(_DEFAULT_GLOBALS)
    merged.update({k: v for k, v in globals_dict.items() if _is_set(v)})
    merged.update({k: v for k, v in frame.entry.items() if _is_set(v)})

    reel = merged.get("ReelName")
    number = merged.get("ImageNumber")
    if reel and number is not None and "ImageUniqueID" not in merged:
        merged["ImageUniqueID"] = f"{reel}_{number}"

    return normalize_entry(merged)


def frames_from_json(
    entries: list[dict[str, Any]], frames: list[FilmFrame]
) -> tuple[dict[str, Any], list[FilmFrame], str | None]:
    """Apply a list of JSON metadata *entries* onto loaded *frames* by order.

    Pairs the i-th entry with the i-th frame (the same ordering rule as
    ``analog_import``). Unlike the CLI this does not hard-error on a count
    mismatch — it maps as many as it can and returns a warning string instead.

    Args:
        entries: Parsed JSON list (one dict per frame, in order).
        frames: The frames currently loaded in the UI.

    Returns:
        ``(globals_dict, frames, warning)`` where *globals_dict* holds the
        reel-wide keys read from the first entry, *frames* is the same list with
        each ``entry`` updated in place, and *warning* is ``None`` or a message
        describing a count mismatch.

    Raises:
        ValueError: If *entries* is not a list.
    """
    if not isinstance(entries, list):
        raise ValueError("metadata JSON must be a list of entries")

    warning: str | None = None
    count = min(len(entries), len(frames))
    if len(entries) != len(frames):
        warning = (
            f"JSON has {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
            f"but {len(frames)} image(s) are loaded; matched the first {count} "
            f"by order."
        )

    globals_dict: dict[str, Any] = {}
    if entries:
        first = entries[0]
        globals_dict = {k: first[k] for k in GLOBAL_KEYS if _is_set(first.get(k))}

    for i in range(count):
        src = entries[i]
        new_entry = {k: src[k] for k in PER_ITEM_KEYS if _is_set(src.get(k))}
        # Preserve a previously auto-assigned frame number if the JSON omits one.
        new_entry.setdefault("ImageNumber", frames[i].entry.get("ImageNumber", i + 1))
        frames[i].entry = new_entry

    return globals_dict, frames, warning
