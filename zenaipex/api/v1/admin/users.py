from fastapi import APIRouter, HTTPException
from core.database import col_users
from bson import ObjectId

router = APIRouter(prefix="/users")

def _fmt_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "email": doc["email"],
        "name": doc.get("name", ""),
        "is_verified": doc.get("is_verified", False),
        "is_platform_admin": doc.get("is_platform_admin", False),
        "created_at": doc.get("created_at"),
        "last_login_at": doc.get("last_login_at"),
    }

@router.get("")
async def list_users():
    """List all platform users."""
    cursor = col_users().find({}).sort("created_at", -1)
    users = []
    async for doc in cursor:
        users.append(_fmt_user(doc))
    return {"users": users}

@router.patch("/{user_id}/status")
async def update_user_status(user_id: str, payload: dict):
    """Toggle user active/verified status or platform admin."""
    updates = {}
    if "is_platform_admin" in payload:
        updates["is_platform_admin"] = payload["is_platform_admin"]
        
    if not updates:
        return {"success": False, "message": "No valid fields to update"}
        
    result = await col_users().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "updates": updates}
