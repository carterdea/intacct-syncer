from __future__ import annotations

import json
from typing import Any
from tenacity import RetryError

import click

from .config import (
    API_BASE_DEV,
    API_BASE_PROD,
    COMPANY_PROD,
    REQUIRED_ENVS,
    load_config,
)
from .http import dev_token, http_get, http_patch_json, http_post_json, prod_token
from .paginate import fetch_all


def _format_error(exc: Exception) -> str:
    if isinstance(exc, RetryError):
        try:
            inner = exc.last_attempt.exception()
            return str(inner)
        except Exception:
            return str(exc)
    return str(exc)
from .sync_engine import ensure_dev_entity


@click.group()
def cli() -> None:
    """Intacct Prod → Dev syncer (Items, Customers, Warehouses, Price Lists) and Shipper create"""
    pass


@cli.command()
def verify() -> None:
    """Check env + config + authenticate; basic GET probe on items."""
    missing = [k for k, v in REQUIRED_ENVS if not v]
    if missing:
        click.echo(f"Missing env vars: {', '.join(missing)}")
        raise SystemExit(1)
    try:
        cfg = load_config()
    except Exception as e:  # noqa: BLE001
        click.echo(f"Config error: {e}")
        raise SystemExit(1) from e
    try:
        pt = prod_token()
        click.echo("Production authentication OK")
    except Exception as e:  # noqa: BLE001
        click.echo(f"Production auth failed: {e}")
        raise SystemExit(1) from e
    try:
        dev_token()
        click.echo("Development authentication OK")
    except Exception as e:  # noqa: BLE001
        click.echo(f"Development auth failed: {e}")
        raise SystemExit(1) from e
    try:
        ent = cfg["entities"]["items"]
        params: dict[str, Any] = {}
        if not str(ent["prod_list_path"]).startswith("/objects/"):
            params = {"page": 1, "pageSize": 1}
        _ = http_get(API_BASE_PROD, ent["prod_list_path"], pt, params)
        click.echo("Production API connection OK")
    except Exception as e:  # noqa: BLE001
        click.echo(f"Production API test failed: {e}")
        raise SystemExit(1) from e
    try:
        params_dev: dict[str, Any] = {}
        if not str(ent["prod_list_path"]).startswith("/objects/"):
            params_dev = {"page": 1, "pageSize": 1}
        _ = http_get(API_BASE_DEV, ent["prod_list_path"], dev_token(), params_dev)
        click.echo("Development API connection OK")
    except Exception as e:  # noqa: BLE001
        click.echo(f"Development API test failed: {e}")
        raise SystemExit(1) from e
    click.echo("All checks passed. Ready to sync.")


