from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---- API payload models ----


class CustomerCreate(BaseModel):
    id: str
    name: str

    # Core scalar fields (optional)
    status: str | None = None
    currency: str | None = None
    deliveryOptions: str | None = None
    emailOptIn: bool | None = None
    isOnHold: bool | None = None
    isOneTimeUse: bool | None = None
    notes: str | None = None
    resaleNumber: str | int | float | None = None
    taxId: str | None = None
    creditLimit: float | None = None
    overridePriceList: str | None = None
    enableOnlineCardPayment: bool | None = None
    enableOnlineACHPayment: bool | None = None
    customerRestriction: str | None = None

    # Nested contacts (Objects v1 puts email on contact rather than top-level)
    contacts: dict[str, Any] | None = None


# ---- Config models (optional; not yet fully wired) ----


class QueryConfig(BaseModel):
    object: str
    fields: list[str] = Field(default_factory=list)
    pageSize: int | None = None
    orderBy: list[dict[str, Any]] | None = None


class EntityConfig(BaseModel):
    use_query: bool = False
    query: QueryConfig | None = None
    prod_list_path: str | None = None
    dev_create_path: str | None = None
    list_params: dict[str, Any] = Field(default_factory=dict)
    list_data_key: str | None = None
    next_page_key: str | None = None
    since_param: str | None = None


class AppConfig(BaseModel):
    entities: dict[str, EntityConfig]
