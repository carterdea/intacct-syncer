from __future__ import annotations

from typing import Any

from .models import CustomerCreate


def map_item_create(prod: dict[str, Any]) -> dict[str, Any]:
    # Objects API fields
    payload: dict[str, Any] = {
        "id": prod.get("id") or prod.get("code") or prod.get("itemNo") or prod.get("itemno"),
        "name": prod.get("name") or prod.get("description") or "Unknown Item",
    }
    status = prod.get("status")
    if status is not None:
        payload["status"] = status
    return payload


def map_customer_create(prod: dict[str, Any]) -> dict[str, Any]:
    """Map Prod customer to minimal-but-rich create payload without optional references."""
    cid = prod.get("id") or prod.get("customerId") or prod.get("customerid")
    name = prod.get("name") or cid or "Customer"
    # Email can appear as nested contact in Objects v1
    email = (
        (prod.get("email") or prod.get("contacts.default.email1") or "").strip()
    )
    model = CustomerCreate(
        id=str(cid),
        name=str(name),
        status=prod.get("status"),
        currency=prod.get("currency"),
        # Intacct requires email if delivery option includes email; only set when consistent
        deliveryOptions=(
            prod.get("deliveryOptions")
            if not (str(prod.get("deliveryOptions") or "").lower().find("email") >= 0 and not (prod.get("email") or ""))
            else None
        ),
        emailOptIn=prod.get("emailOptIn"),
        isOnHold=prod.get("isOnHold"),
        isOneTimeUse=prod.get("isOneTimeUse"),
        notes=prod.get("notes"),
        resaleNumber=prod.get("resaleNumber"),
        taxId=prod.get("taxId"),
        creditLimit=prod.get("creditLimit"),
        overridePriceList=prod.get("overridePriceList"),
        enableOnlineCardPayment=prod.get("enableOnlineCardPayment"),
        enableOnlineACHPayment=prod.get("enableOnlineACHPayment"),
        # Skip customerRestriction on create unless we also map specific restrictions
        # (tenant may require at least one restriction when this is set)
        customerRestriction=None,
        contacts=(
            {"default": {"email1": email}}
            if email
            else None
        ),
    )
    return model.model_dump(exclude_none=True)


def map_warehouse_create(prod: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": prod.get("id") or prod.get("warehouseId") or prod.get("code"),
        "name": prod.get("name") or prod.get("description") or "Warehouse",
    }
    status = prod.get("status")
    if status is not None:
        payload["status"] = status
    return payload


def map_uom_create(prod: dict[str, Any]) -> dict[str, Any]:
    uid = str(prod.get("id") or prod.get("uom") or prod.get("code") or prod.get("name") or "").strip()
    abbr = prod.get("abbreviation") or (uid[:3] if uid else None)
    ndp = prod.get("numberOfDecimalPlaces")
    try:
        if ndp is not None:
            ndp = int(ndp)
    except Exception:
        ndp = None
    conv = prod.get("conversionFactor")
    try:
        if conv is not None:
            conv = float(conv)
    except Exception:
        conv = None
    payload: dict[str, Any] = {"id": uid}
    if abbr:
        payload["abbreviation"] = abbr
    if ndp is not None:
        payload["numberOfDecimalPlaces"] = ndp
    if conv is not None:
        payload["conversionFactor"] = conv
    else:
        payload["conversionFactor"] = 1
    return payload


def map_pricelist_create(prod: dict[str, Any]) -> dict[str, Any]:
    # Order Entry Price List (sales/order-entry/price-list)
    plid = prod.get("priceListId") or prod.get("id") or prod.get("code")
    name = prod.get("name") or None
    status = prod.get("status") or None  # expects "active"/"inactive"
    payload: dict[str, Any] = {"priceListId": plid}
    if name:
        payload["name"] = name
    if status:
        payload["status"] = status
    return payload


def map_pricelist_entry_create(prod: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal price list entry payload. This is best-effort; adjust per tenant.

    Expected fields per API v1: priceList, item/productLine (one required), unitOfMeasure (optional),
    value, valueType, isFixedPrice, startDate/endDate, plus optional currency, qty ranges, status.
    Note: "appliesTo" is not present in v1 and must be omitted.
    """
    payload: dict[str, Any] = {}
    # Refs
    pl = prod.get("priceList") or {}
    it = prod.get("item") or {}
    pline = prod.get("productLine") or {}
    uom = prod.get("unitOfMeasure") or {}
    if pl.get("id"):
        payload["priceList"] = {"id": pl.get("id")}
    if it.get("id"):
        payload["item"] = {"id": it.get("id")}
    if pline.get("id"):
        payload["productLine"] = {"id": pline.get("id")}
    if uom.get("id"):
        payload["unitOfMeasure"] = {"id": uom.get("id")}
    # Scalars (omit unsupported fields like "appliesTo" in v1)
    for k in (
        "value",
        "valueType",
        "isFixedPrice",
        "minimumQuantity",
        "maximumQuantity",
        "currency",
        "status",
        "startDate",
        "endDate",
    ):
        if k in prod and prod.get(k) is not None:
            payload[k] = prod.get(k)
    return payload


def map_uom_group_create(prod: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(prod.get("id") or "").strip(),
    }
    status = prod.get("status")
    if status is not None:
        payload["status"] = status
    return payload


def map_department_create(prod: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(prod.get("id") or prod.get("departmentId") or "").strip(),
        "name": str(prod.get("name") or prod.get("description") or "Department"),
    }
    status = prod.get("status")
    if status is not None:
        payload["status"] = status
    return payload


def map_location_create(prod: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(prod.get("id") or prod.get("locationId") or "").strip(),
        "name": str(prod.get("name") or prod.get("description") or "Location"),
    }
    status = prod.get("status")
    if status is not None:
        payload["status"] = status
    return payload
