import datetime
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import BandSubscription, BillingRecord

class Command(BaseCommand):
    help = 'Processa as assinaturas ativas e gera as faturas/cobranças dos próximos 7 dias.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        target_date = today + datetime.timedelta(days=7)
        
        subscriptions = BandSubscription.objects.filter(status='ATIVO', is_deleted=False)
        created_count = 0
        ignored_count = 0
        
        for sub in subscriptions:
            if not sub.next_due_date:
                continue
                
            if sub.next_due_date <= target_date:
                # Check if it exists
                exists = BillingRecord.objects.filter(subscription=sub, due_date=sub.next_due_date).exists()
                if not exists:
                    # Create billing
                    # reference period logic: e.g. "Agosto/2026"
                    month_name = {
                        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
                        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
                    }[sub.next_due_date.month]
                    ref_period = f"{month_name}/{sub.next_due_date.year}"
                    
                    BillingRecord.objects.create(
                        subscription=sub,
                        band=sub.band,
                        reference_period=ref_period,
                        amount=sub.contracted_value,
                        due_date=sub.next_due_date,
                        status='PENDENTE',
                        plan_name=sub.plan_name,
                        billing_cycle=sub.billing_cycle,
                    )
                    created_count += 1
                else:
                    ignored_count += 1
                    
        self.stdout.write(self.style.SUCCESS(f'Processamento concluído: {created_count} criadas, {ignored_count} ignoradas (já existiam).'))
