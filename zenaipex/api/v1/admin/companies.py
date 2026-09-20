from fastapi import APIRouter, HTTPException
from core.database import (
    col_companies, col_users, col_agents, col_conversations, col_team_members, col_documents,
    col_subscriptions, col_knowledge_bases, col_channels, col_messages, col_usage_records,
    col_scheduled_calls, col_timing_metrics, col_activity_logs
)
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies")

def _fmt_company(doc: dict, owner: dict = None, stats: dict = None) -> dict:
    result = {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "slug": doc["slug"],
        "industry": doc.get("industry"),
        "country": doc.get("country"),
        "plan": doc.get("plan", "free_trial"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
    if owner:
        result["owner_name"] = owner.get("name", "Unknown")
        result["owner_email"] = owner.get("email", "")
    if stats:
        result.update(stats)
    return result

@router.get("")
async def list_companies():
    """List all companies with owner and resource stats."""
    cursor = col_companies().find({}).sort("created_at", -1)
    companies = []
    async for doc in cursor:
        company_id = str(doc["_id"])
        
        # Find the owner from team_members
        owner_membership = await col_team_members().find_one(
            {"company_id": company_id, "role": "owner"}
        )
        owner = None
        if owner_membership:
            try:
                owner = await col_users().find_one({"_id": ObjectId(owner_membership["user_id"])})
            except Exception:
                pass
        
        agents_count = await col_agents().count_documents({"company_id": company_id})
        conversations_count = await col_conversations().count_documents({"company_id": company_id})
        documents_count = await col_documents().count_documents({"company_id": company_id})
        
        stats = {
            "agents_count": agents_count,
            "conversations_count": conversations_count,
            "documents_count": documents_count,
        }
        companies.append(_fmt_company(doc, owner=owner, stats=stats))
    return {"companies": companies}

@router.get("/{company_id}")
async def get_company(company_id: str):
    """Get company details along with full stats."""
    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    owner_membership = await col_team_members().find_one(
        {"company_id": company_id, "role": "owner"}
    )
    owner = None
    if owner_membership:
        try:
            owner = await col_users().find_one({"_id": ObjectId(owner_membership["user_id"])})
        except Exception:
            pass
    
    agents_count = await col_agents().count_documents({"company_id": company_id})
    conversations_count = await col_conversations().count_documents({"company_id": company_id})
    documents_count = await col_documents().count_documents({"company_id": company_id})
    
    # Get all team members
    team = []
    async for member in col_team_members().find({"company_id": company_id}):
        user = None
        try:
            user = await col_users().find_one({"_id": ObjectId(member["user_id"])})
        except Exception:
            pass
        if user:
            team.append({
                "user_id": str(user["_id"]),
                "name": user.get("name"),
                "email": user.get("email"),
                "role": member.get("role"),
                "joined_at": member.get("joined_at"),
            })
    
    fmt = _fmt_company(company, owner=owner)
    fmt["stats"] = {
        "agents_count": agents_count,
        "conversations_count": conversations_count,
        "documents_count": documents_count,
    }
    fmt["team"] = team
    return fmt

@router.patch("/{company_id}/status")
async def update_company_status(company_id: str, payload: dict):
    """Update company active status."""
    is_active = payload.get("is_active", True)
    result = await col_companies().update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"is_active": is_active}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"success": True, "is_active": is_active}

@router.patch("/{company_id}/subscription")
async def update_company_subscription(company_id: str, payload: dict):
    """Update company subscription plan."""
    plan = payload.get("plan")
    if not plan:
        raise HTTPException(status_code=400, detail="Plan is required")
        
    from services.tenant_service import upgrade_plan
    from core.exceptions import NotFoundError
    
    try:
        success = await upgrade_plan(company_id, plan)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update subscription")
        return {"success": True, "plan": plan}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{company_id}")
async def delete_company(company_id: str):
    """Permanently delete a company and all associated resources."""
    if company_id == "6a990b403e9b17bef89acf87":
        raise HTTPException(status_code=403, detail="The INTERNAL / PLATFORM company cannot be deleted.")

    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Proceed with deletion sweep
    from ai.vector_store import NamespacedVectorStore

    try:
        # Delete Pinecone namespaces for any KBs this company owns
        kbs = await col_knowledge_bases().find({"company_id": company_id}).to_list(None)
        for kb in kbs:
            namespace = kb.get("pinecone_namespace")
            if namespace:
                try:
                    vs = NamespacedVectorStore(namespace=namespace)
                    vs._get_index().delete(delete_all=True, namespace=namespace)
                    logger.info(f"Cleared Pinecone namespace {namespace} for deleted company {company_id}")
                except Exception as e:
                    logger.warning(f"Failed to clear Pinecone namespace {namespace}: {e}")

        # Cascade deletes
        filter_query = {"company_id": company_id}
        
        await col_team_members().delete_many(filter_query)
        await col_subscriptions().delete_many(filter_query)
        await col_agents().delete_many(filter_query)
        await col_knowledge_bases().delete_many(filter_query)
        await col_documents().delete_many(filter_query)
        await col_channels().delete_many(filter_query)
        
        # Messages usually use conversation_id or company_id. If only conversation_id, we should fetch convos.
        # But our DB schema for col_messages likely includes company_id since it's tenant-isolated.
        await col_messages().delete_many(filter_query)
        await col_conversations().delete_many(filter_query)
        await col_usage_records().delete_many(filter_query)
        await col_scheduled_calls().delete_many(filter_query)
        await col_timing_metrics().delete_many(filter_query)
        
        # Finally delete company itself
        await col_companies().delete_one({"_id": ObjectId(company_id)})
        
        # Log the deletion as an admin action
        await col_activity_logs().insert_one({
            "action": "company_deleted",
            "company_id": company_id,
            "details": f"Company {company['name']} was permanently deleted.",
            # Note: The `get_platform_admin` doesn't pass the current admin to the endpoint directly in kwargs here unless we ask for it,
            # but we can omit it or update the endpoint signature to include current_user.
        })
        
        logger.info(f"Successfully deleted company {company_id} and all associated data.")
        return {"success": True, "message": "Company and all associated data permanently deleted."}
    except Exception as e:
        logger.error(f"Error deleting company {company_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete company")
