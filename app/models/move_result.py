from dataclasses import dataclass, field


@dataclass
class MoveResult:
    """Aggregated output of a move/copy operation.

    Attributes:
        moved: Number of files successfully copied or moved.
        skipped: Number of files skipped due to collision.
        errors: Number of files that failed due to an exception.
        log: Per-file log messages in order of processing.
    """

    moved: int = 0
    skipped: int = 0
    errors: int = 0
    mtime_used: int = 0
    log: list[str] = field(default_factory=list)
