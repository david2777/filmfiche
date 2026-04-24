import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.models.photo_file import PhotoFile

KNOWN_TOKENS = frozenset({
    "year", "month", "day", "month_name",
    "camera", "camera_make", "camera_model", "ext",
})

PRESETS = [
    "{year}/{month}/{day}",
    "{year}/{month}",
    "{camera}/{year}/{month}",
    "{camera}/{year}-{month}",
    "{year}/{month_name}",
]

_DATE_TOKENS = frozenset({"year", "month", "day", "month_name"})
_CAMERA_TOKENS = frozenset({"camera", "camera_make", "camera_model"})
_TOKEN_RE = re.compile(r"\{(\w+)\}")

_SAMPLE = {
    "year": "2024", "month": "03", "day": "07",
    "month_name": "March",
    "camera": "Canon_EOS_R5", "camera_make": "Canon", "camera_model": "EOS_R5",
    "ext": "jpg",
}


@dataclass
class ValidationResult:
    """Result of validating a directory template string.

    Attributes:
        errors: Fatal issues that prevent the template from being used.
        warnings: Non-fatal advisories (e.g. collision risk).
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """``True`` when there are no errors."""
        return len(self.errors) == 0


def _normalize(value: str | None, fallback: str = "unknown_camera") -> str:
    if not value:
        return fallback
    return value.strip().replace(" ", "_")


def _build_tokens(photo: PhotoFile) -> dict[str, str]:
    dt = photo.date_taken
    make = _normalize(photo.camera_make)
    model = _normalize(photo.camera_model)

    if photo.camera_make and photo.camera_model:
        camera = f"{make}_{model}".replace(" ", "_")
    else:
        raw = photo.camera_make or photo.camera_model or None
        camera = _normalize(raw)

    return {
        "year": dt.strftime("%Y"),
        "month": dt.strftime("%m"),
        "day": dt.strftime("%d"),
        "month_name": dt.strftime("%B"),
        "camera_make": make,
        "camera_model": model,
        "camera": camera,
        "ext": photo.extension,
    }


def validate_template(template: str) -> ValidationResult:
    """Validate a directory template string against known tokens.

    Args:
        template: A template string such as ``"{year}/{month}/{day}"``.

    Returns:
        A ``ValidationResult`` with any errors and warnings.
    """
    if not template:
        return ValidationResult(errors=["Template must not be empty"])

    tokens = _TOKEN_RE.findall(template)
    errors = [f"Unknown token: {{{name}}}" for name in tokens if name not in KNOWN_TOKENS]

    warnings = []
    if not (set(tokens) & (_DATE_TOKENS | _CAMERA_TOKENS)):
        warnings.append("Template has no date or camera tokens — high risk of filename collisions")

    return ValidationResult(errors=errors, warnings=warnings)


def render_preview(template: str) -> str:
    """Render a template with sample values for UI preview.

    Args:
        template: A directory template string.

    Returns:
        The substituted string, or ``""`` if an unknown token is present.
    """
    try:
        return template.format_map(_SAMPLE)
    except KeyError:
        return ""


def resolve_path(template: str, photo: PhotoFile) -> Path | None:
    """Resolve a template to a relative output path for a given photo.

    Args:
        template: A directory template string.
        photo: The ``PhotoFile`` whose metadata supplies token values.

    Returns:
        A relative ``Path`` with tokens substituted, or ``None`` when
        ``photo.date_taken`` is ``None`` (file will go to ``_unknown/``).
    """
    if photo.date_taken is None:
        return None
    tokens = _build_tokens(photo)
    return Path(template.format_map(tokens))
