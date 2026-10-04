"""FastAPI routers for the headless platform."""

from poker_bot_platform.api.demo_router import create_demo_match_router
from poker_bot_platform.api.router import AdminControlService, create_api_router

__all__ = ["AdminControlService", "create_api_router", "create_demo_match_router"]
