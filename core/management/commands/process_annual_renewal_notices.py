import datetime
import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.db import connection

from core.models import BandSubscription, AnnualPlanPurchase, AnnualRenewalNotice, SystemSettings, ScheduledJobRun
from core.services.payments.base import get_business_date, acquire_job_advisory_lock, ANNUAL_NOTICE_JOB_LOCK_ID

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa e envia os avisos pré-renovação de 30 dias para contratos anuais (D-30 com janela de recuperação).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Avalia elegibilidade e exibe o que seria enviado sem persistir ou enviar e-mails.',
        )
        parser.add_argument(
            '--subscription-id',
            type=int,
            help='Processa especificamente a assinatura informada pelo ID.',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Data de referência no formato YYYY-MM-DD (padrão: hoje). Permitido apenas em sandbox/homologação.',
        )

    def get_recipient_email(self, sub: BandSubscription) -> str:
        """
        Obtém o e-mail canônico de cobrança/responsável da banda.
        Prioriza sub.billing_email -> e-mail do produtor da banda -> e-mail do primeiro usuário da banda.
        """
        if sub.billing_email and sub.billing_email.strip():
            return sub.billing_email.strip()

        produtor = sub.band.users.filter(role__in=['PRODUTOR', 'EMPRESARIO']).exclude(email='').first()
        if produtor and produtor.email and produtor.email.strip():
            return produtor.email.strip()

        any_user = sub.band.users.exclude(email='').first()
        if any_user and any_user.email and any_user.email.strip():
            return any_user.email.strip()

        return ''

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        sub_id = options.get('subscription_id')
        date_str = options.get('date')

        target_date = get_business_date()
        if date_str:
            import os
            # PROTEÇÃO HARD BLOCK: O parâmetro --date é estritamente proibido em produção.
            raw_asaas_env = getattr(settings, 'ASAAS_ENVIRONMENT', os.getenv('ASAAS_ENVIRONMENT', 'sandbox')).strip().lower()
            django_env = getattr(settings, 'DJANGO_ENV', os.getenv('DJANGO_ENV', 'development')).strip().lower()
            if raw_asaas_env == 'production' or django_env == 'production':
                self.stderr.write(self.style.ERROR(
                    "BLOQUEIO DE SEGURANÇA: O parâmetro --date é estritamente proibido em ambiente de PRODUÇÃO. Operação abortada."
                ))
                return

            try:
                target_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Data inválida: {date_str}. Use YYYY-MM-DD."))
                return

        # PROTEÇÃO DE ARQUITETURA: Em ambientes Railway/staging/production, nunca executar com SQLite.
        django_env = getattr(settings, 'DJANGO_ENV', 'development').strip().lower()
        if django_env in ('staging', 'homologacao', 'production') and not getattr(settings, 'IS_RUNNING_TESTS', False):
            if connection.vendor == 'sqlite':
                self.stderr.write(self.style.ERROR(
                    "BLOQUEIO DE ARQUITETURA: Cron jobs em homologação/produção Railway não podem utilizar SQLite. "
                    "Utilize o PostgreSQL canônico."
                ))
                return

        # LOCK DISTRIBUÍDO: Garante que apenas uma instância deste job execute simultaneamente
        with acquire_job_advisory_lock(ANNUAL_NOTICE_JOB_LOCK_ID) as lock_acquired:
            if not lock_acquired:
                self.stdout.write(self.style.WARNING("JOB_ALREADY_RUNNING: Outra instância de process_annual_renewal_notices está ativa. Execução ignorada com segurança."))
                if not dry_run:
                    ScheduledJobRun.objects.create(
                        job_name='process_annual_renewal_notices',
                        status=ScheduledJobRun.Status.SKIPPED_LOCKED,
                        error_summary="Execução ignorada: lock distribuído já adquirido por outra instância ativa."
                    )
                return

            job_run = None
            if not dry_run:
                job_run = ScheduledJobRun.objects.create(
                    job_name='process_annual_renewal_notices',
                    status=ScheduledJobRun.Status.RUNNING,
                    started_at=timezone.now()
                )

            self.stdout.write(f"Iniciando processamento de avisos pré-renovação de contratos anuais para a data de negócio: {target_date}")
            if dry_run:
                self.stdout.write(self.style.WARNING("MODO DRY-RUN ATIVADO: Nenhum e-mail será enfileirado e nenhum registro será persistido."))

            qs = BandSubscription.objects.filter(
                billing_cycle='ANUAL',
                status='ATIVO',
                auto_renew=True,
                cancel_at_period_end=False,
                is_deleted=False
            )
            if sub_id:
                qs = qs.filter(id=sub_id)

            processed_count = 0
            sent_count = 0
            failed_count = 0
            skipped_count = 0

            try:
                for sub in qs:
                    if not sub.next_due_date:
                        skipped_count += 1
                        continue

                    diff_days = (sub.next_due_date - target_date).days
                    # Janela de aviso: exatamente D-30 ou janela de recuperação (D-30 até D-25)
                    if diff_days < 25 or diff_days > 30:
                        skipped_count += 1
                        continue

                    # Verificar se já existe aviso para esta assinatura e data de renovação
                    existing_notice = AnnualRenewalNotice.objects.filter(
                        band_subscription=sub,
                        renewal_date=sub.next_due_date
                    ).first()

                    if existing_notice and existing_notice.status == AnnualRenewalNotice.Status.SENT:
                        self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Aviso já enviado anteriormente para {sub.next_due_date}. Pulando.")
                        skipped_count += 1
                        continue

                    processed_count += 1

                    last_confirmed = AnnualPlanPurchase.objects.filter(
                        band_subscription=sub,
                        status=AnnualPlanPurchase.Status.CONFIRMED
                    ).order_by('-coverage_start').first()
                    inst_count = last_confirmed.installment_count if last_confirmed else 1

                    current_price = sub.contracted_value or Decimal('199.90')
                    public_price = SystemSettings.get_canonical_plan_price(sub.plan_name, 'ANUAL')

                    # REGRA DE PROTEÇÃO DE PREÇO (RECOVERY WINDOW):
                    # Se o aviso está sendo emitido no D-30 exato: pode notificar public_price (mesmo com aumento).
                    # Se o aviso é de recuperação (< 30 dias de antecedência, ex: D-29 a D-25):
                    # O aumento NÃO pode ser autorizado para este ciclo! O preço notificado congela em min(public_price, current_price).
                    is_exact_d30 = (diff_days == 30)
                    if is_exact_d30:
                        notified_price = public_price
                        price_changed = (notified_price != current_price)
                        notice_type = AnnualRenewalNotice.NoticeType.PRICE_CHANGE if price_changed else AnnualRenewalNotice.NoticeType.STANDARD
                    else:
                        # Recovery após D-30: sem aumento surpresa
                        notified_price = min(public_price, current_price)
                        price_changed = False
                        notice_type = AnnualRenewalNotice.NoticeType.STANDARD
                        logger.info(
                            "Sub %s: Aviso de recuperação D-%d emitido. Aumento não autorizado por antecedência < 30 dias. Preço notificado: R$ %s.",
                            sub.id, diff_days, notified_price
                        )

                    recipient_email = self.get_recipient_email(sub)
                    has_recipient = bool(recipient_email)

                    self.stdout.write(
                        f"Sub {sub.id} ({sub.band.name}): renewal_date={sub.next_due_date} (D-{diff_days}), "
                        f"current_price=R$ {current_price}, public_price=R$ {public_price}, "
                        f"notified_price=R$ {notified_price}, installments={inst_count}x, "
                        f"recipient_found={'SIM' if has_recipient else 'NAO'}"
                    )

                    if dry_run:
                        sent_count += 1
                        continue

                    notice, created = AnnualRenewalNotice.objects.get_or_create(
                        band_subscription=sub,
                        renewal_date=sub.next_due_date,
                        defaults={
                            'plan_name': sub.plan_name,
                            'billing_cycle': 'ANUAL',
                            'current_contracted_value': current_price,
                            'notified_renewal_price': notified_price,
                            'installment_count': inst_count,
                            'notice_type': notice_type,
                            'email_recipient': recipient_email or None,
                            'scheduled_for': target_date,
                            'status': AnnualRenewalNotice.Status.PENDING,
                        }
                    )

                    if not has_recipient:
                        notice.status = AnnualRenewalNotice.Status.FAILED
                        notice.error_message = "DESTINATARIO_NAO_ENCONTRADO: Nenhum e-mail financeiro ou produtor cadastrado para a banda."
                        notice.save(update_fields=['status', 'error_message', 'updated_at'])
                        self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha: Destinatário não encontrado."))
                        failed_count += 1
                        continue

                    # Enfileirar EmailDelivery na fila transacional (totalmente desacoplado de SMTP)
                    try:
                        from core.services.email_service import enqueue_email
                        idemp_key = f"annual-notice-sub-{sub.id}-{sub.next_due_date.strftime('%Y%m%d')}"
                        ctx = {
                            'responsible_name': sub.financial_responsible_name or sub.band.name,
                            'band_name': sub.band.name,
                            'plan_name': sub.plan_name,
                            'renewal_date': sub.next_due_date.strftime('%d/%m/%Y'),
                            'current_price': f"{current_price:.2f}",
                            'notified_price': f"{notified_price:.2f}",
                            'installment_count': inst_count,
                            'price_changed': price_changed,
                        }
                        subject = "Atualização de valor da sua renovação — Backstage Pro" if price_changed else "Renovação do Backstage Pro em 30 dias"

                        delivery, d_created = enqueue_email(
                            email_type='ANNUAL_RENEWAL_NOTICE',
                            recipient_email=recipient_email,
                            subject=subject,
                            idempotency_key=idemp_key,
                            template_name='emails/annual_renewal_notice',
                            context_data=ctx,
                            related_object_type='AnnualRenewalNotice',
                            related_object_id=str(notice.id)
                        )
                        self.stdout.write(self.style.SUCCESS(f"  Sub {sub.id}: Aviso enfileirado na EmailDelivery (ID={delivery.id}) para {recipient_email}!"))
                        sent_count += 1
                    except Exception as e:
                        clean_err = str(e).replace('\n', ' ')[:200]
                        notice.status = AnnualRenewalNotice.Status.FAILED
                        notice.error_message = f"FALHA_ENFILEIRAMENTO_EMAIL: {clean_err}"
                        notice.save(update_fields=['status', 'error_message', 'updated_at'])
                        self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha ao enfileirar e-mail: {clean_err}"))
                        failed_count += 1

                if job_run:
                    job_run.finished_at = timezone.now()
                    job_run.processed_count = processed_count
                    job_run.success_count = sent_count
                    job_run.skipped_count = skipped_count
                    job_run.failed_count = failed_count
                    if failed_count == 0:
                        job_run.status = ScheduledJobRun.Status.SUCCESS
                    elif sent_count > 0:
                        job_run.status = ScheduledJobRun.Status.PARTIAL
                    else:
                        job_run.status = ScheduledJobRun.Status.FAILED
                    job_run.save()

                self.stdout.write(self.style.SUCCESS(
                    f"Processamento de avisos concluído. Processados: {processed_count}, Sucessos: {sent_count}, Falhas: {failed_count}, Ignorados: {skipped_count}"
                ))

            except Exception as e:
                logger.exception("ANNUAL_NOTICE_JOB_FAILED: Erro inesperado durante process_annual_renewal_notices: %s", str(e))
                if job_run:
                    job_run.finished_at = timezone.now()
                    job_run.status = ScheduledJobRun.Status.FAILED
                    job_run.error_summary = f"ANNUAL_NOTICE_JOB_FAILED: {str(e)[:500]}"
                    job_run.save()
                raise
