# OpenAI Pay Long Link

Standalone tool for generating a hosted payment long link from a ChatGPT access token.

## Features

- Generate ChatGPT Plus payment links (hosted, PayPal, GoPay)
- Dual proxy support for flexible IP management
- Automatic retry and fallback mechanisms
- Real-time task logging
- Asynchronous task processing

## Run

```powershell
cd openai_pay_long_link
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

## Docker

```bash
cd openai_pay_long_link
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

## Proxy Configuration

The server supports **two independent proxies** for different stages of the payment flow:

### 1. Approval Proxy (Default: US Region)
Used for ChatGPT approval requests. This proxy handles the approval stage where ChatGPT validates the payment attempt.

**Priority:**
1. User-provided proxy in UI (highest priority)
2. Environment variable `OPENAI_PAY_DEFAULT_PROXY`
3. Hardcoded default: `http://192.168.67.148:7080`

### 2. Payment Proxy (Default: Japan Region)
Used for Stripe API calls and PayPal/GoPay link extraction. This handles the entire payment flow including checkout creation and provider redirect extraction.

**Priority:**
1. User-provided proxy in UI (highest priority)
2. Environment variable `OPENAI_PAY_PROVIDER_PROXY`
3. Hardcoded default: `socks5://192.168.67.148:7897`

### SOCKS5 Support

Both proxies support HTTP, HTTPS, and SOCKS5 protocols. The payment proxy uses SOCKS5 by default for better HTTPS support and to avoid TLS handshake issues.

When HTTP proxies encounter TLS errors (curl: 35), the system automatically falls back to SOCKS5 proxy for redirect tracking.

### Environment Variables

Override default proxies at deployment:

```bash
# Approval proxy (ChatGPT approval stage)
export OPENAI_PAY_DEFAULT_PROXY="http://your-us-proxy:7890"

# Payment proxy (Stripe API + provider extraction)
export OPENAI_PAY_PROVIDER_PROXY="socks5://your-jp-proxy:7897"

# GoPay-specific proxy (optional)
export OPENAI_PAY_GOPAY_PROVIDER_PROXY="socks5://your-id-proxy:7897"

# SOCKS5 fallback proxy
export OPENAI_PAY_SOCKS_PROXY="socks5://your-proxy:7897"
```

Set any proxy to an empty value to use direct outbound network.

## API

### Synchronous Endpoint

```http
POST /api/long-link
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "approvalProxy": "http://127.0.0.1:7890",
  "paymentProxy": "socks5://127.0.0.1:7897",
  "billing_country": "US",
  "payment_locale": "en",
  "link_type": "paypal",
  "stripe_publishable_key": ""
}
```

### Asynchronous Endpoint (Recommended)

```http
POST /api/long-link-async
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "approvalProxy": "",
  "paymentProxy": "",
  "billing_country": "US",
  "payment_locale": "en",
  "link_type": "paypal"
}

Response: {"task_id": "uuid"}
```

Poll for status:

```http
GET /api/task-status/{task_id}

Response: {
  "status": "running|completed|error",
  "logs": ["..."],
  "result": {...}
}
```

## Link Types

- **`hosted`**: Normal payment long link, defaults to `US/USD`; country remains selectable.
- **`paypal`**: PayPal redirect extraction, checkout locked to `US/USD`, uses a Japan billing address.
- **`gopay`**: GoPay redirect extraction, checkout locked to `ID/IDR`, uses an Indonesia billing address.

For `paypal` and `gopay`, if Stripe provider redirect extraction fails but the hosted checkout URL exists, the API falls back to the hosted long link and returns `fallback: true` plus `provider_error`.

**Note:** Accounts with active USD checkout/subscription state may be blocked by Stripe from creating an IDR checkout (GoPay).

## Payment Flow

### For PayPal/GoPay Links:

1. **Create Checkout** (ChatGPT API) → uses Payment Proxy
2. **Initialize Stripe Payment Page** → uses Payment Proxy  
3. **Create Payment Method** (PayPal/GoPay) → uses Payment Proxy
4. **Confirm Payment** (Stripe API) → uses Payment Proxy
5. **ChatGPT Approval** (if required) → uses Approval Proxy (with IP rotation retry)
6. **Poll Redirect URL** (Stripe API) → uses Payment Proxy
7. **Track External Redirect** → HTTP proxy first, auto-fallback to SOCKS5 on TLS errors

The server creates a ChatGPT checkout, calls Stripe API:

```text
POST https://api.stripe.com/v1/payment_pages/{cs_id}/init
POST https://api.stripe.com/v1/payment_methods
POST https://api.stripe.com/v1/payment_pages/{cs_id}/confirm
```

Then it extracts `redirect_to_url` from the response and follows redirects to get the final PayPal/GoPay URL.

For hosted links, it reads `stripe_hosted_url` and changes:

```text
https://checkout.stripe.com → https://pay.openai.com
```

## Retry & Fallback Mechanisms

- **Connection timeout**: Auto-retry up to 3 times for transient network errors
- **Approval blocked**: Retry up to 30 times with session rebuilding (forces proxy IP rotation)
- **TLS errors**: Automatic fallback from HTTP proxy to SOCKS5 proxy
- **Provider extraction failure**: Graceful fallback to hosted long link

## Dependencies

- `fastapi` - Web framework
- `uvicorn` - ASGI server  
- `requests[socks]` - HTTP client with SOCKS support
- `curl_cffi` - Optional for better TLS fingerprinting
- `pydantic` - Data validation
