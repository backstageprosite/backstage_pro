import datetime
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import BandSubscription
from core.services.payments.renewal import AnnualRenewalService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Executa o motor de renovação automática para assinaturas anuais que atingiram o vencimento.'

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

        target_date = timezone.localdate()
        if date_str:
            try:
                target_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Data inválida: {date_str}. Use YYYY-MM-DD."))
                return

        self.stdout.write(f"Iniciando processamento de renovações anuais para a data-base: {target_date}")
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN ATIVADO: Nenhuma cobrança real será realizada."))

        qs = BandSubscription.objects.filter(
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
        success_count = 0
        failure_count = 0
        skipped_count = 0

        for sub in qs:
            eligible, reason = service.is_eligible_for_renewal(sub, target_date=target_date)
            if not eligible:
                self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Ignorada -> {reason}")
                skipped_count += 1
                continue

            self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Elegível para renovação anual.")
            if dry_run:
                self.stdout.write(f"  [DRY-RUN] Simulação: criaria renovação de R$ {sub.contracted_value}")
                continue

            success, msg, purchase = service.process_subscription_renewal(sub, target_date=target_date)
            if success:
                self.stdout.write(self.style.SUCCESS(f"  Sub {sub.id}: Renovada com sucesso! Nova next_due_date: {sub.next_due_date}"))
                success_count += 1
            else:
                self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha na renovação: {msg}"))
                failure_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Processamento concluído. Sucesso: {success_count}, Falhas: {failure_count}, Ignoradas: {skipped_count}"
        ))
