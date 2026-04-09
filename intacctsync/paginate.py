from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .config import PAGE_SIZE
from .http import http_get, http_post_json


def _fetch_all_via_query(cfg: dict[str, Any], base: str, bearer: str) -> Iterable[dict[str, Any]]:
    q = (cfg.get("query") or {})
    obj = q.get("object") or ""
    # Accept either "fields" or legacy "select" in config
    fields = q.get("fields") or q.get("select") or ["id", "key"]
    order_by = q.get("orderBy") or [{"id": "asc"}]
    # honor config-provided size/start; fall back to env PAGE_SIZE
    size = int(q.get("size") or PAGE_SIZE)
    try:
        start: int | None = int(q.get("start")) if q.get("start") is not None else None
    except Exception:
        start = None
    while True:
        payload: dict[str, Any] = {"object": obj, "fields": fields, "orderBy": order_by, "size": size}
        if start:
            payload["start"] = start
        data = http_post_json(base, "/services/core/query", bearer, payload)
        items = data.get("ia::result") or []
        yield from items
        meta = data.get("ia::meta") or {}
        nxt = meta.get("next")
        if nxt is None:
            break
        start = int(nxt) if isinstance(nxt, int | float) or (isinstance(nxt, str) and nxt.isdigit()) else None
        if not start:
            break


def fetch_all(cfg: dict[str, Any], base: str, bearer: str, company: str, since: str | None) -> Iterable[dict[str, Any]]:
    # Prefer core/query when configured for the object (more stable + faster)
    if cfg.get("use_query"):
        yield from _fetch_all_via_query(cfg, base, bearer)
        return

    params = dict(cfg.get("list_params") or {})
    if "pageSize" in params and not params["pageSize"]:
        params["pageSize"] = PAGE_SIZE
    list_key = cfg.get("list_data_key") or "items"
    next_key = cfg.get("next_page_key") or "hasMore"
    path = cfg["prod_list_path"]
    is_objects = str(path).startswith("/objects/")
    since_param = cfg.get("since_param")
    if since and since_param and not is_objects:
        params[since_param] = since
    if is_objects:
        params = {}
    while True:
        cleaned: dict[str, Any] = {}
        if is_objects:
            if "start" in params:
                try:
                    cleaned["start"] = int(params["start"])  # normalize numeric
                except Exception:
                    cleaned["start"] = params["start"]
            if "pageSize" in params:
                cleaned["pageSize"] = params["pageSize"]
        else:
            cleaned = params
        try:
            data = http_get(base, path, bearer, cleaned)
        except Exception as e:  # noqa: BLE001
            # Fallback for Objects: if 400 and pageSize present, retry without pageSize
            if is_objects and "pageSize" in cleaned:
                fallback_params = {k: v for k, v in cleaned.items() if k != "pageSize"}
                data = http_get(base, path, bearer, fallback_params)
            else:
                raise e
        items = data.get(list_key) or data.get("data") or []
        yield from items
        if is_objects:
            meta = data.get("ia::meta") or {}
            nxt = meta.get("next")
            if nxt is None:
                break
            is_order_entry = "/objects/order-entry/" in str(path)
            if isinstance(nxt, str) and nxt.startswith("/"):
                # For Objects APIs, honor URL-style next when provided
                path = nxt
                params = {}
                continue
            if is_order_entry:
                # For Order Entry (v1), do NOT add numeric start; rely only on URL-style next.
                # If next is not a URL here, stop to avoid REST-1034.
                break
            # Non-Order Entry Objects: allow numeric start token
            params = {"start": int(nxt) if isinstance(nxt, (int, float)) or (isinstance(nxt, str) and nxt.isdigit()) else nxt}
            ps = meta.get("pageSize")
            if ps is not None:
                params["pageSize"] = ps
            continue
        if "hasMore" in data:
            if data.get("hasMore"):
                params["page"] = int(params.get("page", 1)) + 1
                continue
            break
        nxt = data.get(next_key)
        if nxt:
            params["page"] = nxt
            continue
        if len(items) >= int(params.get("pageSize", PAGE_SIZE)):
            params["page"] = int(params.get("page", 1)) + 1
            continue
        break
