# Intacct Prod → Dev Sync Plan

This plan documents the fixes and the exact run order to complete a clean Production → Development sync using the REST (Objects + Core Query) API. Follow in order.

## 0) Prereqs
- Python env: `uv sync`
- Auth/env: copy `env.example` → `.env` and fill all `INTACCT_*` values (both prod + dev).
- Optional safety knobs:
  - `INTACCT_PAGE_SIZE` (default 200)
  - `INTACCT_DEFAULT_UOM_GROUP_ID_DEV` (see §3.2)
  - `INTACCT_DEFAULT_LOCATION_ID_DEV` (see §3.3)

## 1) Config state (already applied)
- Objects Core Query blocks use `size` and `start` (not `pageSize`).
- All entities use `list_data_key: "ia::result"` and `next_page_key: "ia::meta.next"`.
- Order Entry paths are `"/objects/order-entry/..."`.
- See `intacct.config.json` for details.

## 2) Code adjustments to keep
- Query path: `paginate._fetch_all_via_query` includes `size` and honors config `start`.
- Rate‑limit/backoff, token caching, entity header handling are in `intacctsync/http.py`.

## 3) Fixes to apply before running big sync

### 3.1 Price List Entry pagination (order-entry, v1)
Problem you hit: `start` query param is not supported for Order Entry Objects on v1.

Do this:
- Ensure we do NOT force v2 for Order Entry in `intacctsync/http.py`.
  - Remove the base URL bump to `/v2` and the `IA-API-Version: 2` headers for Order Entry.
- Ensure paginator follows `ia::meta.next` as a URL for Order Entry objects.
  - In `intacctsync/paginate.py`, under the `is_objects` branch, if the current `path` contains `/objects/order-entry/` then:
    - If `meta.next` is a string starting with `/`, set `path = meta.next` and clear `params = {}`.
    - If `meta.next` is numeric, DO NOT append `?start=` (skip; rely on URL form only). This avoids REST-1034.

Run a small smoke test after patching:
```
uv run intacctsync sync pricelists --limit 5
uv run intacctsync sync price-list-entries --limit 50 --dry-run
```

### 3.2 UoM parent group mapping
- 14 UoMs failed due to missing parent group mapping.
- Options:
  - Preferred: set `INTACCT_DEFAULT_UOM_GROUP_ID_DEV` to a valid Dev UoM group id, then re-run `uom` sync.
  - Or ensure each failing UoM’s parent group exists in Dev with the same id as Prod, then re-run.

Test:
```
uv run intacctsync sync uom --limit 200
```

### 3.3 Warehouse location mapping
- 90 warehouses failed: “Dev Location not found”. Dev location ids likely differ from Prod.
- Options:
  - Quick fix: set `INTACCT_DEFAULT_LOCATION_ID_DEV` to a valid Dev location id to use as fallback.
  - Better: create a mapping for Prod→Dev location ids. Two ways:
    1) Populate the internal map using a one-off script that calls `LocationMap().put(prod_id, dev_id)` (see `intacctsync/storage.py`).
    2) Align Dev location ids to match Prod (manual admin choice).

After setting a fallback or seeding the map, re-run:
```
uv run intacctsync sync locations
uv run intacctsync sync warehouses --limit 200
```

### 3.4 Product Lines support (referenced by price-list-entries)
- Config has `product-lines`, but CLI lacks the command. Add it if entries reference `productLine`:
  - In `intacctsync/cli.py`: add `"product-lines"` to the `click.Choice` list.
  - In `intacctsync/sync_engine.py`: add a case in `ensure_dev_entity`:
    - `key_name = "id"`
    - minimal payload: `{ "id": prod["id"], "name": prod.get("name") }`
    - `dev_create_path` is already in config.

Test:
```
uv run intacctsync sync product-lines --limit 100
```

## 4) Recommended sync order
Always start with a quick connectivity check.
```
uv run intacctsync verify
```
Then:
```
# reference + hierarchy
uv run intacctsync sync entities
uv run intacctsync sync departments
uv run intacctsync sync locations
uv run intacctsync sync uom-groups
uv run intacctsync sync uom

# master data
uv run intacctsync sync items
uv run intacctsync sync customers

# pricing
uv run intacctsync sync pricelists
# optional once §3.4 is added
# uv run intacctsync sync product-lines
uv run intacctsync sync price-list-entries

# logistics (after §3.3 mapping or default)
uv run intacctsync sync warehouses
```
Tips:
- Use `--limit` for initial smoke tests, then run without it for full syncs.
- Use `--verbose` to see detailed errors; failures are summarized at the end of each run.

## 5) Troubleshooting quick refs
- 400 invalidRequest + REST-1034 with `start`: you’re on v1 Objects that don’t accept `start`. Follow `ia::meta.next` URL form only.
- 400 Version 2 is not valid: tenant doesn’t expose v2; keep base on `/v1` and remove v2 headers.
- 401/expired tokens: the tool auto-refreshes and caches tokens; re-run the command.
- 429 rate limit: the tool backs off; re-run the same command if it aborts.

## 6) Rollback notes
- All changes are idempotent “upserts” where possible. If you need to undo code edits:
  - Revert edits in `intacctsync/http.py` (version logic) and `intacctsync/paginate.py` (order-entry pagination).
  - Config file changes are safe to keep.

---
Last updated: 2025-09-04

