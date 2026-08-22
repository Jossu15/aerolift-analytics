"""
API-key authentication and tier gating.

Keys are random opaque strings ("aero_..." + urlsafe token). Only their
SHA-256 hash is persisted, so a leaked database does not leak credentials.
Every /api/* request must carry the raw key in the X-API-Key header.

Tiers gate advanced endpoints: basic = daily monitoring + alerts
(loading, traverse, SCADA); pro adds nodal analysis, forecasting and
everything built on top of them (reports, ML overlay).
"""

import hashlib
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api import models
from api.database import get_db

KEY_PREFIX = "aero_"
TIER_RANK = {"basic": 1, "pro": 2}


def generate_raw_key():
    """One-time visible credential; only the hash reaches the database."""
    return KEY_PREFIX + secrets.token_urlsafe(30)


def hash_key(raw_key):
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_key(x_api_key: Optional[str] = Header(default=None),
                    db: Session = Depends(get_db)) -> models.ApiKey:
    if not x_api_key:
        raise HTTPException(401, "missing X-API-Key header")
    row = db.query(models.ApiKey).filter(
        models.ApiKey.key_hash == hash_key(x_api_key)).one_or_none()
    if row is None or not row.is_active:
        raise HTTPException(401, "invalid or inactive API key")
    return row


def require_tier(minimum: str):
    minimum_rank = TIER_RANK[minimum]

    def dependency(
            key: models.ApiKey = Depends(get_current_key)) -> models.ApiKey:
        if TIER_RANK.get(key.tier, 0) < minimum_rank:
            raise HTTPException(
                403, "endpoint requires '{}' tier (key tier: '{}')"
                     .format(minimum, key.tier))
        return key

    return dependency


def owns_well(well: models.Well, key: models.ApiKey) -> bool:
    """Legacy rows (owner NULL) stay reachable; owned rows check strictly."""
    return well.owner_key_id is None or well.owner_key_id == key.id
