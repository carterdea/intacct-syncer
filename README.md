# Intacct Syncer (Prod → Dev)

Purpose: Mirror selected master data from Sage Intacct Production into Development and optionally create an OE Named Document ("Shipper"). Tooling is config‑driven and safe by default (dry‑run).

**Highlights**
- OAuth2 per environment; multi‑entity header handled automatically.
- Config‑driven objects in `intacct.config.json` using Objects API and core/query.
- Upserts: creates when missing; patches when different (customers, departments, entities texts; more coming).
- Persistent crosswalk: Prod → Dev ID/key maps in `intacctsync.sqlite3`.
- Resilient HTTP with retries and cooperative rate‑limit smoothing.

**Requirements**
- Python 3.11 and `uv`.
- Sage Intacct OAuth apps/credentials for both Prod and Dev.

**Install**
```bash
uv venv --python 3.11
source .venv/bin/activate
uv sync
cp env.example .env
```

**Configure .env**
- `INTACCT_AUTH_URL_{PROD,DEV}`: usually `https://api.intacct.com/ia/api/v1/oauth2/token`.
- `INTACCT_API_BASE_{PROD,DEV}`: `https://api.intacct.com/ia/api/v1`.
- `INTACCT_COMPANY_ID_{PROD,DEV}`: company IDs for each env.
- `INTACCT_CLIENT_ID_{PROD,DEV}` / `INTACCT_CLIENT_SECRET_{PROD,DEV}`.
- `INTACCT_USERNAME_{PROD,DEV}`: may be `user@company` or `user@company|entity`.
- Optional: `INTACCT_ENTITY_ID_{PROD,DEV}` (adds `X-IA-API-Param-Entity`).
- Optional: `INTACCT_OAUTH_SCOPE_{PROD,DEV}`.
- Optional: `INTACCT_HTTP_TIMEOUT` (default 30), `INTACCT_PAGE_SIZE` (default 200).
- Optional: `INTACCT_DEFAULT_UOM_GROUP_ID_DEV`, `INTACCT_DEFAULT_LOCATION_ID_DEV`.

Paths in `intacct.config.json` should not include `/ia/api/v1`; the base is appended.

**Verify Setup**
```bash
uv run intacctsync verify
```
Performs env/config checks, authenticates to both envs, and does a minimal Items probe in each.

**Supported Entities**
- Objects API: `entities` (create+patch texts.message/customTitle), `departments` (upsert name/status), `locations`, `items`, `customers` (upsert rich fields).
- Service/Objects API: `warehouses`, `uom-groups`, `uom`, `pricelists`, `price-list-entries`.

Notes
- Most entities page via core/query; `--since` generally does not apply to Objects API. Use `--limit` while testing.
- Output legend: `.` = created/updated, `s` = skipped (no change), `!` = error.

**General Sync Command**
```bash
uv run intacctsync sync <entity> [--since YYYY-MM-DD] [--limit N] [--dry-run] [--verbose]
```
Entities: `items | customers | warehouses | pricelists | price-list-entries | entities | departments | locations | uom | uom-groups`.

Examples
- Dry‑run customers with verbose output:
  `uv run intacctsync sync customers --limit 50 --dry-run --verbose`
- Create/update departments (upsert):
  `uv run intacctsync sync departments --limit 100`
- Sync items:
  `uv run intacctsync sync items --limit 200`

Upsert Behavior
- Customers: updates name, email, status, currency, deliveryOptions, emailOptIn, isOnHold, isOneTimeUse, notes, resaleNumber, taxId, creditLimit, overridePriceList, enableOnlineCardPayment, enableOnlineACHPayment, customerRestriction when they differ.
- Departments: updates name/status when they differ.
- Entities: patches `texts.message` and `texts.customTitle` when provided.

Customer Email/Delivery Options
- Intacct requires an email address if `deliveryOptions` includes email. The mapper includes `email` when present and suppresses `deliveryOptions` if it would be inconsistent. If you still see 422s, ensure the source record has an email or change delivery options.

Recommended Order
1) `uom-groups` → 2) `uom` → 3) `locations` + `departments` → 4) `warehouses` → 5) `items` → 6) `customers` → 7) `pricelists` → 8) `price-list-entries` (optional) → 9) `entities` (texts patch).

**Create Shipper (Dev)**
```bash
uv run intacctsync create-shipper \
  --external PROD-PO-12345 \
  --customer-id CUST001 \
  --shipfrom SITE1 \
  --shipto SHIPTO001 \
  --date 2025-08-30 \
  --lines lines.sample.json --dry-run
```
- Endpoint: `POST /oe/v1/company/{company}/documents`.
- Required: `transaction="Shipper"`, `customerId`, `documentDate`, `shipFrom`, `shipTo`, `lines[{ itemId, quantity, memo? }]`.
- All referenced IDs must already exist in Dev.

Performance & Reliability
- Retries with jitter and cooperative handling of HTTP 429 (pauses based on Retry‑After).
- Local SQLite cache (WAL) for token cache and ID/key maps.

Troubleshooting
- 401 after some calls: tokens refresh automatically; if it persists, re‑run `verify` and check client secrets and usernames.
- 422 on Customer create: ensure `email` is present when `deliveryOptions` includes email; otherwise set a non‑email delivery option.
- Pagination appears infinite: core/query uses `ia::meta.next`; ensure your config’s `query.fields` contains the object’s required fields.

Development Tips
- Adjust `intacct.config.json` to add/remove fields per tenant.
- Use `--dry-run` until output shows only the intended creates/updates.
