"""Adornment catalog for the Dia de los Muertos Photo Booth.

This module loads the ``Adornment_Set`` once at startup from the PNG assets and
per-theme ``theme.json`` metadata bundled under ``static/adornments/<theme>/``
(Req 5.4). Each theme directory contains one or more transparent RGBA PNGs plus
a ``theme.json`` describing how every adornment attaches to a facial landmark
(anchor, scale factor, offset ratio, and whether it rotates with the face).

Loading is resilient: a theme whose metadata is unreadable, or whose PNG assets
are missing or fail to decode, is excluded from the returned set while every
other theme stays selectable (Req 5.5). The names of excluded themes are
returned alongside the loaded set so the caller can log them.

The module also exposes :func:`encode_result`, which encodes a composed
``Result_Image`` to bytes in a given format for streaming back to the client
(Req 7.3).

All code, comments and identifiers are written in English (Req 10.7).
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from PIL import Image, UnidentifiedImageError

if TYPE_CHECKING:
    # ``composition`` may not exist yet; importing only for type checking avoids
    # a hard runtime dependency. ``encode_result`` only needs ``result.pixels``.
    from composition import ResultImage


# Filename of the per-theme metadata descriptor inside each theme directory.
THEME_METADATA_FILENAME = "theme.json"


# Where a PNG attaches on the face.
Anchor = Literal[
    "mouth",
    "above_head",
    "behind_head",
    "full_frame",
    "eyes",
    "chin",
]

# The anchor values accepted in theme metadata, used to validate ``theme.json``.
_VALID_ANCHORS: frozenset[str] = frozenset(
    ("mouth", "above_head", "behind_head", "full_frame", "eyes", "chin")
)


@dataclass(frozen=True)
class AdornmentAsset:
    """One transparent PNG plus its placement metadata."""

    image: Image.Image  # RGBA PNG with transparent background (Req 5.3)
    anchor: Anchor  # landmark the asset attaches to
    scale_factor: float  # multiple of inter-eye distance / bbox width (Req 4.3)
    offset_ratio: tuple[float, float]  # x,y offset as a fraction of face size
    rotate_with_face: bool  # follow the eye-line angle


@dataclass(frozen=True)
class AdornmentTheme:
    """A named, coherent set of one or more adornments (e.g. 'calavera')."""

    name: str
    assets: tuple[AdornmentAsset, ...]


@dataclass(frozen=True)
class AdornmentSet:
    """The full collection of available themes (Req 5.1, 5.2)."""

    themes: tuple[AdornmentTheme, ...]


class _ThemeLoadError(Exception):
    """Internal signal that a single theme could not be loaded.

    Raised while loading one theme directory so the top-level loader can exclude
    just that theme and continue with the rest (Req 5.5). Never escapes this
    module.
    """


def _load_asset(theme_dir: str, asset_meta: dict[str, object]) -> AdornmentAsset:
    """Build one :class:`AdornmentAsset` from its metadata entry.

    Reads the referenced PNG from ``theme_dir`` and decodes it to RGBA via
    Pillow. Raises :class:`_ThemeLoadError` when the metadata is malformed, the
    file is missing, or the image fails to decode.
    """

    file_name = asset_meta.get("file")
    if not isinstance(file_name, str) or not file_name:
        raise _ThemeLoadError("asset entry is missing a valid 'file' name")

    anchor = asset_meta.get("anchor")
    if anchor not in _VALID_ANCHORS:
        raise _ThemeLoadError(f"asset '{file_name}' has an invalid anchor: {anchor!r}")

    scale_raw = asset_meta.get("scale_factor")
    if not isinstance(scale_raw, (int, float)) or isinstance(scale_raw, bool):
        raise _ThemeLoadError(f"asset '{file_name}' has an invalid scale_factor")
    scale_factor = float(scale_raw)

    offset_raw = asset_meta.get("offset_ratio")
    if (
        not isinstance(offset_raw, (list, tuple))
        or len(offset_raw) != 2
        or any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in offset_raw
        )
    ):
        raise _ThemeLoadError(f"asset '{file_name}' has an invalid offset_ratio")
    offset_ratio = (float(offset_raw[0]), float(offset_raw[1]))

    rotate_raw = asset_meta.get("rotate_with_face")
    if not isinstance(rotate_raw, bool):
        raise _ThemeLoadError(f"asset '{file_name}' has an invalid rotate_with_face")
    rotate_with_face = rotate_raw

    asset_path = os.path.join(theme_dir, file_name)
    if not os.path.isfile(asset_path):
        raise _ThemeLoadError(f"asset file is missing: {asset_path}")

    try:
        with open(asset_path, "rb") as handle:
            raw = handle.read()
        image = Image.open(io.BytesIO(raw))
        # Force a load so truncated or malformed PNGs are surfaced here, then
        # convert to RGBA so the composition step can alpha-blend directly.
        image.load()
        image = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _ThemeLoadError(f"asset failed to decode: {asset_path}") from exc

    return AdornmentAsset(
        image=image,
        anchor=anchor,  # type: ignore[arg-type]  # validated against _VALID_ANCHORS
        scale_factor=scale_factor,
        offset_ratio=offset_ratio,
        rotate_with_face=rotate_with_face,
    )


def _load_theme(theme_dir: str) -> AdornmentTheme:
    """Load a single theme from its directory.

    Reads ``theme.json`` and every asset it references. Raises
    :class:`_ThemeLoadError` when the metadata is missing/invalid or any asset
    fails to load, so the caller can exclude just this theme (Req 5.5).
    """

    metadata_path = os.path.join(theme_dir, THEME_METADATA_FILENAME)
    if not os.path.isfile(metadata_path):
        raise _ThemeLoadError(f"theme metadata is missing: {metadata_path}")

    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, ValueError) as exc:
        raise _ThemeLoadError(f"theme metadata is unreadable: {metadata_path}") from exc

    if not isinstance(metadata, dict):
        raise _ThemeLoadError(f"theme metadata is not an object: {metadata_path}")

    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        raise _ThemeLoadError(f"theme metadata is missing a valid name: {metadata_path}")

    asset_entries = metadata.get("assets")
    if not isinstance(asset_entries, list) or not asset_entries:
        raise _ThemeLoadError(f"theme '{name}' declares no assets")

    assets: list[AdornmentAsset] = []
    for entry in asset_entries:
        if not isinstance(entry, dict):
            raise _ThemeLoadError(f"theme '{name}' has a malformed asset entry")
        assets.append(_load_asset(theme_dir, entry))

    return AdornmentTheme(name=name, assets=tuple(assets))


def load_adornment_set(assets_dir: str) -> tuple[AdornmentSet, list[str]]:
    """Load every theme's PNG assets and metadata at startup (Req 5.4).

    ``assets_dir`` is the directory that contains one subdirectory per theme
    (for example ``static/adornments``). Each theme subdirectory is read and its
    PNGs are decoded to RGBA via Pillow.

    Returns the loaded :class:`AdornmentSet` plus a list of names of themes that
    were excluded because an asset was missing or failed to decode (Req 5.5).
    All successfully loaded themes remain selectable; a single bad asset excludes
    only its own theme — identified by its directory name in the excluded list —
    while the others stay loaded.
    """

    themes: list[AdornmentTheme] = []
    excluded: list[str] = []

    if not os.path.isdir(assets_dir):
        # No catalog directory at all means no themes could be loaded; there are
        # no per-theme names to exclude in that case.
        return AdornmentSet(themes=()), excluded

    for entry_name in sorted(os.listdir(assets_dir)):
        theme_dir = os.path.join(assets_dir, entry_name)
        if not os.path.isdir(theme_dir):
            continue

        try:
            themes.append(_load_theme(theme_dir))
        except _ThemeLoadError:
            # Exclude only this theme and keep going so the others stay
            # selectable (Req 5.5). Identify the excluded theme by directory
            # name, which is available even when the metadata is unreadable.
            excluded.append(entry_name)

    return AdornmentSet(themes=tuple(themes)), excluded


def encode_result(result: "ResultImage", image_format: str) -> bytes:
    """Encode the Result_Image to bytes in the given format for streaming (Req 7.3).

    ``image_format`` is a Pillow format name such as ``"JPEG"`` or ``"PNG"``.
    JPEG has no alpha channel, so an RGBA (or otherwise alpha-carrying) image is
    flattened onto an opaque background before encoding; PNG preserves the image
    as-is. The encoded bytes are produced in memory and never written to disk.
    """

    normalized_format = image_format.strip().upper()
    if normalized_format == "JPG":
        normalized_format = "JPEG"

    pixels = result.pixels

    if normalized_format == "JPEG":
        # JPEG cannot store transparency. Composite any alpha-carrying image onto
        # an opaque background so the encoder receives a plain RGB image.
        if pixels.mode in ("RGBA", "LA") or (
            pixels.mode == "P" and "transparency" in pixels.info
        ):
            rgba = pixels.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            pixels = background
        elif pixels.mode != "RGB":
            pixels = pixels.convert("RGB")

    buffer = io.BytesIO()
    pixels.save(buffer, format=normalized_format)
    return buffer.getvalue()
