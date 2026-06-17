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
    │   ├── scan_result.py     # ScanResult (file list, extension map, camera map)
    │   └── film_frame.py      # FilmFrame + global/per-item key split (tagger)
    ├── core/
    │   ├── metadata.py        # EXIF + QuickTime atom + hachoir video metadata extraction
    │   ├── template.py        # Template parsing, token substitution, validation
    │   ├── scanner.py         # Directory walk → list[PhotoFile]
    │   ├── mover.py           # Copy/move execution, collision handling
    │   └── tagger.py          # build_exif + write_image + output_path (film tagger)
    └── gui/
        ├── main_window.py     # QMainWindow, tab widget, menu bar (Tools → Tagger)
        ├── scan_tab.py        # Step 1 UI
        ├── move_tab.py        # Step 2 UI
        ├── tagger_dialog.py   # Film Metadata Tagger window + Thumbnail/Export workers
        └── widgets/
            ├── dir_picker.py
            ├── template_editor.py
            ├── filter_panel.py
            ├── file_table.py      # Scan-results table (model/view) + selection
            ├── drop_area.py       # Drag-drop / browse target (tagger)
            └── frame_table.py     # Editable per-frame metadata grid w/ thumbnails (tagger)
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

### Film Metadata Tagger (`tagger_dialog.py`, `tagger.py`, `film_frame.py`)

A standalone `QDialog` launched from **Tools → Film Metadata Tagger…** (held on
`MainWindow._tagger_dialog`, reused/re-focused on reopen). It ports the standalone
`analog_import` CLI into the app: tag scanned film frames and export renamed copies.

Workflow: drag/drop or browse a folder/images (`DropArea`; `collect_image_paths`
expands folders non-recursively and sorts the combined result by filename
ascending) → frames appear in `FrameTable` with thumbnails, auto-numbered 1..N in
that order → set camera make/model + reel/document/film/ISO globally, edit
lens/exposure/etc per frame, **or** Import JSON → **Export…** to a chosen root.

- **Reverse Order button**: `FrameTable.reverse_order()` flips the frame sequence
  and renumbers 1..N (last file becomes #1). For when the scan direction is the
  opposite of the metadata order — reverse, then import/enter metadata so it pairs
  correctly. Thumbnails are cached by frame identity (`id(frame)`), so they follow
  their frames on reorder and a still-loading thumbnail can't land on the wrong
  row.

- **Metadata model**: each frame's per-item values are a plain dict keyed exactly
  like the Lightme/Logbook JSON schema, so `build_exif` is reused unchanged and
  JSON import/round-trip needs no translation. `GLOBAL_KEYS` (Make, Model,
  ReelName, DocumentName, SpectralSensitivity, Description, ISO/ISOSpeed,
  SensitivityType, FileSource, Software) are merged into every frame at export by
  `build_full_entry`; `PER_ITEM_KEYS` (ImageNumber, DateTimeOriginal, Lens*,
  FNumber, ExposureTime, FocalLength*, GPS*, Notes, ImageUniqueID) live on the
  frame. `ImageUniqueID` defaults to `"{ReelName}_{ImageNumber}"`.
- **JSON pairing**: `frames_from_json` pairs the i-th entry with the i-th frame
  (same ordering as `analog_import`) but warns on a count mismatch instead of
  erroring — it maps `min(entries, frames)`.
- **Normalisation**: `normalize_entry` strips/drops blank values and parses
  fractional shutter strings (e.g. `"1/125"`) before `build_exif`.
- **Output naming**: `output_path` → `{root}/{reel}-{sanitize(document)}/`
  `{reel}-{number:04d}{ext}` (spaces → underscores). JPEG bytes are copied
  verbatim + EXIF spliced (`piexif.insert`); TIFF is round-tripped via Pillow
  preserving compression.
- **Threading**: `ThumbnailWorker` (Pillow → `QImage` off the GUI thread, emits
  `(row, QImage)`) and `ExportWorker` (`progress`/`finished(count)`/`error`),
  following the same `QThread` + Signal pattern as scan/move. Note `FrameTable`
  uses a plain editable `QTableWidget` (a roll is only tens of frames), unlike the
  model/view `file_table.py`.
- `piexif` is a runtime dependency (was previously dev-only).

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
| 10 | Film Metadata Tagger: `app/core/tagger.py`, `app/models/film_frame.py`, `app/gui/tagger_dialog.py`, `app/gui/widgets/{drop_area,frame_table}.py` | Done |