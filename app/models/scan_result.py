from dataclasses import dataclass, field

from app.models.photo_file import PhotoFile


@dataclass
class ScanResult:
    files: list[PhotoFile] = field(default_factory=list)
    extension_counts: dict[str, int] = field(default_factory=dict)
    camera_counts: dict[str, int] = field(default_factory=dict)
