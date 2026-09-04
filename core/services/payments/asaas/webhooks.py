import json
import logging
from decimal import Decimal
from typing import Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone
from core.models import PaymentWebhookEvent, BillingRecord, BandSubscription, SignupOrder
from core.services.payments.provisioning import process_checkout_paid_event

logger = logging.getLogger(__name__)


def reconcile_and_update_billing_record(payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    payment_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else payload
    payment_id = payment_data.get('id') or payload.get('paymentId')
    external_ref = payment_data.get('externalReference') or payload.get('externalReference')
    subscription_id = payment_data.get('subscription') or payload.get('subscription')
    customer_id = payment_data.get('customer') or payload.get('customer')

    if not payment_id:
        return False, 'EVENTO_SEM_PAYMENT_ID'

    record = BillingRecord.objects.filter(
        gateway_provider='ASAAS',
        gateway_payment_id=payment_id
    ).first()

    if not record and external_ref:
        record = BillingRecord.objects.filter(
            gateway_provider='ASAAS',
            gateway_external_reference=external_ref,
            gateway_payment_id__isnull=True
        ).first()
        if record:
            record.gateway_payment_id = payment_id

    if not record and subscription_id:
        matching_subs = BandSubscription.objects.filter(
            gateway_provider='ASAAS',
            gateway_subscription_id=subscription_id
        )
        if matching_subs.count() == 1:
            sub = matching_subs.first()
            today = timezone.localdate()
            month_names = {
                1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril',
                5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
            }
            ref_period = f'{month_names[today.month]}/{today.year}'
            raw_value = payment_data.get('value') or payment_data.get('netValue') or sub.contracted_value
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
        elif matching_subs.count() > 1:
            return False, f'AMBIGUIDADE: Multiplas assinaturas locais para gateway_subscription_id={subscription_id}'
        else:
            return False, f'AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID: BandSubscription nao encontrada para gateway_subscription_id={subscription_id}'

    if not record:
        return False, f'AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID: payment_id={payment_id}, ref={external_ref}, sub={subscription_id}'

    record.gateway_event_status = event_type
    if event_type in ('PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED'):
        record.status = 'PAGO'
        if not record.paid_date:
            record.paid_date = payment_data.get('paymentDate') or payment_data.get('clientPaymentDate') or payment_data.get('confirmedDate') or timezone.localdate()
    elif event_type in ('PAYMENT_OVERDUE',):
        if record.status != 'PAGO':
            record.status = 'PENDENTE'
    elif event_type in ('PAYMENT_REFUNDED',):
        record.status = 'ESTORNADO' if hasattr(record, 'status') else record.status

    record.save()
    return True, 'BILLING_CONCILIADO'


def handle_subscription_event(payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    sub_data = payload.get('subscription') if isinstance(payload.get('subscription'), dict) else payload
    sub_id = sub_data.get('id') or payload.get('subscriptionId')
    customer_id = sub_data.get('customer') or payload.get('customer')
    external_ref = sub_data.get('externalReference') or payload.get('externalReference')

    if not sub_id:
        return False, 'SUBSCRIPTION_EVENT_SEM_ID'

    sub = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_subscription_id=sub_id).first()
    if sub:
        if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
            sub.status = 'CANCELADO'
            sub.save()
        return True, f'SUBSCRIPTION_{event_type}_SINCRONIZADA'

    if external_ref:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=external_ref)
        if matching.count() == 1:
            sub = matching.first()
            sub.gateway_subscription_id = sub_id
            if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
                sub.status = 'CANCELADO'
            sub.save()
            return True, 'SUBSCRIPTION_VINCULADA_POR_EXTERNAL_REFERENCE'
        elif matching.count() > 1:
            return False, f'AMBIGUIDADE: Multiplas BandSubscriptions com externalReference={external_ref}'

    if customer_id:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_customer_id=customer_id)
        if matching.count() == 1:
            sub = matching.first()
            if not sub.gateway_subscription_id or sub.gateway_subscription_id == sub_id:
                sub.gateway_subscription_id = sub_id
                if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
                    sub.status = 'CANCELADO'
                sub.save()
                return True, 'SUBSCRIPTION_VINCULADA_POR_CUSTOMER_UNICO'
            else:
                return False, f'AMBIGUIDADE: Assinatura do customer={customer_id} ja possui outro gateway_subscription_id={sub.gateway_subscription_id}'
        elif matching.count() > 1:
            return False, f'AMBIGUIDADE: Multiplas BandSubscriptions para o customer={customer_id}'

    return False, f'BandSubscription nao encontrada de forma inequivoca para sub_id={sub_id}'


