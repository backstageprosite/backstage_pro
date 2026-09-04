import json
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from core.models import (
    Band, BandSubscription, BillingRecord, SignupOrder,
    PaymentWebhookEvent, BandActivationToken
)
from core.services.payments.base import (
    AsaasConfig, normalize_band_slug, generate_unique_band_slug,
    calculate_next_billing_date
)
from core.services.payments.activation import (
    create_band_activation_token, verify_activation_token, generate_activation_token_pair
)
from core.services.payments.asaas.webhooks import handle_asaas_webhook_payload


class AsaasFoundationTests(TestCase):
    def test_asaas_config_sandbox_and_production_urls(self):
        """1, 8, 9, 13. Testar URL Sandbox correta e URLs de producao sem segredos hardcoded."""
        with override_settings(ASAAS_ENVIRONMENT='sandbox', ASAAS_BASE_URL=None, ASAAS_API_KEY=None):
            cfg = AsaasConfig.from_settings()
            self.assertEqual(cfg.environment, 'sandbox')
            self.assertEqual(cfg.base_url, 'https://api-sandbox.asaas.com/v3')
            self.assertFalse(cfg.is_configured())

        with override_settings(ASAAS_ENVIRONMENT='production', ASAAS_BASE_URL=None, ASAAS_API_KEY=None):
            cfg_prod = AsaasConfig.from_settings()
            self.assertEqual(cfg_prod.environment, 'production')
            self.assertEqual(cfg_prod.base_url, 'https://api.asaas.com/v3')

    def test_slug_generation_and_normalization(self):
        """11, 14. Testar normalizacao de slug: 'Banda Mambolada' -> mambolada, 'Duas Medidas' -> duasmedidas."""
        self.assertEqual(normalize_band_slug("Banda Mambolada"), "mambolada")
        self.assertEqual(normalize_band_slug("banda mambolada"), "mambolada")
        self.assertEqual(normalize_band_slug("Duas Medidas"), "duasmedidas")
        self.assertEqual(normalize_band_slug("Banda Calypso!"), "calypso")
        self.assertEqual(normalize_band_slug("Banda É o Tchan"), "eotchan")

    def test_slug_collision_handling(self):
        """11. Colisao de slug: mambolada -> mambolada2 -> mambolada3."""
        Band.objects.create(name="Banda Mambolada", slug="mambolada")
        slug2 = generate_unique_band_slug("Banda Mambolada")
        self.assertEqual(slug2, "mambolada2")

        Band.objects.create(name="Mambolada 2", slug=slug2)
        slug3 = generate_unique_band_slug("Banda Mambolada")
        self.assertEqual(slug3, "mambolada3")

    def test_activation_token_hashing_and_lifecycle(self):
        """7, 15. Token de ativacao nao armazenado em texto puro, validade, expiracao e uso unico."""
        band = Band.objects.create(name="Banda Teste", slug="bandateste")
        activation, raw_token = create_band_activation_token(
            band=band,
            email="produtor@teste.com",
            responsible_name="Produtor Teste",
            valid_hours=48
        )

        # 1. Verifica que no banco esta apenas o HASH
        self.assertNotEqual(activation.token_hash, raw_token)
        expected_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        self.assertEqual(activation.token_hash, expected_hash)

        # 2. Token valido funciona
        valid, code, act = verify_activation_token(raw_token)
        self.assertTrue(valid)
        self.assertEqual(code, "OK")
        self.assertEqual(act.id, activation.id)

        # 3. Marcar como usado
        activation.used_at = timezone.now()
        activation.save()
        valid_used, code_used, _ = verify_activation_token(raw_token)
        self.assertFalse(valid_used)
        self.assertEqual(code_used, "TOKEN_JA_UTILIZADO")

        # 4. Token expirado
        activation.used_at = None
        activation.expires_at = timezone.now() - timedelta(minutes=1)
        activation.save()
        valid_exp, code_exp, _ = verify_activation_token(raw_token)
        self.assertFalse(valid_exp)
        self.assertEqual(code_exp, "TOKEN_EXPIRADO")

    def test_billing_date_calculation_calendar_rules(self):
        """19. Calculo de data-base fixa, fim de mes e ano bissexto."""
        # 1. Mensal padrao (dia 03)
        dt1 = date(2026, 9, 3)
        next_dt1 = calculate_next_billing_date(dt1, 'MENSAL', 1)
        self.assertEqual(next_dt1, date(2026, 10, 3))

        # 2. Fim de mes (dia 31 em janeiro -> fevereiro em ano normal)
        dt_jan31 = date(2026, 1, 31)
        next_feb = calculate_next_billing_date(dt_jan31, 'MENSAL', 1)
        self.assertEqual(next_feb, date(2026, 2, 28))

        # 3. Ano bissexto (2028 e bissexto -> 29 de fevereiro)
        dt_leap = date(2028, 1, 31)
        next_leap_feb = calculate_next_billing_date(dt_leap, 'MENSAL', 1)
        self.assertEqual(next_leap_feb, date(2028, 2, 29))

        # 4. Anual
        dt_anual = date(2026, 9, 3)
        next_anual = calculate_next_billing_date(dt_anual, 'ANUAL', 1)
        self.assertEqual(next_anual, date(2027, 9, 3))

    def test_checkout_paid_provisioning_and_two_level_idempotency(self):
        """6, 8, 10, 14, 15, 16. Idempotencia Nivel 1 (evento duplicado) e Nivel 2 (ordem duplicada)."""
        # Criar SignupOrder previo
        order = SignupOrder.objects.create(
            external_reference="ord_test_123456",
            gateway_checkout_id="chk_asaas_999",
            band_name="Banda Axé Bahia",
            responsible_name="Empresário Axé",
            cpf_cnpj="12345678901",
            email="empresario@axebahia.com",
            phone="71999998888",
            plan_type="AVANCADO",
            billing_cycle="MENSAL",
            amount=Decimal("49.90"),
            status="PENDENTE"
        )

        payload = {
            "id": "evt_checkout_paid_001",
            "event": "CHECKOUT_PAID",
            "checkout": {
                "id": "chk_asaas_999",
                "externalReference": "ord_test_123456",
                "customer": "cus_asaas_111",
                "subscription": "sub_asaas_222"
            },
            "payment": {
                "id": "pay_asaas_333"
            }
        }

        # 1. Primeiro processamento -> Cria Band, Subscription, BillingRecord e Token (Sem criar User)
        success1, msg1 = handle_asaas_webhook_payload(payload)
        self.assertTrue(success1)
        self.assertEqual(msg1, "PROVISIONADO")

        order.refresh_from_db()
        self.assertEqual(order.status, "PAGO")
        self.assertIsNotNone(order.band)
        self.assertEqual(order.band.slug, "axebahia")
        self.assertEqual(order.band.users.count(), 0) # REGRA: Não cria User ainda!

        sub = order.band.subscriptions.first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.gateway_subscription_id, "sub_asaas_222")
        self.assertEqual(sub.gateway_checkout_id, "chk_asaas_999")
        self.assertEqual(sub.status, "ATIVO")

        bill = order.band.billing_records.first()
        self.assertIsNotNone(bill)
        self.assertEqual(bill.status, "PAGO")
        self.assertEqual(bill.gateway_payment_id, "pay_asaas_333")

        tokens = BandActivationToken.objects.filter(band=order.band)
        self.assertEqual(tokens.count(), 1)
        self.assertTrue(tokens.first().is_valid())

        # 2. Idempotência Nível 1: Mesmo event_id repetido
        success2, msg2 = handle_asaas_webhook_payload(payload)
        self.assertTrue(success2)
        self.assertEqual(msg2, "EVENTO_JA_PROCESSADO")
        self.assertEqual(Band.objects.filter(name="Banda Axé Bahia").count(), 1)

        # 3. Idempotência Nível 2: Evento diferente para a mesma ordem já provisionada
        payload_diff_event = {
            "id": "evt_checkout_paid_002_diff",
            "event": "CHECKOUT_PAID",
            "checkout": {
                "id": "chk_asaas_999",
                "externalReference": "ord_test_123456",
            }
        }
        success3, msg3 = handle_asaas_webhook_payload(payload_diff_event)
        self.assertTrue(success3)
        self.assertEqual(msg3, "JA_PROVISIONADO")
        self.assertEqual(Band.objects.filter(name="Banda Axé Bahia").count(), 1)

    def test_legacy_and_manual_subscriptions_compatibility(self):
        """4, 5, 22. Assinaturas manuais/legadas sem gateway continuam totalmente validas."""
        band_manual = Band.objects.create(name="Banda Manual", slug="bandamanual")
        sub_manual = BandSubscription.objects.create(
            band=band_manual,
            plan_name="Plano Manual",
            billing_cycle="MENSAL",
            contracted_value=Decimal("150.00"),
            status="ATIVO",
            payment_method_preference="PIX"
        )
        self.assertIsNone(sub_manual.gateway_provider)
        self.assertIsNone(sub_manual.gateway_subscription_id)

        bill_manual = BillingRecord.objects.create(
            subscription=sub_manual,
            band=band_manual,
            reference_period="Setembro/2026",
            amount=Decimal("150.00"),
            due_date=date(2026, 9, 10),
            status="PAGO",
            payment_method="PIX"
        )
        self.assertIsNone(bill_manual.gateway_provider)
        self.assertIsNone(bill_manual.gateway_payment_id)

    def test_asaas_client_user_agent_and_no_secrets_in_logs(self):
        """ASAAS-02B: User-Agent presente no formato BackstagePro/1.0 (Django; <env>) e sem segredos expostos."""
        from core.services.payments.asaas.client import AsaasClient
        with override_settings(ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='secret_key_123'):
            client = AsaasClient()
            headers = client.get_headers()
            self.assertEqual(headers["User-Agent"], "BackstagePro/1.0 (Django; sandbox)")
            self.assertIn("application/json", headers["Content-Type"])
            self.assertIn("charset=utf-8", headers["Content-Type"])
            self.assertEqual(headers["access_token"], "secret_key_123")

    def test_billing_record_idempotency_multiple_events_same_payment(self):
        """ASAAS-02B: Eventos diferentes com o mesmo payment_id (ex: PAYMENT_CONFIRMED e PAYMENT_RECEIVED) atualizam a MESMA fatura."""
        band = Band.objects.create(name="Banda Samba", slug="samba")
        sub = BandSubscription.objects.create(
            band=band,
            plan_name="Avançado Mensal",
            billing_cycle="MENSAL",
            contracted_value=Decimal("49.90"),
            gateway_provider="ASAAS",
            gateway_subscription_id="sub_samba_100",
            status="ATIVO"
        )

        # 1. Primeiro evento: PAYMENT_CONFIRMED
        payload1 = {
            "id": "evt_conf_1",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_samba_999",
                "subscription": "sub_samba_100",
                "value": "49.90"
            }
        }
        success1, msg1 = handle_asaas_webhook_payload(payload1)
        self.assertTrue(success1)
        self.assertEqual(BillingRecord.objects.filter(gateway_payment_id="pay_samba_999").count(), 1)
        bill1 = BillingRecord.objects.get(gateway_payment_id="pay_samba_999")
        self.assertEqual(bill1.status, "PAGO")
        self.assertEqual(bill1.gateway_event_status, "PAYMENT_CONFIRMED")

        # 2. Segundo evento diferente com o MESMO payment.id: PAYMENT_RECEIVED
        payload2 = {
            "id": "evt_rec_2",
            "event": "PAYMENT_RECEIVED",
            "payment": {
                "id": "pay_samba_999",
                "subscription": "sub_samba_100",
                "value": "49.90"
            }
        }
        success2, msg2 = handle_asaas_webhook_payload(payload2)
        self.assertTrue(success2)
        # OBRIGATÓRIO: Apenas 1 BillingRecord no banco
        self.assertEqual(BillingRecord.objects.filter(gateway_payment_id="pay_samba_999").count(), 1)
        bill1.refresh_from_db()
        self.assertEqual(bill1.gateway_event_status, "PAYMENT_RECEIVED")

    def test_billing_date_calculation_no_drift_anchor_tests(self):
        """ASAAS-02B: Data-base fixa sem drift em sequências de meses (31/01 -> 28/02 -> 31/03 -> 30/04 -> 31/05)."""
        anchor = date(2027, 1, 31)
        self.assertEqual(calculate_next_billing_date(anchor, 'MENSAL', 1), date(2027, 2, 28))
        self.assertEqual(calculate_next_billing_date(anchor, 'MENSAL', 2), date(2027, 3, 31))
        self.assertEqual(calculate_next_billing_date(anchor, 'MENSAL', 3), date(2027, 4, 30))
        self.assertEqual(calculate_next_billing_date(anchor, 'MENSAL', 4), date(2027, 5, 31))

        # Ano bissexto 2028:
        anchor_leap = date(2028, 1, 31)
        self.assertEqual(calculate_next_billing_date(anchor_leap, 'MENSAL', 1), date(2028, 2, 29))
        self.assertEqual(calculate_next_billing_date(anchor_leap, 'MENSAL', 2), date(2028, 3, 31))

        # Âncora dia 30: 30/01 -> 28/02 -> 30/03
        anchor_30 = date(2027, 1, 30)
        self.assertEqual(calculate_next_billing_date(anchor_30, 'MENSAL', 1), date(2027, 2, 28))
        self.assertEqual(calculate_next_billing_date(anchor_30, 'MENSAL', 2), date(2027, 3, 30))

    def test_signup_order_unique_checkout_constraint(self):
        """ASAAS-03: Valida constraint de unicidade de (gateway_provider, gateway_checkout_id) no SignupOrder."""
        from django.db import IntegrityError
        SignupOrder.objects.create(
            external_reference="ord_chk_1",
            gateway_provider="ASAAS",
            gateway_checkout_id="chk_unique_123",
            band_name="Banda Um",
            responsible_name="Resp Um",
            email="um@teste.com",
            amount=Decimal("49.90")
        )

        with self.assertRaises(IntegrityError):
            SignupOrder.objects.create(
                external_reference="ord_chk_2",
                gateway_provider="ASAAS",
                gateway_checkout_id="chk_unique_123",
                band_name="Banda Dois",
                responsible_name="Resp Dois",
                email="dois@teste.com",
                amount=Decimal("49.90")
            )

    def test_asaas_client_utf8_encoding_preserves_accents(self):
        """ASAAS-04 (PASSO 3): Garante que 'Básico', 'Avançado' e 'Assinatura' não sofrem corrupção UTF-8 para '?'."""
        from core.services.payments.asaas.client import AsaasClient
        payload = {
            "name": "Backstage Pro Básico",
            "description": "Assinatura mensal Backstage Pro — Avançado",
            "items": [
                {"name": "Plano Básico", "category": "Assinatura"}
            ]
        }
        encoded = AsaasClient.encode_payload(payload)
        decoded = json.loads(encoded.decode('utf-8'))

        self.assertEqual(decoded["name"], "Backstage Pro Básico")
        self.assertIn("Básico", decoded["name"])
        self.assertNotIn("?", decoded["name"])

        self.assertEqual(decoded["description"], "Assinatura mensal Backstage Pro — Avançado")
        self.assertIn("Avançado", decoded["description"])
        self.assertIn("—", decoded["description"])
        self.assertNotIn("?", decoded["description"])

        self.assertEqual(decoded["items"][0]["category"], "Assinatura")
        self.assertNotIn("?", decoded["items"][0]["category"])

    def test_webhook_endpoint_security_and_validation(self):
        """ASAAS-05: Testes de seguranca e validacao do endpoint /webhooks/asaas/."""
        from django.test import Client
        client = Client()
        webhook_url = '/webhooks/asaas/'

        valid_token = 'secret_webhook_token_test_1234567890'
        with override_settings(ASAAS_WEBHOOK_TOKEN=valid_token):
            payload = {'id': 'evt_test_sec_1', 'event': 'CHECKOUT_CREATED', 'checkout': {'id': 'chk_sec_1'}}

            # 1. GET nao permitido -> 405
            res_get = client.get(webhook_url)
            self.assertEqual(res_get.status_code, 405)

            # 2. POST sem asaas-access-token -> 401
            res_no_token = client.post(webhook_url, data=json.dumps(payload), content_type='application/json')
            self.assertEqual(res_no_token.status_code, 401)

            # 3. POST com token incorreto -> 401
            res_wrong_token = client.post(
                webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN='wrong_token_abc'
            )
            self.assertEqual(res_wrong_token.status_code, 401)

            # 4. JSON invalido -> 400
            res_invalid_json = client.post(
                webhook_url,
                data='{invalid-json',
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN=valid_token
            )
            self.assertEqual(res_invalid_json.status_code, 400)

            # 5. Payload sem id -> 400
            res_no_id = client.post(
                webhook_url,
                data=json.dumps({'event': 'CHECKOUT_CREATED'}),
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN=valid_token
            )
            self.assertEqual(res_no_id.status_code, 400)

            # 6. Payload sem event -> 400
            res_no_event = client.post(
                webhook_url,
                data=json.dumps({'id': 'evt_no_event_1'}),
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN=valid_token
            )
            self.assertEqual(res_no_event.status_code, 400)

            # 7. POST com token correto -> 200
            res_ok = client.post(
                webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN=valid_token
            )
            self.assertEqual(res_ok.status_code, 200)
            self.assertFalse(res_ok.json().get('duplicate'))

            # 8. Token NUNCA aparece na resposta
            self.assertNotIn(valid_token, res_ok.content.decode('utf-8'))

            # 9. Idempotencia de persistencia (mesmo event.id enviado duas vezes -> 1 PaymentWebhookEvent)
            res_dup = client.post(
                webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_ASAAS_ACCESS_TOKEN=valid_token
            )
            self.assertEqual(res_dup.status_code, 200)
            self.assertTrue(res_dup.json().get('duplicate'))
            self.assertEqual(PaymentWebhookEvent.objects.filter(gateway_event_id='evt_test_sec_1').count(), 1)

    def test_webhook_checkout_lifecycle_and_expired_status(self):
        """ASAAS-05: Testar CHECKOUT_CREATED, CHECKOUT_CANCELED e CHECKOUT_EXPIRED mantendo e alterando status."""
        from django.core.management import call_command

        # 1. CHECKOUT_CREATED -> mantem PENDENTE
        order1 = SignupOrder.objects.create(
            external_reference='ord_chk_life_1',
            gateway_checkout_id='chk_life_1',
            band_name='Banda Criada',
            responsible_name='Resp 1',
            email='resp1@teste.com',
            amount=Decimal('49.90'),
            status='PENDENTE'
        )
        PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_created_1',
            event_type='CHECKOUT_CREATED',
            payload={'id': 'evt_created_1', 'event': 'CHECKOUT_CREATED', 'checkout': {'id': 'chk_life_1'}}
        )
        call_command('process_asaas_webhooks', event_id='evt_created_1')
        order1.refresh_from_db()
        self.assertEqual(order1.status, 'PENDENTE')

        # 2. CHECKOUT_CANCELED -> vai para CANCELADO
        order2 = SignupOrder.objects.create(
            external_reference='ord_chk_life_2',
            gateway_checkout_id='chk_life_2',
            band_name='Banda Cancelada',
            responsible_name='Resp 2',
            email='resp2@teste.com',
            amount=Decimal('49.90'),
            status='PENDENTE'
        )
        PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_canceled_1',
            event_type='CHECKOUT_CANCELED',
            payload={'id': 'evt_canceled_1', 'event': 'CHECKOUT_CANCELED', 'checkout': {'id': 'chk_life_2'}}
        )
        call_command('process_asaas_webhooks', event_id='evt_canceled_1')
        order2.refresh_from_db()
        self.assertEqual(order2.status, 'CANCELADO')

        # 3. CHECKOUT_EXPIRED -> vai para EXPIRADO (NAO CANCELADO)
        order3 = SignupOrder.objects.create(
            external_reference='ord_chk_life_3',
            gateway_checkout_id='chk_life_3',
            band_name='Banda Expirada',
            responsible_name='Resp 3',
            email='resp3@teste.com',
            amount=Decimal('49.90'),
            status='PENDENTE'
        )
        PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_expired_1',
            event_type='CHECKOUT_EXPIRED',
            payload={'id': 'evt_expired_1', 'event': 'CHECKOUT_EXPIRED', 'checkout': {'id': 'chk_life_3'}}
        )
        call_command('process_asaas_webhooks', event_id='evt_expired_1')
        order3.refresh_from_db()
        self.assertEqual(order3.status, 'EXPIRADO')

    def test_webhook_checkout_paid_full_activation_isolation(self):
        """ASAAS-05: Apos processar CHECKOUT_PAID: Band=1, Sub=1, Bill=1, Token=1, User=0, Email=0. Protecao contra duplicidade."""
        from django.core.management import call_command
        from django.core import mail
        from django.contrib.auth import get_user_model
        User = get_user_model()

        order = SignupOrder.objects.create(
            external_reference='ord_canon_001',
            gateway_checkout_id='chk_canon_001',
            band_name='Banda Canonica',
            responsible_name='Responsavel Canonico',
            email='canonico@teste.com',
            amount=Decimal('79.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PENDENTE'
        )

        evt_paid = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_paid_canon_1',
            event_type='CHECKOUT_PAID',
            payload={
                'id': 'evt_paid_canon_1',
                'event': 'CHECKOUT_PAID',
                'checkout': {
                    'id': 'chk_canon_001',
                    'externalReference': 'ord_canon_001',
                    'customer': 'cus_canon_1',
                    'subscription': 'sub_canon_1'
                },
                'payment': {'id': 'pay_canon_1'}
            }
        )

        call_command('process_asaas_webhooks', event_id='evt_paid_canon_1')

        # 1. Validar SignupOrder atualizado
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAGO')
        self.assertIsNotNone(order.band)
        self.assertIsNotNone(order.provisioned_at)

        # 2. Validar Band criada (1)
        self.assertEqual(Band.objects.filter(name='Banda Canonica').count(), 1)
        band = order.band

        # 3. Validar BandSubscription criada (1)
        self.assertEqual(BandSubscription.objects.filter(band=band).count(), 1)
        sub = BandSubscription.objects.get(band=band)
        self.assertEqual(sub.gateway_subscription_id, 'sub_canon_1')

        # 4. Validar BillingRecord criada (1)
        self.assertEqual(BillingRecord.objects.filter(band=band).count(), 1)
        bill = BillingRecord.objects.get(band=band)
        self.assertEqual(bill.status, 'PAGO')
        self.assertEqual(bill.gateway_payment_id, 'pay_canon_1')

        # 5. Validar BandActivationToken criado (1)
        self.assertEqual(BandActivationToken.objects.filter(band=band).count(), 1)

        # 6. REGRA RIGIDA: User NAO criado (0)
        self.assertEqual(User.objects.filter(email='canonico@teste.com').count(), 0)
        self.assertEqual(band.users.count(), 0)

        # 7. REGRA RIGIDA: E-mail NAO enviado (0)
        self.assertEqual(len(mail.outbox), 0)

        # 8. Proteção contra dois CHECKOUT_PAID para o mesmo checkout ID
        evt_paid_duplicate = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_paid_canon_2_diff_id',
            event_type='CHECKOUT_PAID',
            payload={
                'id': 'evt_paid_canon_2_diff_id',
                'event': 'CHECKOUT_PAID',
                'checkout': {
                    'id': 'chk_canon_001',
                    'externalReference': 'ord_canon_001',
                    'customer': 'cus_canon_1',
                    'subscription': 'sub_canon_1'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_paid_canon_2_diff_id')

        # Continua havendo exatamente 1 de cada registro
        self.assertEqual(Band.objects.filter(name='Banda Canonica').count(), 1)
        self.assertEqual(BandSubscription.objects.filter(band=band).count(), 1)
        self.assertEqual(BillingRecord.objects.filter(band=band).count(), 1)
        self.assertEqual(BandActivationToken.objects.filter(band=band).count(), 1)

    def test_subscription_and_payment_reconciliation_safeguards(self):
        """ASAAS-05: Reconciliacao segura de subscription e payment sem adivinhar ou duplicar."""
        from django.core.management import call_command

        band = Band.objects.create(name='Banda Jazz', slug='jazz')
        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Avancado Mensal',
            billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'),
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_jazz_1',
            gateway_customer_id='cus_jazz_1',
            status='ATIVO'
        )

        # 1. SUBSCRIPTION_INACTIVATED -> marca sub como CANCELADO
        evt_sub_del = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_sub_inact_1',
            event_type='SUBSCRIPTION_INACTIVATED',
            payload={'id': 'evt_sub_inact_1', 'event': 'SUBSCRIPTION_INACTIVATED', 'subscription': {'id': 'sub_jazz_1'}}
        )
        call_command('process_asaas_webhooks', event_id='evt_sub_inact_1')
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'CANCELADO')

        # 2. Evento de pagamento com vinculo univoco
        evt_pay = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_pay_conf_jazz',
            event_type='PAYMENT_CONFIRMED',
            payload={
                'id': 'evt_pay_conf_jazz',
                'event': 'PAYMENT_CONFIRMED',
                'payment': {
                    'id': 'pay_jazz_100',
                    'subscription': 'sub_jazz_1',
                    'value': '49.90'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_pay_conf_jazz')
        self.assertEqual(BillingRecord.objects.filter(gateway_payment_id='pay_jazz_100').count(), 1)

        # 3. Evento ambiguo/desconhecido de pagamento sem vinculo nao quebra nem cria registros aleatorios
        evt_pay_ambiguous = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_pay_ambig_1',
            event_type='PAYMENT_CONFIRMED',
            payload={
                'id': 'evt_pay_ambig_1',
                'event': 'PAYMENT_CONFIRMED',
                'payment': {
                    'id': 'pay_unknown_999',
                    'value': '99.90'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_pay_ambig_1')
        evt_pay_ambiguous.refresh_from_db()
        self.assertFalse(evt_pay_ambiguous.processed)
        self.assertIsNotNone(evt_pay_ambiguous.error_message)

        # 4. Evento desconhecido generico e persistido e ignorado com seguranca
        evt_unknown = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_future_feature_1',
            event_type='TRANSFER_CONFIRMED',
            payload={'id': 'evt_future_feature_1', 'event': 'TRANSFER_CONFIRMED', 'transfer': {'id': 'tx_123'}}
        )
        call_command('process_asaas_webhooks', event_id='evt_future_feature_1')
        evt_unknown.refresh_from_db()
        self.assertTrue(evt_unknown.processed)
        self.assertEqual(evt_unknown.error_message, None)

    def test_create_asaas_sandbox_checkout_guardrails_and_execution(self):
        """ASAAS-06: Validar travas de ambiente (staging + sandbox), criacao correta do SignupOrder e payload Asaas."""
        from unittest.mock import patch, MagicMock
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # 1. Trava em producao -> deve falhar
        with override_settings(DJANGO_ENV='production', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='key_123'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_sandbox_checkout')
            self.assertIn('so pode ser executado no ambiente de homologacao', str(cm.exception))

        # 2. Trava em staging com ASAAS_ENVIRONMENT=production -> deve falhar
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='production', ASAAS_API_KEY='key_123'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_sandbox_checkout')
            self.assertIn('so pode ser executado no ambiente de homologacao', str(cm.exception))

        # 3. Execucao autorizada em staging + sandbox com mock da API Asaas
        mock_response_data = {
            'id': 'chk_sandbox_test_777',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/test777',
            'items': [{'name': 'Backstage Pro Básico'}]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode('utf-8')
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp

        out = StringIO()
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='test_api_key_valid'):
            with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen:
                call_command('create_asaas_sandbox_checkout', stdout=out)

                # Validar chamada enviada
                self.assertEqual(mock_urlopen.call_count, 1)
                req_arg = mock_urlopen.call_args[0][0]
                self.assertIn('/checkouts', req_arg.full_url)

                # Inspecionar payload enviado
                sent_body = json.loads(req_arg.data.decode('utf-8'))
                self.assertEqual(sent_body['customer'], 'cus_000009006807')
                self.assertEqual(sent_body['chargeTypes'], ['RECURRENT'])
                self.assertEqual(sent_body['billingTypes'], ['CREDIT_CARD'])
                self.assertEqual(sent_body['subscription']['cycle'], 'MONTHLY')
                self.assertIn('nextDueDate', sent_body['subscription'])
                self.assertTrue(len(sent_body['subscription']['nextDueDate']) >= 10)
                self.assertNotIn('endDate', sent_body['subscription'])
                self.assertEqual(sent_body['items'][0]['name'], 'Backstage Pro Básico')
                self.assertEqual(sent_body['items'][0]['value'], 19.90)
                self.assertIn('https://backstage-pro-web-homologacao.up.railway.app/', sent_body['callback']['successUrl'])

                # Validar SignupOrder criado no banco
                order = SignupOrder.objects.filter(gateway_checkout_id='chk_sandbox_test_777').first()
                self.assertIsNotNone(order)
                self.assertEqual(order.plan_type, 'BASICO')
                self.assertEqual(order.billing_cycle, 'MENSAL')
                self.assertEqual(order.amount, Decimal('19.90'))
                self.assertEqual(order.status, 'PENDENTE')
                self.assertIsNone(order.band) # NÃO cria Band

                # Validar que NÃO cria User
                self.assertEqual(User.objects.filter(email='backstagepro-sandbox@example.com').count(), 0)

                # Validar saida sanitizada sem expor segredos
                output_str = out.getvalue()
                self.assertIn('CHECKOUT SANDBOX CRIADO COM SUCESSO', output_str)
                self.assertIn('chk_sandbox_test_777', output_str)
                self.assertIn('nextDueDate:', output_str)
                self.assertNotIn('test_api_key_valid', output_str)

        # 4. Teste de retentativa com --order-id reutilizando pedido existente
        existing_order = SignupOrder.objects.create(
            band_name='Banda Teste Homologacao',
            responsible_name='Cliente Teste Sandbox',
            email='backstagepro-sandbox@example.com',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            external_reference='bp-homolog-test-retry-123'
        )

        mock_response_retry = {
            'id': 'chk_retry_888',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/retry888'
        }
        mock_resp_retry = MagicMock()
        mock_resp_retry.read.return_value = json.dumps(mock_response_retry).encode('utf-8')
        mock_resp_retry.status = 200
        mock_resp_retry.__enter__.return_value = mock_resp_retry

        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='test_key'):
            with patch('urllib.request.urlopen', return_value=mock_resp_retry) as mock_urlopen_retry:
                call_command('create_asaas_sandbox_checkout', order_id=existing_order.id)
                sent_retry_body = json.loads(mock_urlopen_retry.call_args[0][0].data.decode('utf-8'))
                self.assertEqual(sent_retry_body['externalReference'], 'bp-homolog-test-retry-123')

                existing_order.refresh_from_db()
                self.assertEqual(existing_order.gateway_checkout_id, 'chk_retry_888')
                self.assertEqual(existing_order.status, 'PENDENTE')

        # 5. Tentativa com order_id que ja possui gateway_checkout_id -> deve abortar
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='test_key'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_sandbox_checkout', order_id=existing_order.id)
            self.assertIn('ja possui Checkout Asaas vinculado', str(cm.exception))

    def test_inspect_asaas_webhooks_command_sanitization(self):
        """ASAAS-06: Inspecao de webhooks lista eventos de forma sanitizada sem vazar dados confidenciais."""
        from django.core.management import call_command
        from io import StringIO

        PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_insp_001',
            event_type='CHECKOUT_CREATED',
            payload={
                'id': 'evt_insp_001',
                'event': 'CHECKOUT_CREATED',
                'checkout': {'id': 'chk_insp_123', 'externalReference': 'ref_insp_123'},
                'secret_token': 'DO_NOT_SHOW_THIS_TOKEN',
                'creditCard': {'creditCardNumber': '4111111111111111'}
            }
        )

        out = StringIO()
        call_command('inspect_asaas_webhooks', stdout=out)
        output_str = out.getvalue()

        self.assertIn('evt_insp_001', output_str)
        self.assertIn('CHECKOUT_CREATED', output_str)
        self.assertIn('chk_insp_123', output_str)
        self.assertIn('ref_insp_123', output_str)
        self.assertNotIn('DO_NOT_SHOW_THIS_TOKEN', output_str)
        self.assertNotIn('4111111111111111', output_str)

    def test_real_order_four_events_reconciliation_lifecycle(self):
        """
        ASAAS-06: Validar o ciclo real dos 4 eventos recebidos na ordem:
        1. PAYMENT_CREATED (chega antes de CHECKOUT_PAID -> fica pendente para reprocessamento)
        2. PAYMENT_CONFIRMED (chega antes de CHECKOUT_PAID -> fica pendente para reprocessamento)
        3. CHECKOUT_PAID -> consulta pagamentos por checkout no Asaas, vincula payment_id e subscription_id, provisiona Band + BandSubscription + BillingRecord (status=PAGO)
        4. SUBSCRIPTION_CREATED -> reconcilia com BandSubscription existente via gateway_subscription_id sem duplicar
        5. Reprocessamento de 1 e 2 -> reconcilia com BillingRecord existente via gateway_payment_id sem duplicar
        """
        from unittest.mock import patch
        from django.core.management import call_command
        from django.contrib.auth import get_user_model
        User = get_user_model()

        checkout_id = '7d0a0681-282a-42b1-9c74-d0d47288ce18'
        payment_id = 'pay_8ufmj8khm9i24ik1'
        subscription_id = 'sub_2vjxr6kit10l68yr'
        customer_id = 'cus_000009006807'
        ext_ref = 'bp-homolog-17c1aba5cafe'

        # Criar SignupOrder equivalente ao da homologacao
        order = SignupOrder.objects.create(
            band_name='Banda Homologacao Real',
            responsible_name='Cliente Teste Homologacao',
            email='cliente-homolog@example.com',
            phone='(11) 99999-9999',
            cpf_cnpj='12345678901',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id=customer_id,
            gateway_checkout_id=checkout_id,
            external_reference=ext_ref
        )

        # 1. Evento PAYMENT_CREATED
        evt1 = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_real_pay_created',
            event_type='PAYMENT_CREATED',
            payload={
                'id': 'evt_real_pay_created',
                'event': 'PAYMENT_CREATED',
                'payment': {
                    'id': payment_id,
                    'customer': customer_id,
                    'subscription': subscription_id,
                    'checkoutSession': checkout_id,
                    'value': 19.9,
                    'billingType': 'CREDIT_CARD',
                    'status': 'PENDING',
                    'dueDate': '2026-09-04'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_real_pay_created')
        evt1.refresh_from_db()
        self.assertFalse(evt1.processed)
        self.assertIn('AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID', evt1.error_message)
        self.assertEqual(BillingRecord.objects.count(), 0)
        self.assertEqual(Band.objects.count(), 0)

        # 2. Evento PAYMENT_CONFIRMED
        evt2 = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_real_pay_confirmed',
            event_type='PAYMENT_CONFIRMED',
            payload={
                'id': 'evt_real_pay_confirmed',
                'event': 'PAYMENT_CONFIRMED',
                'payment': {
                    'id': payment_id,
                    'customer': customer_id,
                    'subscription': subscription_id,
                    'checkoutSession': checkout_id,
                    'value': 19.9,
                    'billingType': 'CREDIT_CARD',
                    'status': 'CONFIRMED',
                    'dueDate': '2026-09-04',
                    'confirmedDate': '2026-09-04',
                    'clientPaymentDate': '2026-09-04'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_real_pay_confirmed')
        evt2.refresh_from_db()
        self.assertFalse(evt2.processed)
        self.assertIn('AGUARDANDO_PROVISIONAMENTO_CHECKOUT_PAID', evt2.error_message)
        self.assertEqual(BillingRecord.objects.count(), 0)
        self.assertEqual(Band.objects.count(), 0)

        # 3. Evento CHECKOUT_PAID (com mock da chamada get_payments_by_checkout para retornar o payment real)
        mock_asaas_payments = [
            {
                'id': payment_id,
                'customer': customer_id,
                'subscription': subscription_id,
                'checkoutSession': checkout_id,
                'value': 19.9,
                'billingType': 'CREDIT_CARD',
                'status': 'CONFIRMED',
                'dueDate': '2026-09-04',
                'confirmedDate': '2026-09-04',
                'clientPaymentDate': '2026-09-04'
            }
        ]

        evt3 = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_real_checkout_paid',
            event_type='CHECKOUT_PAID',
            payload={
                'id': 'evt_real_checkout_paid',
                'event': 'CHECKOUT_PAID',
                'checkout': {
                    'id': checkout_id,
                    'status': 'PAID',
                    'customer': customer_id,
                    'externalReference': ext_ref
                }
            }
        )

        with patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_checkout', return_value=mock_asaas_payments):
            call_command('process_asaas_webhooks', event_id='evt_real_checkout_paid')

        evt3.refresh_from_db()
        self.assertTrue(evt3.processed)
        self.assertIsNone(evt3.error_message)

        # Validar estado do banco apos CHECKOUT_PAID
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAGO')
        self.assertIsNotNone(order.band)

        # 1 Band criada
        band = order.band
        self.assertEqual(Band.objects.count(), 1)
        self.assertEqual(band.is_active, True)

        # 1 BandSubscription criada com gateway_subscription_id reconciliado
        self.assertEqual(BandSubscription.objects.count(), 1)
        sub = BandSubscription.objects.first()
        self.assertEqual(sub.band, band)
        self.assertEqual(sub.gateway_subscription_id, subscription_id)
        self.assertEqual(sub.gateway_customer_id, customer_id)
        self.assertEqual(sub.status, 'ATIVO')

        # 1 BillingRecord criado com gateway_payment_id reconciliado e status PAGO
        self.assertEqual(BillingRecord.objects.count(), 1)
        billing = BillingRecord.objects.first()
        self.assertEqual(billing.subscription, sub)
        self.assertEqual(billing.gateway_payment_id, payment_id)
        self.assertEqual(billing.status, 'PAGO')
        self.assertEqual(billing.amount, Decimal('19.90'))
        self.assertIsNotNone(billing.paid_date)

        # 1 BandActivationToken criado
        self.assertEqual(BandActivationToken.objects.filter(band=band).count(), 1)

        # 0 User criado
        self.assertEqual(User.objects.filter(email='cliente-homolog@example.com').count(), 0)

        # 4. Evento SUBSCRIPTION_CREATED
        evt4 = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_real_sub_created',
            event_type='SUBSCRIPTION_CREATED',
            payload={
                'id': 'evt_real_sub_created',
                'event': 'SUBSCRIPTION_CREATED',
                'subscription': {
                    'id': subscription_id,
                    'customer': customer_id,
                    'value': 19.9,
                    'cycle': 'MONTHLY',
                    'status': 'ACTIVE',
                    'nextDueDate': '2026-10-04'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_real_sub_created')
        evt4.refresh_from_db()
        self.assertTrue(evt4.processed)
        self.assertIsNone(evt4.error_message)
        # Nao deve criar BandSubscription duplicada
        self.assertEqual(BandSubscription.objects.count(), 1)

        # 5. Reprocessamento dos eventos 1 (PAYMENT_CREATED) e 2 (PAYMENT_CONFIRMED)
        call_command('process_asaas_webhooks', event_id='evt_real_pay_created')
        evt1.refresh_from_db()
        self.assertTrue(evt1.processed)
        self.assertIsNone(evt1.error_message)

        call_command('process_asaas_webhooks', event_id='evt_real_pay_confirmed')
        evt2.refresh_from_db()
        self.assertTrue(evt2.processed)
        self.assertIsNone(evt2.error_message)

        self.assertEqual(Band.objects.count(), 1)
        self.assertEqual(BandSubscription.objects.count(), 1)
        self.assertEqual(BillingRecord.objects.count(), 1)
        self.assertEqual(User.objects.filter(email='cliente-homolog@example.com').count(), 0)

    def test_extract_asaas_id_validation_guardrails(self):
        """ASAAS-06: Validação de extração defensiva de identificadores Asaas."""
        from core.services.payments.base import extract_asaas_id

        # 1. Objeto dict de configuração -> NUNCA vira ID
        config_dict = {'cycle': 'MONTHLY', 'endDate': None, 'nextDueDate': '2026-09-04'}
        self.assertIsNone(extract_asaas_id(config_dict))
        self.assertIsNone(extract_asaas_id(config_dict, expected_prefix='sub_'))

        # 2. String formatada de dict -> NUNCA vira ID
        dict_str = "{'cycle': 'MONTHLY', 'endDate': None, 'nextDueDate': '2026-09-04'}"
        self.assertIsNone(extract_asaas_id(dict_str))
        self.assertIsNone(extract_asaas_id(dict_str, expected_prefix='sub_'))

        # 3. String de ID escalar válido
        self.assertEqual(extract_asaas_id('sub_2vjxr6kit10l68yr'), 'sub_2vjxr6kit10l68yr')
        self.assertEqual(extract_asaas_id('sub_2vjxr6kit10l68yr', expected_prefix='sub_'), 'sub_2vjxr6kit10l68yr')
        self.assertEqual(extract_asaas_id('pay_8ufmj8khm9i24ik1', expected_prefix='pay_'), 'pay_8ufmj8khm9i24ik1')
        self.assertEqual(extract_asaas_id('cus_000009006807', expected_prefix='cus_'), 'cus_000009006807')

        # 4. Prefixo divergente
        self.assertIsNone(extract_asaas_id('sub_123', expected_prefix='pay_'))
        self.assertIsNone(extract_asaas_id('pay_123', expected_prefix='sub_'))

        # 5. Dict com chave 'id' válida
        self.assertEqual(extract_asaas_id({'id': 'sub_2vjxr6kit10l68yr'}, expected_prefix='sub_'), 'sub_2vjxr6kit10l68yr')
        self.assertIsNone(extract_asaas_id({'id': {'nested': 123}}))

        # 6. Valores vazios / None / outros tipos
        self.assertIsNone(extract_asaas_id(None))
        self.assertIsNone(extract_asaas_id(''))
        self.assertIsNone(extract_asaas_id(12345))
        self.assertIsNone(extract_asaas_id([]))

    def test_checkout_paid_with_config_dict_does_not_pollute_subscription_id(self):
        """ASAAS-06: CHECKOUT_PAID com checkout.subscription sendo dict de configuracao nao polui gateway_subscription_id."""
        from unittest.mock import patch
        from django.core.management import call_command
        from core.models import SignupOrder, Band, BandSubscription

        order = SignupOrder.objects.create(
            band_name='Banda Sem Sub Inicial',
            responsible_name='Cliente Teste',
            email='cliente-teste@example.com',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_checkout_id='chk_no_sub_item',
            external_reference='bp-homolog-no-sub'
        )

        evt_checkout = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_checkout_no_sub',
            event_type='CHECKOUT_PAID',
            payload={
                'id': 'evt_checkout_no_sub',
                'event': 'CHECKOUT_PAID',
                'checkout': {
                    'id': 'chk_no_sub_item',
                    'customer': 'cus_000009006807',
                    'externalReference': 'bp-homolog-no-sub',
                    'subscription': {
                        'cycle': 'MONTHLY',
                        'endDate': None,
                        'nextDueDate': '2026-09-04'
                    }
                }
            }
        )

        # Mock do AsaasClient retornando lista vazia para simular checkout sem consulta prévia
        with patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_checkout', return_value=[]):
            call_command('process_asaas_webhooks', event_id='evt_checkout_no_sub')

        evt_checkout.refresh_from_db()
        self.assertTrue(evt_checkout.processed)

        sub = BandSubscription.objects.get(gateway_checkout_id='chk_no_sub_item')
        # gateway_subscription_id DEVE ser None e NÃO o dict de ciclo
        self.assertIsNone(sub.gateway_subscription_id)

        # Evento SUBSCRIPTION_CREATED posterior preenche o gateway_subscription_id de forma limpa
        evt_sub = PaymentWebhookEvent.objects.create(
            gateway_event_id='evt_sub_late_arrive',
            event_type='SUBSCRIPTION_CREATED',
            payload={
                'id': 'evt_sub_late_arrive',
                'event': 'SUBSCRIPTION_CREATED',
                'subscription': {
                    'id': 'sub_2vjxr6kit10l68yr',
                    'customer': 'cus_000009006807',
                    'status': 'ACTIVE'
                }
            }
        )
        call_command('process_asaas_webhooks', event_id='evt_sub_late_arrive')
        evt_sub.refresh_from_db()
        self.assertTrue(evt_sub.processed)

        sub.refresh_from_db()
        self.assertEqual(sub.gateway_subscription_id, 'sub_2vjxr6kit10l68yr')

    def test_repair_asaas_sandbox_order_command(self):
        """ASAAS-06: Validação do management command de reparo da homologação."""
        from unittest.mock import patch, MagicMock
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        # 1. Trava de ambiente em producao
        with override_settings(DJANGO_ENV='production', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='key_123'):
            with self.assertRaises(CommandError) as cm:
                call_command('repair_asaas_sandbox_order', order_id=1)
            self.assertIn('so pode ser executado no ambiente de homologacao', str(cm.exception))

        # 2. Criar cenário com gateway_subscription_id corrompido
        order = SignupOrder.objects.create(
            band_name='Banda Corrompida',
            responsible_name='Cliente Corrompido',
            email='corrompido@example.com',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_checkout_id='7d0a0681-282a-42b1-9c74-d0d47288ce18',
            gateway_subscription_id="{'cycle': 'MONTHLY', 'endDate': None}",
            external_reference='bp-homolog-repair-test'
        )

        band = Band.objects.create(name='Banda Corrompida', slug='bandacorrompida')
        order.band = band
        order.save()

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico Mensal',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            status='ATIVO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_subscription_id="{'cycle': 'MONTHLY', 'endDate': None}",
            gateway_checkout_id='7d0a0681-282a-42b1-9c74-d0d47288ce18'
        )

        billing = BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period='Setembro/2026',
            amount=Decimal('19.90'),
            due_date=timezone.localdate(),
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_8ufmj8khm9i24ik1'
        )

        mock_payments = [{
            'id': 'pay_8ufmj8khm9i24ik1',
            'customer': 'cus_000009006807',
            'subscription': 'sub_2vjxr6kit10l68yr'
        }]

        out = StringIO()
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='key_123'):
            with patch('core.services.payments.asaas.client.AsaasClient.get_payments_by_checkout', return_value=mock_payments):
                call_command('repair_asaas_sandbox_order', order_id=order.id, stdout=out)
        order.refresh_from_db()
        sub.refresh_from_db()
        billing.refresh_from_db()

        self.assertEqual(order.gateway_subscription_id, 'sub_2vjxr6kit10l68yr')
        self.assertEqual(sub.gateway_subscription_id, 'sub_2vjxr6kit10l68yr')
        self.assertEqual(billing.gateway_payment_id, 'pay_8ufmj8khm9i24ik1')
        self.assertIn('REPARO ASAAS SANDBOX EXECUTADO COM SUCESSO', out.getvalue())

    def test_customer_account_activation_flow_and_guardrails(self):
        """ASAAS-07: Validação completa do fluxo de ativação de conta do cliente."""
        from django.test import Client
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        from datetime import timedelta
        from core.services.payments.activation import (
            create_band_activation_token,
            reissue_activation_token,
            verify_activation_token,
            build_activation_email_data
        )

        User = get_user_model()
        client = Client()

        # 1. Setup da contratação e banda
        band = Band.objects.create(name='Banda Ativacao Real', slug='ativacaoreal')
        order = SignupOrder.objects.create(
            band=band,
            band_name='Banda Ativacao Real',
            responsible_name='Produtor Ativacao',
            email='produtor-ativacao@example.com',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_checkout_id='chk_ativ_123',
            external_reference='bp-homolog-ativacao-1'
        )

        # 2. Criar token inicial e reemitir novo token (invalidando o anterior)
        act1, raw1 = create_band_activation_token(band=band, email=order.email, responsible_name=order.responsible_name, signup_order=order)
        self.assertEqual(BandActivationToken.objects.filter(band=band).count(), 1)

        act2, raw2 = reissue_activation_token(band=band, signup_order=order, valid_hours=48)
        self.assertEqual(BandActivationToken.objects.filter(band=band).count(), 2)

        # O primeiro token foi invalidado por expiração
        act1.refresh_from_db()
        self.assertTrue(timezone.now() >= act1.expires_at)
        valid1, code1, _ = verify_activation_token(raw1)
        self.assertFalse(valid1)
        self.assertEqual(code1, 'TOKEN_EXPIRADO')

        # O segundo token é válido
        valid2, code2, _ = verify_activation_token(raw2)
        self.assertTrue(valid2)
        self.assertEqual(code2, 'OK')

        # 3. Teste do helper de e-mail estruturado
        email_data = build_activation_email_data(raw2, act2)
        self.assertEqual(email_data['subject'], 'Ative sua conta no Backstage Pro')
        self.assertIn('/ativar-conta/' + raw2 + '/', email_data['activation_url'])
        self.assertIn('Configurações', email_data['body_text'])

        # 4. Abertura da página GET com token inexistente, expirado e válido
        resp_invalid = client.get('/ativar-conta/token_inexistente_123/')
        self.assertEqual(resp_invalid.status_code, 200)
        self.assertContains(resp_invalid, 'Link Inválido')

        resp_expired = client.get(f'/ativar-conta/{raw1}/')
        self.assertEqual(resp_expired.status_code, 200)
        self.assertContains(resp_expired, 'Link Expirado')

        resp_valid = client.get(f'/ativar-conta/{raw2}/')
        self.assertEqual(resp_valid.status_code, 200)
        self.assertContains(resp_valid, 'Criar Conta')
        self.assertContains(resp_valid, 'Login')
        self.assertContains(resp_valid, 'Senha')
        self.assertContains(resp_valid, 'Confirmar Senha')
        self.assertContains(resp_valid, 'toggle-password-btn')

        # 5. POST com erros de validação
        # 5a. Login vazio
        resp_post_empty = client.post(f'/ativar-conta/{raw2}/', {
            'username': '',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        self.assertContains(resp_post_empty, 'O campo Login é obrigatório.')

        # 5b. Senhas diferentes
        resp_post_diff = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_novo',
            'password': 'Password123!',
            'confirm_password': 'Password999!'
        })
        self.assertContains(resp_post_diff, 'As senhas digitadas não coincidem.')

        # 5c. Login duplicado (criar usuário existente)
        User.objects.create_user(username='produtor_existente', email='outro@example.com', password='pwd')
        resp_post_dup = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_existente',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        self.assertContains(resp_post_dup, 'Este login já está em uso. Escolha outro.')

        # 6. POST com sucesso
        resp_post_success = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_real',
            'password': 'MinhaSenhaSegura123!',
            'confirm_password': 'MinhaSenhaSegura123!'
        })
        self.assertEqual(resp_post_success.status_code, 200)
        self.assertContains(resp_post_success, 'Conta criada com sucesso')
        self.assertContains(resp_post_success, '/ativacaoreal/login/')
        self.assertContains(resp_post_success, 'Configurações')

        # 7. Validar User criado no banco
        created_user = User.objects.get(username='produtor_real')
        self.assertEqual(created_user.email, 'produtor-ativacao@example.com')
        self.assertEqual(created_user.band, band)
        self.assertEqual(created_user.role, 'PRODUTOR')
        self.assertTrue(created_user.check_password('MinhaSenhaSegura123!'))

        # 8. Validar token liquidado (used_at)
        act2.refresh_from_db()
        self.assertIsNotNone(act2.used_at)

        # 9. Retentativa com mesmo token -> Bloqueada (já utilizado)
        resp_post_reuse = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_outro',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        self.assertContains(resp_post_reuse, 'Link Já Utilizado')
        # Nenhum segundo usuário criado
        self.assertEqual(User.objects.filter(band=band).count(), 1)

        # 10. Teste do Management Command create_asaas_activation_test_link
        # 10a. Bloqueio em producao
        with override_settings(DJANGO_ENV='production', ASAAS_ENVIRONMENT='sandbox'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_activation_test_link', order_id=order.id)
            self.assertIn('so pode ser executado no ambiente de homologacao', str(cm.exception))

        # 10b. Bloqueio fora do sandbox
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='production'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_activation_test_link', order_id=order.id)
            self.assertIn('so pode ser executado no ambiente de homologacao com Asaas Sandbox', str(cm.exception))

        # 10c. Bloqueio se já houver usuário de Produtor ativado
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            with self.assertRaises(CommandError) as cm:
                call_command('create_asaas_activation_test_link', order_id=order.id)
            self.assertIn('ja possui usuario inicial de Produtor ativado', str(cm.exception))

        # 10d. Execucao autorizada em novo pedido sem produtor
        band_new = Band.objects.create(name='Banda Sem Produtor', slug='semprodutor')
        order_new = SignupOrder.objects.create(
            band=band_new,
            band_name='Banda Sem Produtor',
            responsible_name='Novo Cliente',
            email='novo@example.com',
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_checkout_id='chk_new_888',
            external_reference='bp-homolog-new-888'
        )

        out_cmd = StringIO()
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            call_command('create_asaas_activation_test_link', order_id=order_new.id, stdout=out_cmd)

        out_val = out_cmd.getvalue()
        self.assertIn('LINK DE ATIVACAO GERADO COM SUCESSO', out_val)
        self.assertIn('https://backstage-pro-web-homologacao.up.railway.app/ativar-conta/', out_val)
        self.assertIn('Banda Sem Produtor', out_val)
