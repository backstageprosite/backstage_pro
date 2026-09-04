import json
import logging
from typing import Dict, Any, Tuple
from django.utils import timezone
from core.models import PaymentWebhookEvent, BillingRecord, BandSubscription
from core.services.payments.provisioning import process_checkout_paid_event

logger = logging.getLogger(__name__)


def reconcile_and_update_billing_record(payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    """
    Concilia eventos de cobrança/pagamento (ex: PAYMENT_CONFIRMED, PAYMENT_RECEIVED, PAYMENT_OVERDUE).
    Garante que eventos múltiplos com o mesmo payment_id atualizem o mesmo registro (Idempotência de BillingRecord).
    """
    payment_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else payload
    payment_id = payment_data.get('id') or payload.get('paymentId')
    external_ref = payment_data.get('externalReference') or payload.get('externalReference')
    subscription_id = payment_data.get('subscription') or payload.get('subscription')
    customer_id = payment_data.get('customer') or payload.get('customer')

    if not payment_id:
        return True, "EVENTO_SEM_PAYMENT_ID"

    # 1. Buscar se já existe BillingRecord por (gateway_provider, gateway_payment_id)
    record = BillingRecord.objects.filter(
        gateway_provider='ASAAS',
        gateway_payment_id=payment_id
    ).first()

    # 2. Se não encontrou por payment_id, tentar conciliar com a fatura inicial do CHECKOUT_PAID por external_reference
    if not record and external_ref:
        record = BillingRecord.objects.filter(
            gateway_provider='ASAAS',
            gateway_external_reference=external_ref,
            gateway_payment_id__isnull=True
        ).first()

    # 3. Se ainda não encontrou, localizar a BandSubscription e criar/atualizar fatura recorrente
    if not record and (subscription_id or external_ref):
        sub = None
        if subscription_id:
            sub = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_subscription_id=subscription_id).first()
        if not sub and external_ref:
            sub = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=external_ref).first()

        if sub:
            today = timezone.localdate()
            month_names = {
                1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
                5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
            }
            ref_period = f"{month_names[today.month]}/{today.year}"
            raw_value = payment_data.get('value') or payment_data.get('netValue') or sub.contracted_value
            from decimal import Decimal
            amount_val = Decimal(str(raw_value))

            record = BillingRecord.objects.create(
                subscription=sub,
                band=sub.band,
                reference_period=ref_period,
                plan_name=sub.plan_name,
                billing_cycle=sub.billing_cycle,
                amount=amount_val,
                due_date=today,
                status='PENDENTE',
                payment_method='CARTAO',
                gateway_provider='ASAAS',
                gateway_payment_id=payment_id,
                gateway_external_reference=external_ref,
                gateway_event_status=event_type
            )

    if record:
        # Atualizar status da fatura conforme o evento Asaas
        if not record.gateway_payment_id:
            record.gateway_payment_id = payment_id
        record.gateway_event_status = event_type
        if event_type in ('PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED'):
            record.status = 'PAGO'
            if not record.paid_date:
                record.paid_date = timezone.localdate()
        elif event_type in ('PAYMENT_OVERDUE',):
            if record.status != 'PAGO':
                record.status = 'PENDENTE'
        record.save()
        return True, "BILLING_CONCILIADO"

    return True, "EVENTO_REGISTRADO_SEM_ASSINATURA_LOCAL"


def handle_asaas_webhook_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Entrada principal para processar webhooks do Asaas.
    Implementa Idempotência Nível 1 via PaymentWebhookEvent.gateway_event_id.
    """
    event_id = payload.get('id') or payload.get('eventId')
    event_type = payload.get('event') or payload.get('eventType')

    if not event_id or not event_type:
        return False, "PAYLOAD_INVALIDO_SEM_ID_OU_EVENTO"

    # Nível 1: Verificar se o evento exato já foi registrado/processado
    webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
        gateway_event_id=event_id,
        defaults={
            'provider': 'ASAAS',
            'event_type': event_type,
            'payload': payload,
            'processed': False
        }
    )

    if not created and webhook_event.processed:
        logger.info("Webhook %s ja foi processado com sucesso. Idempotencia nivel 1 garantida.", event_id)
        return True, "EVENTO_JA_PROCESSADO"

    success = False
    msg = ""

    try:
        # Roteamento dos eventos canônicos
        if event_type in ('CHECKOUT_PAID', 'PAYMENT_CHECKOUT_PAID'):
            success, msg, _ = process_checkout_paid_event(payload, gateway_event_id=event_id)
        elif event_type in ('PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED', 'PAYMENT_OVERDUE', 'PAYMENT_UPDATED', 'PAYMENT_DELETED'):
            success, msg = reconcile_and_update_billing_record(payload, event_type)
        elif event_type == 'SUBSCRIPTION_CREATED':
            msg = "Assinatura Asaas sincronizada com sucesso."
            success = True
        else:
            msg = f"Evento {event_type} registrado com sucesso."
            success = True

        webhook_event.processed = success
        webhook_event.processed_at = timezone.now()
        webhook_event.error_message = None if success else msg
        webhook_event.save()

    except Exception as e:
        logger.exception("Erro ao processar webhook %s (%s): %s", event_id, event_type, str(e))
        webhook_event.processed = False
        webhook_event.error_message = str(e)
        webhook_event.save()
        return False, str(e)

    return success, msg
