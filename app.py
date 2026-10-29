"""Flask web layer for the Dia de los Muertos Photo Booth.

This module hosts the thin HTTP layer: the Flask application factory
(``create_app``) and the routes. The heavy lifting lives in the pure domain
modules (``validation``, ``detection``, ``composition``, ``adornments``), which
know nothing about Flask, keeping the pipeline testable in isolation.

At startup the factory loads the immutable ``Adornment_Set`` exactly once from
the bundled PNG assets under ``static/adornments/`` and logs any theme that had
to be excluded because an asset was missing or failed to decode (Req 5.5). The
loaded set is stored on the app so the ``POST /process`` route can reuse it on
every request without reloading from disk.

``GET /`` renders the single-page upload interface (Req 1.1). The
``POST /process`` route — the full validate -> detect -> compose -> encode
pipeline — is registered by a later task inside this same factory.

The module exposes ``app = create_app()`` for gunicorn (``app:app``), mirroring
``desafio3``, plus a ``__main__`` block for local development.

All code, comments and identifiers are written in English (Req 10.7).
"""

from __future__ import annotations

import io
import logging
import os
import random
import time

from flask import Flask, Response, current_app, jsonify, render_template, request

from adornments import encode_result, load_adornment_set
from composition import ResultImage, assign_themes, compose
from detection import DetectionError, detect_faces, warm_up
from validation import (
    LoadedImage,
    ValidationError,
    is_supported_dimensions,
    validate_upload,
)

# Module-level constants shared by the HTTP layer and the request pipeline.
MAX_UPLOAD_BYTES = 10_485_760  # 10 MB hard limit (Req 1.5, 2.2)
PROCESSING_TIMEOUT_SECONDS = 30  # abort budget for the pipeline (Req 9.3)
ACCEPTED_FORMATS = ("JPEG", "PNG")  # only these input formats are accepted (Req 1.2)

# Directory holding one subdirectory per adornment theme, resolved relative to
# this file so it works regardless of the process working directory.
ADORNMENTS_DIR = os.path.join(os.path.dirname(__file__), "static", "adornments")

# Config key under which the loaded AdornmentSet is stored on the app so the
# /process route (added by a later task) can reuse it without reloading.
ADORNMENT_SET_CONFIG_KEY = "ADORNMENT_SET"

# Exact, user-facing English messages owned by the Flask layer (the design's
# Error Handling table). Validation/detection messages travel on their typed
# exceptions; these cover the conditions decided here in the HTTP layer.
NO_FILE_MESSAGE = "Please select an image before submitting."  # Req 1.6
UNSUPPORTED_DIMENSIONS_MESSAGE = "This photo is invalid or unsupported."  # Req 3.6
NO_FACE_MESSAGE = "No face was detected. Please try another photo."  # Req 3.5, 6.1
PROCESSING_TIMEOUT_MESSAGE = "Processing timed out. Please try again."  # Req 9.3

# Map the authoritative Pillow format name of the Result_Image to the HTTP
# response Content-Type and the download filename extension (Req 7.3).
_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}
_FORMAT_TO_EXTENSION = {"JPEG": "jpg", "PNG": "png"}

# Download filename stem; combined with the format extension to build a
# non-empty Content-Disposition filename (Req 7.3).
DOWNLOAD_FILENAME_STEM = "dia-de-los-muertos-photo-booth"

logger = logging.getLogger(__name__)


def _declared_format_hint(uploaded_file) -> str | None:
    """Derive a best-effort format hint from the upload's MIME type / filename.

    The hint is only advisory: ``validate_upload`` treats the format Pillow
    reports after decoding as authoritative. We look at the declared content
    type first (for example ``image/png``) and fall back to the filename
    extension. Returns a Pillow-style format name (``"JPEG"`` / ``"PNG"``) when
    recognized, otherwise ``None``.
    """

    content_type = (getattr(uploaded_file, "mimetype", "") or "").strip().lower()
    if content_type == "image/jpeg" or content_type == "image/jpg":
        return "JPEG"
    if content_type == "image/png":
        return "PNG"

    filename = (getattr(uploaded_file, "filename", "") or "").strip().lower()
    _, extension = os.path.splitext(filename)
    if extension in (".jpg", ".jpeg"):
        return "JPEG"
    if extension == ".png":
        return "PNG"
    return None


