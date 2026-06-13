import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import api_router
from app.db.session import engine, Base
from app.core.security import get_decrypted_master_prompt

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown processes.
    Initializes PostgreSQL tables and validates prompt decryption configurations.
    """
    logger.info("Initializing DSE Meli Sync backend...")
    
    # 1. Initialize database schemas on startup
    try:
        async with engine.begin() as conn:
            # Create all tables if they don't exist
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schemas verified/created successfully.")
    except Exception as db_err:
        logger.error(f"Failed to connect to database or create tables: {str(db_err)}")
        # We don't block startup, allowing container to launch and self-heal or retry

    # 2. Verify Prompt security integrity
    try:
        decrypted_prompt = get_decrypted_master_prompt()
        logger.info("Security Check: Master system prompt decrypted in-memory successfully.")
        logger.info(f"Loaded prompt footprint: {len(decrypted_prompt)} characters.")
    except Exception as sec_err:
        logger.error(
            f"CRITICAL CONFIGURATION ERROR: Failed to decrypt system prompt. "
            f"Please verify PROMPT_DECRYPTION_KEY and MASTER_PROMPT_ENCRYPTED settings. "
            f"Details: {str(sec_err)}"
        )
        # We don't crash startup immediately so admin can access diagnostics / documentation endpoints.

    yield
    
    # Shutdown logic
    logger.info("Shutting down DSE Meli Sync backend...")
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Automated sales synchronization and AI agent for Mercado Livre.",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception occurred: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact system support."}
    )

# Healthcheck route
@app.get("/health", tags=["Diagnostics"])
async def health_check():
    return {
        "status": "healthy",
        "system": settings.PROJECT_NAME,
        "version": settings.VERSION
    }

# Include API Router
app.include_router(api_router, prefix="/api/v1")
