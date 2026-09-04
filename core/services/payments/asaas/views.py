import json
import logging
import secrets
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.models import PaymentWebhookEvent
from core.services.payments.base import AsaasConfig

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def asaas_webhook_view(request):
    """
    Endpoint publico para recebimento de webhooks do Asaas.
    Valida token de autenticacao em tempo constante, valida formato do payload,
    persiste o evento em PaymentWebhookEvent (com idempotencia por gateway_event_id)
    e retorna HTTP 200 rapidamente.
    """
    config = AsaasConfig.from_settings()
    configured_token = config.webhook_token

    # 1. Autenticacao obrigatoria por token
    if not configured_token:
        logger.error("Webhook Asaas recebido, mas ASAAS_WEBHOOK_TOKEN nao esta configurado no servidor.")
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    received_token = request.headers.get('asaas-access-token') or request.META.get('HTTP_ASAAS_ACCESS_TOKEN')
    if not received_token:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    if not secrets.compare_digest(str(received_token), str(configured_token)):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    # 2. Parsing e validacao do JSON
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({'error': 'Invalid payload format'}, status=400)

    event_id = payload.get('id') or payload.get('eventId')
    event_type = payload.get('event') or payload.get('eventType')

    if not event_id or not event_type:
        return JsonResponse({'error': 'Missing id or event in payload'}, status=400)

    # 3. Sanitizacao recursiva de dados sensiveis (PCI-DSS / Seguranca de Token)
    from core.services.payments.security import sanitize_webhook_payload
    safe_payload = sanitize_webhook_payload(payload)

    # 4. Persistencia idempotente em PaymentWebhookEvent (Nivel 1)
    webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
        gateway_event_id=str(event_id),
        defaults={
            'provider': 'ASAAS',
            'event_type': str(event_type),
            'payload': safe_payload,
            'processed': False,
        }
    )

    if not created:
        logger.info("Webhook Asaas %s (%s) ja havia sido recebido previamente.", event_id, event_type)
        return JsonResponse({'status': 'received', 'duplicate': True}, status=200)

    logger.info("Webhook Asaas %s (%s) recebido e persistido com sucesso.", event_id, event_type)
    return JsonResponse({'status': 'received', 'duplicate': False}, status=200)
