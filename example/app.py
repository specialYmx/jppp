from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from queue import Queue
from typing import Any, AsyncGenerator, Dict, Optional
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
import threading

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

try:
    from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CurlCffiSession = None  # type: ignore


# 全局任务存储
tasks_store: Dict[str, Dict[str, Any]] = {}
tasks_lock = threading.Lock()


class TaskState:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = "running"  # running, completed, error
        self.logs: list[str] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = time.time()

    def add_log(self, message: str):
        """添加日志（带截断保护）"""
        self.logs.append(message)
        # 日志截断：限制最多500条，防止内存泄漏
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def set_result(self, result: Dict[str, Any]):
        """设置任务结果"""
        self.result = result
        self.status = "completed"

    def set_error(self, error: str):
        """设置错误信息"""
        self.error = error
        self.status = "error"


MAX_TASKS = 1000  # 最大任务数限制

def create_task() -> TaskState:
    """创建新任务（带容量保护）"""
    cleanup_old_tasks()  # 先清理旧任务

    task_id = str(uuid.uuid4())
    task = TaskState(task_id)

    with tasks_lock:
        # 如果达到最大任务数，清理最旧的已完成任务
        if len(tasks_store) >= MAX_TASKS:
            completed = [
                tid for tid, t in tasks_store.items()
                if t.status in ("completed", "error")
            ]
            if completed:
                # 删除最旧的已完成任务
                oldest = min(completed, key=lambda tid: tasks_store[tid].created_at)
                del tasks_store[oldest]

        tasks_store[task_id] = task
    return task


def get_task(task_id: str) -> Optional[TaskState]:
    """获取任务"""
    with tasks_lock:
        return tasks_store.get(task_id)


def cleanup_old_tasks():
    """清理超过1小时的旧任务"""
    with tasks_lock:
        now = time.time()
        to_delete = [
            tid for tid, task in tasks_store.items()
            if (now - task.created_at) > 3600
        ]
        for tid in to_delete:
            del tasks_store[tid]


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
    "http://192.168.67.148:7080",
).strip()

# ============================================================================
# 代理配置 - 按照优先级：前端请求参数 → 环境变量 → 硬编码默认值
# ============================================================================

# Checkout 创建阶段专用代理
CHECKOUT_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_CHECKOUT_PROXY",
    "socks5://192.168.67.148:7897",
).strip()

# Approval 审批阶段专用代理
APPROVAL_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_APPROVAL_PROXY",
    "http://192.168.67.148:7080",
).strip()

# Payment 支付阶段专用代理（Stripe API + Provider 跟踪）
PAYMENT_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_PAYMENT_PROXY",
    "socks5://192.168.67.148:7090",
).strip()

# SOCKS5 代理作为 HTTPS 请求的备用方案（当 HTTP 代理遇到 TLS 错误时使用）
DEFAULT_SOCKS_PROXY = os.getenv(
    "OPENAI_PAY_SOCKS_PROXY",
    "socks5://192.168.67.148:7080",
).strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
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
    checkout_proxy: str = Field(default="", alias="checkoutProxy")  # Checkout 创建代理
    approval_proxy: str = Field(default="", alias="approvalProxy")  # 审批代理（美国）
    payment_proxy: str = Field(default="", alias="paymentProxy")    # 支付代理（日本）
    stripe_publishable_key: str = ""
    billing_country: str = "US"
    checkout_ui_mode: str = "hosted"
    payment_locale: str = "en"
    link_type: str = "hosted"
    device_id: str = ""
    user_agent: str = ""


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
    logs: list[str] = []


def new_session() -> Any:
    if CurlCffiSession is not None:
        return CurlCffiSession(impersonate="chrome136")
    return requests.Session()


def effective_default_proxy(proxy: str = "") -> str:
    return str(proxy or "").strip() or DEFAULT_PROXY


def set_proxy_url(session: Any, proxy: str) -> None:
    proxy = str(proxy or "").strip()
    if proxy:
        # 支持 http, https, socks5, socks5h 协议
        # socks5h: 通过代理解析 DNS
        session.proxies = {"http": proxy, "https": proxy}


def set_proxy(session: Any, proxy: str) -> None:
    set_proxy_url(session, effective_default_proxy(proxy))


