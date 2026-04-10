from __future__ import annotations

import json
from typing import Any

import click

from .config import API_BASE_DEV, API_BASE_PROD, COMPANY_DEV, DEFAULT_UOM_GROUP_ID_DEV, DEFAULT_LOCATION_ID_DEV
from .http import http_get, http_patch_json, http_post_json
from .mappers import (
    map_department_create,
    map_customer_create,
    map_item_create,
    map_location_create,
    map_pricelist_create,
    map_pricelist_entry_create,
    map_uom_create,
    map_uom_group_create,
    map_warehouse_create,
)
from .paginate import fetch_all
from .storage import DevIndex, IDMapper, LocationMap, UoMGroupMap


def _find_dev_by_key(entity: str, key_name: str, key_value: str, cfg: dict[str, Any], dt: str) -> dict[str, Any] | None:
    ent = cfg["entities"][entity]
    key_value_n = (key_value or "").strip()
    key_value_l = key_value_n.lower()
    idx = DevIndex()
    dev_key = idx.get(entity, key_value_n)
    if dev_key is not None:
        return {"id": key_value_n, "key": dev_key}
    found: dict[str, Any] | None = None
    for it in fetch_all(ent, API_BASE_DEV, dt, COMPANY_DEV or "", None):
        oid = str(
            it.get("id")
            or it.get(key_name)
            or it.get("customerId")
            or it.get("warehouseId")
            or it.get("uom")
            or it.get("priceListId")
            or ""
        ).strip()
        if not oid:
            continue
        idx.put(entity, oid, str(it.get("key") or ""))
        if oid.lower() == key_value_l and not found:
            found = it
    return found


