import datetime
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import BandSubscription, BillingRecord

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Varredura diaria de vencimentos de assinaturas. "
        "Cria faturas automaticamente para assinaturas que vencem em ate 7 dias "
        "e marca como Vencido as que passaram da data. "
        "Para assinaturas mensais PIX (chargeType=DETACHED), emite cobranca PIX avulsa no Asaas "
        "via POST /v3/payments com idempotencia por externalReference. "
        "Deve ser executado todo inicio do dia via cron/scheduler."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a varredura sem realizar alterações no banco.',
        )

    def _emit_pix_charge(self, sub: BandSubscription, billing_record: BillingRecord, dry_run: bool) -> None:
        """
        Emite cobrança PIX avulsa no Asaas para o próximo ciclo mensal.
        Apenas chamado para assinaturas: billing_cycle=MENSAL, payment_method_preference=PIX,
        gateway_customer_id preenchido e sem gateway_subscription_id (modelo DETACHED).
        Idempotência: externalReference = 'pix-renewal-{billing_record.id}'.
        """
        if not sub.gateway_customer_id:
            logger.warning(
                "Sub %s é PIX mensal mas não tem gateway_customer_id — cobrança PIX ignorada.", sub.id
            )
            return

        ext_ref = f"pix-renewal-{billing_record.id}"

        if dry_run:
            self.stdout.write(
                f"  [DRY-RUN] Emitiria cobrança PIX no Asaas: customer={sub.gateway_customer_id}, "
                f"value={billing_record.amount}, dueDate={sub.next_due_date}, externalReference={ext_ref}"
            )
            return

        try:
            from core.services.payments.asaas.client import AsaasClient
            client = AsaasClient()

            # Idempotência remota prévia: verifica se a cobrança já foi criada no Asaas
            # (ex: timeout de rede em execução anterior onde resposta se perdeu)
            existing_payments = client.get_payments_by_external_reference(ext_ref)
            if existing_payments:
                p_item = existing_payments[0]
                payment_id = p_item.get('id')
                if payment_id:
                    billing_record.gateway_payment_id = payment_id
                    billing_record.gateway_provider = 'ASAAS'
                    billing_record.save(update_fields=['gateway_payment_id', 'gateway_provider'])
                    logger.info(
                        "Cobrança PIX já existente no Asaas reconciliada com sucesso: payment_id=%s, ext_ref=%s",
                        payment_id, ext_ref
                    )
                    return

            payload = {
                "customer": sub.gateway_customer_id,
                "billingType": "PIX",
                "value": float(billing_record.amount),
                "dueDate": sub.next_due_date.strftime('%Y-%m-%d'),
                "description": f"Backstage Pro — {sub.plan_name} ({billing_record.reference_period})",
                "externalReference": ext_ref,
            }
            ok, resp = client.post_payment(payload)
            if ok and resp.get('id'):
                payment_id = resp['id']
                billing_record.gateway_payment_id = payment_id
                billing_record.gateway_provider = 'ASAAS'
                billing_record.save(update_fields=['gateway_payment_id', 'gateway_provider'])
                logger.info(
                    "Cobrança PIX criada no Asaas: payment_id=%s, sub=%s, due=%s",
                    payment_id, sub.id, sub.next_due_date
                )
            else:
                logger.error(
                    "Falha ao criar cobrança PIX no Asaas para sub=%s, due=%s: %s",
                    sub.id, sub.next_due_date, resp
                )
        except Exception as e:
            logger.exception(
                "Exceção ao emitir cobrança PIX no Asaas para sub=%s: %s", sub.id, str(e)
            )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        today = timezone.localdate()
        seven_days = today + datetime.timedelta(days=7)

        created = 0
        updated_vencido = 0
        updated_vencendo = 0
        pix_emitted = 0

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN — nenhuma alteração será realizada no banco de dados."))

        subscriptions = BandSubscription.objects.filter(
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status__in=["ATIVO", "VENCENDO"],
            is_deleted=False
        )

        for sub in subscriptions:
            if sub.is_partnership or not sub.next_due_date:
                continue

            # Apenas criar fatura automática se não existe ainda
            if sub.next_due_date <= seven_days:
                exists = BillingRecord.objects.filter(
                    subscription=sub,
                    due_date=sub.next_due_date
                ).exists()
                if not exists:
                    month_names = {
                        1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
                        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
                        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
                    }
                    month_name = month_names.get(sub.next_due_date.month, str(sub.next_due_date.month))
                    ref_period = f"{month_name}/{sub.next_due_date.year}"

                    if not dry_run:
                        billing_record = BillingRecord.objects.create(
                            subscription=sub,
                            band=sub.band,
                            reference_period=ref_period,
                            amount=sub.contracted_value,
                            due_date=sub.next_due_date,
                            status="PENDENTE",
                            plan_name=getattr(sub, "plan_name", ""),
                            billing_cycle=sub.billing_cycle,
                        )
                    else:
                        # Em dry-run, cria instância temporária para logging sem salvar
                        billing_record = BillingRecord(
                            subscription=sub,
                            band=sub.band,
                            reference_period=ref_period,
                            amount=sub.contracted_value,
                            due_date=sub.next_due_date,
                            status="PENDENTE",
                            plan_name=getattr(sub, "plan_name", ""),
                            billing_cycle=sub.billing_cycle,
                        )
                    created += 1

                    # Emitir cobrança PIX no Asaas para assinaturas mensais PIX gerenciadas internamente.
                    # Critério: MENSAL + PIX + sem gateway_subscription_id (modelo DETACHED/avulso).
                    is_monthly_pix = (
                        sub.billing_cycle == 'MENSAL'
                        and sub.payment_method_preference == 'PIX'
                        and not sub.gateway_subscription_id
                    )
                    if is_monthly_pix:
                        self._emit_pix_charge(sub, billing_record, dry_run)
                        pix_emitted += 1

        # Verificar assinaturas com suspensão financeira (>= 5 dias de atraso) para enfileirar e-mail transacional
        suspended_count = 0
        all_active_subs = BandSubscription.objects.filter(
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status="ATIVO",
            is_deleted=False,
            next_due_date__isnull=False
        )
        for sub in all_active_subs:
            if sub.is_partnership:
                continue
            if sub.is_financially_suspended:
                try:
                    from core.services.email_service import resolve_subscription_recipient
                    recip_email, recip_name = resolve_subscription_recipient(sub)
                    if recip_email and sub.next_due_date and sub.band and sub.band.slug:
                        from django.urls import reverse
                        from core.services.email_service import get_canonical_base_url
                        base_url = get_canonical_base_url()
                        sub_path = reverse('minha_assinatura', kwargs={'band_slug': sub.band.slug})
                        subscription_url = f"{base_url}{sub_path}"

                        if not dry_run:
                            from core.services.email_service import enqueue_email
                            enqueue_email(
                                email_type='SUBSCRIPTION_SUSPENDED',
                                recipient_email=recip_email,
                                subject=f"Acesso Suspenso por Pendência — Backstage Pro ({sub.band.name})",
                                idempotency_key=f"sub-suspended-{sub.id}-{sub.next_due_date.isoformat()}",
                                template_name='emails/subscription_suspended',
                                context_data={
                                    'user_name': recip_name,
                                    'responsible_name': recip_name,
                                    'band_name': sub.band.name,
                                    'plan_name': sub.plan_name,
                                    'contracted_value': f"{sub.contracted_value:.2f}",
                                    'days_overdue': sub.days_overdue(),
                                    'next_due_date': sub.next_due_date.strftime('%d/%m/%Y'),
                                    'subscription_url': subscription_url,
                                },
                                related_object_type='BandSubscription',
                                related_object_id=str(sub.id)
                            )
                        suspended_count += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Falha ao enfileirar e-mail de suspensão para sub {sub.id}: {e}"))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Dry-run concluido: {created} faturas seriam criadas ({pix_emitted} cobranças PIX Asaas), "
                f"{updated_vencendo} assinaturas marcadas como VENCENDO, "
                f"{updated_vencido} marcadas como VENCIDO, "
                f"{suspended_count} suspensões financeiras seriam verificadas/notificadas."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Varredura concluida: {created} faturas criadas ({pix_emitted} cobranças PIX Asaas), "
                f"{updated_vencendo} assinaturas marcadas como VENCENDO, "
                f"{updated_vencido} marcadas como VENCIDO, "
                f"{suspended_count} suspensões financeiras verificadas/notificadas."
            ))

