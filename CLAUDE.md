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
    │   ├── metadata.py        # EXIF + QuickTime atom + hachoir video metadata extraction
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
            ├── filter_panel.py
            └── file_table.py      # Scan-results table (model/view) + selection
```

### Key Data Flow

1. **Scan Tab** → `scanner.py` walks the source directory, calling `metadata.py` per file → produces `ScanResult` (list of `PhotoFile` objects).
2. **Move Tab** → the scan result is shown in the `file_table.py` results table (one row per file: name, date, camera, live output-path preview, plus a selection checkbox). The user picks output dir + template + collision mode → `mover.py` resolves `PhotoFile.resolved_dest` via `template.py`, then copies/moves the **checked, filter-visible** files.
3. Files without a usable date go to `<output_dir>/_unknown/<original_relative_subpath>/`.

### Scan-Results Table (`file_table.py`)

Built on Qt's model/view framework (not item widgets) to stay responsive with
thousands of files — only visible rows are painted.

- `FileTableModel` — wraps `list[PhotoFile]` + a parallel `list[bool]` checked
  state. Columns: Name (with checkbox), Date, Camera, Output Path. The Output
  Path column is computed on demand via a resolver callback set by `MoveTab`
  (`mover.resolve_dest`, collision-free); after a move it reflects each file's
  actual `resolved_dest`.
- `FileFilterProxyModel` — hides rows by extension/camera using the sets from
  `FilterPanel`; leaves the underlying list untouched.
- `FileTableView` — table + Select All/None (over visible rows) + a live count
  label. `checked_visible_files()` returns what a move acts on.

`MoveTab` no longer has a per-file log `QTextEdit`; move outcomes are summarised
in the status line and the table's Output Path column.

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
finished = Signal(object)     # ScanResult or MoveResult
error = Signal(str)
```

All UI updates happen on the main thread via signal connections.

### Template System

Directory templates use tokens like `{year}`, `{month}`, `{day}`, `{camera}`, `{camera_make}`, `{camera_model}`, `{month_name}`, `{ext}`. Unknown tokens are flagged as errors. Validation runs live in the UI.

### Metadata Priority

- **Photo date**: `DateTimeOriginal` → `DateTime` → `DateTimeDigitized` → missing
- **Video date**: `com.apple.quicktime.creationdate` (true capture time, from
  `moov/meta`) → hachoir container creation date (`mvhd`) → missing
- **Camera (photo)**: EXIF Make + Model → `None`
- **Camera (video)**: QuickTime `moov/meta` `com.apple.quicktime.make`/`.model`
  → `udta` `©mak`/`©mod` → Fujifilm `udta` `©inf` ("`<make> DIGITAL CAMERA <model>`",
  split into make/model) → `None`
- Missing date falls back to file mtime (with `has_metadata=False`); missing
  camera renders as `"unknown_camera"` in templates.

### QuickTime / MOV Metadata (`metadata.py`)

`.mov`/`.mp4`/`.m4v`/`.3gp` are parsed directly via a small streaming atom
reader (`_iter_atoms`/`_find_atom`) that only reads atom headers and seeks past
media payloads, so it stays cheap on multi-GB files. It walks
`moov → {meta, udta}`:
- `meta` (Apple keys/ilst table; handles the MP4 FullBox vs QuickTime
  no-version/flags split) → make, model, and precise creation date.
- `udta` `©`-prefixed text atoms → make/model, including the Fujifilm `©inf`
  combined-description split.

hachoir still supplies the date for non-QuickTime containers (avi/mkv/wmv/mts)
and as the fallback when no `creationdate` key is present.

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
| 4 | `app/core/scanner.py` | Done |
| 5 | `app/core/mover.py` | Done |
| 6 | `app/gui/widgets/` | Done |
| 7 | `app/gui/scan_tab.py`, `app/gui/move_tab.py` | Done |
| 8 | `app/gui/main_window.py` | Done |
| 9 | `main.py` | Done |