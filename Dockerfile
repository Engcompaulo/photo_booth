# Dia de los Muertos Photo Booth - Flask application image (Req 10.1)
# Small, self-contained image: the MediaPipe models are bundled at build time
# so there is no runtime download and no network access during a request.
FROM python:3.12-slim

# Keep Python output unbuffered and skip .pyc files for cleaner container logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# MediaPipe and opencv-python-headless still link against a few shared system
# libraries that are not present on the slim base image, even for headless use:
#   - libgl1          : OpenGL runtime (libGL.so.1) required by OpenCV/MediaPipe
#   - libglib2.0-0    : GLib runtime (libgthread/libglib) required by OpenCV
#   - libgomp1        : OpenMP runtime (libgomp.so.1) used by MediaPipe/OpenCV
# Installed with --no-install-recommends and the apt lists removed afterwards to
# keep the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to leverage Docker layer caching.
# Installing mediapipe here also bundles its solution models (face_mesh /
# face_detection): the MediaPipe Python wheel ships those model assets inside
# the installed package, so after this step the models live under the installed
# mediapipe package in the image. There is therefore NO runtime model download
# and NO network at request time (Req 9.4, 3.4, 10.1).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source (app modules, static/ assets, templates/).
COPY . .

# Flask app served by gunicorn listens on 5000 (matches app.py's PORT default
# and docker-compose.yml).
EXPOSE 5000

# Serve the WSGI app (app:app) with gunicorn on port 5000.
# The pipeline is synchronous and has its own 30 s budget
# (PROCESSING_TIMEOUT_SECONDS=30 in app.py). gunicorn's default 30 s worker
# timeout would race that budget and kill the worker mid-request, so it is
# raised to 60 s to comfortably exceed PROCESSING_TIMEOUT_SECONDS. A single
# worker keeps memory low for the image-processing workload; raise --workers if
# more concurrency is needed.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "60", "app:app"]
