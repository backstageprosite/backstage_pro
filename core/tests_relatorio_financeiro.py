from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
import datetime
from core.models import Band, User, Show, ShowPayment, ShowTeamCost, FinancialReceipt, UserBandMembership

class FinancialReportsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste", plan_type=Band.PlanType.AVANCADO)
        self.other_band = Band.objects.create(name="Outra Banda", slug="outra-banda", plan_type=Band.PlanType.AVANCADO)

        self.produtor = User.objects.create_user(
            username="produtor_fin",
            email="produtor@teste.com",
            password="password123",
            role="PRODUTOR",
            band=self.band
        )
        UserBandMembership.objects.create(
            user=self.produtor,
            band=self.band,
            role="PRODUTOR",
            is_active=True
        )

        self.integrante = User.objects.create_user(
            username="integrante_fin",
            email="integrante@teste.com",
            password="password123",
            role="INTEGRANTE",
            band=self.band
        )
        UserBandMembership.objects.create(
            user=self.integrante,
            band=self.band,
            role="INTEGRANTE",
            is_active=True
        )

        # Shows para banda teste
        self.show1 = Show.objects.create(
            band=self.band,
            title="Show Confirmado 1",
            event_name="Festival de Verão",
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 10),
            fee=Decimal('10000.00'),
            payment_status='PARCIAL'
        )
        ShowPayment.objects.create(
            show=self.show1,
            description="Sinal de Entrada",
            value=Decimal('4000.00'),
            expected_date=datetime.date(2026, 9, 1),
            receipt_date=datetime.date(2026, 9, 1),
            status='RECEBIDO'
        )
        ShowPayment.objects.create(
            show=self.show1,
            description="Restante",
            value=Decimal('6000.00'),
            expected_date=datetime.date(2026, 9, 15),
            status='PENDENTE'
        )
        FinancialReceipt.objects.create(
            show=self.show1,
            description="Van Translado",
            value=Decimal('1500.00'),
            date=datetime.date(2026, 9, 10)
        )
        ShowTeamCost.objects.create(
            show=self.show1,
            name="Músico Convidado",
            value=Decimal('500.00')
        )

        # Show cancelado (não deve entrar nos cálculos de elegíveis)
        self.show_cancelado = Show.objects.create(
            band=self.band,
            title="Show Cancelado",
            status=Show.STATUS_CANCELADO,
            date=datetime.date(2026, 9, 20),
            fee=Decimal('8000.00'),
            payment_status='PENDENTE'
        )

    def test_relatorios_view_renders_correctly_for_produtor(self):
        self.client.login(username="produtor_fin", password="password123")
        response = self.client.get(reverse('relatorio_financeiro', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financeiro")
        self.assertContains(response, "Gráficos")
        self.assertContains(response, "Gerar PDF")
        self.assertContains(response, "modalExportFinanceiroPdf")

    def test_relatorio_graficos_view_produtor_allowed_integrante_forbidden(self):
        # Integrante deve receber 403
        self.client.login(username="integrante_fin", password="password123")
        res_int = self.client.get(reverse('relatorio_financeiro_graficos', args=[self.band.slug]))
        self.assertEqual(res_int.status_code, 403)

        # Produtor deve receber 200
        self.client.login(username="produtor_fin", password="password123")
        res_prod = self.client.get(reverse('relatorio_financeiro_graficos', args=[self.band.slug]))
        self.assertEqual(res_prod.status_code, 200)
        self.assertContains(res_prod, "Faturamento por Mês")
        self.assertContains(res_prod, "Recebido vs A Receber por Mês")
        self.assertContains(res_prod, "Top Shows por Cachê")
        self.assertContains(res_prod, "chartFaturamento")

    def test_relatorio_graficos_export_view(self):
        self.client.login(username="produtor_fin", password="password123")
        response = self.client.get(reverse('relatorio_financeiro_graficos_export', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FINANCEIRO — GRÁFICOS E INDICADORES")
        self.assertContains(response, "window.print()")

    def test_relatorio_financeiro_pdf_view_all_types(self):
        self.client.login(username="produtor_fin", password="password123")
        report_types = ['resumo', 'a_receber', 'recebimentos', 'resultado_show', 'fechamento']

        for r_type in report_types:
            url = f"{reverse('relatorio_financeiro_pdf', args=[self.band.slug])}?report_type={r_type}&date_start=2026-09-01&date_end=2026-09-30"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"Falha no tipo de relatório {r_type}")
            self.assertContains(response, "Banda Teste")
            self.assertContains(response, "window.print()")
            # Valida badge padronizada de 72px
            self.assertContains(response, "width: 72px;")

    def test_relatorio_cards_zero_formatting(self):
        # Para a outra banda sem shows nem valores, os cards devem exibir R$ 0,00 e não apenas R$
        self.client.login(username="produtor_fin", password="password123")
        # Vincular produtor na outra banda
        UserBandMembership.objects.create(
            user=self.produtor,
            band=self.other_band,
            role="PRODUTOR",
            is_active=True
        )
        url = f"{reverse('relatorio_financeiro_pdf', args=[self.other_band.slug])}?report_type=resumo"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Deve exibir R$ 0,00 no card Em Atraso e Faturamento
        self.assertContains(response, "R$ 0,00")
        self.assertNotContains(response, '<div class="kpi-mini-value text-danger">R$ </div>')

    def test_relatorio_a_receber_consistency_with_synthetic_item(self):
        # Cria um show com fee mas sem nenhum ShowPayment cadastrado
        Show.objects.create(
            band=self.band,
            title="Show Sem Pagamentos Cadastrados",
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 25),
            fee=Decimal('5000.00'),
            payment_status='PENDENTE'
        )
        self.client.login(username="produtor_fin", password="password123")
        url = f"{reverse('relatorio_financeiro_pdf', args=[self.band.slug])}?report_type=a_receber&date_start=2026-09-01&date_end=2026-09-30"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Deve listar tanto a parcela pendente do show 1 quanto o cachê a faturar do show 2
        self.assertContains(response, "Restante")
        self.assertContains(response, "Cachê a receber (a faturar)")
        # Total a receber deve ser 6.000 + 5.000 = 11.000,00
        self.assertContains(response, "11.000,00")

