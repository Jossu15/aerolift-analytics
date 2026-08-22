"""Credential introspection for minted API keys."""

from fastapi import APIRouter, Depends

from api import models
from api.auth import get_current_key

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def whoami(key: models.ApiKey = Depends(get_current_key)):
    """Confirm a key works and show its tier/label (never the raw key)."""
    return {"id": key.id, "label": key.label,
            "field_name": key.field_name, "tier": key.tier,
            "is_active": key.is_active}
