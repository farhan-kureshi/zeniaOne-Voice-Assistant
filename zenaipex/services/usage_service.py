"""
Zenaipex AI — Usage tracking service.

Tracks call minutes and API usage per company per month.
Enforces call minute limits. Provides dashboard summary data.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId

from core.database import (
    col_usage_records, col_agents, col_channels,
    col_knowledge_bases, col_documents, col_subscriptions,
    col_team_members, col_companies, col_llm_requests,
    col_conversations, col_messages, col_platform_settings, col_users
)
from models.subscription import PLAN_LIMITS

logger = logging.getLogger(__name__)


def _current_month() -> str:
    """Return current month key in YYYY-MM format."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


# 1 LLM call = 1 AI Credit. Easily configurable later.
CREDITS_PER_LLM_CALL = 1.0


async def get_usage_record(company_id: str, month: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch usage record for a company for a given month (defaults to current)."""
    if not month:
        month = _current_month()
    return await col_usage_records().find_one({"company_id": company_id, "month": month})


async def increment_usage(
    company_id: str,
    call_duration_seconds: float,
    stt_calls: int = 0,
    tts_calls: int = 0,
    llm_calls: int = 0,
    rag_queries: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    direction: str = "inbound",
) -> bool:
    """
    Atomically increment usage counters for a company after a call ends.

    Uses MongoDB $inc + upsert so concurrent calls don't clobber each other.
    """
    month = _current_month()
    call_minutes = call_duration_seconds / 60.0

    inc_doc: Dict[str, Any] = {
        "call_minutes_used": call_minutes,
        "stt_api_calls": stt_calls,
        "tts_api_calls": tts_calls,
        "rag_queries": rag_queries,
    }
    
    if direction in ("inbound", "outbound", "reminder") or call_duration_seconds > 0:
        inc_doc["call_count"] = 1

    if llm_calls > 0:
        inc_doc["llm_api_calls"]  = llm_calls
        inc_doc["ai_credits_used"] = llm_calls * CREDITS_PER_LLM_CALL
    if input_tokens > 0:
        inc_doc["input_tokens"]  = input_tokens
    if output_tokens > 0:
        inc_doc["output_tokens"] = output_tokens
    if total_tokens > 0:
        inc_doc["total_tokens"]  = total_tokens

    if direction == "inbound":
        inc_doc["inbound_call_count"] = 1
    elif direction in ("outbound", "reminder"):
        inc_doc["outbound_call_count"] = 1

    try:
        await col_usage_records().update_one(
            {"company_id": company_id, "month": month},
            {
                "$inc": inc_doc,
                "$set": {"updated_at": datetime.now(timezone.utc)},
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        return True
    except Exception as exc:
        raise Exception(f"Failed to increment usage: {exc}")


async def record_interaction_tokens(
    company_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    direction: str = "test-chat",
    llm_calls: int = 1,
    rag_queries: int = 0,
    **kwargs
) -> bool:
    """
    Record token usage and increment LLM call counter for chat / text interactions.
    """
    try:
        return await increment_usage(
            company_id=company_id,
            call_duration_seconds=0.0,
            llm_calls=llm_calls,
            rag_queries=rag_queries,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            direction=direction,
        )
    except Exception as exc:
        logger.error(f"Failed to record interaction tokens: {exc}")
        return False


async def log_llm_request(
    company_id: str,
    agent_id: Optional[str],
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: float = 0.0,
    success: bool = True,
    error_msg: Optional[str] = None,
    direction: str = "unknown",
    request_id: Optional[str] = None
):
    """
    Log an individual LLM request to the database for fine-grained usage and cost tracking.
    """
    if not company_id:
        return
        
    doc = {
        "company_id": company_id,
        "agent_id": agent_id,
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "success": success,
        "direction": direction,
        "timestamp": datetime.now(timezone.utc)
    }
    if request_id:
        doc["request_id"] = request_id
    if error_msg:
        doc["error_msg"] = error_msg
        
    try:
        await col_llm_requests().insert_one(doc)
    except Exception as exc:
        logger.error(f"Failed to log LLM request: {exc}")


async def check_call_minute_limit(company_id: str) -> bool:
    """
    Returns True if company still has call minutes available this month.
    Used as a pre-call gate to prevent overages.
    """
    from core.config import settings
    if not settings.ai_billing_enforcement:
        return True

    try:
        comp = await col_companies().find_one({"_id": ObjectId(company_id)})
        if comp and comp.get("slug") == "admin_workspace":
            return True
    except Exception:
        pass

    sub = await col_subscriptions().find_one({"company_id": company_id})
    if not sub:
        return True  # No sub = no gate (dev mode)

    limits = sub.get("limits", PLAN_LIMITS.get(sub.get("plan", "free_trial"), {}))
    monthly_limit = limits.get("call_minutes_per_month", 60)

    if monthly_limit >= 999_999:
        return True  # Enterprise: unlimited

    usage = await get_usage_record(company_id)
    if not usage:
        return True  # No usage yet = plenty of minutes

    minutes_used = usage.get("call_minutes_used", 0.0)
    return minutes_used < monthly_limit


async def check_ai_credit_limit(company_id: str) -> bool:
    """
    Returns True if company still has AI credits available this month.
    Used as a pre-call gate to prevent overages.
    """
    from core.config import settings
    if not settings.ai_billing_enforcement:
        return True

    try:
        comp = await col_companies().find_one({"_id": ObjectId(company_id)})
        if comp and comp.get("slug") == "admin_workspace":
            return True
    except Exception:
        pass

    sub = await col_subscriptions().find_one({"company_id": company_id})
    if not sub:
        return True  # No sub = no gate (dev mode)

    limits = sub.get("limits", PLAN_LIMITS.get(sub.get("plan", "free_trial"), {}))
    monthly_limit = limits.get("ai_credits_per_month", 20)

    if monthly_limit >= 999_999:
        return True  # Enterprise/Admin: unlimited

    usage = await get_usage_record(company_id)
    if not usage:
        return True  # No usage yet = plenty of credits

    credits_used = usage.get("ai_credits_used", 0.0)
    return credits_used < monthly_limit


async def get_canonical_analytics(company_id: str, days: int = 30) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    from models.subscription import PLAN_LIMITS

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    tenant_filter: Dict[str, Any] = {}
    if company_id and company_id != "all":
        tenant_filter["company_id"] = company_id

    def _c(extra: dict) -> dict:
        d = dict(tenant_filter)
        if extra:
            d.update(extra)
        return d

    # Resource counts
    total_agents = await col_agents().count_documents(_c({"status": {"$ne": "deleted"}}))
    active_agents = await col_agents().count_documents(_c({"status": "active"}))
    total_conversations = await col_conversations().count_documents(_c({"status": {"$nin": ["deleted", "demo", "test"]}}))
    total_documents = await col_documents().count_documents(_c({"status": {"$ne": "deleted"}}))
    total_knowledge_bases = await col_knowledge_bases().count_documents(_c({"status": {"$ne": "deleted"}}))
    total_messages = await col_messages().count_documents(_c({}))
    
    # Platform specific counts
    total_companies = active_companies = suspended_companies = trial_companies = total_users = customer_users = platform_admin_count = 0
    if company_id == "all":
        total_companies = await col_companies().count_documents({})
        active_companies = await col_companies().count_documents({"is_active": True})
        suspended_companies = await col_companies().count_documents({"is_active": False})
        trial_companies = await col_subscriptions().count_documents({"plan": "free_trial"})
        total_users = await col_users().count_documents({})
        platform_admin_count = await col_users().count_documents({"is_platform_admin": True})
        customer_users = total_users - platform_admin_count

    # Non-LLM from usage_records (which is monthly)
    total_call_minutes = 0.0
    total_stt_calls = 0
    total_tts_calls = 0
    total_rag_queries = 0
    
    legacy_llm_calls = 0
    legacy_input_tokens = 0
    legacy_output_tokens = 0
    legacy_total_tokens = 0
    
    async for record in col_usage_records().find(_c({})):
        total_call_minutes += record.get("call_minutes_used", 0)
        total_stt_calls += record.get("stt_api_calls", 0)
        total_tts_calls += record.get("tts_api_calls", 0)
        total_rag_queries += record.get("rag_queries", 0)
        legacy_llm_calls += record.get("llm_api_calls", 0)
        legacy_input_tokens += record.get("input_tokens", 0)
        legacy_output_tokens += record.get("output_tokens", 0)
        legacy_total_tokens += record.get("total_tokens", 0)

    # Detailed LLM requests
    llm_match: Dict[str, Any] = {"timestamp": {"$gte": start_date}}
    if company_id and company_id != "all":
        llm_match["company_id"] = company_id
        
    pipeline = [
        {"$match": llm_match},
        {"$group": {
            "_id": {"provider": "$provider", "model": "$model"},
            "api_calls": {"$sum": 1},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
            "avg_latency": {"$avg": "$latency_ms"}
        }},
        {"$sort": {"api_calls": -1}}
    ]
    
    llm_data = await col_llm_requests().aggregate(pipeline).to_list(None)
    
    
    # Get Pricing configuration
    settings_doc = await col_platform_settings().find_one({"type": "global"})
    pricing_conf = {}
    if settings_doc and "pricing" in settings_doc:
        pricing_conf = settings_doc["pricing"]
        
    exchange_rate = pricing_conf.get("usd_to_inr_rate", 86.50) if pricing_conf else 86.50
    total_cost = 0.0

    provider_usage_table = []
    new_llm_calls = 0
    new_input_tokens = 0
    new_output_tokens = 0
    new_total_tokens = 0
    
    prov_map = {}
    
    # Pre-populate with all active providers so they show up even with 0 usage
    from core.database import col_ai_providers
    active_providers = await col_ai_providers().find({"enabled": True}).to_list(None)
    for ap in active_providers:
        p_name = ap.get("provider", "Unknown")
        c_name = str(p_name).strip().lower()
        if c_name and c_name not in prov_map:
            prov_map[c_name] = {
                "provider": p_name,
                "api_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "success": 0,
                "failed": 0,
                "cost": 0.0,
                "models": []
            }
    
    for row in llm_data:
        raw_prov = row["_id"].get("provider", "Unknown")
        canon_prov = str(raw_prov).strip().lower()
        if not canon_prov:
            canon_prov = "unknown"
            
        mod = row["_id"].get("model", "Unknown")
        api_calls = row.get("api_calls", 0)
        in_toks = row.get("input_tokens", 0)
        out_toks = row.get("output_tokens", 0)
        tot_toks = row.get("total_tokens", 0)
        success_calls = row.get("success", 0)
        failed_calls = row.get("failed", 0)
        
        new_llm_calls += api_calls
        new_input_tokens += in_toks
        new_output_tokens += out_toks
        new_total_tokens += tot_toks
        
        # Determine pricing using canonical provider name
        cost = None
        if canon_prov in pricing_conf:
            prov_pricing = pricing_conf[canon_prov]
            if mod in prov_pricing:
                cost = ((in_toks / 1_000_000) * prov_pricing[mod].get("input_1m", 0)) + \
                       ((out_toks / 1_000_000) * prov_pricing[mod].get("output_1m", 0))
            elif "default" in prov_pricing:
                cost = ((in_toks / 1_000_000) * prov_pricing["default"].get("input_1m", 0)) + \
                       ((out_toks / 1_000_000) * prov_pricing["default"].get("output_1m", 0))
        elif "default" in pricing_conf:
            cost = ((in_toks / 1_000_000) * pricing_conf["default"].get("input_1m", 0)) + \
                   ((out_toks / 1_000_000) * pricing_conf["default"].get("output_1m", 0))
                   
        if cost is not None:
            cost = cost * exchange_rate
            total_cost += cost
            
        model_entry = {
            "model": mod,
            "api_calls": api_calls,
            "input_tokens": in_toks,
            "output_tokens": out_toks,
            "total_tokens": tot_toks,
            "success": success_calls,
            "failed": failed_calls,
            "avg_latency": row.get("avg_latency", 0),
            "cost": cost
        }
        
        if canon_prov not in prov_map:
            # First time seeing this provider, create base entry using original casing for display
            prov_map[canon_prov] = {
                "provider": str(raw_prov).strip(),
                "api_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "success": 0,
                "failed": 0,
                "cost": 0.0,
                "models": []
            }
            
        p_entry = prov_map[canon_prov]
        p_entry["api_calls"] += api_calls
        p_entry["input_tokens"] += in_toks
        p_entry["output_tokens"] += out_toks
        p_entry["total_tokens"] += tot_toks
        p_entry["success"] += success_calls
        p_entry["failed"] += failed_calls
        if cost is not None:
            p_entry["cost"] += cost
        p_entry["models"].append(model_entry)
        
    for p_entry in prov_map.values():
        if p_entry["cost"] == 0.0:
            p_entry["cost"] = None
        provider_usage_table.append(p_entry)
        
    # Reconcile Legacy vs New
    # Unknown/Legacy is grand_total (usage_records) - new_detailed (llm_requests)
    unknown_calls = max(0, legacy_llm_calls - new_llm_calls)
    unknown_input = max(0, legacy_input_tokens - new_input_tokens)
    unknown_output = max(0, legacy_output_tokens - new_output_tokens)
    unknown_total = max(0, legacy_total_tokens - new_total_tokens)
    
    # Fix math: if we are building the unknown row, ensure its total tokens = input + output 
    if unknown_input + unknown_output > 0:
        if unknown_total != (unknown_input + unknown_output):
            unknown_total = unknown_input + unknown_output
            
    if unknown_calls > 0:
        provider_usage_table.append({
            "provider": "Unknown / Legacy",
            "api_calls": unknown_calls,
            "input_tokens": unknown_input,
            "output_tokens": unknown_output,
            "total_tokens": unknown_total,
            "success": unknown_calls,
            "failed": 0,
            "cost": None,
            "models": [{
                "model": "Historical",
                "api_calls": unknown_calls,
                "input_tokens": unknown_input,
                "output_tokens": unknown_output,
                "total_tokens": unknown_total,
                "success": unknown_calls,
                "failed": 0,
                "avg_latency": 0,
                "cost": None
            }]
        })
        
    final_llm_calls = new_llm_calls + unknown_calls
    final_input = new_input_tokens + unknown_input
    final_output = new_output_tokens + unknown_output
    final_total = new_total_tokens + unknown_total
    
    total_api_calls = total_stt_calls + total_tts_calls + final_llm_calls
    
    return {
        # Overview stats
        "total_companies": total_companies,
        "active_companies": active_companies,
        "suspended_companies": suspended_companies,
        "trial_companies": trial_companies,
        "total_users": total_users,
        "customer_users": customer_users,
        "platform_admin_count": platform_admin_count,
        
        "total_agents": total_agents,
        "active_agents": active_agents,
        "total_conversations": total_conversations,
        "total_documents": total_documents,
        "total_knowledge_bases": total_knowledge_bases,
        "total_messages": total_messages,
        
        "total_call_minutes": round(total_call_minutes, 1),
        "total_api_calls": total_api_calls,
        "total_llm_calls": final_llm_calls,
        "total_rag_queries": total_rag_queries,
        "total_input_tokens": final_input,
        "total_output_tokens": final_output,
        "total_tokens": final_total,
        
        "provider_usage_table": provider_usage_table,
        "total_cost": total_cost if total_cost > 0 else None,
        "exchange_rate": exchange_rate,
        "pricing_configured": len(pricing_conf) > 0,
    }

async def get_usage_summary(company_id: str) -> Dict[str, Any]:
    """
    Return a complete usage summary for the dashboard.
    Combines real-time resource counts with monthly usage.
    """
    from models.subscription import PLAN_LIMITS
    
    sub = await col_subscriptions().find_one({"company_id": company_id})
    plan = sub.get("plan", "free_trial") if sub else "free_trial"
    limits = sub.get("limits", PLAN_LIMITS.get(plan, {})) if sub else PLAN_LIMITS.get(plan, {})
    
    month = _current_month()
    usage = await get_usage_record(company_id, month) or {}
    
    metrics = await get_canonical_analytics(company_id, days=30)
    
    call_minutes_used = metrics.get("total_call_minutes", 0.0)
    
    # is_admin check
    is_admin = False
    try:
        comp = await col_companies().find_one({"_id": ObjectId(company_id)})
        if comp and comp.get("slug") == "admin_workspace":
            is_admin = True
    except Exception:
        pass
        
    call_minutes_limit = 999999 if is_admin else limits.get("call_minutes_per_month", 60)
    call_minutes_pct = min(100.0, (call_minutes_used / max(call_minutes_limit, 1)) * 100)

    ai_credits_used = metrics.get("total_llm_calls", 0) * CREDITS_PER_LLM_CALL
    ai_credits_limit = 999999 if is_admin else limits.get("ai_credits_per_month", 20)
    ai_credits_pct = min(100.0, (ai_credits_used / max(ai_credits_limit, 1)) * 100)
    
    return {
        "month": month,
        "plan": plan,
        # Call usage
        "call_minutes_used": round(call_minutes_used, 1),
        "call_minutes_limit": call_minutes_limit,
        "call_minutes_remaining": max(0, call_minutes_limit - call_minutes_used),
        "call_minutes_pct": round(call_minutes_pct, 1),
        "call_count": usage.get("call_count", 0),
        "inbound_call_count": usage.get("inbound_call_count", 0),
        "outbound_call_count": usage.get("outbound_call_count", 0),
        # AI Credits
        "ai_credits_used": round(ai_credits_used, 1),
        "ai_credits_limit": ai_credits_limit,
        "ai_credits_remaining": max(0, ai_credits_limit - ai_credits_used),
        "ai_credits_pct": round(ai_credits_pct, 1),
        # Resource counts
        "agents_used": metrics.get("total_agents", 0),
        "active_agents": metrics.get("active_agents", 0),
        "agents_limit": limits.get("max_agents", 1),
        "channels_used": await col_channels().count_documents({"company_id": company_id}),
        "channels_limit": limits.get("max_channels", 1),
        "kb_docs_used": metrics.get("total_documents", 0),
        "kb_docs_limit": limits.get("max_kb_docs", 10),
        "team_members": await col_team_members().count_documents({"company_id": company_id}),
        "team_members_limit": limits.get("max_team_members", 1),
        "total_conversations": metrics.get("total_conversations", 0),
        # API counts
        "stt_api_calls": usage.get("stt_api_calls", 0),
        "tts_api_calls": usage.get("tts_api_calls", 0),
        "llm_api_calls": metrics.get("total_llm_calls", 0),
        "input_tokens": metrics.get("total_input_tokens", 0),
        "output_tokens": metrics.get("total_output_tokens", 0),
        "total_tokens": metrics.get("total_tokens", 0),
        "rag_queries": metrics.get("total_rag_queries", 0),
        "provider_usage_table": metrics.get("provider_usage_table", []),
    }


async def get_detailed_analytics(company_id: str, days: int = 30) -> Dict[str, Any]:
    """
    Get detailed time-series, agent, and provider analytics for the dashboard.
    """
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Base match filters
    match_filter: Dict[str, Any] = {"timestamp": {"$gte": start_date}}
    conv_match: Dict[str, Any] = {"started_at": {"$gte": start_date}, "status": {"$nin": ["deleted", "demo", "test"]}}
    msg_match: Dict[str, Any] = {"timestamp": {"$gte": start_date}}
    
    if company_id and company_id != "all":
        match_filter["company_id"] = company_id
        conv_match["company_id"] = company_id
        msg_match["company_id"] = company_id
        
    def _c(extra: dict) -> dict:
        d = {}
        if company_id and company_id != "all":
            d["company_id"] = company_id
        if extra:
            d.update(extra)
        return d
        
    # --- 1. KPI Data ---
    total_convs = await col_conversations().count_documents(conv_match)
    total_msgs = await col_messages().count_documents(msg_match)
    # Count agents that are not deleted (draft + active = enabled for use)
    active_agents = await col_agents().count_documents(_c({"status": {"$nin": ["deleted", "inactive"]}}))
    
    llm_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": None,
            "ai_requests": {"$sum": 1},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
        }}
    ]
    llm_stats_res = await col_llm_requests().aggregate(llm_pipeline).to_list(None)
    llm_stats = llm_stats_res[0] if llm_stats_res else {}
    
    ai_requests = llm_stats.get("ai_requests", 0)
    success = llm_stats.get("success", 0)
    failed = llm_stats.get("failed", 0)
    success_rate = round((success / max(ai_requests, 1)) * 100, 1)
    
    # We reuse get_canonical_analytics for provider cost logic
    canon = await get_canonical_analytics(company_id, days=days)
    total_cost = canon.get("total_cost", 0) or 0
    total_tokens = canon.get("total_tokens", 0)
    provider_usage_table = canon.get("provider_usage_table", [])
    
    # --- 2. Time Series Trend ---
    trend_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "ai_requests": {"$sum": 1},
            "total_tokens": {"$sum": "$total_tokens"},
            # In a real heavy-load production, cost grouping would happen here via $lookup or map-reduce,
            # but for now we'll just return requests and tokens.
        }},
        {"$sort": {"_id": 1}}
    ]
    llm_trend_res = await col_llm_requests().aggregate(trend_pipeline).to_list(None)
    
    conv_trend_pipeline = [
        {"$match": conv_match},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$started_at"}},
            "conversations": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    conv_trend_res = await col_conversations().aggregate(conv_trend_pipeline).to_list(None)
    
    # Merge Trends
    trend_map = {}
    for i in range(days + 1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trend_map[d] = {"date": d, "conversations": 0, "ai_requests": 0, "total_tokens": 0, "cost": 0.0}
        
    for row in conv_trend_res:
        date_str = row["_id"]
        if date_str in trend_map:
            trend_map[date_str]["conversations"] = row["conversations"]
            
    # For cost over time, we use a simplified approximation based on tokens 
    # to avoid complex server-side pricing joins per day in MongoDB.
    avg_cost_per_token = (total_cost / max(total_tokens, 1)) if total_tokens > 0 else 0
            
    for row in llm_trend_res:
        date_str = row["_id"]
        if date_str in trend_map:
            trend_map[date_str]["ai_requests"] = row["ai_requests"]
            trend_map[date_str]["total_tokens"] = row["total_tokens"]
            trend_map[date_str]["cost"] = round(row["total_tokens"] * avg_cost_per_token, 2)
            
    usage_trend = sorted(list(trend_map.values()), key=lambda x: x["date"])
    
    # --- 3. Agent Performance ---
    agent_llm_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": "$agent_id",
            "ai_requests": {"$sum": 1},
            "total_tokens": {"$sum": "$total_tokens"},
            "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
        }}
    ]
    agent_llm_res = await col_llm_requests().aggregate(agent_llm_pipeline).to_list(None)
    
    agent_conv_pipeline = [
        {"$match": conv_match},
        {"$group": {
            "_id": "$agent_id",
            "conversations": {"$sum": 1}
        }}
    ]
    agent_conv_res = await col_conversations().aggregate(agent_conv_pipeline).to_list(None)
    
    agent_map = {}
    
    # Populate existing agents first
    async for agent in col_agents().find(_c({})):
        aid = str(agent["_id"])
        agent_map[aid] = {
            "agent_id": aid,
            "name": agent.get("name", "Unknown Agent"),
            "conversations": 0,
            "ai_requests": 0,
            "total_tokens": 0,
            "cost": 0.0,
            "success_rate": 0
        }
        
    for row in agent_conv_res:
        aid = row["_id"]
        if aid not in agent_map:
            agent_map[aid] = {"agent_id": aid, "name": "Deleted Agent", "conversations": 0, "ai_requests": 0, "total_tokens": 0, "cost": 0.0, "success_rate": 0}
        agent_map[aid]["conversations"] = row["conversations"]
        
    for row in agent_llm_res:
        aid = row["_id"]
        if aid not in agent_map:
            agent_map[aid] = {"agent_id": aid, "name": "Deleted Agent", "conversations": 0, "ai_requests": 0, "total_tokens": 0, "cost": 0.0, "success_rate": 0}
        
        reqs = row["ai_requests"]
        succ = row["success"]
        failed_reqs = row["failed"]
        agent_map[aid]["ai_requests"] = reqs
        agent_map[aid]["total_tokens"] = row["total_tokens"]
        agent_map[aid]["cost"] = round(row["total_tokens"] * avg_cost_per_token, 2)
        agent_map[aid]["success_rate"] = round((succ / max(reqs, 1)) * 100, 1)
        agent_map[aid]["failed"] = failed_reqs
        
    # Only return agents that have some usage
    agents = [a for a in agent_map.values() if a["conversations"] > 0 or a["ai_requests"] > 0]
    agents = sorted(agents, key=lambda x: x["ai_requests"], reverse=True)
    
    # --- 4. Recent Activity ---
    recent_activity = await col_conversations().find(conv_match).sort("started_at", -1).limit(10).to_list(length=10)
    for act in recent_activity:
        act["_id"] = str(act["_id"])
        if act.get("agent_id") and act["agent_id"] in agent_map:
            act["agent_name"] = agent_map[act["agent_id"]]["name"]
        else:
            act["agent_name"] = "Unknown Agent"
            
    # Fix datetime serialization
    def _serialize_dt(obj):
        for k, v in obj.items():
            if isinstance(v, datetime):
                obj[k] = v.isoformat()
        return obj
    
    recent_activity = [_serialize_dt(x) for x in recent_activity]
    
    # --- 5. Lightweight Topic Analytics (deterministic keyword matching) ---
    # Fetch recent user messages for the company within the date range
    user_msg_match = dict(msg_match)
    user_msg_match["role"] = "user"
    recent_user_msgs = await col_messages().find(
        user_msg_match, {"text": 1}
    ).sort("timestamp", -1).limit(500).to_list(length=500)
    
    TOPIC_KEYWORDS = {
        "Services & Treatments": ["service", "services", "treatment", "procedure", "offer", "provide", "provide", "available", "do you do", "can you do", "what do you"],
        "Appointments & Booking": ["appointment", "book", "booking", "schedule", "slot", "availability", "visit", "come in", "see"],
        "Business Hours": ["hours", "open", "close", "timing", "timings", "when", "what time", "working hours"],
        "Location & Address": ["location", "address", "where", "directions", "find you", "how to reach", "near", "area"],
        "Pricing & Fees": ["price", "cost", "fee", "charge", "how much", "rate", "affordable", "expensive", "cheap", "payment"],
        "Contact & Communication": ["contact", "phone", "number", "email", "call", "reach", "website", "whatsapp"],
        "General Info": ["info", "information", "details", "tell me", "know", "about"],
    }
    
    topic_counts: Dict[str, int] = {t: 0 for t in TOPIC_KEYWORDS}
    top_questions_raw: Dict[str, int] = {}
    
    for msg in recent_user_msgs:
        text = (msg.get("text") or "").lower().strip()
        if not text or len(text) < 5:
            continue
        
        # Track top questions (normalized, deduplicated)
        norm_q = text[:150]  # cap length
        
        # Filter obvious noise
        noise_words = {"hi", "hello", "thanks", "thank you", "ok", "okay", "test", "testing", "hey", "greetings"}
        if norm_q in noise_words:
            continue
            
        top_questions_raw[norm_q] = top_questions_raw.get(norm_q, 0) + 1
        
        # Topic matching
        matched = False
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                topic_counts[topic] += 1
                matched = True
                break  # Only one topic per message
    
    # Only return topics with at least 1 match
    topics = [
        {"topic": t, "count": c}
        for t, c in sorted(topic_counts.items(), key=lambda x: -x[1])
        if c > 0
    ]
    
    # Top questions: deduplicated, sorted by frequency, limit to 5
    top_questions = [
        {"question": q, "count": c}
        for q, c in sorted(top_questions_raw.items(), key=lambda x: -x[1])
        if len(q) > 8  # Skip very short fragments
    ][:5]
    
    total_user_messages_analyzed = len(recent_user_msgs)

    return {
        "kpi": {
            "total_conversations": total_convs,
            "total_customer_messages": total_msgs,
            "ai_requests": ai_requests,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 2),
            "success_rate": success_rate,
            "active_agents": active_agents
        },
        "usage_trend": usage_trend,
        "providers": provider_usage_table,
        "agents": agents,
        "recent_activity": recent_activity,
        "topics": topics,
        "top_questions": top_questions,
        "total_user_messages_analyzed": total_user_messages_analyzed,
    }
