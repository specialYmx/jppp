# JPPP

Local FastAPI tool for creating ChatGPT payment checkout links and checking the
two outbound proxy stages used by the flow.

## Features

- Hosted payment long-link generation.
- PayPal / GoPay provider redirect extraction with hosted-link fallback.
- Two-stage proxy routing:
  - stage 1: checkout and approve.
  - stage 2: Stripe, provider setup, and redirect resolution.
- Stage IP check endpoint and UI button.
- Local Japanese identity data generator backed by a static Japan Post ZIP data
  export.
- Optional Chrome extension helper files in `源码/`.

## Run Locally

```powershell
cd C:\Users\ymx\Desktop\jppp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

The repository also contains a mirrored copy under `源码/`. In this workspace it
is commonly run as a second local service:

```powershell
cd C:\Users\ymx\Desktop\jppp\源码
.\.venv\Scripts\Activate.ps1
uvicorn app:app --host 127.0.0.1 --port 8788
```

Open:

```text
http://127.0.0.1:8788
```

## Docker

```bash
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8787
```

Stop:

```bash
docker compose down
```

## Proxy Setup

The UI has two proxy fields.

For the current local setup:

```text
阶段1代理: http://127.0.0.1:7890
阶段2代理: http://127.0.0.1:10808
```

Expected routing:

```text
checkout/create = stage 1
approve         = stage 1
Stripe/provider = stage 2
billing_details = payment-method specific address data
```

PayPal / GoPay provider extraction only runs when Stripe init reports
`due_amount = 0`. If Stripe reports a non-zero amount such as `2000`, the app
stops provider extraction, returns the hosted checkout fallback, and shows the
non-zero amount in the `0元资格` field.

If only `checkoutProxy` is set and it contains a `region-JP` style proxy string,
the server can derive the provider stage by replacing the region with `region-US`
for PayPal. For two local tunnel apps, fill both fields explicitly.

## Environment Variables

```text
OPENAI_PAY_DEFAULT_PROXY
OPENAI_PAY_PROVIDER_PROXY
OPENAI_PAY_GOPAY_PROVIDER_PROXY
```

`OPENAI_PAY_DEFAULT_PROXY` is the built-in fallback when no proxy is submitted.
`OPENAI_PAY_PROVIDER_PROXY` overrides the PayPal Stripe/provider stage.
`OPENAI_PAY_GOPAY_PROVIDER_PROXY` overrides the GoPay Stripe/provider stage.

## Stage IP Check

The `检测阶段 IP` button calls:

```http
GET /api/stage-ips
```

It verifies the effective stage 1 and stage 2 exit IPs and reports whether both
stages are accidentally using the same IP.

For the intended PayPal setup:

```text
stage1 = JP
stage2 = US
same_ip = false
```

The button only checks the proxy exits. It does not create checkout sessions.

## API

```http
POST /api/long-link
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "link_type": "paypal",
  "checkoutProxy": "http://127.0.0.1:7890",
  "paymentProxy": "http://127.0.0.1:10808",
  "billing_country": "US",
  "checkout_ui_mode": "hosted",
  "payment_locale": "en",
  "stripe_publishable_key": "",
  "device_id": "",
  "user_agent": ""
}
```

## Link Types

- `hosted`: normal hosted checkout long link.
- `paypal`: PayPal redirect extraction; checkout is locked to `US/USD`.
- `gopay`: GoPay redirect extraction; checkout is locked to `ID/IDR`.

For provider extraction failures, the API returns the hosted checkout URL when
available and includes:

```json
{
  "fallback": true,
  "provider_error": "..."
}
```

## Japanese Address Data

Japanese address generation loads:

```text
public/jpn-addresses.json
源码/public/jpn-addresses.json
```

The JSON was generated from Japan Post official ZIP data:

```text
https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip
```

The generated local dataset contains 1410 records across 47 prefectures. Each
record keeps these fields from the same source row:

```text
zip
prefectJa
prefectEn
streetJa
streetEn
```

This avoids mixing a ZIP code from one prefecture with a street from another.

## Git Ignore Policy

The repository tracks source, static assets, Docker files, requirements, and the
generated Japanese address JSON.

The following local runtime artifacts are intentionally ignored:

```text
.venv/
__pycache__/
*.pyc
*.log
```

This keeps virtual environments, Python bytecode, and uvicorn/server logs out of
GitHub. The current push excludes files such as:

```text
jppp-8787.out.log
jppp-8787.err.log
uvicorn.out.log
uvicorn.err.log
源码/uvicorn-8788.out.log
源码/uvicorn-8788.err.log
```

## Repository

Remote:

```text
https://github.com/specialYmx/jppp.git
```
