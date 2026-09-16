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
    # e enriquecer payment_data (inclusive em caso de parcelamento em que o webhook nao traz 'value' ou 'installment')
    if effective_checkout_id:
        try:
            from core.services.payments.asaas.client import AsaasClient
            client = AsaasClient()
            need_payments_lookup = (not payment_id or not subscription_id) or (
                isinstance(payment_data, dict) and not payment_data.get('installment') and not payment_data.get('installmentNumber')
            )
            if need_payments_lookup:
                payments_found = client.get_payments_by_checkout(effective_checkout_id)
                if len(payments_found) >= 1:
                    # Ordenar por installmentNumber ou data de criacao para pegar a primeira parcela
                    p_item = payments_found[0]
                    for p in payments_found:
                        if p.get('installmentNumber') == 1:
                            p_item = p
                            break
                    payment_id = payment_id or extract_asaas_id(p_item.get('id'), expected_prefix='pay_')
                    subscription_id = subscription_id or extract_asaas_id(p_item.get('subscription'), expected_prefix='sub_')
                    if not payment_data or payment_data.get('value') is None or not payment_data.get('installment'):
                        payment_data = {**p_item, **payment_data}
                elif len(payments_found) > 1:
                    logger.warning("Multiplas cobrancas encontradas para checkout=%s", effective_checkout_id)
        except Exception as e:
            logger.warning("Erro ao consultar pagamentos da sessao %s no Asaas: %s", effective_checkout_id, str(e))

    with transaction.atomic():
        # Lock da ordem de contratação
        order = SignupOrder.objects.select_for_update().get(pk=order.pk)

        # Idempotência Nível 2: Se a ordem já foi provisionada/paga com Band, não recria nem duplica faturamento
        if order.status == 'PAGO' and order.band is not None:
            logger.info("SignupOrder %s ja foi provisionada anteriormente. Ignorando reprovisionamento.", order.external_reference)
            return True, "JA_PROVISIONADO", order.band

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

        is_existing_band = (order.band is not None)

        if is_existing_band:
            # 2a. Banda Já Cadastrada (BP-PEND-60)
            # Reutiliza a banda existente, garantindo ativação e sincronização do plano
            band = order.band
            band.plan_type = order.plan_type
            band.is_active = True
            band.subscription_plan = order.billing_cycle
            band.subscription_status = 'CONFIRMADO'
            band.subscription_due_date = next_due
            band.save(update_fields=['plan_type', 'is_active', 'subscription_plan', 'subscription_status', 'subscription_due_date'])
            logger.info("Cobrança aprovada para banda existente '%s' (id=%s). Atualizando assinatura.", band.name, band.id)
        else:
            # 2b. Nova Banda (Provisionamento inicial público)
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

        # 3. Criar ou Atualizar BandSubscription oficial
        plan_display = 'Avançado' if order.plan_type == 'AVANCADO' else 'Básico'
        is_annual = (order.billing_cycle == 'ANUAL')

        # Detecta forma de pagamento do webhook/cobrança (PIX vs CARTAO)
        billing_type_raw = (payment_data.get('billingType') or '').upper()
        is_pix = (billing_type_raw == 'PIX') or (order.external_reference and order.external_reference.endswith('-pix'))
        pref_method = 'PIX' if is_pix else 'CARTAO'

        # Para ANUAL: auto_renew=False (renovação controlada ou recontratação)
        # Para MENSAL PIX: auto_renew=False (cobrança avulsa ciclo a ciclo via check_subscription_due_dates)
        # Para MENSAL CARTÃO: auto_renew=True (recorrência automática com token ou gateway subscription)
        if is_annual or is_pix:
            auto_renew_val = False
        else:
            auto_renew_val = True

        sub = None
        if is_existing_band:
            sub = BandSubscription.objects.filter(band=band, is_deleted=False).order_by('-created_at').first()

        if sub:
            sub.plan_name = plan_display
            sub.billing_cycle = order.billing_cycle
            sub.contracted_value = order.amount
            sub.start_date = financial_start_date
            sub.next_due_date = next_due
            sub.auto_renew = auto_renew_val
            sub.status = 'ATIVO'
            sub.payment_method_preference = pref_method
            if order.responsible_name:
                sub.financial_responsible_name = order.responsible_name
            if order.phone:
                sub.billing_phone = order.phone
            if order.email:
                sub.billing_email = order.email
            sub.gateway_provider = 'ASAAS'
            if customer_id or order.gateway_customer_id:
                sub.gateway_customer_id = customer_id or order.gateway_customer_id
            if subscription_id or order.gateway_subscription_id:
                sub.gateway_subscription_id = subscription_id or order.gateway_subscription_id
            if effective_checkout_id:
                sub.gateway_checkout_id = effective_checkout_id
            sub.gateway_external_reference = order.external_reference
            sub.is_financially_suspended = False
            sub.save()
        else:
            sub = BandSubscription.objects.create(
                band=band,
                plan_name=plan_display,
                billing_cycle=order.billing_cycle,
                contracted_value=order.amount,
                start_date=financial_start_date,
                next_due_date=next_due,
                auto_renew=auto_renew_val,
                status='ATIVO',
                payment_method_preference=pref_method,
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

        # 4.1. Criar/Vincular AnnualPlanPurchase para contratos anuais (Modelagem ASAAS-11)
        annual_purchase = None
        is_installment_plan = False
        initial_installment_number = None

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
                        if p_info.get('installmentNumber'):
                            initial_installment_number = p_info.get('installmentNumber')

                if installment_id:
                    inst_info = client.get_installment(installment_id)
                    if inst_info:
                        installment_count_val = inst_info.get('installmentCount') or 1
                        if inst_info.get('netValue') is not None:
                            net_amount_val = Decimal(str(inst_info.get('netValue')))
            except Exception as e:
                logger.warning("Falha ao enriquecer dados do parcelamento %s no Asaas: %s", installment_id, str(e))

            if payment_data.get('installmentNumber'):
                initial_installment_number = payment_data.get('installmentNumber')

            if installment_id or installment_count_val > 1 or (initial_installment_number is not None and initial_installment_number >= 1):
                is_installment_plan = True
                initial_installment_number = initial_installment_number or 1

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

        # Valor da cobranca inicial: se houver parcelamento (ex: anual em ate 5x),
        # a cobranca do primeiro pagamento (payment_data['value']) contem o valor da 1a parcela.
        # Se for parcelamento mas nao houver value em payment_data, calcula order.amount / installment_count.
        # Caso nao seja parcelado (ex: anual a vista ou PIX), utiliza order.amount (valor integral).
        # Isso impede duplicacao de valor contabil/financeiro quando as parcelas subsequentes chegarem.
        initial_record_amount = order.amount
        if is_installment_plan:
            if payment_data and payment_data.get('value') is not None:
                try:
                    initial_record_amount = Decimal(str(payment_data.get('value')))
                except Exception:
                    initial_record_amount = (order.amount / Decimal(str(installment_count_val))).quantize(Decimal('0.01'))
            elif installment_count_val > 1:
                initial_record_amount = (order.amount / Decimal(str(installment_count_val))).quantize(Decimal('0.01'))
        elif payment_data and payment_data.get('value') is not None:
            try:
                initial_record_amount = Decimal(str(payment_data.get('value')))
            except Exception:
                initial_record_amount = order.amount

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
            payment_method=pref_method,
            notes=record_notes,
            gateway_provider='ASAAS',
            gateway_payment_id=payment_id,
            gateway_external_reference=order.external_reference,
            gateway_event_status='CHECKOUT_PAID',
            annual_purchase=annual_purchase,
            installment_number=initial_installment_number if is_installment_plan else None
        )

        # 5. Criar BandActivationToken e notificação (Apenas para novas bandas)
        # Para bandas já existentes (BP-PEND-60), os usuários já possuem acesso e senha configurada.
        if not is_existing_band:
            activation, raw_token = create_band_activation_token(
                band=band,
                email=order.email,
                responsible_name=order.responsible_name,
                signup_order=order,
                valid_hours=48
            )

            # 5.1 Enfileirar EmailDelivery ACCOUNT_ACTIVATION (desacoplado de SMTP)
            # Formatação detalhada da forma de pagamento e parcelamento (BP-PEND-40)
            payment_info = None
            if pref_method == 'PIX':
                payment_info = 'PIX — à vista'
            elif not is_annual:
                payment_info = 'Cartão de crédito — cobrança mensal'
            else:
                # Plano Anual no Cartão: 1x ou parcelado em até 5x
                if is_installment_plan and installment_count_val > 1:
                    inst_amount_str = f"{initial_record_amount:.2f}".replace('.', ',')
                    payment_info = f"Cartão de crédito — {installment_count_val}x de R$ {inst_amount_str}"
                else:
                    full_amount_str = f"{order.amount:.2f}".replace('.', ',')
                    payment_info = f"Cartão de crédito — 1x de R$ {full_amount_str}"

            try:
                from core.services.email_service import enqueue_email
                enqueue_email(
                    email_type='ACCOUNT_ACTIVATION',
                    recipient_email=order.email,
                    subject='Sua conta no Backstage Pro está pronta!',
                    idempotency_key=f"activation-signup-{order.id}",
                    template_name='emails/account_activation',
                    context_data={
                        'responsible_name': order.responsible_name or band.name,
                        'band_name': band.name,
                        'plan_name': plan_display,
                        'billing_cycle': 'Anual' if is_annual else 'Mensal',
                        'amount': f"{order.amount:.2f}".replace('.', ','),
                        'payment_info': payment_info,
                    },
                    related_object_type='BandActivationToken',
                    related_object_id=str(activation.pk)
                )
                del raw_token  # Limpa token em texto plano da memória
            except Exception as e:
                logger.warning("Falha ao enfileirar e-mail de ativação para pedido %s: %s", order.external_reference, str(e))

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

