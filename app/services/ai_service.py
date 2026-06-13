import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class AIService:
    """
    Service layer for calling Large Language Models (Gemini/OpenAI) 
    to process sales responses.
    """
    
    async def get_response(
        self, 
        system_prompt: str, 
        user_question: str, 
        product_context: dict, 
        history: list
    ) -> str:
        """
        Orchestrates prompt formatting and calls the selected LLM provider.
        """
        # If no LLM_API_KEY is defined, return a mock response that satisfies the persona
        if not settings.LLM_API_KEY:
            logger.info("AIService: API key missing. Returning high-conversion mockup response.")
            return self._get_mock_sales_response(user_question, product_context)

        # Structure payload based on provider
        provider = settings.LLM_PROVIDER.lower()
        try:
            if provider == "gemini":
                return await self._call_gemini(system_prompt, user_question, product_context, history)
            elif provider == "openai":
                return await self._call_openai(system_prompt, user_question, product_context, history)
            else:
                logger.error(f"Unsupported LLM Provider: {provider}. Falling back to mock.")
                return self._get_mock_sales_response(user_question, product_context)
        except Exception as e:
            logger.error(f"Failed calling LLM provider {provider}: {str(e)}")
            return self._get_mock_sales_response(user_question, product_context)

    async def _call_gemini(
        self, 
        system_prompt: str, 
        user_question: str, 
        product_context: dict, 
        history: list
    ) -> str:
        """
        Calls the Google Gemini API with system instructions.
        """
        model_name = settings.LLM_MODEL.strip("'\"")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.LLM_API_KEY}"
        
        # Build contents from history
        contents = []
        for msg in history:
            contents.append({
                "role": "model" if msg["role"] == "assistant" else "user",
                "parts": [{"text": msg["content"]}]
            })
            
        # Append latest context and query
        context_str = f"Contexto do Produto:\n{str(product_context)}\n\nPergunta do Comprador:\n{user_question}"
        contents.append({
            "role": "user",
            "parts": [{"text": context_str}]
        })

        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 400
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError):
                    logger.error(f"Unexpected response shape from Gemini: {data}")
                    raise Exception("Invalid Gemini response format")
            
            logger.error(f"Gemini API returned error status {response.status_code}: {response.text}")
            raise Exception(f"Gemini API Error: {response.status_code}")

    async def _call_openai(
        self, 
        system_prompt: str, 
        user_question: str, 
        product_context: dict, 
        history: list
    ) -> str:
        """
        Calls OpenAI Chat Completions API.
        """
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json"
        }

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
            
        context_str = f"Contexto do Produto:\n{str(product_context)}\n\nPergunta do Comprador:\n{user_question}"
        messages.append({"role": "user", "content": context_str})

        model_name = settings.LLM_MODEL.strip("'\"") if settings.LLM_MODEL else "gpt-4-turbo"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 400
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            
            logger.error(f"OpenAI API returned error status {response.status_code}: {response.text}")
            raise Exception(f"OpenAI API Error: {response.status_code}")

    def _get_mock_sales_response(self, user_question: str, product_context: dict) -> str:
        """
        Returns a mock response matching the high-converting seller persona.
        Useful for fallback, demoing, and test runs.
        """
        title = product_context.get("title", "Curso")
        price = product_context.get("price", 197.90)
        
        normalized = user_question.lower()
        if "garantia" in normalized or "seguro" in normalized:
            return (
                f"Olá! Com certeza! O '{title}' tem garantia incondicional de 7 dias. "
                "Se você não ficar satisfeito, devolvemos 100% do seu dinheiro direto pelo Mercado Pago. "
                "Além disso, a liberação do acesso é imediata. Aproveite as últimas vagas desse lote promocional!"
            )
        elif "funciona" in normalized or "como" in normalized:
            return (
                f"Olá! O '{title}' funciona de forma 100% online/digital. O acesso é enviado diretamente "
                "no seu e-mail e chat pós-venda em segundos após a confirmação. O conteúdo é prático e "
                "direto ao ponto para você ter resultados rápidos. Vamos garantir o seu?"
            )
        elif "frete" in normalized or "gratis" in normalized or "grátis" in normalized:
            return (
                f"Olá! Por se tratar de um produto com entrega digital, o envio é totalmente GRÁTIS e "
                "imediato. Não há custos de entrega! Você receberá tudo em minutos no seu e-mail. "
                "Qualquer dúvida estou à disposição!"
            )
        
        return (
            f"Olá! Excelente pergunta. O '{title}' (apenas R$ {price}) é a solução mais completa "
            "do mercado. Com ele você conta com suporte premium e material atualizado para 2026. "
            "Temos pouquíssimas licenças remanescentes com este valor especial. Posso garantir a sua?"
        )

ai_service = AIService()
