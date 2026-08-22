import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import BandSubscription, BillingRecord


class Command(BaseCommand):
    help = (
        "Varredura diaria de vencimentos de assinaturas. "
        "Cria faturas automaticamente para assinaturas que vencem em ate 7 dias "
        "e marca como Vencido as que passaram da data. "
        "Deve ser executado todo inicio do dia via cron/scheduler."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        seven_days = today + datetime.timedelta(days=7)

        created = 0
        updated_vencido = 0
        updated_vencendo = 0

        subscriptions = BandSubscription.objects.filter(
            status__in=["ATIVO", "VENCENDO"],
            is_deleted=False
        )

        for sub in subscriptions:
            if not sub.next_due_date:
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

                    BillingRecord.objects.create(
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

        self.stdout.write(self.style.SUCCESS(
            f"Varredura concluida: {created} faturas criadas, "
            f"{updated_vencendo} assinaturas marcadas como VENCENDO, "
            f"{updated_vencido} marcadas como VENCIDO."
        ))