def handle_checkout_event(payload: Dict[str, Any], event_type: str, event_id: str = None) -> Tuple[bool, str]:
    checkout_data = payload.get('checkout') if isinstance(payload.get('checkout'), dict) else payload
    checkout_id = checkout_data.get('id') or payload.get('checkoutId')
    external_ref = checkout_data.get('externalReference') or payload.get('externalReference')

    order = None
    if checkout_id:
        order = SignupOrder.objects.filter(gateway_checkout_id=checkout_id).first()
    if not order and external_ref:
        order = SignupOrder.objects.filter(external_reference=external_ref).first()

    if event_type == 'CHECKOUT_CREATED':
        if order:
            if order.status == 'PENDENTE':
                return True, 'CHECKOUT_CREATED_PROCESSADO'
            return True, f'CHECKOUT_CREATED_IGNORADO_STATUS_{order.status}'
        return True, 'CHECKOUT_CREATED_SIGNUPORDER_NAO_ENCONTRADO'

    elif event_type == 'CHECKOUT_CANCELED':
        if order:
            if order.status != 'PAGO':
                order.status = 'CANCELADO'
                order.save()
                return True, 'CHECKOUT_CANCELED_PROCESSADO'
            return True, 'CHECKOUT_CANCELED_IGNORADO_JA_PAGO'
        return True, 'CHECKOUT_CANCELED_SIGNUPORDER_NAO_ENCONTRADO'

    elif event_type == 'CHECKOUT_EXPIRED':
        if order:
            if order.status != 'PAGO':
                order.status = 'EXPIRADO'
                order.save()
                return True, 'CHECKOUT_EXPIRED_PROCESSADO'
            return True, 'CHECKOUT_EXPIRED_IGNORADO_JA_PAGO'
        return True, 'CHECKOUT_EXPIRED_SIGNUPORDER_NAO_ENCONTRADO'

    elif event_type in ('CHECKOUT_PAID', 'PAYMENT_CHECKOUT_PAID'):
        success, msg, _ = process_checkout_paid_event(payload, gateway_event_id=event_id)
        return success, msg

    return True, f'CHECKOUT_{event_type}_PROCESSADO'


def process_webhook_event(webhook_event: PaymentWebhookEvent) -> Tuple[bool, str]:
    event_id = webhook_event.gateway_event_id
    event_type = webhook_event.event_type
    payload = webhook_event.payload or {}

    try:
        if event_type.startswith('CHECKOUT_') or event_type == 'PAYMENT_CHECKOUT_PAID':
            success, msg = handle_checkout_event(payload, event_type, event_id=event_id)
        elif event_type.startswith('SUBSCRIPTION_'):
            success, msg = handle_subscription_event(payload, event_type)
        elif event_type.startswith('PAYMENT_'):
            success, msg = reconcile_and_update_billing_record(payload, event_type)
        else:
            success = True
            msg = f'EVENTO_{event_type}_IGNORADO'

        webhook_event.processed = success
        webhook_event.processed_at = timezone.now()
        webhook_event.error_message = None if success else msg
        webhook_event.save()
        return success, msg

    except Exception as e:
        logger.exception('Erro ao processar evento %s (%s): %s', event_id, event_type, str(e))
        webhook_event.processed = False
        webhook_event.error_message = str(e)
        webhook_event.save()
        return False, str(e)


def handle_asaas_webhook_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    event_id = payload.get('id') or payload.get('eventId')
    event_type = payload.get('event') or payload.get('eventType')

    if not event_id or not event_type:
        return False, 'PAYLOAD_INVALIDO_SEM_ID_OU_EVENTO'

    webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
        gateway_event_id=str(event_id),
        defaults={
            'provider': 'ASAAS',
            'event_type': str(event_type),
            'payload': payload,
            'processed': False
        }
    )

    if not created and webhook_event.processed:
        logger.info('Webhook %s ja foi processado com sucesso. Idempotencia nivel 1 garantida.', event_id)
        return True, 'EVENTO_JA_PROCESSADO'

    return process_webhook_event(webhook_event)
