import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import settings

class PromptEncryption:
    @staticmethod
    def generate_key() -> str:
        """
        Generates a 32-byte key and returns it as a base64 encoded string.
        """
        key = AESGCM.generate_key(bit_length=256)
        return base64.b64encode(key).decode('utf-8')

    @staticmethod
    def encrypt(text: str, key_b64: str) -> str:
        """
        Encrypts text using AES-256-GCM.
        Returns base64 encoded string of (nonce + ciphertext).
        """
        key = base64.b64decode(key_b64)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 12-byte nonce for GCM
        ciphertext = aesgcm.encrypt(nonce, text.encode('utf-8'), None)
        # Combine nonce and ciphertext
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode('utf-8')

    @staticmethod
    def decrypt(encrypted_b64: str, key_b64: str) -> str:
        """
        Decrypts a base64 encoded string containing (nonce + ciphertext) using AES-256-GCM.
        """
        try:
            key = base64.b64decode(key_b64)
            combined = base64.b64decode(encrypted_b64)
            if len(combined) < 12:
                raise ValueError("Encrypted data is too short.")
            
            nonce = combined[:12]
            ciphertext = combined[12:]
            
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Failed to decrypt prompt. Verify key/payload. Error: {str(e)}")

# Helper to load decrypted prompt master in-memory
_cached_prompt: str = ""

def get_decrypted_master_prompt() -> str:
    """
    Retrieves and decrypts the master prompt from settings, caching it in-memory.
    Never exposes the raw decrypted prompt outside of internal processing.
    """
    global _cached_prompt
    if _cached_prompt:
        return _cached_prompt

    if not settings.PROMPT_DECRYPTION_KEY or not settings.MASTER_PROMPT_ENCRYPTED:
        raise ValueError("Decryption key or encrypted prompt is not set in environment.")

    _cached_prompt = PromptEncryption.decrypt(
        settings.MASTER_PROMPT_ENCRYPTED, 
        settings.PROMPT_DECRYPTION_KEY
    )
    return _cached_prompt
