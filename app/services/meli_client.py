import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class MeliClient:
    """
    Client wrapper for Mercado Livre API.
    Handles product info retrieval and responding to webhook events.
    """
    def __init__(self):
        self.base_url = "https://api.mercadolibre.com"
        self.headers = {
            "Authorization": f"Bearer {settings.MELI_CLIENT_SECRET}" if settings.MELI_CLIENT_SECRET else "",
            "Content-Type": "application/json"
        }

    async def get_item_details(self, item_id: str) -> dict:
        """
        Fetches item details from Mercado Livre catalog.
        """
        url = f"{self.base_url}/items/{item_id}"
        
        # In case credentials are not configured, fallback to mock data for reliability
        if not settings.MELI_CLIENT_SECRET:
            logger.info(f"MeliClient: Credentials missing. Mocking item details for {item_id}.")
            return {
                "id": item_id,
                "title": "Curso Completo de Data Science 2026 - Certificado Incluso",
                "price": 197.90,
                "permalink": f"https://produto.mercadolivre.com.br/{item_id}-curso-ds",
                "status": "active",
                "available_quantity": 999,
                "attributes": {
                    "format": "Digital (PDF / Vídeo)",
                    "duration": "80 horas",
                    "level": "Iniciante ao Avançado"
                }
            }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=10.0)
                if response.status_code == 200:
                    return response.json()
                logger.error(f"Error fetching item details: {response.status_code} - {response.text}")
                raise Exception(f"Failed to fetch item details: {response.status_code}")
            except Exception as e:
                logger.error(f"Failed connection to Mercado Livre API: {str(e)}")
                raise

    async def answer_question(self, question_id: str, text: str) -> bool:
        """
        Posts the answered question back to Mercado Livre API.
        """
        url = f"{self.base_url}/answers"
        payload = {
            "question_id": question_id,
            "text": text
        }

        if not settings.MELI_CLIENT_SECRET:
            logger.info(f"MeliClient: Mocking answer posting to question {question_id}: '{text}'")
            return True

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers, timeout=10.0)
                if response.status_code in (200, 201):
                    logger.info(f"Successfully answered question {question_id} on Mercado Livre.")
                    return True
                logger.error(f"Error answering question: {response.status_code} - {response.text}")
                return False
            except Exception as e:
                logger.error(f"Failed connection to Mercado Livre answers endpoint: {str(e)}")
                return False

meli_client = MeliClient()
