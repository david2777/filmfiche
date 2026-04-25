import shutil
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from app.core.template import resolve_path
from app.models.move_result import MoveResult
from app.models.photo_file import PhotoFile


class CollisionMode(Enum):
    """Strategy for handling a file that already exists at the destination.

    Attributes:
        SKIP: Leave the existing destination file untouched and log as skipped.
        SUFFIX: Append ``_1``, ``_2``, … to the stem until a free name is found.
        OVERRIDE: Overwrite the destination unconditionally.
    """

    SKIP = "skip"
    SUFFIX = "suffix"
    OVERRIDE = "override"


def _resolve_dest(
    photo: PhotoFile,
    output_dir: Path,
    template: str,
    source: Path,
    default_make: str = "",
    default_model: str = "",
) -> Path:
    """Compute the absolute destination path for a single photo.

    Args:
        photo: The source file with extracted metadata.
        output_dir: Root destination directory.
        template: Directory template string.
        source: Original source root used to derive ``_unknown/`` sub-paths.
        default_make: Fallback camera make when the file has none.
        default_model: Fallback camera model when the file has none.

    Returns:
        Absolute destination path (not yet validated for collisions).
    """
    rel_dir = resolve_path(template, photo, default_make, default_model)
    if rel_dir is None:
        return output_dir / "_unknown" / photo.source_path.relative_to(source)
    return output_dir / rel_dir / photo.source_path.name


def _apply_collision(dest: Path, mode: CollisionMode) -> Path | None:
    """Resolve a potential collision at *dest* according to *mode*.

    Args:
        dest: Proposed destination path.
        mode: Collision handling strategy.

    Returns:
        The final destination path to write to, or ``None`` if the file
        should be skipped.
    """
    if not dest.exists():
        return dest
    if mode is CollisionMode.SKIP:
        return None
    if mode is CollisionMode.OVERRIDE:
        return dest
    # SUFFIX
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def move_files(
    files: list[PhotoFile],
    output_dir: Path,
    template: str,
    collision_mode: CollisionMode,
    source: Path,
    copy: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
    default_make: str = "",
    default_model: str = "",
) -> MoveResult:
    """Copy or move a list of PhotoFiles to an output directory.

    Args:
        files: PhotoFile objects from a prior scan.
        output_dir: Root destination directory.
        template: Directory template string (e.g. ``"{year}/{month}"``).
        collision_mode: How to handle pre-existing destination files.
        source: Original source root used to compute ``_unknown/`` relative paths.
        copy: If ``True``, copy files (preserve source). If ``False``, move them.
        progress_callback: Optional ``(current, total)`` callable for QThread signals.
        default_make: Fallback camera make for files without camera metadata.
        default_model: Fallback camera model for files without camera metadata.

    Returns:
        MoveResult with counts and per-file log messages.
    """
    total = len(files)
    result = MoveResult()
    verb = "COPY" if copy else "MOVE"

    for i, photo in enumerate(files, 1):
        name = photo.source_path.name
        try:
            raw_dest = _resolve_dest(photo, output_dir, template, source, default_make, default_model)
            dest = _apply_collision(raw_dest, collision_mode)
            if dest is None:
                result.log.append(f"SKIP {name}")
                result.skipped += 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if copy:
                    shutil.copy2(photo.source_path, dest)
                else:
                    shutil.move(str(photo.source_path), dest)
                photo.resolved_dest = dest
                mtime_tag = " [mtime]" if not photo.has_metadata else ""
                result.log.append(f"{verb} {name} → {dest}{mtime_tag}")
                if not photo.has_metadata:
                    result.mtime_used += 1
                result.moved += 1
        except Exception as e:
            result.log.append(f"ERROR {name}: {e}")
            result.errors += 1

        if progress_callback is not None:
            progress_callback(i, total)

    return result
