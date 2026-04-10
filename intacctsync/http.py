from __future__ import annotations

import logging
import time
from typing import Any

import asyncio
import threading
from email.utils import parsedate_to_datetime

log = logging.getLogger(__name__)

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .config import (
    API_BASE_DEV,
    API_BASE_PROD,
    AUTH_URL_DEV,
    AUTH_URL_PROD,
    CLIENT_ID_DEV,
    CLIENT_ID_PROD,
    CLIENT_SECRET_DEV,
    CLIENT_SECRET_PROD,
    COMPANY_DEV,
    COMPANY_PROD,
    ENTITY_ID_DEV,
    ENTITY_ID_PROD,
    HTTP_TIMEOUT,
    SCOPE_DEV,
    SCOPE_PROD,
    USERNAME_DEV,
    USERNAME_PROD,
)
from .storage import TokenCache


def _build_url(base: str, path: str, company: str) -> str:
    # Normalize company token
    if "{company}" in path:
        path = path.replace("{company}", company)
    # Bump version to v2 for Sales objects only. Do NOT bump for Order Entry.
    if "/objects/sales/" in path:
        base = base.replace("/v1", "/v2")
    return f"{base.rstrip('/')}/{path.lstrip('/')}"



def _compose_username(user: str, company: str, entity: str | None) -> str:
    user = user or ""
    company = company or ""
    entity = (entity or "").strip()
    if "@" in user:
        return user
    return f"{user}@{company}{('|' + entity) if entity else ''}"


@retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(1, 5), retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)))
def _token_full(auth_url: str, client_id: str, client_secret: str, username: str, scope: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
    }
    if scope:
        payload["scope"] = scope
    r = httpx.post(auth_url, json=payload, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()



@retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(1, 5), retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)))
def _refresh_full(auth_url: str, client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    r = httpx.post(auth_url, json=payload, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _ensure_token(env: str) -> str:
    if env == "prod":
        auth_url = AUTH_URL_PROD
        cid = CLIENT_ID_PROD or ""
        csec = CLIENT_SECRET_PROD or ""
        company = COMPANY_PROD or ""
        username = _compose_username(USERNAME_PROD or "", company, ENTITY_ID_PROD)
        scope = SCOPE_PROD or ""
    else:
        auth_url = AUTH_URL_DEV
        cid = CLIENT_ID_DEV or ""
        csec = CLIENT_SECRET_DEV or ""
        company = COMPANY_DEV or ""
        username = _compose_username(USERNAME_DEV or "", company, ENTITY_ID_DEV)
        scope = SCOPE_DEV or ""

    cache = TokenCache()
    row = cache.get(env, company, username, scope)
    now = time.time()
    if row and row.get("access_token") and (row.get("expires_at", 0) - 60) > now:
        return str(row["access_token"])  # fresh token

    # Try refresh if available
    if row and row.get("refresh_token"):
        try:
            data = _refresh_full(auth_url, cid, csec, str(row["refresh_token"]))
            at = data.get("access_token") or data.get("accessToken")
            rt = data.get("refresh_token") or row.get("refresh_token")
            exp_in = int(data.get("expires_in") or 3600)
            exp_at = now + exp_in
            if at:
                cache.put(env, company, username, scope, at, rt, exp_at)
                return at
        except Exception:
            log.debug("Token refresh failed for %s/%s, clearing cache", env, company, exc_info=True)
            cache.clear(env, company, username, scope)

    # Fresh token
    data = _token_full(auth_url, cid, csec, username, scope)
    at = data.get("access_token") or data.get("accessToken") or ""
    rt = data.get("refresh_token")
    exp_in = int(data.get("expires_in") or 3600)
    exp_at = now + exp_in
    cache.put(env, company, username, scope, at, rt, exp_at)
    return at


def _clear_token(env: str) -> None:
    if env == "prod":
        company = COMPANY_PROD or ""
        username = _compose_username(USERNAME_PROD or "", company, ENTITY_ID_PROD)
        scope = SCOPE_PROD or ""
    else:
        company = COMPANY_DEV or ""
        username = _compose_username(USERNAME_DEV or "", company, ENTITY_ID_DEV)
        scope = SCOPE_DEV or ""
    TokenCache().clear(env, company, username, scope)


def prod_token() -> str:
    return _ensure_token("prod")


def dev_token() -> str:
    return _ensure_token("dev")


# --- Cooperative rate limit smoothing ---
_rate_limit_until: dict[str, float] = {"prod": 0.0, "dev": 0.0}
_rl_lock = threading.Lock()


def _env_name_for_base(base: str) -> str:
    return "prod" if base == API_BASE_PROD else "dev"


def _sleep_if_limited(env_name: str) -> None:
    with _rl_lock:
        until = _rate_limit_until.get(env_name, 0.0)
    now = time.time()
    if until > now:
        time.sleep(until - now)


def _note_429(env_name: str, r: httpx.Response) -> None:
    wait_for = 0.0
    ra = r.headers.get("Retry-After")
    if ra:
        try:
            # Retry-After can be seconds or HTTP date
            if ra.isdigit():
                wait_for = float(ra)
            else:
                dt = parsedate_to_datetime(ra)
                wait_for = max(0.0, dt.timestamp() - time.time())
        except Exception:
            wait_for = 5.0
    else:
        wait_for = 5.0
    with _rl_lock:
        _rate_limit_until[env_name] = max(_rate_limit_until.get(env_name, 0.0), time.time() + wait_for)


def _prepare_request(base: str, path: str, bearer: str) -> tuple[str, dict[str, str], str]:
    """Build URL, headers, and env name for any Intacct API call."""
    company = (COMPANY_PROD or "") if base == API_BASE_PROD else (COMPANY_DEV or "")
    url = _build_url(base, path, company)
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    ent_id = ENTITY_ID_PROD if base == API_BASE_PROD else ENTITY_ID_DEV
    if str(path).startswith("/objects/company-config/"):
        ent_id = None
    if ent_id:
        headers["X-IA-API-Param-Entity"] = ent_id
    if "/objects/sales/" in str(path):
        headers["IA-API-Version"] = "2"
        headers["IA-Api-Version"] = "2"
    return url, headers, _env_name_for_base(base)


def _handle_response(r: httpx.Response, env_name: str) -> dict[str, Any]:
    """Handle 429, raise with body context on errors, return parsed JSON."""
    if r.status_code == 429:
        _note_429(env_name, r)
        raise httpx.HTTPStatusError("Rate limited", request=r.request, response=r)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        msg = f"{e} | body: {r.text[:1000]}"
        raise httpx.HTTPStatusError(msg, request=r.request, response=r) from e
    try:
        return r.json()
    except Exception:
        return {}


@retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(1, 5), retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)))
def _request(method: str, base: str, path: str, bearer: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url, headers, env_name = _prepare_request(base, path, bearer)
    _sleep_if_limited(env_name)
    send = getattr(httpx, method)
    kwargs: dict[str, Any] = {"headers": headers, "timeout": HTTP_TIMEOUT}
    if params is not None:
        kwargs["params"] = params
    if payload is not None:
        kwargs["json"] = payload
    r = send(url, **kwargs)
    if r.status_code == 401:
        _clear_token(env_name)
        headers["Authorization"] = f"Bearer {_ensure_token(env_name)}"
        kwargs["headers"] = headers
        r = send(url, **kwargs)
    return _handle_response(r, env_name)


def http_get(base: str, path: str, bearer: str, params: dict[str, Any]) -> dict[str, Any]:
    return _request("get", base, path, bearer, params=params)


def http_post_json(base: str, path: str, bearer: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request("post", base, path, bearer, payload=payload)


def http_patch_json(base: str, path: str, bearer: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request("patch", base, path, bearer, payload=payload)


async def http_post_json_async(
    base: str,
    path: str,
    bearer: str,
    payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url, headers, env_name = _prepare_request(base, path, bearer)
    close_client = False
    if client is None:
        client = httpx.AsyncClient(http2=True, timeout=HTTP_TIMEOUT)
        close_client = True
    try:
        until = _rate_limit_until.get(env_name, 0.0)
        now = time.time()
        if until > now:
            await asyncio.sleep(until - now)
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code == 401:
            _clear_token(env_name)
            headers["Authorization"] = f"Bearer {_ensure_token(env_name)}"
            r = await client.post(url, headers=headers, json=payload)
        return _handle_response(r, env_name)
    finally:
        if close_client:
            await client.aclose()
