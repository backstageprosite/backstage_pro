import json
import logging
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from django.db import transaction
from django.utils import timezone
from core.models import PaymentWebhookEvent, BillingRecord, BandSubscription, SignupOrder, AnnualPlanPurchase, GatewayPaymentMethod
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


def synchronize_asaas_subscription_anchor(
    sub: BandSubscription,
    paid_date: Any,
    triggering_payment_id: Optional[str] = None,
    client: Optional[Any] = None
) -> Tuple[bool, str]:
    """
    Sincroniza a nova data-base (billing anchor) com a API do Asaas apos regularizacao
    de assinatura que estava suspensa.

    IMPORTANTE: Esta funcao deve ser chamada ANTES de apply_payment_success().
    Se qualquer PUT remoto falhar, retorna (False, msg) sem alterar o estado local,
    permitindo reprocessamento idempotente do webhook.

    Idempotencia:
    - Os targets sao sempre calculados a partir de paid_date + offset cronologico.
    - Se uma cobranca ja estiver na data correta, o PUT e omitido (sem deslocamento duplo).
    - O payment que disparou a regularizacao (triggering_payment_id) e excluido
      do realinhamento de futuros.

    Passos:
    1. Lista cobranças abertas (PENDING/OVERDUE) da assinatura no Asaas.
    2. Exclui: deletadas, quitadas, estornadas, canceladas, e a cobrança triggerante.
    3. Ordena cronologicamente por dueDate.
    4. Sequencia novas datas a partir de paid_date + offset (sempre deterministico).
    5. Atualiza dueDates discordantes via PUT /v3/payments/{id}.
    6. Atualiza subscription.nextDueDate via PUT /v3/subscriptions/{id}.
    """
    if not sub or sub.gateway_provider != 'ASAAS' or not sub.gateway_subscription_id:
        return True, 'GATEWAY_NAO_ASAAS'

    from core.services.payments.asaas.client import AsaasClient
    from core.services.payments.base import calculate_next_billing_date
    import datetime

    if isinstance(paid_date, str):
        paid_date = datetime.date.fromisoformat(paid_date)
    elif isinstance(paid_date, datetime.datetime):
        paid_date = paid_date.date()

    if not client:
        client = AsaasClient()

    cycle = sub.billing_cycle or 'MENSAL'
    remote_payments = client.get_payments_by_subscription(sub.gateway_subscription_id)

    # Filtrar cobranças futuras abertas:
    # - nao deletadas
    # - status PENDING ou OVERDUE
    # - nao e a cobranca que disparou a regularizacao
    open_future_payments = []
    for p in remote_payments:
        p_status = p.get('status')
        p_deleted = p.get('deleted', False)
        p_id = p.get('id')
        if p_deleted:
            continue
        if p_status not in ('PENDING', 'OVERDUE'):
            continue
        if triggering_payment_id and p_id == triggering_payment_id:
            # Cobranca que acabou de ser confirmada - nao realinhar
            continue
        open_future_payments.append(p)

    # Ordena cronologicamente por dueDate (deterministico)
    open_future_payments.sort(key=lambda x: x.get('dueDate') or '')

    # Sequenciar novas datas a partir de paid_date (targets sempre deterministicos)
    current_offset = 1
    for p in open_future_payments:
        p_id = p.get('id')
        # Target sempre calculado de paid_date + offset - nunca do dueDate atual
        new_target_due = calculate_next_billing_date(paid_date, cycle, periods_offset=current_offset)
        new_due_str = new_target_due.isoformat()
        if p.get('dueDate') != new_due_str:
            ok_p, resp_p = client.update_payment(p_id, {'dueDate': new_due_str})
            if not ok_p:
                logger.error(
                    "Falha ao atualizar dueDate da cobranca %s no Asaas para %s: %s",
                    p_id, new_due_str, resp_p
                )
                return False, f'ERRO_PUT_PAYMENT_{p_id}'
        current_offset += 1

    # Proxima data da assinatura para quando nao houver cobranca gerada
    next_sub_due = calculate_next_billing_date(paid_date, cycle, periods_offset=current_offset)
    next_sub_due_str = next_sub_due.isoformat()

    ok_sub, resp_sub = client.update_subscription(sub.gateway_subscription_id, {'nextDueDate': next_sub_due_str})
    if not ok_sub:
        logger.error(
            "Falha ao atualizar nextDueDate da assinatura %s no Asaas para %s: %s",
            sub.gateway_subscription_id, next_sub_due_str, resp_sub
        )
        return False, 'ERRO_PUT_SUBSCRIPTION_NEXT_DUE_DATE'

    logger.info(
        "Assinatura %s reancorada com sucesso no Asaas a partir de %s. NextDueDate: %s (%d pagamentos realinhados).",
        sub.gateway_subscription_id, paid_date, next_sub_due_str, len(open_future_payments)
    )
    return True, 'ASAAS_ANCHOR_SINCRONIZADO'


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
                # Localizar vinculo com AnnualPlanPurchase se for plano anual
                inst_id_ref = extract_asaas_id(payment_data.get('installment'))
                inst_num_ref = payment_data.get('installmentNumber')
                annual_purchase_ref = None
                if sub.billing_cycle == 'ANUAL':
                    if inst_id_ref:
                        annual_purchase_ref = AnnualPlanPurchase.objects.filter(
                            band_subscription=sub,
                            gateway_installment_id=inst_id_ref
                        ).first()
                    if not annual_purchase_ref:
                        annual_purchase_ref = AnnualPlanPurchase.objects.filter(
                            band_subscription=sub
                        ).order_by('-coverage_start').first()

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
                    gateway_event_status=event_type,
                    annual_purchase=annual_purchase_ref,
                    installment_number=inst_num_ref
                )
            else:
                record.gateway_payment_id = payment_id
                record.gateway_invoice_url = payment_data.get('invoiceUrl') or record.gateway_invoice_url
                record.gateway_external_reference = external_ref or record.gateway_external_reference
                record.gateway_event_status = event_type
                if sub.billing_cycle == 'ANUAL':
                    if payment_data.get('installmentNumber') and not record.installment_number:
                        record.installment_number = payment_data.get('installmentNumber')
                    if not record.annual_purchase:
                        inst_id_ref = extract_asaas_id(payment_data.get('installment'))
                        if inst_id_ref:
                            record.annual_purchase = AnnualPlanPurchase.objects.filter(
                                band_subscription=sub,
                                gateway_installment_id=inst_id_ref
                            ).first()
                        if not record.annual_purchase:
                            record.annual_purchase = AnnualPlanPurchase.objects.filter(
                                band_subscription=sub
                            ).order_by('-coverage_start').first()
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

        # Atualiza a BandSubscription associada aplicando a regra de regularizacao vs tolerancia
        # apenas se a cobranca ainda nao estava quitada
        if not was_already_paid and record.subscription:
            sub = record.subscription
            was_suspended = sub.is_financially_suspended or (sub.status == 'DESATIVADO')

            # REGRA DE CONSISTENCIA TRANSACIONAL:
            # Se estava suspensa, a sincronizacao remota do billing anchor no Asaas
            # DEVE ser concluida com SUCESSO antes de aplicar o ciclo local.
            # Falha remota => retorna False => webhook permanece nao-processado => reprocessavel.
            if was_suspended and sub.gateway_provider == 'ASAAS' and sub.gateway_subscription_id:
                sync_ok, sync_msg = synchronize_asaas_subscription_anchor(
                    sub,
                    paid_date=record.paid_date,
                    triggering_payment_id=payment_id
                )
                if not sync_ok:
                    logger.error(
                        "Sincronizacao do billing anchor falhou para sub %s: %s. "
                        "Acesso NAO sera liberado. Webhook permanece reprocessavel.",
                        sub.gateway_subscription_id, sync_msg
                    )
                    # Nao salva o record nem avanca o ciclo local.
                    # process_webhook_event marcara processed=False para retry.
                    return False, f'ANCHOR_SYNC_FALHOU_{sync_msg}'

            # Sincronizacao remota concluida (ou desnecessaria por tolerancia):
            # Para planos ANUAIS (parcelamentos desacoplados gerenciados por AnnualPlanPurchase),
            # parcelas subsequentes apenas liquidam seu respectivo BillingRecord e NUNCA avancam next_due_date,
            # pois a vigencia de 12 meses ja e concedida atomicamente pelo motor de renovacao / provisionamento.
            # Somente chama apply_payment_success se NAO for ANUAL ou se for regularizacao pos-suspensao.
            is_annual_installment = (sub.billing_cycle == 'ANUAL' or record.annual_purchase_id is not None)
            if is_annual_installment and sub.status == 'ATIVO' and not was_suspended:
                logger.info("Parcela de plano anual recebida para sub %s (record=%s). Billing liquidado sem estender vigencia.", sub.id, record.id)
            else:
                sub.apply_payment_success(paid_date=record.paid_date)

    elif event_type in ('PAYMENT_OVERDUE',):
        if record.status != 'PAGO':
            record.status = 'PENDENTE'
            if record.subscription:
                try:
                    from core.services.email_service import enqueue_email, resolve_subscription_recipient
                    sub = record.subscription
                    recip_email, recip_name = resolve_subscription_recipient(sub)
                    if recip_email:
                        due_fmt = record.due_date.strftime('%d/%m/%Y') if record.due_date else ''
                        import datetime
                        grace_until_date = record.due_date + datetime.timedelta(days=4) if record.due_date else None
                        grace_fmt = grace_until_date.strftime('%d/%m/%Y') if grace_until_date else ''
                        enqueue_email(
                            email_type='PAYMENT_OVERDUE',
                            recipient_email=recip_email,
                            subject=f"Aviso de Vencimento — Backstage Pro ({sub.band.name if sub.band else 'Assinatura'})",
                            idempotency_key=f"overdue-payment-{payment_id}",
                            template_name='emails/payment_overdue',
                            context_data={
                                'user_name': recip_name,
                                'band_name': sub.band.name if sub.band else 'Sua Banda',
                                'plan_name': sub.plan_name,
                                'amount': f"{record.amount:.2f}".replace('.', ','),
                                'due_date': due_fmt,
                                'grace_until': grace_fmt,
                                'invoice_url': record.gateway_invoice_url or '',
                            },
                            related_object_type='BillingRecord',
                            related_object_id=str(record.id)
                        )
                except Exception as e:
                    logger.warning("Falha ao enfileirar e-mail PAYMENT_OVERDUE para payment %s: %s", payment_id, str(e))

    elif event_type in ('PAYMENT_CREDIT_CARD_CAPTURE_REFUSED',):
        if record.status != 'PAGO':
            record.status = 'PENDENTE'
            if record.subscription:
                try:
                    from core.services.email_service import enqueue_email, resolve_subscription_recipient
                    sub = record.subscription
                    recip_email, recip_name = resolve_subscription_recipient(sub)
                    if recip_email:
                        refusal_reason = payment_data.get('creditCard', {}).get('creditCardBrand') or payment_data.get('refusalReason') or 'Transação não autorizada pela emissora do cartão.'
                        enqueue_email(
                            email_type='CREDIT_CARD_CAPTURE_REFUSED',
                            recipient_email=recip_email,
                            subject=f"Falha na Captura do Cartão — Backstage Pro ({sub.band.name if sub.band else 'Assinatura'})",
                            idempotency_key=f"cc-refused-webhook-{payment_id}",
                            template_name='emails/credit_card_capture_refused',
                            context_data={
                                'user_name': recip_name,
                                'band_name': sub.band.name if sub.band else 'Sua Banda',
                                'plan_name': sub.plan_name,
                                'amount': f"{record.amount:.2f}",
                                'reason': refusal_reason,
                                'invoice_url': record.gateway_invoice_url or '',
                            },
                            related_object_type='BillingRecord',
                            related_object_id=str(record.id)
                        )
                except Exception as e:
                    logger.warning("Falha ao enfileirar e-mail CREDIT_CARD_CAPTURE_REFUSED para payment %s: %s", payment_id, str(e))

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

    from core.services.payments.security import sanitize_webhook_payload
    safe_payload = sanitize_webhook_payload(payload)

    webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
        gateway_event_id=str(event_id),
        defaults={
            'provider': 'ASAAS',
            'event_type': str(event_type),
            'payload': safe_payload,
            'processed': False
        }
    )

    if not created and webhook_event.processed:
        logger.info('Webhook %s ja foi processado com sucesso. Idempotencia nivel 1 garantida.', event_id)
        return True, 'EVENTO_JA_PROCESSADO'

    return process_webhook_event(webhook_event)
