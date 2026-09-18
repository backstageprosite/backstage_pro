import os
import logging
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

def get_google_token_encryption_key() -> bytes:
    """
    Recupera a chave Fernet para criptografia de tokens do Google OAuth.
    Procura em GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY e faz fallback para PAYMENT_TOKEN_ENCRYPTION_KEY ou chave derivada.
    """
    key = getattr(settings, 'GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY', None) or os.getenv('GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY')
    if not key:
        key = getattr(settings, 'PAYMENT_TOKEN_ENCRYPTION_KEY', None) or os.getenv('PAYMENT_TOKEN_ENCRYPTION_KEY')
    
    if not key:
        secret = getattr(settings, 'SECRET_KEY', 'default-secret-key-backstage-pro-fernet')
        import base64
        import hashlib
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())
    
    if isinstance(key, str):
        key = key.strip().encode('utf-8')
    return key

def encrypt_token(token: str) -> str:
    """
    Criptografa um token (access_token ou refresh_token) utilizando Fernet.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Token inválido para criptografia.")
    
    key = get_google_token_encryption_key()
    f = Fernet(key)
    ciphertext = f.encrypt(token.strip().encode('utf-8'))
    return ciphertext.decode('utf-8')

def decrypt_token(encrypted_token: str) -> str:
    """
    Descriptografa um token cifrado com Fernet para uso estritamente em memória.
    """
    if not encrypted_token or not isinstance(encrypted_token, str):
        raise ValueError("Ciphertext inválido para descriptografia.")

    key = get_google_token_encryption_key()
    f = Fernet(key)
    try:
        decrypted_bytes = f.decrypt(encrypted_token.strip().encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken as e:
        logger.error("Falha ao descriptografar token do Google Calendar: chave incorreta ou token corrompido.")
        raise ValueError("Falha na descriptografia do token do Google Calendar.") from e
