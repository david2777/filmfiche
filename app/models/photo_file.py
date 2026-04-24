from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PhotoFile:
    source_path: Path
    extension: str          # lowercase, no dot
    date_taken: datetime | None
    camera_make: str | None
    camera_model: str | None
    resolved_dest: Path | None   # None until template is applied
    has_metadata: bool
