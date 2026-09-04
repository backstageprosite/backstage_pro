import json
import logging
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from django.db import transaction
from django.utils import timezone
from core.models import PaymentWebhookEvent, BillingRecord, BandSubscription, SignupOrder
from core.services.payments.base import extract_asaas_id
from core.services.payments.provisioning import process_checkout_paid_event

logger = logging.getLogger(__name__)


def resolve_reactivation_subscription(
    checkout_id: Optional[str] = None,
    external_ref: Optional[str] = None,
    subscription_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    payment_data: Optional[Dict[str, Any]] = None,
    sub_data: Optional[Dict[str, Any]] = None,
) -> Optional[BandSubscription]:
    """
    Localiza de forma centralizada e segura a BandSubscription em estado de reativação
    utilizando a hierarquia estrita de confiança:
    1. gateway_checkout_id exato;
    2. gateway_external_reference exato de reativação;
    Apenas assinaturas em estado compatível com reativação (status in ('DESATIVADO', 'CANCELADO')
    ou cancel_at_period_end=True / auto_renew=False) são elegíveis para substituição de ID.
    """
    # 1. Busca por gateway_checkout_id direto
    chk = checkout_id
    if not chk and isinstance(payment_data, dict):
        chk = payment_data.get('checkoutSession') or payment_data.get('checkoutId')
    if not chk and isinstance(sub_data, dict):
        chk = sub_data.get('checkoutSession') or sub_data.get('checkoutId')
    chk = extract_asaas_id(chk)

    if chk:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_checkout_id=chk)
        if matching.count() == 1:
            return matching.first()

    # 2. Busca por gateway_external_reference direto
    ext = external_ref
    if not ext and isinstance(payment_data, dict):
        ext = payment_data.get('externalReference')
    if not ext and isinstance(sub_data, dict):
        ext = sub_data.get('externalReference')

    if ext:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=ext)
        if matching.count() == 1:
            return matching.first()

    # 3. Correlação remota via Asaas API (quando há subscription_id nova)
    if subscription_id:
        try:
            from core.services.payments.asaas.client import AsaasClient
            client = AsaasClient()
            # Verifica se algum pagamento desta nova subscription no Asaas aponta para nosso gateway_checkout_id
            payments_found = client.get_payments_by_subscription(subscription_id)
            for p in payments_found:
                p_chk = extract_asaas_id(p.get('checkoutSession'))
                p_ext = p.get('externalReference')
                if p_chk:
                    m_chk = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_checkout_id=p_chk)
                    if m_chk.count() == 1:
                        return m_chk.first()
                if p_ext:
                    m_ext = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=p_ext)
                    if m_ext.count() == 1:
                        return m_ext.first()

            # Verifica se a própria subscription no Asaas aponta para checkoutSession
            sub_remote = client.get_subscription(subscription_id)
            if sub_remote:
                s_chk = extract_asaas_id(sub_remote.get('checkoutSession'))
                s_ext = sub_remote.get('externalReference')
                if s_chk:
                    m_chk = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_checkout_id=s_chk)
                    if m_chk.count() == 1:
                        return m_chk.first()
                if s_ext:
                    m_ext = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=s_ext)
                    if m_ext.count() == 1:
                        return m_ext.first()
        except Exception as e:
            logger.warning("Falha na consulta remota ao Asaas para resolver reativacao de sub=%s: %s", subscription_id, str(e))

    # 4. Fallback seguro por customer_id para assinaturas elegíveis a reativação
    if customer_id:
        candidates = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_customer_id=customer_id)
        if candidates.count() == 1:
            candidate = candidates.first()
            if candidate.status in ('DESATIVADO', 'CANCELADO') or candidate.cancel_at_period_end or not candidate.auto_renew:
                if candidate.gateway_checkout_id or candidate.gateway_external_reference:
                    return candidate

    return None


