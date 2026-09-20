"""
Zenaipex AI — Super Admin AI Providers API.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Any
import logging

from core.dependencies import get_platform_admin
from services.provider_service import get_all_providers, update_provider, get_provider_by_id
from models.user import User
from models.provider import AIProviderResponse, AIProviderUpdate
import aiohttp
import asyncio
import json

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/providers",
    tags=["Admin - Providers"]
)

@router.get("", response_model=List[AIProviderResponse])
async def list_providers(admin: dict = Depends(get_platform_admin)):
    """List all AI providers and their status."""
    providers = await get_all_providers()
    
    # We must mask the API keys for the frontend
    responses = []
    for p in providers:
        has_key = bool(p.api_key and p.api_key.strip())
        responses.append(AIProviderResponse(
            id=p.id,
            provider=p.provider,
            enabled=p.enabled,
            priority=p.priority,
            model=p.model,
            updated_at=p.updated_at,
            updated_by=p.updated_by,
            has_api_key=has_key
        ))
    return responses



@router.get("/unified-state")
async def get_unified_state(days: int = 30, admin: dict = Depends(get_platform_admin)):
    """Get the authoritative unified provider state (config + usage + balance)."""
    from services.provider_service import get_unified_provider_state
    state = await get_unified_provider_state(days=days)
    return {"providers": state}

@router.get("/balances")

async def get_provider_balances(force_refresh: bool = False, admin: dict = Depends(get_platform_admin)):
    """Get real official balances for all configured providers (with caching)."""
    from services.provider_service import get_all_provider_balances
    balances = await get_all_provider_balances(force_refresh=force_refresh)
    return {"balances": balances}


@router.put("/{provider_id}", response_model=AIProviderResponse)
async def modify_provider(
    provider_id: str,
    update_data: AIProviderUpdate,
    admin: dict = Depends(get_platform_admin)
):
    """Update an AI provider (e.g. enable/disable, change API key)."""
    updates = update_data.model_dump(exclude_unset=True)
    
    # If the frontend passes "••••••••" or empty for API key, don't update it
    if "api_key" in updates and (not updates["api_key"] or updates["api_key"].startswith("••••")):
        del updates["api_key"]
        
    updated = await update_provider(provider_id, updates, admin.get("email", "system"))
    if not updated:
        raise HTTPException(status_code=404, detail="Provider not found")
        
    return AIProviderResponse(
        id=updated.id,
        provider=updated.provider,
        enabled=updated.enabled,
        priority=updated.priority,
        model=updated.model,
        updated_at=updated.updated_at,
        updated_by=updated.updated_by,
        has_api_key=bool(updated.api_key and updated.api_key.strip())
    )


from pydantic import BaseModel
from typing import Optional

class TestProviderRequest(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None

@router.post("/{provider_id}/test")
async def test_provider(provider_id: str, req: TestProviderRequest = None, admin: dict = Depends(get_platform_admin)):
    """Test connection to a provider using its configured API key and model, or temporary provided ones."""
    provider = await get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
        
    api_key_to_use = None
    if req and req.api_key is not None:
        api_key_to_use = req.api_key
    else:
        api_key_to_use = provider.api_key

    if not api_key_to_use or not str(api_key_to_use).strip() or "••••" in str(api_key_to_use):
        return {"status": "failed", "message": "API key is not configured."}
        
    api_key_to_use = str(api_key_to_use).strip()

    model_to_use = req.model if req and req.model is not None else provider.model

    # We send a tiny 1-token request to verify auth and model
    messages = [{"role": "user", "content": "Hi"}]
    payload = {
        "model": model_to_use,
        "messages": messages,
        "max_tokens": 1,
        "temperature": 0
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key_to_use}"
    }
    
    p_name = provider.provider.lower()
    is_openai_models_api = False
    method = "POST"
    
    if p_name == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    elif p_name == "groq":
        url = "https://api.groq.com/openai/v1/models"
        method = "GET"
        is_openai_models_api = True
    elif "nvidia" in p_name:
        url = "https://integrate.api.nvidia.com/v1/models"
        method = "GET"
        is_openai_models_api = True
    else:
        # sarvam
        url = "https://api.sarvam.ai/v1/chat/completions"
        if "sarvam" in p_name:
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": api_key_to_use
            }
            
    try:
        timeout_sec = 10.0
        
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                req_coro = session.get(url, headers=headers, timeout=timeout_sec)
            else:
                req_coro = session.post(url, headers=headers, json=payload, timeout=timeout_sec)
                
            async with req_coro as response:
                text = await response.text()
                if response.status == 200:
                    try:
                        resp_json = json.loads(text)
                        
                        if is_openai_models_api:
                            models = [m.get("id") for m in resp_json.get("data", [])]
                            if model_to_use in models:
                                return {"status": "connected", "message": f"Successfully connected to {provider.provider}."}
                            else:
                                return {"status": "failed", "message": f"Model unavailable: '{model_to_use}' not found in available models list."}
                                
                        if "error" in resp_json:
                            err_msg = resp_json["error"].get("message", "Invalid API config") if isinstance(resp_json["error"], dict) else "Invalid API config"
                            return {"status": "failed", "message": err_msg}
                            
                        has_content = False
                        if "choices" in resp_json and len(resp_json["choices"]) > 0:
                            choice = resp_json["choices"][0]
                            msg = choice.get("message", {})
                            c = msg.get("content")
                            if c is None:
                                c = msg.get("reasoning_content", "")
                            if (c and str(c).strip()) or choice.get("finish_reason") == "length":
                                has_content = True
                        elif "candidates" in resp_json and len(resp_json["candidates"]) > 0:
                            parts = resp_json["candidates"][0].get("content", {}).get("parts", [])
                            if parts and parts[0].get("text"):
                                has_content = True
                                
                        if has_content:
                            return {"status": "connected", "message": f"Successfully connected to {provider.provider}."}
                        else:
                            return {"status": "failed", "message": "Connected, but provider returned empty content."}
                    except Exception as e:
                        return {"status": "failed", "message": f"Auth succeeded, but failed to parse response: {e}"}
                else:
                    # Classify specific error types
                    try:
                        err_json = json.loads(text)
                        if isinstance(err_json, list) and len(err_json) > 0:
                            err_msg = err_json[0].get("error", {}).get("message", text)
                            err_status = err_json[0].get("error", {}).get("status", "")
                        elif isinstance(err_json, dict):
                            err_msg = err_json.get("error", {}).get("message", text)
                            err_status = err_json.get("error", {}).get("status", "")
                        else:
                            err_msg = text
                            err_status = ""
                    except:
                        err_msg = text
                        err_status = ""
                    
                    if response.status == 401 or response.status == 403:
                        return {"status": "failed", "message": f"Authentication failed: {err_msg[:200]}"}
                    elif response.status == 429:
                        return {"status": "failed", "message": f"Quota/rate limit exceeded: {err_msg[:200]}"}
                    elif response.status == 404:
                        return {"status": "failed", "message": f"Model unavailable: {err_msg[:200]}"}
                    else:
                        return {"status": "failed", "message": f"HTTP {response.status}: {err_msg[:200]}"}
    except aiohttp.ClientConnectorError:
        return {"status": "failed", "message": "Network error: Cannot connect to provider endpoint."}
    except asyncio.TimeoutError:
        return {"status": "failed", "message": f"Timeout: Provider did not respond within {timeout_sec}s."}
    except Exception as e:
        return {"status": "failed", "message": f"Connection error: {type(e).__name__}: {str(e)[:100]}"}
