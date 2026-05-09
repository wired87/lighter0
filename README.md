# lighter0

lighter0 is a single FastAPI app with:

1. AI cover-art generation (Gemini/Imagen).
2. A browser frontend (React in one HTML template).
3. Google sign-in + Firebase user sync.
4. Credit purchases with Stripe.
5. File artifact viewing/downloading.

## What the project does

### 1. Cover generation pipeline

The generator accepts an image source plus style parameters and creates output files in a run folder under `output/<uuid>/`.

Input source can be:

1. A local folder.
2. A local image file.
3. A direct image URL.

Pipeline flow:

1. Build prompt from theme/math/typography/colors/tags.
2. Generate image with Google model `imagen-4.0-ultra-generate-001`.
3. Save `img.jpg` and `args.json`.
4. Vectorize to `vec.eps`.
5. Run additional 3D/mesh processing (`conv_3d.py`).

Typical generated artifacts:

1. `img.jpg`
2. `vec.eps`
3. `out.svg`
4. `out.html` (3D preview)
5. `out.stl` (mesh export if trimesh works)
6. `animated.svg`
7. `brainmaster.json`
8. `args.json`

### 2. Frontend functionality

The web UI includes:

1. Google sign-in button.
2. User card (email, uid, credits, purchases).
3. Cover generator form.
4. Payment tab to buy credits.
5. Artifact panel with view/download links.
6. Free daily generation indicator.

### 3. Firebase usage

Firebase is used for:

1. Creating/fetching auth users from Google claims.
2. Reading/deducting/adding credits via realtime DB manager.
3. Uploading generated files to user folders in Firebase Storage.
4. Tracking free daily usage via custom claims (`last_free_generation_date`).

If Firebase admin credentials are invalid/missing, some flows fall back but sync/storage/billing features can be limited.

### 4. Stripe usage

Stripe supports credit purchases with three tiers:

1. `starter`
2. `professional`
3. `enterprise`

Implemented features:

1. Checkout session creation.
2. Checkout status lookup (paid/expired/stale/open normalization).
3. Webhook signature verification.
4. Local payment event log in `output/payments/events.jsonl`.

### 5. Email notifications

SMTP-based email sending is used for selected events (for example webhook updates or no-credit notices), controlled by env vars.

## API overview

Important routes (mounted under `/api` by `main.py`):

1. `POST /api/auth-user`
2. `GET /api/tiers`
3. `GET /api/user-profile`
4. `GET /api/free-generation-status`
5. `POST /api/checkout`
6. `GET /api/checkout/{session_id}`
7. `POST /api/payment/webhook`
8. `POST /api/process`
9. `GET /api/files/view/{file_path}`
10. `GET /api/files/download/{file_path}`

Legacy non-`/api` variants also exist for several endpoints.

## Project layout (simple)

1. `main.py`: Starts combined app and mounts API + frontend.
2. `server.py`: Core API (generation, auth, billing, file serving).
3. `frontend.py`: React UI served by FastAPI.
4. `gem.py`: Generation CLI + pipeline.
5. `conv_3d.py`: SVG/mesh/3D helper processing.
6. `payment/stripe.py`: Stripe logic.
7. `fb_core/db_admin.py`: Firebase admin helper.
8. `frontend/`: Static JS config/auth files.
9. `output/`: Generated files and payment logs.

## Local setup

1. Install dependencies

```bash
pip install -r r.txt
```

2. Configure environment

Use `.env.example` as reference. Minimum recommended variables:

```bash
GEM_API_KEY=...
STRIPE_API_KEY=...
STRIPE_WEBHOOK_SECRET=...
HOST=0.0.0.0
PORT=8000
```

For full features also configure:

1. Firebase credentials (valid `frontend/credentials.json` with Service Account JSON for admin initialization).
2. Stripe publishable key and tier prices.
3. SMTP credentials for notifications.

3. Run

```bash
python main.py
```

4. Open

1. App: `http://localhost:8000/`
2. API docs: `http://localhost:8000/api/docs`

## Docker

Build and run:

```bash
docker build -t lighter0 .
docker run --rm -p 8080:8080 --env-file .env lighter0
```

Container command is `python main.py` and default container port is `8080`.

## Notes

1. Generation and payment logs are written locally (`output/`).
2. File serving is restricted to files inside the output directory.
3. Credit deduction happens only after validated artifacts exist.


