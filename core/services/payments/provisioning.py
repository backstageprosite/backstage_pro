import logging
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from django.db import transaction
from django.utils import timezone
from core.models import Band, BandSubscription, BillingRecord, SignupOrder, PaymentWebhookEvent, AnnualPlanPurchase, GatewayPaymentMethod
from core.services.payments.base import generate_unique_band_slug, calculate_next_billing_date, extract_asaas_id
from core.services.payments.activation import create_band_activation_token

logger = logging.getLogger(__name__)


def process_checkout_paid_event(payload: Dict[str, Any], gateway_event_id: str = None) -> Tuple[bool, str, Optional[Band]]:
    """
    Processa o evento canônico CHECKOUT_PAID para provisionamento inicial da contratação.
    Implementa idempotência de Nível 2 via SignupOrder.external_reference / gateway_checkout_id.
    NÃO cria User ainda (usuário cria senha via token de ativação).
    """
    checkout_data = payload.get('checkout') if isinstance(payload.get('checkout'), dict) else payload
    external_reference = checkout_data.get('externalReference') or payload.get('externalReference')
    checkout_id = extract_asaas_id(checkout_data.get('id') or payload.get('checkoutId') or payload.get('id'))
    customer_id = extract_asaas_id(checkout_data.get('customer') or payload.get('customer'), expected_prefix='cus_')
    subscription_id = extract_asaas_id(checkout_data.get('subscription') or payload.get('subscription'), expected_prefix='sub_')

    # 1. Localizar SignupOrder correspondente
    order = None
    if external_reference:
        order = SignupOrder.objects.filter(external_reference=external_reference).first()
    if not order and checkout_id:
        order = SignupOrder.objects.filter(gateway_checkout_id=checkout_id).first()

    if not order:
        return False, f"SignupOrder nao encontrado para ref={external_reference} / checkout={checkout_id}", None

    effective_checkout_id = checkout_id or extract_asaas_id(order.gateway_checkout_id)
    payment_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else {}
    payment_id = extract_asaas_id(payment_data.get('id') or payload.get('paymentId'), expected_prefix='pay_')

    # Consulta de seguranca via API Asaas para obter payment.id e subscription.id exatos
    if (not payment_id or not subscription_id) and effective_checkout_id:
        try:
            from core.services.payments.asaas.client import AsaasClient
            client = AsaasClient()
            payments_found = client.get_payments_by_checkout(effective_checkout_id)
            if len(payments_found) == 1:
                p_item = payments_found[0]
                payment_id = payment_id or extract_asaas_id(p_item.get('id'), expected_prefix='pay_')
                subscription_id = subscription_id or extract_asaas_id(p_item.get('subscription'), expected_prefix='sub_')
                if not payment_data:
                    payment_data = p_item
            elif len(payments_found) > 1:
                logger.warning("Multiplas cobrancas encontradas para checkout=%s", effective_checkout_id)
        except Exception as e:
            logger.warning("Erro ao consultar pagamentos da sessao %s no Asaas: %s", effective_checkout_id, str(e))

    with transaction.atomic():
        # Lock da ordem de contratação
        order = SignupOrder.objects.select_for_update().get(pk=order.pk)

        # Idempotência Nível 2: Se a ordem já foi provisionada com Band, não recria
        if order.status == 'PAGO' and order.band is not None:
            logger.info("SignupOrder %s ja foi provisionada anteriormente. Ignorando reprovisionamento.", order.external_reference)
            return True, "JA_PROVISIONADO", order.band

        # 2. Criar a Band
        # Extrair data de efetivação financeira (paymentDate / clientPaymentDate / confirmedDate) com fallback para hoje
        raw_paid = (
            payment_data.get('paymentDate')
            or payment_data.get('clientPaymentDate')
            or payment_data.get('confirmedDate')
            or timezone.localdate()
        )
        if isinstance(raw_paid, str):
            import datetime
            raw_paid = datetime.date.fromisoformat(raw_paid)

        financial_start_date = raw_paid
        next_due = calculate_next_billing_date(financial_start_date, order.billing_cycle, 1)

        band_slug = generate_unique_band_slug(order.band_name)
        band = Band.objects.create(
            name=order.band_name,
            slug=band_slug,
            plan_type=order.plan_type,
            is_active=True,
            subscription_plan=order.billing_cycle,
            subscription_status='CONFIRMADO',
            subscription_due_date=next_due
        )

        # 3. Criar BandSubscription oficial
        # O nome do plano deve ser estritamente 'Básico' ou 'Avançado' (o ciclo e exibido separadamente)
        plan_display = 'Avançado' if order.plan_type == 'AVANCADO' else 'Básico'
        is_annual = (order.billing_cycle == 'ANUAL')

        # Para ANUAL (INSTALLMENT): nao ha recorrencia automatica no gateway (auto_renew=False)
        # Para MENSAL (RECURRENT): ha renovacao automatica (auto_renew=True)
        auto_renew_val = False if is_annual else True

        sub = BandSubscription.objects.create(
            band=band,
            plan_name=plan_display,
            billing_cycle=order.billing_cycle,
            contracted_value=order.amount,
            start_date=financial_start_date,
            next_due_date=next_due,
            auto_renew=auto_renew_val,
            status='ATIVO',
            payment_method_preference='CARTAO',
            financial_responsible_name=order.responsible_name,
            billing_phone=order.phone,
            billing_email=order.email,
            gateway_provider='ASAAS',
            gateway_customer_id=customer_id or order.gateway_customer_id,
            gateway_subscription_id=subscription_id or order.gateway_subscription_id,
            gateway_checkout_id=effective_checkout_id,
            gateway_external_reference=order.external_reference
        )

        # 4. Criar BillingRecord inicial liquidado (PAGO)
        today = timezone.localdate()
        month_names = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
            5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
            9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        if is_annual:
            ref_period = f"Vigência {financial_start_date.strftime('%d/%m/%Y')} a {next_due.strftime('%d/%m/%Y')}"
            record_notes = "Compra Anual parcelável aprovada via Checkout Asaas (vigência de 12 meses)"
        else:
            ref_period = f"{month_names[financial_start_date.month]}/{financial_start_date.year}"
            record_notes = "Primeiro pagamento aprovado via Checkout Asaas"

        # Valor da cobranca inicial: se houver parcelamento (ex: anual em ate 5x),
        # a cobranca do primeiro pagamento (payment_data['value']) contem o valor da 1a parcela.
        # Caso nao haja 'value' em payment_data, utiliza order.amount (valor integral).
        # Isso impede duplicacao de valor contabil/financeiro quando as parcelas subsequentes chegarem.
        initial_record_amount = order.amount
        if payment_data and payment_data.get('value') is not None:
            try:
                initial_record_amount = Decimal(str(payment_data.get('value')))
            except Exception:
                initial_record_amount = order.amount

        # 4.1. Criar/Vincular AnnualPlanPurchase para contratos anuais (Modelagem ASAAS-11)
        annual_purchase = None
        if is_annual:
            # Obter detalhes do installment via API se disponivel
            installment_id = None
            installment_count_val = 1
            net_amount_val = None
            raw_inst = payment_data.get('installment') if isinstance(payment_data, dict) else None
            installment_id = extract_asaas_id(raw_inst)

            try:
                from core.services.payments.asaas.client import AsaasClient
                client = AsaasClient()
                if not installment_id and payment_id:
                    p_info = client.get_payment(payment_id)
                    if p_info:
                        installment_id = extract_asaas_id(p_info.get('installment'))

                if installment_id:
                    inst_info = client.get_installment(installment_id)
                    if inst_info:
                        installment_count_val = inst_info.get('installmentCount') or 1
                        if inst_info.get('netValue') is not None:
                            net_amount_val = Decimal(str(inst_info.get('netValue')))
            except Exception as e:
                logger.warning("Falha ao enriquecer dados do parcelamento %s no Asaas: %s", installment_id, str(e))

            annual_purchase, _ = AnnualPlanPurchase.objects.get_or_create(
                gateway_provider='ASAAS',
                gateway_installment_id=installment_id or f"inst_pending_{order.external_reference}",
                defaults={
                    'band_subscription': sub,
                    'signup_order': order,
                    'purchase_type': AnnualPlanPurchase.PurchaseType.INITIAL,
                    'gateway_external_reference': order.external_reference,
                    'installment_count': installment_count_val,
                    'gross_amount': order.amount,
                    'net_amount': net_amount_val,
                    'coverage_start': financial_start_date,
                    'coverage_end': next_due,
                    'approved_at': timezone.now(),
                    'status': AnnualPlanPurchase.Status.CONFIRMED,
                }
            )

            # 4.2. Captura segura e criptografada do token de pagamento no Gateway (sem salvar no webhook)
            if payment_id:
                try:
                    from core.services.payments.asaas.client import AsaasClient
                    client = AsaasClient()
                    p_full = client.get_payment(payment_id)
                    if p_full:
                        cc_info = p_full.get('creditCard') if isinstance(p_full.get('creditCard'), dict) else {}
                        raw_token = p_full.get('creditCardToken') or cc_info.get('creditCardToken')
                        if raw_token:
                            pm, created_pm = GatewayPaymentMethod.objects.get_or_create(
                                subscription=sub,
                                gateway_provider='ASAAS',
                                is_active=True,
                                defaults={
                                    'gateway_customer_id': customer_id or order.gateway_customer_id or '',
                                    'card_brand': cc_info.get('creditCardBrand'),
                                    'card_last4': str(cc_info.get('creditCardNumber') or '')[-4:] if cc_info.get('creditCardNumber') else None,
                                    'encrypted_token': ''
                                }
                            )
                            pm.set_token(raw_token)
                            pm.gateway_customer_id = customer_id or order.gateway_customer_id or pm.gateway_customer_id
                            pm.card_brand = cc_info.get('creditCardBrand') or pm.card_brand
                            if cc_info.get('creditCardNumber'):
                                pm.card_last4 = str(cc_info.get('creditCardNumber'))[-4:]
                            pm.save()
                            del raw_token  # Descarta imediatamente da memoria
                except Exception as e:
                    logger.warning("Falha ao capturar e criptografar token para subscription %s: %s", sub.id, str(e))

        BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period=ref_period,
            plan_name=plan_display,
            billing_cycle=order.billing_cycle,
            amount=initial_record_amount,
            due_date=financial_start_date,
            paid_date=financial_start_date,
            status='PAGO',
            payment_method='CARTAO',
            notes=record_notes,
            gateway_provider='ASAAS',
            gateway_payment_id=payment_id,
            gateway_external_reference=order.external_reference,
            gateway_event_status='CHECKOUT_PAID',
            annual_purchase=annual_purchase,
            installment_number=1 if is_annual else None
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
