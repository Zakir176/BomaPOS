# BomaPOS Backend (FastAPI + PostgreSQL + Alembic + Multi-Tenant RLS)

## Prerequisites
- Python 3.11+
- PostgreSQL 15+

Install dependencies:
```bash
pip install -r backend/requirements.txt
```

## Environment & Role Configuration
Copy `.env.example` at the repository root to `.env`.

To guarantee PostgreSQL Row Level Security (`FORCE ROW LEVEL SECURITY`) cannot be bypassed by a superuser or table owner, the application connects at runtime as a dedicated non-superuser, non-owner role `bomapos_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`), while Alembic migrations run via `ADMIN_DATABASE_URL` (`postgres`):
```env
DATABASE_URL=postgresql+psycopg://bomapos_app:bomapos_app@localhost:5432/bomapos
ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bomapos
TEST_DATABASE_URL=postgresql+psycopg://bomapos_app:bomapos_app@localhost:5432/bomapos_test
TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bomapos_test
JWT_SECRET=change-me-to-a-secure-random-secret-at-least-32-chars-long
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TRUSTED_PROXY_COUNT=0
LENCO_MODE=mock
LENCO_API_TOKEN=replace-with-your-lenco-secret-api-token
LENCO_API_BASE_URL=https://api.lenco.co/access/v2
```

Create the development and test databases in PostgreSQL:
```bash
createdb -U postgres bomapos
createdb -U postgres bomapos_test
```

## Database Migrations & Seeding
Run Alembic migrations (which create the schema, composite tenant constraints, RLS policies, and the `bomapos_app` role):
```bash
alembic -c backend/alembic.ini upgrade head
```

Seed two isolated tenants (`aunts-lusaka` and `boma-kitwe`) with overlapping usernames (`aunt`, `cashier1`) and menu item names:
```bash
python backend/seed.py
```

### Reverse Proxy & Client IP Trust (`TRUSTED_PROXY_COUNT`)
To prevent client IP spoofing in login rate limiting, BomaPOS uses `TRUSTED_PROXY_COUNT` (default `0`):
- When `0`: `X-Forwarded-For` is ignored completely and the direct socket client IP (`request.client.host`) is used.
- When `N > 0`: the backend extracts the Nth IP entry counting from the **right** of `X-Forwarded-For` (the entry appended by your trusted reverse proxy infrastructure).
- If there are fewer than N entries in `X-Forwarded-For`, it falls back safely to `request.client.host`.
- Leftmost entries provided by untrusted clients are never used.

## Running the Dev Server
```bash
uvicorn main:app --app-dir backend --reload --port 8000
```

## Lenco Webhook Configuration & Testing with a Tunnel
1. **Set Live/Sandbox Credentials**:
   Set `LENCO_MODE=live` and `LENCO_API_TOKEN=<your-lenco-secret-key>` in `.env`.
2. **Start a Local HTTPS Tunnel**:
   Expose your local FastAPI backend (`localhost:8000`) over HTTPS using `ngrok` or Cloudflare Tunnel (`cloudflared`):
   ```bash
   # Option A: ngrok
   ngrok http 8000

   # Option B: Cloudflare Tunnel
   cloudflared tunnel --url http://localhost:8000
   ```
3. **Register the Webhook URL in Lenco Dashboard**:
   Copy the public HTTPS forwarding URL from the tunnel (e.g. `https://<tunnel-id>.ngrok-free.app`) and set the Webhook URL in your Lenco Dashboard (**Developers -> Webhooks**) to:
   ```text
   https://<tunnel-id>.ngrok-free.app/api/webhooks/lenco
   ```
4. **How Webhook Verification & Reconciliation Work**:
   - Lenco signs raw webhook request bodies using `HMAC-SHA512` keyed with `sha256(LENCO_API_TOKEN).hexdigest()` and sends the hex digest in the `X-Lenco-Signature` header.
   - `POST /api/webhooks/lenco` verifies `X-Lenco-Signature` against the raw request bytes before parsing JSON, resolves the order's `tenant_id` via `resolve_tenant_for_lenco_ref`, binds the DB session to that tenant under RLS, re-fetches the collection from Lenco (`GET /collections/status/{reference}`), and verifies that `status`, `amount`, and `currency` (`ZMW`) match the order before marking it `paid` and decrementing drink stock.
   - If a webhook is missed, owners can trigger `POST /api/payments/reconcile` (or run `reconcile_all_tenants_stuck_orders()`), which queries Lenco in lock-free batches of 50 and settles or expires attempts (`> 30 minutes` and confirmed not-successful at Lenco become `expired`, while late webhooks still settle `expired` orders).
5. **Host Scheduler Cron (`POST /internal/reconcile`)**:
   - Configure the host scheduler (e.g., `cron`, `systemd` timer, or cloud scheduler) to call `POST /internal/reconcile` every **5 minutes** with the `X-Cron-Secret` header matching `CRON_SECRET`:
     ```bash
     # Crontab entry (every 5 minutes)
     */5 * * * * curl -fsS -X POST http://127.0.0.1:8000/internal/reconcile -H "X-Cron-Secret: ${CRON_SECRET}" >/dev/null
     ```
   - When `LENCO_MODE=live`, the application refuses to start if `CRON_SECRET` is missing.

## Running the Test Suite
The test suite uses `TEST_DATABASE_URL` (`bomapos_app`), `TEST_ADMIN_DATABASE_URL` (`postgres`), and `LENCO_MODE=mock`, automatically applies `alembic upgrade head`, seeds both tenants, and verifies core POS workflows, atomic stock deduction, money conversion, `Africa/Lusaka` timezone grouping, JWT auth, Lenco webhook HMAC verification, reconciliation, and cross-tenant + RLS isolation:
```bash
pytest backend -v
```