def proxy_for_region(proxy: str, region: str) -> str:
    proxy = str(proxy or "").strip()
    region = str(region or "").strip().upper()
    if proxy and region and "region-" in proxy:
        return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", proxy)
    return proxy


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
        return "US"  # PayPal 使用美国地区（OpenAI 只在美国启用了 PayPal）
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


def normalize_access_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    if token.startswith("{") or token.startswith("["):
        try:
            return find_token(json.loads(token)) or token
        except json.JSONDecodeError:
            return token
    return token


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

    device_id = req.device_id.strip() or str(uuid.uuid4())
    user_agent = req.user_agent.strip() or DEFAULT_USER_AGENT
    session = new_session()

    # 注意：如果代理使用 SOCKS5，连接池会导致代理隧道复用，无法轮询IP
    # 建议代理配置改用 HTTP 代理以获得更好的IP轮询效果
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
            "sec-ch-ua": '"Google Chrome";v="148", "Chromium";v="148", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )

    # 使用连接池提升性能
    if hasattr(session, 'adapters'):
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

    # 代理优先级：前端参数 → 环境变量 → 硬编码默认值
    proxy = req.checkout_proxy or CHECKOUT_STAGE_PROXY
    set_proxy(session, proxy)
    return session


def build_chatgpt_approval_session(req: LongLinkRequest) -> Any:
    """构建用于审批阶段的 ChatGPT session，使用 approval_proxy"""
    access_token = normalize_access_token(req.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="accessToken is required")

    device_id = req.device_id.strip() or str(uuid.uuid4())
    user_agent = req.user_agent.strip() or DEFAULT_USER_AGENT
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
            "sec-ch-ua": '"Google Chrome";v="148", "Chromium";v="148", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )

    # 使用连接池提升性能
    if hasattr(session, 'adapters'):
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

    # 代理优先级：前端参数 → 环境变量 → 硬编码默认值
    proxy = req.approval_proxy or APPROVAL_STAGE_PROXY
    set_proxy(session, proxy)
    return session


def create_checkout(req: LongLinkRequest, chatgpt_session: Any | None = None, max_retries: int = 3) -> dict[str, Any]:
    """创建 checkout，支持连接超时重试"""
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

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            session = chatgpt_session or build_chatgpt_session(req)

            # 调试：记录请求详情
            try:
                import logging
                logging.info(f"[DEBUG] 请求 URL: https://chatgpt.com/backend-api/payments/checkout")
                logging.info(f"[DEBUG] 请求体: {json.dumps(body, indent=2)}")
                logging.info(f"[DEBUG] Authorization: Bearer {req.access_token[:20]}...")
                logging.info(f"[DEBUG] User-Agent: {session.headers.get('User-Agent', 'N/A')}")
                logging.info(f"[DEBUG] Proxy: {session.proxies}")
            except Exception:
                pass

            response = session.post(
                "https://chatgpt.com/backend-api/payments/checkout",
                json=body,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )

            # 调试：记录响应详情
            try:
                logging.info(f"[DEBUG] 响应状态码: {response.status_code}")
                logging.info(f"[DEBUG] 响应头: {dict(response.headers)}")
                logging.info(f"[DEBUG] 响应内容: {response.text[:1000]}")
            except Exception:
                pass

            if response.status_code >= 400:
                body_text = response.text[:500] if response.text else ""

                # 增强错误信息
                error_detail = f"checkout create failed: {body_text}\n"
                error_detail += f"Status Code: {response.status_code}\n"
                error_detail += f"Request Headers: Authorization=Bearer {req.access_token[:20]}..., "
                error_detail += f"User-Agent={session.headers.get('User-Agent', 'N/A')[:50]}...\n"
                error_detail += f"Proxy: {session.proxies.get('https', 'None')}\n"

                if "cannot combine currencies" in body_text.lower():
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "GoPay needs an IDR checkout, but this Stripe customer already has active USD "
                            "checkout/subscription state. Use a fresh account/customer or wait for the USD "
                            "checkout state to expire; this cannot be bypassed in code."
                        ),
                    )

                # 针对 403 提供更多建议
                if response.status_code == 403:
                    error_detail += "\n可能原因:\n"
                    error_detail += "1. Access Token 无效或过期\n"
                    error_detail += "2. 代理 IP 被 ChatGPT 封禁\n"
                    error_detail += "3. 账号存在限制\n"
                    error_detail += "4. 请求头特征被识别为机器人\n"
                    error_detail += "建议: 检查 token 有效性，更换代理 IP，或使用真实浏览器的完整请求头"

                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail,
                )

            data = response.json() or {}
            cs_id = data.get("checkout_session_id") or data.get("session_id") or data.get("id")
            if not cs_id or not str(cs_id).startswith("cs_"):
                raise HTTPException(status_code=502, detail=f"checkout response missing cs_id: {data}")

            # 成功，返回结果
            return {
                "cs_id": str(cs_id),
                "processor_entity": extract_processor_entity(data),
                "billing_country": billing_country,
                "currency": currency,
            }

        except Exception as e:
            last_error = e
            error_msg = str(e)

            # 检测是否为可重试的错误（连接超时、网络错误）
            is_retryable = any(keyword in error_msg.lower() for keyword in [
                "connection timed out",
                "curl: (28)",
                "timeout",
                "connection refused",
                "connection reset",
                "curl: (7)",
                "curl: (35)",
            ])

            if is_retryable and attempt < max_retries:
                # 可重试的错误，继续下一次尝试
                time.sleep(2)  # 等待2秒后重试
                continue
            else:
                # 不可重试的错误，或已达到最大重试次数
                raise

    # 如果所有重试都失败，抛出最后一个错误
    raise last_error


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
    # 代理优先级：proxy_override → 前端参数 → 环境变量 → 硬编码默认值
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        proxy = req.payment_proxy or PAYMENT_STAGE_PROXY
        set_proxy_url(stripe, proxy)
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
    # 注意：stripe session 必须已经配置了美国代理
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
    # 代理优先级：proxy_override → 前端参数 → 环境变量 → 硬编码默认值
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        proxy = req.payment_proxy or PAYMENT_STAGE_PROXY
        set_proxy_url(stripe, proxy)
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
    return response.json() or {}