@cli.command()
@click.argument(
    "entity",
    type=click.Choice([
        "items",
        "uom",
        "uom-groups",
        "customers",
        "warehouses",
        "pricelists",
        "product-lines",
        "price-list-entries",
        "entities",
        "departments",
        "locations",
    ]),
)
@click.option("--since")
@click.option("--limit", type=int, default=0)
@click.option("--dry-run", is_flag=True)
@click.option("--verbose", is_flag=True)
def sync(entity: str, since: str | None, limit: int, dry_run: bool, verbose: bool) -> None:
    """Sync from Prod to Dev for selected entity (minimal mapping)."""
    cfg = load_config()
    ent = cfg["entities"][entity]
    pt = prod_token()
    dt = dev_token()

    if entity == "entities":
        count = 0
        updated = 0
        created = 0
        errors = 0
        errors_details: list[str] = []
        would_create = 0
        click.echo("Legend: .=created/updated s=skipped !=error")
        for ref in fetch_all(ent, API_BASE_PROD, pt, COMPANY_PROD or "", since):
            count += 1
            try:
                prod_id = str(ref.get("id") or "")
                prod_key = str(ref.get("key") or "")
                if not prod_id or not prod_key:
                    continue
                prod_detail = http_get(API_BASE_PROD, f"{ent['prod_list_path']}/{prod_key}", pt, {})
                pobj = prod_detail.get("ia::result") if isinstance(prod_detail, dict) else None
                if not pobj:
                    pobj = prod_detail
                ptxt = (pobj or {}).get("texts") or {}
                msg = ptxt.get("message")
                title = ptxt.get("customTitle")
                dev_ref = _find_dev_by_id(dt, prod_id, cfg)
                if not dev_ref:
                    payload = {"id": prod_id, "name": prod_id}
                    texts_payload: dict[str, Any] = {}
                    if msg is not None:
                        texts_payload["message"] = msg
                    if title is not None:
                        texts_payload["customTitle"] = title
                    if texts_payload:
                        payload["texts"] = texts_payload
                    if dry_run:
                        click.echo(f"DRY RUN - Would create entities: {json.dumps(payload)}")
                        would_create += 1
                    else:
                        try:
                            http_post_json(API_BASE_DEV, ent["dev_create_path"], dt, payload)
                            created += 1
                            click.echo(".", nl=False)
                        except Exception as ce:  # noqa: BLE001
                            errors += 1
                            if verbose:
                                click.echo(f"Create entity failed for {prod_id}: {ce}")
                    continue
                dev_key = str(dev_ref.get("key") or "")
                dev_detail = http_get(API_BASE_DEV, f"{ent['prod_list_path']}/{dev_key}", dt, {})
                dobj = dev_detail.get("ia::result") if isinstance(dev_detail, dict) else None
                if not dobj:
                    dobj = dev_detail
                dtxt = (dobj or {}).get("texts") or {}
                needs_update = False
                payload: dict[str, Any] = {"texts": {}}
                if msg is not None and msg != dtxt.get("message"):
                    payload["texts"]["message"] = msg
                    needs_update = True
                if title is not None and title != dtxt.get("customTitle"):
                    payload["texts"]["customTitle"] = title
                    needs_update = True
                if needs_update:
                    if dry_run:
                        click.echo(f"DRY RUN - Would update entity {prod_id} (key {dev_key}): {json.dumps(payload)}")
                    else:
                        http_patch_json(API_BASE_DEV, f"{ent['prod_list_path']}/{dev_key}", dt, payload)
                        click.echo(".", nl=False)
                    updated += 1
                else:
                    click.echo("s", nl=False)
                    if verbose:
                        click.echo(f" skipped: entities {prod_id}")
            except Exception as e:  # noqa: BLE001
                errors += 1
                errors_details.append(f"entities {prod_id or prod_key}: {e}")
                click.echo("!", nl=False)
                if verbose:
                    click.echo(f"Error updating entity {ref}: {_format_error(e)}")
            if limit and count >= limit:
                break
        click.echo("")
        click.echo(
            json.dumps(
                {"entity": entity, "processed": count, "created": created, "updated": updated, "would_create": would_create, "errors": errors},
                indent=2,
            )
        )
        if errors_details:
            click.echo("Errors:")
            for msg in errors_details:
                click.echo(f"- {msg}")
        return

    click.echo("Legend: .=created/updated s=skipped !=error")
    count = 0
    created = 0
    errors = 0
    errors_details: list[str] = []
    for rec in fetch_all(ent, API_BASE_PROD, pt, COMPANY_PROD or "", since):
        count += 1
        try:
            res_id, was_created = ensure_dev_entity(entity, rec, dt, dry_run, pt)
            if not dry_run:
                if was_created:
                    created += 1
                    click.echo(".", nl=False)
                else:
                    click.echo("s", nl=False)
                    if verbose:
                        rid = str(rec.get("id") or rec.get("customerId") or rec.get("itemNo") or rec.get("warehouseId") or rec.get("uom") or rec.get("priceListId") or "")
                        click.echo(f" skipped: {entity} {rid}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            rid = str(rec.get("id") or rec.get("customerId") or rec.get("itemNo") or rec.get("warehouseId") or rec.get("uom") or rec.get("priceListId") or "")
            errors_details.append(f"{entity} {rid}: {e}")
            click.echo("!", nl=False)
            if verbose:
                click.echo(f"Error on record: {_format_error(e)}")
        if limit and count >= limit:
            break
    click.echo("")
    click.echo(
        json.dumps(
            {"entity": entity, "processed": count, "created_or_updated": created, "errors": errors},
            indent=2,
        )
    )
    if errors_details:
        click.echo("Errors:")
        for msg in errors_details:
            click.echo(f"- {msg}")


def _find_dev_by_id(dt: str, prod_id: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    ent = cfg["entities"]["entities"]
    # Minimal scan via query
    for ref in fetch_all(ent, API_BASE_DEV, dt, COMPANY_PROD or "", None):
        if str(ref.get("id") or "") == prod_id:
            return ref
    return None


@cli.command("create-shipper")
@click.option("--external", required=True, help="External correlation id (e.g., PROD-PO-123)")
@click.option("--customer-id", required=True)
@click.option("--shipfrom", required=True, help="Warehouse/Site code")
@click.option("--shipto", required=True, help="Ship-to contact or id")
@click.option("--date", required=True, help="ISO date (YYYY-MM-DD)")
@click.option("--lines", type=click.Path(exists=True), required=True, help="JSON file: [{ itemId, quantity, memo? }]")
@click.option("--dry-run", is_flag=True)
@click.option("--verbose", is_flag=True)
def create_shipper(external: str, customer_id: str, shipfrom: str, shipto: str, date: str, lines: str, dry_run: bool, verbose: bool) -> None:
    """Create an OE Named Document (Shipper) in Dev using config path. Defaults to dry-run."""
    dt = dev_token()
    doc_path = "/oe/v1/company/{company}/documents"
    try:
        with open(lines, encoding="utf-8") as f:
            line_items = json.load(f)
    except Exception as e:  # noqa: BLE001
        click.echo(f"Failed to read lines file: {e}")
        raise SystemExit(1) from e
    items_mapped = []
    for ln in line_items:
        items_mapped.append(
            {
                "itemId": ln.get("itemId") or ln.get("item") or ln.get("itemNo"),
                "quantity": ln.get("quantity") or ln.get("qty") or 0,
                **({"memo": ln.get("memo")} if ln.get("memo") else {}),
            }
        )
    payload = {
        "transaction": "Shipper",
        "externalId": external,
        "customerId": customer_id,
        "documentDate": date,
        "shipFrom": shipfrom,
        "shipTo": shipto,
        "lines": items_mapped,
    }
    if dry_run:
        click.echo("DRY RUN - Shipper payload:")
        click.echo(json.dumps(payload, indent=2))
        return
    try:
        res = http_post_json(API_BASE_DEV, doc_path, dt, payload)
        click.echo(json.dumps({"result": res}, indent=2))
    except Exception as e:  # noqa: BLE001
        click.echo(f"Create shipper failed: {e}")
        raise SystemExit(1) from e
