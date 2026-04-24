# Filmfiche — Photo Organizer

A PySide6 desktop app that scans a folder for photos and videos, extracts
metadata, and copies or moves files to a structured output directory.

---

## Python & Dependency Recommendations

### Required packages (`requirements.txt`)

| Package | Purpose |
|---|---|
| `PySide6` | GUI framework |
| `exifread` | EXIF extraction for JPEG, TIFF, and most RAW formats |
| `Pillow` | Thumbnail generation; fallback metadata for common formats |
| `pillow-heif` | HEIC/HEIF read support (registers as a Pillow plugin) |
| `hachoir` | Pure-Python video metadata extraction (MP4, MOV, MKV, etc.) |

---

## Supported File Types

| Category | Extensions |
|---|---|
| JPEG | `.jpg` `.jpeg` |
| PNG / GIF / BMP / WebP | `.png` `.gif` `.bmp` `.webp` |
| TIFF | `.tif` `.tiff` |
| HEIC/HEIF | `.heic` `.heif` |
| RAW | `.cr2` `.cr3` `.nef` `.arw` `.dng` `.orf` `.rw2` `.raf` `.pef` `.srw` |
| Video | `.mp4` `.mov` `.avi` `.mkv` `.wmv` `.m4v` `.3gp` `.mts` `.m2ts` |

---

## Directory Template System

### Variables

| Token | Example value | Source |
|---|---|---|
| `{year}` | `2024` | EXIF DateTimeOriginal |
| `{month}` | `03` | zero-padded |
| `{month_name}` | `March` | locale month name |
| `{day}` | `07` | zero-padded |
| `{camera}` | `Canon_EOS_R5` | Make + Model, spaces → underscores |
| `{camera_make}` | `Canon` | EXIF Make |
| `{camera_model}` | `EOS_R5` | EXIF Model |
| `{ext}` | `jpg` | lowercase original extension |

### Built-in Presets

- `{year}/{month}/{day}`
- `{year}/{month}`
- `{camera}/{year}/{month}`
- `{camera}/{year}-{month}`
- `{year}/{month_name}`

### Validation Rules (shown live in UI)

1. All `{tokens}` must be from the known variable list — unknown tokens are flagged.
2. A preview line is rendered using sample data: `2024/03/07/IMG_0001.jpg`.
3. Warning if the template contains no date or camera component — high collision risk.
4. Error if the template is empty or resolves to the root of the output directory.

---

## Metadata Extraction Strategy

Priority order for date:

1. EXIF `DateTimeOriginal`
2. EXIF `DateTime`
3. EXIF `DateTimeDigitized`
4. Video container creation date (via hachoir)
5. **→ Missing metadata path** (see below)

Priority order for camera:

1. EXIF `Make` + `Model`
2. Video container device metadata
3. `"unknown_camera"` literal (used in template rendering)

If **any date field is unavailable**, the file is routed to the missing-metadata path
regardless of camera resolution.

---

## Missing Metadata Handling

Files that cannot produce a valid resolved path (no usable date) are copied/moved to:

```
<output_dir>/_unknown/<original_relative_subpath>/<filename>
```

This preserves sub-folder structure so files remain traceable. The `_unknown` folder
is reported separately in the results summary.

---

## Collision Handling

Three user-selectable modes apply to the final resolved destination path:

| Mode | Behaviour |
|---|---|
| **Skip** | Leave the destination file untouched; log as skipped. |
| **Copy with Suffix** | Append `_1`, `_2`, … until the name is free: `IMG_001_1.jpg`. |
| **Override** | Overwrite the destination file unconditionally. |

---

## Application Architecture

```
filmfiche/
├── main.py                    # Entry point — boots QApplication
├── requirements.txt
├── PLAN.md
└── app/
    ├── __init__.py
    ├── models/
    │   ├── photo_file.py      # PhotoFile dataclass (path, metadata, resolved dest)
    │   └── scan_result.py     # ScanResult (file list, extension map, camera map)
    ├── core/
    │   ├── metadata.py        # EXIF + video metadata extraction
    │   ├── template.py        # Template parsing, token substitution, validation
    │   ├── scanner.py         # Recursive directory walk → list[PhotoFile]
    │   └── mover.py           # Copy/move execution, collision handling
    └── gui/
        ├── main_window.py     # QMainWindow, tab widget, menu bar
        ├── scan_tab.py        # Step 1 UI
        ├── move_tab.py        # Step 2 UI
        └── widgets/
            ├── dir_picker.py      # Reusable directory selector widget
            ├── template_editor.py # Template input + live preview + validator
            └── filter_panel.py    # Extension / camera model checkbox list
```

### Key Data Model

```python
# app/models/photo_file.py
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

---

## Two-Step Workflow

### Step 1 — Scan Tab

1. **Source directory** picker (with recursive toggle, default: on).
2. **Scan** button → runs `scanner.py` in a `QThread`; progress shown via status bar.
3. Results panel:
   - Total files discovered.
   - **Extension filter**: checkbox list — each extension with count, all enabled by default.
   - **Camera model filter**: checkbox list — each detected camera with count, all enabled by default.
   - Selecting/deselecting updates "Files to process: X" live.
4. **Proceed to Copy/Move** button (enabled once scan completes).

Scan runs entirely in memory. No files are touched during this step.

### Step 2 — Move/Copy Tab

1. **Output directory** picker.
2. **Template editor** (`template_editor.py`):
   - Text field with preset dropdown.
   - Live preview using first discovered file's metadata as sample.
   - Inline validation messages.
3. **Operation mode**: radio — Copy / Move.
4. **Collision handling**: dropdown — Skip / Copy with Suffix / Override.
5. **Execute** button → runs `mover.py` in a `QThread`.
6. Progress bar (per-file) + scrollable log view.
7. On completion — summary dialog:
   - Copied/moved: N
   - Skipped (collision): N
   - Routed to `_unknown`: N
   - Errors: N (with expandable list)

---

## Threading Model

Both the scan and move operations run in a `QThread` subclass that emits Qt signals:

```python
progress = Signal(int, int)   # current, total
file_done = Signal(str)       # log message per file
finished = Signal(object)     # ScanResult or MoveResult
error = Signal(str)           # fatal error message
```

The GUI connects to these signals; all UI updates happen on the main thread.

---

## Implementation Order

1. `app/models/` — dataclasses only, no dependencies.
2. `app/core/metadata.py` — EXIF + video extraction, tested against sample files.
3. `app/core/template.py` — parsing, validation, substitution, unit-tested.
4. `app/core/scanner.py` — directory walk using metadata module.
5. `app/core/mover.py` — copy/move with collision and unknown-folder logic.
6. `app/gui/widgets/` — reusable widgets (dir picker, template editor, filter panel).
7. `app/gui/scan_tab.py` + `move_tab.py` — wire widgets to core via QThread workers.
8. `app/gui/main_window.py` — assemble tabs, add menu bar (File > Quit, Help > About).
9. `main.py` — launch, apply stylesheet, show window.

---

## Out of Scope (v1)

- Resume / recovery from a partial move (noted as v2 feature).
- Saving scan results to disk.
- Undo of move operations.
- Writing/modifying EXIF data on output files.
- Cloud or network destinations.
