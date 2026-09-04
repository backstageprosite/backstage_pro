import os
import logging
from typing import Optional, Any, Dict, List
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def get_encryption_key() -> bytes:
    """
    Recupera a chave Fernet configurada em PAYMENT_TOKEN_ENCRYPTION_KEY.
    A chave deve ser uma string base64 válida de 32 bytes (44 caracteres).
    """
    key = getattr(settings, 'PAYMENT_TOKEN_ENCRYPTION_KEY', None) or os.getenv('PAYMENT_TOKEN_ENCRYPTION_KEY')
    if not key:
        raise ValueError(
            "PAYMENT_TOKEN_ENCRYPTION_KEY nao configurada no servidor. "
            "Defina uma chave Fernet valida de 32 bytes."
        )
    if isinstance(key, str):
        key = key.strip().encode('utf-8')
    return key


def encrypt_payment_token(token: str) -> str:
    """
    Criptografa um token de meio de pagamento utilizando Fernet (AES-128-CBC + HMAC-SHA256).
    Retorna o ciphertext seguro codificado em string base64.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Token invalido para criptografia.")
    
    key = get_encryption_key()
    f = Fernet(key)
    ciphertext = f.encrypt(token.strip().encode('utf-8'))
    return ciphertext.decode('utf-8')


def decrypt_payment_token(encrypted_token: str) -> str:
    """
    Descriptografa um token de meio de pagamento cifrado com Fernet.
    Retorna o token original em texto plano para uso estritamente em memoria.
    """
    if not encrypted_token or not isinstance(encrypted_token, str):
        raise ValueError("Ciphertext invalido para descriptografia.")

    key = get_encryption_key()
    f = Fernet(key)
    try:
        decrypted_bytes = f.decrypt(encrypted_token.strip().encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken as e:
        logger.error("Falha ao descriptografar token: chave incorreta ou token corrompido.")
        raise ValueError("Falha na descriptografia do token de pagamento.") from e


def get_activation_encryption_key() -> bytes:
    """
    Recupera a chave Fernet configurada em ACTIVATION_TOKEN_ENCRYPTION_KEY ou PAYMENT_TOKEN_ENCRYPTION_KEY.
    A chave deve ser uma string base64 válida de 32 bytes (44 caracteres).
    """
    key = getattr(settings, 'ACTIVATION_TOKEN_ENCRYPTION_KEY', None) or os.getenv('ACTIVATION_TOKEN_ENCRYPTION_KEY')
    if not key:
        key = getattr(settings, 'PAYMENT_TOKEN_ENCRYPTION_KEY', None) or os.getenv('PAYMENT_TOKEN_ENCRYPTION_KEY')
    if not key:
        secret = getattr(settings, 'SECRET_KEY', 'default-dev-secret-key-32-chars-long!')
        import base64, hashlib
        derived = hashlib.sha256(secret.encode('utf-8')).digest()
        key = base64.urlsafe_b64encode(derived)
    if isinstance(key, str):
        key = key.strip().encode('utf-8')
    return key


def encrypt_activation_token(token: str) -> str:
    """
    Criptografa um token de ativação de conta utilizando Fernet (AES-128-CBC + HMAC-SHA256).
    Retorna o ciphertext seguro codificado em string base64.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Token invalido para criptografia.")

    key = get_activation_encryption_key()
    f = Fernet(key)
    ciphertext = f.encrypt(token.strip().encode('utf-8'))
    return ciphertext.decode('utf-8')


def decrypt_activation_token(encrypted_token: str) -> str:
    """
    Descriptografa um token de ativação cifrado com Fernet.
    Retorna o token original em texto plano para montagem estritamente em memoria pelo worker de email.
    """
    if not encrypted_token or not isinstance(encrypted_token, str):
        raise ValueError("Ciphertext invalido para descriptografia.")

    key = get_activation_encryption_key()
    f = Fernet(key)
    try:
        decrypted_bytes = f.decrypt(encrypted_token.strip().encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken as e:
        logger.error("Falha ao descriptografar token de ativacao: chave incorreta ou token corrompido.")
        raise ValueError("Falha na descriptografia do token de ativacao.") from e


SENSITIVE_FIELD_NAMES = {
    # Tokens e segredos
    'creditcardtoken', 'token', 'access_token', 'accesstoken', 'secret',
    # Dados de PAN e segurança de cartão
    'creditcardnumber', 'cardnumber', 'number', 'cvv', 'cvc', 'securitycode',
    # Dados de titularidade quando agrupados em objetos de cartão
    'creditcardholderinfo'
}

SAFE_CARD_FIELDS = {'brand', 'creditcardbrand', 'last4', 'creditcardnumber_last4'}


def sanitize_webhook_payload(data: Any) -> Any:
    """
    Sanitiza recursivamente um dicionário ou lista de payload de webhook,
    removendo qualquer dado sensível de cartão (PAN, CVV, creditCardToken, creditCardHolderInfo),
    preservando estritamente metadados operacionais e de conciliação:
    brand, last4, IDs, customer, payment, installment, status, value, dates, externalReference.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            key_lower = str(k).strip().lower().replace('_', '').replace('-', '')
            
            # Se a chave for sensível, remove
            if key_lower in SENSITIVE_FIELD_NAMES:
                continue

            # Se o valor for um dicionário de cartão ('creditCard'), processa recursivamente mantendo apenas brand e last4
            if key_lower in ('creditcard', 'card'):
                if isinstance(v, dict):
                    card_dict = {}
                    if 'creditCardBrand' in v:
                        card_dict['creditCardBrand'] = v['creditCardBrand']
                    elif 'brand' in v:
                        card_dict['brand'] = v['brand']
                    
                    # Preserva apenas os ultimos 4 digitos
                    raw_num = str(v.get('creditCardNumber') or v.get('cardNumber') or v.get('last4') or '')
                    if raw_num:
                        last4 = raw_num[-4:] if len(raw_num) >= 4 else raw_num
                        card_dict['creditCardNumber'] = last4
                    sanitized[k] = card_dict
                continue

            # Recursão para outros dicionários ou listas
            sanitized[k] = sanitize_webhook_payload(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_webhook_payload(item) for item in data]
    return data

