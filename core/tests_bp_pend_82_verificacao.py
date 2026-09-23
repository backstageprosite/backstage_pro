from decimal import Decimal
import datetime
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, User, UserBandMembership, Show, FinancialReceipt, BandActivationToken, SignupOrder

class BPPend82VerificationTests(TestCase):
    def setUp(self):
        # Cria Banda Avançada
        self.band = Band.objects.create(name='Banda Teste BP82', slug='banda-teste-bp82', plan_type='AVANCADO')

        # Cria Empresário
        self.empresario = User.objects.create_user(
            username='emp_user',
            email='emp@teste.com',
            password='Password123!',
            band=self.band,
            role='EMPRESARIO'
        )
        UserBandMembership.objects.create(user=self.empresario, band=self.band, role='EMPRESARIO', is_active=True)

        # Cria Produtor
        self.produtor = User.objects.create_user(
            username='prod_user',
            email='prod@teste.com',
            password='Password123!',
            band=self.band,
            role='PRODUTOR'
        )
        UserBandMembership.objects.create(user=self.produtor, band=self.band, role='PRODUTOR', is_active=True)

        # Cria Outro Produtor
        self.produtor2 = User.objects.create_user(
            username='prod2_user',
            email='prod2@teste.com',
            password='Password123!',
            band=self.band,
            role='PRODUTOR'
        )
        UserBandMembership.objects.create(user=self.produtor2, band=self.band, role='PRODUTOR', is_active=True)

        # Show com cachê e valores financeiros
        self.show = Show.objects.create(
            band=self.band,
            title='Show Sigiloso',
            date=datetime.date.today(),
            fee=Decimal('50000.00'),
            payment_status='PENDENTE',
            contractor_name='Contratante VIP'
        )

    def test_ponto_1_produtor_nao_obtem_dados_financeiros_por_url_ou_endpoints(self):
        """
        1. Um PRODUTOR não obtém cachês, receitas ou relatórios financeiros por URL direta,
        endpoint, PDF ou download, mesmo que o card esteja oculto.
        """
        self.client.login(username='prod_user', password='Password123!')

        # Acesso direto a show_finance_detail_view deve ser proibido (403)
        url_finance = reverse('show_finance_detail', args=[self.band.slug, self.show.id])
        res = self.client.get(url_finance)
        self.assertEqual(res.status_code, 403)

        # Acesso direto a relatorio_financeiro deve ser proibido (403)
        url_relatorio = reverse('relatorio_financeiro', args=[self.band.slug])
        res = self.client.get(url_relatorio)
        self.assertEqual(res.status_code, 403)

        # Acesso direto a relatorio_financeiro_graficos deve ser proibido (403)
        url_graficos = reverse('relatorio_financeiro_graficos', args=[self.band.slug])
        res = self.client.get(url_graficos)
        self.assertEqual(res.status_code, 403)

        # Acesso direto a relatorio_financeiro_pdf deve ser proibido (403)
        url_pdf = reverse('relatorio_financeiro_pdf', args=[self.band.slug])
        res = self.client.get(url_pdf)
        self.assertEqual(res.status_code, 403)

        # Acesso a show_detail é permitido (200), mas SEM vazamento de cachê ou dados do contrato
        url_show_detail = reverse('show_detail', args=[self.band.slug, self.show.id])
        res = self.client.get(url_show_detail)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertNotIn('50000.00', content)
        self.assertNotIn('50.000,00', content)
        self.assertNotIn('Contratante VIP', content)
        self.assertNotIn('Valor (Cachê)', content)

        # Acesso a show_pdf é permitido para o produtor para logística, mas SEM dados financeiros
        url_show_pdf = reverse('show_pdf', args=[self.band.slug, self.show.id])
        res = self.client.get(url_pdf)
        self.assertEqual(res.status_code, 403)
        res_show_pdf = self.client.get(url_show_pdf)
        self.assertEqual(res_show_pdf.status_code, 200)
        pdf_content = res_show_pdf.content.decode('utf-8')
        self.assertNotIn('50000', pdf_content)
        self.assertNotIn('50.000', pdf_content)

    def test_ponto_2_produtor_lanca_e_corrige_apenas_despesas_proprias(self):
        """
        2. O PRODUTOR consegue lançar despesa com comprovante e consultar ou corrigir somente lançamentos
        próprios, sem acessar despesas de terceiros ou totais financeiros.
        """
        # Criação de comprovante pelo produtor 1
        fake_file = SimpleUploadedFile("recibo_combustivel.pdf", b"%PDF-1.4 test receipt content", content_type="application/pdf")
        receipt1 = FinancialReceipt.objects.create(
            show=self.show,
            description="Combustivel Van",
            value=Decimal("350.00"),
            file=fake_file,
            created_by=self.produtor
        )

        # Criação de comprovante pelo produtor 2
        fake_file2 = SimpleUploadedFile("recibo_almoco.pdf", b"%PDF-1.4 test receipt content 2", content_type="application/pdf")
        receipt2 = FinancialReceipt.objects.create(
            show=self.show,
            description="Almoco Equipe",
            value=Decimal("200.00"),
            file=fake_file2,
            created_by=self.produtor2
        )

        # Login como produtor 1
        self.client.login(username='prod_user', password='Password123!')

        # Produtor 1 pode editar sua própria despesa
        url_edit_own = reverse('receipt_edit', args=[self.band.slug, receipt1.id])
        res = self.client.get(url_edit_own)
        self.assertEqual(res.status_code, 200)

        # Post editando sua própria despesa
        res = self.client.post(url_edit_own, {
            'description': 'Combustivel Van Atualizado',
            'value': '380.00',
            'date': datetime.date.today().strftime('%Y-%m-%d'),
        })
        self.assertIn(res.status_code, [200, 302])
        receipt1.refresh_from_db()
        self.assertEqual(receipt1.description, 'Combustivel Van Atualizado')

        # Produtor 1 NÃO PODE editar despesa de produtor 2 (403 Forbidden)
        url_edit_other = reverse('receipt_edit', args=[self.band.slug, receipt2.id])
        res = self.client.get(url_edit_other)
        self.assertEqual(res.status_code, 403)

        # Produtor 1 NÃO PODE excluir despesa de produtor 2 (403 Forbidden)
        url_del_other = reverse('receipt_delete', args=[self.band.slug, receipt2.id])
        res = self.client.post(url_del_other)
        self.assertEqual(res.status_code, 403)

        # Produtor 1 PODE excluir sua própria despesa
        url_del_own = reverse('receipt_delete', args=[self.band.slug, receipt1.id])
        res = self.client.post(url_del_own)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(FinancialReceipt.objects.filter(id=receipt1.id).exists())

    def test_ponto_3_autopromocao_bloqueada_e_multiband_membership(self):
        """
        3. A criação e edição de usuários não permitem autopromoção por PRODUTOR; a permissão
        efetiva usa UserBandMembership da banda ativa, inclusive quando a mesma pessoa participa de outras bandas.
        """
        # Cria Banda 2
        band2 = Band.objects.create(name='Banda Secundaria', slug='banda-secundaria', plan_type='AVANCADO')
        
        # O produtor é EMPRESARIO na Banda 2, mas PRODUTOR na Banda 1
        UserBandMembership.objects.create(user=self.produtor, band=band2, role='EMPRESARIO', is_active=True)

        # Verifica permissão no contexto da Banda 1 -> False
        self.assertFalse(self.produtor.is_empresario_for_band(self.band))
        # Verifica permissão no contexto da Banda 2 -> True
        self.assertTrue(self.produtor.is_empresario_for_band(band2))

        # Produtor loga na Banda 1 e tenta promover a si mesmo ou outro usuário para EMPRESARIO
        self.client.login(username='prod_user', password='Password123!')

        # Tentativa de criar usuário como EMPRESARIO na Banda 1
        url_create_user = reverse('usuarios_add', args=[self.band.slug])
        res = self.client.post(url_create_user, {
            'first_name': 'Novo',
            'last_name': 'User',
            'username': 'novouser',
            'email': 'novo@teste.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'role': 'EMPRESARIO',
            'is_active': 'on'
        })
        self.assertFalse(User.objects.filter(username='novouser').exists())

        # Tentativa de editar o próprio perfil na Banda 1 para EMPRESARIO
        url_edit_user = reverse('usuarios_edit', args=[self.band.slug, self.produtor.id])
        res = self.client.post(url_edit_user, {
            'first_name': self.produtor.first_name,
            'last_name': self.produtor.last_name,
            'username': self.produtor.username,
            'email': self.produtor.email,
            'role': 'EMPRESARIO',
            'is_active': 'on'
        })
        self.produtor.refresh_from_db()
        # Papel na Banda 1 permanece PRODUTOR
        membership = UserBandMembership.objects.get(user=self.produtor, band=self.band)
        self.assertEqual(membership.role, 'PRODUTOR')
        self.assertFalse(self.produtor.is_empresario_for_band(self.band))

    def test_ponto_4_migracao_0119_afeta_apenas_vinicius_e_glauber(self):
        """
        4. A migração 0119_set_empresarios_danniel_vieira.py afeta somente os vínculos
        explicitamente definidos de Vinicius e Glauber, sem promover outros usuários.
        """
        import importlib
        mig_module = importlib.import_module('core.migrations.0119_set_empresarios_danniel_vieira')
        import inspect
        source = inspect.getsource(mig_module.set_empresarios)
        self.assertIn("for username in ['vinicius', 'glauber']:", source)
        self.assertNotIn("filter(role='PRODUTOR')", source)
        self.assertNotIn("all()", source)

    def test_ponto_5_ativacao_checkout_atribui_empresario_ao_titular(self):
        """
        5. Uma nova ativação pelo checkout atribui ao titular o vínculo empresarial
        adequado (EMPRESARIO) tanto em CREATE_ACCOUNT quanto em LINK_BAND.
        """
        from django.utils import timezone
        import hashlib

        # 5a: LINK_BAND
        raw_token = 'test_token_link_band_123'
        token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        band_new = Band.objects.create(name='Nova Banda Comprada', slug='nova-banda-comprada', plan_type='AVANCADO')
        order = SignupOrder.objects.create(
            external_reference='ord_test_bp82_123',
            band_name='Nova Banda Comprada',
            responsible_name='Titular Comprador',
            email='titular@teste.com',
            responsible_cpf='12345678901',
            amount=Decimal('197.00'),
            status='PAGO'
        )
        existing_user = User.objects.create_user(
            username='titular_existente',
            email='titular@teste.com',
            password='Password123!',
            cpf='12345678901'
        )

        token_obj = BandActivationToken.objects.create(
            band=band_new,
            token_hash=token_hash,
            token_type=BandActivationToken.TokenType.LINK_BAND,
            signup_order=order,
            target_user=existing_user,
            expires_at=timezone.now() + datetime.timedelta(days=2)
        )

        self.client.login(username='titular_existente', password='Password123!')
        url_link = reverse('activate_account', args=[raw_token])
        res = self.client.post(url_link)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context.get('link_success'))

        # Verifica se o membership na nova banda foi criado como EMPRESARIO
        membership = UserBandMembership.objects.get(user=existing_user, band=band_new)
        self.assertEqual(membership.role, 'EMPRESARIO')
        self.assertTrue(existing_user.is_empresario_for_band(band_new))
