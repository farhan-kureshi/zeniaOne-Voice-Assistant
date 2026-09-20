from fastapi import APIRouter, Depends
from core.dependencies import get_platform_admin

from . import companies, users, metrics, agents, conversations, knowledge, channels, subscriptions, usage, logs, providers, settings

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_platform_admin)],
)

router.include_router(companies.router)
router.include_router(users.router)
router.include_router(metrics.router)
router.include_router(agents.router)
router.include_router(conversations.router)
router.include_router(knowledge.router)
router.include_router(channels.router)
router.include_router(subscriptions.router)
router.include_router(usage.router)
router.include_router(logs.router)
router.include_router(providers.router)
router.include_router(settings.router)

public_router = APIRouter(
    prefix="/admin",
    tags=["Admin Public"],
)
public_router.include_router(settings.public_router)
