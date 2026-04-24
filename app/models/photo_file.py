from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PhotoFile:
    """A single photo or video file with extracted metadata.

    Attributes:
        source_path: Absolute path to the original file.
        extension: Lowercase file extension without leading dot (e.g. ``"jpg"``).
        date_taken: Capture timestamp parsed from EXIF/container, or ``None``.
        camera_make: EXIF Make field, or ``None`` if unavailable.
        camera_model: EXIF Model field, or ``None`` if unavailable.
        resolved_dest: Output path after template substitution; ``None`` until set.
        has_metadata: ``True`` when at least a date was successfully extracted.
    """

    source_path: Path
    extension: str          # lowercase, no dot
    date_taken: datetime | None
    camera_make: str | None
    camera_model: str | None
    resolved_dest: Path | None   # None until template is applied
    has_metadata: bool
