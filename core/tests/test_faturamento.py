import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Band, User, BandSubscription, BillingRecord, Expense
from django.core.management import call_command
from unittest.mock import patch

class FaturamentoTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(username='admin', password='123', email='admin@a.com')
        self.produtor = User.objects.create_user(username='prod', password='123', email='prod@a.com', role='PRODUTOR_BANDA')
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.subscription = BandSubscription.objects.create(
            band=self.band,
            plan_name='Mensal',
            billing_cycle='MENSAL',
            contracted_value=Decimal('500.00'),
            start_date=datetime.date(2026, 1, 1),
            next_due_date=datetime.date(2026, 8, 1),
            status='ATIVO'
        )
        self.client.login(username='admin', password='123')

    @patch('django.utils.timezone.localdate')
    def test_cenario_exato_vencido(self, mock_localdate):
        mock_localdate.return_value = datetime.date(2026, 8, 20)
        
        record = BillingRecord.objects.create(
            subscription=self.subscription,
            band=self.band,
            reference_period='Agosto/2026',
            amount=500,
            due_date=datetime.date(2026, 8, 1),
            status='PENDENTE'
        )
        
        self.assertEqual(record.dynamic_status, 'VENCIDO')
        self.assertEqual(record.get_dynamic_status_display(), 'Vencido')
        
    @patch('django.utils.timezone.localdate')
    def test_cenario_exato_prox_vencimento(self, mock_localdate):
        mock_localdate.return_value = datetime.date(2026, 8, 20)
        
        record = BillingRecord.objects.create(
            subscription=self.subscription,
            band=self.band,
            reference_period='Agosto/2026',
            amount=500,
            due_date=datetime.date(2026, 8, 25),
            status='PENDENTE'
        )
        
        self.assertEqual(record.dynamic_status, 'PROX_VENCIMENTO')
        
    def test_process_subscription_billings_creation(self):
        call_command('process_subscription_billings')
        self.assertEqual(BillingRecord.objects.count(), 1)
        record = BillingRecord.objects.first()
        self.assertEqual(record.status, 'PENDENTE')

    def test_billing_marcar_paga(self):
        record = BillingRecord.objects.create(
            subscription=self.subscription,
            band=self.band,
            reference_period='Agosto/2026',
            amount=500,
            due_date=datetime.date(2026, 8, 1),
            status='PENDENTE'
        )
        old_due = self.subscription.next_due_date
        
        response = self.client.post(reverse('admin_painel:cobrancas_status', args=[record.id, 'PAGO']))
        self.assertEqual(response.status_code, 302)
        
        record.refresh_from_db()
        self.assertEqual(record.status, 'PAGO')
        self.assertIsNotNone(record.paid_date)
        
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.next_due_date, datetime.date(2026, 9, 1))
        
    def test_expense_crud(self):
        # Create
        response = self.client.post(reverse('admin_painel:expense_create'), {
            'description': 'Railway',
            'category': 'Servidor',
            'amount': '50.00',
            'competence_date': timezone.localdate().strftime('%Y-%m-%d'),
            'due_date': timezone.localdate().strftime('%Y-%m-%d'),
            'status': 'PENDENTE'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Expense.objects.count(), 1)
        
        exp = Expense.objects.first()
        # Mark paid
        response = self.client.post(reverse('admin_painel:expense_mark_paid', args=[exp.id]))
        exp.refresh_from_db()
        self.assertEqual(exp.status, 'PAGO')
        
        # Delete
        response = self.client.post(reverse('admin_painel:expense_delete', args=[exp.id]))
        self.assertEqual(Expense.objects.count(), 0)

    def test_assinatura_soft_delete(self):
        response = self.client.post(reverse('admin_painel:assinaturas_cancelar', args=[self.subscription.id]))
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.is_deleted)
        self.assertEqual(self.subscription.status, 'DESATIVADO')
        
        # New subscription for the same band
        sub2 = BandSubscription.objects.create(
            band=self.band,
            plan_name='Mensal',
            status='ATIVO'
        )
        self.assertEqual(BandSubscription.objects.filter(band=self.band).count(), 2)
        
    def test_kpis_report(self):
        record_paid = BillingRecord.objects.create(
            subscription=self.subscription, band=self.band,
            reference_period='08/2026', amount=300,
            due_date=datetime.date(2026, 8, 1), paid_date=datetime.date(2026, 8, 2), status='PAGO'
        )
        record_pend = BillingRecord.objects.create(
            subscription=self.subscription, band=self.band,
            reference_period='09/2026', amount=300,
            due_date=datetime.date(2026, 9, 1), status='PENDENTE'
        )
        exp_paid = Expense.objects.create(
            description='Exp1', category='Cat', amount=100,
            competence_date=datetime.date(2026, 8, 1), due_date=datetime.date(2026, 8, 1),
            paid_date=datetime.date(2026, 8, 1), status='PAGO'
        )
        exp_pend = Expense.objects.create(
            description='Exp2', category='Cat', amount=50,
            competence_date=datetime.date(2026, 9, 1), due_date=datetime.date(2026, 9, 1),
            status='PENDENTE'
        )
        
        response = self.client.get(reverse('admin_painel:relatorio_financeiro') + "?start_date=2026-08-01&end_date=2026-09-30")
        self.assertEqual(response.context['recebido'], Decimal('300.00'))
        self.assertEqual(response.context['despesa_paga'], Decimal('100.00'))
        self.assertEqual(response.context['saldo_realizado'], Decimal('200.00'))
        self.assertEqual(response.context['a_receber'], Decimal('300.00'))
        self.assertEqual(response.context['a_pagar'], Decimal('50.00'))

    def test_security(self):
        self.client.logout()
        self.client.login(username='prod', password='123')
        
        response = self.client.get(reverse('admin_painel:assinaturas'))
        self.assertEqual(response.status_code, 302) # Redirect to login

    def test_process_recurring_expenses(self):
        Expense.objects.create(
            description='Recorrente Mensal', category='Cat', amount=50,
            competence_date=datetime.date.today(), due_date=datetime.date.today() - datetime.timedelta(days=25),
            status='PENDENTE', is_recurring=True, recurrence_cycle='MENSAL'
        )
        call_command('process_recurring_expenses')
        self.assertEqual(Expense.objects.count(), 2)
