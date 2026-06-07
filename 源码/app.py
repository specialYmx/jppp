from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

try:
    from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CurlCffiSession = None  # type: ignore


DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRac"
    "ViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
DEFAULT_TIMEOUT = 30
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DEFAULT_PROXY = os.getenv(
    "OPENAI_PAY_DEFAULT_PROXY",
    "http://dsgytrca-region-JP-sid--t-5:@us2.cliproxy.io:3010",
).strip()
PROVIDER_STAGE_PROXY = os.getenv("OPENAI_PAY_PROVIDER_PROXY", "").strip()
GOPAY_PROVIDER_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_GOPAY_PROVIDER_PROXY",
    "http://dsgytrca-region-ID-sid--t-5:udhhdhdhsjadsa@us2.cliproxy.io:3010",
).strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "6f8494a281"
US_BILLING_NAMES = [
    ("James", "Smith"),
    ("John", "Brown"),
    ("Michael", "Johnson"),
    ("Robert", "Miller"),
    ("David", "Davis"),
    ("William", "Wilson"),
]
US_BILLING_STREETS = [
    ("3110 Sunset Boulevard", "Los Angeles", "CA", "90026"),
    ("1200 Market Street", "San Francisco", "CA", "94102"),
    ("500 Main Street", "Austin", "TX", "78701"),
    ("88 Broadway", "New York", "NY", "10007"),
    ("1200 Peachtree St", "Atlanta", "GA", "30309"),
]
JAPAN_BILLING_NAMES = [
    ("Taro", "Yamada"),
    ("Hanako", "Sato"),
    ("Ken", "Suzuki"),
    ("Yui", "Takahashi"),
    ("Haruto", "Tanaka"),
]
JAPAN_BILLING_STREETS = [
    ("1-2-3 Shibuya", "Shibuya-ku", "Tokyo", "150-0002"),
    ("2-1-1 Namba", "Chuo-ku", "Osaka", "542-0076"),
    ("3-4-5 Sakae", "Naka-ku", "Aichi", "460-0008"),
    ("4-2-8 Hakata", "Hakata-ku", "Fukuoka", "812-0011"),
]
INDONESIA_BILLING_NAMES = [
    ("Budi", "Santoso"),
    ("Agus", "Wijaya"),
    ("Siti", "Rahma"),
    ("Dewi", "Lestari"),
    ("Rizky", "Pratama"),
]
INDONESIA_BILLING_STREETS = [
    ("Jl. Jend. Sudirman No. 1", "Jakarta", "DKI Jakarta", "10210"),
    ("Jl. MH Thamrin No. 10", "Jakarta", "DKI Jakarta", "10350"),
    ("Jl. Asia Afrika No. 8", "Bandung", "Jawa Barat", "40111"),
    ("Jl. Basuki Rahmat No. 5", "Surabaya", "Jawa Timur", "60271"),
]
COUNTRY_CURRENCY = {
    "AT": "EUR",
    "AU": "AUD",
    "BE": "EUR",
    "BR": "BRL",
    "CA": "CAD",
    "CH": "CHF",
    "CZ": "CZK",
    "DE": "EUR",
    "DK": "DKK",
    "ES": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "GB": "GBP",
    "HK": "HKD",
    "ID": "IDR",
    "IE": "EUR",
    "IN": "INR",
    "IT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "MX": "MXN",
    "MY": "MYR",
    "NL": "EUR",
    "NO": "NOK",
    "NZ": "NZD",
    "PH": "PHP",
    "PL": "PLN",
    "PT": "EUR",
    "SE": "SEK",
    "SG": "SGD",
    "TH": "THB",
    "TW": "TWD",
    "US": "USD",
    "VN": "VND",
}
LOCALE_MAP = {
    "de": ("de-DE", "de"),
    "en": ("en-US", "en"),
    "en-US": ("en-US", "en"),
    "es": ("es-ES", "es"),
    "fr": ("fr-FR", "fr"),
    "id": ("id-ID", "id"),
    "it": ("it-IT", "it"),
    "ja": ("ja-JP", "ja"),
    "ko": ("ko-KR", "ko"),
    "pt-BR": ("pt-BR", "pt-BR"),
    "zh-CN": ("zh-CN", "zh-CN"),
    "zh-TW": ("zh-TW", "zh-TW"),
}


class LongLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(..., alias="accessToken")
    proxy: str = ""
    checkout_proxy: str = Field(default="", alias="checkoutProxy")
    payment_proxy: str = Field(default="", alias="paymentProxy")
    stripe_publishable_key: str = ""
    billing_country: str = "US"
    checkout_ui_mode: str = "hosted"
    payment_locale: str = "en"
    link_type: str = "hosted"
    device_id: str = ""
    user_agent: str = ""


class ProxyStageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proxy: str = ""
    checkout_proxy: str = Field(default="", alias="checkoutProxy")
    payment_proxy: str = Field(default="", alias="paymentProxy")
    link_type: str = "paypal"


class LongLinkResponse(BaseModel):
    ok: bool
    cs_id: str
    processor_entity: str
    billing_country: str
    currency: str
    payment_locale: str
    link_type: str
    payment_method_type: str
    payment_method_id: str
    stripe_redirect_url: str
    provider_redirect_url: str
    fallback: bool = False
    provider_error: str = ""
    stripe_hosted_url: str
    long_url: str


def new_session() -> Any:
    if CurlCffiSession is not None:
        return CurlCffiSession(impersonate="chrome120")
    return requests.Session()


def effective_default_proxy(proxy: str = "") -> str:
    proxy_val = str(proxy or "").strip()
    if proxy_val.lower() in ("direct", "none"):
        return ""
    return proxy_val or DEFAULT_PROXY


def set_proxy_url(session: Any, proxy: str) -> None:
    proxy = str(proxy or "").strip()
    if not proxy:
        return
    proxy_dict = {"http": proxy, "https": proxy}
    if hasattr(session, "proxies") and isinstance(session.proxies, dict):
        session.proxies.update(proxy_dict)
    else:
        session.proxies = proxy_dict


def clear_proxy_url(session: Any) -> None:
    if hasattr(session, "proxies") and isinstance(session.proxies, dict):
        session.proxies.clear()
    else:
        session.proxies = {}


def set_proxy(session: Any, proxy: str) -> None:
    set_proxy_url(session, effective_default_proxy(proxy))


def proxy_for_region(proxy: str, region: str) -> str:
    proxy = str(proxy or "").strip()
    region = str(region or "").strip().upper()
    if proxy and region and "region-" in proxy:
        return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", proxy)
    return proxy


def checkout_stage_proxy(req: LongLinkRequest) -> str:
    explicit = str(req.checkout_proxy or req.proxy or "").strip()
    if explicit:
        return "" if explicit.lower() in ("direct", "none") else explicit
    return effective_default_proxy("")


def payment_stage_proxy(req: LongLinkRequest) -> str:
    explicit = str(req.payment_proxy or "").strip()
    if explicit:
        return "" if explicit.lower() in ("direct", "none") else explicit

    link_type = normalize_link_type(req.link_type)
    checkout_proxy = checkout_stage_proxy(req)
    base_proxy = checkout_proxy or effective_default_proxy("")

    if link_type == "gopay":
        return GOPAY_PROVIDER_STAGE_PROXY or proxy_for_region(base_proxy, "ID")
    if link_type == "paypal":
        return PROVIDER_STAGE_PROXY or proxy_for_region(base_proxy, "US")
    return base_proxy


def apply_provider_proxy(chatgpt: Any, proxy: str) -> None:
    if proxy:
        set_proxy_url(chatgpt, proxy)
    else:
        clear_proxy_url(chatgpt)


def currency_for_country(country: str) -> str:
    return COUNTRY_CURRENCY.get(str(country or "").upper(), "USD")


def normalize_country(country: str) -> str:
    country = str(country or "").strip().upper()
    return country if country in COUNTRY_CURRENCY else "US"


def normalize_link_type(link_type: str) -> str:
    value = str(link_type or "hosted").strip().lower()
    aliases = {
        "payment": "hosted",
        "pay": "hosted",
        "long": "hosted",
        "pp": "paypal",
        "paypal": "paypal",
        "gopy": "gopay",
        "gopay": "gopay",
    }
    return aliases.get(value, "hosted")


def effective_country(req: LongLinkRequest) -> str:
    link_type = normalize_link_type(req.link_type)
    if link_type == "paypal":
        return "US"
    if link_type == "gopay":
        return "ID"
    return normalize_country(req.billing_country)


def locale_parts(locale: str) -> tuple[str, str]:
    return LOCALE_MAP.get(str(locale or "").strip(), LOCALE_MAP["en"])


def find_token(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "token"):
            token = str(value.get(key) or "").strip()
            if token:
                return token
        for item in value.values():
            token = find_token(item)
            if token:
                return token
    if isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return ""


def extract_token_from_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    bearer_match = re.search(r"Bearer\s+([A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+(?:\.[A-Za-z0-9\-_=]+)?)", text)
    if bearer_match:
        return bearer_match.group(1).strip()
    jwt_match = re.search(r"(eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+(?:\.[A-Za-z0-9\-_=]+)?)", text)
    if jwt_match:
        return jwt_match.group(1).strip()
    return ""


