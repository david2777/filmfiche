# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Filmfiche is a PySide6 desktop app that scans a folder for photos and videos, extracts metadata (EXIF/video container), and copies or moves files to a user-defined structured output directory.

## Setup & Commands

```bash
# Install dependencies
pip install PySide6 exifread Pillow pillow-heif hachoir piexif

# Run the app
python main.py

# Run tests
python -m pytest
python -m pytest tests/test_metadata.py -v   # single test file
```

Requires Python 3.14+.

## Development Guidelines
- **Write Tests**: Write unit tests for all core functionality.
- **Write Docstrings**: Write succinct Google style docstrings for all public functions and classes.
- **Update CLAUDE.md**: Update this file after each turn so that your memory is up to date.

## Architecture

```
filmfiche/
├── main.py                    # Entry point — boots QApplication
└── app/
    ├── models/
    │   ├── photo_file.py      # PhotoFile dataclass
    │   └── scan_result.py     # ScanResult (file list, extension map, camera map)
    ├── core/
    │   ├── metadata.py        # EXIF + hachoir video metadata extraction
    │   ├── template.py        # Template parsing, token substitution, validation
    │   ├── scanner.py         # Directory walk → list[PhotoFile]
    │   └── mover.py           # Copy/move execution, collision handling
    └── gui/
        ├── main_window.py     # QMainWindow, tab widget, menu bar
        ├── scan_tab.py        # Step 1 UI
        ├── move_tab.py        # Step 2 UI
        └── widgets/
            ├── dir_picker.py
            ├── template_editor.py
            └── filter_panel.py
```

### Key Data Flow

1. **Scan Tab** → `scanner.py` walks the source directory, calling `metadata.py` per file → produces `ScanResult` (list of `PhotoFile` objects).
2. **Move Tab** → user picks output dir + template + collision mode → `mover.py` resolves `PhotoFile.resolved_dest` via `template.py`, then copies/moves.
3. Files without a usable date go to `<output_dir>/_unknown/<original_relative_subpath>/`.

### PhotoFile Dataclass

```python
@dataclass
class PhotoFile:
    source_path: Path
    extension: str          # lowercase, no dot
    date_taken: datetime | None
    camera_make: str | None
    camera_model: str | None
    resolved_dest: Path | None   # None until template is applied
    has_metadata: bool
```

### Threading Model

Both scan and move operations run in a `QThread` subclass. Signals used:

```python
progress = Signal(int, int)   # current, total
file_done = Signal(str)       # log message per file
finished = Signal(object)     # ScanResult or MoveResult
error = Signal(str)
```

All UI updates happen on the main thread via signal connections.

### Template System

Directory templates use tokens like `{year}`, `{month}`, `{day}`, `{camera}`, `{camera_make}`, `{camera_model}`, `{month_name}`, `{ext}`. Unknown tokens are flagged as errors. Validation runs live in the UI.

### Metadata Priority

- **Date**: `DateTimeOriginal` → `DateTime` → `DateTimeDigitized` → hachoir video creation date → missing
- **Camera**: EXIF Make+Model → video container device metadata → `"unknown_camera"`

### Collision Handling Modes

- **Skip**: leave destination untouched, log as skipped
- **Copy with Suffix**: append `_1`, `_2`, … until name is free
- **Override**: overwrite unconditionally

## Implementation Status

| Task | Module | Status |
|---|---|---|
| 1 | `app/models/photo_file.py`, `app/models/scan_result.py` | Done |
| 2 | `app/core/metadata.py` | Done |
| 3 | `app/core/template.py` | Done |
| 4 | `app/core/scanner.py` | Pending |
| 5 | `app/core/mover.py` | Pending |
| 6 | `app/gui/widgets/` | Pending |
| 7 | `app/gui/scan_tab.py`, `app/gui/move_tab.py` | Pending |
| 8 | `app/gui/main_window.py` | Pending |
| 9 | `main.py` | Pending |