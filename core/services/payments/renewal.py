import logging
import datetime
from decimal import Decimal
from typing import Optional, Tuple, List, Dict, Any

from django.db import transaction
from django.utils import timezone
from django.conf import settings

from core.models import (
    BandSubscription,
    AnnualPlanPurchase,
    GatewayPaymentMethod,
    BillingRecord,
    SystemSettings,
    AnnualRenewalNotice
)
from core.services.payments.base import calculate_next_billing_date
from core.services.payments.asaas.client import AsaasClient

logger = logging.getLogger(__name__)


class AnnualRenewalService:
    """
    Motor seguro de renovação automática para planos anuais no Backstage Pro.
    
    Regras de Negócio e Hardening Financeiro (ETAPA 3.1):
    1. Elegibilidade:
       - sub.billing_cycle == 'ANUAL'
       - sub.status == 'ATIVO'
       - sub.auto_renew is True
       - sub.cancel_at_period_end is False
       - sub.is_deleted is False
       - Janela de tentativa: D0 (next_due_date) até D+4 (tolerância).
       - A partir de D+5 (atraso >= 5 dias): tentativas automáticas cessam. Assinatura fica suspensa financeiramente.
       
    2. Preço Vigente e Trava de Aviso (D-30):
       - O preço pago não muda durante a vigência em curso.
       - Na renovação, o preço base é o preço vigente canônico de SystemSettings.get_canonical_plan_price().
       - Se houve AnnualRenewalNotice enviado (SENT) para este ciclo:
         * O preço notificado congela o valor máximo cobrado: min(notified_price, public_price_d0).
       - Se o preço público subiu (public > contracted) mas NÃO houve aviso SENT registrado:
         * Política segura de fallback: cobra o contracted_value anterior e registra fallback (não cobra aumento surpresa).
       - BandSubscription.contracted_value SOMENTE é atualizado após a aprovação de TODAS as parcelas.
       - Quantidade de parcelas é rigorosamente preservada da última compra confirmada (ex: 5x).
       
    3. Idempotência e Recuperação de Falhas (Crash Recovery):
       - AnnualPlanPurchase criada/recuperada com status PENDING e external_reference determinístico.
       - Se já houver gateway_installment_id gravado, NÃO cria novo parcelamento no gateway; reaproveita o existente.
       
    4. Hardening de Execução Financeira (payWithCreditCard):
       - Consulta cobranças do parcelamento ANTES de qualquer cobrança.
       - Se 5/5 já estiverem CONFIRMED/RECEIVED: pula payWithCreditCard e finaliza a renovação idempotentemente.
       - Se a parcela 1 estiver CONFIRMED e as demais PENDING: NÃO chama payWithCreditCard novamente (retorna ESTADO_FINANCEIRO_INCONCLUSIVO).
       - Somente chama payWithCreditCard se a parcela 1 estiver em estado aberto compatível (PENDING ou OVERDUE).
       - Se ocorrer timeout/erro de rede: reconsulta payments no gateway antes de falhar.
       
    5. Confirmação e Extensão da Vigência:
       - Vigência somente avança (+1 ano em next_due_date) se TODAS as parcelas estiverem CONFIRMED/RECEIVED.
       - sub.start_date permanece inalterado.
       - Atualiza sub.contracted_value para o gross_amount efetivo da nova contratação confirmada.
    """

    def __init__(self, client: Optional[AsaasClient] = None):
        self.client = client or AsaasClient()

    @staticmethod
    def get_deterministic_external_reference(sub: BandSubscription, target_date: Optional[datetime.date] = None) -> str:
        ref_date = target_date or sub.next_due_date or timezone.localdate()
        date_str = ref_date.strftime('%Y%m%d')
        return f"bp-annual-renewal-{sub.id}-{date_str}"

    @staticmethod
    def is_eligible_for_renewal(sub: BandSubscription, target_date: Optional[datetime.date] = None) -> Tuple[bool, str]:
        if not sub or sub.is_deleted:
            return False, "SUBSCRIPTION_INEXISTENTE_OU_DELETADA"

        if sub.billing_cycle != 'ANUAL':
            return False, "CICLO_NAO_ANUAL"

        if sub.status != 'ATIVO':
            return False, f"STATUS_INVALIDO_{sub.status}"

        if not sub.auto_renew:
            return False, "AUTO_RENEW_DESATIVADO"

        if sub.cancel_at_period_end:
            return False, "CANCELAMENTO_AGENDADO"

        if not sub.next_due_date:
            return False, "NEXT_DUE_DATE_AUSENTE"

        eval_date = target_date or timezone.localdate()
        days_diff = (eval_date - sub.next_due_date).days

        if days_diff < 0:
            return False, f"DATA_FUTURA_AINDA_NAO_VENCEU (vence em {sub.next_due_date})"

        if days_diff >= 5:
            return False, f"JANELA_EXPIRADA_SUSPENSAO_FINANCEIRA (atraso de {days_diff} dias >= 5)"

        return True, "ELEGIVEL"

    @classmethod
    def calculate_renewal_price(
        cls,
        sub: BandSubscription,
        target_date: Optional[datetime.date] = None
    ) -> Tuple[Decimal, str]:
        """
        Calcula o valor da renovação respeitando o preço vigente, congelamento por aviso D-30,
        e política de fallback caso um aumento não tenha sido comunicado previamente.
        Retorna (preço_final, motivo_politica).
        """
        eval_date = target_date or sub.next_due_date or timezone.localdate()
        public_price = SystemSettings.get_canonical_plan_price(sub.plan_name, 'ANUAL')
        contracted_val = sub.contracted_value or Decimal('199.90')

        # Buscar se existe aviso formal enviado para a data de renovação deste ciclo
        notice = AnnualRenewalNotice.objects.filter(
            band_subscription=sub,
            renewal_date=sub.next_due_date,
            status=AnnualRenewalNotice.Status.SENT
        ).first()

        if notice and notice.notified_renewal_price:
            notified_price = notice.notified_renewal_price
            # Se o preço diminuiu após o aviso, beneficia o cliente com o menor valor
            # Nunca cobra acima do valor notificado
            final_price = min(notified_price, public_price)
            reason = f"NOTICE_FROZEN_PRICE (notified={notified_price}, public={public_price}, final={final_price})"
            return final_price, reason

        # Se NÃO houve aviso prévio enviado:
        if public_price > contracted_val:
            # Aumento sem aviso prévio de 30 dias: não cobrar aumento surpresa. Fallback para contracted_value.
            logger.warning(
                "Sub %s: Preço público (%s) é maior que contratado (%s) mas aviso de 30 dias não foi enviado. "
                "Aplicando política de segurança PRICE_CHANGE_NOTICE_MISSING (mantendo %s).",
                sub.id, public_price, contracted_val, contracted_val
            )
            return contracted_val, "PRICE_CHANGE_NOTICE_MISSING"

        # Se o preço for igual ou menor, aplica o preço vigente público
        return public_price, "PUBLIC_PRICE_APPLIED"

    def get_or_create_renewal_purchase(
        self,
        sub: BandSubscription,
        target_date: Optional[datetime.date] = None
    ) -> AnnualPlanPurchase:
        external_ref = self.get_deterministic_external_reference(sub, target_date)
        
        # Tenta buscar compra de renovação existente para esta referência
        existing = AnnualPlanPurchase.objects.filter(
            gateway_provider='ASAAS',
            gateway_external_reference=external_ref
        ).first()
        if existing:
            return existing

        # Determina quantidade de parcelas baseada no histórico da assinatura (preserva última escolha, ex: 5x)
        last_confirmed = AnnualPlanPurchase.objects.filter(
            band_subscription=sub,
            status=AnnualPlanPurchase.Status.CONFIRMED
        ).order_by('-coverage_start').first()

        inst_count = last_confirmed.installment_count if last_confirmed else 1
        gross_amt, price_reason = self.calculate_renewal_price(sub, target_date=target_date)
        cov_start = sub.next_due_date or timezone.localdate()
        cov_end = calculate_next_billing_date(cov_start, 'ANUAL', periods_offset=1)

        purchase, _ = AnnualPlanPurchase.objects.get_or_create(
            gateway_provider='ASAAS',
            gateway_external_reference=external_ref,
            defaults={
                'band_subscription': sub,
                'purchase_type': AnnualPlanPurchase.PurchaseType.RENEWAL,
                'gateway_installment_id': '',  # Será preenchido após criação no gateway
                'installment_count': inst_count,
                'gross_amount': gross_amt,
                'coverage_start': cov_start,
                'coverage_end': cov_end,
                'status': AnnualPlanPurchase.Status.PENDING,
            }
        )
        return purchase

    def process_subscription_renewal(
        self,
        sub: BandSubscription,
        target_date: Optional[datetime.date] = None
    ) -> Tuple[bool, str, Optional[AnnualPlanPurchase]]:
        """
        Executa o fluxo completo de renovação anual da assinatura especificada com hardening financeiro.
        """
        eval_date = target_date or timezone.localdate()
        eligible, reason = self.is_eligible_for_renewal(sub, target_date=eval_date)
        if not eligible:
            logger.info("Assinatura %s não elegível para renovação anual automática: %s", sub.id, reason)
            return False, reason, None

        # 1. Obter ou criar AnnualPlanPurchase idempotente
        annual_purchase = self.get_or_create_renewal_purchase(sub, target_date=eval_date)

        # Se já foi confirmada anteriormente, nada a fazer (idempotência total)
        if annual_purchase.status == AnnualPlanPurchase.Status.CONFIRMED:
            return True, "RENOVACAO_JA_CONFIRMADA", annual_purchase

        # 2. Obter método de pagamento ativo
        payment_method = GatewayPaymentMethod.objects.filter(
            subscription=sub,
            gateway_provider='ASAAS',
            is_active=True
        ).first()

        if not payment_method or not payment_method.encrypted_token:
            logger.error("Assinatura %s não possui método de pagamento ativo com token.", sub.id)
            return False, "PAYMENT_METHOD_MISSING", annual_purchase

        customer_id = payment_method.gateway_customer_id or sub.gateway_customer_id
        if not customer_id:
            logger.error("Assinatura %s não possui gateway_customer_id definido.", sub.id)
            return False, "CUSTOMER_ID_MISSING", annual_purchase

        # 3. Garantir existência do parcelamento no gateway (Idempotência / Crash Recovery)
        installment_id = annual_purchase.gateway_installment_id
        if not installment_id:
            # Criar novo parcelamento no Asaas sem cartão
            desc = f"Renovacao Anual - {sub.band.name[:20]}"
            inst_payload = {
                'customer': customer_id,
                'billingType': 'CREDIT_CARD',
                'installmentCount': annual_purchase.installment_count,
                'totalValue': float(annual_purchase.gross_amount),
                'dueDate': annual_purchase.coverage_start.isoformat(),
                'description': desc,
                'externalReference': annual_purchase.gateway_external_reference
            }
            success_inst, inst_resp = self.client.create_installment(inst_payload)
            if not success_inst or not inst_resp.get('id'):
                logger.error("Falha ao criar installment para sub %s no Asaas: %s", sub.id, inst_resp)
                return False, f"FALHA_CRIACAO_PARCELAMENTO: {inst_resp.get('error', 'desconhecido')}", annual_purchase

            installment_id = inst_resp.get('id')
            annual_purchase.gateway_installment_id = installment_id
            if inst_resp.get('netValue') is not None:
                annual_purchase.net_amount = Decimal(str(inst_resp.get('netValue')))
            annual_purchase.save(update_fields=['gateway_installment_id', 'net_amount', 'updated_at'])
            logger.info("Installment %s criado e salvo para AnnualPlanPurchase %s", installment_id, annual_purchase.id)

        # 4. Obter as parcelas geradas pelo installment
        payments = self.client.get_payments_by_installment(installment_id)
        if not payments:
            logger.error("Nenhuma parcela encontrada para o installment %s no Asaas.", installment_id)
            return False, "PARCELAS_NAO_ENCONTRADAS", annual_purchase

        # Ordenar por installmentNumber
        payments.sort(key=lambda x: x.get('installmentNumber', 0))
        first_payment = payments[0]
        first_payment_id = first_payment.get('id')
        first_status = first_payment.get('status')

        # HARDENING: Contagem de parcelas confirmadas previamente
        confirmed_count = sum(1 for p in payments if p.get('status') in ('CONFIRMED', 'RECEIVED'))

        # REGRA 23: Se todas as parcelas já estão CONFIRMED/RECEIVED, não chama payWithCreditCard
        if confirmed_count >= annual_purchase.installment_count:
            logger.info("Todas as %d parcelas do installment %s já estão confirmadas. Finalizando renovação.", confirmed_count, installment_id)
        # REGRA 24: Se a parcela 1 já estiver confirmada mas as restantes ainda pendentes, NÃO chama payWithCreditCard de novo
        elif first_status in ('CONFIRMED', 'RECEIVED'):
            logger.warning(
                "Primeira parcela %s está CONFIRMED mas parcelas restantes ainda pendentes (%d/%d). "
                "payWithCreditCard NÃO será repetido. Estado inconclusivo.",
                first_payment_id, confirmed_count, annual_purchase.installment_count
            )
            return False, "ESTADO_FINANCEIRO_INCONCLUSIVO", annual_purchase
        # REGRA 25: Somente chama payWithCreditCard se a primeira parcela estiver aberta (PENDING ou OVERDUE)
        elif first_status in ('PENDING', 'OVERDUE'):
            # Descriptografa token na memória estrita
            plain_token = payment_method.get_decrypted_token()
            try:
                success_pay, pay_resp = self.client.pay_with_credit_card(first_payment_id, plain_token)
            finally:
                del plain_token  # Remove imediatamente da memória

            if not success_pay:
                # REGRA 26: Em caso de erro ou timeout, reconsulta o gateway antes de concluir recusa
                recheck_payments = self.client.get_payments_by_installment(installment_id)
                recheck_confirmed = sum(1 for p in recheck_payments if p.get('status') in ('CONFIRMED', 'RECEIVED'))
                if recheck_confirmed >= annual_purchase.installment_count:
                    logger.info("Após timeout/falha na resposta, reconsulta confirmou 100%% das parcelas para installment %s.", installment_id)
                    payments = recheck_payments
                else:
                    err_msg = pay_resp.get('error') or pay_resp.get('errors') or "pagamento_recusado"
                    logger.warning("Falha ao pagar primeira parcela %s da renovação: %s", first_payment_id, err_msg)
                    try:
                        from core.services.email_service import enqueue_email, resolve_subscription_recipient
                        from core.models import EmailDelivery
                        recipient_email, recipient_name = resolve_subscription_recipient(sub)
                        if recipient_email:
                            idemp_key = f"cc-refused-renewal-{annual_purchase.id}-{timezone.localdate().isoformat()}"
                            enqueue_email(
                                email_type=EmailDelivery.EmailType.CREDIT_CARD_CAPTURE_REFUSED,
                                recipient_email=recipient_email,
                                subject="Não conseguimos processar o pagamento da sua assinatura - Backstage Pro",
                                idempotency_key=idemp_key,
                                template_name="emails/credit_card_capture_refused",
                                context_data={
                                    "user_name": recipient_name,
                                    "band_name": sub.band.name,
                                    "plan_name": sub.plan_name,
                                    "amount": str(annual_purchase.gross_amount),
                                    "due_date": annual_purchase.coverage_start.strftime("%d/%m/%Y"),
                                    "error_reason": str(err_msg),
                                    "manage_payment_url": "/assinatura/gerenciar/",
                                },
                                related_object_type="AnnualPlanPurchase",
                                related_object_id=str(annual_purchase.id)
                            )
                    except Exception as eq_err:
                        logger.error("Erro ao enfileirar email de cartão recusado para sub %s: %s", sub.id, eq_err)
                    return False, f"CARTAO_RECUSADO: {err_msg}", annual_purchase
        else:
            logger.error("Parcela 1 em estado incompatível com pagamento: %s", first_status)
            return False, f"ESTADO_PARCELA_INCOMPATIVEL_{first_status}", annual_purchase

        # 5. Verificar se TODAS as parcelas do parcelamento estão confirmadas
        updated_payments = self.client.get_payments_by_installment(installment_id)
        confirmed_count = sum(1 for p in updated_payments if p.get('status') in ('CONFIRMED', 'RECEIVED'))

        if confirmed_count < annual_purchase.installment_count:
            logger.warning(
                "Nem todas as parcelas do installment %s foram confirmadas (%d de %d). Vigência NÃO será estendida.",
                installment_id, confirmed_count, annual_purchase.installment_count
            )
            return False, f"PARCELAS_PENDENTES: {confirmed_count}/{annual_purchase.installment_count}", annual_purchase

        # 6. Efetivação atômica: Confirmação da compra, avanço de vigência, atualização de contracted_value e criação dos BillingRecords
        with transaction.atomic():
            sub_locked = BandSubscription.objects.select_for_update().get(id=sub.id)
            
            # Atualiza AnnualPlanPurchase
            annual_purchase.status = AnnualPlanPurchase.Status.CONFIRMED
            annual_purchase.approved_at = timezone.now()
            annual_purchase.save(update_fields=['status', 'approved_at', 'updated_at'])

            # Avança vigência: next_due_date + 1 ano
            # sub.start_date permanece inalterado (data de início original da assinatura)
            base_anchor = sub_locked.next_due_date or annual_purchase.coverage_start
            new_due_date = calculate_next_billing_date(base_anchor, 'ANUAL', periods_offset=1)
            sub_locked.next_due_date = new_due_date
            sub_locked.status = 'ATIVO'
            
            # Atualiza contracted_value para o novo preço vigente confirmado
            sub_locked.contracted_value = annual_purchase.gross_amount
            sub_locked.save(update_fields=['next_due_date', 'status', 'contracted_value', 'updated_at'])

            # Criar/atualizar BillingRecords para todas as parcelas
            for p in updated_payments:
                pid = p.get('id')
                inst_num = p.get('installmentNumber') or 1
                val = Decimal(str(p.get('value', annual_purchase.gross_amount / annual_purchase.installment_count)))
                due_val = p.get('dueDate') or annual_purchase.coverage_start.isoformat()
                p_status = 'PAGO' if p.get('status') in ('CONFIRMED', 'RECEIVED') else 'PENDENTE'
                paid_val = p.get('paymentDate') or p.get('confirmedDate') or eval_date

                BillingRecord.objects.update_or_create(
                    gateway_payment_id=pid,
                    defaults={
                        'subscription': sub_locked,
                        'band': sub_locked.band,
                        'reference_period': f"{eval_date.strftime('%B/%Y')}",
                        'plan_name': sub_locked.plan_name,
                        'billing_cycle': 'ANUAL',
                        'amount': val,
                        'due_date': due_val,
                        'paid_date': paid_val if p_status == 'PAGO' else None,
                        'status': p_status,
                        'payment_method': 'CARTAO',
                        'gateway_provider': 'ASAAS',
                        'gateway_external_reference': annual_purchase.gateway_external_reference,
                        'gateway_event_status': p.get('status'),
                        'annual_purchase': annual_purchase,
                        'installment_number': inst_num,
                    }
                )

        # 7. Enfileirar e-mail transacional de sucesso na renovação
        try:
            from core.services.email_service import enqueue_email, resolve_subscription_recipient
            from core.models import EmailDelivery
            recipient_email, recipient_name = resolve_subscription_recipient(sub_locked)
            if recipient_email:
                idemp_key = f"annual-renewal-success-{annual_purchase.id}"
                inst_text = f"{annual_purchase.installment_count}x de R$ {(annual_purchase.gross_amount / annual_purchase.installment_count):.2f}" if annual_purchase.installment_count > 1 else f"R$ {annual_purchase.gross_amount:.2f} à vista"
                enqueue_email(
                    email_type=EmailDelivery.EmailType.ANNUAL_RENEWAL_SUCCESS,
                    recipient_email=recipient_email,
                    subject=f"Renovação anual confirmada com sucesso! - Backstage Pro",
                    idempotency_key=idemp_key,
                    template_name="emails/annual_renewal_success",
                    context_data={
                        "user_name": recipient_name,
                        "band_name": sub_locked.band.name,
                        "plan_name": sub_locked.plan_name,
                        "total_amount": str(annual_purchase.gross_amount),
                        "installment_text": inst_text,
                        "new_coverage_start": annual_purchase.coverage_start.strftime("%d/%m/%Y"),
                        "new_coverage_end": annual_purchase.coverage_end.strftime("%d/%m/%Y"),
                        "next_due_date": sub_locked.next_due_date.strftime("%d/%m/%Y") if sub_locked.next_due_date else "",
                        "receipt_url": "/assinatura/historico/",
                    },
                    related_object_type="AnnualPlanPurchase",
                    related_object_id=str(annual_purchase.id)
                )
        except Exception as e:
            logger.error("Erro ao enfileirar email de sucesso de renovação para sub %s: %s", sub_locked.id, e)

        logger.info(
            "Renovação anual concluída com sucesso para subscription %s. Nova next_due_date: %s, Novo contracted_value: %s",
            sub.id, sub_locked.next_due_date, sub_locked.contracted_value
        )
        return True, "RENOVACAO_CONCLUIDA_COM_SUCESSO", annual_purchase