def extract_redirect_to_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    # 方法1: 检查顶层 next_action
    next_action = payload.get("next_action")
    if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
        redirect_to_url = next_action.get("redirect_to_url") or {}
        if isinstance(redirect_to_url, dict):
            url = str(redirect_to_url.get("url") or "").strip()
            if url:
                return url

    # 方法2: 检查 submission_attempt.payment_intent.next_action
    submission = payload.get("submission_attempt")
    if isinstance(submission, dict):
        pi = submission.get("payment_intent")
        if isinstance(pi, dict):
            pi_next_action = pi.get("next_action")
            if isinstance(pi_next_action, dict) and pi_next_action.get("type") == "redirect_to_url":
                redirect_info = pi_next_action.get("redirect_to_url") or {}
                if isinstance(redirect_info, dict):
                    url = str(redirect_info.get("url") or "").strip()
                    if url:
                        return url

    # 方法3: 递归检查 setup_intent 和 payment_intent（顶层）
    for key in ("setup_intent", "payment_intent"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = extract_redirect_to_url(nested)
            if found:
                return found

    return ""


def stripe_payment_page_redirect_url(stripe: Any, cs_id: str, stripe_pk: str, req: LongLinkRequest, timeout_seconds: float = 30, task: Optional[TaskState] = None) -> str:
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": locale_parts(req.payment_locale)[1],
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }

    # 记录 Polling 阶段使用的代理
    if task:
        proxy_info = stripe.proxies.get("https", stripe.proxies.get("http", "无代理"))
        task.add_log(f"[Polling] 使用代理: {proxy_info}")

    attempt = 0
    wait_time = 1.0  # 初始等待时间
    while time.time() < deadline:
        attempt += 1
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                if task:
                    task.add_log(f"[Polling] 第 {attempt} 次尝试成功获取到重定向 URL")
                return redirect_url

            # 增强调试：记录完整的响应结构
            if task and attempt <= 3:
                # 前3次尝试记录详细信息
                task.add_log(f"[Polling Debug] 第 {attempt} 次尝试")

                # 检查 submission_attempt 状态
                if "submission_attempt" in payload:
                    sub = payload["submission_attempt"]
                    if isinstance(sub, dict):
                        task.add_log(f"  submission_attempt.state: {sub.get('state')}")

                        # 如果失败，记录错误详情并立即抛出异常（不再无意义轮询）
                        if sub.get('state') == 'failed':
                            error = sub.get('error') or {}
                            error_code = error.get('code') if isinstance(error, dict) else None

                            if isinstance(error, dict):
                                task.add_log(f"  ❌ SUBMISSION FAILURE:")
                                task.add_log(f"    - type: {error.get('type')}")
                                task.add_log(f"    - code: {error_code}")
                                task.add_log(f"    - message: {error.get('message')}")
                                task.add_log(f"    - decline_code: {error.get('decline_code')}")

                            # 展开显示 payment_intent.last_payment_error（真正的失败原因）
                            last_payment_error = None
                            if "payment_intent" in sub:
                                pi = sub["payment_intent"]
                                if isinstance(pi, dict) and pi.get("last_payment_error"):
                                    last_payment_error = pi["last_payment_error"]
                                    task.add_log(f"  💳 PAYMENT_INTENT.LAST_PAYMENT_ERROR (真实失败原因):")
                                    task.add_log(f"    - type: {last_payment_error.get('type')}")
                                    task.add_log(f"    - code: {last_payment_error.get('code')}")
                                    task.add_log(f"    - decline_code: {last_payment_error.get('decline_code')}")
                                    task.add_log(f"    - message: {last_payment_error.get('message')}")

                                    # 如果有 payment_method 详情
                                    if last_payment_error.get('payment_method'):
                                        pm = last_payment_error['payment_method']
                                        task.add_log(f"    - payment_method.type: {pm.get('type')}")
                                        task.add_log(f"    - payment_method.id: {pm.get('id')}")

                            # 关键：如果是 checkout_approval_payment_failure_with_payment_error，立即抛出异常
                            if error_code == 'checkout_approval_payment_failure_with_payment_error':
                                task.add_log("[Error] 检测到支付失败，停止轮询")

                                # 构建详细错误信息
                                if last_payment_error:
                                    error_detail = (
                                        f"PaymentIntent 支付失败。\n"
                                        f"错误类型: {last_payment_error.get('type')}\n"
                                        f"错误代码: {last_payment_error.get('code')}\n"
                                        f"拒绝码: {last_payment_error.get('decline_code')}\n"
                                        f"错误消息: {last_payment_error.get('message')}\n"
                                        f"建议: 请检查支付方式、账户余额或联系支付提供商"
                                    )
                                else:
                                    error_detail = (
                                        f"支付确认阶段失败 (code: {error_code})。\n"
                                        f"错误: {error.get('message')}\n"
                                        f"建议: 检查代理配置、支付方式或重试"
                                    )

                                raise HTTPException(status_code=502, detail=error_detail)

                        if "payment_intent" in sub:
                            pi = sub["payment_intent"]
                            if isinstance(pi, dict):
                                task.add_log(f"  payment_intent.status: {pi.get('status')}")
                                if pi.get('next_action'):
                                    task.add_log(f"  payment_intent.next_action.type: {pi.get('next_action', {}).get('type')}")

                # 检查 payment_intent (顶层)
                if "payment_intent" in payload:
                    pi = payload["payment_intent"]
                    if isinstance(pi, dict):
                        task.add_log(f"  payment_intent.status: {pi.get('status')}")
                        if pi.get('next_action'):
                            task.add_log(f"  payment_intent.next_action.type: {pi.get('next_action', {}).get('type')}")

            last_err = f"keys=[{','.join(sorted(payload.keys())[:8])}]"
            wait_time = 1.0  # 重置等待时间
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
            # 指数退避：逐渐增加等待时间
            wait_time = min(wait_time * 1.5, 5.0)

        if attempt % 5 == 0 and task:
            task.add_log(f"[Polling] 已尝试 {attempt} 次，继续轮询...")
        time.sleep(wait_time)

    if task:
        task.add_log(f"[Polling] 超时失败，共尝试 {attempt} 次")
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve(chatgpt: Any, cs_id: str, checkout: dict[str, Any], req: LongLinkRequest, task: Optional[TaskState] = None, max_retries: int = 30) -> None:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))

    # 注意：传入的 chatgpt 参数会被忽略，我们总是使用 approval session
    for attempt in range(1, max_retries + 1):
        # 每次尝试都完全重建 session，确保使用正确的 approval 代理
        if attempt > 1:
            try:
                if hasattr(chatgpt, 'close'):
                    chatgpt.close()
                if hasattr(chatgpt, '__del__'):
                    chatgpt.__del__()
            except Exception:
                pass

        # 总是使用审批专用 session（不管是第几次尝试）
        chatgpt = build_chatgpt_approval_session(req)
        if task and attempt > 1:
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 已重建 session")

        # 每次都获取出口IP，用于验证代理轮询是否生效
        if task:
            proxy_info = chatgpt.proxies.get("https", chatgpt.proxies.get("http", "无代理"))
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 当前使用代理: {proxy_info}")

            # 获取实际出口IP（用于验证代理轮询）
            try:
                ip_response = chatgpt.get("https://api.ipify.org?format=json", timeout=5)
                if ip_response.status_code == 200:
                    exit_ip = ip_response.json().get("ip", "未知")
                    task.add_log(f"[Approval] 第 {attempt} 次尝试 - 出口IP: {exit_ip}")
            except Exception as e:
                task.add_log(f"[Approval] 第 {attempt} 次尝试 - 无法获取出口IP: {str(e)[:50]}")

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

        if task:
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 发送 approve 请求...")

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

        if task:
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 响应状态码: {response.status_code}")
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 响应内容: {response.text[:300]}")

        if response.status_code >= 400:
            if attempt < max_retries:
                if task:
                    task.add_log(f"[Approval] 第 {attempt} 次尝试 - HTTP 错误 {response.status_code}，继续重试...")
                time.sleep(1)  # 短暂延迟后重试
                continue
            else:
                raise HTTPException(status_code=response.status_code, detail=f"chatgpt approve failed after {max_retries} retries: {response.text[:500]}")

        try:
            result = (response.json() or {}).get("result")
        except Exception:
            result = ""

        if task:
            task.add_log(f"[Approval] 第 {attempt} 次尝试 - 审批结果: {result}")

        if result == "approved":
            if task:
                task.add_log(f"[Approval] ✓ 审批成功（第 {attempt} 次尝试）")
            return  # 成功，退出函数

        # 如果结果是 blocked 或其他非 approved 的值，继续重试
        if attempt < max_retries:
            if task:
                task.add_log(f"[Approval] 第 {attempt} 次尝试 - 审批被拒绝（{result}），继续重试...")
            # 使用指数退避策略减少无效重试
            wait_time = min(1.0 * (1.5 ** (attempt - 1)), 3.0)
            time.sleep(wait_time)
        else:
            # 已达到最大重试次数
            raise HTTPException(status_code=502, detail=f"chatgpt approve failed after {max_retries} retries, last result: {result!r}")


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    task: Optional[TaskState] = None,
) -> str:
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        if task:
            task.add_log("[Redirect] 从 confirm 响应中直接提取到重定向 URL")
        return redirect_url

    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict) and submission.get("state") == "requires_approval":
        if task:
            task.add_log("[Approval] 检测到需要审批，调用 ChatGPT approve")

        # 使用审批专用 session（美国代理）
        approval_session = build_chatgpt_approval_session(req)
        chatgpt_approve(approval_session, cs_id, checkout, req, task)

        if task:
            task.add_log("[Polling] 审批完成，开始轮询重定向 URL (超时: 45秒)")
        # 注意：这里的 stripe 已经配置了 Payment 代理（日本代理）
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=45, task=task)

    if task:
        task.add_log("[Polling] 开始轮询重定向 URL (超时: 30秒)")
    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=30, task=task)