def normalize_access_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    extracted = extract_token_from_text(token)
    if extracted:
        return extracted
    if token.startswith("{") or token.startswith("["):
        try:
            found = find_token(json.loads(token))
            if found:
                extracted = extract_token_from_text(found)
                return extracted or found
            return token
        except json.JSONDecodeError:
            extracted = extract_token_from_text(token)
            return extracted or token
    return token


def validate_header_value(name: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return cleaned
    if "\r" in cleaned or "\n" in cleaned:
        raise HTTPException(status_code=400, detail=f"{name} contains invalid newline characters")
    try:
        cleaned.encode("latin-1")
    except UnicodeEncodeError:
        raise HTTPException(status_code=400, detail=f"{name} contains non-ASCII/non-latin characters")
    return cleaned


def extract_processor_entity(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("processor_entity") or data.get("processorEntity")
    if direct:
        return str(direct).strip()
    for key in ("checkout_session", "session", "checkout", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_processor_entity(nested)
            if found:
                return found
    return ""


def build_chatgpt_session(req: LongLinkRequest) -> Any:
    access_token = normalize_access_token(req.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="accessToken is required")
    access_token = validate_header_value("accessToken", access_token)
    if "." not in access_token:
        raise HTTPException(status_code=400, detail="accessToken format is invalid; paste the raw JWT access token or session JSON")

    device_id = validate_header_value("device_id", req.device_id.strip() or str(uuid.uuid4()))
    user_agent = validate_header_value("user_agent", req.user_agent.strip() or DEFAULT_USER_AGENT)
    session = new_session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-US",
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    checkout_proxy = checkout_stage_proxy(req)
    if checkout_proxy:
        set_proxy_url(session, checkout_proxy)
    return session


def create_checkout(req: LongLinkRequest, chatgpt_session: Any | None = None) -> dict[str, Any]:
    billing_country = effective_country(req)
    currency = currency_for_country(billing_country)
    checkout_ui_mode = (req.checkout_ui_mode or "hosted").strip() or "hosted"
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {
            "country": billing_country,
            "currency": currency,
        },
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": checkout_ui_mode,
    }
    headers = {
        "Referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
    }
    response = (chatgpt_session or build_chatgpt_session(req)).post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=body,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        body_text = response.text[:500] if response.text else ""
        if "cannot combine currencies" in body_text.lower():
            raise HTTPException(
                status_code=409,
                detail=(
                    "GoPay needs an IDR checkout, but this Stripe customer already has active USD "
                    "checkout/subscription state. Use a fresh account/customer or wait for the USD "
                    "checkout state to expire; this cannot be bypassed in code."
                ),
            )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"checkout create failed: {body_text}",
        )

    data = response.json() or {}
    cs_id = data.get("checkout_session_id") or data.get("session_id") or data.get("id")
    if not cs_id or not str(cs_id).startswith("cs_"):
        raise HTTPException(status_code=502, detail=f"checkout response missing cs_id: {data}")
    return {
        "cs_id": str(cs_id),
        "processor_entity": extract_processor_entity(data),
        "billing_country": billing_country,
        "currency": currency,
    }


def stripe_init(cs_id: str, req: LongLinkRequest, proxy_override: str = "") -> dict[str, Any]:
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    browser_locale, elements_locale = locale_parts(req.payment_locale)
    stripe = new_session()
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        payment_proxy = payment_stage_proxy(req)
        if payment_proxy:
            set_proxy_url(stripe, payment_proxy)
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": "Asia/Shanghai",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"stripe init failed: {response.text[:500]}",
        )
    return response.json() or {}


def stripe_init_gopay_checksum(stripe: Any, cs_id: str, stripe_pk: str, req: LongLinkRequest) -> str:
    browser_locale, elements_locale = locale_parts(req.payment_locale)
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": "Asia/Shanghai",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "key": stripe_pk,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe gopay init failed: {response.text[:500]}")
    checksum = str((response.json() or {}).get("init_checksum") or "").strip()
    if not checksum:
        raise HTTPException(status_code=502, detail=f"stripe gopay init missing init_checksum: {response.text[:300]}")
    return checksum


def to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]

    parsed = urlsplit(url)
    if parsed.netloc.lower() == "checkout.stripe.com":
        return urlunsplit((parsed.scheme or "https", "pay.openai.com", parsed.path, parsed.query, parsed.fragment))
    return url


def processor_entity_for_country(country: str, processor_entity: str = "") -> str:
    entity = str(processor_entity or "").strip()
    if entity:
        return entity
    return "openai_llc" if str(country or "").upper() == "US" else "openai_ie"


