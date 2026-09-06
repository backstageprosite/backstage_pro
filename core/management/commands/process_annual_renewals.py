import datetime
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.db import connection

from core.models import BandSubscription, AnnualPlanPurchase, ScheduledJobRun
from core.services.payments.renewal import AnnualRenewalService
from core.services.payments.base import get_business_date, acquire_job_advisory_lock, ANNUAL_RENEWAL_JOB_LOCK_ID

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Executa o motor de renovação automática para assinaturas anuais que atingiram o vencimento (D0 a D+4).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas avalia elegibilidade sem criar parcelamentos ou executar cobranças.',
        )
        parser.add_argument(
            '--subscription-id',
            type=int,
            help='Processa especificamente a assinatura informada pelo ID.',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Data de referência para avaliação no formato YYYY-MM-DD (padrão: hoje).',
        )

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

        # PROTEÇÃO DE ARQUITETURA: Testes financeiros reais e cron em homologação/produção não podem rodar em SQLite.
        django_env = getattr(settings, 'DJANGO_ENV', 'development').strip().lower()
        if django_env in ('staging', 'homologacao', 'production') and not getattr(settings, 'IS_RUNNING_TESTS', False):
            if connection.vendor == 'sqlite':
                self.stderr.write(self.style.ERROR(
                    "BLOQUEIO DE ARQUITETURA: Cron jobs em homologação/produção Railway não podem utilizar SQLite. "
                    "Utilize o PostgreSQL canônico do ambiente Railway."
                ))
                return

        # LOCK DISTRIBUÍDO: Garante que apenas uma instância deste job financeiro execute simultaneamente
        with acquire_job_advisory_lock(ANNUAL_RENEWAL_JOB_LOCK_ID) as lock_acquired:
            if not lock_acquired:
                self.stdout.write(self.style.WARNING("JOB_ALREADY_RUNNING: Outra instância de process_annual_renewals está ativa. Execução ignorada com segurança."))
                if not dry_run:
                    ScheduledJobRun.objects.create(
                        job_name='process_annual_renewals',
                        status=ScheduledJobRun.Status.SKIPPED_LOCKED,
                        error_summary="Execução ignorada: lock distribuído já adquirido por outra instância ativa."
                    )
                return

            job_run = None
            if not dry_run:
                job_run = ScheduledJobRun.objects.create(
                    job_name='process_annual_renewals',
                    status=ScheduledJobRun.Status.RUNNING,
                    started_at=timezone.now()
                )

            self.stdout.write(f"Iniciando processamento de renovações anuais para a data de negócio: {target_date}")
            if dry_run:
                self.stdout.write(self.style.WARNING("MODO DRY-RUN ATIVADO: Nenhuma cobrança real será realizada."))

            qs = BandSubscription.objects.filter(
                commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
                billing_cycle='ANUAL',
                status='ATIVO',
                auto_renew=True,
                cancel_at_period_end=False,
                is_deleted=False
            )

            if sub_id:
                qs = qs.filter(id=sub_id)

            count_total = qs.count()
            self.stdout.write(f"Total de assinaturas anuais ativas com auto_renew encontradas: {count_total}")

            service = AnnualRenewalService()
            processed_count = 0
            success_count = 0
            failure_count = 0
            skipped_count = 0

            try:
                for sub in qs:
                    if sub.is_partnership:
                        skipped_count += 1
                        continue

                    eligible, reason = service.is_eligible_for_renewal(sub, target_date=target_date)
                    if not eligible:
                        self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Ignorada -> {reason}")
                        skipped_count += 1
                        continue

                    processed_count += 1
                    price, reason_price = service.calculate_renewal_price(sub, target_date=target_date)
                    last_confirmed = AnnualPlanPurchase.objects.filter(
                        band_subscription=sub,
                        status=AnnualPlanPurchase.Status.CONFIRMED
                    ).order_by('-coverage_start').first()
                    inst_count = last_confirmed.installment_count if last_confirmed else 1

                    self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Elegível para renovação anual.")
                    if dry_run:
                        self.stdout.write(f"  [DRY-RUN] Simulação: criaria renovação de R$ {price:.2f} em {inst_count}x (Motivo: {reason_price})")
                        success_count += 1
                        continue

                    success, msg, purchase = service.process_subscription_renewal(sub, target_date=target_date)
                    if success:
                        self.stdout.write(self.style.SUCCESS(f"  Sub {sub.id}: Renovada com sucesso! Nova next_due_date: {sub.next_due_date}"))
                        success_count += 1
                    else:
                        self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha na renovação: {msg}"))
                        failure_count += 1

                if job_run:
                    job_run.finished_at = timezone.now()
                    job_run.processed_count = processed_count
                    job_run.success_count = success_count
                    job_run.skipped_count = skipped_count
                    job_run.failed_count = failure_count
                    if failure_count == 0:
                        job_run.status = ScheduledJobRun.Status.SUCCESS
                    elif success_count > 0:
                        job_run.status = ScheduledJobRun.Status.PARTIAL
                    else:
                        job_run.status = ScheduledJobRun.Status.FAILED
                    job_run.save()

                self.stdout.write(self.style.SUCCESS(
                    f"Processamento concluído. Processados: {processed_count}, Sucesso: {success_count}, Falhas: {failure_count}, Ignoradas: {skipped_count}"
                ))

            except Exception as e:
                logger.exception("ANNUAL_RENEWAL_JOB_FAILED: Erro inesperado durante process_annual_renewals: %s", str(e))
                if job_run:
                    job_run.finished_at = timezone.now()
                    job_run.status = ScheduledJobRun.Status.FAILED
                    job_run.error_summary = f"ANNUAL_RENEWAL_JOB_FAILED: {str(e)[:500]}"
                    job_run.save()
                raise
