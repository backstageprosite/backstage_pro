import hashlib
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives

from core.models import EmailDelivery, BandSubscription, Band, BandActivationToken

logger = logging.getLogger(__name__)


def get_canonical_base_url() -> str:
    """
    Retorna a URL base canônica para links em e-mails transacionais.
    Homologação: URL Railway oficial.
    Produção: https://backstagepro.site (ou configurado via CANONICAL_BASE_URL).
    """
    raw = getattr(settings, 'CANONICAL_BASE_URL', None) or getattr(settings, 'RAILWAY_PUBLIC_DOMAIN', None)
    if raw:
        raw = raw.strip()
        if not raw.startswith('http://') and not raw.startswith('https://'):
            raw = f"https://{raw}"
        return raw.rstrip('/')

    is_prod = getattr(settings, 'IS_PRODUCTION', False)
    django_env = getattr(settings, 'DJANGO_ENV', 'development').strip().lower()

    if is_prod and django_env == 'production':
        return "https://backstagepro.site"
    elif is_prod or django_env in {'staging', 'homologacao'}:
        return "https://backstage-pro-web-homologacao.up.railway.app"
    else:
        return "https://backstage-pro-web-homologacao.up.railway.app"


def resolve_subscription_recipient(sub: BandSubscription) -> Tuple[str, str]:
    """
    Resolve o destinatário canônico para e-mails de uma assinatura.
    Retorna: (email, nome)
    Prioridade:
    1. sub.billing_email se válido
    2. Produtor/Empresário da banda
    3. Primeiro usuário da banda
    4. fallback vazio
    """
    if not sub:
        return ('', 'Cliente')

    name = getattr(sub, 'financial_responsible_name', None) or ''
    if sub.billing_email and sub.billing_email.strip():
        return (sub.billing_email.strip(), name or (sub.band.name if sub.band else 'Cliente'))

    if sub.band:
        produtor = sub.band.users.filter(role__in=['PRODUTOR', 'EMPRESARIO']).exclude(email='').first()
        if produtor and produtor.email and produtor.email.strip():
            p_name = produtor.get_full_name() or produtor.first_name or produtor.username
            return (produtor.email.strip(), name or p_name)

        any_user = sub.band.users.exclude(email='').first()
        if any_user and any_user.email and any_user.email.strip():
            u_name = any_user.get_full_name() or any_user.first_name or any_user.username
            return (any_user.email.strip(), name or u_name)

    return ('', name or 'Cliente')


def generate_deterministic_message_id(idempotency_key: str) -> str:
    """
    Gera um Message-ID SMTP determinístico a partir do SHA-256 da idempotency_key.
    Não contém dados pessoais nem segredos.
    """
    key_hash = hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]
    return f"<{key_hash}@backstagepro.mail>"


def enqueue_email(
    email_type: str,
    recipient_email: str,
    subject: str,
    idempotency_key: str,
    template_name: Optional[str] = None,
    context_data: Optional[Dict[str, Any]] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[str] = None,
    max_attempts: int = 6
) -> Tuple[EmailDelivery, bool]:
    """
    Enfileira um e-mail transacional de negócio na fila EmailDelivery de forma estritamente idempotente.
    NUNCA executa envio SMTP síncrono.
    """
    if not recipient_email or not recipient_email.strip():
        logger.warning("Tentativa de enfileirar e-mail com destinatário vazio: type=%s, key=%s", email_type, idempotency_key)
        delivery, created = EmailDelivery.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                'email_type': email_type,
                'recipient_email': 'missing_recipient@backstagepro.local',
                'subject': subject,
                'template_name': template_name,
                'context_data': context_data or {},
                'related_object_type': related_object_type,
                'related_object_id': str(related_object_id) if related_object_id else None,
                'status': EmailDelivery.Status.FAILED,
                'last_error_code': 'RECIPIENT_MISSING',
                'last_error_message': 'Destinatário não encontrado ou vazio.',
                'message_id': generate_deterministic_message_id(idempotency_key),
            }
        )
        return delivery, created

    msg_id = generate_deterministic_message_id(idempotency_key)
    sanitized_context = context_data.copy() if context_data else {}

    delivery, created = EmailDelivery.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            'email_type': email_type,
            'recipient_email': recipient_email.strip(),
            'subject': subject,
            'template_name': template_name,
            'context_data': sanitized_context,
            'related_object_type': related_object_type,
            'related_object_id': str(related_object_id) if related_object_id else None,
            'status': EmailDelivery.Status.PENDING,
            'max_attempts': max_attempts,
            'next_attempt_at': timezone.now(),
            'message_id': msg_id,
        }
    )

    if created:
        logger.info("E-mail enfileirado com sucesso: ID=%s, type=%s, key=%s", delivery.id, email_type, idempotency_key)
    else:
        logger.info("E-mail já existente na fila (idempotente): ID=%s, status=%s, key=%s", delivery.id, delivery.status, idempotency_key)

    return delivery, created


