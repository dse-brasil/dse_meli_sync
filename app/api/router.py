from fastapi import APIRouter
from app.api.endpoints import webhooks, chat, auth, admin

api_router = APIRouter()

api_router.include_router(
    webhooks.router,
    prefix="/webhooks",
    tags=["Webhooks"]
)

api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"]
)

api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

api_router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Administration"]
)