def resolve_external_redirect(stripe: Any, redirect_url: str, preferred_hosts: tuple[str, ...] = (), max_hops: int = 5, task: Optional[TaskState] = None) -> str:
    current = str(redirect_url or "").strip()
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)

    for hop in range(max(1, int(max_hops or 1))):
        if not current:
            if task:
                task.add_log("[Redirect] URL 为空，停止跟踪")
            return ""

        host = (urlsplit(current).netloc or "").lower()

        if preferred and any(host == item or host.endswith(f".{item}") for item in preferred):
            if task:
                task.add_log(f"[Redirect] 第 {hop + 1} 跳：到达目标域名 {host}")
            return current

        try:
            response = stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        except Exception as e:
            error_msg = str(e)
            if task:
                task.add_log(f"[Redirect] 第 {hop + 1} 跳：网络错误 {error_msg[:80]}")

            # 检测 TLS/SSL 错误，尝试使用 SOCKS5 代理回退
            if any(keyword in error_msg.lower() for keyword in ["ssl", "tls", "certificate", "curl: (35)"]):
                if task:
                    task.add_log(f"[Redirect] 检测到 TLS 错误，尝试切换到 SOCKS5 代理重试...")

                # 尝试使用 SOCKS5 代理重建 session
                try:
                    socks_stripe = new_session()
                    socks_stripe.headers.update(stripe.headers)
                    set_proxy_url(socks_stripe, DEFAULT_SOCKS_PROXY)

                    if task:
                        task.add_log(f"[Redirect] 使用 SOCKS5 代理: {DEFAULT_SOCKS_PROXY[:50]}...")

                    response = socks_stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)

                    if task:
                        task.add_log(f"[Redirect] SOCKS5 代理成功！继续跟踪重定向...")

                    # 如果成功，更新 stripe session 为 SOCKS5 版本
                    stripe = socks_stripe

                except Exception as socks_err:
                    if task:
                        task.add_log(f"[Redirect] SOCKS5 代理也失败: {str(socks_err)[:80]}")
                        task.add_log(f"[Redirect] 返回 Stripe 重定向 URL（仍然可用）")
                    return redirect_url  # 返回初始的 Stripe URL，它仍然有效
            else:
                # 非 TLS 错误，直接返回当前 URL
                return current

        if response.status_code not in (301, 302, 303, 307, 308):
            if task:
                task.add_log(f"[Redirect] 第 {hop + 1} 跳：非重定向状态码 {response.status_code}，停止")
            return current

        location = str(response.headers.get("Location") or "").strip()
        if not location:
            if task:
                task.add_log(f"[Redirect] 第 {hop + 1} 跳：无 Location 头，停止")
            return current

        if task:
            task.add_log(f"[Redirect] 第 {hop + 1} 跳：{response.status_code} → {urlsplit(location).netloc or location[:50]}")
        current = urljoin(current, location)

    if task:
        task.add_log(f"[Redirect] 达到最大跳数 {max_hops}，停止跟踪")
    return current


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    task: Optional[TaskState] = None,
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    if task:
        task.add_log(f"[Provider] 开始提取 {link_type.upper()} 链接")

    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    stripe = build_stripe_session(req, proxy_override=provider_proxy)

    if task:
        task.add_log("[Provider] 构建 Stripe 上下文")
    ctx = stripe_context(checkout["cs_id"], init_payload, req)

    if task:
        task.add_log(f"[Provider] 生成账单地址 (类型: {link_type})")
    billing = billing_for_link_type(link_type)

    if task:
        task.add_log(f"[Stripe] 创建 Payment Method (类型: {link_type})")
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    if task:
        task.add_log(f"[Stripe] Payment Method 已创建: {pm_id}")

    if task:
        task.add_log("[Stripe] 确认支付 (confirm)")
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
    if task:
        task.add_log("[Stripe] 支付确认完成")

    if task:
        task.add_log("[Redirect] 获取重定向 URL")
    stripe_redirect_url = redirect_url_after_confirm(
        chatgpt,
        stripe,
        confirm_payload,
        checkout["cs_id"],
        stripe_pk,
        checkout,
        req,
        task,
    )
    if task:
        task.add_log(f"[Redirect] Stripe 重定向 URL 已获取: {stripe_redirect_url[:80]}...")

    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    if task:
        task.add_log(f"[Redirect] 跟踪外部重定向 (目标: {preferred_hosts or '任意'})")
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts, task=task)

    if provider_url and provider_url != stripe_redirect_url:
        if task:
            task.add_log(f"[Success] 成功提取 Provider URL: {provider_url[:80]}...")
    else:
        if task:
            task.add_log("[Warning] 未能提取到不同的 Provider URL，使用 Stripe URL")

    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url or stripe_redirect_url,
    }