def render_and_send_email_delivery(delivery: EmailDelivery) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Renderiza o template HTML e TXT associado à EmailDelivery e executa o envio SMTP via Django EmailBackend.
    Retorna: (sucesso: bool, error_code: str, error_message: str)
    """
    ctx = delivery.context_data.copy() if delivery.context_data else {}
    base_url = get_canonical_base_url()
    ctx['base_url'] = base_url

    # Resolução dinâmica para ACCOUNT_ACTIVATION (link seguro em memória)
    if delivery.email_type == EmailDelivery.EmailType.ACCOUNT_ACTIVATION:
        if delivery.related_object_id:
            try:
                activation = BandActivationToken.objects.get(pk=delivery.related_object_id)
                if activation.used_at is not None:
                    return False, 'ACTIVATION_TOKEN_ALREADY_USED', 'O token de ativação já foi utilizado anteriormente.'
                if not activation.is_valid():
                    return False, 'ACTIVATION_TOKEN_EXPIRED', 'O token de ativação expirou (prazo de 48h).'
                # Se o raw_token estiver no context temporário de memória ou precisar montar URL
                raw_tok = ctx.get('_raw_activation_token')
                if raw_tok:
                    ctx['activation_url'] = f"{base_url}/ativar-conta/{raw_tok}/"
                elif 'activation_url' not in ctx:
                    return False, 'ACTIVATION_TOKEN_RAW_MISSING', 'Token em texto puro não disponível para geração do link.'
            except BandActivationToken.DoesNotExist:
                return False, 'ACTIVATION_TOKEN_NOT_FOUND', 'Registro BandActivationToken não encontrado.'

    template_base = delivery.template_name or f"emails/{delivery.email_type.lower()}"
    html_template = f"{template_base}.html"
    txt_template = f"{template_base}.txt"

    try:
        body_html = render_to_string(html_template, ctx)
    except Exception as e:
        logger.warning("Template HTML %s não encontrado ou erro na renderização: %s", html_template, str(e))
        body_html = None

    try:
        body_txt = render_to_string(txt_template, ctx)
    except Exception as e:
        logger.warning("Template TXT %s não encontrado: %s", txt_template, str(e))
        body_txt = ctx.get('body_text') or delivery.subject

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Backstage Pro <backstagepro.site@gmail.com>')

    headers = {}
    if delivery.message_id:
        headers['Message-ID'] = delivery.message_id

    email_msg = EmailMultiAlternatives(
        subject=delivery.subject,
        body=body_txt,
        from_email=from_email,
        to=[delivery.recipient_email],
        headers=headers
    )

    if body_html:
        email_msg.attach_alternative(body_html, "text/html")

    try:
        sent_count = email_msg.send(fail_silently=False)
        if sent_count >= 1:
            return True, None, None
        else:
            return False, 'SMTP_REJECTED', 'O servidor SMTP não confirmou a aceitação da mensagem (0 entregas).'
    except Exception as e:
        err_str = str(e)
        err_type = type(e).__name__
        logger.error("Falha no envio SMTP para delivery %s (%s): %s", delivery.id, delivery.recipient_email, err_str)
        return False, err_type, err_str[:500]
