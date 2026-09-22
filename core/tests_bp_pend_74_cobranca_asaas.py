import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Band, BandSubscription, SignupOrder, SystemSettings, User
)


class BpPend74CobrancaAsaasTests(TestCase):
    """
    Testes específicos para BP-PEND-74:
    - Validação prévia de campos fiscais e endereço antes de invocar o Asaas.
    - Reutilização inteligente de Customer Asaas existente (sem duplicidades em retry).
    - Preenchimento completo de dados cadastrais e endereço no SignupOrder.
    - Tratamento amigável de erro HTTP 400 retornado pelo Asaas (sem erro 500).
    - Auto-preenchimento no contexto de assinaturas.
    """

    def setUp(self):
        self.client = Client()
        self.settings = SystemSettings.get_settings()
        self.settings.plan_basic_monthly = Decimal('19.90')
        self.settings.plan_basic_annual = Decimal('199.90')
        self.settings.plan_advanced_monthly = Decimal('49.90')
        self.settings.plan_advanced_annual = Decimal('499.90')
        self.settings.save()

        # Admin Geral
        self.admin = User.objects.create_superuser(
            username='admin_geral',
            email='admin@backstagepro.com.br',
            password='admin_password_123'
        )

        # Banda de Teste
        self.band = Band.objects.create(
            name='Banda Som & Luz',
            slug='banda-som-e-luz',
            plan_type='AVANCADO',
            is_active=True
        )

        self.produtor = User.objects.create_user(
            username='produtor_som',
            email='contato@someluz.com.br',
            password='prod_pass_123',
            band=self.band,
            role='PRODUTOR',
            phone='11988887777',
            first_name='Marcos',
            last_name='Oliveira',
            cpf='11144477735'
        )

    def test_01_missing_required_fields_blocks_before_calling_asaas(self):
        """Campos obrigatórios ausentes retornam HTTP 400 com erro amigável sem chamar Asaas."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})

        with patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order') as mock_checkout:
            # Enviando sem campos de endereço e sem cpf_cnpj
            data = {
                'plan_type': 'AVANCADO',
                'billing_cycle': 'MENSAL',
                'responsible_name': 'Marcos Oliveira',
                'email': 'contato@someluz.com.br',
                'phone': '11988887777',
                'format': 'json'
            }
            resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(resp.status_code, 400)
            res_json = resp.json()
            self.assertFalse(res_json['ok'])
            self.assertIn("campos obrigatórios não foram preenchidos", res_json['error'])
            self.assertIn("CEP", res_json['error'])
            self.assertIn("Endereço / Logradouro", res_json['error'])
            self.assertIn("Número", res_json['error'])
            self.assertIn("Bairro", res_json['error'])
            self.assertIn("Cidade", res_json['error'])
            mock_checkout.assert_not_called()

    def test_02_invalid_cpf_or_cnpj_format_blocks_with_400(self):
        """CPF ou CNPJ inválido retorna HTTP 400 sem chamar Asaas."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})

        with patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order') as mock_checkout:
            data = {
                'plan_type': 'AVANCADO',
                'billing_cycle': 'MENSAL',
                'responsible_name': 'Marcos Oliveira',
                'email': 'contato@someluz.com.br',
                'phone': '11988887777',
                'cpf_cnpj': '111.222.333-44',  # CPF inválido
                'postal_code': '01310-100',
                'address': 'Av. Paulista',
                'address_number': '1500',
                'province': 'Bela Vista',
                'city': 'São Paulo',
                'state': 'SP',
                'format': 'json'
            }
            resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(resp.status_code, 400)
            res_json = resp.json()
            self.assertFalse(res_json['ok'])
            self.assertIn("CPF informado é inválido", res_json['error'])
            mock_checkout.assert_not_called()

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_03_valid_fields_creates_signup_order_with_complete_address_and_fiscal(self, mock_checkout):
        """Com todos os dados válidos, cria o SignupOrder com endereço completo e gera checkout com sucesso."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_gerar_cobranca')

        mock_checkout.return_value = (
            True,
            'https://sandbox.asaas.com/c/cobranca_bp_74',
            {'id': 'chk_bp_74', 'paymentLink': 'https://sandbox.asaas.com/c/cobranca_bp_74'},
            None
        )

        data = {
            'band_id': self.band.id,
            'plan_type': 'AVANCADO',
            'billing_cycle': 'ANUAL',
            'responsible_name': 'Marcos Oliveira',
            'email': 'contato@someluz.com.br',
            'phone': '(11) 98888-7777',
            'cpf_cnpj': '11144477735',
            'postal_code': '01310-100',
            'address': 'Avenida Paulista',
            'address_number': '1578',
            'complement': 'Andar 10',
            'province': 'Bela Vista',
            'city': 'São Paulo',
            'state': 'SP',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json()
        self.assertTrue(res_json['ok'])
        self.assertEqual(res_json['checkout_url'], 'https://sandbox.asaas.com/c/cobranca_bp_74')
        self.assertEqual(res_json['amount'], '499,90')

        # Conferir SignupOrder persistido
        order = SignupOrder.objects.filter(band=self.band).order_by('-id').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.cpf_cnpj, '11144477735')
        self.assertEqual(order.postal_code, '01310-100')
        self.assertEqual(order.address, 'Avenida Paulista')
        self.assertEqual(order.address_number, '1578')
        self.assertEqual(order.complement, 'Andar 10')
        self.assertEqual(order.province, 'Bela Vista')
        self.assertEqual(order.city, 'São Paulo')
        self.assertEqual(order.state, 'SP')

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_04_reuses_existing_gateway_customer_id_on_new_charge(self, mock_checkout):
        """Reutiliza gateway_customer_id existente na assinatura ou ordem prévia da banda."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})

        # Criar assinatura prévia com gateway_customer_id
        BandSubscription.objects.create(
            band=self.band,
            plan_name='Avançado',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            gateway_customer_id='cus_prev_som_123',
            status='DESATIVADO'
        )

        mock_checkout.return_value = (
            True,
            'https://sandbox.asaas.com/c/reuse_cust_123',
            {'id': 'chk_reuse_123'},
            None
        )

        data = {
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
            'responsible_name': 'Marcos Oliveira',
            'email': 'contato@someluz.com.br',
            'phone': '11988887777',
            'cpf_cnpj': '11144477735',
            'postal_code': '01310-100',
            'address': 'Avenida Paulista',
            'address_number': '1578',
            'province': 'Bela Vista',
            'city': 'São Paulo',
            'state': 'sp',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)

        order = SignupOrder.objects.filter(band=self.band).order_by('-id').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.gateway_customer_id, 'cus_prev_som_123')

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_05_graceful_handling_of_asaas_error_returns_http_400_not_500(self, mock_checkout):
        """Erro 400 retornado pelo Asaas é tratado amigavelmente retornando JSON HTTP 400 sem crash 500."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})

        asaas_res_data = {
            'errors': [
                {'code': 'invalid_address', 'description': 'O endereço informado não foi localizado na base postal.'}
            ]
        }
        mock_checkout.return_value = (
            False,
            None,
            asaas_res_data,
            'O endereço informado não foi localizado na base postal.'
        )

        data = {
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
            'responsible_name': 'Marcos Oliveira',
            'email': 'contato@someluz.com.br',
            'phone': '11988887777',
            'cpf_cnpj': '11144477735',
            'postal_code': '01310-100',
            'address': 'Avenida Paulista',
            'address_number': '1578',
            'province': 'Bela Vista',
            'city': 'São Paulo',
            'state': 'SP',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        res_json = resp.json()
        self.assertFalse(res_json['ok'])
        self.assertIn("Asaas:", res_json['error'])
        self.assertIn("O endereço informado não foi localizado", res_json['error'])

        # SignupOrder deve estar marcado como FALHOU
        order = SignupOrder.objects.filter(band=self.band).order_by('-id').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.status, 'FALHOU')