app = FastAPI(title="OpenAI Pay Long Link")
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


def execute_long_link_task(task: TaskState, req: LongLinkRequest):
    """在后台线程执行任务"""
    try:
        link_type = normalize_link_type(req.link_type)

        task.add_log(f"[Start] 开始生成 {link_type} 类型链接")
        task.add_log(f"[Config] 国家: {req.billing_country}, 语言: {req.payment_locale}")

        task.add_log("[ChatGPT] 构建会话")
        chatgpt = build_chatgpt_session(req)

        # 显示 Checkout 阶段实际使用的代理
        checkout_proxy_str = req.checkout_proxy.strip() if req.checkout_proxy else ""
        actual_checkout_proxy = checkout_proxy_str or CHECKOUT_STAGE_PROXY
        task.add_log(f"[Proxy] Checkout 使用代理: {actual_checkout_proxy[:60]}... {'(用户配置)' if checkout_proxy_str else '(默认值)'}")

        # 获取实际出口 IP（验证 checkout 代理）
        try:
            ip_response = chatgpt.get("https://api.ipify.org?format=json", timeout=5)
            if ip_response.status_code == 200:
                exit_ip = ip_response.json().get("ip", "未知")
                task.add_log(f"[Proxy] Checkout 出口 IP: {exit_ip}")
        except Exception as e:
            task.add_log(f"[Proxy] 无法获取出口 IP: {str(e)[:50]}")

        task.add_log("[ChatGPT] 创建 Checkout")
        checkout = create_checkout(req, chatgpt)
        task.add_log(f"[ChatGPT] Checkout 已创建: {checkout['cs_id']}")

        task.add_log("[Stripe] 初始化 Payment Page")
        init_payload = stripe_init(checkout["cs_id"], req)
        stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()

        if not stripe_hosted_url:
            task.add_log("[Error] Stripe init 未返回 hosted URL")
            task.set_error("stripe init response missing stripe_hosted_url")
            return

        task.add_log("[Stripe] Payment Page 已初始化")
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
                    task=task,
                )
            except HTTPException as exc:
                fallback = True
                provider_error = str(exc.detail)
                task.add_log(f"[Fallback] Provider 提取失败: {provider_error}")
                task.add_log("[Fallback] 回退到 hosted 长链")
            except Exception as exc:
                fallback = True
                provider_error = str(exc)
                task.add_log(f"[Fallback] Provider 提取异常: {provider_error}")
                task.add_log("[Fallback] 回退到 hosted 长链")

        task.add_log("[Complete] 链接生成完成")

        # 设置任务结果
        result = {
            "ok": True,
            "cs_id": checkout["cs_id"],
            "processor_entity": checkout["processor_entity"],
            "billing_country": checkout["billing_country"],
            "currency": checkout["currency"],
            "payment_locale": locale_parts(req.payment_locale)[0],
            "link_type": link_type,
            "payment_method_type": link_type if link_type in {"paypal", "gopay"} else "",
            "payment_method_id": provider["payment_method_id"],
            "stripe_redirect_url": provider["stripe_redirect_url"],
            "provider_redirect_url": provider["provider_redirect_url"],
            "fallback": fallback,
            "provider_error": provider_error,
            "stripe_hosted_url": stripe_hosted_url,
            "long_url": provider["long_url"] or hosted_long_url,
        }
        task.set_result(result)

    except Exception as e:
        task.add_log(f"[Error] 任务执行失败: {str(e)}")
        task.set_error(str(e))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/test-proxy")
