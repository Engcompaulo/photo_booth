# Día de los Muertos Photo Booth

A tiny, privacy-first web app that decorates every face in a photo with festive
**Día de los Muertos** adornments — running **100% locally**, with no cloud, no
account, and no photo ever leaving your machine.

You upload one JPEG or PNG. The app detects the faces in the picture locally,
randomly assigns each face a Día de los Muertos theme, and alpha-composites
transparent PNG adornments onto each face using its facial landmarks. The
result is shown in the browser and can be downloaded in the same format you
uploaded.

> Built for the Hacktoberfest Open-Source AI Challenge Week 3: *Ghost in the
> Machine*. See [`SUBMISSION.md`](SUBMISSION.md) for the challenge submission.

---

## Features

- **Automatic face detection** — locates up to 20 faces per photo using
  on-device AI (MediaPipe Face Mesh), with no manual tagging.
- **Random themed adornments** — each detected face is given a random theme and
  decorated using its facial landmarks (eyes, mouth, top of head, chin).
- **Adornments track the face** — they scale with face size and rotate to
  follow a tilted head.
- **Download your portrait** — the composed image is returned in the same
  format (JPEG/PNG) you uploaded.
- **Private by construction** — all processing is in memory; nothing is written
  to disk and no request ever leaves the machine.
- **Responsive UI** — single-column on mobile (320–767 px), multi-column on
  desktop (≥ 768 px).
- **Runs offline** — the AI models are bundled into the Docker image at build
  time, so there is no runtime download.

## Themes

| Theme          | Adornments                                              |
| -------------- | ------------------------------------------------------- |
| `calavera`     | Sugar-skull eye/nose/grin decoration + forehead marigold |
| `sombrero`     | Charro sombrero + curled mustache                       |
| `flower_crown` | Cempasúchil (marigold) flower crown                     |
| `catrina`      | La Catrina feathered veil + stitched lips               |
| `papel_picado` | Decorative cut-paper banner (full-frame overlay)        |
| `marigold_path`| Marigold-petal overlay + flower crown                   |
| `mariachi`     | Mustache + bow tie + sombrero                           |
| `monarch`      | Monarch butterfly above the head                        |

Each theme is a folder under `static/adornments/<theme>/` holding one or more
transparent PNG assets plus a `theme.json` describing how each asset is
anchored, scaled, offset, and rotated. **You can add or replace themes without
touching the code** — drop a new folder with PNGs + a `theme.json` and restart.

Example `theme.json`:

```json
{
  "name": "sombrero",
  "assets": [
    {
      "file": "sombrero.png",
      "anchor": "above_head",
      "scale_factor": 2.8,
      "offset_ratio": [0.0, -0.25],
      "rotate_with_face": true
    }
  ]
}
```

Valid `anchor` values: `mouth`, `above_head`, `behind_head`, `full_frame`,
`eyes`, `chin`.

## Tech stack

- **Python / Flask** — thin HTTP layer, served by **gunicorn**.
- **MediaPipe** (Face Mesh) — local face detection + 468-point facial landmarks.
- **Pillow** — image decode/encode, scaling, rotation, alpha compositing.
- **OpenCV** (`opencv-python-headless`) + **NumPy** — image-array handling that
  feeds the detector.
- **Vanilla JavaScript** frontend (no framework) + responsive CSS.
- **Docker** + **docker-compose** — single-service stack, developed under WSL.

## Architecture

The code is a thin Flask HTTP layer over pure, independently testable domain
modules that know nothing about Flask.

```
Browser (upload)
      │  POST /process (multipart)
      ▼
app.py ── validate ──▶ validation.py   (size / format / decode / dimensions)
      │
      ├── detect ─────▶ detection.py    (MediaPipe Face Mesh → faces+landmarks)
      │
      ├── assign ─────▶ composition.py  (random theme per face)
      │
      ├── compose ────▶ composition.py  (scale/rotate/alpha-composite PNGs)
      │
      └── encode ─────▶ adornments.py   (encode result → bytes, same format)
      ▼
Browser (display + download)
```

Every upload and result buffer is released in a `try/finally` block on every
path — success, validation failure, no-face, timeout — so nothing persists.

## Project structure

```
desafio5/
├── app.py                 # Flask factory + routes (GET /, POST /process)
├── validation.py          # In-memory upload validation
├── detection.py           # MediaPipe Face Mesh wrapper + warm-up
├── composition.py         # Theme assignment + adornment compositing
├── adornments.py          # Loads the Adornment_Set, encodes the result
├── templates/
│   └── index.html         # Single-page upload UI
├── static/
│   ├── app.js             # Vanilla-JS uploader (fetch + blob result)
│   ├── style.css          # Responsive stylesheet
│   └── adornments/        # One folder per theme (PNG + theme.json)
│       └── generate_placeholders.py  # Regenerates the adornment art
├── tests/                 # Test suite
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── SUBMISSION.md          # Hacktoberfest submission write-up
└── README.md
```

## Prerequisites

- **WSL 2** (Windows Subsystem for Linux, version 2). WSL 1 is not sufficient.
- **Docker** with the **Docker Compose v2** plugin — either Docker Desktop with
  WSL 2 integration enabled, or Docker Engine inside WSL 2 with the
  `docker compose` v2 plugin.

No model download or extra setup is needed: the MediaPipe models are baked into
the image at build time.

## Run it

From the `desafio5/` directory:

```bash
docker compose up --build
```

Then open **http://localhost:5000**.

Stop with `Ctrl+C`, or `docker compose down` from the same directory.

## Usage

1. Open **http://localhost:5000**.
2. Choose exactly one **JPEG or PNG** photo (up to 10 MB) with one or more faces.
3. Click **Create portrait**. A progress indicator appears while the photo is
   processed locally.
4. The composed image — each detected face given a random Día de los Muertos
   theme — appears in the result panel.
5. Click **Download image** to save it (same format as the upload).

If no face is detected, or the file is not a valid JPEG/PNG within the size
limit, the app shows a clear message and stays ready for another upload without
reloading the page.

## Limits & behavior

- **Accepted formats:** JPEG and PNG only.
- **Max upload size:** 10 MB (10,485,760 bytes).
- **Supported dimensions:** 64–8000 px per side.
- **Max faces per photo:** 20.
- **Processing budget:** 30 s (returns a timeout message if exceeded).
- Faces whose landmarks can't be computed are skipped while the rest are still
  decorated.

## Development

Run the test suite (inside the container or a local environment with the
dependencies installed):

```bash
# Inside the running container
docker compose exec web python -m pytest

# Or locally, after: pip install -r requirements.txt
pytest
```

Regenerate the adornment art after editing `generate_placeholders.py`:

```bash
cd static/adornments
python generate_placeholders.py
```

## Privacy

Photos are processed entirely on the local machine and held only in memory for
the duration of the request. The app makes **no outbound network requests** with
your image, writes **nothing to disk**, and discards every buffer when the
request completes. The face-detection model runs on-device and is bundled in the
image, so the app works fully offline.

## License

See the repository root for license information.
