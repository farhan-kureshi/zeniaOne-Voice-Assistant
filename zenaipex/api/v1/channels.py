"""
Zenaipex AI — Channels API router.

GET    /api/v1/companies/{id}/channels
POST   /api/v1/companies/{id}/channels
GET    /api/v1/companies/{id}/channels/{cid}
PATCH  /api/v1/companies/{id}/channels/{cid}
DELETE /api/v1/companies/{id}/channels/{cid}
"""
from fastapi import APIRouter, Depends, Path, Query
from typing import Optional

from core.dependencies import get_auth_context, AuthContext
from core.exceptions import NotFoundError, InsufficientPermissionsError
from models.channel import ChannelCreate, ChannelUpdate, ChannelResponse
from services import channel_service

router = APIRouter(tags=["Channels"])


def _fmt(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": doc["company_id"],
        "agent_id": doc["agent_id"],
        "name": doc["name"],
        "type": doc["type"],
        "phone_number": doc.get("phone_number"),
        "public_identifier": doc.get("public_identifier"),
        "has_custom_twilio": bool(doc.get("twilio_account_sid")),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.post(
    "/companies/{company_id}/channels",
    response_model=ChannelResponse,
    summary="Create a new channel",
)
async def create_channel(
    body: ChannelCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    # Only Admin or Owner can create channels
    if not ctx.is_admin:
        raise InsufficientPermissionsError("Requires admin privileges")

    channel_doc = await channel_service.create_channel(company_id, body.dict(exclude_unset=True))
    return _fmt(channel_doc)


@router.get(
    "/companies/{company_id}/channels",
    summary="List channels",
)
async def list_channels(
    company_id: str = Path(...),
    type: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=100),
    ctx: AuthContext = Depends(get_auth_context),
):
    channels = await channel_service.list_channels(company_id, type=type, skip=skip, limit=limit)
    return {"channels": [_fmt(c) for c in channels], "count": len(channels)}


@router.get(
    "/companies/{company_id}/channels/{channel_id}",
    response_model=ChannelResponse,
    summary="Get channel details",
)
async def get_channel(
    company_id: str = Path(...),
    channel_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    channel = await channel_service.get_channel(company_id, channel_id)
    if not channel:
        raise NotFoundError("Channel")
    return _fmt(channel)


@router.patch(
    "/companies/{company_id}/channels/{channel_id}",
    response_model=ChannelResponse,
    summary="Update channel",
)
async def update_channel(
    body: ChannelUpdate,
    company_id: str = Path(...),
    channel_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.is_admin:
        raise InsufficientPermissionsError("Requires admin privileges")

    channel = await channel_service.update_channel(company_id, channel_id, body.dict(exclude_unset=True))
    if not channel:
        raise NotFoundError("Channel")
    return _fmt(channel)


@router.delete(
    "/companies/{company_id}/channels/{channel_id}",
    summary="Delete channel",
)
async def delete_channel(
    company_id: str = Path(...),
    channel_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.is_admin:
        raise InsufficientPermissionsError("Requires admin privileges")

    deleted = await channel_service.delete_channel(company_id, channel_id)
    if not deleted:
        raise NotFoundError("Channel")
    return {"success": True}
