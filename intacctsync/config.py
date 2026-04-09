from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("INTACCTSYNC_DB", "intacctsync.sqlite3")
CONFIG_PATH = Path("intacct.config.json")

# Envs
AUTH_URL_PROD = os.getenv("INTACCT_AUTH_URL_PROD", "https://api.intacct.com/ia/api/v1/oauth2/token")
AUTH_URL_DEV = os.getenv("INTACCT_AUTH_URL_DEV", "https://api.intacct.com/ia/api/v1/oauth2/token")
API_BASE_PROD = os.getenv("INTACCT_API_BASE_PROD", "https://api.intacct.com/ia/api/v1")
API_BASE_DEV = os.getenv("INTACCT_API_BASE_DEV", "https://api.intacct.com/ia/api/v1")
COMPANY_PROD = os.getenv("INTACCT_COMPANY_ID_PROD")
COMPANY_DEV = os.getenv("INTACCT_COMPANY_ID_DEV")
CLIENT_ID_PROD = os.getenv("INTACCT_CLIENT_ID_PROD")
CLIENT_SECRET_PROD = os.getenv("INTACCT_CLIENT_SECRET_PROD")
CLIENT_ID_DEV = os.getenv("INTACCT_CLIENT_ID_DEV")
CLIENT_SECRET_DEV = os.getenv("INTACCT_CLIENT_SECRET_DEV")
USERNAME_PROD = os.getenv("INTACCT_USERNAME_PROD")
USERNAME_DEV = os.getenv("INTACCT_USERNAME_DEV")
ENTITY_ID_PROD = os.getenv("INTACCT_ENTITY_ID_PROD")
ENTITY_ID_DEV = os.getenv("INTACCT_ENTITY_ID_DEV")
SCOPE_PROD = os.getenv("INTACCT_OAUTH_SCOPE_PROD", "")
SCOPE_DEV = os.getenv("INTACCT_OAUTH_SCOPE_DEV", "")
HTTP_TIMEOUT = int(os.getenv("INTACCT_HTTP_TIMEOUT", "30"))
PAGE_SIZE = int(os.getenv("INTACCT_PAGE_SIZE", "200"))
DEFAULT_UOM_GROUP_ID_DEV = os.getenv("INTACCT_DEFAULT_UOM_GROUP_ID_DEV", "")
DEFAULT_LOCATION_ID_DEV = os.getenv("INTACCT_DEFAULT_LOCATION_ID_DEV", "")

REQUIRED_ENVS = [
    ("INTACCT_AUTH_URL_PROD", AUTH_URL_PROD),
    ("INTACCT_AUTH_URL_DEV", AUTH_URL_DEV),
    ("INTACCT_API_BASE_PROD", API_BASE_PROD),
    ("INTACCT_API_BASE_DEV", API_BASE_DEV),
    ("INTACCT_COMPANY_ID_PROD", COMPANY_PROD),
    ("INTACCT_COMPANY_ID_DEV", COMPANY_DEV),
    ("INTACCT_CLIENT_ID_PROD", CLIENT_ID_PROD),
    ("INTACCT_CLIENT_SECRET_PROD", CLIENT_SECRET_PROD),
    ("INTACCT_CLIENT_ID_DEV", CLIENT_ID_DEV),
    ("INTACCT_CLIENT_SECRET_DEV", CLIENT_SECRET_DEV),
    ("INTACCT_USERNAME_PROD", USERNAME_PROD),
    ("INTACCT_USERNAME_DEV", USERNAME_DEV),
]


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("intacct.config.json not found")
    return json.loads(CONFIG_PATH.read_text())
