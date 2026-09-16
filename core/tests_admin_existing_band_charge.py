import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Band, BandSubscription, BillingRecord, SignupOrder,
    BandActivationToken, EmailDelivery, SystemSettings, User
)
from core.services.payments.provisioning import process_checkout_paid_event


class AdminExistingBandChargeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = SystemSettings.get_settings()
        self.settings.plan_basic_monthly = Decimal('19.90')
        self.settings.plan_basic_annual = Decimal('199.90')
        self.settings.plan_advanced_monthly = Decimal('49.90')
        self.settings.plan_advanced_annual = Decimal('499.90')
        self.settings.save()

        # Admin geral
        self.admin = User.objects.create_superuser(
            username='admin_geral',
            email='admin@backstagepro.com.br',
            password='admin_password_123'
        )

        # Banda existente cadastrada (is_active=True por padrão, mas sem BandSubscription)
        self.band = Band.objects.create(
            name='Banda Rock Star',
            slug='banda-rock-star',
            plan_type='BASICO',
            is_active=True
        )
        self.produtor = User.objects.create_user(
            username='produtor_rock',
            email='produtor@rockstar.com',
            password='prod_pass_123',
            band=self.band,
            role='PRODUTOR',
            phone='71988887777',
            first_name='Carlos',
            last_name='Silva'
        )

    def test_01_non_admin_cannot_access_create_charge(self):
        "Usuários não administradores não podem acessar a rota de criação de cobrança."
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})
        resp = self.client.post(url, data={})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin-master/login/', resp.url)

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_02_admin_can_generate_charge_for_existing_band_with_canonical_price(self, mock_checkout):
        "Admin geral pode gerar cobrança com preço canônico para banda existente."
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})

        mock_checkout.return_value = (
            True,
            'https://sandbox.asaas.com/checkout/chk_test_123',
            {'id': 'chk_test_123', 'paymentLink': 'https://sandbox.asaas.com/checkout/chk_test_123'},
            None
        )

        data = {
            'plan_type': 'AVANCADO',
            'billing_cycle': 'ANUAL',
            'payment_method': 'CREDIT_CARD',
            'responsible_name': 'Carlos Silva',
            'email': 'produtor@rockstar.com',
            'phone': '71988887777',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json()
        self.assertTrue(res_json['ok'])
        self.assertEqual(res_json['checkout_url'], 'https://sandbox.asaas.com/checkout/chk_test_123')
        self.assertEqual(res_json['amount'], '499,90')

        # Verificar criação do SignupOrder vinculado à banda existente
        order = SignupOrder.objects.filter(band=self.band).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.plan_type, 'AVANCADO')
        self.assertEqual(order.billing_cycle, 'ANUAL')
        self.assertEqual(order.amount, Decimal('499.90'))
        self.assertEqual(order.email, 'produtor@rockstar.com')
        self.assertEqual(order.band, self.band)

        # Testar backward compatibility de Band.signup_order
        self.assertEqual(self.band.signup_order, order)

    def test_03_warning_when_band_already_has_active_subscription_without_confirm_override(self):
        "Deve exigir confirmação se a banda já possuir uma assinatura ativa."
        self.client.force_login(self.admin)

        # Cria assinatura ativa para a banda
        BandSubscription.objects.create(
            band=self.band,
            status='ATIVO',
            plan_name='Avançado',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            start_date=timezone.localdate(),
            next_due_date=timezone.localdate() + timezone.timedelta(days=30)
        )
        self.band.is_active = True
        self.band.save()

        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})
        data = {
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        res_json = resp.json()
        self.assertFalse(res_json['ok'])
        self.assertTrue(res_json.get('warning_active'))

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_04_override_allows_charge_generation_for_active_band(self, mock_checkout):
        "Com confirm_override=1, permite gerar cobrança mesmo com assinatura ativa."
        self.client.force_login(self.admin)

        BandSubscription.objects.create(
            band=self.band,
            status='ATIVO',
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=timezone.localdate(),
            next_due_date=timezone.localdate() + timezone.timedelta(days=30)
        )
        self.band.is_active = True
        self.band.save()

        mock_checkout.return_value = (
            True,
            'https://sandbox.asaas.com/checkout/chk_override_456',
            {'id': 'chk_override_456'},
            None
        )

        url = reverse('admin_painel:bandas_criar_cobranca', kwargs={'pk': self.band.pk})
        data = {
            'plan_type': 'AVANCADO',
            'billing_cycle': 'ANUAL',
            'confirm_override': '1',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json()
        self.assertTrue(res_json['ok'])

    def test_05_webhook_checkout_paid_for_existing_band_updates_subscription_without_new_band_or_activation(self):
        """
        Ao processar CHECKOUT_PAID para ordem com banda existente:
        - NÃO cria nova Band.
        - Atualiza o plano e status da Band existente para ativo.
        - Atualiza/cria BandSubscription como ATIVO.
        - Cria BillingRecord como PAGO.
        - NÃO cria BandActivationToken.
        - NÃO enfileira e-mail ACCOUNT_ACTIVATION.
        """
        # Criar ordem prévia associada à banda existente
        order = SignupOrder.objects.create(
            band=self.band,
            external_reference=f"bp-adm-{self.band.id}-test05",
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_paid_exist_123',
            band_name=self.band.name,
            responsible_name='Carlos Silva',
            email='produtor@rockstar.com',
            phone='71988887777',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE'
        )

        bands_count_before = Band.objects.count()
        users_count_before = User.objects.count()
        tokens_count_before = BandActivationToken.objects.count()
        emails_count_before = EmailDelivery.objects.filter(email_type='ACCOUNT_ACTIVATION').count()

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_paid_exist_123',
                'externalReference': order.external_reference,
                'status': 'PAID',
            },
            'payment': {
                'id': 'pay_exist_123',
                'status': 'CONFIRMED',
                'billingType': 'CREDIT_CARD',
                'value': 499.90,
                'confirmedDate': '2026-09-16'
            }
        }

        success, msg, returned_band = process_checkout_paid_event(payload, gateway_event_id='evt_adm_test_05')

        self.assertTrue(success)
        self.assertEqual(returned_band.id, self.band.id)

        # 1. Nenhuma nova Band ou User foi criado
        self.assertEqual(Band.objects.count(), bands_count_before)
        self.assertEqual(User.objects.count(), users_count_before)

        # 2. A banda existente foi ativada e atualizada para AVANCADO
        self.band.refresh_from_db()
        self.assertTrue(self.band.is_active)
        self.assertEqual(self.band.plan_type, 'AVANCADO')
        self.assertEqual(self.band.subscription_status, 'CONFIRMADO')

        # 3. BandSubscription criada/atualizada com sucesso
        sub = BandSubscription.objects.filter(band=self.band).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, 'ATIVO')
        self.assertEqual(sub.plan_name, 'Avançado')
        self.assertEqual(sub.billing_cycle, 'ANUAL')
        self.assertEqual(sub.contracted_value, Decimal('499.90'))

        # 4. BillingRecord liquidado
        record = BillingRecord.objects.filter(band=self.band, status='PAGO').first()
        self.assertIsNotNone(record)
        self.assertEqual(record.amount, Decimal('499.90'))

        # 5. SEM token de ativação e SEM e-mail de ativação de conta
        self.assertEqual(BandActivationToken.objects.count(), tokens_count_before)
        self.assertEqual(EmailDelivery.objects.filter(email_type='ACCOUNT_ACTIVATION').count(), emails_count_before)

        # 6. Status da ordem
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAGO')

        # 7. Idempotência: reprocessar o mesmo evento
        re_success, re_msg, re_band = process_checkout_paid_event(payload, gateway_event_id='evt_adm_test_05_dup')
        self.assertTrue(re_success)
        self.assertEqual(re_msg, 'JA_PROVISIONADO')
        self.assertEqual(Band.objects.count(), bands_count_before)

    def test_06_public_checkout_paid_still_creates_new_band_and_activation(self):
        """Garante que a ordem pública original (sem band vinculada) continua criando nova banda e token."""
        order = SignupOrder.objects.create(
            band=None,
            external_reference=f"bp-pub-{uuid.uuid4().hex[:8]}",
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_pub_456',
            band_name='Nova Banda Indie',
            responsible_name='Lucas Indie',
            email='lucas@indieband.com',
            phone='71999990000',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE'
        )

        bands_before = Band.objects.count()
        tokens_before = BandActivationToken.objects.count()

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_pub_456',
                'externalReference': order.external_reference,
            },
            'payment': {
                'id': 'pay_pub_456',
                'status': 'CONFIRMED',
                'billingType': 'PIX',
                'value': 19.90,
                'confirmedDate': '2026-09-16'
            }
        }

        success, msg, new_band = process_checkout_paid_event(payload, gateway_event_id='evt_pub_test_06')
        self.assertTrue(success)
        self.assertEqual(Band.objects.count(), bands_before + 1)
        self.assertEqual(new_band.name, 'Nova Banda Indie')

        # Para nova banda, o token de ativação é gerado
        self.assertEqual(BandActivationToken.objects.count(), tokens_before + 1)

    @patch('core.services.payments.checkout.create_asaas_checkout_for_signup_order')
    def test_07_assinaturas_gerar_cobranca_with_band_id_and_whatsapp_payload(self, mock_checkout):
        """
        Gera cobrança via endpoint 'assinaturas_gerar_cobranca' passando band_id no POST.
        Verifica se o retorno inclui dados de WhatsApp formatados corretamente.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas_gerar_cobranca')

        mock_checkout.return_value = (
            True,
            'https://sandbox.asaas.com/checkout/chk_wa_test',
            {'id': 'chk_wa_test'},
            None
        )

        data = {
            'band_id': self.band.id,
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
            'responsible_name': 'Carlos Silva',
            'email': 'produtor@rockstar.com',
            'phone': '71988887777',
            'format': 'json'
        }

        resp = self.client.post(url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json()
        self.assertTrue(res_json['ok'])
        self.assertIn('whatsapp', res_json)
        wa = res_json['whatsapp']
        self.assertTrue(wa['has_phone'])
        self.assertEqual(wa['phone_normalized'], '5571988887777')
        self.assertIn('Olá, Carlos Silva!', wa['message_text'])
        self.assertIn('Banda:* Banda Rock Star', wa['message_text'])
        self.assertIn('Plano:* AVANÇADO', wa['message_text'])
        self.assertIn('Ciclo:* MENSAL', wa['message_text'])
        self.assertIn('Valor:* R$ 49,90', wa['message_text'])
        self.assertIn('https://sandbox.asaas.com/checkout/chk_wa_test', wa['message_text'])
        self.assertIn('https://wa.me/5571988887777?text=', wa['whatsapp_mobile_url'])
        self.assertIn('whatsapp://send?phone=5571988887777&text=', wa['whatsapp_app_url'])
        self.assertIn('https://web.whatsapp.com/send?phone=5571988887777&text=', wa['whatsapp_web_url'])

    def test_08_whatsapp_message_exact_format_and_unicode_emojis(self):
        """Valida que build_whatsapp_charge_data gera a mensagem exata com todos os emojis e quebras de linha."""
        from core.views import build_whatsapp_charge_data
        from urllib.parse import unquote

        data = build_whatsapp_charge_data(
            responsible_name='João Silva',
            band_name='Banda Alfa',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount_str='199,90',
            checkout_url='https://asaas.com/c/12345',
            phone='(11) 98765-4321'
        )

        expected_text = (
            "Olá, João Silva! 👋\n\n"
            "Segue o link de pagamento referente à assinatura do Backstage Pro:\n\n"
            "🎤 *Banda:* Banda Alfa\n"
            "📦 *Plano:* BÁSICO\n"
            "🔄 *Ciclo:* ANUAL\n"
            "💰 *Valor:* R$ 199,90\n\n"
            "🔗 *Link para pagamento:*\n"
            "https://asaas.com/c/12345\n\n"
            "Após a confirmação do pagamento, a assinatura desta banda será atualizada automaticamente.\n\n"
            "Backstage Pro\n"
            "Gestão profissional para bandas e artistas."
        )

        self.assertEqual(data['message_text'], expected_text)
        self.assertEqual(data['phone_normalized'], '5511987654321')
        self.assertTrue(data['has_phone'])

        # Decodificar URL para assegurar que não houve dupla codificação ou quebra de emojis
        raw_query = data['whatsapp_mobile_url'].split('?text=')[1]
        decoded_query = unquote(raw_query)
        self.assertEqual(decoded_query, expected_text)

    def test_09_assinaturas_page_contains_gerar_cobranca_button_and_modal(self):
        """Verifica se a página de Assinaturas contém o botão Gerar Cobrança e o modal correspondente."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:assinaturas')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Gerar Cobrança', content)
        self.assertIn('Nova Assinatura', content)
        self.assertIn('id="modalChargeBand"', content)
        self.assertIn('id="modalWhatsappDesktopChoiceCharge"', content)
        self.assertIn('id="chargeSelectBand"', content)

    def test_10_bandas_page_does_not_contain_criar_cobranca_button(self):
        """Verifica que o botão Criar Cobrança foi removido da página Gestão de Bandas."""
        self.client.force_login(self.admin)
        url = reverse('admin_painel:bandas')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertNotIn('Criar Cobrança', content)
        self.assertNotIn('modalChargeBand', content)

