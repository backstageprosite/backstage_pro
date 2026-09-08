import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from core.models import (
    SignupOrder, Band, BandSubscription, BillingRecord,
    BandActivationToken, EmailDelivery, SystemSettings, User
)
from core.services.payments.asaas.client import PaymentsLiveDisabledError, AsaasClient
from core.services.payments.checkout import create_asaas_checkout_for_signup_order, build_checkout_payload
from core.services.payments.provisioning import process_checkout_paid_event


class LandingAndCheckoutIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client(headers={'host': 'localhost'})
        self.settings = SystemSettings.get_settings()
        self.settings.plan_basic_monthly = Decimal('19.90')
        self.settings.plan_basic_annual = Decimal('199.90')
        self.settings.plan_advanced_monthly = Decimal('49.90')
        self.settings.plan_advanced_annual = Decimal('499.90')
        self.settings.save()

    def test_01_landing_page_renders_200_and_contains_checkout_links(self):
        """1. Landing page deve carregar HTTP 200 e conter links para o fluxo de checkout."""
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('/assinar/?plano=basico&ciclo=mensal', content)
        self.assertIn('/assinar/?plano=avancado&ciclo=mensal', content)
        self.assertIn('btn-cta-basic', content)
        self.assertIn('btn-cta-advanced', content)

    def test_02_subscription_ctas_do_not_contain_whatsapp_links(self):
        """2. Os 4 CTAs de assinatura NÃO devem apontar para wa.me."""
        resp = self.client.get(reverse('home'))
        content = resp.content.decode('utf-8')
        self.assertNotIn('wa.me/5571983474004?text=Ol%C3%A1%21%20Tenho%20interesse%20no%20Plano%20B', content)
        self.assertNotIn('wa.me/5571983474004?text=Ol%C3%A1%21%20Tenho%20interesse%20no%20Plano%20Avan', content)

    def test_03_non_subscription_whatsapp_links_are_preserved(self):
        """3. Links legítimos de WhatsApp para suporte/contato no Hero e Footer permanecem intactos."""
        resp = self.client.get(reverse('home'))
        content = resp.content.decode('utf-8')
        self.assertIn('https://wa.me/5571983474004?text=Ol%C3%A1%21%20Conheci%20o%20Backstage%20Pro', content)
        self.assertIn('https://wa.me/5571983474004?text=Ol%C3%A1%21%20Gostaria%20de%20saber%20mais', content)

    def test_04_checkout_get_renders_with_canonical_pricing(self):
        """4. GET /assinar/ deve renderizar plano, ciclo e valor canônico sem confiar no cliente."""
        url_basic_monthly = reverse('checkout') + '?plano=basico&ciclo=mensal'
        resp = self.client.get(url_basic_monthly)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '19,90')
        self.assertContains(resp, 'Básico')
        self.assertContains(resp, 'Mensal')

        url_adv_annual = reverse('checkout') + '?plano=avancado&ciclo=anual'
        resp_adv = self.client.get(url_adv_annual)
        self.assertEqual(resp_adv.status_code, 200)
        self.assertContains(resp_adv, '499,90')
        self.assertContains(resp_adv, 'Avançado')
        self.assertContains(resp_adv, 'Anual')

    def test_05_checkout_post_validates_required_fields(self):
        """5. POST /assinar/ sem campos obrigatórios deve exibir erros e não criar SignupOrder."""
        resp = self.client.post(reverse('checkout'), data={
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
            'band_name': '',
            'responsible_name': '',
            'email': '',
            'phone': '',
            'cpf_cnpj': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Informe o nome da banda ou artista.')
        self.assertContains(resp, 'Informe um telefone ou WhatsApp para contato.')
        self.assertContains(resp, 'Informe um CPF ou CNPJ válido.')
        self.assertEqual(SignupOrder.objects.count(), 0)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_06_checkout_post_creates_signup_order_and_redirects_to_asaas(self, mock_create_chk):
        """6. POST /assinar/ válido deve criar SignupOrder PENDENTE e redirecionar para URL Asaas via AsaasClient."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_live_order_123',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/live_order_123'
        })

        resp = self.client.post(reverse('checkout'), data={
            'band_name': 'Banda Estrela Solar',
            'responsible_name': 'Marina Silva',
            'email': 'marina@estrelasolar.com',
            'phone': '71999887766',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://sandbox.asaas.com/c/live_order_123')
        self.assertEqual(mock_create_chk.call_count, 1)

        # Validar persistência do SignupOrder
        order = SignupOrder.objects.filter(email='marina@estrelasolar.com').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.band_name, 'Banda Estrela Solar')
        self.assertEqual(order.amount, Decimal('19.90'))
        self.assertEqual(order.status, 'PENDENTE')
        self.assertEqual(order.gateway_checkout_id, 'chk_live_order_123')
        self.assertIsNone(order.band)  # NÃO provisiona antes do pagamento
        self.assertFalse(User.objects.filter(email='marina@estrelasolar.com').exists())  # NÃO cria usuário

    @override_settings(PAYMENTS_LIVE_ENABLED=False, ASAAS_API_KEY='test_api_key')
    def test_07_safety_gate_blocks_live_checkout_when_live_disabled(self):
        """7. Safety gate central bloqueia criação real de checkout se PAYMENTS_LIVE_ENABLED=False."""
        resp = self.client.post(reverse('checkout'), data={
            'band_name': 'Banda Prova Seguranca',
            'responsible_name': 'Seguranca Silva',
            'email': 'seg@prova.com',
            'phone': '71999887766',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'ANUAL',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'PAYMENTS_LIVE_ENABLED=False')
        # Pedido existe como PENDENTE mas sem checkout gerado
        order = SignupOrder.objects.filter(email='seg@prova.com').first()
        self.assertIsNotNone(order)
        self.assertIsNone(order.gateway_checkout_id)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_08_annual_checkout_payload_structure_pix_and_card(self, mock_create_chk):
        """8. Payload anual deve conter PIX + CREDIT_CARD, INSTALLMENT com maxInstallmentCount=12 e valor integral."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_annual_999',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/annual999'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-test',
            gateway_provider='ASAAS',
            band_name='Banda Anual Teste',
            responsible_name='Roberto',
            email='roberto@teste.com',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE',
        )

        ok, link, data, err = create_asaas_checkout_for_signup_order(order)
        self.assertTrue(ok)
        self.assertEqual(link, 'https://sandbox.asaas.com/c/annual999')

        # Verificar payload enviado ao AsaasClient
        sent_payload = mock_create_chk.call_args[0][0]
        self.assertIn('PIX', sent_payload['billingTypes'])
        self.assertIn('CREDIT_CARD', sent_payload['billingTypes'])
        self.assertEqual(sent_payload['chargeTypes'], ['DETACHED', 'INSTALLMENT'])
        self.assertEqual(sent_payload['installment']['maxInstallmentCount'], 12)
        self.assertEqual(sent_payload['items'][0]['value'], 499.90)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_09_monthly_checkout_payload_structure_credit_card(self, mock_create_chk):
        """9. Payload mensal com cartão deve conter CREDIT_CARD, RECURRENT com subscription.cycle=MONTHLY e nextDueDate."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_monthly_777',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/monthly777'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-monthly-test',
            gateway_provider='ASAAS',
            band_name='Banda Mensal Teste',
            responsible_name='Lucas',
            email='lucas@teste.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, data, err = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)
        self.assertEqual(link, 'https://sandbox.asaas.com/c/monthly777')

        sent_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(sent_payload['billingTypes'], ['CREDIT_CARD'])
        self.assertEqual(sent_payload['chargeTypes'], ['RECURRENT'])
        self.assertEqual(sent_payload['subscription']['cycle'], 'MONTHLY')
        self.assertIn('nextDueDate', sent_payload['subscription'])
        self.assertEqual(sent_payload['items'][0]['value'], 19.90)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_09b_monthly_checkout_payload_structure_pix(self, mock_create_chk):
        """9b. Payload mensal com PIX deve ser DETACHED avulso com billingTypes=['PIX'] (sem RECURRENT indevido)."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_monthly_pix_888',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/monthlypix888'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-monthly-pix-test',
            gateway_provider='ASAAS',
            band_name='Banda Mensal Pix Teste',
            responsible_name='Juliana',
            email='juliana@teste.com',
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            amount=Decimal('49.90'),
            status='PENDENTE',
        )

        ok, link, data, err = create_asaas_checkout_for_signup_order(order, payment_method='PIX')
        self.assertTrue(ok)
        self.assertEqual(link, 'https://sandbox.asaas.com/c/monthlypix888')

        sent_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(sent_payload['billingTypes'], ['PIX'])
        self.assertEqual(sent_payload['chargeTypes'], ['DETACHED'])
        self.assertNotIn('subscription', sent_payload)
        self.assertEqual(sent_payload['items'][0]['value'], 49.90)

    def test_10_end_to_end_provisioning_after_checkout_paid(self):
        """10. Simulação de CHECKOUT_PAID: provisiona Band, BandSubscription, BillingRecord, Token e EmailDelivery."""
        order = SignupOrder.objects.create(
            external_reference='bp-ord-e2e-provision',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_e2e_paid_123',
            band_name='Banda E2E Sucesso',
            responsible_name='Fernanda Lima',
            email='fernanda@e2e.com',
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            amount=Decimal('49.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_e2e_paid_123',
                'externalReference': 'bp-ord-e2e-provision',
                'customer': 'cus_e2e_customer_99',
                'subscription': 'sub_e2e_sub_88',
            },
            'payment': {
                'id': 'pay_e2e_pay_77',
                'paymentDate': '2026-09-07',
                'value': '49.90',
            }
        }

        success, msg, band = process_checkout_paid_event(payload)
        self.assertTrue(success)
        self.assertIsNotNone(band)

        order.refresh_from_db()
        self.assertEqual(order.status, 'PAGO')
        self.assertEqual(order.band, band)

        # Assinatura criada
        sub = BandSubscription.objects.filter(band=band).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan_name, 'Avançado')
        self.assertEqual(sub.billing_cycle, 'MENSAL')
        self.assertEqual(sub.status, 'ATIVO')

        # BillingRecord criado
        record = BillingRecord.objects.filter(subscription=sub).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.status, 'PAGO')
        self.assertEqual(record.amount, Decimal('49.90'))

        # BandActivationToken gerado
        token_obj = BandActivationToken.objects.filter(band=band, signup_order=order).first()
        self.assertIsNotNone(token_obj)
        self.assertTrue(token_obj.is_valid())

        # EmailDelivery enfileirado
        email_del = EmailDelivery.objects.filter(
            email_type='ACCOUNT_ACTIVATION',
            recipient_email='fernanda@e2e.com'
        ).first()
        self.assertIsNotNone(email_del)
        self.assertEqual(email_del.status, 'PENDING')

    def test_11_idempotency_of_checkout_paid_event(self):
        """11. Segundo recebimento de CHECKOUT_PAID não duplica Band nem gera erro."""
        order = SignupOrder.objects.create(
            external_reference='bp-ord-idempotency-test',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_idemp_111',
            band_name='Banda Idempotente',
            responsible_name='Pedro',
            email='pedro@idemp.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_idemp_111',
                'externalReference': 'bp-ord-idempotency-test',
            },
            'payment': {
                'id': 'pay_idemp_222',
                'value': '19.90',
            }
        }

        # 1ª execução
        s1, m1, b1 = process_checkout_paid_event(payload)
        self.assertTrue(s1)
        self.assertEqual(Band.objects.filter(name='Banda Idempotente').count(), 1)

        # 2ª execução
        s2, m2, b2 = process_checkout_paid_event(payload)
        self.assertTrue(s2)
        self.assertEqual(m2, 'JA_PROVISIONADO')
        self.assertEqual(Band.objects.filter(name='Banda Idempotente').count(), 1)

    def test_12_tampered_price_ignored_and_canonical_enforced(self):
        """12. Parâmetro de preço adulterado via query param ou POST é descartado em favor do preço canônico."""
        resp = self.client.post(reverse('checkout') + '?plano=avancado&ciclo=anual&amount=1.00&valor=5.00', data={
            'band_name': 'Banda Hacker',
            'responsible_name': 'Hacker',
            'email': 'hacker@test.com',
            'phone': '71999887766',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'ANUAL',
            'amount': '1.00',
        })
        # O pedido deve ser criado com R$ 499.90 e NUNCA R$ 1.00
        order = SignupOrder.objects.filter(email='hacker@test.com').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.amount, Decimal('499.90'))

    def test_13_basic_annual_checkout_pricing(self):
        """13. Básico Anual deve resolver rigorosamente R$ 199,90."""
        resp = self.client.get(reverse('checkout') + '?plano=basico&ciclo=anual')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '199,90')
        self.assertContains(resp, 'Básico')
        self.assertContains(resp, 'Anual')

    def test_14_advanced_monthly_checkout_pricing(self):
        """14. Avançado Mensal deve resolver rigorosamente R$ 49,90."""
        resp = self.client.get(reverse('checkout') + '?plano=avancado&ciclo=mensal')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '49,90')
        self.assertContains(resp, 'Avançado')
        self.assertContains(resp, 'Mensal')

    def test_15_invalid_plan_or_cycle_defaults_safely(self):
        """15. Planos ou ciclos desconhecidos sofrem fallback seguro para AVANCADO / MENSAL."""
        resp = self.client.get(reverse('checkout') + '?plano=desconhecido&ciclo=invalido')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '49,90')
        self.assertContains(resp, 'Avançado')
        self.assertContains(resp, 'Mensal')

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_16_checkout_post_idempotency_prevents_duplicate_orders(self, mock_create_chk):
        """16. Duplo clique / repost com o mesmo idempotency_token não duplica SignupOrder."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_idemp_token_555',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/idemp555'
        })
        token = 'bp-ord-fixed-idempotency-key'
        form_data = {
            'band_name': 'Banda Duplo Clique',
            'responsible_name': 'Carlos Teste',
            'email': 'carlos@duploclique.com',
            'phone': '71999887766',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
            'idempotency_token': token,
        }

        # Primeiro submit
        r1 = self.client.post(reverse('checkout'), data=form_data)
        self.assertEqual(r1.status_code, 302)

        # Segundo submit idêntico (duplo clique / refresh)
        r2 = self.client.post(reverse('checkout'), data=form_data)
        self.assertEqual(r2.status_code, 302)

        # Deve existir exatamente 1 SignupOrder no banco
        self.assertEqual(SignupOrder.objects.filter(external_reference=token).count(), 1)
        self.assertEqual(SignupOrder.objects.filter(email='carlos@duploclique.com').count(), 1)

    def test_17_checkout_no_external_requests_when_payments_live_disabled(self):
        """17. Com PAYMENTS_LIVE_ENABLED=False nenhuma requisição remota é despachada."""
        with override_settings(PAYMENTS_LIVE_ENABLED=False, ASAAS_API_KEY='test_api_key'):
            with patch('urllib.request.urlopen') as mock_urlopen:
                self.client.post(reverse('checkout'), data={
                    'band_name': 'Banda Segura Sem Asaas',
                    'responsible_name': 'Seguro',
                    'email': 'seguro@semasaas.com',
                    'phone': '71999887766',
                    'cpf_cnpj': '12.345.678/0001-95',
                    'plan_type': 'BASICO',
                    'billing_cycle': 'MENSAL',
                })
                self.assertEqual(mock_urlopen.call_count, 0)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    def test_18_remote_timeout_idempotency_prevents_duplicate_checkout(self):
        """18. Se a 1ª chamada sofre timeout após envio mas salva checkout_id, retry não cria duplicata remota."""
        order = SignupOrder.objects.create(
            external_reference='bp-ord-timeout-idemp',
            gateway_provider='ASAAS',
            band_name='Banda Timeout Idemp',
            responsible_name='Lucas Timeout',
            email='lucas.timeout@teste.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        mock_client = MagicMock(spec=AsaasClient)
        mock_client.config = MagicMock()
        mock_client.config.is_configured.return_value = True

        # Primeira tentativa tem sucesso e gera checkout_id 'chk_timeout_123'
        mock_client.create_checkout.return_value = (True, {
            'id': 'chk_timeout_123',
            'paymentLink': 'https://sandbox.asaas.com/c/chk_timeout_123'
        })
        ok1, url1, data1, err1 = create_asaas_checkout_for_signup_order(order, client=mock_client)
        self.assertTrue(ok1)
        self.assertEqual(mock_client.create_checkout.call_count, 1)

        # Segunda tentativa (retentativa por timeout do cliente)
        # Deve reutilizar o checkout_id existente e NÃO chamar create_checkout novamente
        mock_client.get_payments_by_checkout.return_value = [{
            'id': 'pay_timeout_999',
            'invoiceUrl': 'https://sandbox.asaas.com/i/pay_timeout_999'
        }]
        ok2, url2, data2, err2 = create_asaas_checkout_for_signup_order(order, client=mock_client)
        self.assertTrue(ok2)
        # O AsaasClient.create_checkout continua tendo sido chamado apenas 1 única vez!
        self.assertEqual(mock_client.create_checkout.call_count, 1)

    def test_19_annual_subscription_born_with_auto_renew_false(self):
        """19. Garantia de que contratação anual nasce estritamente com auto_renew=False e sem dummy payment method."""
        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-auto-renew-false',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_annual_autorenew_test',
            band_name='Banda Anual Sem Renovacao Auto',
            responsible_name='Ana Paula',
            email='anapaula@teste.com',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_autorenew_test',
                'externalReference': 'bp-ord-annual-auto-renew-false',
                'customer': 'cus_annual_customer_11',
            },
            'payment': {
                'id': 'pay_annual_pay_22',
                'value': '499.90',
                'billingType': 'CREDIT_CARD',
            }
        }

        success, msg, band = process_checkout_paid_event(payload)
        self.assertTrue(success)
        sub = BandSubscription.objects.get(band=band)
        # Rigorosamente False
        self.assertFalse(sub.auto_renew)
        self.assertEqual(sub.billing_cycle, 'ANUAL')

    def test_20_monthly_pix_subscription_born_with_auto_renew_false_and_preference_pix(self):
        """20. Assinatura mensal paga com PIX nasce com auto_renew=False e payment_method_preference='PIX'."""
        order = SignupOrder.objects.create(
            external_reference='bp-ord-monthly-pix-flow',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_monthly_pix_flow',
            band_name='Banda Mensal Pix Flow',
            responsible_name='Marcos',
            email='marcos@pixflow.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_monthly_pix_flow',
                'externalReference': 'bp-ord-monthly-pix-flow',
                'customer': 'cus_monthly_pix_cust',
            },
            'payment': {
                'id': 'pay_monthly_pix_77',
                'value': '19.90',
                'billingType': 'PIX',
            }
        }

        success, msg, band = process_checkout_paid_event(payload)
        self.assertTrue(success)
        sub = BandSubscription.objects.get(band=band)
        self.assertFalse(sub.auto_renew)
        self.assertEqual(sub.payment_method_preference, 'PIX')
        record = BillingRecord.objects.get(subscription=sub)
        self.assertEqual(record.payment_method, 'PIX')

    def test_21_checkout_created_webhook_reconciles_gateway_checkout_id_on_timeout(self):
        """
        21. Cenário timeout: POST /v3/checkouts chegou ao Asaas mas resposta se perdeu.
        Quando CHECKOUT_CREATED chega via webhook, o gateway_checkout_id deve ser
        salvo no SignupOrder (idempotência nível 1.5 no próximo retry).
        """
        from core.services.payments.asaas.webhooks import handle_checkout_event

        # Order sem gateway_checkout_id (POST respondeu com timeout antes de salvar)
        order = SignupOrder.objects.create(
            external_reference='bp-ord-timeout-test',
            gateway_provider='ASAAS',
            gateway_checkout_id='',      # vazio — simula timeout
            band_name='Banda Timeout',
            responsible_name='Tiago',
            email='tiago@timeout.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_CREATED',
            'checkout': {
                'id': 'chk_timeout_recovered_001',
                'externalReference': 'bp-ord-timeout-test',
            },
            'externalReference': 'bp-ord-timeout-test',
        }

        ok, msg = handle_checkout_event(payload, 'CHECKOUT_CREATED')
        self.assertTrue(ok)
        self.assertIn('CHECKOUT_CREATED_PROCESSADO', msg)

        order.refresh_from_db()
        self.assertEqual(order.gateway_checkout_id, 'chk_timeout_recovered_001',
                         "CHECKOUT_CREATED deve reconciliar gateway_checkout_id ausente")

    def test_22_checkout_created_webhook_does_not_overwrite_existing_gateway_checkout_id(self):
        """
        22. Se gateway_checkout_id já estava salvo, o webhook CHECKOUT_CREATED não deve sobrescrevê-lo.
        """
        from core.services.payments.asaas.webhooks import handle_checkout_event

        order = SignupOrder.objects.create(
            external_reference='bp-ord-existing-chk',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_already_saved',
            band_name='Banda Existente',
            responsible_name='Carlos',
            email='carlos@existing.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        payload = {
            'event': 'CHECKOUT_CREATED',
            'checkout': {
                'id': 'chk_different_id_from_webhook',
                'externalReference': 'bp-ord-existing-chk',
            },
        }

        ok, msg = handle_checkout_event(payload, 'CHECKOUT_CREATED')
        self.assertTrue(ok)

        order.refresh_from_db()
        self.assertEqual(order.gateway_checkout_id, 'chk_already_saved',
                         "CHECKOUT_CREATED não deve sobrescrever gateway_checkout_id já existente")

    def test_23_pix_monthly_renewal_emits_asaas_charge_and_saves_payment_id(self):
        """
        23. Ciclo seguinte PIX mensal: o cron deve chamar POST /v3/payments via AsaasClient.post_payment,
        guardar o payment_id no BillingRecord e contar 1 cobrança emitida.
        """
        import datetime
        from unittest.mock import patch, MagicMock
        from django.utils import timezone
        from core.management.commands.check_subscription_due_dates import Command

        # Criar Band e BandSubscription mensal PIX sem gateway_subscription_id
        band = Band.objects.create(
            name='Banda PIX Ciclo Seguinte',
            slug='banda-pix-ciclo-seguinte',
            plan_type='BASICO',
            is_active=True,
        )
        today = timezone.localdate()
        due_date = today + datetime.timedelta(days=3)  # vence em 3 dias (dentro da janela de 7)

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=today - datetime.timedelta(days=27),
            next_due_date=due_date,
            auto_renew=False,
            status='ATIVO',
            payment_method_preference='PIX',
            commercial_condition='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_pix_renewal_customer',
            gateway_subscription_id='',  # sem sub_ — modelo DETACHED
        )

        mock_response = {'id': 'pay_pix_renewal_abc123', 'status': 'PENDING', 'billingType': 'PIX'}

        with patch('core.services.payments.asaas.client.AsaasClient.post_payment',
                   return_value=(True, mock_response)) as mock_post:
            cmd = Command()
            cmd.stdout = MagicMock()
            cmd.style = MagicMock()
            cmd.style.WARNING = lambda x: x
            cmd.style.SUCCESS = lambda x: x
            cmd.handle(dry_run=False)

        # Verificar que post_payment foi chamado 1x com os parâmetros corretos
        mock_post.assert_called_once()
        call_payload = mock_post.call_args[0][0]
        self.assertEqual(call_payload['billingType'], 'PIX')
        self.assertEqual(call_payload['customer'], 'cus_pix_renewal_customer')
        self.assertAlmostEqual(call_payload['value'], 19.90, places=2)
        self.assertEqual(call_payload['dueDate'], due_date.strftime('%Y-%m-%d'))
        ext_ref = call_payload['externalReference']
        self.assertTrue(ext_ref.startswith('pix-renewal-'), f"externalReference deve começar com 'pix-renewal-', recebeu: {ext_ref}")

        # Verificar que BillingRecord foi criado com gateway_payment_id salvo
        record = BillingRecord.objects.get(subscription=sub, due_date=due_date)
        self.assertEqual(record.gateway_payment_id, 'pay_pix_renewal_abc123')
        self.assertEqual(record.gateway_provider, 'ASAAS')

    def test_24_pix_monthly_renewal_without_customer_id_skips_asaas_call(self):
        """
        24. Se BandSubscription PIX mensal não tem gateway_customer_id, o cron cria o BillingRecord
        mas NÃO chama o Asaas (log de aviso esperado, sem exceção).
        """
        import datetime
        from unittest.mock import patch, MagicMock
        from django.utils import timezone
        from core.management.commands.check_subscription_due_dates import Command

        band = Band.objects.create(
            name='Banda PIX Sem Customer',
            slug='banda-pix-sem-customer',
            plan_type='BASICO',
            is_active=True,
        )
        today = timezone.localdate()
        due_date = today + datetime.timedelta(days=2)

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            next_due_date=due_date,
            auto_renew=False,
            status='ATIVO',
            payment_method_preference='PIX',
            commercial_condition='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='',   # ausente
            gateway_subscription_id='',
        )

        with patch('core.services.payments.asaas.client.AsaasClient.post_payment') as mock_post:
            cmd = Command()
            cmd.stdout = MagicMock()
            cmd.style = MagicMock()
            cmd.style.WARNING = lambda x: x
            cmd.style.SUCCESS = lambda x: x
            cmd.handle(dry_run=False)

        # post_payment NÃO deve ter sido chamado
        mock_post.assert_not_called()

        # BillingRecord deve ter sido criado mesmo assim (PENDENTE, sem gateway_payment_id)
        record = BillingRecord.objects.get(subscription=sub, due_date=due_date)
        self.assertEqual(record.status, 'PENDENTE')
        self.assertFalse(record.gateway_payment_id)

    def test_25_apply_payment_success_advances_next_due_date(self):
        """
        25. Após PAYMENT_RECEIVED do ciclo PIX mensal, apply_payment_success avança next_due_date
        exatamente 1 mês (âncora preservada quando pagamento ocorre até 5 dias antes).
        """
        import datetime
        from django.utils import timezone

        band = Band.objects.create(
            name='Banda PIX Apply Success',
            slug='banda-pix-apply-success',
            plan_type='BASICO',
            is_active=True,
        )
        today = timezone.localdate()
        # Âncora original: dia 15
        anchor_day = 15
        due_date = today.replace(day=anchor_day)
        if due_date <= today:
            # Avançar para o próximo mês
            if due_date.month == 12:
                due_date = due_date.replace(year=due_date.year + 1, month=1)
            else:
                due_date = due_date.replace(month=due_date.month + 1)

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            next_due_date=due_date,
            auto_renew=False,
            status='ATIVO',
            payment_method_preference='PIX',
            commercial_condition='PAGO',
        )

        # Pagamento realizado 2 dias antes do vencimento (dentro da tolerância)
        payment_date = due_date - datetime.timedelta(days=2)
        sub.apply_payment_success(paid_date=payment_date)
        sub.refresh_from_db()

        # next_due_date deve avançar 1 mês, preservando o dia âncora
        expected_month = due_date.month + 1 if due_date.month < 12 else 1
        expected_year = due_date.year if due_date.month < 12 else due_date.year + 1
        self.assertEqual(sub.next_due_date.day, anchor_day,
                         "O dia âncora deve ser preservado após apply_payment_success")
        self.assertEqual(sub.next_due_date.month, expected_month)
        self.assertEqual(sub.next_due_date.year, expected_year)

    def test_26_checkout_created_payload_without_external_reference_locates_by_checkout_id(self):
        """
        26. Webhook CHECKOUT_CREATED real do Sandbox pode vir sem externalReference no payload.
        Deve localizar deterministicamente o SignupOrder pelo checkout_id (gateway_checkout_id).
        """
        from core.services.payments.asaas.webhooks import handle_checkout_event

        order = SignupOrder.objects.create(
            external_reference='bp-ord-real-sandbox-ref',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_sandbox_real_999',
            band_name='Banda Real Sandbox',
            responsible_name='Lucas',
            email='lucas@sandbox.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        # Payload simulando Sandbox real onde externalReference não vem preenchido
        payload = {
            'event': 'CHECKOUT_CREATED',
            'checkout': {
                'id': 'chk_sandbox_real_999',
                'customer': 'cus_sandbox_cust_111',
                # Sem externalReference
            }
        }

        ok, msg = handle_checkout_event(payload, 'CHECKOUT_CREATED')
        self.assertTrue(ok)
        self.assertEqual(msg, 'CHECKOUT_CREATED_PROCESSADO')

    def test_27_pix_renewal_idempotency_prevents_duplicate_charge_after_timeout(self):
        """
        27. Idempotência PIX Renovação:
        Cenário:
        - 1ª execução: AsaasClient.post_payment é enviado, Asaas cria a cobrança mas timeout ocorre antes de salvar gateway_payment_id.
        - 2ª execução do cron: Antes de repetir POST /v3/payments, consulta GET /v3/payments?externalReference=pix-renewal-<id>.
        - Cobrança é encontrada -> reconcilia gateway_payment_id no BillingRecord e NÃO chama POST novamente (exatamente 1 cobrança remota).
        """
        import datetime
        from unittest.mock import patch, MagicMock
        from django.utils import timezone
        from core.management.commands.check_subscription_due_dates import Command

        band = Band.objects.create(
            name='Banda PIX Idempotencia Timeout',
            slug='banda-pix-idempotencia-timeout',
            plan_type='BASICO',
            is_active=True,
        )
        today = timezone.localdate()
        due_date = today + datetime.timedelta(days=2)

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=today - datetime.timedelta(days=28),
            next_due_date=due_date,
            auto_renew=False,
            status='ATIVO',
            payment_method_preference='PIX',
            commercial_condition='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_pix_timeout_cust',
            gateway_subscription_id='',
        )

        # Simula que o BillingRecord já existe (criado pelo cron) mas gateway_payment_id está vazio devido a timeout prévio
        month_names = {
            1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
        }
        ref_period = f"{month_names.get(due_date.month)}/{due_date.year}"
        billing_record = BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period=ref_period,
            amount=sub.contracted_value,
            due_date=due_date,
            status="PENDENTE",
            plan_name=sub.plan_name,
            billing_cycle=sub.billing_cycle,
            gateway_payment_id='',  # Vazio por causa do timeout!
        )

        expected_ext_ref = f"pix-renewal-{billing_record.id}"
        mock_remote_charge = {
            'id': 'pay_remote_already_created_999',
            'status': 'PENDING',
            'billingType': 'PIX',
            'externalReference': expected_ext_ref,
            'value': 19.90
        }

        # Na reexecução do cron:
        # get_payments_by_external_reference retorna a cobrança criada remotamente
        # post_payment NUNCA deve ser chamado
        with patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_external_reference',
                   return_value=[mock_remote_charge]) as mock_get_ext, \
             patch('core.services.payments.asaas.client.AsaasClient.post_payment') as mock_post:
            
            cmd = Command()
            cmd.stdout = MagicMock()
            cmd.style = MagicMock()
            cmd.style.WARNING = lambda x: x
            cmd.style.SUCCESS = lambda x: x
            # Executa apenas para reconciliar
            cmd._emit_pix_charge(sub, billing_record, dry_run=False)

        # Asserções estritas
        mock_get_ext.assert_called_once_with(expected_ext_ref)
        mock_post.assert_not_called()  # Garante zero duplicações no Asaas!

        billing_record.refresh_from_db()
        self.assertEqual(billing_record.gateway_payment_id, 'pay_remote_already_created_999')
        self.assertEqual(billing_record.gateway_provider, 'ASAAS')

    def test_28_initial_get_has_empty_text_inputs_bp_pend_25(self):
        """
        28. BP-PEND-25: No GET inicial, todos os campos de texto iniciam estritamente vazios.
        Nenhum valor default ou pré-preenchido para banda, responsável, email, telefone ou cpf/cnpj,
        e nenhum dos 5 inputs de texto possui atributo placeholder de exemplo.
        """
        resp = self.client.get(reverse('checkout') + '?plano=basico&ciclo=mensal')
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        
        # 1. Valores iniciais vazios
        self.assertFalse(form.initial.get('band_name'))
        self.assertFalse(form.initial.get('responsible_name'))
        self.assertFalse(form.initial.get('email'))
        self.assertFalse(form.initial.get('phone'))
        self.assertFalse(form.initial.get('cpf_cnpj'))

        # 2. Nenhum dos 5 inputs possui atributo placeholder
        for field_name in ('band_name', 'responsible_name', 'email', 'phone', 'cpf_cnpj'):
            field_widget = form.fields[field_name].widget
            self.assertNotIn('placeholder', field_widget.attrs, f"Campo {field_name} não deve ter placeholder")

        # 3. Confirmar que na resposta HTML renderizada não há placeholders de exemplo nesses campos
        content = resp.content.decode('utf-8')
        self.assertNotIn('placeholder="Ex: Banda Graveto"', content)
        self.assertNotIn('placeholder="Ex: Carlos Oliveira"', content)
        self.assertNotIn('placeholder="seuemail@exemplo.com"', content)
        self.assertNotIn('placeholder="(71) 99999-9999"', content)
        self.assertNotIn('placeholder="000.000.000-00 ou 00.000.000/0000-00"', content)
        self.assertNotIn('placeholder=', content)

    def test_29_phone_validation_rules_bp_pend_23(self):
        """
        29. BP-PEND-23: Telefone/WhatsApp obrigatório com validação rigorosa.
        """
        from core.forms_checkout import SignupOrderForm

        # Vazio -> Inválido
        f1 = SignupOrderForm(data={'phone': ''})
        f1.is_valid()
        self.assertIn('phone', f1.errors)

        # Inválido (poucos dígitos) -> Rejeitado
        f2 = SignupOrderForm(data={'phone': '12345'})
        f2.is_valid()
        self.assertIn('phone', f2.errors)

        # DDDs inexistentes dentro da faixa 11-99 -> Rejeitados
        # 4. DDD inexistente 20
        f_ddd20 = SignupOrderForm(data={'phone': '(20) 99999-9999'})
        f_ddd20.is_valid()
        self.assertIn('phone', f_ddd20.errors)

        # 5. DDD inexistente 23
        f_ddd23 = SignupOrderForm(data={'phone': '(23) 99999-9999'})
        f_ddd23.is_valid()
        self.assertIn('phone', f_ddd23.errors)

        # 6. DDD inexistente 90
        f_ddd90 = SignupOrderForm(data={'phone': '(90) 99999-9999'})
        f_ddd90.is_valid()
        self.assertIn('phone', f_ddd90.errors)

        # DDDs válidos testados explicitamente:
        # 1. DDD válido 71 -> aceito
        f_ddd71 = SignupOrderForm(data={
            'band_name': 'Banda Fone 71',
            'responsible_name': 'Resp 71',
            'email': 'resp71@teste.com',
            'phone': '(71) 98877-6655',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertTrue(f_ddd71.is_valid(), f_ddd71.errors)
        self.assertEqual(f_ddd71.cleaned_data['phone'], '71988776655')

        # 2. DDD válido 11 -> aceito
        f_ddd11 = SignupOrderForm(data={
            'band_name': 'Banda Fone 11',
            'responsible_name': 'Resp 11',
            'email': 'resp11@teste.com',
            'phone': '(11) 97766-5544',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertTrue(f_ddd11.is_valid(), f_ddd11.errors)
        self.assertEqual(f_ddd11.cleaned_data['phone'], '11977665544')

        # 3. DDD válido 99 -> aceito
        f_ddd99 = SignupOrderForm(data={
            'band_name': 'Banda Fone 99',
            'responsible_name': 'Resp 99',
            'email': 'resp99@teste.com',
            'phone': '(99) 96655-4433',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertTrue(f_ddd99.is_valid(), f_ddd99.errors)
        self.assertEqual(f_ddd99.cleaned_data['phone'], '99966554433')

        # 7. +55 (71) ... -> continua aceito e normalizado corretamente
        f_ddi55_71 = SignupOrderForm(data={
            'band_name': 'Banda Fone DDI 55 71',
            'responsible_name': 'Resp DDI',
            'email': 'respddi@teste.com',
            'phone': '+55 (71) 98877-6655',
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertTrue(f_ddi55_71.is_valid(), f_ddi55_71.errors)
        self.assertEqual(f_ddi55_71.cleaned_data['phone'], '71988776655')

    def test_30_cpf_cnpj_validation_rules_bp_pend_23(self):
        """
        30. BP-PEND-23: CPF/CNPJ obrigatório com validação matemática e normalização para dígitos.
        """
        from core.forms_checkout import SignupOrderForm

        base_data = {
            'band_name': 'Banda Docs',
            'responsible_name': 'Responsável',
            'email': 'doc@teste.com',
            'phone': '71999999999',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        }

        # Vazio -> Inválido
        f_empty = SignupOrderForm(data={**base_data, 'cpf_cnpj': ''})
        self.assertFalse(f_empty.is_valid())
        self.assertIn('cpf_cnpj', f_empty.errors)

        # Quantidade de dígitos inválida (ex: 8 dígitos) -> Rejeitado
        f_len = SignupOrderForm(data={**base_data, 'cpf_cnpj': '12345678'})
        self.assertFalse(f_len.is_valid())
        self.assertIn('cpf_cnpj', f_len.errors)

        # CPF com dígitos repetidos (inválido) -> Rejeitado
        f_cpf_rep = SignupOrderForm(data={**base_data, 'cpf_cnpj': '111.111.111-11'})
        self.assertFalse(f_cpf_rep.is_valid())
        self.assertIn('cpf_cnpj', f_cpf_rep.errors)

        # CPF matematicamente inválido -> Rejeitado
        f_cpf_inv = SignupOrderForm(data={**base_data, 'cpf_cnpj': '123.456.789-00'})
        self.assertFalse(f_cpf_inv.is_valid())
        self.assertIn('cpf_cnpj', f_cpf_inv.errors)

        # CPF matematicamente válido -> Aceito e normalizado
        # CPF válido conhecido: 52998224725
        f_cpf_ok = SignupOrderForm(data={**base_data, 'cpf_cnpj': '529.982.247-25'})
        self.assertTrue(f_cpf_ok.is_valid(), f_cpf_ok.errors)
        self.assertEqual(f_cpf_ok.cleaned_data['cpf_cnpj'], '52998224725')

        # CNPJ com dígitos repetidos (inválido) -> Rejeitado
        f_cnpj_rep = SignupOrderForm(data={**base_data, 'cpf_cnpj': '11.111.111/1111-11'})
        self.assertFalse(f_cnpj_rep.is_valid())
        self.assertIn('cpf_cnpj', f_cnpj_rep.errors)

        # CNPJ matematicamente inválido -> Rejeitado
        f_cnpj_inv = SignupOrderForm(data={**base_data, 'cpf_cnpj': '12.345.678/0001-00'})
        self.assertFalse(f_cnpj_inv.is_valid())
        self.assertIn('cpf_cnpj', f_cnpj_inv.errors)

        # CNPJ matematicamente válido -> Aceito e normalizado
        # CNPJ válido conhecido: 12.345.678/0001-95
        f_cnpj_ok = SignupOrderForm(data={**base_data, 'cpf_cnpj': '12.345.678/0001-95'})
        self.assertTrue(f_cnpj_ok.is_valid(), f_cnpj_ok.errors)
        self.assertEqual(f_cnpj_ok.cleaned_data['cpf_cnpj'], '12345678000195')

    def test_31_invalid_post_preserves_submitted_values_bp_pend_25(self):
        """
        31. BP-PEND-25: Quando o POST falha na validação, o formulário deve preservar
        todos os valores submetidos pelo usuário para que não precise digitar novamente.
        """
        resp = self.client.post(reverse('checkout'), data={
            'band_name': 'Banda Preservada',
            'responsible_name': 'Mariana Duarte',
            'email': 'mariana@preservada.com',
            'phone': '12345',               # Telefone inválido proposital
            'cpf_cnpj': '12.345.678/0001-95',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Banda Preservada')
        self.assertContains(resp, 'Mariana Duarte')
        self.assertContains(resp, 'mariana@preservada.com')
        self.assertContains(resp, '12345')
        self.assertContains(resp, '12.345.678/0001-95')

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_32_asaas_payload_contains_customer_data_and_not_customer_bp_pend_26(self, mock_create_chk):
        """
        32. BP-PEND-26: O payload do Asaas deve conter customerData com os dados do responsável
        normalizados e NÃO deve conter o campo customer simultaneamente.
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_customer_data_123',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/custdata123'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-custdata-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_old_test',
            band_name='Banda do Produtor',
            responsible_name='João Produtor',
            email='joao.produtor@teste.com',
            phone='(71) 98877-6655',
            cpf_cnpj='12.345.678/0001-95',
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            amount=Decimal('49.90'),
            status='PENDENTE',
        )

        ok, link, data, err = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)
        self.assertEqual(link, 'https://sandbox.asaas.com/c/custdata123')

        sent_payload = mock_create_chk.call_args[0][0]

        # Validar customerData
        self.assertIn('customerData', sent_payload)
        cust_data = sent_payload['customerData']
        self.assertEqual(cust_data['name'], 'João Produtor')
        self.assertEqual(cust_data['email'], 'joao.produtor@teste.com')
        self.assertEqual(cust_data['cpfCnpj'], '12345678000195')
        self.assertEqual(cust_data['phone'], '71988776655')

        # REGRA CRÍTICA: NÃO enviar customer junto com customerData
        self.assertNotIn('customer', sent_payload)

        # Preservação das demais regras
        self.assertEqual(sent_payload['externalReference'], 'bp-ord-custdata-test')
        self.assertEqual(sent_payload['items'][0]['value'], 49.90)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_33_all_four_flows_preserve_customer_data_and_canonical_pricing(self, mock_create_chk):
        """
        33. Validação explícita dos 4 fluxos combinados (Mensal Cartão, Mensal PIX, Anual Cartão, Anual PIX)
        garantindo customerData, preço canônico e sem customer no payload.
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_combo_ok',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/combo'
        })

        flows = [
            ('BASICO', 'MENSAL', 'CREDIT_CARD', Decimal('19.90'), ['CREDIT_CARD'], ['RECURRENT']),
            ('BASICO', 'MENSAL', 'PIX', Decimal('19.90'), ['PIX'], ['DETACHED']),
            ('AVANCADO', 'ANUAL', 'CREDIT_CARD', Decimal('499.90'), ['CREDIT_CARD'], ['DETACHED', 'INSTALLMENT']),
            ('AVANCADO', 'ANUAL', 'PIX', Decimal('499.90'), ['PIX'], ['DETACHED', 'INSTALLMENT']),
        ]

        for idx, (plan, cycle, method, expected_val, exp_billing_types, exp_charge_types) in enumerate(flows):
            mock_create_chk.return_value = (True, {
                'id': f'chk_combo_ok_{idx}',
                'status': 'ACTIVE',
                'paymentLink': f'https://sandbox.asaas.com/c/combo_{idx}'
            })
            order = SignupOrder.objects.create(
                external_reference=f'bp-ord-flow-{plan}-{cycle}-{method}',
                gateway_provider='ASAAS',
                band_name='Banda Flow Test',
                responsible_name='Nome do Comprador',
                email='comprador@teste.com',
                phone='(11) 98765-4321',
                cpf_cnpj='529.982.247-25',
                plan_type=plan,
                billing_cycle=cycle,
                amount=expected_val,
                status='PENDENTE',
            )

            ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method=method)
            self.assertTrue(ok)

            payload = mock_create_chk.call_args[0][0]
            self.assertIn('customerData', payload)
            self.assertNotIn('customer', payload)
            self.assertEqual(payload['customerData']['name'], 'Nome do Comprador')
            self.assertEqual(payload['customerData']['cpfCnpj'], '52998224725')
            self.assertEqual(payload['customerData']['phone'], '11987654321')
            self.assertEqual(payload['items'][0]['value'], float(expected_val))
            self.assertEqual(payload['billingTypes'], exp_billing_types)
            self.assertEqual(payload['chargeTypes'], exp_charge_types)
