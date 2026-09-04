import hashlib
import secrets
from datetime import timedelta
from typing import Tuple
from django.utils import timezone
from core.models import Band, BandActivationToken, SignupOrder


def generate_activation_token_pair() -> Tuple[str, str]:
    """
    Gera um token criptograficamente seguro e seu hash SHA-256.
    Retorna: (raw_token, token_hash)
    O raw_token é enviado por e-mail para o comprador e NUNCA salvo em banco.
    O token_hash é persistido no banco de dados.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    return raw_token, token_hash


def create_band_activation_token(
    band: Band,
    email: str,
    responsible_name: str,
    signup_order: SignupOrder = None,
    valid_hours: int = 48
) -> Tuple[BandActivationToken, str]:
    """
    Cria registro de token de ativação com validade (padrão 48h) e retorna a instância e o token em texto puro.
    """
    raw_token, token_hash = generate_activation_token_pair()
    expires_at = timezone.now() + timedelta(hours=valid_hours)

    activation = BandActivationToken.objects.create(
        band=band,
        signup_order=signup_order,
        email=email,
        responsible_name=responsible_name,
        token_hash=token_hash,
        expires_at=expires_at
    )
    return activation, raw_token


def verify_activation_token(raw_token: str) -> Tuple[bool, str, BandActivationToken]:
    """
    Valida um raw_token recebido pela URL de ativação.
    Retorna: (is_valid, error_code, activation_instance)
    """
    if not raw_token or not raw_token.strip():
        return False, "TOKEN_VAZIO", None

    token_hash = hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()
    activation = BandActivationToken.objects.filter(token_hash=token_hash).first()

    if not activation:
        return False, "TOKEN_NAO_ENCONTRADO", None

    if activation.used_at is not None:
        return False, "TOKEN_JA_UTILIZADO", activation

    if timezone.now() > activation.expires_at:
        return False, "TOKEN_EXPIRADO", activation

    return True, "OK", activation
