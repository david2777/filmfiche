"""Result of a half-frame split batch."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SplitResult:
    """Summary of a :class:`~app.gui.half_frame_dialog.SplitWorker` run.

    Attributes:
        processed: Number of source scans read.
        written: Number of output photos written (two per successful scan).
        errors: Number of scans that failed to process.
        messages: Human-readable per-file error messages.
    """

    processed: int = 0
    written: int = 0
    errors: int = 0
    messages: list[str] = field(default_factory=list)
