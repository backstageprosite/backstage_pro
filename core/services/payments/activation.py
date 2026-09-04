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


def reissue_activation_token(
    band: Band,
    signup_order: SignupOrder = None,
    valid_hours: int = 48
) -> Tuple[BandActivationToken, str]:
    """
    Invalida tokens ativos anteriores da mesma contratação/banda e gera um novo BandActivationToken.
    Retorna: (new_activation_instance, raw_token)
    """
    now = timezone.now()

    # Invalida tokens anteriores não utilizados da mesma banda/pedido marcando used_at ou expirando
    qs = BandActivationToken.objects.filter(band=band, used_at__isnull=True)
    if signup_order:
        qs = qs.filter(signup_order=signup_order)

    # Invalida definindo expires_at no passado para preservar histórico
    qs.filter(expires_at__gt=now).update(expires_at=now)

    email = (signup_order.email if signup_order else None) or ""
    responsible_name = (signup_order.responsible_name if signup_order else None) or band.name

    return create_band_activation_token(
        band=band,
        email=email,
        responsible_name=responsible_name,
        signup_order=signup_order,
        valid_hours=valid_hours
    )


def build_activation_email_data(raw_token: str, activation: BandActivationToken, base_url: str = None) -> dict:
    """
    Prepara o payload e dados estruturados para envio do e-mail de ativação de conta.
    NÃO dispara o envio de e-mail externo.
    """
    if not base_url:
        base_url = "https://backstage-pro-web-homologacao.up.railway.app"
    base_url = base_url.rstrip('/')
    activation_url = f"{base_url}/ativar-conta/{raw_token}/"
    band_name = activation.band.name if activation.band else "Sua Banda"
    responsible_name = activation.responsible_name or "Produtor(a)"

    subject = "Ative sua conta no Backstage Pro"
    body_text = (
        f"Olá, {responsible_name}!\n\n"
        f"Seja bem-vindo(a) ao Backstage Pro. A assinatura para a banda '{band_name}' foi confirmada com sucesso!\n\n"
        f"Para criar sua conta de acesso e começar a gerenciar sua produção musical, clique no link abaixo:\n"
        f"{activation_url}\n\n"
        f"Este link é de uso único e expira em 48 horas.\n\n"
        f"Importante: Após entrar, acesse Configurações para inserir a logo da sua banda ou artista e personalizar o Backstage Pro.\n\n"
        f"Equipe Backstage Pro"
    )

    return {
        'subject': subject,
        'recipient_email': activation.email,
        'responsible_name': responsible_name,
        'band_name': band_name,
        'activation_url': activation_url,
        'expires_at': activation.expires_at,
        'body_text': body_text
    }