def chatgpt_success_return_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    entity = processor_entity_for_country(country, processor_entity)
    return f"https://chatgpt.com/checkout/verify?stripe_session_id={cs_id}&processor_entity={entity}&plan_type=plus"


def stripe_checkout_long_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    return (
        f"https://checkout.stripe.com/c/pay/{cs_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url="
        f"{quote(chatgpt_success_return_url(cs_id, country, processor_entity), safe='')}"
    )


def stripe_confirm_return_url(cs_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = to_openai_pay_url(stripe_hosted_url) or stripe_checkout_long_url(
        cs_id,
        checkout["billing_country"],
        checkout.get("processor_entity", ""),
    )
    if "pay.openai.com/" in hosted_url or "checkout.stripe.com/" in hosted_url:
        parsed = urlsplit(hosted_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault(
            "success_return_url",
            chatgpt_success_return_url(
                cs_id,
                checkout["billing_country"],
                checkout.get("processor_entity", ""),
            ),
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return hosted_url


def expected_amount(init_payload: Any) -> str:
    if not isinstance(init_payload, dict):
        return "0"
    total_summary = init_payload.get("total_summary")
    if isinstance(total_summary, dict) and total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    invoice = init_payload.get("invoice")
    if isinstance(invoice, dict) and invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    line_items = init_payload.get("line_items")
    if isinstance(line_items, list):
        total = 0
        found = False
        for item in line_items:
            if isinstance(item, dict) and item.get("amount") is not None:
                try:
                    total += int(item.get("amount") or 0)
                    found = True
                except Exception:
                    pass
        if found:
            return str(total)
    return "0"


def stripe_context(cs_id: str, init_payload: dict[str, Any], req: LongLinkRequest) -> dict[str, Any]:
    _, elements_locale = locale_parts(req.payment_locale)
    return {
        "stripe_js_id": str(uuid.uuid4()),
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(init_payload.get("config_id") or uuid.uuid4()),
        "config_id": init_payload.get("config_id") or "",
        "init_checksum": init_payload.get("init_checksum") or "",
        "currency": str(init_payload.get("currency") or currency_for_country(effective_country(req))).lower(),
        "checkout_amount": expected_amount(init_payload),
        "locale": elements_locale,
    }


def billing_for_link_type(link_type: str) -> dict[str, str]:
    normalized = normalize_link_type(link_type)
    if normalized == "paypal":
        first_name, last_name = random.choice(JAPAN_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(JAPAN_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": "JP",
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    if normalized == "gopay":
        first_name, last_name = random.choice(INDONESIA_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(INDONESIA_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": "ID",
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    first_name, last_name = random.choice(US_BILLING_NAMES)
    line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first_name} {last_name}",
        "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
        "country": "US",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }


def build_stripe_session(req: LongLinkRequest, proxy_override: str = "") -> Any:
    stripe = new_session()
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        payment_proxy = payment_stage_proxy(req)
        if payment_proxy:
            set_proxy_url(stripe, payment_proxy)
    return stripe


def stripe_create_payment_method(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    billing: dict[str, str],
    payment_method_type: str,
    ctx: dict[str, Any],
) -> str:
    payment_method_type = normalize_link_type(payment_method_type)
    if payment_method_type == "gopay":
        body = {
            "billing_details[name]": billing.get("name") or "Budi Santoso",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "ID",
            "billing_details[address][line1]": billing.get("line1") or "Jl. Jend. Sudirman No. 1",
            "billing_details[address][city]": billing.get("city") or "Jakarta",
            "billing_details[address][postal_code]": billing.get("postal_code") or "10210",
            "billing_details[address][state]": billing.get("state") or "DKI Jakarta",
            "type": "gopay",
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        body = {
            "billing_details[name]": billing.get("name") or "John Doe",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "US",
            "billing_details[address][line1]": billing.get("line1") or "3110 Sunset Boulevard",
            "billing_details[address][city]": billing.get("city") or "Los Angeles",
            "billing_details[address][postal_code]": billing.get("postal_code") or "90026",
            "billing_details[address][state]": billing.get("state") or "CA",
            "type": "paypal",
            "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
            "referrer": "https://chatgpt.com",
            "time_on_page": str(random.randint(25000, 55000)),
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "2021",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
    response = stripe.post("https://api.stripe.com/v1/payment_methods", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe payment_methods failed: {response.text[:500]}")
    pm_id = str((response.json() or {}).get("id") or "")
    if not pm_id.startswith("pm_"):
        raise HTTPException(status_code=502, detail=f"stripe payment_methods bad response: {response.text[:300]}")
    return pm_id


def stripe_confirm(
    stripe: Any,
    cs_id: str,
    pm_id: str,
    stripe_pk: str,
    payment_method_type: str,
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
) -> dict[str, Any]:
    payment_method_type = normalize_link_type(payment_method_type)
    return_url = stripe_confirm_return_url(cs_id, checkout, stripe_hosted_url)
    if payment_method_type == "gopay":
        init_checksum = stripe_init_gopay_checksum(stripe, cs_id, stripe_pk, req)
        body = {
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": pm_id,
            "init_checksum": init_checksum,
            "version": "fed52f3bc6",
            "expected_amount": "0",
            "expected_payment_method_type": "gopay",
            "return_url": return_url,
            "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[locale]": locale_parts(req.payment_locale)[1],
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "client_attribution_metadata[client_session_id]": str(uuid.uuid4()),
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        body = {
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": pm_id,
            "init_checksum": str(init_payload.get("init_checksum") or ctx.get("init_checksum") or ""),
            "version": runtime_version,
            "expected_amount": str(ctx.get("checkout_amount") or expected_amount(init_payload)),
            "expected_payment_method_type": "paypal",
            "return_url": return_url,
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[locale]": str(ctx.get("locale") or "en"),
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "custom",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
    response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe confirm failed: {response.text[:500]}")
    payload = response.json() or {}
    print(f"DEBUG stripe_confirm: status={response.status_code}")
    debug_summary("stripe_confirm payload", payload)
    return payload


def extract_redirect_to_url(payload: Any) -> str:
    """从 Stripe 各种响应结构中提取 PayPal/GoPay 重定向 URL"""
    if not isinstance(payload, dict):
        return ""
    # 1. 顶层 next_action
    next_action = payload.get("next_action")
    if isinstance(next_action, dict):
        print(f"DEBUG extract_redirect_to_url: next_action.type={next_action.get('type')!r}, keys={list(next_action.keys())}")
        action_type = next_action.get("type") or ""
        if action_type == "redirect_to_url":
            redirect_to_url = next_action.get("redirect_to_url") or {}
            if isinstance(redirect_to_url, dict):
                url = str(redirect_to_url.get("url") or "").strip()
                if url:
                    return url
        # 有些版本直接在 next_action 里放 url
        direct_url = str(next_action.get("url") or "").strip()
        if direct_url and direct_url.startswith("http"):
            return direct_url
    # 2. 顶层 redirect_url / url 字段
    for key in ("redirect_url", "url", "redirect_to_url"):
        val = payload.get(key)
        if val and isinstance(val, str) and val.startswith("http"):
            return val
    # 3. 嵌套到 payment_intent / setup_intent / submission_attempt
    for key in ("payment_intent", "setup_intent", "submission_attempt"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = extract_redirect_to_url(nested)
            if found:
                return found
    return ""


def summarize_error_details(value: Any) -> Any:
    if isinstance(value, dict):
        summary: dict[str, Any] = {
            "keys": sorted(value.keys())[:20],
        }
        for key in (
            "type",
            "code",
            "decline_code",
            "message",
            "param",
            "reason",
            "doc_url",
        ):
            item = value.get(key)
            if item not in (None, ""):
                summary[key] = item
        return summary
    if value in (None, ""):
        return None
    return str(value)[:240]


def summarize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}

    next_action = payload.get("next_action")
    redirect_to_url = next_action.get("redirect_to_url") if isinstance(next_action, dict) else None
    redirect_url = ""
    if isinstance(redirect_to_url, dict):
        redirect_url = str(redirect_to_url.get("url") or "").strip()
    if not redirect_url and isinstance(next_action, dict):
        redirect_url = str(next_action.get("url") or "").strip()
    if not redirect_url:
        for key in ("redirect_url", "url", "redirect_to_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                redirect_url = value.strip()
                break

    summary: dict[str, Any] = {
        "keys": sorted(payload.keys())[:20],
        "state": payload.get("state"),
        "status": payload.get("status"),
        "result": payload.get("result"),
        "next_action_type": next_action.get("type") if isinstance(next_action, dict) else None,
        "next_action_keys": sorted(next_action.keys())[:20] if isinstance(next_action, dict) else [],
        "redirect_url": redirect_url[:240],
    }
    error_details = summarize_error_details(payload.get("error"))
    if error_details:
        summary["error"] = error_details

    for key in ("submission_attempt", "payment_intent", "setup_intent"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            nested_next_action = nested.get("next_action")
            nested_redirect = ""
            if isinstance(nested_next_action, dict):
                nested_redirect_to_url = nested_next_action.get("redirect_to_url")
                if isinstance(nested_redirect_to_url, dict):
                    nested_redirect = str(nested_redirect_to_url.get("url") or "").strip()
                if not nested_redirect:
                    nested_redirect = str(nested_next_action.get("url") or "").strip()
            if not nested_redirect:
                for nested_key in ("redirect_url", "url", "redirect_to_url"):
                    nested_value = nested.get(nested_key)
                    if isinstance(nested_value, str) and nested_value.startswith("http"):
                        nested_redirect = nested_value.strip()
                        break
            summary[key] = {
                "keys": sorted(nested.keys())[:20],
                "state": nested.get("state"),
                "status": nested.get("status"),
                "next_action_type": nested_next_action.get("type") if isinstance(nested_next_action, dict) else None,
                "next_action_keys": sorted(nested_next_action.keys())[:20] if isinstance(nested_next_action, dict) else [],
                "redirect_url": nested_redirect[:240],
            }
            if key == "submission_attempt":
                nested_error = summarize_error_details(nested.get("error"))
                if nested_error:
                    summary[key]["error"] = nested_error
            if key == "payment_intent":
                last_payment_error = summarize_error_details(nested.get("last_payment_error"))
                if last_payment_error:
                    summary[key]["last_payment_error"] = last_payment_error
            if key == "setup_intent":
                last_setup_error = summarize_error_details(nested.get("last_setup_error"))
                if last_setup_error:
                    summary[key]["last_setup_error"] = last_setup_error
    return summary


def debug_summary(label: str, payload: Any) -> None:
    try:
        print(f"DEBUG {label}: {json.dumps(summarize_payload(payload), ensure_ascii=False)}")
    except Exception as exc:
        print(f"DEBUG {label}: <summary_failed {exc}>")


def stripe_payment_page_redirect_url(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    timeout_seconds: float = 30,
    ctx: dict[str, Any] | None = None,
) -> str:
    """轮询 Stripe payment_pages，等待并提取 PayPal/GoPay 重定向 URL"""
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    attempt = 0
    # 复用 ctx 中的 session_id，保持上下文一致性
    elements_session_id = (ctx or {}).get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}"
    stripe_js_id = (ctx or {}).get("stripe_js_id") or str(uuid.uuid4())
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": elements_session_id,
        "elements_session_client[stripe_js_id]": stripe_js_id,
        "elements_session_client[locale]": locale_parts(req.payment_locale)[1],
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    print(
        "DEBUG payment_page_poll_start: "
        f"cs_id={cs_id}, timeout_seconds={timeout_seconds}, locale={locale_parts(req.payment_locale)[1]!r}, "
        f"elements_session_id={elements_session_id!r}, stripe_js_id={stripe_js_id!r}"
    )
    while time.time() < deadline:
        attempt += 1
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            debug_summary(f"payment_pages poll#{attempt}", payload)
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                print(f"DEBUG payment_pages poll#{attempt}: resolved redirect_url={redirect_url}")
                return redirect_url
            # 额外检查：payment_pages 可能在顶层 submission_attempt 的 next_action 里
            sub = payload.get("submission_attempt")
            if isinstance(sub, dict):
                debug_summary(f"payment_pages poll#{attempt} submission_attempt", sub)
                sub_url = extract_redirect_to_url(sub)
                if sub_url:
                    print(f"DEBUG payment_pages poll#{attempt}: resolved submission_attempt redirect_url={sub_url}")
                    return sub_url
            last_err = json.dumps(summarize_payload(payload), ensure_ascii=False)
        else:
            print(f"DEBUG: polled payment_pages failed status={response.status_code}, text={response.text[:200]}")
            last_err = f"http {response.status_code}: {response.text[:120]}"
        time.sleep(1)
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve(chatgpt: Any, cs_id: str, checkout: dict[str, Any]) -> None:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    try:
        chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        pass
    response = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/approve",
            "x-openai-target-route": "/backend-api/payments/checkout/approve",
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"chatgpt approve failed: {response.text[:500]}")
    print(f"DEBUG chatgpt_approve: status={response.status_code}, body={response.text[:300]}")
    try:
        result = (response.json() or {}).get("result")
    except Exception:
        result = ""
    if result != "approved":
        raise HTTPException(status_code=502, detail=f"chatgpt approve unexpected result: {result!r}")


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
) -> str:
    debug_summary("redirect_url_after_confirm confirm_payload", confirm_payload)
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        print(f"DEBUG redirect_url_after_confirm: got redirect directly from confirm: {redirect_url}")
        return redirect_url
    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict):
        state = submission.get("state") or ""
        debug_summary("redirect_url_after_confirm submission_attempt", submission)
        if state == "requires_approval":
            approval_proxy = checkout_stage_proxy(req)
            apply_provider_proxy(chatgpt, approval_proxy)
            print(
                "DEBUG redirect_url_after_confirm: "
                f"calling chatgpt_approve via approval_proxy={'set' if approval_proxy else 'direct'} then polling"
            )
            chatgpt_approve(chatgpt, cs_id, checkout)
            return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=45, ctx=ctx)
        if state in ("processing", "pending", "requires_action"):
            print(f"DEBUG redirect_url_after_confirm: state={state!r}, polling directly")
            return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=45, ctx=ctx)
    print(f"DEBUG redirect_url_after_confirm: no redirect found, fallback polling")
    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=30, ctx=ctx)


def resolve_external_redirect(stripe: Any, redirect_url: str, preferred_hosts: tuple[str, ...] = (), max_hops: int = 5) -> str:
    current = str(redirect_url or "").strip()
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        host = (urlsplit(current).netloc or "").lower()
        if preferred and any(host == item or host.endswith(f".{item}") for item in preferred):
            return current
        try:
            response = stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        except Exception:
            return current
        if response.status_code not in (301, 302, 303, 307, 308):
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    stripe = build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    print(
        "DEBUG create_provider_link: "
        f"link_type={link_type!r}, cs_id={checkout['cs_id']}, billing_country={checkout['billing_country']}, "
        f"currency={checkout['currency']}, provider_proxy={'set' if provider_proxy else 'default/direct'}"
    )
    billing = billing_for_link_type(link_type)
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    confirm_payload = stripe_confirm(
        stripe,
        checkout["cs_id"],
        pm_id,
        stripe_pk,
        link_type,
        init_payload,
        ctx,
        checkout,
        req,
        stripe_hosted_url,
    )
    stripe_redirect_url = redirect_url_after_confirm(
        chatgpt,
        stripe,
        confirm_payload,
        checkout["cs_id"],
        stripe_pk,
        checkout,
        req,
        ctx=ctx,
    )
    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts)
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url or stripe_redirect_url,
    }


app = FastAPI(title="OpenAI Pay Long Link")
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/long-link", response_model=LongLinkResponse)
def generate_long_link(req: LongLinkRequest) -> LongLinkResponse:
    link_type = normalize_link_type(req.link_type)
    stage1_proxy = checkout_stage_proxy(req)
    stage2_proxy = payment_stage_proxy(req)
    print(
        "DEBUG stage_proxies: "
        f"link_type={link_type!r}, "
        f"checkout_proxy={'set' if stage1_proxy else 'direct'}, "
        f"payment_proxy={'set' if stage2_proxy else 'direct'}"
    )
    chatgpt = build_chatgpt_session(req)
    checkout = create_checkout(req, chatgpt)
    post_checkout_proxy = ""
    if link_type in {"paypal", "gopay"}:
        post_checkout_proxy = payment_stage_proxy(req)
    init_payload = stripe_init(checkout["cs_id"], req, proxy_override=post_checkout_proxy)
    stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
    if not stripe_hosted_url:
        raise HTTPException(
            status_code=502,
            detail=f"stripe init response missing stripe_hosted_url, keys={sorted(init_payload.keys())}",
        )
    hosted_long_url = to_openai_pay_url(stripe_hosted_url)
    provider = {
        "payment_method_id": "",
        "stripe_redirect_url": "",
        "provider_redirect_url": "",
        "long_url": hosted_long_url,
    }
    fallback = False
    provider_error = ""
    if link_type in {"paypal", "gopay"}:
        try:
            provider = create_provider_link(
                chatgpt,
                checkout,
                init_payload,
                stripe_hosted_url,
                req,
                provider_proxy=post_checkout_proxy,
            )
        except HTTPException as exc:
            fallback = True
            provider_error = str(exc.detail)
        except Exception as exc:
            fallback = True
            provider_error = str(exc)

    return LongLinkResponse(
        ok=True,
        cs_id=checkout["cs_id"],
        processor_entity=checkout["processor_entity"],
        billing_country=checkout["billing_country"],
        currency=checkout["currency"],
        payment_locale=locale_parts(req.payment_locale)[0],
        link_type=link_type,
        payment_method_type=link_type if link_type in {"paypal", "gopay"} else "",
        payment_method_id=provider["payment_method_id"],
        stripe_redirect_url=provider["stripe_redirect_url"],
        provider_redirect_url=provider["provider_redirect_url"],
        fallback=fallback,
        provider_error=provider_error,
        stripe_hosted_url=stripe_hosted_url,
        long_url=provider["long_url"] or hosted_long_url,
    )


def lookup_ip_address(proxy: str = "") -> dict:
    """
    通过代理查询当前出口 IP 的真实地理地址。
    主方案：ipinfo.io/json（单次请求，返回 IP+城市+州+邮编+国家，免费 5 万次/月）
    备用方案：ip-api.com/json（HTTP，免费无限制）
    """
    session = new_session()
    effective_proxy = effective_default_proxy(proxy)
    if effective_proxy:
        set_proxy_url(session, effective_proxy)

    last_error = ""

    # ── 主方案：ipinfo.io ──────────────────────────────────────────────────
    try:
        resp = session.get(
            "https://ipinfo.io/json",
            headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
            timeout=12,
        )
        if resp.status_code == 200:
            d = resp.json() or {}
            ip = str(d.get("ip") or "").strip()
            city = str(d.get("city") or "").strip()
            state = str(d.get("region") or "").strip()
            postcode = str(d.get("postal") or "").strip()
            country_code = str(d.get("country") or "").strip().upper()
            loc = str(d.get("loc") or "")
            lat, lon = (loc.split(",") + ["", ""])[:2]
            if ip and (city or state or postcode):
                return {
                    "ok": True,
                    "ip": ip,
                    "latitude": lat.strip(),
                    "longitude": lon.strip(),
                    "country_code": country_code,
                    "street": "",
                    "city": city,
                    "state": state,
                    "postcode": postcode,
                    "country": country_code,
                    "source": "ipinfo.io",
                }
        last_error = f"ipinfo.io HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        last_error = f"ipinfo.io 异常: {exc}"

    # ── 备用方案：ip-api.com（HTTP，无速率限制）────────────────────────────
    try:
        resp2 = session.get(
            "http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,query",
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=12,
        )
        if resp2.status_code == 200:
            d2 = resp2.json() or {}
            if d2.get("status") == "success":
                return {
                    "ok": True,
                    "ip": str(d2.get("query") or "").strip(),
                    "latitude": str(d2.get("lat") or ""),
                    "longitude": str(d2.get("lon") or ""),
                    "country_code": str(d2.get("countryCode") or "").upper(),
                    "street": "",
                    "city": str(d2.get("city") or "").strip(),
                    "state": str(d2.get("regionName") or "").strip(),
                    "postcode": str(d2.get("zip") or "").strip(),
                    "country": str(d2.get("country") or "").strip(),
                    "source": "ip-api.com",
                }
            last_error = f"ip-api.com status={d2.get('status')}: {d2.get('message', '')}"
        else:
            last_error = f"ip-api.com HTTP {resp2.status_code}"
    except Exception as exc:
        last_error = f"ip-api.com 异常: {exc}"

    raise HTTPException(status_code=502, detail=f"所有 IP 查询方案均失败。最后错误: {last_error}")
@app.get("/api/ip-address")
def get_ip_address(proxy: str = "") -> dict:
    return lookup_ip_address(proxy)


@app.get("/api/stage-ips")
def get_stage_ips(
    checkoutProxy: str = "",
    paymentProxy: str = "",
    proxy: str = "",
    linkType: str = "paypal",
) -> dict:
    req = ProxyStageRequest(
        checkoutProxy=checkoutProxy,
        paymentProxy=paymentProxy,
        proxy=proxy,
        link_type=linkType,
    )
    checkout_proxy = checkout_stage_proxy(req)  # type: ignore[arg-type]
    payment_proxy = payment_stage_proxy(req)  # type: ignore[arg-type]
    stages: dict[str, dict[str, Any]] = {}

    for name, stage_proxy in (("checkout", checkout_proxy), ("payment", payment_proxy)):
        item: dict[str, Any] = {
            "proxy_configured": bool(stage_proxy),
            "proxy": stage_proxy,
        }
        try:
            item.update(lookup_ip_address(stage_proxy))
        except HTTPException as exc:
            item["ok"] = False
            item["error"] = f"lookup failed with HTTP {exc.status_code}"
        except Exception as exc:
            item["ok"] = False
            item["error"] = str(exc)
        stages[name] = item

    checkout_ip = str(stages["checkout"].get("ip") or "")
    payment_ip = str(stages["payment"].get("ip") or "")
    return {
        "ok": bool(stages["checkout"].get("ok")) and bool(stages["payment"].get("ok")),
        "link_type": normalize_link_type(linkType),
        "checkout": stages["checkout"],
        "payment": stages["payment"],
        "same_ip": bool(checkout_ip and payment_ip and checkout_ip == payment_ip),
    }
