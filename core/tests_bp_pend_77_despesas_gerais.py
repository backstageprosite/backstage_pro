import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, User, Show, FinancialReceipt, ShowTeamCost, ShowPayment, BandGeneralExpense

class BandGeneralExpenseTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # 1. Setup Band and Users
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste', is_active=True, subscription_plan='ADVANCED')
        self.other_band = Band.objects.create(name='Outra Banda', slug='outra-banda', is_active=True, subscription_plan='ADVANCED')

        self.producer = User.objects.create_user(
            username='produtor',
            email='produtor@teste.com',
            password='password123',
            role='PRODUTOR',
            band=self.band
        )

        self.musician = User.objects.create_user(
            username='musico',
            email='musico@teste.com',
            password='password123',
            role='INTEGRANTE',
            band=self.band
        )

        self.other_producer = User.objects.create_user(
            username='outro_produtor',
            email='outro@teste.com',
            password='password123',
            role='PRODUTOR',
            band=self.other_band
        )

    def test_create_general_expense_success(self):
        """Teste 1: Criação de despesa geral da banda via view"""
        self.client.login(username='produtor', password='password123')
        url = reverse('general_expense_create', args=[self.band.slug])
        data = {
            'description': 'Marketing Digital Meta Ads',
            'category': 'Marketing',
            'date': '2026-09-15',
            'value': '450,00',
            'observations': 'Campanha de lançamento',
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        expense = BandGeneralExpense.objects.filter(band=self.band, description='Marketing Digital Meta Ads').first()
        self.assertIsNotNone(expense)
        self.assertEqual(expense.value, Decimal('450.00'))
        self.assertEqual(expense.created_by, self.producer)

    def test_edit_general_expense_success(self):
        """Teste 2: Edição de despesa geral"""
        expense = BandGeneralExpense.objects.create(
            band=self.band,
            description='Contador Mensal',
            category='Administrativo',
            date=datetime.date(2026, 9, 10),
            value=Decimal('300.00'),
            created_by=self.producer
        )
        self.client.login(username='produtor', password='password123')
        url = reverse('general_expense_edit', args=[self.band.slug, expense.id])
        data = {
            'description': 'Contador Mensal Atualizado',
            'category': 'Administrativo',
            'date': '2026-09-10',
            'value': '350,00',
            'observations': 'Reajuste anual',
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        expense.refresh_from_db()
        self.assertEqual(expense.description, 'Contador Mensal Atualizado')
        self.assertEqual(expense.value, Decimal('350.00'))

    def test_delete_general_expense_success(self):
        """Teste 3: Exclusão de despesa geral"""
        expense = BandGeneralExpense.objects.create(
            band=self.band,
            description='Equipamento Cabo XLR',
            category='Equipamentos',
            date=datetime.date(2026, 9, 12),
            value=Decimal('120.00'),
            created_by=self.producer
        )
        self.client.login(username='produtor', password='password123')
        url = reverse('general_expense_delete', args=[self.band.slug, expense.id])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.assertFalse(BandGeneralExpense.objects.filter(id=expense.id).exists())

    def test_musician_cannot_manage_general_expenses(self):
        """Teste 4: Apenas Produtor tem permissão para criar/editar/excluir despesas gerais"""
        self.client.login(username='musico', password='password123')

        create_url = reverse('general_expense_create', args=[self.band.slug])
        resp = self.client.post(create_url, {'description': 'Hack', 'date': '2026-09-15', 'value': '100'})
        self.assertEqual(resp.status_code, 403)

    def test_cross_band_isolation(self):
        """Teste 5: Isolamento multi-tenant entre bandas"""
        expense = BandGeneralExpense.objects.create(
            band=self.band,
            description='Despesa Banda 1',
            date=datetime.date(2026, 9, 10),
            value=Decimal('200.00')
        )
        self.client.login(username='outro_produtor', password='password123')

        # Tentar editar despesa da banda 1 usando a banda 2
        url_edit = reverse('general_expense_edit', args=[self.other_band.slug, expense.id])
        resp = self.client.post(url_edit, {'description': 'Tentativa Invasao', 'date': '2026-09-10', 'value': '100'})
        self.assertEqual(resp.status_code, 404)

        # Tentar excluir
        url_del = reverse('general_expense_delete', args=[self.other_band.slug, expense.id])
        resp_del = self.client.post(url_del)
        self.assertEqual(resp_del.status_code, 404)

    def test_financial_totals_consolidation_with_general_expenses(self):
        """Teste 6: Consolidação de totais com Despesas Gerais no Relatório Financeiro"""
        # Show: Fee 5000, Logística 500, Equipe 1000, Recebido 3000
        show = Show.objects.create(
            band=self.band,
            title='Festival de Primavera',
            date=datetime.date(2026, 9, 20),
            fee=Decimal('5000.00'),
            payment_status='PARCIAL',
            status='CONFIRMADO'
        )
        dummy_file = SimpleUploadedFile("recibo.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        FinancialReceipt.objects.create(show=show, description='Van', value=Decimal('500.00'), file=dummy_file)
        ShowTeamCost.objects.create(show=show, name='Técnico Som', value=Decimal('1000.00'))
        ShowPayment.objects.create(show=show, description='Sinal 60%', value=Decimal('3000.00'), status='RECEBIDO')

        # Despesa Geral da Banda: 800
        BandGeneralExpense.objects.create(
            band=self.band,
            description='Tráfego Pago Instagram',
            category='Marketing',
            date=datetime.date(2026, 9, 18),
            value=Decimal('800.00')
        )

        self.client.login(username='produtor', password='password123')
        url = reverse('relatorio_financeiro', args=[self.band.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Receita Contratada: 5000
        # Custos Shows: 500 + 1000 = 1500
        # Despesas Gerais: 800
        # Custos Totais: 1500 + 800 = 2300
        # Total Recebido: 3000
        # Resultado Previsto: 5000 - 2300 = 2700
        # Caixa Realizado: 3000 - 2300 = 700
        self.assertEqual(response.context['total_receita'], Decimal('5000.00'))
        self.assertEqual(response.context['total_custos_shows'], Decimal('1500.00'))
        self.assertEqual(response.context['total_despesas_gerais'], Decimal('800.00'))
        self.assertEqual(response.context['total_custos'], Decimal('2300.00'))
        self.assertEqual(response.context['resultado_previsto_total'], Decimal('2700.00'))
        self.assertEqual(response.context['caixa_realizado_geral'], Decimal('700.00'))

    def test_filter_by_period_affects_general_expenses(self):
        """Teste 7: Filtro por data filtra tanto shows quanto despesas gerais"""
        BandGeneralExpense.objects.create(
            band=self.band,
            description='Despesa Agosto',
            date=datetime.date(2026, 8, 15),
            value=Decimal('400.00')
        )
        BandGeneralExpense.objects.create(
            band=self.band,
            description='Despesa Setembro',
            date=datetime.date(2026, 9, 15),
            value=Decimal('600.00')
        )

        self.client.login(username='produtor', password='password123')
        url = f"{reverse('relatorio_financeiro', args=[self.band.slug])}?date_start=2026-09-01&date_end=2026-09-30"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context['qtd_general_expenses'], 1)
        self.assertEqual(response.context['total_despesas_gerais'], Decimal('600.00'))

    def test_file_upload_and_download_general_expense(self):
        """Teste 8: Upload de comprovante e download/preview protegido"""
        pdf_content = b"%PDF-1.4 sample pdf content"
        uploaded_file = SimpleUploadedFile("comprovante_anuncio.pdf", pdf_content, content_type="application/pdf")

        expense = BandGeneralExpense.objects.create(
            band=self.band,
            description='Anúncios Facebook',
            category='Marketing',
            date=datetime.date(2026, 9, 10),
            value=Decimal('250.00'),
            file=uploaded_file
        )

        self.client.login(username='produtor', password='password123')

        # Download
        url_download = reverse('download_general_expense', args=[self.band.slug, expense.id])
        resp_dl = self.client.get(url_download)
        self.assertEqual(resp_dl.status_code, 200)
        self.assertIn('attachment', resp_dl.headers.get('Content-Disposition', ''))

        # Preview
        url_preview = reverse('preview_general_expense', args=[self.band.slug, expense.id])
        resp_prev = self.client.get(url_preview)
        self.assertEqual(resp_prev.status_code, 200)

        # Viewer PWA
        url_viewer = reverse('file_viewer', args=[self.band.slug, 'general_expense', expense.id])
        resp_view = self.client.get(url_viewer)
        self.assertEqual(resp_view.status_code, 200)
