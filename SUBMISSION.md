*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Ghost in the Machine](https://dev.to/challenges/hacktoberfest-week3-2026-10-19)*

## What I Built

**Día de los Muertos Photo Booth** is a tiny Flask web app that decorates every face in a photo with festive Día de los Muertos adornments — all on your own machine, with no cloud, no account, and no photo ever leaving your computer.

You upload one JPEG or PNG. The app detects the faces in the picture locally, randomly assigns each face one of eight Día de los Muertos themes — **calavera** (sugar-skull decoration + forehead marigold), **sombrero** (hat + mustache), **flower_crown** (cempasúchil marigold crown), **catrina** (La Catrina veil + stitched lips), **papel_picado** (decorative banner), **marigold_path** (petal overlay + crown), **mariachi** (mustache + bow tie + sombrero), and **monarch** (monarch butterfly) — and alpha-composites transparent PNG adornments onto each face using its facial landmarks. Each adornment is anchored to the face: hats, crowns, veils, the monarch butterfly, and the forehead marigold sit above the head; the calavera decoration frames the eyes; mustaches and stitched lips land on the mouth; the bow tie sits at the chin; and the papel picado and marigold-petal overlays cover the whole frame. Several themes layer multiple pieces (for example, mariachi combines a mustache, a bow tie, and a sombrero). Every adornment scales with each face and rotates to follow a tilted head, so the result tracks the real geometry of the photo. You then see the composed image in the browser and can download it in the same format you uploaded.

**Who it's for:** anyone who wants a fun, instant, private way to celebrate Día de los Muertos with a photo effect — families, classrooms, cultural events, or a self-hosted photo-booth kiosk. Because everything runs locally and in memory, it's a good fit for anyone who cares that their faces and family photos are never uploaded to a third-party service.

The privacy guarantee is structural, not a promise: there is no external API, nothing is written to disk, and every buffer is released in a `try/finally` block on every request path. Processing is fully in-memory and ephemeral.

The adornment catalog is fully data-driven: each theme is a folder of transparent PNGs plus a `theme.json` describing how each piece is anchored, scaled, offset, and rotated, so themes can be added, enriched, or swapped without touching a line of code.

## Demo

Run it locally with Docker (see the run steps below) and open **http://localhost:5000**.

Pick a JPEG or PNG with one or more faces, click **Create portrait**, and the composed, adorned image appears in the result panel ready to download. No setup, seeding, or model download is required on first start — the app is ready the moment the container is up.

## Code

All code lives in `desafio5/` and is deliberately small: a thin Flask layer over pure, independently testable domain modules, a vanilla-JS frontend, and a single-service Docker stack.

- `app.py` — Flask app factory and routes. `GET /` renders the single-page upload UI; `POST /process` runs the full in-memory pipeline (validate → detect → assign themes → compose → encode) and streams the result back. Loads the adornment set once at startup, warms up the detection model, and enforces a 30 s processing budget.
- `validation.py` — decodes and validates the upload entirely in memory (10 MB limit, JPEG/PNG only, decodability, non-zero dimensions). Never touches disk.
- `detection.py` — the Detection_Engine wrapper around MediaPipe Face Mesh; locates up to 20 faces and derives the eye/mouth/head/chin landmarks used to anchor adornments.
- `composition.py` — the Composition_Engine: assigns a random theme per face and scales, rotates, and alpha-composites each PNG onto the photo while preserving the input dimensions.
- `adornments.py` — loads the Adornment_Set (PNG assets + per-theme `theme.json`) once at startup and encodes the result image back to bytes.
- `templates/index.html` — single-page upload interface (all labels in English).
- `static/app.js` + `static/style.css` — the fetch-based uploader and the responsive stylesheet.
- `static/adornments/<theme>/` — the transparent PNG assets and placement metadata per theme.
- `Dockerfile` + `docker-compose.yml` — a single `web` service served by gunicorn.
- `README.md` — project documentation (features, themes, architecture, run and usage instructions).

## How I Built It

The whole image-processing pipeline runs on an **open-source, fully local AI/vision stack**. No request ever leaves the machine, and no model weights are downloaded at runtime — they are bundled into the Docker image at build time. Here is each open-source tool and the core image-processing job it does:

- **MediaPipe** (Google's open-source on-device ML framework) is the heart of the app: its Face Mesh solution runs locally to both detect each face in the uploaded photo and compute the 468-point facial landmark set, from which the app derives the eye, mouth, top-of-head, and chin anchor points that every adornment is pinned to. The MediaPipe Python wheel ships its solution models inside the installed package, so they live in the image and there is no network call during a request. MediaPipe is pinned to a known-good release in `requirements.txt`, and the app runs one throwaway inference at startup to warm the model graph so the first real upload isn't penalized by lazy initialization.
- **Pillow (PIL)** does all of the raster work: it decodes the uploaded JPEG/PNG bytes into an image, scales each transparent PNG adornment to the face size, rotates it to match the eye-line angle, alpha-composites it onto the photo so the transparent edges blend cleanly, and finally encodes the composed result back to bytes in the same format the user uploaded.
- **OpenCV** (via `opencv-python-headless`, the server-friendly build with no GUI dependencies) provides the image-array handling and color/format conventions that MediaPipe builds on, so the decoded photo is presented to the detector in the array layout its inference graph expects.
- **NumPy** is the array representation of the image itself: the decoded photo is converted into a NumPy array that MediaPipe consumes directly as the frame it runs face detection and landmark inference on, making it the in-memory data structure that bridges Pillow/OpenCV and the model.

On top of that vision stack, **Flask** serves the single page and the processing endpoint, run under **gunicorn** inside the container, and the frontend is plain vanilla JavaScript that posts the file with `fetch` and renders the returned image blob.

The design decision I care most about is **local-and-ephemeral by construction**. Validation decodes the bytes in a memory buffer and never writes them; detection and composition operate on in-memory images; and the `/process` route releases every upload buffer and decoded image in a `finally` block on success, failure, and timeout alike. A face whose landmarks can't be computed is simply skipped while the other faces are still adorned, so a hard photo degrades gracefully instead of erroring out.

## Why Does Open Innovation Matter?

Building this on **open-source local models** instead of a hosted vision API changed what the project could be:

- **Privacy by default.** Faces are some of the most sensitive data there is. Because MediaPipe runs on-device and nothing is persisted, a user's photos never touch anyone else's servers. That is a guarantee a closed cloud API cannot make.
- **No per-image cost and no rate limits.** A classroom or a cultural-event kiosk can process as many photos as it likes with zero marginal cost, which is exactly what makes a free, celebratory tool viable.
- **It works offline.** The models are bundled in the image, so the booth keeps working with no internet at all — ideal for an event laptop or a kiosk on a flaky network.
- **It's auditable and adaptable.** Open tooling means the whole pipeline is inspectable, and the adornment art is just transparent PNGs plus a `theme.json`, so new themes can be dropped in without changing a line of code.

Open weights and on-device inference are what let a genuinely useful, face-aware AI effect live on cheap, private, offline hardware that anyone can own.

## My First User

<!-- Optional. Remove if unused. -->

## Prize Categories

<!-- Optional. List applicable partner categories or remove this section. -->

---

## Prerequisites

Before running the Docker commands below, make sure you have:

- **WSL 2** (Windows Subsystem for Linux, version 2). WSL 1 is not sufficient — the Docker Engine requires the WSL 2 backend.
- **Docker** with the **Docker Compose v2** plugin. Either:
  - **Docker Desktop** with **WSL 2 integration enabled** for your distro, or
  - **Docker Engine** installed directly inside your WSL 2 distro together with the **`docker compose` v2** plugin.

No other local setup is needed. In particular, **there is no model-pull step**: unlike an Ollama-based app, the MediaPipe models are bundled into the image at build time, so nothing is downloaded at runtime.

## Setup and Usage

### Run it with Docker (under WSL)

From the `desafio5/` directory, run these commands in order:

```bash
# 1. Build the image and start the app (single web service).
#    The MediaPipe models are baked into the image during the build,
#    so there is NO separate model-pull step and no network at request time.
docker compose up --build

# 2. Open the app in your browser.
#    http://localhost:5000
```

That's the complete sequence: `docker compose up --build` builds the image and starts the `web` service, which gunicorn serves on `0.0.0.0:5000` inside the container, published to the host as `5000:5000`. The app is then reachable at **http://localhost:5000**.

To stop the app, press `Ctrl+C` in that terminal (or run `docker compose down` from the `desafio5/` directory).

### Using the app

1. Open **http://localhost:5000**.
2. Click **Choose an image** and select exactly one **JPEG or PNG** photo (up to 10 MB) that contains one or more faces.
3. Click **Create portrait**. A progress indicator appears while the photo is processed locally.
4. The composed image — each detected face given a random Día de los Muertos theme — appears in the result panel.
5. Click **Download image** to save it. The download is in the same format (JPEG or PNG) as the photo you uploaded.

If no face is detected, or the file is not a valid JPEG/PNG within the size limit, the app shows a clear message and stays ready for another upload without reloading the page.
