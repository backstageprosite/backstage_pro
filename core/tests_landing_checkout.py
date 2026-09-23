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
            'postal_code': '',
            'address': '',
            'address_number': '',
            'province': '',
            'city': '',
            'state': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Informe o nome da banda ou artista.')
        self.assertContains(resp, 'Informe um telefone ou WhatsApp para contato.')
        self.assertContains(resp, 'Informe um CPF ou CNPJ válido.')
        self.assertContains(resp, 'Informe o CEP.')
        self.assertContains(resp, 'Informe o endereço.')
        self.assertContains(resp, 'Informe o número.')
        self.assertContains(resp, 'Informe o bairro.')
        self.assertContains(resp, 'Informe a cidade.')
        self.assertContains(resp, 'Informe o Estado / UF.')
        self.assertEqual(SignupOrder.objects.count(), 0)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_customer', return_value=(True, {'id': 'cus_live_06'}))
    @patch.object(AsaasClient, 'create_checkout')
    def test_06_checkout_post_creates_signup_order_and_redirects_to_asaas(self, mock_create_chk, mock_create_cust):
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
            'postal_code': '41720-000',
            'address': 'Avenida Jorge Amado',
            'address_number': '100',
            'complement': 'Sala 204',
            'province': 'Imbuí',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://sandbox.asaas.com/c/live_order_123')
        self.assertEqual(mock_create_chk.call_count, 1)

        # Validar persistência do SignupOrder com endereço
        order = SignupOrder.objects.filter(email='marina@estrelasolar.com').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.band_name, 'Banda Estrela Solar')
        self.assertEqual(order.postal_code, '41720000')
        self.assertEqual(order.address, 'Avenida Jorge Amado')
        self.assertEqual(order.address_number, '100')
        self.assertEqual(order.complement, 'Sala 204')
        self.assertEqual(order.province, 'Imbuí')
        self.assertEqual(order.city, 'Salvador')
        self.assertEqual(order.state, 'BA')
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
            'postal_code': '41720-000',
            'address': 'Rua da Segurança',
            'address_number': '1',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
        """8. Payload anual deve conter PIX + CREDIT_CARD, INSTALLMENT com maxInstallmentCount=5 e valor integral."""
        mock_create_chk.return_value = (True, {
            'id': 'chk_annual_999',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/annual999'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_annual_test_customer',
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
        self.assertEqual(sent_payload['installment']['maxInstallmentCount'], 5)
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
            gateway_customer_id='cus_monthly_test_customer',
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
            gateway_customer_id='cus_pix_test_customer',
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
            'postal_code': '41720-000',
            'address': 'Rua do Teste',
            'address_number': '123',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
    @patch.object(AsaasClient, 'get_customer', return_value={'postalCode': '41720000', 'address': 'Rua Teste', 'addressNumber': '10', 'province': 'Bairro', 'city': 'Salvador', 'state': 'BA'})
    @patch.object(AsaasClient, 'create_customer', return_value=(True, {'id': 'cus_idemp_16'}))
    @patch.object(AsaasClient, 'create_checkout')
    def test_16_checkout_post_idempotency_prevents_duplicate_orders(self, mock_create_chk, mock_create_cust, mock_get_cust):
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Bairro',
            'city': 'Salvador',
            'state': 'BA',
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
            gateway_customer_id='cus_timeout_test_cust',
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
        Nenhum valor default ou pré-preenchido para banda, responsável, email, telefone, cpf/cnpj ou endereço,
        e nenhum dos inputs de texto possui atributo placeholder de exemplo.
        """
        resp = self.client.get(reverse('checkout') + '?plano=basico&ciclo=mensal')
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        
        # 1. Valores iniciais vazios
        for field_name in (
            'band_name', 'responsible_name', 'email', 'phone', 'cpf_cnpj',
            'postal_code', 'address', 'address_number', 'complement', 'province', 'city', 'state'
        ):
            self.assertFalse(form.initial.get(field_name), f"Campo {field_name} não deve ter valor inicial")

        # 2. Nenhum dos inputs possui atributo placeholder
        for field_name in (
            'band_name', 'responsible_name', 'email', 'phone', 'cpf_cnpj',
            'postal_code', 'address', 'address_number', 'complement', 'province', 'city', 'state'
        ):
            field_widget = form.fields[field_name].widget
            self.assertNotIn('placeholder', field_widget.attrs, f"Campo {field_name} não deve ter placeholder")

        # 3. Confirmar que na resposta HTML renderizada não há placeholders de exemplo nesses campos
        content = resp.content.decode('utf-8')
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
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
            'postal_code': '41720-000',
            'address': 'Rua das Flores',
            'address_number': '42B',
            'complement': 'Apto 101',
            'province': 'Pituba',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Banda Preservada')
        self.assertContains(resp, 'Mariana Duarte')
        self.assertContains(resp, 'mariana@preservada.com')
        self.assertContains(resp, '12345')
        self.assertContains(resp, '12.345.678/0001-95')
        self.assertContains(resp, '41720-000')
        self.assertContains(resp, 'Rua das Flores')
        self.assertContains(resp, '42B')
        self.assertContains(resp, 'Apto 101')
        self.assertContains(resp, 'Pituba')
        self.assertContains(resp, 'Salvador')
        self.assertContains(resp, 'BA')

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_32_asaas_payload_contains_customer_and_not_customer_data_bp_pend_26(self, mock_create_chk):
        """
        32. BP-PEND-26 / BP-PEND-27: O payload do Asaas deve conter "customer": "cus_..."
        e NUNCA deve conter "customerData".
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_customer_data_123',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/custdata123'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-custdata-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_existing_test_32',
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

        # Validar ausência de customerData
        self.assertNotIn('customerData', sent_payload)

        # REGRA CRÍTICA BP-PEND-26: Enviar customer: "cus_..."
        self.assertEqual(sent_payload.get('customer'), 'cus_existing_test_32')

        # Preservação das demais regras
        self.assertEqual(sent_payload['externalReference'], 'bp-ord-custdata-test')
        self.assertEqual(sent_payload['items'][0]['value'], 49.90)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_33_all_four_flows_preserve_customer_id_and_canonical_pricing(self, mock_create_chk):
        """
        33. Validação explícita dos 4 fluxos combinados (Mensal Cartão, Mensal PIX, Anual Cartão, Anual PIX)
        garantindo customer ID, preço canônico e sem customerData no payload.
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_combo_ok',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/combo'
        })

        flows = [
            ('BASICO', 'MENSAL', 'CREDIT_CARD', Decimal('19.90'), ['CREDIT_CARD'], ['RECURRENT'], False),
            ('BASICO', 'MENSAL', 'PIX', Decimal('19.90'), ['PIX'], ['DETACHED'], False),
            ('AVANCADO', 'ANUAL', 'CREDIT_CARD', Decimal('499.90'), ['CREDIT_CARD'], ['DETACHED', 'INSTALLMENT'], True),
            ('AVANCADO', 'ANUAL', 'PIX', Decimal('499.90'), ['PIX'], ['DETACHED'], False),
        ]

        for idx, (plan, cycle, method, expected_val, exp_billing_types, exp_charge_types, has_installment) in enumerate(flows):
            mock_create_chk.return_value = (True, {
                'id': f'chk_combo_ok_{idx}',
                'status': 'ACTIVE',
                'paymentLink': f'https://sandbox.asaas.com/c/combo_{idx}'
            })
            order = SignupOrder.objects.create(
                external_reference=f'bp-ord-flow-{plan}-{cycle}-{method}',
                gateway_provider='ASAAS',
                gateway_customer_id=f'cus_flow_{idx}',
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
            self.assertNotIn('customerData', payload)
            self.assertEqual(payload.get('customer'), f'cus_flow_{idx}')
            self.assertEqual(payload['items'][0]['value'], float(expected_val))
            self.assertEqual(payload['billingTypes'], exp_billing_types)
            self.assertEqual(payload['chargeTypes'], exp_charge_types)
            if has_installment:
                self.assertIn('installment', payload)
            else:
                self.assertNotIn('installment', payload)
                self.assertNotIn('INSTALLMENT', payload['chargeTypes'])

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_34_new_customer_created_when_signup_order_has_no_customer_id(self, mock_create_chk, mock_create_cust):
        """
        34. BP-PEND-27: Cria novo customer no Asaas via POST /v3/customers quando SignupOrder
        ainda não possui gateway_customer_id. O customer é vinculado à ordem e ao checkout.
        """
        mock_create_cust.return_value = (True, {
            'id': 'cus_new_created_123',
            'name': 'Responsável Teste',
            'email': 'resp@teste.com',
            'cpfCnpj': '12345678000195',
            'mobilePhone': '71988776655',
        })
        mock_create_chk.return_value = (True, {
            'id': 'chk_created_123',
            'paymentLink': 'https://sandbox.asaas.com/c/chk123'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-new-cust-order',
            gateway_provider='ASAAS',
            gateway_customer_id=None,
            band_name='Banda Sem Customer',
            responsible_name='Responsável Teste',
            email='resp@teste.com',
            phone='(71) 98877-6655',
            cpf_cnpj='12.345.678/0001-95',
            postal_code='41720-000',
            address='Avenida Jorge Amado',
            address_number='100',
            complement='Sala 204',
            province='Imbuí',
            city='Salvador',
            state='BA',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='PIX')
        self.assertTrue(ok)

        # Verificar chamada create_customer com identificação e endereço completos
        mock_create_cust.assert_called_once()
        cust_payload = mock_create_cust.call_args[0][0]
        self.assertEqual(cust_payload['name'], 'Responsável Teste')
        self.assertEqual(cust_payload['email'], 'resp@teste.com')
        self.assertEqual(cust_payload['cpfCnpj'], '12345678000195')
        self.assertEqual(cust_payload['mobilePhone'], '71988776655')
        self.assertEqual(cust_payload['externalReference'], 'bp-cust-bp-ord-new-cust-order')
        self.assertEqual(cust_payload['postalCode'], '41720000')
        self.assertEqual(cust_payload['address'], 'Avenida Jorge Amado')
        self.assertEqual(cust_payload['addressNumber'], '100')
        self.assertEqual(cust_payload['complement'], 'Sala 204')
        self.assertEqual(cust_payload['province'], 'Imbuí')
        self.assertEqual(cust_payload['city'], 'Salvador')
        self.assertEqual(cust_payload['state'], 'BA')
        self.assertTrue(cust_payload['notificationDisabled'])

        # Ordem deve ter salvo o gateway_customer_id
        order.refresh_from_db()
        self.assertEqual(order.gateway_customer_id, 'cus_new_created_123')

        # Checkout deve ter sido chamado com "customer": "cus_new_created_123" e sem customerData
        chk_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(chk_payload.get('customer'), 'cus_new_created_123')
        self.assertNotIn('customerData', chk_payload)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_35_existing_customer_id_on_signup_order_is_reused_without_api_call(self, mock_create_chk, mock_create_cust):
        """
        35. Se SignupOrder já possui gateway_customer_id, NÃO chama POST /v3/customers nem GET /v3/customers.
        Reutiliza diretamente o ID local.
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_reused_cust',
            'paymentLink': 'https://sandbox.asaas.com/c/chk_reused'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-reused-cust',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_local_already_saved',
            band_name='Banda Local Cust',
            responsible_name='Resp Local',
            email='resplocal@teste.com',
            phone='11999998888',
            cpf_cnpj='52998224725',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)
        mock_create_cust.assert_not_called()

        chk_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(chk_payload['customer'], 'cus_local_already_saved')
        self.assertNotIn('customerData', chk_payload)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'get_customers_by_external_reference')
    @patch.object(AsaasClient, 'create_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_36_existing_remote_customer_found_by_external_reference_is_reused(
        self, mock_create_chk, mock_create_cust, mock_get_cust_by_ref
    ):
        """
        36. Idempotência: Se o gateway_customer_id local estiver vazio, mas o Asaas já possuir um
        customer com aquele externalReference determinístico, recupera e reutiliza sem disparar POST.
        """
        mock_get_cust_by_ref.return_value = [{'id': 'cus_remote_existing_456'}]
        mock_create_chk.return_value = (True, {
            'id': 'chk_found_cust',
            'paymentLink': 'https://sandbox.asaas.com/c/chk_found'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-ref-lookup',
            gateway_provider='ASAAS',
            gateway_customer_id=None,
            band_name='Banda Lookup',
            responsible_name='Resp Lookup',
            email='lookup@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='PIX')
        self.assertTrue(ok)

        # GET foi chamado com o externalReference determinístico
        mock_get_cust_by_ref.assert_called_once_with('bp-cust-bp-ord-ref-lookup')
        # POST NÃO foi chamado
        mock_create_cust.assert_not_called()

        order.refresh_from_db()
        self.assertEqual(order.gateway_customer_id, 'cus_remote_existing_456')

        chk_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(chk_payload['customer'], 'cus_remote_existing_456')

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'get_customers_by_external_reference')
    @patch.object(AsaasClient, 'create_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_37_timeout_on_customer_creation_reconciles_via_external_reference(
        self, mock_create_chk, mock_create_cust, mock_get_cust_by_ref
    ):
        """
        37. Idempotência e tolerância a falhas: Se POST /v3/customers lança exceção (ex: timeout),
        o sistema realiza busca por externalReference e recupera o customer criado remotamente.
        """
        # Primeira busca (antes do POST): não encontra
        # Segunda busca (após timeout): encontra o customer criado remotamente
        mock_get_cust_by_ref.side_effect = [[], [{'id': 'cus_recovered_after_timeout'}]]
        mock_create_cust.side_effect = Exception("Connection timed out waiting for Asaas")
        mock_create_chk.return_value = (True, {
            'id': 'chk_after_timeout',
            'paymentLink': 'https://sandbox.asaas.com/c/after_timeout'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-timeout-recovery',
            gateway_provider='ASAAS',
            gateway_customer_id=None,
            band_name='Banda Timeout Recovery',
            responsible_name='Resp Timeout',
            email='timeout@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='PIX')
        self.assertTrue(ok)

        # Customer recuperado e salvo no banco
        order.refresh_from_db()
        self.assertEqual(order.gateway_customer_id, 'cus_recovered_after_timeout')

        # Checkout gerado com o customer recuperado
        chk_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(chk_payload['customer'], 'cus_recovered_after_timeout')

    @override_settings(PAYMENTS_LIVE_ENABLED=False, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    def test_38_customer_creation_blocked_by_safety_gate_when_live_disabled(self):
        """
        38. Safety Gate: Se PAYMENTS_LIVE_ENABLED=False e a ordem não tem gateway_customer_id,
        o AsaasClient.create_customer é bloqueado e a operação retorna erro sem afetar o gateway.
        """
        order = SignupOrder.objects.create(
            external_reference='bp-ord-safety-gate',
            gateway_provider='ASAAS',
            gateway_customer_id=None,
            band_name='Banda Safety Gate',
            responsible_name='Resp Safety',
            email='safety@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, res_data, err = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertFalse(ok)
        self.assertIn("PAYMENTS_LIVE_ENABLED=False", str(err))
        self.assertIsNone(order.gateway_customer_id)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_39_annual_pix_payload_is_detached_without_installment_bp_pend_28(self, mock_create_chk):
        """
        39. BP-PEND-28: Anual + PIX é rigorosamente à vista:
        - billingTypes=['PIX']
        - chargeTypes=['DETACHED']
        - NÃO contém 'INSTALLMENT'
        - NÃO contém objeto 'installment'
        - preserva o valor anual canônico correto (ex: R$ 499.90 ou R$ 199.90)
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_annual_pix_ok',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/annual_pix_link'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-pix-explicit',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_annual_pix_cust',
            band_name='Banda Anual Pix',
            responsible_name='Roberto Pix',
            email='robertopix@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='PIX')
        self.assertTrue(ok)
        self.assertEqual(link, 'https://sandbox.asaas.com/c/annual_pix_link')

        sent_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(sent_payload['billingTypes'], ['PIX'])
        self.assertEqual(sent_payload['chargeTypes'], ['DETACHED'])
        self.assertNotIn('INSTALLMENT', sent_payload['chargeTypes'])
        self.assertNotIn('installment', sent_payload)
        self.assertEqual(sent_payload['items'][0]['value'], 499.90)
        self.assertEqual(sent_payload['customer'], 'cus_annual_pix_cust')
        self.assertNotIn('customerData', sent_payload)

    def test_40_address_required_fields_validation_bp_pend_32(self):
        """
        40. BP-PEND-32 Regra B: CEP, Endereço, Número, Bairro, Cidade e UF são obrigatórios.
        Complemento é opcional.
        """
        from core.forms_checkout import SignupOrderForm

        base_valid_data = {
            'band_name': 'Banda Teste Endereço',
            'responsible_name': 'Produtor Teste',
            'email': 'produtor@teste.com',
            'phone': '(71) 98877-6655',
            'cpf_cnpj': '12.345.678/0001-95',
            'postal_code': '41720-000',
            'address': 'Avenida Jorge Amado',
            'address_number': '100',
            'complement': '',  # Opcional!
            'province': 'Imbuí',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        }

        # Com todos obrigatórios preenchidos e complemento vazio -> Válido!
        f_ok = SignupOrderForm(data=base_valid_data)
        self.assertTrue(f_ok.is_valid(), f_ok.errors)
        self.assertEqual(f_ok.cleaned_data['complement'], '')

        # Testa cada campo obrigatório de endereço individualmente ausente
        for field in ('postal_code', 'address', 'address_number', 'province', 'city', 'state'):
            tampered = dict(base_valid_data)
            tampered[field] = ''
            f_err = SignupOrderForm(data=tampered)
            self.assertFalse(f_err.is_valid(), f"Campo {field} deveria ser obrigatório")
            self.assertIn(field, f_err.errors)

    def test_41_cep_validation_and_normalization_bp_pend_32(self):
        """
        41. BP-PEND-32 Regra C: CEP aceita formatado ou somente dígitos,
        valida tamanho exato de 8 dígitos e rejeita inválidos.
        """
        from core.forms_checkout import SignupOrderForm

        base_data = {
            'band_name': 'Banda CEP Test',
            'responsible_name': 'Produtor CEP',
            'email': 'cep@teste.com',
            'phone': '(71) 98877-6655',
            'cpf_cnpj': '12.345.678/0001-95',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        }

        # Formatado 41720-000 -> normaliza para 41720000
        f1 = SignupOrderForm(data={**base_data, 'postal_code': '41720-000'})
        self.assertTrue(f1.is_valid(), f1.errors)
        self.assertEqual(f1.cleaned_data['postal_code'], '41720000')

        # Somente números 41720000 -> normaliza para 41720000
        f2 = SignupOrderForm(data={**base_data, 'postal_code': '41720000'})
        self.assertTrue(f2.is_valid(), f2.errors)
        self.assertEqual(f2.cleaned_data['postal_code'], '41720000')

        # CEP menor que 8 dígitos -> Rejeitado
        f3 = SignupOrderForm(data={**base_data, 'postal_code': '41720-00'})
        self.assertFalse(f3.is_valid())
        self.assertIn('postal_code', f3.errors)

        # CEP maior que 8 dígitos -> Rejeitado
        f4 = SignupOrderForm(data={**base_data, 'postal_code': '417200001'})
        self.assertFalse(f4.is_valid())
        self.assertIn('postal_code', f4.errors)

    def test_42_state_uf_validation_and_normalization_bp_pend_32(self):
        """
        42. BP-PEND-32 Regra D: Estado / UF valida contra as 27 UFs brasileiras,
        normaliza para maiúsculas e rejeita siglas inexistentes.
        """
        from core.forms_checkout import SignupOrderForm

        base_data = {
            'band_name': 'Banda UF Test',
            'responsible_name': 'Produtor UF',
            'email': 'uf@teste.com',
            'phone': '(71) 98877-6655',
            'cpf_cnpj': '12.345.678/0001-95',
            'postal_code': '41720-000',
            'address': 'Rua Teste',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'plan_type': 'BASICO',
            'billing_cycle': 'MENSAL',
        }

        # UF em minúsculas 'sp' -> normaliza para 'SP'
        f_min = SignupOrderForm(data={**base_data, 'state': 'sp'})
        self.assertTrue(f_min.is_valid(), f_min.errors)
        self.assertEqual(f_min.cleaned_data['state'], 'SP')

        # UF válida 'BA' -> aceita
        f_ba = SignupOrderForm(data={**base_data, 'state': 'BA'})
        self.assertTrue(f_ba.is_valid(), f_ba.errors)
        self.assertEqual(f_ba.cleaned_data['state'], 'BA')

        # UF inexistente 'XX' -> rejeitada
        f_inv = SignupOrderForm(data={**base_data, 'state': 'XX'})
        self.assertFalse(f_inv.is_valid())
        self.assertIn('state', f_inv.errors)

        # UF com tamanho inválido 'SPO' -> rejeitada
        f_len = SignupOrderForm(data={**base_data, 'state': 'SPO'})
        self.assertFalse(f_len.is_valid())
        self.assertIn('state', f_len.errors)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'update_customer')
    @patch.object(AsaasClient, 'get_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_43_existing_customer_with_missing_address_is_updated_via_put_bp_pend_32(
        self, mock_create_chk, mock_get_cust, mock_update_cust
    ):
        """
        43. BP-PEND-32 Regra G: Se SignupOrder já possui gateway_customer_id mas o cliente no Asaas
        não possui endereço preenchido, dispara PUT /v3/customers/{id} com o endereço completo
        sem criar customer duplicado e usa o customer ID no checkout.
        """
        mock_get_cust.return_value = {
            'id': 'cus_existing_no_address',
            'name': 'Responsável Antigo',
            'email': 'antigo@teste.com',
            'postalCode': None,
            'address': None,
            'addressNumber': None,
            'province': None,
            'city': None,
            'state': None,
        }
        mock_update_cust.return_value = (True, {'id': 'cus_existing_no_address'})
        mock_create_chk.return_value = (True, {
            'id': 'chk_updated_cust',
            'paymentLink': 'https://sandbox.asaas.com/c/updated'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-update-address-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_existing_no_address',
            band_name='Banda Atualiza Endereço',
            responsible_name='Responsável Atualizado',
            email='atualizado@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            postal_code='41720-000',
            address='Avenida Paralela',
            address_number='500',
            complement='Bloco B',
            province='Alphaville',
            city='Salvador',
            state='BA',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)

        # GET foi chamado para consultar os dados atuais do customer
        mock_get_cust.assert_called_once_with('cus_existing_no_address')

        # PUT foi chamado com os dados completos de endereço para sincronizar
        mock_update_cust.assert_called_once()
        upd_id, upd_payload = mock_update_cust.call_args[0]
        self.assertEqual(upd_id, 'cus_existing_no_address')
        self.assertEqual(upd_payload['postalCode'], '41720000')
        self.assertEqual(upd_payload['address'], 'Avenida Paralela')
        self.assertEqual(upd_payload['addressNumber'], '500')
        self.assertEqual(upd_payload['complement'], 'Bloco B')
        self.assertEqual(upd_payload['province'], 'Alphaville')
        self.assertEqual(upd_payload['city'], 'Salvador')
        self.assertEqual(upd_payload['state'], 'BA')
        self.assertTrue(upd_payload['notificationDisabled'])

        # Checkout enviado com "customer": "cus_existing_no_address" e sem customerData
        chk_payload = mock_create_chk.call_args[0][0]
        self.assertEqual(chk_payload.get('customer'), 'cus_existing_no_address')
        self.assertNotIn('customerData', chk_payload)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'update_customer')
    @patch.object(AsaasClient, 'get_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_44_existing_customer_with_complete_matching_address_does_not_call_put_bp_pend_32(
        self, mock_create_chk, mock_get_cust, mock_update_cust
    ):
        """
        44. BP-PEND-32: Se o cliente remoto já possui exatamente o mesmo endereço preenchido,
        e notificationDisabled=True, não dispara PUT /v3/customers/{id} desnecessariamente.
        """
        mock_get_cust.return_value = {
            'id': 'cus_already_complete',
            'name': 'Responsável Completo',
            'email': 'completo@teste.com',
            'postalCode': '41720000',
            'address': 'Avenida Paralela',
            'addressNumber': '500',
            'province': 'Alphaville',
            'city': 'Salvador',
            'state': 'BA',
            'notificationDisabled': True,
        }
        mock_create_chk.return_value = (True, {
            'id': 'chk_complete_cust',
            'paymentLink': 'https://sandbox.asaas.com/c/complete'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-already-synced-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_already_complete',
            band_name='Banda Já Sincronizada',
            responsible_name='Responsável Completo',
            email='completo@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            postal_code='41720000',
            address='Avenida Paralela',
            address_number='500',
            province='Alphaville',
            city='Salvador',
            state='BA',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)

        # GET foi chamado
        mock_get_cust.assert_called_once_with('cus_already_complete')
        # PUT NÃO foi chamado porque os dados são compatíveis
        mock_update_cust.assert_not_called()
        mock_create_chk.assert_called_once()

    def test_45_html_renders_address_fields_and_dynamic_masks_bp_pend_32(self):
        """
        45. BP-PEND-32: Verifica renderização dos campos de endereço no HTML e script de máscaras dinâmicas.
        """
        resp = self.client.get(reverse('checkout') + '?plano=basico&ciclo=mensal')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Inputs de endereço presentes no formulário
        self.assertIn('id_postal_code', content)
        self.assertIn('id_address', content)
        self.assertIn('id_address_number', content)
        self.assertIn('id_complement', content)
        self.assertIn('id_province', content)
        self.assertIn('id_city', content)
        self.assertIn('id_state', content)

        # Labels e seções
        self.assertIn('Endereço de Faturamento', content)
        self.assertIn('CEP', content)
        self.assertIn('Endereço / Logradouro', content)
        self.assertIn('Número', content)
        self.assertIn('Complemento', content)
        self.assertIn('Bairro', content)
        self.assertIn('Cidade', content)
        self.assertIn('UF', content)

        # Scripts de máscara dinâmica presentes
        self.assertIn('id_postal_code', content)
        self.assertIn('id_phone', content)
        self.assertIn('id_cpf_cnpj', content)
        self.assertIn('id_state', content)
        self.assertIn('toUpperCase()', content)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_46_annual_card_installments_max_5x_for_basic_and_advanced(self, mock_create_chk):
        """
        46. Regra de Parcelamento Anual:
        - Básico Anual no cartão: installment.maxInstallmentCount == 5
        - Avançado Anual no cartão: installment.maxInstallmentCount == 5
        - Textos no HTML do checkout exibem 'até 5x' e não 'até 12x'
        - Anual + PIX permanece sem installment (à vista)
        """
        mock_create_chk.side_effect = [
            (True, {'id': 'chk_annual_5x_basic', 'paymentLink': 'https://sandbox.asaas.com/c/5x_basic'}),
            (True, {'id': 'chk_annual_5x_adv', 'paymentLink': 'https://sandbox.asaas.com/c/5x_adv'}),
        ]

        # Teste 1: Básico Anual no Cartão
        order_basic = SignupOrder.objects.create(
            external_reference='bp-ord-annual-basic-5x',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_basic_5x',
            band_name='Banda Básico 5x',
            responsible_name='Resp Básico',
            email='basic5x@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            postal_code='41720000',
            address='Rua Teste',
            address_number='1',
            province='Centro',
            city='Salvador',
            state='BA',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
        )

        ok_basic, _, _, _ = create_asaas_checkout_for_signup_order(order_basic, payment_method='CREDIT_CARD')
        self.assertTrue(ok_basic)
        payload_basic = mock_create_chk.call_args[0][0]
        self.assertEqual(payload_basic['installment']['maxInstallmentCount'], 5)
        self.assertNotIn('12', str(payload_basic.get('installment', {})))

        # Teste 2: Avançado Anual no Cartão
        order_adv = SignupOrder.objects.create(
            external_reference='bp-ord-annual-adv-5x',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_adv_5x',
            band_name='Banda Avançado 5x',
            responsible_name='Resp Avançado',
            email='adv5x@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            postal_code='41720000',
            address='Rua Teste',
            address_number='2',
            province='Centro',
            city='Salvador',
            state='BA',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE',
        )

        ok_adv, _, _, _ = create_asaas_checkout_for_signup_order(order_adv, payment_method='CREDIT_CARD')
        self.assertTrue(ok_adv)
        payload_adv = mock_create_chk.call_args[0][0]
        self.assertEqual(payload_adv['installment']['maxInstallmentCount'], 5)

        # Teste 3: Verificação dos textos no HTML do checkout para ciclo anual
        resp = self.client.get(reverse('checkout') + '?plano=avancado&ciclo=anual')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('parcelamento em até 5x no cartão', html)
        self.assertIn('Em até 5x', html)
        self.assertNotIn('até 12x', html)

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'update_customer')
    @patch.object(AsaasClient, 'get_customer')
    @patch.object(AsaasClient, 'create_checkout')
    def test_47_customer_sync_updates_if_notification_disabled_is_false_bp_pend_36(
        self, mock_create_chk, mock_get_cust, mock_update_cust
    ):
        """
        47. BP-PEND-36: Se o cliente remoto já possui endereço mas notificationDisabled não é True,
        dispara sincronização via PUT /v3/customers/{id} com notificationDisabled=True.
        """
        mock_get_cust.return_value = {
            'id': 'cus_notif_enabled',
            'name': 'Resp Notif',
            'email': 'notif@teste.com',
            'postalCode': '41720000',
            'address': 'Rua Teste',
            'addressNumber': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'notificationDisabled': False,  # Notificação habilitada no gateway -> deve sincronizar
        }
        mock_update_cust.return_value = (True, {'id': 'cus_notif_enabled', 'notificationDisabled': True})
        mock_create_chk.return_value = (True, {'id': 'chk_notif_sync', 'paymentLink': 'https://sandbox.asaas.com/c/chk'})

        order = SignupOrder.objects.create(
            external_reference='bp-ord-notif-sync-test',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_notif_enabled',
            band_name='Banda Notif Sync',
            responsible_name='Resp Notif',
            email='notif@teste.com',
            phone='71988887777',
            cpf_cnpj='12345678000195',
            postal_code='41720000',
            address='Rua Teste',
            address_number='10',
            province='Centro',
            city='Salvador',
            state='BA',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PENDENTE',
        )

        ok, link, _, _ = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)

        # Deve disparar PUT para desativar as notificações
        mock_update_cust.assert_called_once()
        upd_id, upd_payload = mock_update_cust.call_args[0]
        self.assertEqual(upd_id, 'cus_notif_enabled')
        self.assertTrue(upd_payload.get('notificationDisabled'))

    def test_48_subscription_created_first_legitimate_association_empty_id_bp_pend_37(self):
        """
        48. BP-PEND-37: Quando SUBSCRIPTION_CREATED chega com assinatura local ATIVA mas
        gateway_subscription_id vazio, a correlação determinística via checkoutSession ->
        SignupOrder -> BandSubscription deve associar o ID sem erro de segurança e sincronizar
        o SignupOrder.
        """
        from core.services.payments.asaas.webhooks import handle_subscription_event

        band = Band.objects.create(name='Banda Sub Created Teste', slug='banda-sub-created-teste')
        order = SignupOrder.objects.create(
            external_reference='bp-ord-sub-created-001',
            gateway_provider='ASAAS',
            gateway_checkout_id='66a81549-ac35-4845-ae18-1dd453e8c3d2',
            gateway_subscription_id=None,
            band_name='Banda Sub Created Teste',
            responsible_name='Responsavel',
            email='subcreated@teste.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PAGO',
            band=band,
        )
        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id=None,
            gateway_checkout_id='66a81549-ac35-4845-ae18-1dd453e8c3d2',
        )

        payload = {
            'event': 'SUBSCRIPTION_CREATED',
            'subscription': {
                'id': 'sub_k1cz0ghh8nu7lurz',
                'customer': 'cus_sub_created_test',
                'checkoutSession': '66a81549-ac35-4845-ae18-1dd453e8c3d2',
            }
        }

        ok, msg = handle_subscription_event(payload, 'SUBSCRIPTION_CREATED')
        self.assertTrue(ok)
        self.assertEqual(msg, 'SUBSCRIPTION_VINCULADA')

        sub.refresh_from_db()
        self.assertEqual(sub.gateway_subscription_id, 'sub_k1cz0ghh8nu7lurz')
        self.assertEqual(sub.status, 'ATIVO')

        order.refresh_from_db()
        self.assertEqual(order.gateway_subscription_id, 'sub_k1cz0ghh8nu7lurz')

    def test_49_subscription_created_idempotent_when_id_already_equals_bp_pend_37(self):
        """
        49. BP-PEND-37: Quando SUBSCRIPTION_CREATED chega e gateway_subscription_id local
        já é igual ao recebido, trata de forma idempotente sem retornar erro.
        """
        from core.services.payments.asaas.webhooks import handle_subscription_event

        band = Band.objects.create(name='Banda Sub Idemp Teste', slug='banda-sub-idemp-teste')
        order = SignupOrder.objects.create(
            external_reference='bp-ord-sub-idemp-001',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_sub_idemp_111',
            gateway_subscription_id='sub_idemp_111',
            band_name='Banda Sub Idemp Teste',
            responsible_name='Responsavel',
            email='subidemp@teste.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PAGO',
            band=band,
        )
        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_idemp_111',
            gateway_checkout_id='chk_sub_idemp_111',
        )

        payload = {
            'event': 'SUBSCRIPTION_CREATED',
            'subscription': {
                'id': 'sub_idemp_111',
                'customer': 'cus_sub_idemp_test',
                'checkoutSession': 'chk_sub_idemp_111',
            }
        }

        ok, msg = handle_subscription_event(payload, 'SUBSCRIPTION_CREATED')
        self.assertTrue(ok)
        self.assertEqual(msg, 'SUBSCRIPTION_SUBSCRIPTION_CREATED_SINCRONIZADA')

        sub.refresh_from_db()
        self.assertEqual(sub.gateway_subscription_id, 'sub_idemp_111')

    def test_50_subscription_created_blocks_different_id_on_active_subscription_bp_pend_37(self):
        """
        50. BP-PEND-37: Quando a assinatura local está ATIVA e já possui outro gateway_subscription_id
        diferente, mantém o bloqueio de segurança e não substitui.
        """
        from core.services.payments.asaas.webhooks import handle_subscription_event

        band = Band.objects.create(name='Banda Sub Sec Block', slug='banda-sub-sec-block')
        order = SignupOrder.objects.create(
            external_reference='bp-ord-sub-sec-001',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_sec_block_222',
            gateway_subscription_id='sub_original_active',
            band_name='Banda Sub Sec Block',
            responsible_name='Responsavel',
            email='subsec@teste.com',
            plan_type='BASICO',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            status='PAGO',
            band=band,
        )
        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            status='ATIVO',
            auto_renew=True,
            cancel_at_period_end=False,
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_original_active',
            gateway_checkout_id='chk_sec_block_222',
        )

        payload = {
            'event': 'SUBSCRIPTION_CREATED',
            'subscription': {
                'id': 'sub_different_attacker',
                'customer': 'cus_sec_block_test',
                'checkoutSession': 'chk_sec_block_222',
            }
        }

        ok, msg = handle_subscription_event(payload, 'SUBSCRIPTION_CREATED')
        self.assertFalse(ok)
        self.assertIn('SEGURANCA', msg)
        self.assertIn('nao permite substituicao arbitraria', msg)

        sub.refresh_from_db()
        self.assertEqual(sub.gateway_subscription_id, 'sub_original_active')

        order.refresh_from_db()
        self.assertEqual(order.gateway_subscription_id, 'sub_original_active')

    def test_51_annual_card_5x_installments_billing_records_bp_pend_39(self):
        """
        51. BP-PEND-39: Plano Básico Anual parcelado em 5x no cartão gera 5 BillingRecords de R$ 39,98.
        Nenhum registro com o valor agregado de R$ 199,90 pode coexistir.
        Soma total deve ser exatamente R$ 199,90.
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from core.services.payments.asaas.webhooks import reconcile_and_update_billing_record

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-5x-test',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_annual_5x_999',
            band_name='Banda Anual 5x Teste',
            responsible_name='Vitor',
            email='vitor5x@teste.com',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
        )

        # 1. Evento CHECKOUT_PAID para provisionamento com a 1ª parcela
        payload_checkout_paid = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_5x_999',
                'externalReference': 'bp-ord-annual-5x-test',
                'customer': 'cus_annual_5x_cust',
            },
            'payment': {
                'id': 'pay_inst_1',
                'value': '39.98',
                'billingType': 'CREDIT_CARD',
                'installment': 'inst_group_777',
                'installmentNumber': 1,
            }
        }

        success, msg, band = process_checkout_paid_event(payload_checkout_paid)
        self.assertTrue(success)
        self.assertIsNotNone(band)

        sub = BandSubscription.objects.get(band=band)
        self.assertEqual(sub.billing_cycle, 'ANUAL')
        self.assertFalse(sub.auto_renew)

        # 2. Webhooks subsequentes / conciliação de cada parcela (1 a 5)
        # Parcela 1: reconciliação via webhook
        reconcile_and_update_billing_record(
            {
                'event': 'PAYMENT_CONFIRMED',
                'payment': {
                    'id': 'pay_inst_1',
                    'value': '39.98',
                    'installment': 'inst_group_777',
                    'installmentNumber': 1,
                    'dueDate': '2026-09-08',
                    'externalReference': 'bp-ord-annual-5x-test',
                    'checkoutSession': 'chk_annual_5x_999',
                }
            },
            'PAYMENT_CONFIRMED'
        )

        # Parcelas 2 a 5
        due_dates = ['2026-10-08', '2026-11-08', '2026-12-08', '2027-01-08']
        for idx, due_d in enumerate(due_dates, start=2):
            p_id = f'pay_inst_{idx}'
            reconcile_and_update_billing_record(
                {
                    'event': 'PAYMENT_CONFIRMED',
                    'payment': {
                        'id': p_id,
                        'value': '39.98',
                        'installment': 'inst_group_777',
                        'installmentNumber': idx,
                        'dueDate': due_d,
                        'externalReference': 'bp-ord-annual-5x-test',
                        'checkoutSession': 'chk_annual_5x_999',
                    }
                },
                'PAYMENT_CONFIRMED'
            )

        records = BillingRecord.objects.filter(subscription=sub).order_by('installment_number')
        self.assertEqual(records.count(), 5)

        total_local = sum(r.amount for r in records)
        self.assertEqual(total_local, Decimal('199.90'))

        for idx, r in enumerate(records, start=1):
            self.assertEqual(r.amount, Decimal('39.98'))
            self.assertEqual(r.installment_number, idx)
            self.assertEqual(r.gateway_payment_id, f'pay_inst_{idx}')

        # Garantir que NÃO existe nenhum registro com valor total de 199.90
        self.assertFalse(BillingRecord.objects.filter(subscription=sub, amount=Decimal('199.90')).exists())

    def test_52_annual_card_1x_billing_records_bp_pend_39(self):
        """
        52. BP-PEND-39: Plano Básico Anual no cartão à vista (1x) gera exatamente 1 BillingRecord de R$ 199,90.
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from core.services.payments.asaas.webhooks import reconcile_and_update_billing_record

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-1x-test',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_annual_1x_888',
            band_name='Banda Anual 1x Teste',
            responsible_name='Lucas',
            email='lucas1x@teste.com',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
        )

        payload_checkout_paid = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_1x_888',
                'externalReference': 'bp-ord-annual-1x-test',
                'customer': 'cus_annual_1x_cust',
            },
            'payment': {
                'id': 'pay_single_1',
                'value': '199.90',
                'billingType': 'CREDIT_CARD',
            }
        }

        success, msg, band = process_checkout_paid_event(payload_checkout_paid)
        self.assertTrue(success)

        sub = BandSubscription.objects.get(band=band)
        records = BillingRecord.objects.filter(subscription=sub)
        self.assertEqual(records.count(), 1)
        record = records.first()
        self.assertEqual(record.amount, Decimal('199.90'))
        self.assertIsNone(record.installment_number)
        self.assertEqual(record.gateway_payment_id, 'pay_single_1')

    def test_53_annual_pix_billing_records_bp_pend_39(self):
        """
        53. BP-PEND-39: Plano Básico Anual no PIX à vista gera exatamente 1 BillingRecord de R$ 199,90.
        """
        from core.services.payments.provisioning import process_checkout_paid_event

        order = SignupOrder.objects.create(
            external_reference='bp-ord-annual-pix-39',
            gateway_provider='ASAAS',
            gateway_checkout_id='chk_annual_pix_777',
            band_name='Banda Anual Pix 39',
            responsible_name='Rodrigo',
            email='rodrigo39@teste.com',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
        )

        payload_checkout_paid = {
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_pix_777',
                'externalReference': 'bp-ord-annual-pix-39',
                'customer': 'cus_annual_pix_39',
            },
            'payment': {
                'id': 'pay_pix_annual_39',
                'value': '199.90',
                'billingType': 'PIX',
            }
        }

        success, msg, band = process_checkout_paid_event(payload_checkout_paid)
        self.assertTrue(success)

        sub = BandSubscription.objects.get(band=band)
        records = BillingRecord.objects.filter(subscription=sub)
        self.assertEqual(records.count(), 1)
        record = records.first()
        self.assertEqual(record.amount, Decimal('199.90'))
        self.assertIsNone(record.installment_number)
        self.assertEqual(record.payment_method, 'PIX')
        self.assertEqual(record.gateway_payment_id, 'pay_pix_annual_39')

    @override_settings(PAYMENTS_LIVE_ENABLED=True, ASAAS_API_KEY='test_api_key', ASAAS_ENVIRONMENT='sandbox')
    @patch.object(AsaasClient, 'create_checkout')
    def test_54_checkout_payload_includes_band_name_in_item_and_subscription_description(self, mock_create_chk):
        """
        54. Identificar banda nas assinaturas e cobranças do Asaas:
        O payload de checkout para cartão recorrente deve incluir o nome da banda e plano
        na descrição da assinatura e do item, mantendo externalReference único intacto.
        """
        mock_create_chk.return_value = (True, {
            'id': 'chk_band_desc_123',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/band123'
        })

        order = SignupOrder.objects.create(
            external_reference='bp-ord-multi-band-1',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_same_owner_123',
            band_name='Banda Fulana Acústico',
            responsible_name='Carla Empresaria',
            email='carla@empresaria.com',
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            amount=Decimal('49.90'),
            status='PENDENTE',
        )

        ok, link, data, err = create_asaas_checkout_for_signup_order(order, payment_method='CREDIT_CARD')
        self.assertTrue(ok)

        sent_payload = mock_create_chk.call_args[0][0]
        # externalReference intacto
        self.assertEqual(sent_payload['externalReference'], 'bp-ord-multi-band-1')
        # Item com nome e descrição contendo a banda
        self.assertEqual(sent_payload['items'][0]['name'], 'Backstage Pro — Banda Fulana Acústico')
        self.assertEqual(sent_payload['items'][0]['description'], 'Backstage Pro — Banda Fulana Acústico — Avançado Mensal')
        # Subscription com descrição legível
        self.assertEqual(sent_payload['subscription']['description'], 'Backstage Pro — Banda Fulana Acústico — Avançado Mensal')

    @patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription')
    @patch('core.services.payments.asaas.client.AsaasClient.get_subscription')
    def test_55_cancel_subscription_selects_strictly_band_linked_subscription(self, mock_get_sub, mock_cancel_sub):
        """
        55. Cancelamento por banda seleciona a assinatura da banda ativa, mesmo quando a mesma
        empresária possui múltiplas bandas com o mesmo valor contratado.
        """
        from django.contrib.auth import get_user_model
        from datetime import date
        from core.models import UserBandMembership
        User = get_user_model()

        owner = User.objects.create_user(
            username='empresaria_multi',
            email='multi@empresaria.com',
            password='testpass123_password'
        )

        band_a = Band.objects.create(name='Banda Alfa Show', slug='banda-alfa-show')
        band_b = Band.objects.create(name='Banda Beta Show', slug='banda-beta-show')

        UserBandMembership.objects.create(user=owner, band=band_a, role='EMPRESARIO', is_active=True)
        UserBandMembership.objects.create(user=owner, band=band_b, role='EMPRESARIO', is_active=True)

        sub_a = BandSubscription.objects.create(
            band=band_a,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            next_due_date=date(2026, 11, 8),
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_alfa_111',
            gateway_customer_id='cus_shared_owner',
            auto_renew=True,
            cancel_at_period_end=False
        )

        sub_b = BandSubscription.objects.create(
            band=band_b,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            next_due_date=date(2026, 11, 8),
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_beta_222',
            gateway_customer_id='cus_shared_owner',
            auto_renew=True,
            cancel_at_period_end=False
        )

        # Simula cancelamento da Banda Alfa
        mock_get_sub.return_value = {
            'id': 'sub_alfa_111',
            'customer': 'cus_shared_owner',
            'status': 'ACTIVE',
            'deleted': False
        }
        mock_cancel_sub.return_value = (True, {'deleted': True})

        client = Client()
        client.force_login(owner)

        resp = client.post(f'/{band_a.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Confirma que cancelou APENAS sub_alfa_111
        mock_cancel_sub.assert_called_once_with('sub_alfa_111')

        sub_a.refresh_from_db()
        sub_b.refresh_from_db()

        # Banda Alfa teve cancelamento agendado
        self.assertTrue(sub_a.cancel_at_period_end)
        self.assertFalse(sub_a.auto_renew)

        # Banda Beta PERMANECE 100% INTACTA
        self.assertFalse(sub_b.cancel_at_period_end)
        self.assertTrue(sub_b.auto_renew)



