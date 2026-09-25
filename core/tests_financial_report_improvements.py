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
        self.client.force_login(self.admin)

    def test_expense_create_and_edit_brazilian_currency_formats(self):
        """Valida que valores com vírgula, ponto e separadores de milhar são aceitos e normalizados com Decimal"""
        from django.urls import reverse
        self.client.force_login(self.admin)
        url_create = reverse('admin_painel:expense_create')

        # 1. Cadastro com vírgula '49,90'
        resp1 = self.client.post(url_create, {
            'description': 'Licença Software A',
            'category': 'Sistemas',
            'amount': '49,90',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-10',
            'status': 'PENDENTE'
        })
        self.assertEqual(resp1.status_code, 302)
        exp1 = Expense.objects.get(description='Licença Software A')
        self.assertEqual(exp1.amount, Decimal('49.90'))
        self.assertFalse(bool(exp1.proof_file))

        # 2. Cadastro com ponto '49.90'
        resp2 = self.client.post(url_create, {
            'description': 'Licença Software B',
            'category': 'Sistemas',
            'amount': '49.90',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-11',
            'status': 'PENDENTE'
        })
        self.assertEqual(resp2.status_code, 302)
        exp2 = Expense.objects.get(description='Licença Software B')
        self.assertEqual(exp2.amount, Decimal('49.90'))

        # 3. Cadastro com milhar e vírgula '1.234,56'
        resp3 = self.client.post(url_create, {
            'description': 'Servidor Cloud Anual',
            'category': 'Infraestrutura',
            'amount': '1.234,56',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-15',
            'status': 'PAGO'
        })
        self.assertEqual(resp3.status_code, 302)
        exp3 = Expense.objects.get(description='Servidor Cloud Anual')
        self.assertEqual(exp3.amount, Decimal('1234.56'))

        # 4. Cadastro com milhar americano '1,234.56'
        resp4 = self.client.post(url_create, {
            'description': 'Gateway Setup Fee',
            'category': 'Taxas',
            'amount': '1,234.56',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-16',
            'status': 'PAGO'
        })
        self.assertEqual(resp4.status_code, 302)
        exp4 = Expense.objects.get(description='Gateway Setup Fee')
        self.assertEqual(exp4.amount, Decimal('1234.56'))

        # 5. Edição com formato brasileiro '2.345,67'
        url_edit1 = reverse('admin_painel:expense_edit', kwargs={'pk': exp1.id})
        resp_edit = self.client.post(url_edit1, {
            'description': 'Licença Software A Atualizada',
            'category': 'Sistemas',
            'amount': '2.345,67',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-10',
            'status': 'PENDENTE'
        })
        self.assertEqual(resp_edit.status_code, 302)
        exp1.refresh_from_db()
        self.assertEqual(exp1.description, 'Licença Software A Atualizada')
        self.assertEqual(exp1.amount, Decimal('2345.67'))

    def test_expense_currency_rejections_and_validation(self):
        """Valida que entradas inválidas ou ambíguas são rejeitadas sem conversão silenciosa"""
        from core.admin_views_expenses import parse_brazilian_currency
        from django import forms

        # Mais de 2 casas decimais -> Rejeita
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('49,999')
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('49.999')

        # Formato de milhar inconsistente -> Rejeita
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('1.23.456,78')
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('1,234,56')

        # Letras / caracteres inválidos -> Rejeita
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('abc')
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('R$')

        # Valor zero ou negativo -> Rejeita
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('0,00')
        with self.assertRaises(forms.ValidationError):
            parse_brazilian_currency('-50,00')

    def test_expense_proof_preserved_on_edit_without_new_file(self):
        """Valida que comprovante existente não é apagado quando edição é enviada sem novo arquivo"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        self.client.force_login(self.admin)

        proof = SimpleUploadedFile("recibo_inicial.pdf", b"%PDF-1.4 initial receipt content", content_type="application/pdf")
        expense = Expense.objects.create(
            description='Serviço com Comprovante',
            category='Infraestrutura',
            amount=Decimal('150.00'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 10),
            status='PAGO',
            proof_file=proof,
            created_by=self.admin
        )
        self.assertTrue(bool(expense.proof_file))
        old_filename = expense.proof_file.name

        # Envia edição sem o campo de arquivo proof_file
        url_edit = reverse('admin_painel:expense_edit', kwargs={'pk': expense.id})
        resp = self.client.post(url_edit, {
            'description': 'Serviço com Comprovante (Atualizado)',
            'category': 'Infraestrutura',
            'amount': '150,00',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-10',
            'status': 'PAGO'
        })
        self.assertEqual(resp.status_code, 302)

        expense.refresh_from_db()
        self.assertEqual(expense.description, 'Serviço com Comprovante (Atualizado)')
        self.assertTrue(bool(expense.proof_file))
        self.assertEqual(expense.proof_file.name, old_filename)

    def test_duplicate_expense_detection_with_normalized_amount(self):
        """Valida que a detecção de duplicata compara pelo valor normalizado Decimal"""
        from django.urls import reverse
        self.client.force_login(self.admin)

        # Cria primeira despesa com '49.90'
        Expense.objects.create(
            description='Hospedagem Web',
            category='Infra',
            amount=Decimal('49.90'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 20),
            status='PENDENTE',
            created_by=self.admin
        )

        # Tenta cadastrar idêntica digitando '49,90'
        url_create = reverse('admin_painel:expense_create')
        resp = self.client.post(url_create, {
            'description': 'Hospedagem Web',
            'category': 'Infra',
            'amount': '49,90',
            'competence_date': '2026-09-01',
            'due_date': '2026-09-20',
            'status': 'PENDENTE'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages_list = [str(m) for m in resp.context['messages']]
        self.assertTrue(any('Já existe um lançamento com a mesma descrição' in m for m in messages_list))
        # O lançamento legítimo foi registrado (avisa sem impedir)
        self.assertEqual(Expense.objects.filter(description='Hospedagem Web').count(), 2)

    def test_expense_ordering_by_paid_date_and_due_date(self):
        """
        Valida que no Relatório Financeiro > Despesas Detalhadas:
        - Despesas pagas são ordenadas pela data de pagamento (paid_date), da mais recente para a mais antiga.
          Exemplo:
            #1 — 21/09/2026;
            #3 — 22/08/2026;
            #2 — 04/07/2026.
        - Despesas não pagas têm o vencimento mais próximo primeiro (due_date ASC).
        - Despesas com IDs e datas fora de sequência testam que a ordenação não depende de ID ou updated_at.
        - Totais e filtros permanecem preservados.
        """
        self.client.force_login(self.admin)
        # Limpar despesas pré-existentes para teste isolado
        Expense.objects.all().delete()

        # Criar despesas com IDs e datas fora de sequência:
        # ID 1: paga em 21/09/2026
        # ID 2: paga em 04/07/2026
        # ID 3: paga em 22/08/2026
        e1 = Expense.objects.create(
            id=1,
            description='Despesa 1',
            category='Infra',
            amount=Decimal('50.00'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 25),
            status='PAGO',
            paid_date=datetime.date(2026, 9, 21),
            created_by=self.admin
        )
        e2 = Expense.objects.create(
            id=2,
            description='Despesa 2',
            category='Infra',
            amount=Decimal('30.00'),
            competence_date=datetime.date(2026, 7, 1),
            due_date=datetime.date(2026, 7, 10),
            status='PAGO',
            paid_date=datetime.date(2026, 7, 4),
            created_by=self.admin
        )
        e3 = Expense.objects.create(
            id=3,
            description='Despesa 3',
            category='Infra',
            amount=Decimal('40.00'),
            competence_date=datetime.date(2026, 8, 1),
            due_date=datetime.date(2026, 8, 15),
            status='PAGO',
            paid_date=datetime.date(2026, 8, 22),
            created_by=self.admin
        )

        # Despesas não pagas com datas e IDs fora de sequência
        # ID 4: Pendente vencimento 30/09/2026
        # ID 5: Pendente vencimento 15/09/2026 (mais próximo que ID 4)
        # ID 6: Vencido vencimento 10/10/2026
        e4 = Expense.objects.create(
            id=4,
            description='Despesa 4 Pendente',
            category='Infra',
            amount=Decimal('20.00'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 30),
            status='PENDENTE',
            paid_date=None,
            created_by=self.admin
        )
        e5 = Expense.objects.create(
            id=5,
            description='Despesa 5 Pendente Vencimento Mais Próximo',
            category='Infra',
            amount=Decimal('25.00'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 15),
            status='PENDENTE',
            paid_date=None,
            created_by=self.admin
        )
        e6 = Expense.objects.create(
            id=6,
            description='Despesa 6 Vencida',
            category='Infra',
            amount=Decimal('15.00'),
            competence_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 10, 5),
            status='VENCIDO',
            paid_date=None,
            created_by=self.admin
        )

        # Acessa relatório financeiro com período cobrindo todas as datas
        resp = self.client.get('/painel/relatorios/financeiro/?start_date=2026-07-01&end_date=2026-10-31')
        self.assertEqual(resp.status_code, 200)

        expenses_period = list(resp.context['expenses_period'])
        ordered_ids = [exp.id for exp in expenses_period]

        # Ordem esperada:
        # Pagas primeiro por paid_date DESC: #1 (21/09), #3 (22/08), #2 (04/07)
        # Não pagas depois por due_date ASC: #5 (15/09), #4 (30/09), #6 (05/10)
        self.assertEqual(ordered_ids, [1, 3, 2, 5, 4, 6])

        # Verificar as datas exatas das despesas pagas
        paid_expenses = [exp for exp in expenses_period if exp.status == 'PAGO']
        self.assertEqual([(exp.id, exp.paid_date) for exp in paid_expenses], [
            (1, datetime.date(2026, 9, 21)),
            (3, datetime.date(2026, 8, 22)),
            (2, datetime.date(2026, 7, 4)),
        ])

        # Verificar as datas de vencimento das não pagas (mais próximo primeiro)
        unpaid_expenses = [exp for exp in expenses_period if exp.status != 'PAGO']
        self.assertEqual([(exp.id, exp.due_date) for exp in unpaid_expenses], [
            (5, datetime.date(2026, 9, 15)),
            (4, datetime.date(2026, 9, 30)),
            (6, datetime.date(2026, 10, 5)),
        ])

        # Verificar que o total de despesas pagas continua preservado (50 + 30 + 40 = 120.00)
        self.assertEqual(resp.context['despesa_paga'], Decimal('120.00'))