def create_app() -> Flask:
    """Build and configure the Flask application.

    Loads the ``Adornment_Set`` once at startup (logging any unavailable
    themes, Req 5.5), sets the upload size guard, stores the loaded set on the
    app for the request pipeline to reuse, and registers the routes. Returns the
    ready-to-serve application instance.
    """
    flask_app = Flask(__name__)

    # Enforce the upload size ceiling at the framework level as a first guard;
    # the validation layer enforces the same limit again inside the pipeline.
    flask_app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    # Load the immutable Adornment_Set a single time at startup and keep every
    # selectable theme; a theme whose asset is missing or undecodable is
    # excluded and logged so the others stay usable (Req 5.4, 5.5).
    adornment_set, excluded_themes = load_adornment_set(ADORNMENTS_DIR)
    for theme_name in excluded_themes:
        logger.warning("Theme '%s' is unavailable.", theme_name)
    flask_app.config[ADORNMENT_SET_CONFIG_KEY] = adornment_set

    # Warm up MediaPipe once at startup so the first real upload is not slowed
    # by the lazy graph build. Best-effort: a failure here is logged but never
    # blocks startup.
    if warm_up():
        logger.info("Face detection model warmed up.")
    else:
        logger.info("Face detection warm-up skipped or unavailable.")

    @flask_app.route("/")
    def index() -> str:
        """GET / — render the single-page upload interface (Req 1.1)."""
        return render_template("index.html")

    @flask_app.route("/process", methods=["POST"])
    def process() -> Response:
        """POST /process — validate, detect, compose, and stream the Result_Image.

        Reads exactly one uploaded file (Req 1.1) and runs the full in-memory
        pipeline ``validate_upload -> detect_faces -> assign_themes -> compose
        -> encode_result``. Typed domain failures are mapped to HTTP statuses
        with the exact English messages from the design's Error Handling table:
        client problems (missing file, validation, unsupported dimensions, no
        face) return ``400`` JSON ``{"error": ...}`` and a detection failure or
        a blown 30 s budget returns ``503`` (Req 1.6, 3.5, 3.6, 6.1, 9.3). On
        success the encoded image bytes are streamed back with a matching
        ``Content-Type`` and a non-empty download filename (Req 7.3).

        A single ``finally`` block releases the upload buffer and every decoded
        Pillow image / result buffer on every path — success, validation
        failure, detection failure, mid-composition failure, or abort — so
        nothing lingers in memory and nothing is ever written to disk
        (Req 8.1, 8.2, 8.3, 8.4, 8.5).
        """

        started_at = time.monotonic()

        # References tracked so the finally block can release them on every
        # exit path. They are populated as the pipeline advances.
        upload_buffer: io.BytesIO | None = None
        loaded_image: LoadedImage | None = None
        result_image: ResultImage | None = None

        def _timed_out() -> bool:
            """True once the 30 s processing budget is exhausted (Req 9.3)."""
            return time.monotonic() - started_at >= PROCESSING_TIMEOUT_SECONDS

        try:
            # 1. Read exactly one uploaded file (Req 1.1). A missing file is a
            #    client error with the no-file message (Req 1.6).
            uploaded_file = request.files.get("image")
            if uploaded_file is None or not (uploaded_file.filename or ""):
                return _error_response(NO_FILE_MESSAGE, 400)

            declared_format = _declared_format_hint(uploaded_file)

            # Read the raw bytes into an in-memory buffer; never to disk
            # (Req 8.1, 8.2).
            upload_buffer = io.BytesIO()
            uploaded_file.save(upload_buffer)
            raw_bytes = upload_buffer.getvalue()

            # 2. Validate size/format/decodability/dimensions. ValidationError
            #    carries the exact user-facing message (Req 1.4, 1.5, 1.7, 2.x).
            loaded_image = validate_upload(raw_bytes, declared_format)

            # Dimensions must fall in the 64..8000 px range detection supports
            # (Req 3.6); otherwise the photo is unsupported.
            if not is_supported_dimensions(loaded_image.width, loaded_image.height):
                return _error_response(UNSUPPORTED_DIMENSIONS_MESSAGE, 400)

            if _timed_out():
                return _error_response(PROCESSING_TIMEOUT_MESSAGE, 503)

            # 3. Locate faces. DetectionError (timeout/unavailable) maps to 503
            #    (Req 9.3). An empty result means no face was detected, so the
            #    pipeline stops here and never builds a Result_Image
            #    (Req 3.5, 6.1, 6.2).
            faces = detect_faces(loaded_image)

            if _timed_out():
                return _error_response(PROCESSING_TIMEOUT_MESSAGE, 503)

            if not faces:
                return _error_response(NO_FACE_MESSAGE, 400)

            # 4. Assign a random theme per face from the preloaded Adornment_Set
            #    (reused, never reloaded) and composite the Result_Image, which
            #    preserves the input dimensions (Req 4.4).
            adornment_set = current_app.config[ADORNMENT_SET_CONFIG_KEY]
            themes = assign_themes(faces, adornment_set, random.Random())
            result_image = compose(loaded_image, faces, themes)

            if _timed_out():
                return _error_response(PROCESSING_TIMEOUT_MESSAGE, 503)

            # 5. Encode the result back to bytes in the same format as the input
            #    (Req 7.3) and stream it with a non-empty download filename.
            encoded = encode_result(result_image, result_image.image_format)

            if _timed_out():
                return _error_response(PROCESSING_TIMEOUT_MESSAGE, 503)

            response_format = result_image.image_format
            mime_type = _FORMAT_TO_MIME.get(response_format, "application/octet-stream")
            extension = _FORMAT_TO_EXTENSION.get(response_format, "img")
            filename = f"{DOWNLOAD_FILENAME_STEM}.{extension}"

            response = Response(encoded, status=200, mimetype=mime_type)
            response.headers["Content-Disposition"] = (
                f'attachment; filename="{filename}"'
            )
            return response

        except ValidationError as exc:
            # Validation failures carry the exact English message (Req 1.4, 1.5,
            # 1.7, 2.2, 2.3, 2.4).
            return _error_response(exc.message, 400)
        except DetectionError:
            # Detection unavailable or over its own time budget surfaces as a
            # processing timeout to the client (Req 9.3).
            return _error_response(PROCESSING_TIMEOUT_MESSAGE, 503)
        finally:
            # Release every in-memory buffer and decoded image on all paths —
            # success, any failure, or abort — so nothing persists (Req 8.3,
            # 8.4, 8.5). Each close is guarded so cleanup never raises.
            if upload_buffer is not None:
                try:
                    upload_buffer.close()
                except Exception:  # noqa: BLE001 - cleanup must not raise
                    pass
            if loaded_image is not None and loaded_image.pixels is not None:
                try:
                    loaded_image.pixels.close()
                except Exception:  # noqa: BLE001 - cleanup must not raise
                    pass
            if result_image is not None and result_image.pixels is not None:
                try:
                    result_image.pixels.close()
                except Exception:  # noqa: BLE001 - cleanup must not raise
                    pass
            # Drop references so the garbage collector can reclaim the memory.
            upload_buffer = None
            loaded_image = None
            result_image = None

    return flask_app


def _error_response(message: str, status: int) -> Response:
    """Build a JSON error response ``{"error": message}`` with ``status``.

    Centralizes the error contract so every failure path returns the same
    JSON shape with the proper HTTP status code (Req 9.4).
    """

    response = jsonify({"error": message})
    response.status_code = status
    return response


# Module-level application object exposed for gunicorn as ``app:app``.
app = create_app()


if __name__ == "__main__":
    # Local development entry point; production serves this via gunicorn.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
