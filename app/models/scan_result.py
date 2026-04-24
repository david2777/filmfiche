from dataclasses import dataclass, field

from app.models.photo_file import PhotoFile


@dataclass
class ScanResult:
    """Aggregated output of a directory scan.

    Attributes:
        files: Ordered list of every ``PhotoFile`` found during the scan.
        extension_counts: Mapping of lowercase extension → number of files.
        camera_counts: Mapping of camera identifier → number of files.
    """

    files: list[PhotoFile] = field(default_factory=list)
    extension_counts: dict[str, int] = field(default_factory=dict)
    camera_counts: dict[str, int] = field(default_factory=dict)
