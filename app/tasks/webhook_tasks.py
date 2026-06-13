import asyncio
import logging
from datetime import datetime
from uuid import UUID
from celery import shared_task
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import WebhookEvent, Conversation, Product
from app.core.security import get_decrypted_master_prompt
from app.core.guardrails import PromptGuard, PromptInjectionException
from app.services.meli_client import meli_client
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)

async def _process_event_async(event_id: str):
    """
    Core async business logic for processing webhook events.
    """
    async with SessionLocal() as db:
        # 1. Fetch Webhook Event from DB
        stmt = select(WebhookEvent).where(WebhookEvent.id == UUID(event_id))
        result = await db.execute(stmt)
        event = result.scalar_one_or_none()

        if not event:
            logger.error(f"Webhook event not found in database: {event_id}")
            return

        event.status = "processing"
        await db.commit()

        try:
            topic = event.topic
            payload = event.payload
            resource = event.resource

            logger.info(f"Worker processing event {event_id} - Topic: {topic}")

            # 2. Process based on Mercado Livre topic
            if topic == "questions":
                # Typical questions payload:
                # {
                #   "resource": "/questions/12345",
                #   "user_id": 98765432,
                #   "topic": "questions",
                #   "application_id": 11111,
                #   "sent": "2026-06-13T10:30:00.000Z",
                #   "received": "2026-06-13T10:30:01.000Z"
                # }
                # Let's extract the resource ID or mock the details.
                # In real life, we would call GET https://api.mercadolibre.com/questions/12345
                # Here we parse it or use mock payload details.
                question_id = resource.split("/")[-1]
                
                # Mocking question content and product info (often fetched from API or DB)
                user_question = payload.get("text", "Olá! Esse produto tem garantia? Como funciona?")
                item_id = payload.get("item_id", "MLB999888777")
                buyer_id = str(payload.get("buyer_id", "buyer_123456"))

                # Perform input Guardrail check
                try:
                    PromptGuard.validate_input(user_question)
                except PromptInjectionException as p_err:
                    # If injection is caught, we answer with a generic security block
                    logger.warning(f"Guardrail caught injection on question {question_id}. Answering safely.")
                    await meli_client.answer_question(
                        question_id=question_id,
                        text="Olá! Desculpe, não consegui compreender sua dúvida. Poderia reformulá-la, por favor?"
                    )
                    event.status = "processed"
                    event.processed_at = datetime.utcnow()
                    await db.commit()
                    return

                # Get product details (calls catalog service/Meli client)
                product_data = await meli_client.get_item_details(item_id)
                
                # Sync product details in database
                prod_stmt = select(Product).where(Product.id == item_id)
                prod_res = await db.execute(prod_stmt)
                db_product = prod_res.scalar_one_or_none()
                if not db_product:
                    db_product = Product(
                        id=item_id,
                        title=product_data["title"],
                        price=product_data["price"],
                        permalink=product_data.get("permalink"),
                        status=product_data["status"],
                        stock=product_data.get("available_quantity", 0),
                        attributes=product_data.get("attributes", {})
                    )
                    db.add(db_product)
                else:
                    db_product.title = product_data["title"]
                    db_product.price = product_data["price"]
                    db_product.status = product_data["status"]
                    db_product.stock = product_data.get("available_quantity", 0)
                    db_product.attributes = product_data.get("attributes", {})
                
                # Get/Create buyer Conversation history
                conv_id = f"meli_{buyer_id}_{item_id}"
                conv_stmt = select(Conversation).where(Conversation.id == conv_id)
                conv_res = await db.execute(conv_stmt)
                db_conv = conv_res.scalar_one_or_none()
                
                if not db_conv:
                    db_conv = Conversation(id=conv_id, user_id=buyer_id, history=[])
                    db.add(db_conv)
                
                # Fetch System Prompt securely
                master_prompt = get_decrypted_master_prompt()

                # Call LLM Service (Gemini/OpenAI)
                llm_response = await ai_service.get_response(
                    system_prompt=master_prompt,
                    user_question=user_question,
                    product_context=product_data,
                    history=db_conv.history
                )

                # Output Guardrail check (Prevent leak of System Prompt / security keys)
                final_response = PromptGuard.sanitize_output(llm_response)

                # Send answer back to Mercado Livre
                success = await meli_client.answer_question(question_id, final_response)
                if not success:
                    raise Exception("Failed posting answer to Mercado Livre")

                # Update conversation history
                new_history = list(db_conv.history)
                new_history.append({"role": "user", "content": user_question})
                new_history.append({"role": "assistant", "content": final_response})
                db_conv.history = new_history
                db_conv.updated_at = datetime.utcnow()

            elif topic in ("orders", "payments", "shipments"):
                # Handle order synchronization (logistics and financial state)
                # Typically we fetch order details from Mercado Livre and update DB.
                logger.info(f"Syncing order details for resource: {resource}")
                # Mock action
                await asyncio.sleep(0.5)

            else:
                logger.info(f"Unimplemented topic: {topic}")

            event.status = "processed"
            event.processed_at = datetime.utcnow()
            await db.commit()

        except Exception as e:
            logger.exception(f"Error executing task for event {event_id}: {str(e)}")
            event.status = "failed"
            event.error_message = str(e)
            await db.commit()
            raise

@shared_task(name="app.tasks.process_webhook_event_task")
def process_webhook_event_task(event_id: str):
    """
    Celery entrypoint. Runs the async process event logic inside the event loop.
    """
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # If loop is already running (e.g. nested settings), create a task or run it
        future = asyncio.ensure_future(_process_event_async(event_id))
        loop.run_until_complete(future)
    else:
        loop.run_until_complete(_process_event_async(event_id))
    return f"Processed webhook {event_id}"
