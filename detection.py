"""Detection_Engine wrapper around MediaPipe Face Detection / Face Mesh.

This module locates faces in a decoded, in-memory image and computes the
facial landmarks needed to anchor Dia de los Muertos adornments. All inference runs
entirely on the local machine using the MediaPipe models bundled with the
application; nothing is sent off the machine and no model weights are
downloaded at runtime (Requirements 3.4, 8.1, 9.4).

MediaPipe (and its OpenCV/NumPy dependencies) are imported lazily inside
``detect_faces`` so that this module still imports and parses in environments
where MediaPipe is not installed. The dataclasses, constants, and the pure
helper ``inter_eye_distance`` are always available.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # ``validation`` is produced by a parallel task. Importing it only under
    # TYPE_CHECKING keeps this module importable before validation.py exists,
    # while still giving type checkers the real LoadedImage type.
    from validation import LoadedImage


# Maximum number of faces processed within a single Uploaded_Photo (Req 3.3).
MAX_FACES = 20

# Local time budget for detection + landmark computation (Req 3.1).
DETECTION_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Landmarks:
    """Key facial points needed to anchor adornments, in pixel coordinates."""

    left_eye: tuple[float, float]
    right_eye: tuple[float, float]
    mouth_center: tuple[float, float]
    top_of_head: tuple[float, float]
    chin: tuple[float, float]


@dataclass(frozen=True)
class DetectedFace:
    """A single located face: its bounding box and computed landmarks.

    ``bbox`` is ``(x, y, width, height)`` in pixels. ``landmarks`` is ``None``
    when landmark computation failed for this face, so the composition step can
    skip only that face while still adorning the others (Req 4.6).
    """

    bbox: tuple[int, int, int, int]
    landmarks: Landmarks | None


class DetectionError(Exception):
    """Raised when detection cannot run or exceeds its local time budget.

    Carries a user-facing message in English for the Flask layer to surface.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# MediaPipe Face Mesh landmark indices (468-point canonical face model).
# These select the points used to derive the anchor landmarks above.
_LEFT_EYE_INDICES = (33, 133, 159, 145)
_RIGHT_EYE_INDICES = (362, 263, 386, 374)
_MOUTH_INDICES = (13, 14, 78, 308)
_TOP_OF_HEAD_INDEX = 10
_CHIN_INDEX = 152


def inter_eye_distance(landmarks: Landmarks) -> float:
    """Return the Euclidean distance between the two eyes, used for scaling.

    This is a pure function used to scale adornments relative to face size
    (Req 4.3).
    """
    (lx, ly) = landmarks.left_eye
    (rx, ry) = landmarks.right_eye
    return math.hypot(rx - lx, ry - ly)


def _centroid(
    points: "list[tuple[float, float]]",
    indices: tuple[int, ...],
) -> tuple[float, float]:
    """Average the selected landmark points into a single (x, y) coordinate."""
    xs = [points[i][0] for i in indices]
    ys = [points[i][1] for i in indices]
    count = len(indices)
    return (sum(xs) / count, sum(ys) / count)


def _landmarks_from_mesh(
    normalized_points: "list[tuple[float, float]]",
    width: int,
    height: int,
) -> Landmarks | None:
    """Build a :class:`Landmarks` from normalized Face Mesh points.

    ``normalized_points`` holds (x, y) values in the 0..1 range produced by
    MediaPipe. Returns ``None`` when the mesh is missing points required to
    anchor the adornments, so the caller records ``landmarks=None`` for the
    face instead of failing the whole image (Req 4.6).
    """
    required = set(
        _LEFT_EYE_INDICES
        + _RIGHT_EYE_INDICES
        + _MOUTH_INDICES
        + (_TOP_OF_HEAD_INDEX, _CHIN_INDEX)
    )
    if any(index >= len(normalized_points) for index in required):
        return None

    # Convert normalized coordinates to absolute pixel coordinates.
    pixels = [(x * width, y * height) for (x, y) in normalized_points]

    try:
        left_eye = _centroid(pixels, _LEFT_EYE_INDICES)
        right_eye = _centroid(pixels, _RIGHT_EYE_INDICES)
        mouth_center = _centroid(pixels, _MOUTH_INDICES)
        top_of_head = pixels[_TOP_OF_HEAD_INDEX]
        chin = pixels[_CHIN_INDEX]
    except (IndexError, ZeroDivisionError):
        return None

    return Landmarks(
        left_eye=left_eye,
        right_eye=right_eye,
        mouth_center=mouth_center,
        top_of_head=top_of_head,
        chin=chin,
    )