def ensure_dev_entity(
    entity: str,
    prod_rec: dict[str, Any],
    dt: str,
    dry_run: bool,
    pt: str | None = None,
) -> tuple[str | None, bool]:
    from .config import load_config  # local import to avoid cycles

    cfg = load_config()
    ent = cfg["entities"][entity]
    if entity == "items":
        key_name = "id"
        payload = map_item_create(prod_rec)
        key_val = payload["id"]
    elif entity == "customers":
        key_name = "id"
        payload = map_customer_create(prod_rec)
        key_val = payload["id"]
    elif entity == "warehouses":
        key_name = "id"
        payload = map_warehouse_create(prod_rec)
        key_val = payload["id"]
        # Ensure Location for multi-entity shared warehouses using Prod->Dev map
        loc = prod_rec.get("location") if isinstance(prod_rec.get("location"), dict) else {}
        prod_loc_id = str(loc.get("id") or prod_rec.get("locationId") or "").strip()
        # If location missing from list view, try fetching full record from Prod for this warehouse
        if not prod_loc_id and pt:
            prod_key = str(prod_rec.get("key") or "").strip()
            if prod_key:
                try:
                    detail = http_get(API_BASE_PROD, f"{ent['prod_list_path']}/{prod_key}", pt, {})
                    pobj = detail.get("ia::result") if isinstance(detail, dict) else None
                    if not pobj:
                        pobj = detail
                    if isinstance(pobj, dict):
                        dloc = pobj.get("location") if isinstance(pobj.get("location"), dict) else {}
                        prod_loc_id = str(dloc.get("id") or pobj.get("locationId") or "").strip()
                except Exception:
                    # best-effort; fall through to default handling
                    pass
        dev_loc_id: str | None = None
        if prod_loc_id:
            dev_loc_id = LocationMap().get(prod_loc_id)
            if not dev_loc_id:
                dev_loc = _find_dev_by_key("locations", "id", prod_loc_id, cfg, dt)
                if dev_loc and dev_loc.get("id"):
                    dev_loc_id = str(dev_loc.get("id"))
                    LocationMap().put(prod_loc_id, dev_loc_id)
            if not dev_loc_id:
                raise click.ClickException("Dev Location not found; sync locations first to match Prod IDs")
        else:
            # Fallback to default Dev location if provided
            if DEFAULT_LOCATION_ID_DEV:
                dev_loc = _find_dev_by_key("locations", "id", DEFAULT_LOCATION_ID_DEV, cfg, dt)
                if dev_loc and dev_loc.get("id"):
                    dev_loc_id = str(dev_loc.get("id"))
                else:
                    raise click.ClickException(
                        "Default Dev Location not found; set INTACCT_DEFAULT_LOCATION_ID_DEV to a valid Dev location id and sync locations"
                    )
            else:
                raise click.ClickException(
                    "Warehouse Location required (no Prod location.id). Set INTACCT_DEFAULT_LOCATION_ID_DEV for a fallback."
                )
        payload["location"] = {"id": dev_loc_id}
    elif entity == "uom":
        key_name = "id"
        payload = map_uom_create(prod_rec)
        key_val = payload.get("id") or ""
        # Resolve parent UoM group key in Dev (enforce parent.key always)
        grp_key: str | None = None
        grp_dev_id: str | None = None
        parent = (prod_rec.get("parent") or {}) if isinstance(prod_rec.get("parent"), dict) else {}
        parent_id = str(parent.get("id") or prod_rec.get("parentId") or "").strip()
        # First try persisted map
        if parent_id:
            dev_id_m, dev_key_m = UoMGroupMap().get(parent_id)
            grp_dev_id = dev_id_m
            grp_key = dev_key_m
        if (not grp_key or not grp_dev_id) and parent_id:
            grp = _find_dev_by_key("uom-groups", "id", parent_id, cfg, dt)
            if grp:
                grp_dev_id = str(grp.get("id") or "")
                grp_key = str(grp.get("key") or "")
                UoMGroupMap().put(parent_id, grp_dev_id, grp_key)
        if (not grp_key or not grp_dev_id) and DEFAULT_UOM_GROUP_ID_DEV:
            grp = _find_dev_by_key("uom-groups", "id", DEFAULT_UOM_GROUP_ID_DEV, cfg, dt)
            if grp:
                grp_dev_id = str(grp.get("id") or "")
                grp_key = str(grp.get("key") or "")
        if not grp_dev_id and not grp_key:
            raise click.ClickException(
                "UoM parent group missing: set parent group in Prod or configure INTACCT_DEFAULT_UOM_GROUP_ID_DEV"
            )
        # Use parent.id for this tenant (key is read-only)
        if not grp_dev_id and grp_key:
            # Resolve dev_id from key if only key is known
            grp = _find_dev_by_key("uom-groups", "key", grp_key, cfg, dt)
            grp_dev_id = str(grp.get("id") or "") if grp else ""
        if not grp_dev_id:
            raise click.ClickException("UoM parent group id not found in Dev")
        payload["parent"] = {"id": grp_dev_id}
    elif entity == "pricelists":
        key_name = "priceListId"
        payload = map_pricelist_create(prod_rec)
        key_val = payload["priceListId"]
    elif entity == "product-lines":
        key_name = "id"
        pid = str(prod_rec.get("id") or "").strip()
        pname = prod_rec.get("name") or None
        payload = {"id": pid}
        if pname:
            payload["name"] = pname
        else:
            # Fallback to using id as name when not provided
            payload["name"] = pid
        key_val = payload["id"]
    elif entity == "price-list-entries":
        key_name = "key"
        payload = map_pricelist_entry_create(prod_rec)
        key_val = str(prod_rec.get("key") or "")
        # Resolve Dev ids for references via IDMapper or one-shot lookup
        id_map = IDMapper()
        # Helper to read nested or flattened refs from core/query (e.g., "item": {id} OR "item.id": "...")
        def _ref_id(rec: dict[str, Any], name: str) -> str:
            val = ""
            obj = rec.get(name)
            if isinstance(obj, dict):
                val = str(obj.get("id") or obj.get("key") or "").strip()
            if not val:
                val = str(rec.get(f"{name}.id") or rec.get(f"{name}.key") or "").strip()
            return val

        pl_id = _ref_id(prod_rec, "priceList")
        if pl_id:
            dev_pl_id = id_map.get("pricelists", pl_id)
            if not dev_pl_id:
                found_pl = _find_dev_by_key("pricelists", "priceListId", pl_id, cfg, dt)
                if found_pl and found_pl.get("id"):
                    dev_pl_id = str(found_pl.get("id"))
                    id_map.put("pricelists", pl_id, dev_pl_id)
            if dev_pl_id:
                payload["priceList"] = {"id": dev_pl_id}
        # Prefer item; fallback to productLine if item not present
        it_id = _ref_id(prod_rec, "item")
        dev_it_id: str | None = None
        if it_id:
            dev_it_id = id_map.get("items", it_id)
            if not dev_it_id:
                found_it = _find_dev_by_key("items", "id", it_id, cfg, dt)
                if found_it and found_it.get("id"):
                    dev_it_id = str(found_it.get("id"))
                    id_map.put("items", it_id, dev_it_id)
            # If still not found, auto-create/minimally ensure the item in Dev
            if not dev_it_id:
                # Use item name if provided, else use id as name
                prod_item_stub = {"id": it_id, "name": it_id}
                ensured_id, _created = ensure_dev_entity("items", prod_item_stub, dt, False)
                if ensured_id:
                    dev_it_id = ensured_id
                    id_map.put("items", it_id, dev_it_id)
        if dev_it_id:
            payload["item"] = {"id": dev_it_id}
        else:
            pline_id = _ref_id(prod_rec, "productLine")
            if pline_id:
                dev_pline_id = id_map.get("product-lines", pline_id)
                if not dev_pline_id:
                    found_pline = _find_dev_by_key("product-lines", "id", pline_id, cfg, dt)
                    if found_pline and found_pline.get("id"):
                        dev_pline_id = str(found_pline.get("id"))
                        id_map.put("product-lines", pline_id, dev_pline_id)
                if dev_pline_id:
                    payload["productLine"] = {"id": dev_pline_id}
    elif entity == "departments":
        key_name = "id"
        payload = map_department_create(prod_rec)
        key_val = payload["id"]
    elif entity == "locations":
        key_name = "id"
        payload = map_location_create(prod_rec)
        key_val = payload["id"]
    elif entity == "uom-groups":
        key_name = "id"
        payload = map_uom_group_create(prod_rec)
        key_val = payload["id"]
    else:
        return None, False

    found = _find_dev_by_key(entity, key_name, str(key_val), cfg, dt)
    if found:
        # Persist UoM group mapping when applicable
        if entity == "uom-groups":
            UoMGroupMap().put(str(key_val), str(found.get("id") or ""), str(found.get("key") or ""))
        if entity in ("items", "pricelists", "uom", "locations", "product-lines"):
            IDMapper().put(entity, str(key_val), str(found.get("id") or ""))
        # If locations were found by id, record mapping
        if entity == "locations":
            from .storage import LocationMap as _LM
            _LM().put(str(key_val), str(found.get("id") or ""))
        # Upsert for warehouses: patch name/status if different
        if entity == "warehouses":
            dev_key = str(found.get("key") or "")
            patch: dict[str, Any] = {}
            desired_name = payload.get("name")
            desired_status = payload.get("status")
            curr_name = (found.get("name") if isinstance(found, dict) else None) or None
            curr_status = (found.get("status") if isinstance(found, dict) else None) or None
            if (desired_name is not None and desired_name != curr_name) or (
                desired_status is not None and desired_status != curr_status
            ):
                if desired_name is not None and desired_name != curr_name:
                    patch["name"] = desired_name
                if desired_status is not None and desired_status != curr_status:
                    patch["status"] = desired_status
                if patch and dev_key:
                    if dry_run:
                        click.echo(
                            f"DRY RUN - Would update warehouses {key_val} (key {dev_key}): {json.dumps(patch)}"
                        )
                    else:
                        http_patch_json(API_BASE_DEV, f"{ent['prod_list_path']}/{dev_key}", dt, patch)
                    return str(found.get("id") or found.get(key_name)), True
        # Upsert for departments: patch name/status if different
        if entity == "departments":
            dev_key = str(found.get("key") or "")
            patch: dict[str, Any] = {}
            desired_name = payload.get("name")
            desired_status = payload.get("status")
            # Prefer using fields from list result; fallback to GET if missing
            curr_name = (found.get("name") if isinstance(found, dict) else None) or None
            curr_status = (found.get("status") if isinstance(found, dict) else None) or None
            if (desired_name is not None and desired_name != curr_name) or (
                desired_status is not None and desired_status != curr_status
            ):
                if desired_name is not None and desired_name != curr_name:
                    patch["name"] = desired_name
                if desired_status is not None and desired_status != curr_status:
                    patch["status"] = desired_status
                if patch and dev_key:
                    if dry_run:
                        click.echo(
                            f"DRY RUN - Would update departments {key_val} (key {dev_key}): {json.dumps(patch)}"
                        )
                    else:
                        http_patch_json(API_BASE_DEV, f"{ent['prod_list_path']}/{dev_key}", dt, patch)
                    return str(found.get("id") or found.get(key_name)), True
        # Upsert for customers: patch selected fields if different
        if entity == "customers":
            dev_key = str(found.get("key") or "")
            patch: dict[str, Any] = {}
            for k in (
                "name",
                "status",
                "currency",
                "deliveryOptions",
                "emailOptIn",
                "isOnHold",
                "isOneTimeUse",
                "notes",
                "resaleNumber",
                "taxId",
                "creditLimit",
                "overridePriceList",
                "enableOnlineCardPayment",
                "enableOnlineACHPayment",
            ):
                if k in payload and payload.get(k) != found.get(k):
                    patch[k] = payload.get(k)
            # Email lives under contacts.default.email1 for v1
            contacts = payload.get("contacts") if isinstance(payload, dict) else None
            default_email = (
                ((contacts or {}).get("default") or {}).get("email1") if isinstance(contacts, dict) else None
            )
            if default_email:
                patch["contacts"] = {"default": {"email1": default_email}}
            if patch and dev_key:
                if dry_run:
                    click.echo(
                        f"DRY RUN - Would update customers {key_val} (key {dev_key}): {json.dumps(patch)}"
                    )
                else:
                    http_patch_json(API_BASE_DEV, f"{ent['prod_list_path']}/{dev_key}", dt, patch)
                return str(found.get("id") or found.get(key_name)), True
        return str(found.get("id") or found.get(key_name)), False

    if dry_run:
        click.echo(f"DRY RUN - Would create {entity}: {json.dumps(payload)}")
        return None, False
    if entity == "price-list-entries":
        created = http_post_json(API_BASE_DEV, ent["dev_create_path"], dt, payload)
        return (str(created.get("id") or key_val) or None), True
    created = http_post_json(API_BASE_DEV, ent["dev_create_path"], dt, payload)
    idx = DevIndex()
    new_id = str(payload.get("id") or payload.get(key_name) or "")
    created_ref = created.get("ia::result") if isinstance(created, dict) else None
    new_key = None
    if isinstance(created_ref, dict):
        new_key = str(created_ref.get("key") or "")
    idx.put(entity, new_id, new_key)
    if entity == "uom-groups":
        # Newly created group: map prod_id -> dev_id/key (ids are same if you mirror IDs)
        UoMGroupMap().put(str(key_val), new_id, str(new_key or ""))
    if entity in ("items", "pricelists", "uom", "locations", "product-lines"):
        IDMapper().put(entity, str(key_val), new_id)
    return (str(created.get("id") or created.get(key_name) or new_id) or None), True
