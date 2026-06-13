import re
import logging

logger = logging.getLogger(__name__)

class PromptInjectionException(Exception):
    """Exception raised when an injection attack is detected in user input."""
    pass

class PromptGuard:
    # Heuristics for jailbreaks
    JAILBREAK_PATTERNS = [
        r"(ignore|ignorar|ignora)\s+(as|os|previous|instructions|instruções|diretrizes|regras)",
        r"(system\s*prompt|prompt\s*de\s*sistema|prompt\s*original|prompt\s*mestre)",
        r"(developer\s*mode|modo\s*desenvolvedor|modo\s*de\s*desenvolvedor|dan\s*mode)",
        r"(you\s*are\s*now\s*a|você\s*agora\s*é\s*um|aja\s*como|decode\s*base64|traduzir\s*base64)",
        r"(rules\s*of\s*engagement|regras\s*de\s*atuação|regras\s*do\s*robô)",
        r"(vaze\s*o|vazar\s*o|exponha\s*o|exibir\s*instruções)",
        r"tente\s+ignorar\s+os\s+limites",
        r"nova\s+persona",
        r"reset\s+instruction"
    ]

    # Patterns indicating that the LLM might have leaked rules in its output
    LEAK_PATTERNS = [
        r"Você é o Robô Especialista em Vendas",
        r"DSE Meli Sync",
        r"vendedor de alta conversão",
        r"dropshipping",
        r"Prompt Master",
        r"System Prompt",
        r"DIRETRIZES DE COMPORTAMENTO"
    ]

    @classmethod
    def validate_input(cls, text: str) -> None:
        """
        Scans user input for prompt injection signatures.
        Raises PromptInjectionException if a match is found.
        """
        if not text:
            return

        normalized_text = text.lower().strip()
        
        # Check against blacklist patterns
        for pattern in cls.JAILBREAK_PATTERNS:
            if re.search(pattern, normalized_text):
                logger.warning(f"Security Alert: Possible Prompt Injection detected! Pattern: {pattern}")
                raise PromptInjectionException("Solicitação inválida. Por favor, reformule sua pergunta sobre o produto.")

    @classmethod
    def sanitize_output(cls, model_output: str) -> str:
        """
        Scans model output to ensure no system instructions or backend jargon leaked.
        If a leak is suspected, overrides the output with a generic high-conversion fallback response.
        """
        if not model_output:
            return "Olá! Sou o especialista de vendas. Como posso te ajudar com as compras hoje?"

        # Count how many leak indicators match
        matches = 0
        for pattern in cls.LEAK_PATTERNS:
            if re.search(pattern, model_output, re.IGNORECASE):
                matches += 1

        # If 2 or more leak signatures match, we assume a leak occurred
        if matches >= 2:
            logger.error(f"Security Alert: LLM response leaked system prompt metadata! Overriding response.")
            return (
                "Olá! Estou aqui para tirar qualquer dúvida sobre os nossos produtos "
                "e garantir a melhor experiência de compra para você. Qual produto você gostaria de conhecer hoje?"
            )
            
        return model_output
