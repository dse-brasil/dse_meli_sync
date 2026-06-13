import logging
import hmac
import hashlib
from typing import Any, Dict
from fastapi import APIRouter, Header, HTTPException, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import WebhookEvent
from app.config import settings
from app.tasks.webhook_tasks import process_webhook_event_task

logger = logging.getLogger(__name__)
router = APIRouter()

def verify_meli_signature(payload_bytes: bytes, x_signature: str) -> bool:
    """
    Verifies that the webhook payload is signed with the secret token.
    Uses SHA256 HMAC signature verification.
    """
    if not settings.MELI_WEBHOOK_SIGNATURE_KEY or "your-meli-webhook" in settings.MELI_WEBHOOK_SIGNATURE_KEY:
        # If no key is set or using placeholder, warn and allow (local dev/testing)
        logger.warning("MELI_WEBHOOK_SIGNATURE_KEY not configured or using default placeholder. Skipping HMAC signature check.")
        return True

    if not x_signature:
        return False

    computed = hmac.new(
        settings.MELI_WEBHOOK_SIGNATURE_KEY.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, x_signature)

@router.post("/meli", status_code=status.HTTP_200_OK)
async def receive_meli_webhook(
    request: Request,
    x_signature: str = Header(None, alias="X-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    FastAPI endpoint to receive Mercado Livre Webhook events.
    Validates the signature, saves the raw JSONB payload to PostgreSQL,
    enqueues a Celery job, and returns 200 OK immediately.
    """
    # 1. Read raw body bytes for signature validation
    body_bytes = await request.body()
    
    # Verify authenticity
    if not verify_meli_signature(body_bytes, x_signature):
        logger.warning("Unauthorized webhook received: Invalid signature signature verification failed.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid signature"
        )

    # 2. Parse payload JSON
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Malformed JSON body"
        )

    # Mercado Livre webhook payload schema generally contains:
    # {
    #   "resource": "/questions/123456",
    #   "user_id": 98765432,
    #   "topic": "questions",
    #   "application_id": 111111111111,
    #   "sent": "2026-06-13T10:30:00.000Z",
    #   "received": "2026-06-13T10:30:01.000Z"
    # }
    topic = payload.get("topic")
    resource = payload.get("resource")

    if not topic or not resource:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing 'topic' or 'resource' in webhook payload"
        )

    # 3. Save Raw Payload in database (JSONB)
    db_event = WebhookEvent(
        topic=topic,
        resource=resource,
        payload=payload,
        status="received"
    )
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)

    # 4. Enqueue background processing using Celery
    try:
        process_webhook_event_task.delay(str(db_event.id))
        logger.info(f"Enqueued webhook task: {db_event.id} | Topic: {topic}")
    except Exception as err:
        logger.error(f"Failed to enqueue task for event {db_event.id}: {str(err)}")
        # We still return 200 OK because Mercado Livre requires us to accept the webhook,
        # but we mark the event status in DB as failed to trigger monitoring/retries.
        db_event.status = "failed"
        db_event.error_message = f"Queueing error: {str(err)}"
        await db.commit()

    return {"status": "received", "event_id": str(db_event.id)}