def reconcile_and_update_billing_record(payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    payment_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else payload
    payment_id = extract_asaas_id(payment_data.get('id') or payload.get('paymentId'), expected_prefix='pay_')
    external_ref = payment_data.get('externalReference') or payload.get('externalReference')
    subscription_id = extract_asaas_id(payment_data.get('subscription') or payload.get('subscription'), expected_prefix='sub_')
    customer_id = extract_asaas_id(payment_data.get('customer') or payload.get('customer'), expected_prefix='cus_')
    chk_session = extract_asaas_id(payment_data.get('checkoutSession'))

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

    sub = None
    if not record:
        if subscription_id:
            matching_subs = BandSubscription.objects.filter(
                gateway_provider='ASAAS',
                gateway_subscription_id=subscription_id
            )
            if matching_subs.count() == 1:
                sub = matching_subs.first()
            elif matching_subs.count() > 1:
                return False, f'AMBIGUIDADE: Multiplas assinaturas locais para gateway_subscription_id={subscription_id}'

        if not sub:
            # Tentar resolver via resolver central de reativação
            sub = resolve_reactivation_subscription(
                checkout_id=chk_session,
                external_ref=external_ref,
                subscription_id=subscription_id,
                payment_id=payment_id,
                customer_id=customer_id,
                payment_data=payment_data
            )
            if sub and subscription_id and sub.gateway_subscription_id != subscription_id:
                if sub.status in ('DESATIVADO', 'CANCELADO') or sub.cancel_at_period_end or not sub.auto_renew:
                    sub.gateway_subscription_id = subscription_id
                    sub.save(update_fields=['gateway_subscription_id', 'updated_at'])

        if sub:
            today = timezone.localdate()
            month_names = {
                1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril',
                5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
            }
            due_date_val = payment_data.get('dueDate') or sub.next_due_date or today
            if isinstance(due_date_val, str):
                import datetime
                due_date_val = datetime.date.fromisoformat(due_date_val)
            ref_period = f'{month_names[due_date_val.month]}/{due_date_val.year}'
            raw_value = payment_data.get('value') or payment_data.get('netValue') or sub.contracted_value
            amount_val = Decimal(str(raw_value))

            record = BillingRecord.objects.filter(
                subscription=sub,
                due_date=due_date_val
            ).first()

            if not record:
                record = BillingRecord.objects.create(
                    subscription=sub,
                    band=sub.band,
                    reference_period=ref_period,
                    plan_name=sub.plan_name,
                    billing_cycle=sub.billing_cycle,
                    amount=amount_val,
                    due_date=due_date_val,
                    status='PENDENTE',
                    payment_method='CARTAO',
                    gateway_provider='ASAAS',
                    gateway_payment_id=payment_id,
                    gateway_invoice_url=payment_data.get('invoiceUrl'),
                    gateway_external_reference=external_ref,
                    gateway_event_status=event_type
                )
            else:
                record.gateway_payment_id = payment_id
                record.gateway_invoice_url = payment_data.get('invoiceUrl') or record.gateway_invoice_url
                record.gateway_external_reference = external_ref or record.gateway_external_reference
                record.gateway_event_status = event_type
        else:
            return False, f'AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID: payment_id={payment_id}, ref={external_ref}, sub={subscription_id}'

    if not record:
        return False, f'AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID: payment_id={payment_id}, ref={external_ref}, sub={subscription_id}'

    record.gateway_event_status = event_type
    if payment_data.get('invoiceUrl'):
        record.gateway_invoice_url = payment_data.get('invoiceUrl')

    if event_type in ('PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED'):
        was_already_paid = (record.status == 'PAGO')
        record.status = 'PAGO'
        if not record.paid_date:
            raw_paid = payment_data.get('paymentDate') or payment_data.get('clientPaymentDate') or payment_data.get('confirmedDate') or timezone.localdate()
            if isinstance(raw_paid, str):
                import datetime
                raw_paid = datetime.date.fromisoformat(raw_paid)
            record.paid_date = raw_paid
        
        # Atualiza a BandSubscription associada aplicando a regra de regularização vs tolerância
        # apenas se a cobrança ainda não estava quitada
        if not was_already_paid and record.subscription:
            record.subscription.apply_payment_success(paid_date=record.paid_date)
    elif event_type in ('PAYMENT_OVERDUE',):
        if record.status != 'PAGO':
            record.status = 'PENDENTE'
    elif event_type in ('PAYMENT_REFUNDED',):
        record.status = 'ESTORNADO' if hasattr(record, 'status') else record.status
    elif event_type in ('PAYMENT_DELETED', 'PAYMENT_CANCELLED', 'PAYMENT_CANCELED'):
        if record.status != 'PAGO':
            record.status = 'CANCELADO'

    record.save()
    return True, 'BILLING_CONCILIADO'


def handle_subscription_event(payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    sub_data = payload.get('subscription') if isinstance(payload.get('subscription'), dict) else payload
    sub_id = extract_asaas_id(sub_data.get('id') or payload.get('subscriptionId') or payload.get('subscription'), expected_prefix='sub_')
    customer_id = extract_asaas_id(sub_data.get('customer') or payload.get('customer'), expected_prefix='cus_')
    external_ref = sub_data.get('externalReference') or payload.get('externalReference')
    checkout_id = extract_asaas_id(sub_data.get('checkoutSession') or sub_data.get('checkoutId'))

    if not sub_id:
        return False, 'SUBSCRIPTION_EVENT_SEM_ID'

    # 1. Busca direta por gateway_subscription_id
    sub = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_subscription_id=sub_id).first()
    if sub:
        if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
            sub.status = 'CANCELADO'
            sub.save(update_fields=['status', 'updated_at'])
        return True, f'SUBSCRIPTION_{event_type}_SINCRONIZADA'

    # 2. Resolver central de reativação com correlação forte
    react_sub = resolve_reactivation_subscription(
        checkout_id=checkout_id,
        external_ref=external_ref,
        subscription_id=sub_id,
        customer_id=customer_id,
        sub_data=sub_data
    )
    if react_sub:
        # Segurança: apenas assinaturas inativas/em cancelamento permitem substituição de ID
        if react_sub.status in ('DESATIVADO', 'CANCELADO') or react_sub.cancel_at_period_end or not react_sub.auto_renew:
            react_sub.gateway_subscription_id = sub_id
            if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
                react_sub.status = 'CANCELADO'
            react_sub.save(update_fields=['gateway_subscription_id', 'status', 'updated_at'])
            return True, 'SUBSCRIPTION_REATIVACAO_VINCULADA'
        else:
            return False, f'SEGURANCA: Assinatura {react_sub.id} ativa nao permite substituicao arbitraria de gateway_subscription_id'

    # 3. Fallback por external_reference
    if external_ref:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_external_reference=external_ref)
        if matching.count() == 1:
            sub = matching.first()
            sub.gateway_subscription_id = sub_id
            if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
                sub.status = 'CANCELADO'
            sub.save(update_fields=['gateway_subscription_id', 'status', 'updated_at'])
            return True, 'SUBSCRIPTION_VINCULADA_POR_EXTERNAL_REFERENCE'
        elif matching.count() > 1:
            return False, f'AMBIGUIDADE: Multiplas BandSubscriptions com externalReference={external_ref}'

    # 4. Fallback por customer_id único
    if customer_id:
        matching = BandSubscription.objects.filter(gateway_provider='ASAAS', gateway_customer_id=customer_id)
        if matching.count() == 1:
            sub = matching.first()
            if not sub.gateway_subscription_id or sub.gateway_subscription_id == sub_id:
                sub.gateway_subscription_id = sub_id
                if event_type in ('SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED'):
                    sub.status = 'CANCELADO'
                sub.save(update_fields=['gateway_subscription_id', 'status', 'updated_at'])
                return True, 'SUBSCRIPTION_VINCULADA_POR_CUSTOMER_UNICO'
            else:
                return False, f'AMBIGUIDADE: Assinatura do customer={customer_id} ja possui outro gateway_subscription_id={sub.gateway_subscription_id}'
        elif matching.count() > 1:
            return False, f'AMBIGUIDADE: Multiplas BandSubscriptions para o customer={customer_id}'

    return False, f'BandSubscription nao encontrada de forma inequivoca para sub_id={sub_id}'


