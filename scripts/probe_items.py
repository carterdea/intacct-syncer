#!/usr/bin/env python3
import json
import os
import sys

import httpx

# Ensure repo root on path to import intacctsync
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

"""Probe a few Intacct endpoints quickly."""


def main() -> None:
    # Import here to avoid E402 (non-top-level import after path tweaks)
    from intacctsync import API_BASE_PROD, ENTITY_ID_PROD, HTTP_TIMEOUT, prod_token

    t = prod_token()
    headers = {"Authorization": f"Bearer {t}"}
    if ENTITY_ID_PROD:
        headers["X-IA-API-Param-Entity"] = ENTITY_ID_PROD
    base = (API_BASE_PROD or "https://api.intacct.com/ia/api/v1").rstrip("/")
    paths = [
        "/objects/inventory-control/item",
    ]
    for p in paths:
        url = f"{base}/{p.lstrip('/')}"
        # Objects list endpoints in v1 do not support page/pageSize; omit params.
        params = None if p.startswith("/objects/") else {"page": 1, "pageSize": 1}
        try:
            r = httpx.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
            try:
                body = r.json()
                print(r.status_code, p)
                print(json.dumps(body, indent=2))
            except Exception:
                print(r.status_code, p, r.text)
        except Exception as e:
            print("ERROR", p, str(e))


if __name__ == "__main__":
    main()
