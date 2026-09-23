import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Band, BandSubscription, User


class IdentificarCobrancaAsaasAdminTests(TestCase):
    """
    Testes focados para a funcionalidade 'Identificar cobrança Asaas' no Painel Admin Geral:
    1. Três bandas da mesma cliente com o mesmo valor e IDs distintos: ao consultar cada pay_...,
       identifica com exatidão a banda e assinatura corretas.
    2. Cobrança sem vínculo comprovado no banco local ou inexistente no gateway:
       retorna 'Vínculo não identificado' e não sugere banda.
    3. Bloqueio de acesso para usuários não autorizados (não logado ou usuário sem privilégio de superuser).
    4. Pesquisa pelo ID da assinatura Asaas na listagem de assinaturas (AdminAssinaturasView).
    """

    def setUp(self):
        self.client = Client()

        # Superusuário (Admin Geral)
        self.admin = User.objects.create_superuser(
            username='admin_geral',
            email='admin@backstagepro.com.br',
            password='admin_password_123'
        )

        # Usuário Comum (não admin geral)
        self.user_regular = User.objects.create_user(
            username='usuario_comum',
            email='comum@email.com',
            password='user_password_123'
        )

        # Três bandas distintas da mesma empresária com mesmo plano e valor contratado (R$ 49,90)
        self.band_luisinho = Band.objects.create(name='Luisinho Vaqueiro', slug='luisinho-vaqueiro')
        self.band_ph10 = Band.objects.create(name='Ph10', slug='ph10')
        self.band_ruan = Band.objects.create(name='Ruan Vitor Vaqueirinho', slug='ruan-vitor-vaqueirinho')

        # Assinatura 1
        self.sub_luisinho = BandSubscription.objects.create(
            band=self.band_luisinho,
            plan_name='Avançado',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            commercial_condition='PAGO',
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_luisinho_111',
            gateway_external_reference='bp-ord-luisinho-111',
            financial_responsible_name='Empresária Responsável',
            billing_email='empresaria@email.com'
        )

        # Assinatura 2
        self.sub_ph10 = BandSubscription.objects.create(
            band=self.band_ph10,
            plan_name='Avançado',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            commercial_condition='PAGO',
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_ph10_222',
            gateway_external_reference='bp-ord-ph10-222',
            financial_responsible_name='Empresária Responsável',
            billing_email='empresaria@email.com'
        )

        # Assinatura 3
        self.sub_ruan = BandSubscription.objects.create(
            band=self.band_ruan,
            plan_name='Avançado',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            commercial_condition='PAGO',
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_ruan_333',
            gateway_external_reference='bp-ord-ruan-333',
            financial_responsible_name='Empresária Responsável',
            billing_email='empresaria@email.com'
        )

    @patch('core.services.payments.asaas.client.AsaasClient.get_payment')
    def test_01_identifica_corretamente_cada_banda_da_mesma_cliente_sem_ambiguidade(self, mock_get_payment):
        """
        Ao consultar o ID de cada cobrança pay_..., o endpoint busca na API Asaas,
        obtém a assinatura sub_... e identifica unicamente a banda correta.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_identificar_cobranca')

        # Mock para cobranca 1 (Luisinho Vaqueiro)
        mock_get_payment.return_value = {
            'id': 'pay_luisinho_991',
            'subscription': 'sub_luisinho_111',
            'value': 49.90,
            'status': 'RECEIVED'
        }
        resp1 = self.client.post(url, {'payment_id': 'pay_luisinho_991'})
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertTrue(data1['ok'])
        self.assertEqual(data1['status'], 'Comprovado')
        self.assertEqual(data1['band']['name'], 'Luisinho Vaqueiro')
        self.assertEqual(data1['subscription_id'], 'sub_luisinho_111')

        # Mock para cobranca 2 (Ph10)
        mock_get_payment.return_value = {
            'id': 'pay_ph10_992',
            'subscription': 'sub_ph10_222',
            'value': 49.90,
            'status': 'CONFIRMED'
        }
        resp2 = self.client.post(url, {'payment_id': 'pay_ph10_992'})
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2['ok'])
        self.assertEqual(data2['status'], 'Comprovado')
        self.assertEqual(data2['band']['name'], 'Ph10')
        self.assertEqual(data2['subscription_id'], 'sub_ph10_222')

        # Mock para cobranca 3 (Ruan Vitor Vaqueirinho)
        mock_get_payment.return_value = {
            'id': 'pay_ruan_993',
            'subscription': 'sub_ruan_333',
            'value': 49.90,
            'status': 'RECEIVED'
        }
        resp3 = self.client.post(url, {'payment_id': 'pay_ruan_993'})
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.json()
        self.assertTrue(data3['ok'])
        self.assertEqual(data3['status'], 'Comprovado')
        self.assertEqual(data3['band']['name'], 'Ruan Vitor Vaqueirinho')
        self.assertEqual(data3['subscription_id'], 'sub_ruan_333')

    @patch('core.services.payments.asaas.client.AsaasClient.get_payment')
    def test_02_cobranca_sem_vinculo_retorna_nao_identificado_e_nao_sugere_banda(self, mock_get_payment):
        """
        Se a cobrança não tiver assinatura de origem ou pertencer a um sub_id não registrado
        no banco local, retorna 'Vínculo não identificado' e não traz dados de banda.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_identificar_cobranca')

        # Caso A: Cobrança sem subscription_id (ex: cobrança avulsa)
        mock_get_payment.return_value = {
            'id': 'pay_avulso_123',
            'subscription': None,
            'value': 49.90
        }
        resp = self.client.post(url, {'payment_id': 'pay_avulso_123'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['status'], 'Vínculo não identificado')
        self.assertNotIn('band', data)

        # Caso B: Cobrança com subscription_id desconhecido no sistema
        mock_get_payment.return_value = {
            'id': 'pay_desconhecido_456',
            'subscription': 'sub_inexistente_999',
            'value': 49.90
        }
        resp_b = self.client.post(url, {'payment_id': 'pay_desconhecido_456'})
        self.assertEqual(resp_b.status_code, 200)
        data_b = resp_b.json()
        self.assertFalse(data_b['ok'])
        self.assertEqual(data_b['status'], 'Vínculo não identificado')
        self.assertNotIn('band', data_b)

        # Caso C: Cobrança não encontrada no Asaas (retorna None)
        mock_get_payment.return_value = None
        resp_c = self.client.post(url, {'payment_id': 'pay_nao_existe_000'})
        self.assertEqual(resp_c.status_code, 200)
        data_c = resp_c.json()
        self.assertFalse(data_c['ok'])
        self.assertEqual(data_c['status'], 'Vínculo não identificado')
        self.assertNotIn('band', data_c)

    def test_03_bloqueio_de_acesso_para_usuarios_nao_autorizados(self):
        """Usuários anônimos ou não administradores gerais não podem acessar a consulta."""
        url = reverse('admin_painel:assinaturas_identificar_cobranca')

        # Usuário anônimo deve ser redirecionado para login
        resp_anon = self.client.post(url, {'payment_id': 'pay_test_123'})
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/admin-master/login/', resp_anon.url)

        # Usuário comum (não superuser) deve ser bloqueado
        self.client.force_login(self.user_regular)
        resp_user = self.client.post(url, {'payment_id': 'pay_test_123'})
        self.assertEqual(resp_user.status_code, 302)
        self.assertIn('/admin-master/login/', resp_user.url)

    def test_04_pesquisa_por_id_da_assinatura_asaas_na_listagem(self):
        """
        O filtro de pesquisa 'q' na tela de Assinaturas deve encontrar registros
        pelo gateway_subscription_id e gateway_external_reference.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas')

        # Buscar pelo ID Asaas do Luisinho
        resp = self.client.get(url, {'q': 'sub_luisinho_111'})
        self.assertEqual(resp.status_code, 200)
        subs = list(resp.context['assinaturas'])
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].band.name, 'Luisinho Vaqueiro')

        # Buscar pelo ID Asaas do Ph10
        resp2 = self.client.get(url, {'q': 'sub_ph10_222'})
        self.assertEqual(resp2.status_code, 200)
        subs2 = list(resp2.context['assinaturas'])
        self.assertEqual(len(subs2), 1)
        self.assertEqual(subs2[0].band.name, 'Ph10')

        # Buscar pela referência externa do Ruan
        resp3 = self.client.get(url, {'q': 'bp-ord-ruan-333'})
        self.assertEqual(resp3.status_code, 200)
        subs3 = list(resp3.context['assinaturas'])
        self.assertEqual(len(subs3), 1)
        self.assertEqual(subs3[0].band.name, 'Ruan Vitor Vaqueirinho')

    @patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_subscription')
    def test_05_identifica_cobranca_por_numero_da_fatura_exato(self, mock_get_sub_payments):
        """
        Ao informar o número da fatura (ex: '91758949' ou '917589949'), o endpoint consulta
        as cobranças de cada uma das assinaturas Asaas, compara invoiceNumber exatamente e
        identifica a banda única comprovada.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_identificar_cobranca')

        # Mock das 3 assinaturas retornando cobranças distintas com invoiceNumber
        def side_effect(sub_id, limit=50, fetch_all=True):
            if sub_id == 'sub_luisinho_111':
                return [{
                    'id': 'pay_luisinho_991',
                    'subscription': 'sub_luisinho_111',
                    'invoiceNumber': '917589949',
                    'status': 'CONFIRMED',
                    'value': 49.90
                }]
            elif sub_id == 'sub_ph10_222':
                return [{
                    'id': 'pay_ph10_992',
                    'subscription': 'sub_ph10_222',
                    'invoiceNumber': '917582370',
                    'status': 'CONFIRMED',
                    'value': 49.90
                }]
            elif sub_id == 'sub_ruan_333':
                return [{
                    'id': 'pay_ruan_993',
                    'subscription': 'sub_ruan_333',
                    'invoiceNumber': '917578101',
                    'status': 'CONFIRMED',
                    'value': 49.90
                }]
            return []

        mock_get_sub_payments.side_effect = side_effect

        # Consulta pela fatura do Luisinho
        resp = self.client.post(url, {'payment_id': '917589949'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'Comprovado')
        self.assertEqual(data['band']['name'], 'Luisinho Vaqueiro')
        self.assertEqual(data['payment_id'], 'pay_luisinho_991')
        self.assertEqual(data['subscription_id'], 'sub_luisinho_111')
        self.assertEqual(data['invoice_number'], '917589949')

        # Consulta pela fatura da Ph10
        resp_ph = self.client.post(url, {'payment_id': '917582370'})
        self.assertEqual(resp_ph.status_code, 200)
        data_ph = resp_ph.json()
        self.assertTrue(data_ph['ok'])
        self.assertEqual(data_ph['status'], 'Comprovado')
        self.assertEqual(data_ph['band']['name'], 'Ph10')
        self.assertEqual(data_ph['payment_id'], 'pay_ph10_992')
        self.assertEqual(data_ph['subscription_id'], 'sub_ph10_222')

        # Consulta por fatura inexistente
        resp_none = self.client.post(url, {'payment_id': '999999999'})
        self.assertEqual(resp_none.status_code, 200)
        data_none = resp_none.json()
        self.assertFalse(data_none['ok'])
        self.assertEqual(data_none['status'], 'Vínculo não identificado')

    @patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_subscription')
    def test_06_ver_cobrancas_banda_asaas(self, mock_get_sub_payments):
        """
        Endpoint 'Ver cobranças Asaas' retorna a lista de cobranças com ID e número da fatura.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_ver_cobrancas_asaas', kwargs={'subscription_id': self.sub_luisinho.id})

        mock_get_sub_payments.return_value = [
            {
                'id': 'pay_luisinho_991',
                'subscription': 'sub_luisinho_111',
                'invoiceNumber': '917589949',
                'value': 49.90,
                'status': 'CONFIRMED',
                'dueDate': '2026-09-23',
                'invoiceUrl': 'https://www.asaas.com/i/pay_luisinho_991'
            }
        ]

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['band_name'], 'Luisinho Vaqueiro')
        self.assertEqual(data['total_payments'], 1)
        self.assertEqual(data['payments'][0]['invoice_number'], '917589949')
        self.assertEqual(data['payments'][0]['id'], 'pay_luisinho_991')
