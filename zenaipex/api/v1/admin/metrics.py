from fastapi import APIRouter
from core.database import (
    col_companies, col_users, col_agents, col_conversations,
    col_documents, col_knowledge_bases, col_messages, col_usage_records,
    col_platform_settings, col_llm_requests
)
from typing import Optional
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/metrics")

@router.get("")
async def get_metrics(company_id: Optional[str] = None, days: int = 30):
    """Get platform-wide aggregated metrics with optional filters."""
    from services.usage_service import get_canonical_analytics
    # Default to "all" if no company_id is provided or if it's explicitly "all"
    target_company = "all" if not company_id or company_id == "all" else company_id
    metrics = await get_canonical_analytics(company_id=target_company, days=days)
    return metrics

@router.get("/provider-balances")
async def get_provider_balances(force_refresh: bool = False):
    """Get real official balances for all configured providers (with caching)."""
    from services.provider_service import get_all_provider_balances
    balances = await get_all_provider_balances(force_refresh=force_refresh)
    return {"balances": balances}

@router.get("/trends")
async def get_trends(days: int = 30):
    """Get aggregated trend data for the last N days."""
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    # Start of day for the oldest date
    start_date = (now - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 1. Companies Growth
    companies_pipeline = [
        {"$match": {"created_at": {"$gte": start_date}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "count": {"$sum": 1},
            "active": {"$sum": {"$cond": [{"$eq": ["$is_active", True]}, 1, 0]}}
        }},
        {"$sort": {"_id": 1}}
    ]
    companies_data = await col_companies().aggregate(companies_pipeline).to_list(None)
    
    # 2. Conversations Activity
    conversations_pipeline = [
        {"$match": {"started_at": {"$gte": start_date}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$started_at"}},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    conversations_data = await col_conversations().aggregate(conversations_pipeline).to_list(None)
    
    # 3. AI Usage Trend (from messages)
    ai_pipeline = [
        {"$match": {"timestamp": {"$gte": start_date}, "role": "assistant"}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    ai_data = await col_messages().aggregate(ai_pipeline).to_list(None)
    
    # Format _id to date
    for item in companies_data: item["date"] = item.pop("_id")
    for item in conversations_data: item["date"] = item.pop("_id")
    for item in ai_data: item["date"] = item.pop("_id")

    # --- ADVANCED ANALYTICS ---
    # 4. Token & Cost Trends
    daily_llm_pipeline = [
        {"$match": {"timestamp": {"$gte": start_date}}},
        {"$group": {
            "_id": {
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                "provider": "$provider",
                "model": "$model"
            },
            "api_calls": {"$sum": 1},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
        }},
        {"$sort": {"_id.date": 1}}
    ]
    daily_llm_raw = await col_llm_requests().aggregate(daily_llm_pipeline).to_list(None)

    # 5. RAG Queries (from usage records - aggregated by month unfortunately, so we just pass what we have)
    
    # 6. Failure Reasons
    fail_pipeline = [
        {"$match": {"timestamp": {"$gte": start_date}, "success": False}},
        {"$group": {
            "_id": "$error_msg",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    fail_data = await col_llm_requests().aggregate(fail_pipeline).to_list(None)
    
    def normalize_error(msg: str) -> str:
        msg_lower = str(msg).lower() if msg else ""
        if "429" in msg_lower or "rate limit" in msg_lower or "quota" in msg_lower:
            return "Quota / Rate Limit"
        elif "timeout" in msg_lower or "deadline" in msg_lower:
            return "Timeout"
        elif "empty" in msg_lower or "no response" in msg_lower:
            return "Empty Response"
        elif "503" in msg_lower or "502" in msg_lower or "unavailable" in msg_lower or "bad gateway" in msg_lower:
            return "Service Unavailable"
        elif "401" in msg_lower or "403" in msg_lower or "auth" in msg_lower or "invalid api key" in msg_lower:
            return "Authentication Failed"
        elif "404" in msg_lower or "not found" in msg_lower:
            return "Model Unavailable"
        elif "connection" in msg_lower or "network" in msg_lower or "socket" in msg_lower or "dns" in msg_lower:
            return "Network Error"
        return "Other"
        
    normalized_failures = {}
    for row in fail_data:
        raw_msg = row.get("_id") or "Unknown Error"
        cat = normalize_error(raw_msg)
        normalized_failures[cat] = normalized_failures.get(cat, 0) + row["count"]
        
    final_fail_data = [{"reason": k, "count": v} for k, v in sorted(normalized_failures.items(), key=lambda x: x[1], reverse=True)]

    # Get pricing
    settings_doc = await col_platform_settings().find_one({"type": "global"})
    pricing_conf = settings_doc.get("pricing", {}) if settings_doc else {}
    exchange_rate = pricing_conf.get("usd_to_inr_rate", 86.50) if pricing_conf else 86.50

    # Aggregate daily
    daily_aggregated = {}
    provider_aggregated = {}
    
    for row in daily_llm_raw:
        date = row["_id"]["date"]
        prov = row["_id"]["provider"]
        mod = row["_id"]["model"]
        
        in_toks = row.get("input_tokens", 0)
        out_toks = row.get("output_tokens", 0)
        tot_toks = row.get("total_tokens", 0)
        
        cost = 0.0
        if prov in pricing_conf:
            prov_pricing = pricing_conf[prov]
            if mod in prov_pricing:
                cost = ((in_toks / 1_000_000) * prov_pricing[mod].get("input_1m", 0)) + \
                       ((out_toks / 1_000_000) * prov_pricing[mod].get("output_1m", 0))
            elif "default" in prov_pricing:
                cost = ((in_toks / 1_000_000) * prov_pricing["default"].get("input_1m", 0)) + \
                       ((out_toks / 1_000_000) * prov_pricing["default"].get("output_1m", 0))
        elif "default" in pricing_conf:
            cost = ((in_toks / 1_000_000) * pricing_conf["default"].get("input_1m", 0)) + \
                   ((out_toks / 1_000_000) * pricing_conf["default"].get("output_1m", 0))
                   
        cost = cost * exchange_rate
        
        if date not in daily_aggregated:
            daily_aggregated[date] = {
                "date": date, "api_calls": 0, "input_tokens": 0, 
                "output_tokens": 0, "total_tokens": 0, "cost": 0.0,
                "success": 0, "failed": 0
            }
            
        d = daily_aggregated[date]
        d["api_calls"] += row.get("api_calls", 0)
        d["input_tokens"] += in_toks
        d["output_tokens"] += out_toks
        d["total_tokens"] += tot_toks
        d["success"] += row.get("success", 0)
        d["failed"] += row.get("failed", 0)
        d["cost"] += cost
        
        if prov not in provider_aggregated:
            provider_aggregated[prov] = {
                "provider": prov, "api_calls": 0, "input_tokens": 0,
                "output_tokens": 0, "total_tokens": 0, "cost": 0.0,
                "success": 0, "failed": 0
            }
            
        p = provider_aggregated[prov]
        p["api_calls"] += row.get("api_calls", 0)
        p["input_tokens"] += in_toks
        p["output_tokens"] += out_toks
        p["total_tokens"] += tot_toks
        p["success"] += row.get("success", 0)
        p["failed"] += row.get("failed", 0)
        p["cost"] += cost

    return {
        "companies": companies_data,
        "conversations": conversations_data,
        "ai_requests": ai_data,
        "daily_llm": list(daily_aggregated.values()),
        "provider_usage": list(provider_aggregated.values()),
        "failure_reasons": final_fail_data
    }
