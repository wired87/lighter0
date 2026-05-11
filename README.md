# lighter0

lighter0 is a single FastAPI app with:

1. AI cover-art generation (Gemini/Imagen).
2. A browser frontend (React in one HTML template).
3. Google sign-in + Firebase user sync.
4. Credit purchases with Stripe.
5. File artifact viewing/downloading.

## New functionality (recent updates)

This section summarizes the latest behavior in plain language.

### Frontend and generation UX

1. The generation result is persisted in the browser (local store + localStorage).
2. The latest successful process payload remains available after page reload and navigation.
3. Generator and payment are displayed in one page flow (payment is below generator).
4. Generated artifacts are rendered from the persisted latest process response.

### Payment flow UX

1. Checkout opens in a new tab/window (`_blank`).
2. Stripe success/failed return pages are dedicated endpoints:
1. `/checkout/success`
2. `/checkout/failed`
3. Both return pages show the same centered message:
1. `Process finished, please close this window.`

### Payment webhook feedback in frontend

1. Backend provides latest webhook status via `GET /api/payment/webhook-latest`.
2. Frontend polls this endpoint for authenticated users.
3. Frontend shows toast notifications for successful or failed payment webhook outcomes.
4. Duplicate toasts are prevented using a locally stored last-seen webhook event id.

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
4. Tracking free daily usage and per-try timestamps in Realtime DB (`usage/free_daily` and `usage/workflow_executions`).

Billing/free-try validation is enforced in the generation engine (`POST /api/process`):

1. Free tries are checked server-side against `FREE_DAILY_TRIES`.
2. If no free try is available (or free mode is not requested), credits are validated against `COST_CREDITS_SINGLE_EXECUTION`.
3. After successful output validation, either free-try usage timestamps are updated or credits are deducted.

Additional production hardening in API validation layers:

1. Input identity validation for `user_id` and `user_email` in billing/process routes.
2. Upload limits for pasted image count/size and total payload volume.
3. Stack ZIP limits (file count and total bytes) to mitigate resource exhaustion.
4. Public output file guard blocks sensitive paths (for example `output/payments/*`).
5. Optional host allow-list for checkout redirect host validation.

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

#### Webhook stability checklist (Codespaces)

Use this checklist when Stripe shows repeated delivery failures:

1. Ensure the app port is public (required for Stripe callbacks):

```bash
gh codespace ports visibility 8000:public -c "$CODESPACE_NAME"
gh codespace ports -c "$CODESPACE_NAME"
```

Expected: port `8000` has visibility `public`.

2. Configure Stripe endpoint to one of these URLs:

1. `https://<codespace>-8000.app.github.dev/payment/webhook`
2. `https://<codespace>-8000.app.github.dev/api/payment/webhook`

3. Verify your app responds publicly (without signature this must be 400, not 401):

```bash
curl -i -X POST "https://<codespace>-8000.app.github.dev/api/payment/webhook" \
	-H "Content-Type: application/json" \
	--data '{}'
```

Expected: `400` with `{"detail":"Missing Stripe signature header."}`.
If you see `401` with `www-authenticate: tunnel`, the port is not publicly reachable yet.

4. Ensure webhook secret matches the configured Stripe endpoint exactly:

1. Stripe Dashboard -> Developers -> Webhooks -> select endpoint.
2. Copy that endpoint secret (`whsec_...`).
3. Set `STRIPE_WEBHOOK_SECRET` in `.env` to the same value.

5. Resend the failed event from Stripe dashboard.

6. Confirm processing in app logs and `output/payments/events.jsonl`.

7. Use the operator self-test endpoint to verify config without Stripe payloads:

```bash
curl -H "X-Admin-Key: $ADMIN_SECRET_KEY" \
	"http://127.0.0.1:8000/api/admin/webhook-selftest"
```

Expected: JSON with the active base URL, both webhook URLs, and the expected unauthenticated response of `400 Missing Stripe signature header.`

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
COST_CREDITS_SINGLE_EXECUTION=1
FREE_DAILY_TRIES=1
MAX_PASTED_IMAGES=8
MAX_PASTED_IMAGE_BYTES=8388608
MAX_TOTAL_PASTED_BYTES=33554432
MAX_STACK_FILE_COUNT=200
MAX_STACK_ZIP_BYTES=104857600
MAX_RENDER_DIMENSION=4096
TRUST_PROXY_HEADERS=false
ALLOWED_PUBLIC_HOSTS=example.com,api.example.com
ENFORCE_ID_TOKEN_AUTH=true
CHECK_REVOKED_ID_TOKEN=true
WEBHOOK_PROCESSING_TTL_SECONDS=300
CORS_ALLOWED_ORIGINS=https://your-domain.example
RATE_LIMIT_PROCESS_PER_MINUTE=10
RATE_LIMIT_CHECKOUT_PER_HOUR=5
ADMIN_SECRET_KEY=replace_with_long_random_secret
PAYMENT_EVENTS_MAX_SCAN_LINES=5000
PAYMENT_EVENTS_CACHE_TTL_SECONDS=3
CHECKOUT_STATUS_CACHE_TTL_SECONDS=4
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

## Dev TODO (hosting + git workflow)

Use this checklist for the next deployment handover.

1. Verify production hosting setup
1. Configure public base URL and webhook endpoint routing.
2. Validate Stripe webhook delivery to `/payment/webhook` or `/api/payment/webhook`.
3. Verify Firebase admin credentials and credit mutation paths in production.

2. Commit and push workflow
1. Commit and push all project source files to `lighter0` while respecting `.gitignore`.
2. `.env` must remain excluded in `lighter0` (already covered by `.gitignore`).
3. For `lighter1` (owner: `wired87`), only include `.env` if explicitly required for a private/internal mirror and after secret review/rotation approval.
4. Preferred safe default for `lighter1`: commit `.env.example` or sanitized config, not raw secrets.

3. Post-push validation
1. Run `python -m py_compile server.py frontend.py`.
2. Rebuild frontend bundle: `npx esbuild frontend/app.jsx --bundle --format=iife --outfile=frontend/app.js`.
3. Smoke-test auth, process generation, checkout open-in-new-tab, and webhook toast behavior.