def test_proxy(req: dict[str, str]) -> dict[str, Any]:
    """测试代理连通性和延迟"""
    proxy_url = req.get("proxy", "").strip()

    if not proxy_url:
        return {
            "ok": False,
            "error": "代理 URL 不能为空",
            "latency_ms": 0,
        }

    test_url = "https://www.google.com"
    session = new_session()

    try:
        set_proxy_url(session, proxy_url)

        start_time = time.time()
        response = session.get(test_url, timeout=10)
        elapsed_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            return {
                "ok": True,
                "latency_ms": elapsed_ms,
                "message": f"代理连接成功 (延迟: {elapsed_ms}ms)",
            }
        else:
            return {
                "ok": False,
                "error": f"HTTP {response.status_code}",
                "latency_ms": elapsed_ms,
            }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:200],
            "latency_ms": 0,
        }


@app.post("/api/long-link", response_model=LongLinkResponse)
def generate_long_link(req: LongLinkRequest) -> LongLinkResponse:
    logs = []
    link_type = normalize_link_type(req.link_type)

    logs.append(f"[Start] 开始生成 {link_type} 类型链接")
    logs.append(f"[Config] 国家: {req.billing_country}, 语言: {req.payment_locale}")

    # 显示用户提供的代理配置
    checkout_proxy_str = req.checkout_proxy.strip() if req.checkout_proxy else ""
    approval_proxy_str = req.approval_proxy.strip() if req.approval_proxy else ""
    payment_proxy_str = req.payment_proxy.strip() if req.payment_proxy else ""

    # 显示实际使用的代理（包括默认值）
    actual_checkout_proxy = checkout_proxy_str or CHECKOUT_STAGE_PROXY
    actual_approval_proxy = approval_proxy_str or APPROVAL_STAGE_PROXY
    actual_payment_proxy = payment_proxy_str or PAYMENT_STAGE_PROXY

    logs.append(f"[Proxy] 创建代理: {actual_checkout_proxy[:60]}... {'(用户配置)' if checkout_proxy_str else '(默认值)'}")
    logs.append(f"[Proxy] 审批代理: {actual_approval_proxy[:60]}... {'(用户配置)' if approval_proxy_str else '(默认值)'}")
    logs.append(f"[Proxy] 支付代理: {actual_payment_proxy[:60]}... {'(用户配置)' if payment_proxy_str else '(默认值)'}")

    logs.append("[ChatGPT] 构建会话")
    chatgpt = build_chatgpt_session(req)

    logs.append("[ChatGPT] 创建 Checkout")
    checkout = create_checkout(req, chatgpt)
    logs.append(f"[ChatGPT] Checkout 已创建: {checkout['cs_id']}")

    logs.append("[Stripe] 初始化 Payment Page")
    init_payload = stripe_init(checkout["cs_id"], req)
    stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()

    if not stripe_hosted_url:
        logs.append("[Error] Stripe init 未返回 hosted URL")
        raise HTTPException(
            status_code=502,
            detail=f"stripe init response missing stripe_hosted_url, keys={sorted(init_payload.keys())}",
        )

    logs.append(f"[Stripe] Payment Page 已初始化")
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
                task=None,
            )
        except HTTPException as exc:
            fallback = True
            provider_error = str(exc.detail)
            logs.append(f"[Fallback] Provider 提取失败: {provider_error}")
            logs.append("[Fallback] 回退到 hosted 长链")
        except Exception as exc:
            fallback = True
            provider_error = str(exc)
            logs.append(f"[Fallback] Provider 提取异常: {provider_error}")
            logs.append("[Fallback] 回退到 hosted 长链")

    logs.append("[Complete] 链接生成完成")

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
        logs=logs,
    )


@app.post("/api/long-link-async")
def start_long_link_async(req: LongLinkRequest) -> dict[str, str]:
    """启动异步任务"""
    # 清理旧任务
    cleanup_old_tasks()

    # 创建任务
    task = create_task()

    # 在后台线程执行
    thread = threading.Thread(
        target=execute_long_link_task,
        args=(task, req),
        daemon=True
    )
    thread.start()

    # 立即返回 task_id
    return {"task_id": task.task_id}


@app.get("/api/task-status/{task_id}")
def get_task_status(task_id: str) -> dict[str, Any]:
    """获取任务状态和新日志"""
    task = get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 返回任务状态
    response = {
        "status": task.status,
        "logs": task.logs,  # 返回所有日志（前端会处理去重）
    }

    if task.status == "completed" and task.result:
        response["result"] = task.result
    elif task.status == "error" and task.error:
        response["error"] = task.error

    return response
