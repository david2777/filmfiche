# Filmfiche

A simple desktop app for organizing photos and videos by date and camera metadata. Filmfiche scans a source folder, reads EXIF and video container metadata, and copies or moves files into a structured output directory based on a user-defined template.

![Image](docs/screenshot.png "Image")

## Features
- Recursive scan of source directories for photos and videos
- Metadata extraction from JPEG, PNG, HEIC, RAF (Fujifilm), and MOV/MP4 files
- Camera info sourced from EXIF Make/Model or video container device metadata
- Template-based output paths using tokens
- Live template preview and validation in the UI
- Filter by file extension and camera before copying
- Copy or Move mode
- Collision handling: Skip, Add Suffix, or Overwrite
- Files without a usable date use the modified date (but warn the user on scan and copy)
- Default Make / Default Model fallbacks for files with no camera metadata

## Tested Devices / Formats
- iPhone (jpg, mov, dng)
- Fujifilm Mirrorless (jpg, mov, raf)

If you find a format that doesn't work, feel free to open an issue and provide a sample file.

## Future Goals
- Test on more devices
- Add file format conversion (e.g. HEIC to JPEG)
- Add support for more metadata (e.g. Lens, GPS, Content, etc.)
- Interactive baking of metadata into film scans (currently using a CLI tool I built for this)

## Requirements

- Python 3.14+
- Dependencies: `PySide6 exifread Pillow pillow-heif hachoir piexif`

## Setup

### Using uv (recommended)

[uv](https://docs.astral.sh/uv/) reads `pyproject.toml` and `uv.lock` to build a
virtual environment with pinned dependencies:

```bash
uv sync          # create .venv and install all dependencies (incl. test deps)
uv run main.py   # launch the app
```

### Using pip

```bash
pip install PySide6 exifread Pillow pillow-heif hachoir piexif
python main.py
```

## Template Tokens

| Token | Example |
|---|---|
| `{year}` | `2024` |
| `{month}` | `03` |
| `{day}` | `07` |
| `{month_name}` | `March` |
| `{camera}` | `FUJIFILM_X-S20` |
| `{camera_make}` | `FUJIFILM` |
| `{camera_model}` | `X-S20` |
| `{ext}` | `jpg` |

Example: `{camera_model}/{year}/{month}` → `X-S20/2024/03/`

## Running Tests

```bash
uv run pytest     # with uv
python -m pytest  # with pip
```
