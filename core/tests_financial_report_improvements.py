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

        resp3 = self.client.get('/painel/relatorios/financeiro/despesas/1/comprovante/')
        self.assertEqual(resp3.status_code, 403)

    def test_quick_period_buttons_calculation_and_year_transition(self):
        """Valida que os botões rápidos aplicam o período e atualizam start_date e end_date em uma ação"""
        from unittest.mock import patch

        # Testa com a data fixa de 24/09/2026 exigida
        fixed_date = datetime.date(2026, 9, 24)
        with patch('django.utils.timezone.localdate', return_value=fixed_date):
            # Este mês: 01/09/2026 a 30/09/2026
            resp = self.client.get('/painel/relatorios/financeiro/?period=this_month')
            self.assertEqual(resp.context['start_date'], '2026-09-01')
            self.assertEqual(resp.context['end_date'], '2026-09-30')

            # Mês passado: 01/08/2026 a 31/08/2026
            resp = self.client.get('/painel/relatorios/financeiro/?period=last_month')
            self.assertEqual(resp.context['start_date'], '2026-08-01')
            self.assertEqual(resp.context['end_date'], '2026-08-31')

            # Próx. 30 dias: 24/09/2026 a 23/10/2026 (30 dias incluindo hoje)
            resp = self.client.get('/painel/relatorios/financeiro/?period=next_30')
            self.assertEqual(resp.context['start_date'], '2026-09-24')
            self.assertEqual(resp.context['end_date'], '2026-10-23')

            # Este ano: 01/01/2026 a 31/12/2026
            resp = self.client.get('/painel/relatorios/financeiro/?period=this_year')
            self.assertEqual(resp.context['start_date'], '2026-01-01')
            self.assertEqual(resp.context['end_date'], '2026-12-31')

            # Preservação de outros filtros ao clicar no período rápido mesmo se inputs antigos vierem preenchidos
            resp = self.client.get('/painel/relatorios/financeiro/?period=last_month&start_date=2026-09-01&end_date=2026-09-30&status=PAGO&cycle=MENSAL')
            self.assertEqual(resp.context['start_date'], '2026-08-01')
            self.assertEqual(resp.context['end_date'], '2026-08-31')
            self.assertEqual(resp.context['status'], 'PAGO')
            self.assertEqual(resp.context['cycle'], 'MENSAL')

        # Testa virada de ano em 15/01/2027: mês passado deve ser 01/12/2026 a 31/12/2026
        jan_date = datetime.date(2027, 1, 15)
        with patch('django.utils.timezone.localdate', return_value=jan_date):
            resp = self.client.get('/painel/relatorios/financeiro/?period=last_month')
            self.assertEqual(resp.context['start_date'], '2026-12-01')
            self.assertEqual(resp.context['end_date'], '2026-12-31')

    def test_billings_period_filtering_coherence(self):
        """Valida que Faturas Detalhadas e Gráfico de Status contêm apenas faturas do período filtrado"""
        sep_date = datetime.date(2026, 9, 23)
        oct_date = datetime.date(2026, 10, 23)

        # 3 bandas com 1 fatura de Setembro (paga) e 1 de Outubro (pendente) cada, totalizando 6 faturas no banco
        bands_subs = []
        for i in range(3):
            b = Band.objects.create(name=f'Banda {i}', slug=f'banda-{i}')
            s = BandSubscription.objects.create(
                band=b,
                plan_name='Profissional',
                billing_cycle='MENSAL',
                contracted_value=Decimal('49.90'),
                commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
                status='ATIVO',
                gateway_provider='ASAAS',
                gateway_subscription_id=f'sub_test_coherence_{i}',
                gateway_customer_id=f'cus_test_coherence_{i}'
            )
            bands_subs.append((b, s))

        for idx, (b, s) in enumerate(bands_subs):
            BillingRecord.objects.create(
                subscription=s,
                band=b,
                reference_period=f'Setembro/2026 #{idx}',
                amount=Decimal('49.90'),
                due_date=sep_date,
                paid_date=sep_date,
                status='PAGO',
                gateway_provider='ASAAS',
                gateway_payment_id=f'pay_sep_{idx}'
            )
            BillingRecord.objects.create(
                subscription=s,
                band=b,
                reference_period=f'Outubro/2026 #{idx}',
                amount=Decimal('49.90'),
                due_date=oct_date,
                status='PENDENTE',
                gateway_provider='ASAAS',
                gateway_payment_id=f'pay_oct_{idx}'
            )

        # Filtrar 01/09/2026 a 30/09/2026: deve conter exatamente as 3 faturas de Setembro e 0 de Outubro
        resp = self.client.get('/painel/relatorios/financeiro/?start_date=2026-09-01&end_date=2026-09-30')
        self.assertEqual(resp.status_code, 200)
        billings_context = list(resp.context['billings'])
        self.assertEqual(len(billings_context), 3)
        self.assertTrue(all(b.paid_date == sep_date for b in billings_context))

        # O gráfico de status (chart_pie) deve refletir somente as 3 faturas de Setembro
        import json
        pie_data = json.loads(resp.context['chart_pie'])
        self.assertEqual(pie_data['labels'], ['PAGO'])
        self.assertEqual(pie_data['data'], [3])

    def test_expense_proof_view_security_and_availability(self):
        """Valida rota protegida de comprovante de despesa para admin e bloqueio de não-autorizados"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        # Cria despesa com arquivo de comprovante real em memória
        proof = SimpleUploadedFile("comprovante_hostinger.jpg", b"fake image bytes", content_type="image/jpeg")
        expense = Expense.objects.create(
            description='Hostinger Dominio',
            provider='Hostinger',
            category='Infraestrutura',
            amount=Decimal('86.28'),
            competence_date=datetime.date(2026, 7, 4),
            due_date=datetime.date(2029, 7, 4),
            paid_date=datetime.date(2026, 7, 4),
            status='PAGO',
            proof_file=proof,
            created_by=self.admin
        )

        # Admin geral consegue abrir o comprovante
        resp = self.client.get(f'/painel/relatorios/financeiro/despesas/{expense.id}/comprovante/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')

        # Usuário comum é bloqueado
        self.client.force_login(self.regular_user)
        resp_forbidden = self.client.get(f'/painel/relatorios/financeiro/despesas/{expense.id}/comprovante/')
        self.assertIn(resp_forbidden.status_code, [302, 403])
