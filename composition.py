"""Composition_Engine: theme assignment and adornment compositing.

This module assigns a random Dia de los Muertos Adornment_Theme to each detected face
and (in a later step) composites the themed PNG adornments over the uploaded
photo to produce the Result_Image. All processing happens in memory; nothing
is written to disk.

The composition step relies on ``inter_eye_distance`` from the ``detection``
module and on Pillow (``PIL.Image``) for every raster operation (scaling,
rotation, alpha compositing). Those are imported at runtime because the
``compose`` / ``_place_adornment`` code below actually calls them.

Type-only names (``DetectedFace`` / ``Landmarks`` from ``detection`` and
``AdornmentSet`` / ``AdornmentTheme`` / ``AdornmentAsset`` from ``adornments``)
are imported under ``TYPE_CHECKING`` together with ``from __future__ import
annotations`` so the annotations read cleanly without forcing extra runtime
imports.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from detection import inter_eye_distance

if TYPE_CHECKING:
    # ``detection`` provides DetectedFace / Landmarks; ``adornments`` provides
    # the theme catalog types. These are only needed for annotations, so they
    # stay under TYPE_CHECKING.
    from PIL.Image import Image as PILImage

    from adornments import AdornmentAsset, AdornmentSet, AdornmentTheme
    from detection import DetectedFace
    from validation import LoadedImage


def assign_themes(
    faces: list["DetectedFace"],
    adornment_set: "AdornmentSet",
    rng: random.Random,
) -> list["AdornmentTheme"]:
    """Assign exactly one Adornment_Theme to each detected face.

    Each face receives a theme chosen uniformly and independently at random
    from the Adornment_Set's available themes (Requirements 4.1, 4.5). The
    selection is made with ``rng.choice`` per face, so every theme is equally
    likely and each draw is independent of the others. For ``N`` faces this
    returns ``N`` themes, one per face, in the same order as the input faces.

    Args:
        faces: The detected faces to assign themes to.
        adornment_set: The non-empty collection of available themes.
        rng: Injectable random source (``random.Random``) so tests can seed
            and reproduce assignments deterministically.

    Returns:
        A list of assigned themes with exactly one entry per input face.
    """
    return [rng.choice(adornment_set.themes) for _ in range(len(faces))]


@dataclass
class ResultImage:
    """The composed output image, held entirely in memory (never on disk).

    ``image_format`` carries the same Pillow format name as the originating
    ``LoadedImage`` ("JPEG" or "PNG"), so the output is encoded back in the same
    format as the input (Req 7.3).
    """

    pixels: Image.Image  # Pillow image object
    image_format: str  # same format as the originating LoadedImage


def _face_size(face: "DetectedFace") -> float:
    """Return a positive scalar describing the face's size for scaling.

    Scaling is relative to the inter-eye distance (Req 4.3). When landmarks make
    that distance unavailable (missing landmarks, or two eyes resolving to the
    same point), fall back to the bounding-box width. The returned value is
    always strictly positive so later scaling never collapses an asset to zero.
    """

    landmarks = face.landmarks
    if landmarks is not None:
        distance = inter_eye_distance(landmarks)
        if distance > 0:
            return distance

    # Fall back to the bounding-box width when the inter-eye distance is
    # unavailable or degenerate.
    _, _, width, _ = face.bbox
    if width > 0:
        return float(width)

    # Last-resort guard so scaling math stays well defined.
    return 1.0


def _eye_line_angle(face: "DetectedFace") -> float:
    """Return the eye-line angle in degrees, measured from the horizontal.

    Computed from the left and right eye landmarks via ``atan2`` (Req 4.3). A
    positive angle means the right eye sits lower than the left eye in image
    coordinates (y grows downward). Returns 0.0 when landmarks are unavailable.
    """

    landmarks = face.landmarks
    if landmarks is None:
        return 0.0
    (lx, ly) = landmarks.left_eye
    (rx, ry) = landmarks.right_eye
    return math.degrees(math.atan2(ry - ly, rx - lx))


def _anchor_position(
    asset: "AdornmentAsset",
    face: "DetectedFace",
    face_size: float,
) -> tuple[float, float] | None:
    """Resolve the asset's anchor to a pixel center position on the canvas.

    Maps each :class:`~adornments.Anchor` value to the landmark (or bounding-box
    derived point) it attaches to, then shifts that point by
    ``asset.offset_ratio`` expressed as a fraction of the face size. Returns the
    center ``(x, y)`` the scaled/rotated asset should be placed on, or ``None``
    when the required landmark is unavailable (so the caller can skip the asset).

    ``"full_frame"`` is handled by the caller and never reaches this function.
    """

    landmarks = face.landmarks
    bbox_x, bbox_y, bbox_w, bbox_h = face.bbox

    base: tuple[float, float] | None
    if asset.anchor == "mouth":
        base = landmarks.mouth_center if landmarks is not None else None
    elif asset.anchor == "chin":
        base = landmarks.chin if landmarks is not None else None
    elif asset.anchor == "eyes":
        if landmarks is not None:
            (lx, ly) = landmarks.left_eye
            (rx, ry) = landmarks.right_eye
            base = ((lx + rx) / 2.0, (ly + ry) / 2.0)
        else:
            base = None
    elif asset.anchor == "above_head":
        # Anchor at the top of the head, offset upward by roughly half a face
        # size so hats/crowns/veils sit above the crown rather than on it.
        if landmarks is not None:
            (hx, hy) = landmarks.top_of_head
            base = (hx, hy - face_size * 0.5)
        else:
            base = None
    elif asset.anchor == "behind_head":
        # Centered behind the face: prefer the top-of-head x with the bbox
        # vertical center, falling back to the bbox center when no landmarks.
        if landmarks is not None:
            (hx, _) = landmarks.top_of_head
            base = (hx, bbox_y + bbox_h / 2.0)
        else:
            base = (bbox_x + bbox_w / 2.0, bbox_y + bbox_h / 2.0)
    else:
        # Unknown anchor: nothing to place.
        base = None

    if base is None:
        return None

    # Apply the per-asset offset as a fraction of the face size (Req 4.3).
    offset_x, offset_y = asset.offset_ratio
    return (base[0] + offset_x * face_size, base[1] + offset_y * face_size)


def _place_adornment(
    canvas: "PILImage",
    asset: "AdornmentAsset",
    face: "DetectedFace",
) -> None:
    """Scale, rotate, and alpha-blend one PNG adornment onto ``canvas`` in place.

    The asset is scaled relative to the face size (inter-eye distance, falling
    back to bounding-box width), rotated by the eye-line angle when
    ``asset.rotate_with_face`` is True, and alpha-composited onto the canvas so
    its center lands on the anchored landmark position shifted by
    ``asset.offset_ratio`` (Req 4.2, 4.3).

    ``"full_frame"`` assets ignore per-face landmarks and are scaled to cover
    the whole canvas. For every other anchor, when the required landmark is
    unavailable the asset is skipped (the caller already skips faces whose
    landmarks are entirely ``None``; this is a per-asset safety net).

    The canvas is expected to be an RGBA Pillow image and is mutated in place.
    """

    source = asset.image.convert("RGBA")

    if asset.anchor == "full_frame":
        # Scale to cover the entire canvas and composite from the origin; the
        # full-frame overlay does not depend on any per-face landmark.
        canvas_w, canvas_h = canvas.size
        if canvas_w <= 0 or canvas_h <= 0:
            return
        scaled = source.resize((canvas_w, canvas_h), Image.LANCZOS)
        canvas.alpha_composite(scaled, dest=(0, 0))
        return

    face_size = _face_size(face)

    # Scale the asset by the face size times its configured scale factor. The
    # asset's native width maps to ``scale_factor * face_size`` pixels, keeping
    # its aspect ratio so larger faces receive proportionally larger adornments
    # (Req 4.3).
    src_w, src_h = source.size
    if src_w <= 0 or src_h <= 0:
        return
    target_w = max(1, int(round(asset.scale_factor * face_size)))
    aspect = src_h / src_w
    target_h = max(1, int(round(target_w * aspect)))
    scaled = source.resize((target_w, target_h), Image.LANCZOS)

    # Rotate by the eye-line angle so the adornment follows a tilted face.
    if asset.rotate_with_face:
        angle = _eye_line_angle(face)
        if angle != 0.0:
            # Pillow rotates counter-clockwise for positive angles; our eye-line
            # angle is measured clockwise-positive in image coordinates, so
            # negate it to rotate the asset in the same direction as the face.
            scaled = scaled.rotate(
                -angle,
                resample=Image.BICUBIC,
                expand=True,
            )

    position = _anchor_position(asset, face, face_size)
    if position is None:
        return

    # Center the scaled/rotated asset on the anchor point.
    asset_w, asset_h = scaled.size
    top_left_x = int(round(position[0] - asset_w / 2.0))
    top_left_y = int(round(position[1] - asset_h / 2.0))

    # Alpha-composite onto a transparent full-canvas layer so the paste honors
    # the asset's alpha even when it spills past the canvas edges.
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(scaled, (top_left_x, top_left_y), scaled)
    canvas.alpha_composite(layer)


def compose(
    image: "LoadedImage",
    faces: list["DetectedFace"],
    themes: list["AdornmentTheme"],
) -> ResultImage:
    """Composite each face's themed adornments over the photo (Req 4.2, 4.3, 4.4).

    ``faces`` and ``themes`` are parallel lists: ``themes[i]`` is the theme
    assigned to ``faces[i]``. For each face, every asset in its theme is placed
    with :func:`_place_adornment`. A face whose ``landmarks`` is ``None`` is
    skipped so its landmark-anchored adornments are not misplaced, while every
    other face is still composited (Req 4.6); a face's ``full_frame`` assets do
    not require landmarks and are still applied.

    The result preserves the input image's exact width and height (Req 4.4): the
    work happens on an RGBA copy of the photo at its original size. When the
    originating image is JPEG the canvas is flattened back to RGB (JPEG has no
    alpha channel) before building the :class:`ResultImage`; PNG keeps its RGBA
    canvas. ``ResultImage.image_format`` always equals ``image.image_format``.
    """

    # Work on an RGBA copy of the photo so compositing never mutates the input
    # and the alpha channel is available for blending. ``convert`` already
    # produces a fresh image at the original dimensions, preserving size.
    canvas = image.pixels.convert("RGBA")

    for face, theme in zip(faces, themes):
        has_landmarks = face.landmarks is not None
        for asset in theme.assets:
            if asset.anchor == "full_frame":
                # Full-frame overlays do not depend on landmarks (Req 4.6).
                _place_adornment(canvas, asset, face)
            elif has_landmarks:
                _place_adornment(canvas, asset, face)
            # Otherwise the face has no landmarks: skip this landmark-anchored
            # asset while leaving the rest of the composition intact.

    # Flatten to RGB for JPEG (which cannot store transparency); keep RGBA for
    # PNG. The output dimensions equal the input's in both cases (Req 4.4).
    if image.image_format == "JPEG":
        background = Image.new("RGB", canvas.size, (255, 255, 255))
        background.paste(canvas, mask=canvas.split()[-1])
        result_pixels: Image.Image = background
    else:
        result_pixels = canvas

    return ResultImage(pixels=result_pixels, image_format=image.image_format)
