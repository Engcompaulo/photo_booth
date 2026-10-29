"""Upload validation for the Dia de los Muertos Photo Booth.

This module decodes and validates an uploaded photo entirely in memory. It
never writes bytes to disk, honoring the privacy requirement (Req 8.2): the raw
upload is read into a ``BytesIO`` buffer, decoded with Pillow, and returned as a
``LoadedImage`` that holds the decoded pixels in memory only.

Validation enforces, in order:

* the 10,485,760-byte (10 MB) hard size limit (Req 1.5, 2.2);
* the accepted raster formats, JPEG and PNG only (Req 1.2, 1.4);
* that the bytes actually decode into a valid image (Req 1.7, 2.1, 2.3);
* that the decoded image has non-zero width and height (Req 2.4).

On any failure the module raises :class:`ValidationError` carrying the exact
English, user-facing message from the design's Error Handling table. All code,
comments and identifiers are written in English (Req 10.7).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

# Hard upload size limit: 10 MB expressed in bytes (Req 1.5, 2.2).
MAX_UPLOAD_BYTES = 10_485_760

# Raster formats the service accepts (Req 1.2). Pillow reports formats in this
# uppercase spelling, so comparisons are done against these canonical names.
ACCEPTED_FORMATS = ("JPEG", "PNG")

# Supported per-side pixel range for a photo that detection can process
# (Req 3.1): width and height must each fall within these inclusive bounds.
MIN_DIMENSION_PX = 64
MAX_DIMENSION_PX = 8000

# Exact, user-facing English messages from the design Error Handling table.
UNSUPPORTED_FORMAT_MESSAGE = "Only JPEG and PNG images are accepted."
FILE_TOO_LARGE_MESSAGE = (
    "The file exceeds the maximum allowed size of 10 MB (10,485,760 bytes)."
)
CORRUPTED_IMAGE_MESSAGE = (
    "This image file is corrupted or cannot be read. Please try another image."
)
INVALID_DIMENSIONS_MESSAGE = "The image dimensions are invalid."


@dataclass
class LoadedImage:
    """A validated, decoded image held entirely in memory (never on disk)."""

    pixels: Image.Image  # Pillow image object
    width: int
    height: int
    image_format: str  # "JPEG" or "PNG" (matches the input, Req 7.3)


class ValidationError(Exception):
    """Raised when an upload fails validation; carries a user-facing message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _normalize_format(image_format: str | None) -> str | None:
    """Map a Pillow/declared format string to its canonical accepted name.

    Returns the matching entry from :data:`ACCEPTED_FORMATS` (``"JPEG"`` or
    ``"PNG"``) or ``None`` when the format is absent or not accepted. ``"JPG"``
    is treated as an alias for ``"JPEG"``.
    """

    if not image_format:
        return None

    normalized = image_format.strip().upper()
    if normalized == "JPG":
        normalized = "JPEG"
    if normalized in ACCEPTED_FORMATS:
        return normalized
    return None


def validate_upload(raw_bytes: bytes, declared_format: str | None) -> LoadedImage:
    """Validate size, format, decodability, and dimensions of an upload.

    Enforces the 10,485,760-byte limit (Req 1.5, 2.2), accepts only JPEG/PNG
    (Req 1.2, 1.4), verifies the bytes decode into a valid image (Req 1.7, 2.1,
    2.3), and rejects zero-width or zero-height images (Req 2.4). Raises
    :class:`ValidationError` with the matching English message on failure. Never
    writes the bytes to disk.

    The ``declared_format`` argument is an optional hint (for example from a
    client-provided MIME type or filename); the authoritative format is always
    the one Pillow reports after decoding the bytes.
    """

    # 1. Size limit first: reject oversized payloads before any decoding work
    #    so a very large upload cannot be decoded into memory (Req 1.5, 2.2).
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationError(FILE_TOO_LARGE_MESSAGE)

    # 2. Decode the bytes from an in-memory buffer. Any decoding problem means
    #    the content is corrupted or not a readable image (Req 1.7, 2.1, 2.3).
    buffer = io.BytesIO(raw_bytes)
    try:
        pixels = Image.open(buffer)
        # ``Image.open`` is lazy; force a load so truncated or malformed data is
        # surfaced here rather than later during processing.
        pixels.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(CORRUPTED_IMAGE_MESSAGE) from exc

    # 3. Format check: the format Pillow identified is authoritative. Only
    #    JPEG and PNG are accepted (Req 1.2, 1.4).
    detected_format = _normalize_format(pixels.format)
    if detected_format is None:
        raise ValidationError(UNSUPPORTED_FORMAT_MESSAGE)

    # 4. Dimension check: a valid image must have non-zero width and height
    #    (Req 2.4).
    width, height = pixels.size
    if width <= 0 or height <= 0:
        raise ValidationError(INVALID_DIMENSIONS_MESSAGE)

    return LoadedImage(
        pixels=pixels,
        width=width,
        height=height,
        image_format=detected_format,
    )


def is_supported_dimensions(width: int, height: int) -> bool:
    """Return True when width and height are each between 64 and 8000 px (Req 3.1).

    The bounds are inclusive on both ends.
    """

    return (
        MIN_DIMENSION_PX <= width <= MAX_DIMENSION_PX
        and MIN_DIMENSION_PX <= height <= MAX_DIMENSION_PX
    )
