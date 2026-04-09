#!/usr/bin/env python3
"""List Dev UoM Groups and UoMs (id -> key).

Usage:
  uv run scripts/list_uoms_dev.py
"""

import json
import os
import sys

import httpx

# Ensure repo root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from intacctsync import API_BASE_DEV, dev_token, HTTP_TIMEOUT  # noqa: E402


def fetch_all(path: str):
    base = (API_BASE_DEV or os.getenv("INTACCT_API_BASE_DEV", "")).rstrip("/")
    url = f"{base}{path}"
    head = {"Authorization": f"Bearer {dev_token()}"}
    params = {}
    while True:
        r = httpx.get(url, headers=head, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for ref in (data.get("ia::result") or []):
            yield ref
        meta = data.get("ia::meta") or {}
        nxt = meta.get("next")
        if nxt is None:
            break
        if isinstance(nxt, int) or (isinstance(nxt, str) and nxt.isdigit()):
            params = {"start": int(nxt)}
        else:
            params = {}


def main() -> None:
    print("UoM Groups (id -> key)")
    for ref in fetch_all("/objects/inventory-control/unit-of-measure-group"):
        print(f"- {ref.get('id')} -> {ref.get('key')}")

    print("\nUoMs (id -> key)")
    for ref in fetch_all("/objects/inventory-control/unit-of-measure"):
        print(f"- {ref.get('id')} -> {ref.get('key')}")


if __name__ == "__main__":
    main()

