import logging
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from django.db import transaction
from django.utils import timezone
from core.models import Band, BandSubscription, BillingRecord, SignupOrder, PaymentWebhookEvent
from core.services.payments.base import generate_unique_band_slug, calculate_next_billing_date
from core.services.payments.activation import create_band_activation_token

logger = logging.getLogger(__name__)


def process_checkout_paid_event(payload: Dict[str, Any], gateway_event_id: str = None) -> Tuple[bool, str, Optional[Band]]:
    """
    Processa o evento canônico CHECKOUT_PAID para provisionamento inicial da contratação.
    Implementa idempotência de Nível 2 via SignupOrder.external_reference / gateway_checkout_id.
    NÃO cria User ainda (usuário cria senha via token de ativação).
    """
    checkout_data = payload.get('checkout') or payload
    external_reference = checkout_data.get('externalReference') or payload.get('externalReference')
    checkout_id = checkout_data.get('id') or payload.get('checkoutId') or payload.get('id')
    customer_id = checkout_data.get('customer') or payload.get('customer')
    subscription_id = checkout_data.get('subscription') or payload.get('subscription')

    # 1. Localizar SignupOrder correspondente
    order = None
    if external_reference:
        order = SignupOrder.objects.filter(external_reference=external_reference).first()
    if not order and checkout_id:
        order = SignupOrder.objects.filter(gateway_checkout_id=checkout_id).first()

    if not order:
        return False, f"SignupOrder nao encontrado para ref={external_reference} / checkout={checkout_id}", None

    with transaction.atomic():
        # Lock da ordem de contratação
        order = SignupOrder.objects.select_for_update().get(pk=order.pk)

        # Idempotência Nível 2: Se a ordem já foi provisionada com Band, não recria
        if order.status == 'PAGO' and order.band is not None:
            logger.info("SignupOrder %s ja foi provisionada anteriormente. Ignorando reprovisionamento.", order.external_reference)
            return True, "JA_PROVISIONADO", order.band

        # 2. Criar a Band
        band_slug = generate_unique_band_slug(order.band_name)
        band = Band.objects.create(
            name=order.band_name,
            slug=band_slug,
            plan_type=order.plan_type,
            is_active=True,
            subscription_plan=order.billing_cycle,
            subscription_status='CONFIRMADO',
            subscription_due_date=calculate_next_billing_date(timezone.localdate(), order.billing_cycle, 1)
        )

        # 3. Criar BandSubscription oficial
        cycle_name = 'Anual' if order.billing_cycle == 'ANUAL' else 'Mensal'
        plan_display = f"{'Avançado' if order.plan_type == 'AVANCADO' else 'Básico'} {cycle_name}"
        next_due = calculate_next_billing_date(timezone.localdate(), order.billing_cycle, 1)

        sub = BandSubscription.objects.create(
            band=band,
            plan_name=plan_display,
            billing_cycle=order.billing_cycle,
            contracted_value=order.amount,
            start_date=timezone.localdate(),
            next_due_date=next_due,
            auto_renew=True,
            status='ATIVO',
            payment_method_preference='CARTAO',
            financial_responsible_name=order.responsible_name,
            billing_phone=order.phone,
            billing_email=order.email,
            gateway_provider='ASAAS',
            gateway_customer_id=customer_id or order.gateway_customer_id,
            gateway_subscription_id=subscription_id or order.gateway_subscription_id,
            gateway_checkout_id=checkout_id or order.gateway_checkout_id,
            gateway_external_reference=order.external_reference
        )

        # 4. Criar BillingRecord inicial liquidado (PAGO)
        today = timezone.localdate()
        month_names = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
            5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
            9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        ref_period = f"{month_names[today.month]}/{today.year}"
        payment_id = payload.get('payment', {}).get('id') if isinstance(payload.get('payment'), dict) else payload.get('paymentId')

        BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period=ref_period,
            plan_name=plan_display,
            billing_cycle=order.billing_cycle,
            amount=order.amount,
            due_date=today,
            paid_date=today,
            status='PAGO',
            payment_method='CARTAO',
            notes="Primeiro pagamento aprovado via Checkout Asaas",
            gateway_provider='ASAAS',
            gateway_payment_id=payment_id,
            gateway_external_reference=order.external_reference,
            gateway_event_status='CHECKOUT_PAID'
        )

        # 5. Criar BandActivationToken seguro (48 horas)
        activation, raw_token = create_band_activation_token(
            band=band,
            email=order.email,
            responsible_name=order.responsible_name,
            signup_order=order,
            valid_hours=48
        )

        # 6. Atualizar SignupOrder
        order.band = band
        order.status = 'PAGO'
        order.provisioned_at = timezone.now()
        if customer_id and not order.gateway_customer_id:
            order.gateway_customer_id = customer_id
        if subscription_id and not order.gateway_subscription_id:
            order.gateway_subscription_id = subscription_id
        order.save()

        logger.info("Band '%s' (slug=%s) provisionada com sucesso atraves do pedido %s", band.name, band.slug, order.external_reference)
        return True, "PROVISIONADO", band
