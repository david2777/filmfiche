# Filmfiche

A simple desktop app for organizing photos and videos by date and camera metadata. Filmfiche scans a source folder, reads EXIF and video container metadata, and copies or moves files into a structured output directory based on a user-defined template.

## Features

- Recursive scan of source directories for photos and videos
- Metadata extraction from JPEG, PNG, HEIC, RAF (Fujifilm), and MOV/MP4 files
- Camera info sourced from EXIF Make/Model or video container device metadata
- Template-based output paths using tokens
- Live template preview and validation in the UI
- Filter by file extension and camera before copying
- Copy or Move mode
- Collision handling: Skip, Add Suffix, or Overwrite
- Files without a usable date go to `_unknown/` preserving their relative subpath

## Requirements

- Python 3.14+
- Dependencies: `PySide6 exifread Pillow pillow-heif hachoir piexif`

## Setup

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
python -m pytest
```
