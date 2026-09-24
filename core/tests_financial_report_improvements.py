from decimal import Decimal
import datetime
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import Band, BandSubscription, BillingRecord, Expense
from core.services.payments.asaas.webhooks import reconcile_and_update_billing_record

User = get_user_model()


class FinancialReportImprovementsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='password123'
        )
        self.client = Client()
        self.client.force_login(self.admin)

        self.regular_user = User.objects.create_user(
            username='user_test',
            email='user@test.com',
            password='password123'
        )

        self.band = Band.objects.create(name='Banda Alpha', slug='banda-alpha')
        self.sub = BandSubscription.objects.create(
            band=self.band,
            plan_name='Profissional',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_test_123',
            gateway_customer_id='cus_test_123'
        )

    def test_billings_passed_in_context_resolving_divergence(self):
        """Testa se a lista billings é passada no contexto do relatório financeiro"""
        today = timezone.localdate()
        BillingRecord.objects.create(
            subscription=self.sub,
            band=self.band,
            reference_period='Setembro/2026',
            amount=Decimal('49.90'),
            due_date=today,
            paid_date=today,
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_001'
        )

        response = self.client.get(f'/painel/relatorios/financeiro/?start_date={today.replace(day=1)}&end_date={today}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('billings', response.context)
        self.assertEqual(response.context['billings'].count(), 1)
        self.assertIn('expenses_period', response.context)
        self.assertEqual(response.context['kpi_recebido'], Decimal('49.90'))

    def test_expense_crud_and_duplicate_warning(self):
        """Testa criação com aviso de duplicidade e exclusão de despesa"""
        today = timezone.localdate()
        exp1 = Expense.objects.create(
            description='Servidor Cloud',
            provider='AWS',
            category='Infraestrutura',
            amount=Decimal('50.00'),
            competence_date=today,
            due_date=today,
            status='PAGO',
            paid_date=today,
            created_by=self.admin
        )

        # Cadastro de despesa idêntica deve emitir warning de duplicidade
        response = self.client.post('/painel/relatorios/financeiro/despesas/nova/', {
            'description': 'Servidor Cloud',
            'provider': 'AWS',
            'category': 'Infraestrutura',
            'amount': '50.00',
            'competence_date': today.strftime('%Y-%m-%d'),
            'due_date': today.strftime('%Y-%m-%d'),
            'status': 'PAGO',
            'paid_date': today.strftime('%Y-%m-%d'),
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expense.objects.filter(description='Servidor Cloud').count(), 2)

        # Exclusão via post de exp1 sem afetar exp2
        exp2 = Expense.objects.exclude(id=exp1.id).first()
        del_resp = self.client.post(f'/painel/relatorios/financeiro/despesas/{exp1.id}/excluir/', follow=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(Expense.objects.filter(id=exp1.id).exists())
        self.assertTrue(Expense.objects.filter(id=exp2.id).exists())

    def test_edit_net_amount_individual_and_kpi_recalculation(self):
        """Testa edição do valor líquido recebido de uma fatura e recálculo dos indicadores"""
        today = timezone.localdate()
        rec1 = BillingRecord.objects.create(
            subscription=self.sub,
            band=self.band,
            reference_period='Agosto/2026',
            amount=Decimal('49.90'),
            due_date=today,
            paid_date=today,
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_002'
        )
        rec2 = BillingRecord.objects.create(
            subscription=self.sub,
            band=self.band,
            reference_period='Setembro/2026',
            amount=Decimal('49.90'),
            due_date=today + datetime.timedelta(days=30),
            paid_date=today,
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_003'
        )

        # Ajusta líquido apenas da fatura 1
        adj_resp = self.client.post(f'/painel/relatorios/financeiro/cobrancas/{rec1.id}/ajustar-liquido/', {
            'net_amount': '47.91',
            'reason': 'Desconto taxa Asaas R$ 1,99'
        })
        self.assertEqual(adj_resp.status_code, 200)
        data = adj_resp.json()
        self.assertTrue(data['ok'])

        rec1.refresh_from_db()
        rec2.refresh_from_db()
        self.assertEqual(rec1.net_amount, Decimal('47.91'))
        self.assertTrue(rec1.net_amount_manual)
        self.assertEqual(rec1.net_amount_reason, 'Desconto taxa Asaas R$ 1,99')
        self.assertEqual(rec1.net_amount_updated_by, self.admin)

        # Fatura 2 não deve ter sido afetada
        self.assertIsNone(rec2.net_amount)
        self.assertFalse(rec2.net_amount_manual)

        # Indicador de recebidos deve somar 47.91 + 49.90 = 97.81
        start_date = today.replace(day=1)
        end_date = today + datetime.timedelta(days=60)
        report_resp = self.client.get(f'/painel/relatorios/financeiro/?start_date={start_date}&end_date={end_date}')
        self.assertEqual(report_resp.context['kpi_recebido'], Decimal('97.81'))

    def test_webhook_does_not_overwrite_manual_net_amount(self):
        """Garante que webhooks subsequentes não sobrescrevam a correção manual do líquido"""
        today = timezone.localdate()
        rec = BillingRecord.objects.create(
            subscription=self.sub,
            band=self.band,
            reference_period='Setembro/2026',
            amount=Decimal('49.90'),
            net_amount=Decimal('47.91'),
            net_amount_manual=True,
            net_amount_reason='Taxa gateway',
            due_date=today,
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_hook'
        )

        payload = {
            'event': 'PAYMENT_RECEIVED',
            'payment': {
                'id': 'pay_test_hook',
                'value': 49.90,
                'netValue': 47.50,
                'status': 'RECEIVED',
                'paymentDate': today.isoformat(),
                'subscription': 'sub_test_123',
                'customer': 'cus_test_123'
            }
        }

        success, msg = reconcile_and_update_billing_record(payload, 'PAYMENT_RECEIVED')
        self.assertTrue(success)

        rec.refresh_from_db()
        self.assertEqual(rec.status, 'PAGO')
        self.assertEqual(rec.net_amount, Decimal('47.91'), "O net_amount manual deve ser preservado.")
        self.assertTrue(rec.net_amount_manual)
        self.assertEqual(rec.net_amount_reason, 'Taxa gateway')

    def test_regular_user_access_blocked(self):
        """Garante que usuários sem privilégio de admin geral não acessem os endpoints"""
        self.client.force_login(self.regular_user)
        resp1 = self.client.get('/painel/relatorios/financeiro/')
        self.assertEqual(resp1.status_code, 302)

        resp2 = self.client.get(f'/painel/relatorios/financeiro/bandas/{self.band.id}/cobrancas/')
        self.assertEqual(resp2.status_code, 302)
