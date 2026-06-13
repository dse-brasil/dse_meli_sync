import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Conversation, Product
from app.core.security import get_decrypted_master_prompt
from app.core.guardrails import PromptGuard, PromptInjectionException
from app.services.meli_client import meli_client
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    buyer_id: str
    item_id: str
    message: str

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    secured: bool

@router.post("/message", response_model=ChatResponse)
async def chat_with_sales_agent(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Direct endpoint to converse with the DSE Sales Robot.
    Allows manual testing of AI agent persona, security filters (Guardrails) and prompt protection.
    """
    # 1. Guardrail input validation (anti-injection)
    try:
        PromptGuard.validate_input(request.message)
    except PromptInjectionException as inject_err:
        logger.warning(f"Chat message blocked by injection guardrail: '{request.message}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(inject_err)
        )

    # 2. Get product details to feed the AI context
    try:
        product_data = await meli_client.get_item_details(request.item_id)
    except Exception as e:
        logger.error(f"Failed to fetch item details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {request.item_id} not found."
        )

    # 3. Retrieve or initiate the conversation context
    conv_id = f"chat_{request.buyer_id}_{request.item_id}"
    stmt = select(Conversation).where(Conversation.id == conv_id)
    res = await db.execute(stmt)
    db_conv = res.scalar_one_or_none()

    if not db_conv:
        db_conv = Conversation(id=conv_id, user_id=request.buyer_id, history=[])
        db.add(db_conv)

    # 4. Decrypt Master System Prompt
    try:
        master_prompt = get_decrypted_master_prompt()
    except Exception as p_err:
        logger.error(f"Critical encryption configuration error: {str(p_err)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System prompt decryption failed. Check server configurations."
        )

    # 5. Call AI Service (Gemini/OpenAI)
    try:
        llm_response = await ai_service.get_response(
            system_prompt=master_prompt,
            user_question=request.message,
            product_context=product_data,
            history=db_conv.history
        )
    except Exception as ai_err:
        logger.error(f"Failed to query LLM: {str(ai_err)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM model service failed to respond."
        )

    # 6. Sanitize LLM response (anti-leak protection)
    sanitized_response = PromptGuard.sanitize_output(llm_response)

    # Update conversation history
    new_history = list(db_conv.history)
    new_history.append({"role": "user", "content": request.message})
    new_history.append({"role": "assistant", "content": sanitized_response})
    db_conv.history = new_history
    await db.commit()

    return ChatResponse(
        response=sanitized_response,
        conversation_id=conv_id,
        secured=True
    )