def _bbox_from_mesh(
    normalized_points: "list[tuple[float, float]]",
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Compute an (x, y, width, height) pixel bounding box around a face mesh."""
    xs = [x * width for (x, _) in normalized_points]
    ys = [y * height for (_, y) in normalized_points]
    min_x = max(0, int(math.floor(min(xs))))
    min_y = max(0, int(math.floor(min(ys))))
    max_x = min(width, int(math.ceil(max(xs))))
    max_y = min(height, int(math.ceil(max(ys))))
    return (min_x, min_y, max(0, max_x - min_x), max(0, max_y - min_y))


def _import_face_mesh_module():
    """Return MediaPipe's Face Mesh solution module, resolved robustly.

    Imports ``mediapipe.python.solutions.face_mesh`` directly rather than going
    through the ``mediapipe.solutions`` attribute, which is not reliably exposed
    on the top-level package in recent MediaPipe wheels. Falls back to the other
    known import paths and raises :class:`DetectionError` when none work.
    """

    import importlib

    for module_path in (
        "mediapipe.python.solutions.face_mesh",
        "mediapipe.solutions.face_mesh",
    ):
        try:
            return importlib.import_module(module_path)
        except ImportError:
            continue

    # Last resort: import the package and read the attribute if present.
    try:
        import mediapipe as mp  # noqa: WPS433 (intentional lazy import)

        return mp.solutions.face_mesh
    except (ImportError, AttributeError) as exc:  # pragma: no cover
        raise DetectionError(
            "Face detection is unavailable on this server."
        ) from exc


def warm_up() -> bool:
    """Run one throwaway Face Mesh inference so the model graph is built eagerly.

    MediaPipe builds its inference graph lazily on the first ``process`` call,
    which can make the first real request noticeably slow. Calling this once at
    startup moves that cost off the request path. It is best-effort: any failure
    (MediaPipe/NumPy unavailable, etc.) is swallowed and reported via the return
    value so startup never fails because of warm-up. Returns ``True`` when the
    warm-up inference ran, ``False`` otherwise.
    """

    try:
        import numpy as np  # noqa: WPS433 (intentional lazy import)

        face_mesh_solution = _import_face_mesh_module()
        blank = np.zeros((64, 64, 3), dtype=np.uint8)
        with face_mesh_solution.FaceMesh(
            static_image_mode=True,
            max_num_faces=MAX_FACES,
            refine_landmarks=False,
            min_detection_confidence=0.5,
        ) as mesh:
            mesh.process(blank)
        return True
    except Exception:  # noqa: BLE001 - warm-up must never break startup
        return False


def detect_faces(image: "LoadedImage") -> list[DetectedFace]:
    """Locate up to :data:`MAX_FACES` faces and compute landmarks, fully offline.

    Wraps MediaPipe Face Mesh (which performs its own face detection). Returns
    an empty list when no face is found (Req 3.5). Runs entirely on the local
    machine and sends nothing off it (Req 3.4). A face whose landmark
    computation fails is returned with ``landmarks=None`` so the composition
    step can skip only that face (Req 4.6).

    Enforces a local time budget of :data:`DETECTION_TIMEOUT_SECONDS`: if the
    budget is exhausted a :class:`DetectionError` is raised (Req 3.1).
    """
    started_at = time.monotonic()

    def _remaining_budget() -> float:
        return DETECTION_TIMEOUT_SECONDS - (time.monotonic() - started_at)

    # Lazy imports keep the module importable without the heavy CV stack
    # installed, and ensure MediaPipe is only loaded when detection runs.
    try:
        import numpy as np  # noqa: WPS433 (intentional lazy import)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DetectionError(
            "Face detection is unavailable on this server."
        ) from exc

    # Resolve the legacy Face Mesh "solutions" module. On recent MediaPipe
    # wheels the top-level ``mediapipe`` package does not expose
    # ``mp.solutions`` as an attribute (accessing it raises "module
    # 'mediapipe' has no attribute 'solutions'"), so the submodule is imported
    # explicitly by ``_import_face_mesh_module``.
    face_mesh_solution = _import_face_mesh_module()

    # Convert the decoded Pillow image to an RGB NumPy array that MediaPipe
    # expects. This stays entirely in memory.
    rgb_image = image.pixels.convert("RGB")
    frame = np.asarray(rgb_image)

    if _remaining_budget() <= 0:
        raise DetectionError("Face detection timed out. Please try again.")


    # static_image_mode=True targets single still images (not a video stream).
    # max_num_faces caps the work and the result size at MAX_FACES (Req 3.3).
    with face_mesh_solution.FaceMesh(
        static_image_mode=True,
        max_num_faces=MAX_FACES,
        refine_landmarks=False,
        min_detection_confidence=0.5,
    ) as mesh:
        results = mesh.process(frame)

    if _remaining_budget() <= 0:
        raise DetectionError("Face detection timed out. Please try again.")

    multi_face_landmarks = getattr(results, "multi_face_landmarks", None)
    if not multi_face_landmarks:
        # No face located in a valid photo (Req 3.5).
        return []

    faces: list[DetectedFace] = []
    for face_landmark_list in multi_face_landmarks[:MAX_FACES]:
        if _remaining_budget() <= 0:
            raise DetectionError("Face detection timed out. Please try again.")

        try:
            normalized_points = [
                (point.x, point.y) for point in face_landmark_list.landmark
            ]
        except AttributeError:
            # Malformed landmark payload for this face: keep the face with a
            # best-effort bbox but no landmarks so composition skips it.
            normalized_points = []

        if not normalized_points:
            faces.append(
                DetectedFace(bbox=(0, 0, 0, 0), landmarks=None)
            )
            continue

        bbox = _bbox_from_mesh(normalized_points, image.width, image.height)
        landmarks = _landmarks_from_mesh(
            normalized_points, image.width, image.height
        )
        faces.append(DetectedFace(bbox=bbox, landmarks=landmarks))

    return faces
