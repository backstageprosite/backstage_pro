import datetime
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Expense

class Command(BaseCommand):
    help = 'Processa as despesas recorrentes e gera os próximos lançamentos (7 dias antes do próximo vencimento).'

    def handle(self, *args, **options):
        today = timezone.localdate()
        target_date = today + datetime.timedelta(days=7)
        
        # We process all recurring expenses
        # To avoid infinite generation, we only generate the *immediate next* one for each expense if its next date is <= target_date
        
        recurring_expenses = Expense.objects.filter(is_recurring=True).order_by('due_date')
        created_count = 0
        
        for exp in recurring_expenses:
            # Determine next due date
            if exp.recurrence_cycle == 'MENSAL':
                next_due = exp.due_date + relativedelta(months=1)
                next_comp = exp.competence_date + relativedelta(months=1)
            elif exp.recurrence_cycle == 'TRIMESTRAL':
                next_due = exp.due_date + relativedelta(months=3)
                next_comp = exp.competence_date + relativedelta(months=3)
            elif exp.recurrence_cycle == 'SEMESTRAL':
                next_due = exp.due_date + relativedelta(months=6)
                next_comp = exp.competence_date + relativedelta(months=6)
            elif exp.recurrence_cycle == 'ANUAL':
                next_due = exp.due_date + relativedelta(years=1)
                next_comp = exp.competence_date + relativedelta(years=1)
            else:
                continue
                
            # If next_due is within our generation window (up to 7 days from now)
            # Actually, it could be generated any time it's past due or within 7 days.
            if next_due <= target_date:
                # Check if it has an end date and we passed it
                if exp.recurrence_end_date and next_due > exp.recurrence_end_date:
                    continue
                    
                # Check if this future expense already exists
                exists = Expense.objects.filter(
                    description=exp.description,
                    provider=exp.provider,
                    category=exp.category,
                    
                    due_date=next_due,
                    is_recurring=True
                ).exists()
                
                if not exists:
                    Expense.objects.create(
                        description=exp.description,
                        provider=exp.provider,
                        category=exp.category,
                        amount=exp.amount,
                        competence_date=next_comp,
                        due_date=next_due,
                        status='PENDENTE',
                        is_recurring=True,
                        recurrence_cycle=exp.recurrence_cycle,
                        recurrence_end_date=exp.recurrence_end_date
                    )
                    created_count += 1
                    
        self.stdout.write(self.style.SUCCESS(f'Processamento de despesas concluído: {created_count} criadas.'))