def handle_checkout_event(payload: Dict[str, Any], event_type: str, event_id: str = None) -> Tuple[bool, str]:
    checkout_data = payload.get('checkout') if isinstance(payload.get('checkout'), dict) else payload
    checkout_id = extract_asaas_id(checkout_data.get('id') or payload.get('checkoutId'))
    external_ref = checkout_data.get('externalReference') or payload.get('externalReference')
    customer_id = extract_asaas_id(checkout_data.get('customer') or payload.get('customer'), expected_prefix='cus_')
    subscription_id = extract_asaas_id(checkout_data.get('subscription') or payload.get('subscription'), expected_prefix='sub_')

    order = None
    if checkout_id:
        order = SignupOrder.objects.filter(gateway_checkout_id=checkout_id).first()
    if not order and external_ref:
        order = SignupOrder.objects.filter(external_reference=external_ref).first()

    if order:
        if event_type == 'CHECKOUT_CREATED':
            if order.status == 'PENDENTE':
                return True, 'CHECKOUT_CREATED_PROCESSADO'
            return True, f'CHECKOUT_CREATED_IGNORADO_STATUS_{order.status}'

        elif event_type == 'CHECKOUT_CANCELED':
            if order.status != 'PAGO':
                order.status = 'CANCELADO'
                order.save(update_fields=['status', 'updated_at'])
                return True, 'CHECKOUT_CANCELED_PROCESSADO'
            return True, 'CHECKOUT_CANCELED_IGNORADO_JA_PAGO'

        elif event_type == 'CHECKOUT_EXPIRED':
            if order.status != 'PAGO':
                order.status = 'EXPIRADO'
                order.save(update_fields=['status', 'updated_at'])
                return True, 'CHECKOUT_EXPIRED_PROCESSADO'
            return True, 'CHECKOUT_EXPIRED_IGNORADO_JA_PAGO'

        elif event_type in ('CHECKOUT_PAID', 'PAYMENT_CHECKOUT_PAID'):
            success, msg, _ = process_checkout_paid_event(payload, gateway_event_id=event_id)
            return success, msg

    # Se não houver SignupOrder, verifica se é uma reativação de BandSubscription
    react_sub = resolve_reactivation_subscription(
        checkout_id=checkout_id,
        external_ref=external_ref,
        subscription_id=subscription_id,
        customer_id=customer_id
    )
    if react_sub:
        if subscription_id and react_sub.gateway_subscription_id != subscription_id:
            if react_sub.status in ('DESATIVADO', 'CANCELADO') or react_sub.cancel_at_period_end or not react_sub.auto_renew:
                react_sub.gateway_subscription_id = subscription_id
                react_sub.save(update_fields=['gateway_subscription_id', 'updated_at'])

        if event_type == 'CHECKOUT_CREATED':
            return True, 'CHECKOUT_CREATED_REATIVACAO_PROCESSADO'
        elif event_type in ('CHECKOUT_PAID', 'PAYMENT_CHECKOUT_PAID'):
            return True, 'CHECKOUT_PAID_REATIVACAO_PROCESSADO'
        elif event_type == 'CHECKOUT_CANCELED':
            return True, 'CHECKOUT_CANCELED_REATIVACAO_PROCESSADO'
        elif event_type == 'CHECKOUT_EXPIRED':
            return True, 'CHECKOUT_EXPIRED_REATIVACAO_PROCESSADO'

    if event_type == 'CHECKOUT_CREATED':
        return True, 'CHECKOUT_CREATED_SIGNUPORDER_NAO_ENCONTRADO'
    elif event_type == 'CHECKOUT_CANCELED':
        return True, 'CHECKOUT_CANCELED_SIGNUPORDER_NAO_ENCONTRADO'
    elif event_type == 'CHECKOUT_EXPIRED':
        return True, 'CHECKOUT_EXPIRED_SIGNUPORDER_NAO_ENCONTRADO'
    elif event_type in ('CHECKOUT_PAID', 'PAYMENT_CHECKOUT_PAID'):
        return False, f'SignupOrder e BandSubscription nao encontrados para ref={external_ref} / checkout={checkout_id}'

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
        webhook_event.save(update_fields=['processed', 'processed_at', 'error_message'])
        return success, msg

    except Exception as e:
        logger.exception('Erro ao processar evento %s (%s): %s', event_id, event_type, str(e))
        webhook_event.processed = False
        webhook_event.error_message = str(e)
        webhook_event.save(update_fields=['processed', 'error_message'])
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
