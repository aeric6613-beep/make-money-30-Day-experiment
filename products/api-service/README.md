# ToolPipe API

Free developer utility APIs. 55+ endpoints for QR codes, text analysis, PDF processing, image manipulation, DNS lookup, and more.

## Quick Start

No API key required for the free tier.

```bash
# Generate a QR code
curl -X POST https://toolpipe.dev/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"data": "https://example.com"}'

# Extract metadata from a URL
curl "https://toolpipe.dev/meta/extract?url=https://github.com"

# Analyze text
curl -X POST https://toolpipe.dev/text/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Your content here"}'
```

## Run the API and revenue dashboard locally

The dashboard reads paid USD records from `data/payments.db`; it does not fetch a live wallet balance or subtract fees and expenses.

```bash
cd products/api-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export REVENUE_DASHBOARD_KEY="choose-a-long-random-secret"
# Optional: enable payment-admin endpoints with a different secret.
export TOOLPIPE_ADMIN_KEY="choose-a-different-long-random-secret"
python main.py
```

Open `http://localhost:8080/revenue-dashboard` and enter the dashboard key. In Codespaces, forward port `8080` and use its forwarded URL. Keep both keys private and use HTTPS if exposing the service publicly. The dashboard API returns only aggregate totals and recent paid payment details without customer email addresses. Admin payment endpoints remain disabled unless `TOOLPIPE_ADMIN_KEY` is set; use a different key from the dashboard key.

`run.sh` starts the separate agent loop; it is not the API or dashboard server. Avoid launching autonomous agents with permission-skipping enabled unless you have reviewed and intentionally accepted that behavior.

## Run persistently with Docker Compose

This deployment keeps the API and its sibling-service databases in Docker-managed volumes, excludes local databases and secrets from the image, and binds the service to localhost. It is suitable for a private server or for use behind a TLS reverse proxy; it is not a public HTTPS deployment by itself.

```bash
cd products/api-service
cp docker.env.example .env
```

Generate a dashboard key with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and put it in `.env` as `REVENUE_DASHBOARD_KEY`. Keep `.env` private and never paste provider secrets into chat or commit them.

Hosted checkout is supported through OxaPay or NOWPayments. Before enabling it, use an account you control and configure:

- `PAYMENTS_PUBLIC_BASE_URL`: the public HTTPS origin only, such as `https://api.example.com` (no path or trailing route).
- OxaPay: `OXAPAY_MERCHANT_KEY`. The app creates invoices through OxaPay's v1 invoice API and verifies callbacks with the HMAC-SHA512 signature in the `HMAC` header, using the merchant key.
- NOWPayments: both `NOWPAYMENTS_API_KEY` and `NOWPAYMENTS_IPN_SECRET`. The IPN secret is distinct from the API key; callbacks are verified using `x-nowpayments-sig`.

The app sends provider callbacks to `/payments/webhook/oxapay` or `/payments/webhook/nowpayments` and activates access only after a signed, final, provider-confirmed payment for the invoice amount. A browser redirect is not proof of payment. Each successful Pro or Enterprise payment grants 30 days; customers must renew manually, and duplicate callbacks do not extend access twice. After confirmation, the high-entropy order link returns the API key with `Cache-Control: no-store`; keep that link private. Upgrading an existing account requires its current API key. Expired plans are downgraded on the next key check. Direct wallet verification is disabled because it cannot safely tie a transaction to an invoice, and credit purchases remain unavailable until their provider fulfillment flow is implemented. With no provider credentials configured, `/payments/create` returns HTTP 503; configure credentials and the public URL before taking payments. Test with the provider's sandbox first, then verify a real low-value live transaction before announcing the service as accepting payments.

Provider accounts, merchant approval, credentials, production hosting, and an actual customer payment are external requirements; this repository cannot create or verify those on your behalf. Codespaces URLs are temporary and are not an always-on production host.

## Deploy on Render

The root `render.yaml` defines a Docker web service with a 1 GB persistent disk mounted at `/var/data`. SQLite databases for the API, URL shortener, and uptime monitor use that disk through `TOOLPIPE_DATA_DIR`. The service uses Render's `0.5c-512mb` compute plan; a persistent disk requires a paid web service, so review current Render pricing before creating the Blueprint. The Blueprint has not been deployed.

To deploy, push this repository to GitHub, create a Render Blueprint from it, and enter a strong `REVENUE_DASHBOARD_KEY` when prompted. After the first deploy, set `PAYMENTS_PUBLIC_BASE_URL` to the service's HTTPS origin. Add provider credentials only in Render's environment settings; checkout stays unavailable until a provider and public URL are configured. Verify health at `/health`, then test provider callbacks and a low-value payment before announcing production payments. Render's persistent disk is attached to one instance, so keep the service at one instance and back up the data regularly.

**Security launch blocker:** this repository's public Git history contains a previously tracked wallet private-key file. Treat that key as compromised if it ever held funds: do not use it, move any remaining funds to a newly generated wallet, and remove the secret from Git history before deployment. Deleting the file from the latest commit or excluding it from the Docker image does not remove historical copies.

```bash
docker compose up -d --build
docker compose logs -f api
```

Open `http://localhost:8080/revenue-dashboard`. Use `docker compose down` to stop the service without deleting its database volume. Compose restarts the container after a process exit, but the Docker host must remain on. For public access, use an always-on host, TLS, persistent storage, backups, and provider-approved production payment credentials.

## Endpoints

### Core API
- `POST /qr/generate` - Generate QR codes (PNG)
- `GET /meta/extract?url=` - Extract Open Graph metadata
- `POST /text/analyze` - Word count, readability, sentiment
- `POST /markdown/to-html` - Markdown to HTML
- `POST /hash/generate` - MD5, SHA256, SHA512
- `POST /image/resize` - Resize images
- `POST /image/convert` - Convert image formats
- `POST /json/to-csv` - JSON to CSV
- `GET /uuid/generate` - Generate UUIDs
- `GET /dns/lookup?domain=` - DNS records
- `GET /color/convert?hex=` - Color conversion
- `POST /base64` - Base64 encode/decode

### PDF Tools
- `POST /pdf/merge` - Merge PDFs
- `POST /pdf/split` - Split PDF by pages
- `POST /pdf/compress` - Compress PDF
- `POST /pdf/rotate` - Rotate pages
- `POST /pdf/watermark` - Add watermark
- `POST /pdf/protect` - Password protect
- `POST /pdf/extract-text` - Extract text

### URL Shortener
- `POST /s/create` - Create short URL
- `GET /s/{code}` - Redirect
- `GET /s/{code}/stats` - Click analytics

### Network Tools
- `GET /ip/lookup?ip=` - IP geolocation
- `GET /ip/my` - Your public IP
- `GET /down/check?url=` - Is website down?
- `GET /seo/analyze?url=` - SEO audit

## Rate Limits
- Free: 100 req/min
- Pro: 1,000 req/min ($9.99 per 30 days; manual renewal)
- Enterprise: Unlimited ($49.99 per 30 days; manual renewal)

## SDKs
Python and JavaScript client libraries in `../digital-products/api-starter-kit/`.
