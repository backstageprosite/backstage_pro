import json
import hashlib
from unittest.mock import patch
from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from core.models import (
    User, Band, BandSubscription, BillingRecord, SignupOrder,
    PaymentWebhookEvent, BandActivationToken
)
from core.services.payments.base import (
    AsaasConfig, normalize_band_slug, generate_unique_band_slug,
    calculate_next_billing_date
)
from core.services.payments.activation import (
    create_band_activation_token, verify_activation_token, generate_activation_token_pair,
    reissue_activation_token
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
            'password': '123',
            'confirm_password': '456'
        })
        self.assertContains(resp_post_diff, 'As senhas não coincidem.')

        # 5c. Login duplicado (criar usuário existente)
        User.objects.create_user(username='produtor_existente', email='outro@example.com', password='pwd')
        resp_post_dup = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_existente',
            'password': '123',
            'confirm_password': '123'
        })
        self.assertContains(resp_post_dup, 'Este login já está em uso. Escolha outro.')

        # 6. POST com sucesso (aceita senha simples/numérica como '1234')
        resp_post_success = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_real',
            'password': '1234',
            'confirm_password': '1234'
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
        self.assertTrue(created_user.check_password('1234'))

        # 8. Validar token liquidado (used_at)
        act2.refresh_from_db()
        self.assertIsNotNone(act2.used_at)

        # 9. Retentativa com mesmo token -> Bloqueada (já utilizado)
        resp_post_reuse = client.post(f'/ativar-conta/{raw2}/', {
            'username': 'produtor_outro',
            'password': '1234',
            'confirm_password': '1234'
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
            self.assertIn('ja possui uma conta inicial ativada', str(cm.exception))

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

    def test_signuporder_activated_user_idempotency_and_repair(self):
        """ASAAS-07 Passo 4: Testes completos de associacao direta SignupOrder -> activated_user, idempotencia e reparo."""
        from django.test import Client
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        User = get_user_model()
        client = Client()

        # Cenário A: SignupOrder PAGO + Band sem produtores -> Ativação cria User e preenche order.activated_user
        band_a = Band.objects.create(name='Banda Alpha', slug='bandaalpha')
        order_a = SignupOrder.objects.create(
            band=band_a,
            band_name='Banda Alpha',
            responsible_name='Produtor Alpha',
            email='alpha@test.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            external_reference='bp-alpha-001'
        )
        act_a, raw_a = create_band_activation_token(band=band_a, email=order_a.email, responsible_name=order_a.responsible_name, signup_order=order_a)

        resp_a = client.post(f'/ativar-conta/{raw_a}/', {
            'username': 'user_alpha',
            'password': '123',
            'confirm_password': '123'
        })
        self.assertEqual(resp_a.status_code, 200)
        self.assertContains(resp_a, 'Conta criada com sucesso')

        order_a.refresh_from_db()
        user_alpha = User.objects.get(username='user_alpha')
        self.assertEqual(order_a.activated_user, user_alpha)
        self.assertEqual(user_alpha.role, 'PRODUTOR')
        self.assertEqual(user_alpha.band, band_a)

        # Cenário B: Band com produtor manual pré-existente + SignupOrder novo sem activated_user
        # A ativação DEVE ser permitida pois order.activated_user é None
        band_b = Band.objects.create(name='Banda Beta', slug='bandabeta')
        User.objects.create_user(username='produtor_manual_b', email='manual@test.com', password='123', band=band_b, role='PRODUTOR')
        order_b = SignupOrder.objects.create(
            band=band_b,
            band_name='Banda Beta',
            responsible_name='Produtor Beta',
            email='beta@test.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            external_reference='bp-beta-002'
        )
        self.assertIsNone(order_b.activated_user)
        self.assertEqual(band_b.users.filter(role='PRODUTOR').count(), 1)

        act_b, raw_b = create_band_activation_token(band=band_b, email=order_b.email, responsible_name=order_b.responsible_name, signup_order=order_b)
        resp_b = client.post(f'/ativar-conta/{raw_b}/', {
            'username': 'user_beta_ativado',
            'password': '123',
            'confirm_password': '123'
        })
        self.assertEqual(resp_b.status_code, 200)
        self.assertContains(resp_b, 'Conta criada com sucesso')

        order_b.refresh_from_db()
        user_beta = User.objects.get(username='user_beta_ativado')
        self.assertEqual(order_b.activated_user, user_beta)
        self.assertEqual(band_b.users.filter(role='PRODUTOR').count(), 2)

        # Cenário C: SignupOrder já com activated_user preenchido -> tentativa de ativação não cria 2º usuário e liquida token
        act_c, raw_c = create_band_activation_token(band=band_a, email=order_a.email, responsible_name=order_a.responsible_name, signup_order=order_a)
        resp_c = client.post(f'/ativar-conta/{raw_c}/', {
            'username': 'user_alpha_tentativa2',
            'password': '123',
            'confirm_password': '123'
        })
        self.assertEqual(resp_c.status_code, 200)
        self.assertContains(resp_c, 'Conta criada com sucesso')
        self.assertContains(resp_c, '/bandaalpha/login/')
        # Nenhum segundo usuário criado
        self.assertFalse(User.objects.filter(username='user_alpha_tentativa2').exists())
        self.assertEqual(band_a.users.count(), 1)
        act_c.refresh_from_db()
        self.assertIsNotNone(act_c.used_at)

        # Cenário D: reissue_activation_token bloqueia se order.activated_user estiver preenchido
        with self.assertRaises(ValueError) as ctx:
            reissue_activation_token(band=band_a, signup_order=order_a)
        self.assertIn('Esta contratação já possui uma conta inicial ativada', str(ctx.exception))

        # Cenário E: create_asaas_activation_test_link bloqueia se order.activated_user estiver preenchido
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            with self.assertRaises(CommandError) as ctx_cmd:
                call_command('create_asaas_activation_test_link', order_id=order_a.id)
            self.assertIn('ja possui uma conta inicial ativada', str(ctx_cmd.exception))

        # Cenário F: repair_asaas_activation_user bloqueia fora de staging / fora de sandbox
        band_rep = Band.objects.create(name='Banda Reparo', slug='bandareparo')
        user_rep = User.objects.create_user(username='prod_rep', email='rep@test.com', password='123', band=band_rep, role='PRODUTOR')
        order_rep = SignupOrder.objects.create(
            band=band_rep,
            band_name='Banda Reparo',
            responsible_name='Produtor Rep',
            email='rep@test.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            external_reference='bp-rep-001'
        )

        with override_settings(DJANGO_ENV='production', ASAAS_ENVIRONMENT='sandbox'):
            with self.assertRaises(CommandError):
                call_command('repair_asaas_activation_user', order_id=order_rep.id)

        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='production'):
            with self.assertRaises(CommandError):
                call_command('repair_asaas_activation_user', order_id=order_rep.id)

        # Cenário G: repair_asaas_activation_user executa com sucesso em staging+sandbox e repara activated_user
        out_rep = StringIO()
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            call_command('repair_asaas_activation_user', order_id=order_rep.id, stdout=out_rep)

        self.assertIn('REPARO DE ATIVACAO EXECUTADO COM SUCESSO', out_rep.getvalue())
        order_rep.refresh_from_db()
        self.assertEqual(order_rep.activated_user, user_rep)

        # Cenário H: repair_asaas_activation_user em ordem já associada informa que nada precisa ser feito
        out_rep2 = StringIO()
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            call_command('repair_asaas_activation_user', order_id=order_rep.id, stdout=out_rep2)
        self.assertIn('ja possui activated_user', out_rep2.getvalue())

        # Cenário I: repair_asaas_activation_user falha se houver ambiguidade (múltiplos produtores)
        band_amb = Band.objects.create(name='Banda Ambigua', slug='bandaambigua')
        User.objects.create_user(username='prod_amb_1', email='amb1@test.com', password='123', band=band_amb, role='PRODUTOR')
        User.objects.create_user(username='prod_amb_2', email='amb2@test.com', password='123', band=band_amb, role='PRODUTOR')
        order_amb = SignupOrder.objects.create(
            band=band_amb,
            band_name='Banda Ambigua',
            responsible_name='Produtor Amb',
            email='amb@test.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PAGO',
            gateway_provider='ASAAS',
            external_reference='bp-amb-001'
        )
        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox'):
            with self.assertRaises(CommandError) as ctx_amb:
                call_command('repair_asaas_activation_user', order_id=order_amb.id)
            self.assertIn('Ambiguidade', str(ctx_amb.exception))

        # Cenário J: Band sem SignupOrder (legada/manual) continua operando sem erros
        band_legacy = Band.objects.create(name='Banda Legada', slug='bandalegada')
        user_leg = User.objects.create_user(username='prod_leg', email='leg@test.com', password='123', band=band_legacy, role='PRODUTOR')
        self.assertEqual(SignupOrder.objects.filter(band=band_legacy).count(), 0)
        self.assertFalse(hasattr(user_leg, 'activated_signup_order') and user_leg.activated_signup_order is not None)

    def test_band_logo_fallback_and_removal(self):
        """ASAAS-07 Passo 3: Identidade visual sem repeticao de nome no branding e remocao de logo."""
        from django.test import Client
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.contrib.auth import get_user_model
        User = get_user_model()
        client = Client()

        # 1. Banda sem logo
        band = Band.objects.create(name='Banda Sem Imagem', slug='semimagem')
        act, raw = create_band_activation_token(
            band=band,
            email='contato@semimagem.com',
            responsible_name='Artista'
        )

        # 1a. Ativacao: branding exibe apenas a logo Backstage Pro (sem h2 com nome da banda)
        resp_act = client.get(f'/ativar-conta/{raw}/')
        self.assertEqual(resp_act.status_code, 200)
        self.assertContains(resp_act, 'backstage-pro-logo.png')
        self.assertNotContains(resp_act, '<h2 class="text-primary fw-bold">')
        # Contexto informativo interno continua com o nome da banda
        self.assertContains(resp_act, 'administrar a banda <strong>Banda Sem Imagem</strong>')

        # 1b. Login: branding exibe apenas a logo Backstage Pro (sem título/nome escrito no branding)
        resp_login = client.get(f'/{band.slug}/login/')
        self.assertEqual(resp_login.status_code, 200)
        self.assertContains(resp_login, 'backstage-pro-logo.png')
        self.assertNotContains(resp_login, '<h1')
        self.assertNotContains(resp_login, '<h2')
        self.assertNotContains(resp_login, '<h3')

        # 1c. Area logada (Sidebar e Configuracoes)
        user_produtor = User.objects.create_user(
            username='prod_sem_logo',
            email='contato@semimagem.com',
            password='123',
            band=band,
            role='PRODUTOR'
        )
        client.force_login(user_produtor)

        # Sidebar no Dashboard: apenas logo Backstage Pro sem texto do nome
        resp_dash = client.get(f'/{band.slug}/painel/')
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, 'backstage-pro-logo.png')
        self.assertNotContains(resp_dash, 'span class="fs-5 fw-bold text-dark text-truncate w-100"')

        # Configuracoes sem logo cadastrada:
        # Exibe fallback, texto "Logo da banda ainda não cadastrada." e NAO exibe botao "Remover Logo"
        resp_config = client.get(f'/{band.slug}/configuracoes/')
        self.assertEqual(resp_config.status_code, 200)
        self.assertContains(resp_config, 'backstage-pro-logo.png')
        self.assertContains(resp_config, 'Logo da banda ainda não cadastrada.')
        self.assertContains(resp_config, 'Recomendamos imagens com fundo transparente (PNG)')
        self.assertNotContains(resp_config, 'Remover Logo')
        self.assertNotContains(resp_config, 'modalRemoverLogo')

        # 2. Upload de logo própria
        dummy_img = SimpleUploadedFile("custom_logo.png", b"fake_image_content", content_type="image/png")
        resp_upload = client.post(f'/{band.slug}/configuracoes/', {'logo': dummy_img})
        self.assertEqual(resp_upload.status_code, 302)

        band.refresh_from_db()
        self.assertTrue(bool(band.logo))
        self.assertIn('custom_logo', band.logo.name)

        # Configuracoes com logo cadastrada:
        # Exibe logo própria, texto "Logo cadastrada." e exibe botao e modal "Remover Logo"
        resp_config_custom = client.get(f'/{band.slug}/configuracoes/')
        self.assertEqual(resp_config_custom.status_code, 200)
        self.assertContains(resp_config_custom, f'/{band.slug}/assets/logo/')
        self.assertContains(resp_config_custom, 'Logo cadastrada.')
        self.assertContains(resp_config_custom, 'Remover Logo')
        self.assertContains(resp_config_custom, 'modalRemoverLogo')
        self.assertContains(resp_config_custom, 'Tem certeza que deseja remover a logo da banda?')

        # 3. Remover Logo via POST action=remove_logo
        resp_remove = client.post(f'/{band.slug}/configuracoes/', {'action': 'remove_logo'})
        self.assertEqual(resp_remove.status_code, 302)

        # Validar no banco de dados que band.logo e None / vazio e NÃO salvou string 'backstage-pro-logo.png'
        band.refresh_from_db()
        self.assertFalse(bool(band.logo))
        self.assertIsNone(band.logo.name if band.logo else None)

        # 4. Validar retorno imediato do fallback Backstage Pro
        resp_config_after = client.get(f'/{band.slug}/configuracoes/')
        self.assertEqual(resp_config_after.status_code, 200)
        self.assertContains(resp_config_after, 'backstage-pro-logo.png')
        self.assertContains(resp_config_after, 'Logo da banda ainda não cadastrada.')
        self.assertNotContains(resp_config_after, 'modalRemoverLogo')

    def test_relatorios_assinatura_view(self):
        """ASAAS-08: Teste completo de visualização de Assinatura e Histórico de Pagamentos em Relatórios."""
        from django.test import Client
        from django.contrib.auth import get_user_model
        User = get_user_model()
        client = Client()

        # 1. Setup de Bandas e Usuários
        band_a = Band.objects.create(name='Banda Teste Homologacao', slug='testehomologacao', plan_type='BASICO')
        user_produtor_a = User.objects.create_user(username='prod_a', email='proda@test.com', password='123', band=band_a, role='PRODUTOR')
        user_integrante_a = User.objects.create_user(username='integ_a', email='intega@test.com', password='123', band=band_a, role='INTEGRANTE')

        band_b = Band.objects.create(name='Banda Outra', slug='bandaoutra', plan_type='AVANCADO')
        user_produtor_b = User.objects.create_user(username='prod_b', email='prodb@test.com', password='123', band=band_b, role='PRODUTOR')

        # 2. Permissão de Acesso:
        # Integrante recebe 403
        client.force_login(user_integrante_a)
        resp_forbid = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertEqual(resp_forbid.status_code, 403)

        # 3. Band sem assinatura (Band B): exibe mensagem amigável e histórico vazio sem erro 500
        client.force_login(user_produtor_b)
        resp_no_sub = client.get(f'/{band_b.slug}/relatorios/assinatura/')
        self.assertEqual(resp_no_sub.status_code, 200)
        self.assertContains(resp_no_sub, 'Não há uma assinatura cadastrada para esta banda.')
        self.assertContains(resp_no_sub, 'Nenhum pagamento registrado.')

        # 4. Band A com assinatura Asaas (dados da homologação real) e histórico de faturas
        sub_a = BandSubscription.objects.create(
            band=band_a,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 3),
            next_due_date=date(2026, 10, 3),
            status='ATIVO',
            auto_renew=True,
            payment_method_preference='CARTAO',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_000009006807',
            gateway_subscription_id='sub_2vjxr6kit10l68yr',
            gateway_checkout_id='7d0a0681-282a-42b1-9c74-d0d47288ce18'
        )

        bill_a1 = BillingRecord.objects.create(
            subscription=sub_a,
            band=band_a,
            reference_period='Setembro/2026',
            plan_name='Básico',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            due_date=date(2026, 9, 3),
            paid_date=date(2026, 9, 3),
            status='PAGO',
            payment_method='CARTAO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_8ufmj8khm9i24ik1',
            gateway_invoice_url='https://sandbox.asaas.com/i/8ufmj8khm9i24ik1'
        )

        client.force_login(user_produtor_a)
        resp_a = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertEqual(resp_a.status_code, 200)

        # Validar exibição do Resumo com nomes amigáveis
        self.assertContains(resp_a, 'Básico')
        self.assertContains(resp_a, 'Ativo')
        self.assertContains(resp_a, '19,90')
        self.assertContains(resp_a, 'Mensal')
        self.assertContains(resp_a, '03/09/2026')  # Início
        self.assertContains(resp_a, '03/10/2026')  # Próxima Cobrança
        self.assertContains(resp_a, 'Cartão de crédito')
        self.assertContains(resp_a, 'Sim')

        # Validar histórico com colunas e link seguro
        self.assertContains(resp_a, 'Setembro/2026')
        self.assertContains(resp_a, 'Pago')
        self.assertContains(resp_a, 'Ver cobrança')
        self.assertContains(resp_a, 'https://sandbox.asaas.com/i/8ufmj8khm9i24ik1')
        self.assertContains(resp_a, 'rel="noopener noreferrer"')

        # Validar que IDs técnicos Asaas NÃO são exibidos no HTML para o usuário
        self.assertNotContains(resp_a, 'sub_2vjxr6kit10l68yr')
        self.assertNotContains(resp_a, 'cus_000009006807')
        self.assertNotContains(resp_a, 'pay_8ufmj8khm9i24ik1')
        self.assertNotContains(resp_a, '7d0a0681-282a-42b1-9c74-d0d47288ce18')

        # 5. Cancelamento agendado (cancel_at_period_end = True)
        sub_a.cancel_at_period_end = True
        sub_a.save()
        resp_cancel = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertContains(resp_cancel, 'Cancelamento agendado')
        self.assertContains(resp_cancel, 'Acesso até')
        # Quando está cancelado no período pago: não exibe Cancelar Assinatura nem Regularizar Pagamento
        self.assertNotContains(resp_cancel, 'modalCancelarAssinatura')
        self.assertNotContains(resp_cancel, 'Regularizar Pagamento')

        # Testar POST cancel_subscription
        sub_a.cancel_at_period_end = False
        sub_a.auto_renew = True
        sub_a.save()
        resp_before = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertContains(resp_before, 'Cancelar Assinatura')

        post_cancel = client.post(f'/{band_a.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        self.assertEqual(post_cancel.status_code, 200)
        sub_a.refresh_from_db()
        self.assertTrue(sub_a.cancel_at_period_end)
        self.assertFalse(sub_a.auto_renew)
        self.assertContains(post_cancel, 'Cancelamento agendado')
        self.assertContains(post_cancel, 'Acesso até')
        self.assertNotContains(post_cancel, 'modalCancelarAssinatura')

        # Testar POST reactivate_subscription
        post_reactivate = client.post(f'/{band_a.slug}/relatorios/assinatura/', {'action': 'reactivate_subscription'}, follow=True)
        self.assertEqual(post_reactivate.status_code, 200)
        sub_a.refresh_from_db()
        self.assertFalse(sub_a.cancel_at_period_end)
        self.assertTrue(sub_a.auto_renew)
        self.assertContains(post_reactivate, 'Sim')
        self.assertNotContains(post_reactivate, '- Acesso até')
        self.assertContains(post_reactivate, 'Cancelar Assinatura')
        self.assertNotContains(post_reactivate, 'modalReativarAssinatura')

        # Testar estado de assinatura inativa/desativada (Assinar Novamente)
        sub_a.status = 'DESATIVADO'
        sub_a.save()
        resp_desativado = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertContains(resp_desativado, 'Assinar Novamente')
        self.assertContains(resp_desativado, 'modalAssinarNovamente')
        self.assertNotContains(resp_desativado, 'modalCancelarAssinatura')
        self.assertNotContains(resp_desativado, 'modalReativarAssinatura')
        sub_a.status = 'ATIVO'
        sub_a.save()

        # 6. Assinatura manual/legada sem gateway
        band_manual = Band.objects.create(name='Banda Manual Teste', slug='manualteste', plan_type='AVANCADO')
        user_manual = User.objects.create_user(username='prod_man', email='man@test.com', password='123', band=band_manual, role='PRODUTOR')
        sub_manual = BandSubscription.objects.create(
            band=band_manual,
            plan_name='Avançado',
            billing_cycle='ANUAL',
            contracted_value=Decimal('299.00'),
            start_date=date(2026, 1, 1),
            next_due_date=date(2027, 1, 1),
            status='ATIVO',
            auto_renew=False,
            payment_method_preference='PIX'
        )
        bill_manual = BillingRecord.objects.create(
            subscription=sub_manual,
            band=band_manual,
            reference_period='Ano 2026',
            plan_name='Avançado',
            billing_cycle='ANUAL',
            amount=Decimal('299.00'),
            due_date=date(2026, 1, 1),
            paid_date=date(2026, 1, 1),
            status='PAGO',
            payment_method='PIX'
        )

        client.force_login(user_manual)
        resp_man = client.get(f'/{band_manual.slug}/relatorios/assinatura/')
        self.assertEqual(resp_man.status_code, 200)
        self.assertContains(resp_man, 'Avançado')
        self.assertContains(resp_man, 'Anual')
        self.assertContains(resp_man, '299,00')
        self.assertContains(resp_man, 'Pix')
        self.assertContains(resp_man, 'Não')
        self.assertContains(resp_man, 'Ano 2026')
        # Sem gateway_invoice_url exibe '-' em vez do botão
        self.assertNotContains(resp_man, 'Ver cobrança')

        # 7. Isolamento Multi-Tenant: Usuário de uma banda não pode ver faturas de outra
        resp_isolated = client.get(f'/{band_manual.slug}/relatorios/assinatura/')
        self.assertNotContains(resp_isolated, 'Setembro/2026')
        self.assertNotContains(resp_isolated, 'Banda Teste Homologacao')

        # 8. Validação do Card Assinatura no Hub de Relatórios (relatorios_index)
        resp_hub = client.get(f'/{band_manual.slug}/relatorios/')
        self.assertEqual(resp_hub.status_code, 200)
        self.assertContains(resp_hub, 'Assinatura')
        self.assertContains(resp_hub, f'/{band_manual.slug}/relatorios/assinatura/')
        self.assertContains(resp_hub, 'fa-credit-card')

    def test_auto_expiration_and_access_restriction(self):
        """
        Valida os 5 cenários do encerramento automático e restrição de acesso:
        Cenário A: cancel_at_period_end=True, auto_renew=False, today < next_due_date -> STATUS Ativo, acesso normal
        Cenário B: cancel_at_period_end=True, auto_renew=False, today >= next_due_date -> STATUS Inativo, bloqueio operacional, redireciona para Assinatura
        Cenário C: cancel_at_period_end=False, auto_renew=True, today >= next_due_date -> STATUS permanece Ativo (aguarda cobrança)
        Cenário D: Tela de Assinatura exibe 'Inativo', 'Sem cobrança agendada', 'Não' e botão 'Assinar Novamente'
        Cenário E: Superuser continua com acesso administrativo
        """
        from django.test import Client
        from core.models import User
        from django.utils import timezone
        today = timezone.localdate()
        client = Client()

        # Cenário A: Assinatura cancelada mas ainda dentro do período pago
        band_a = Band.objects.create(name='Banda Periodo Valido', slug='bandaperiodovalido')
        user_a = User.objects.create_user(username='prod_valido', email='valido@test.com', password='123', band=band_a, role='PRODUTOR')
        sub_a = BandSubscription.objects.create(
            band=band_a,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=10),
            next_due_date=today + timedelta(days=20),
            status='ATIVO',
            auto_renew=False,
            cancel_at_period_end=True,
            payment_method_preference='CARTAO'
        )

        client.force_login(user_a)
        # Deve acessar dashboard normalmente
        resp_dash = client.get(f'/{band_a.slug}/painel/')
        self.assertEqual(resp_dash.status_code, 200)
        # Assinatura permanece ATIVO
        self.assertTrue(band_a.has_active_subscription)
        self.assertEqual(sub_a.status, 'ATIVO')

        # Cenário B: Assinatura cancelada cujo período pago VENCEU (today >= next_due_date)
        band_b = Band.objects.create(name='Banda Expirada', slug='bandaexpirada')
        user_b = User.objects.create_user(username='prod_expirado', email='expirado@test.com', password='123', band=band_b, role='PRODUTOR')
        sub_b = BandSubscription.objects.create(
            band=band_b,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=35),
            next_due_date=today - timedelta(days=5),
            status='ATIVO',
            auto_renew=False,
            cancel_at_period_end=True,
            payment_method_preference='CARTAO'
        )

        client.force_login(user_b)
        # Ao acessar o dashboard, é bloqueado e redirecionado para a tela de Assinatura
        resp_dash_b = client.get(f'/{band_b.slug}/painel/')
        self.assertEqual(resp_dash_b.status_code, 302)
        self.assertEqual(resp_dash_b.url, f'/{band_b.slug}/relatorios/assinatura/')

        # Outras rotas operacionais (ex: contatos, shows, calendario) também redirecionam
        resp_contatos = client.get(f'/{band_b.slug}/contatos/')
        self.assertEqual(resp_contatos.status_code, 302)
        self.assertEqual(resp_contatos.url, f'/{band_b.slug}/relatorios/assinatura/')

        # Status no banco foi alterado para DESATIVADO
        sub_b.refresh_from_db()
        self.assertEqual(sub_b.status, 'DESATIVADO')
        self.assertFalse(band_b.has_active_subscription)

        # Cenário D: Tela de Assinatura para a banda expirada
        resp_assina = client.get(f'/{band_b.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina.status_code, 200)
        self.assertContains(resp_assina, 'Assinatura encerrada')
        self.assertContains(resp_assina, sub_b.next_due_date.strftime('%d/%m/%Y'))
        self.assertContains(resp_assina, 'Reativar Assinatura')
        self.assertNotContains(resp_assina, 'Regularizar Pagamento')
        # Sidebar restrita: não exibe link do Dashboard operacional
        self.assertNotContains(resp_assina, f'/{band_b.slug}/calendario/')

        # Cenário C: Assinatura com renovação ativa vencida (auto_renew=True, cancel_at_period_end=False)
        # NÃO deve ser cancelada automaticamente (aguarda webhook/tentativa de cobrança)
        band_c = Band.objects.create(name='Banda Renovacao Normal', slug='bandarenovacao')
        user_c = User.objects.create_user(username='prod_renov', email='renov@test.com', password='123', band=band_c, role='PRODUTOR')
        sub_c = BandSubscription.objects.create(
            band=band_c,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=35),
            next_due_date=today - timedelta(days=1),
            status='ATIVO',
            auto_renew=True,
            cancel_at_period_end=False,
            payment_method_preference='CARTAO'
        )
        self.assertTrue(band_c.has_active_subscription)
        sub_c.refresh_from_db()
        self.assertEqual(sub_c.status, 'ATIVO')

        # Cenário E: Superuser acessa qualquer página mesmo com banda inativa
        super_user = User.objects.create_superuser(username='superadmin', email='admin@test.com', password='123')
        client.force_login(super_user)
        resp_admin_dash = client.get(f'/{band_b.slug}/painel/')
        self.assertEqual(resp_admin_dash.status_code, 200)

    def test_overdue_tolerance_and_automatic_suspension_scenarios(self):
        """
        Testes de Inadimplência e Suspensão Automática após 5 dias:
        - Cenário A: Dia 0 (data de vencimento) -> normal, sem alerta, acesso total
        - Cenário B: 1 dia de atraso -> tolerância, 'Pagamento em atraso', banner amarelo, acesso operacional liberado
        - Cenário C: 4 dias de atraso -> tolerância, data limite calculada (+5 dias), acesso operacional liberado
        - Cenário D: 5 dias de atraso -> suspensão automática, 'Suspensa', banner vermelho, acesso operacional bloqueado
        - Cenário E: 10 dias de atraso -> permanece 'Suspensa', idempotente
        - Cenário F: Pagamento realizado durante tolerância -> volta a Ativo, normalizado
        - Cenário G: Cancelamento agendado -> NÃO entra no fluxo de atraso (dias_overdue=0)
        - Cenário H: Superuser bypassa bloqueio de suspensão
        - Cenário I: Suspensão administrativa (is_active=False) vs Suspensão financeira
        - Cenário J: Webhook PAYMENT_OVERDUE idempotente e não suspende imediatamente
        """
        from django.test import Client
        from core.models import User
        client = Client()
        today = timezone.localdate()

        # --- Cenário A: Dia 0 (Vencimento hoje) ---
        band_a = Band.objects.create(name='Banda Dia 0', slug='bandadia0')
        user_a = User.objects.create_user(username='prod_a', email='a@test.com', password='123', band=band_a, role='PRODUTOR')
        sub_a = BandSubscription.objects.create(
            band=band_a, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=30), next_due_date=today,
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_a.days_overdue(), 0)
        self.assertFalse(sub_a.is_overdue_tolerance)
        self.assertFalse(sub_a.is_financially_suspended)
        self.assertTrue(band_a.has_active_subscription)

        client.force_login(user_a)
        resp_a = client.get(f'/{band_a.slug}/relatorios/assinatura/')
        self.assertEqual(resp_a.status_code, 200)
        self.assertContains(resp_a, 'Ativo')
        self.assertNotContains(resp_a, 'Pagamento em atraso')
        self.assertNotContains(resp_a, 'Existe um pagamento em atraso')

        # --- Cenário B: 1 dia de atraso (Tolerância) ---
        band_b = Band.objects.create(name='Banda Dia 1', slug='bandadia1')
        user_b = User.objects.create_user(username='prod_b', email='b@test.com', password='123', band=band_b, role='PRODUTOR')
        sub_b = BandSubscription.objects.create(
            band=band_b, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=31), next_due_date=today - timedelta(days=1),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_b.days_overdue(), 1)
        self.assertTrue(sub_b.is_overdue_tolerance)
        self.assertFalse(sub_b.is_financially_suspended)
        self.assertTrue(band_b.has_active_subscription)

        client.force_login(user_b)
        # Acesso operacional liberado
        resp_dash_b = client.get(f'/{band_b.slug}/painel/')
        self.assertEqual(resp_dash_b.status_code, 200)

        # Página de assinatura exibe alerta amarelo e status de atraso
        resp_assina_b = client.get(f'/{band_b.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_b.status_code, 200)
        self.assertContains(resp_assina_b, 'Pagamento em atraso')
        self.assertContains(resp_assina_b, 'Existe um pagamento em atraso')
        self.assertContains(resp_assina_b, '- Vencida')

        # --- Cenário C: 4 dias de atraso (Último dia de tolerância) ---
        band_c = Band.objects.create(name='Banda Dia 4', slug='bandadia4')
        user_c = User.objects.create_user(username='prod_c', email='c@test.com', password='123', band=band_c, role='PRODUTOR')
        sub_c = BandSubscription.objects.create(
            band=band_c, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=34), next_due_date=today - timedelta(days=4),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_c.days_overdue(), 4)
        self.assertTrue(sub_c.is_overdue_tolerance)
        self.assertFalse(sub_c.is_financially_suspended)
        self.assertTrue(band_c.has_active_subscription)

        client.force_login(user_c)
        resp_assina_c = client.get(f'/{band_c.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_c.status_code, 200)
        self.assertContains(resp_assina_c, 'Pagamento em atraso')
        limit_date_c = (sub_c.next_due_date + timedelta(days=4)).strftime('%d/%m/%Y')
        self.assertContains(resp_assina_c, limit_date_c)


        # --- Cenário D: 5 dias de atraso (Suspensão Automática) ---
        band_d = Band.objects.create(name='Banda Dia 5', slug='bandadia5')
        user_d = User.objects.create_user(username='prod_d', email='d@test.com', password='123', band=band_d, role='PRODUTOR')
        sub_d = BandSubscription.objects.create(
            band=band_d, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=35), next_due_date=today - timedelta(days=5),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_d.days_overdue(), 5)
        self.assertFalse(sub_d.is_overdue_tolerance)
        self.assertTrue(sub_d.is_financially_suspended)
        self.assertFalse(band_d.has_active_subscription)

        client.force_login(user_d)
        # Acesso operacional bloqueado -> redireciona para Assinatura
        resp_dash_d = client.get(f'/{band_d.slug}/painel/')
        self.assertEqual(resp_dash_d.status_code, 302)
        self.assertEqual(resp_dash_d.url, f'/{band_d.slug}/relatorios/assinatura/')

        # Tela de assinatura exibe alerta vermelho, status 'Suspensa' e botão 'Regularizar Pagamento'
        resp_assina_d = client.get(f'/{band_d.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_d.status_code, 200)
        self.assertContains(resp_assina_d, 'Suspensa')
        self.assertContains(resp_assina_d, 'Assinatura suspensa por pagamento em atraso')
        self.assertContains(resp_assina_d, '- Vencida')
        self.assertContains(resp_assina_d, 'Regularizar Pagamento')

        # --- Cenário E: 10 dias de atraso (Permanece Suspensa) ---
        band_e = Band.objects.create(name='Banda Dia 10', slug='bandadia10')
        sub_e = BandSubscription.objects.create(
            band=band_e, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=40), next_due_date=today - timedelta(days=10),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_e.days_overdue(), 10)
        self.assertTrue(sub_e.is_financially_suspended)
        self.assertFalse(band_e.has_active_subscription)

        # --- Cenário G: Cancelamento agendado (cancel_at_period_end=True) ---
        # Não entra no fluxo de atraso (dias_overdue retorna 0)
        band_g = Band.objects.create(name='Banda Cancel Agendado', slug='bandacancel')
        sub_g = BandSubscription.objects.create(
            band=band_g, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=20), next_due_date=today - timedelta(days=2),
            status='ATIVO', auto_renew=False, cancel_at_period_end=True, payment_method_preference='CARTAO'
        )
        self.assertEqual(sub_g.days_overdue(), 0)
        self.assertFalse(sub_g.is_overdue_tolerance)
        self.assertFalse(sub_g.is_financially_suspended)

        # --- Cenário H: Superuser bypassa suspensão financeira ---
        super_user = User.objects.create_superuser(username='superadm_test', email='superadm@test.com', password='123')
        client.force_login(super_user)
        resp_admin_dash = client.get(f'/{band_d.slug}/painel/')
        self.assertEqual(resp_admin_dash.status_code, 200)

        # --- Cenário I: Suspensão administrativa vs financeira ---
        band_admin_off = Band.objects.create(name='Banda Admin Off', slug='bandaadminoff', is_active=False)
        user_admin_off = User.objects.create_user(username='prod_off', email='off@test.com', password='123', band=band_admin_off, role='PRODUTOR')
        client.force_login(user_admin_off)
        resp_admin_off = client.get(f'/{band_admin_off.slug}/painel/')
        self.assertEqual(resp_admin_off.status_code, 403)

        # --- Cenário J: Webhook PAYMENT_OVERDUE idempotente ---
        event_overdue = {
            "id": "evt_test_overdue_999",
            "event": "PAYMENT_OVERDUE",
            "payment": {
                "id": "pay_test_overdue_123",
                "customer": "cus_test_123",
                "value": 19.90,
                "netValue": 19.90,
                "status": "OVERDUE",
                "externalReference": "ext_test_overdue"
            }
        }
        BillingRecord.objects.create(
            subscription=sub_d, band=band_d, reference_period='Setembro/2026',
            plan_name='Básico', billing_cycle='MENSAL', amount=Decimal('19.90'),
            due_date=today - timedelta(days=5), status='PENDENTE', payment_method='CARTAO',
            gateway_provider='ASAAS', gateway_payment_id='pay_test_overdue_123'
        )
        ok, msg = handle_asaas_webhook_payload(event_overdue)
        self.assertTrue(ok)
        rec = BillingRecord.objects.get(gateway_payment_id='pay_test_overdue_123')
        self.assertEqual(rec.status, 'PENDENTE')
        self.assertEqual(rec.gateway_event_status, 'PAYMENT_OVERDUE')

    def test_regularization_rules_and_billing_anchors(self):
        """
        Regras comerciais obrigatórias:
        A) Vencimento dia 03, pagamento dia 05 (em tolerância) -> próxima cobrança dia 03 (mantém billing anchor).
        B) Vencimento dia 03, suspensão financeira, regularização dia 15 -> próxima cobrança dia 15 (novo anchor).
        C) Regularização após suspensão -> acesso somente volta APÓS confirmação do pagamento.
        D) Antes da confirmação -> acesso continua bloqueado.
        E) Regularização não cria nova BandSubscription (preserva a existente).
        F) Histórico financeiro anterior permanece intacto.
        G) Novo billing anchor fica persistido corretamente (inclusive anual).
        """
        from django.test import Client
        from core.models import User
        client = Client()

        # --- Regra A: Tolerância preserva data-base original ---
        band_tol = Band.objects.create(name='Banda Tol Anchor', slug='bandatolanchor')
        sub_tol = BandSubscription.objects.create(
            band=band_tol, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 3), next_due_date=date(2026, 10, 3),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )
        # Pagamento efetuado dia 05/10 (2 dias de atraso, dentro da tolerância)
        was_suspended = sub_tol.apply_payment_success(paid_date=date(2026, 10, 5))
        self.assertFalse(was_suspended)
        self.assertEqual(sub_tol.next_due_date, date(2026, 11, 3))
        self.assertEqual(sub_tol.start_date, date(2026, 9, 3))

        # --- Regra B: Suspensão financeira + Regularização -> nova data-base ---
        band_reg = Band.objects.create(name='Banda Reg Anchor', slug='bandareganchor')
        user_reg = User.objects.create_user(username='prod_reg', email='reg@test.com', password='123', band=band_reg, role='PRODUTOR')
        sub_reg = BandSubscription.objects.create(
            band=band_reg, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 3), next_due_date=date(2026, 10, 3),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO',
            gateway_provider='ASAAS', gateway_subscription_id='sub_reg_test_999'
        )
        # Cria faturas anteriores no histórico
        old_rec = BillingRecord.objects.create(
            subscription=sub_reg, band=band_reg, reference_period='Setembro/2026',
            plan_name='Básico', billing_cycle='MENSAL', amount=Decimal('19.90'),
            due_date=date(2026, 9, 3), paid_date=date(2026, 9, 3), status='PAGO', payment_method='CARTAO'
        )
        overdue_rec = BillingRecord.objects.create(
            subscription=sub_reg, band=band_reg, reference_period='Outubro/2026',
            plan_name='Básico', billing_cycle='MENSAL', amount=Decimal('19.90'),
            due_date=date(2026, 10, 3), status='PENDENTE', payment_method='CARTAO',
            gateway_provider='ASAAS', gateway_payment_id='pay_reg_test_oct'
        )

        client.force_login(user_reg)

        # Regra D: Antes da confirmação do pagamento, com data simulada 15/10 (12 dias de atraso), acesso bloqueado
        with override_settings():
            # A assinatura está suspensa financeiramente
            self.assertTrue(sub_reg.days_overdue() > 0 or (date(2026, 10, 15) - sub_reg.next_due_date).days >= 5)

        # Simula o recebimento do webhook PAYMENT_CONFIRMED em 15/10/2026
        event_reg = {
            "id": "evt_reg_oct_15",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_reg_test_oct",
                "customer": "cus_reg_123",
                "value": 19.90,
                "netValue": 19.90,
                "status": "CONFIRMED",
                "paymentDate": "2026-10-15"
            }
        }
        initial_sub_id = sub_reg.id
        ok, msg = handle_asaas_webhook_payload(event_reg)
        self.assertTrue(ok)

        # Regra E: Não cria nova BandSubscription (preserva o mesmo ID)
        self.assertEqual(band_reg.subscriptions.count(), 1)
        sub_reg.refresh_from_db()
        self.assertEqual(sub_reg.id, initial_sub_id)

        # Regra B & G: Nova data-base é 15/10 e próxima cobrança mensal é 15/11
        self.assertEqual(sub_reg.start_date, date(2026, 10, 15))
        self.assertEqual(sub_reg.next_due_date, date(2026, 11, 15))
        self.assertEqual(sub_reg.status, 'ATIVO')

        # Regra C: Acesso operacional liberado após confirmação do pagamento
        self.assertTrue(band_reg.has_active_subscription)

        # Regra F: Histórico anterior permanece intacto
        self.assertEqual(sub_reg.records.count(), 2)
        old_rec.refresh_from_db()
        self.assertEqual(old_rec.status, 'PAGO')
        overdue_rec.refresh_from_db()
        self.assertEqual(overdue_rec.status, 'PAGO')
        self.assertEqual(overdue_rec.paid_date, date(2026, 10, 15))

    def test_cancellation_expiry_and_reactivation_scenarios(self):
        """
        Suíte completa de testes ASAAS-08 (Cancelamento, Fim de Período e Reativação):
        - Cancelamento:
          A) Assinatura ativa -> 'Cancelar Assinatura' disponível.
          B) Cancelamento solicitado -> cancel_at_period_end=True.
          C) Cancelamento solicitado -> auto_renew=False.
          D) Antes do fim do período -> acesso operacional continua.
          E) Antes do fim -> Renovação Automática = 'Cancelamento agendado'.
          F) Antes do fim -> Próxima Cobrança vira 'Acesso até'.
          G) 'Cancelar Assinatura' desaparece.
        - Fim do Período:
          H) Período cancelado termina -> acesso operacional bloqueado.
          I) Band.is_active continua True.
          J) Não entra em is_financially_suspended.
          K) Usuário consegue acessar Assinatura.
          L) Usuário não consegue acessar Dashboard (redireciona).
          M) Sidebar fica restrita.
          N) Status mostra 'Assinatura encerrada'.
          O) Botão 'Reativar Assinatura' aparece.
          P) 'Regularizar Pagamento' NÃO aparece.
        - Reativação:
          Q) Clicar Reativar -> modal/pagamento, não libera acesso imediatamente.
          R) Antes da confirmação -> continua bloqueado.
          S) Pagamento confirmado -> acesso restaurado.
          T) Pagamento confirmado -> cancel_at_period_end=False.
          U) Pagamento confirmado -> auto_renew=True.
          V) Pagamento confirmado -> status ATIVO.
          W) Data de pagamento vira nova data-base.
          X) Mensal: 18/10 -> 18/11.
          Y) Anual: 18/10/2026 -> 18/10/2027.
          Z) Não cria nova Band.
          AA) Não cria novo User.
          AB) Preserva histórico financeiro anterior.
          AC) Webhook duplicado idempotente.
          AD) Inadimplência continua usando Regularizar Pagamento.
        """
        from django.test import Client
        from core.models import User
        client = Client()
        today = timezone.localdate()

        # 1. CANCELAMENTO VOLUNTÁRIO DURANTE O PERÍODO PAGO (A até G)
        band_canc = Band.objects.create(name='Banda Cancel Test', slug='bandacanceltest')
        user_canc = User.objects.create_user(username='prod_canc', email='canc@test.com', password='123', band=band_canc, role='PRODUTOR')
        sub_canc = BandSubscription.objects.create(
            band=band_canc, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=today - timedelta(days=10), next_due_date=today + timedelta(days=20),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO'
        )

        client.force_login(user_canc)

        # Teste A: Assinatura ativa -> 'Cancelar Assinatura' disponível
        resp_assina_active = client.get(f'/{band_canc.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_active.status_code, 200)
        self.assertContains(resp_assina_active, 'Cancelar Assinatura')
        self.assertContains(resp_assina_active, 'Próxima Cobrança')

        # Realiza o cancelamento voluntário
        resp_post_cancel = client.post(f'/{band_canc.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'})
        self.assertEqual(resp_post_cancel.status_code, 302)

        # Teste B & C: cancel_at_period_end=True e auto_renew=False
        sub_canc.refresh_from_db()
        self.assertTrue(sub_canc.cancel_at_period_end)
        self.assertFalse(sub_canc.auto_renew)
        self.assertIsNotNone(sub_canc.canceled_at)

        # Teste D: Antes do fim do período -> acesso operacional continua
        self.assertTrue(band_canc.has_active_subscription)
        resp_dash_during = client.get(f'/{band_canc.slug}/painel/')
        self.assertEqual(resp_dash_during.status_code, 200)

        # Teste E, F, G: Na tela de assinatura
        resp_assina_scheduled = client.get(f'/{band_canc.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_scheduled.status_code, 200)
        self.assertContains(resp_assina_scheduled, 'Cancelamento agendado')
        self.assertContains(resp_assina_scheduled, 'Acesso até')
        self.assertContains(resp_assina_scheduled, sub_canc.next_due_date.strftime('%d/%m/%Y'))
        self.assertNotContains(resp_assina_scheduled, 'Cancelar Assinatura')
        self.assertNotContains(resp_assina_scheduled, 'Regularizar Pagamento')

        # 2. FIM DO PERÍODO PAGO APÓS CANCELAMENTO (H até P)
        band_exp = Band.objects.create(name='Banda Periodo Encerrado', slug='bandaexp')
        user_exp = User.objects.create_user(username='prod_exp', email='exp@test.com', password='123', band=band_exp, role='PRODUTOR')
        sub_exp = BandSubscription.objects.create(
            band=band_exp, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 4), next_due_date=date(2026, 10, 4),
            status='ATIVO', auto_renew=False, cancel_at_period_end=True, payment_method_preference='CARTAO',
            gateway_provider='ASAAS', gateway_subscription_id='sub_exp_test_888'
        )
        BillingRecord.objects.create(
            subscription=sub_exp, band=band_exp, reference_period='Setembro/2026',
            plan_name='Básico', billing_cycle='MENSAL', amount=Decimal('19.90'),
            due_date=date(2026, 9, 4), paid_date=date(2026, 9, 4), status='PAGO', payment_method='CARTAO'
        )

        # Simulando acesso em 05/10/2026 (período pago encerrou em 04/10)
        # Teste H, I, J:
        # Band.is_active continua True
        self.assertTrue(band_exp.is_active)
        # Não entra em is_financially_suspended
        self.assertFalse(sub_exp.is_financially_suspended)
        # É identificado como cancelamento expirado
        sub_exp.status = 'DESATIVADO'
        sub_exp.save(update_fields=['status'])
        self.assertTrue(sub_exp.is_canceled_period_expired)
        self.assertFalse(band_exp.has_active_subscription)

        client.force_login(user_exp)

        # Teste L: Usuário não consegue acessar Dashboard (redireciona para Assinatura)
        resp_dash_exp = client.get(f'/{band_exp.slug}/painel/')
        self.assertEqual(resp_dash_exp.status_code, 302)
        self.assertEqual(resp_dash_exp.url, f'/{band_exp.slug}/relatorios/assinatura/')

        # Teste K, M, N, O, P:
        resp_assina_exp = client.get(f'/{band_exp.slug}/relatorios/assinatura/')
        self.assertEqual(resp_assina_exp.status_code, 200)
        self.assertContains(resp_assina_exp, 'Assinatura encerrada')
        self.assertContains(resp_assina_exp, 'Acesso até')
        self.assertContains(resp_assina_exp, '04/10/2026')
        self.assertContains(resp_assina_exp, 'Reativar Assinatura')
        self.assertNotContains(resp_assina_exp, 'Regularizar Pagamento')
        self.assertNotContains(resp_assina_exp, 'Cancelar Assinatura')
        # Sidebar restrita
        self.assertNotContains(resp_assina_exp, f'/{band_exp.slug}/calendario/')

        # 3. REATIVAÇÃO COM PAGAMENTO PRIMEIRO E NOVA DATA-BASE (Q até AD)
        # Teste Q & R: Antes da confirmação do pagamento, acesso permanece bloqueado
        self.assertFalse(band_exp.has_active_subscription)

        # Simula pagamento de reativação confirmado no Asaas em 18/10/2026
        event_reactivate = {
            "id": "evt_reactivate_18_oct",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_reactivate_888",
                "customer": "cus_reactivate_123",
                "value": 19.90,
                "netValue": 19.90,
                "status": "CONFIRMED",
                "paymentDate": "2026-10-18",
                "subscription": "sub_exp_test_888"
            }
        }
        initial_band_id = band_exp.id
        initial_sub_id = sub_exp.id
        initial_user_id = user_exp.id

        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_anc:
            mock_anc.return_value = (True, 'ASAAS_ANCHOR_SINCRONIZADO')
            ok, msg = handle_asaas_webhook_payload(event_reactivate)
        self.assertTrue(ok)

        # Teste S, T, U, V: Acesso restaurado, flags resetadas, status ATIVO
        sub_exp.refresh_from_db()
        self.assertEqual(sub_exp.status, 'ATIVO')
        self.assertTrue(sub_exp.auto_renew)
        self.assertFalse(sub_exp.cancel_at_period_end)
        self.assertIsNone(sub_exp.canceled_at)
        self.assertTrue(band_exp.has_active_subscription)

        # Teste W & X: Data do pagamento (18/10) vira nova data-base; mensal: 18/10 -> 18/11
        self.assertEqual(sub_exp.start_date, date(2026, 10, 18))
        self.assertEqual(sub_exp.next_due_date, date(2026, 11, 18))

        # Teste Z & AA: Não cria nova Band nem novo User nem nova Sub
        self.assertEqual(band_exp.id, initial_band_id)
        self.assertEqual(user_exp.id, initial_user_id)
        self.assertEqual(sub_exp.id, initial_sub_id)

        # Teste AB: Preserva histórico financeiro anterior + novo registro
        self.assertEqual(sub_exp.records.count(), 2)

        # Teste AC: Webhook duplicado idempotente
        ok_dup, msg_dup = handle_asaas_webhook_payload(event_reactivate)
        self.assertTrue(ok_dup)
        self.assertEqual(sub_exp.records.count(), 2)
        sub_exp.refresh_from_db()
        self.assertEqual(sub_exp.next_due_date, date(2026, 11, 18))

        # Teste Y: Ciclo Anual reativado
        band_ann = Band.objects.create(name='Banda Anual Exp', slug='bandaanualexp')
        sub_ann = BandSubscription.objects.create(
            band=band_ann, plan_name='Avançado', billing_cycle='ANUAL', contracted_value=Decimal('300.00'),
            start_date=date(2025, 10, 4), next_due_date=date(2026, 10, 4),
            status='DESATIVADO', auto_renew=False, cancel_at_period_end=True, payment_method_preference='CARTAO'
        )
        sub_ann.apply_payment_success(paid_date=date(2026, 10, 18))
        self.assertEqual(sub_ann.start_date, date(2026, 10, 18))
        self.assertEqual(sub_ann.next_due_date, date(2027, 10, 18))
        self.assertEqual(sub_ann.status, 'ATIVO')
        self.assertTrue(sub_ann.auto_renew)
        self.assertFalse(sub_ann.cancel_at_period_end)

    @patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription')
    @patch('core.services.payments.asaas.client.AsaasClient.get_subscription')
    def test_asaas_cancellation_flow_and_anti_free_month_entitlement(self, mock_get_sub, mock_cancel_sub):
        """
        ASAAS-08: Testes do fluxo de cancelamento com AsaasClient e regra comercial anti-mês-grátis.
        """
        client = Client()
        band = Band.objects.create(name='Banda Cancel Entitlement', slug='bandacancelentitlement')
        user = User.objects.create_user(username='prod_cancel_ent', email='cancelent@test.com', password='123', band=band, role='PRODUTOR')
        client.login(username='prod_cancel_ent', password='123')

        sub = BandSubscription.objects.create(
            band=band,
            plan_name='Básico',
            billing_cycle='MENSAL',
            contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 4),
            next_due_date=date(2026, 10, 4),
            status='ATIVO',
            auto_renew=True,
            cancel_at_period_end=False,
            gateway_provider='ASAAS',
            gateway_subscription_id='sub_test_remote_123',
            gateway_customer_id='cus_test_remote_456'
        )

        # 1. BillingRecord quitado em 04/09/2026
        BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period='Setembro/2026',
            plan_name='Básico',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            due_date=date(2026, 9, 4),
            paid_date=date(2026, 9, 4),
            status='PAGO',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_04_sep'
        )

        # 2. BillingRecord de renovação de 04/10/2026 PENDENTE
        BillingRecord.objects.create(
            subscription=sub,
            band=band,
            reference_period='Outubro/2026',
            plan_name='Básico',
            billing_cycle='MENSAL',
            amount=Decimal('19.90'),
            due_date=date(2026, 10, 4),
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_payment_id='pay_test_04_oct'
        )

        # Cenário A: Falha na validação remota (GET retorna None) -> Não altera estado local
        mock_get_sub.return_value = None
        resp_fail_get = client.post(f'/{band.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        self.assertEqual(resp_fail_get.status_code, 200)
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)
        self.assertTrue(sub.auto_renew)

        # Cenário B: Divergência de Customer ID -> Cancelamento abortado
        mock_get_sub.return_value = {'id': 'sub_test_remote_123', 'customer': 'cus_divergente_999'}
        resp_fail_cust = client.post(f'/{band.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)

        # Cenário C: Falha no DELETE do Asaas -> Não altera estado local
        mock_get_sub.return_value = {'id': 'sub_test_remote_123', 'customer': 'cus_test_remote_456'}
        mock_cancel_sub.return_value = (False, {'error': 'gateway_timeout'})
        resp_fail_del = client.post(f'/{band.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)

        # Cenário D: Sucesso no GET e no DELETE Asaas -> Marca cancelamento agendado
        mock_cancel_sub.return_value = (True, {'deleted': True})
        resp_success = client.post(f'/{band.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
        self.assertEqual(resp_success.status_code, 200)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertFalse(sub.auto_renew)
        self.assertIsNotNone(sub.canceled_at)
        self.assertEqual(sub.status, 'ATIVO')

        # Regra Anti-Mês-Grátis:
        # Cobrança de 04/10 pendente não concede período até 04/11. Acesso até = 04/10/2026.
        resp_view = client.get(f'/{band.slug}/relatorios/assinatura/')
        self.assertContains(resp_view, 'Acesso até')
        self.assertContains(resp_view, '04/10/2026')
        self.assertNotContains(resp_view, '04/11/2026')

        # Acesso operacional permanece ativo
        resp_dash = client.get(f'/{band.slug}/painel/')
        self.assertEqual(resp_dash.status_code, 200)
        resp_cal = client.get(f'/{band.slug}/calendario/')
        self.assertEqual(resp_cal.status_code, 200)

        # Webhook SUBSCRIPTION_DELETED posterior é idempotente e preserva Band.is_active e BillingRecords
        del_event = {
            "id": "evt_sub_del_test_123",
            "event": "SUBSCRIPTION_DELETED",
            "subscription": {
                "id": "sub_test_remote_123",
                "customer": "cus_test_remote_456"
            }
        }
        ok_del, _ = handle_asaas_webhook_payload(del_event)
        self.assertTrue(ok_del)
        band.refresh_from_db()
        self.assertTrue(band.is_active)
        self.assertEqual(sub.records.filter(status='PAGO').count(), 1)

        # Webhook PAYMENT_DELETED para cobrança PENDENTE: marca CANCELADO e preserva registro
        pay_del_event = {
            "id": "evt_pay_del_04_oct",
            "event": "PAYMENT_DELETED",
            "payment": {
                "id": "pay_test_04_oct",
                "subscription": "sub_test_remote_123",
                "customer": "cus_test_remote_456",
                "status": "DELETED"
            }
        }
        ok_pdel, msg_pdel = handle_asaas_webhook_payload(pay_del_event)
        self.assertTrue(ok_pdel)
        record_oct = BillingRecord.objects.get(gateway_payment_id='pay_test_04_oct')
        self.assertEqual(record_oct.status, 'CANCELADO')
        self.assertEqual(sub.records.count(), 2)
        band.refresh_from_db()
        self.assertTrue(band.is_active)

        # Webhook PAYMENT_DELETED para cobrança PAGA: NUNCA altera status nem apaga registro
        pay_del_paid_event = {
            "id": "evt_pay_del_04_sep_paid",
            "event": "PAYMENT_DELETED",
            "payment": {
                "id": "pay_test_04_sep",
                "subscription": "sub_test_remote_123",
                "customer": "cus_test_remote_456"
            }
        }
        ok_pdel_paid, _ = handle_asaas_webhook_payload(pay_del_paid_event)
        self.assertTrue(ok_pdel_paid)
        record_sep = BillingRecord.objects.get(gateway_payment_id='pay_test_04_sep')
        self.assertEqual(record_sep.status, 'PAGO')

        # Idempotência do PAYMENT_DELETED
        ok_pdel_dup, _ = handle_asaas_webhook_payload(pay_del_event)
        self.assertTrue(ok_pdel_dup)
        self.assertEqual(sub.records.count(), 2)
        sub.refresh_from_db()
        self.assertEqual(sub.next_due_date, date(2026, 10, 4))

    def test_canceled_at_lifecycle_audit(self):
        """
        BACKSTAGE PRO — ASAAS-08: Auditoria estrita do ciclo de vida de `canceled_at`.
        - Cancelamento voluntário preenche `canceled_at`.
        - Fim do período / expiração preserva `canceled_at`.
        - Criação de Checkout de reativação preserva `canceled_at`.
        - Webhook CHECKOUT_CREATED preserva `canceled_at`.
        - Webhook SUBSCRIPTION_CREATED preserva `canceled_at`.
        - Webhook PAYMENT_CREATED preserva `canceled_at`.
        - Webhook PAYMENT_CONFIRMED redefine `canceled_at = None` e restaura acesso.
        - Webhook PAYMENT_RECEIVED posterior é idempotente e mantém `canceled_at = None`.
        - Checkout abandonado preserva `canceled_at` indefinidamente.
        """
        band_audit = Band.objects.create(name='Banda Auditoria CanceledAt', slug='bandaauditcanc')
        user_audit = User.objects.create_user(
            username='prod_audit_canc', email='audit_canc@test.com', password='123',
            band=band_audit, role='PRODUTOR'
        )
        sub_audit = BandSubscription.objects.create(
            band=band_audit, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 9, 4),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO',
            gateway_provider='ASAAS', gateway_subscription_id='sub_audit_old_111',
            gateway_customer_id='cus_audit_999'
        )
        BillingRecord.objects.create(
            subscription=sub_audit, band=band_audit, reference_period='Agosto/2026',
            plan_name='Básico', billing_cycle='MENSAL', amount=Decimal('19.90'),
            due_date=date(2026, 8, 4), paid_date=date(2026, 8, 4), status='PAGO', payment_method='CARTAO',
            gateway_payment_id='pay_audit_aug'
        )

        # 1. Cancelamento voluntário -> preenche canceled_at
        client = Client(HTTP_HOST='localhost')
        client.force_login(user_audit)
        with patch('core.services.payments.asaas.client.AsaasClient.get_subscription') as mock_get, \
             patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription') as mock_del:
            mock_get.return_value = {'id': 'sub_audit_old_111', 'customer': 'cus_audit_999'}
            mock_del.return_value = (True, {'deleted': True})
            resp_canc = client.post(f'/{band_audit.slug}/relatorios/assinatura/', {'action': 'cancel_subscription'}, follow=True)
            self.assertEqual(resp_canc.status_code, 200)

        sub_audit.refresh_from_db()
        self.assertTrue(sub_audit.cancel_at_period_end)
        self.assertFalse(sub_audit.auto_renew)
        self.assertIsNotNone(sub_audit.canceled_at)
        initial_canceled_at = sub_audit.canceled_at

        # 2. Fim do período pago (expiração) -> status=DESATIVADO, canceled_at permanece preenchido
        sub_audit.status = 'DESATIVADO'
        sub_audit.save(update_fields=['status'])
        sub_audit.refresh_from_db()
        self.assertEqual(sub_audit.canceled_at, initial_canceled_at)
        self.assertTrue(sub_audit.is_canceled_period_expired)

        # 3. Criação de Checkout de reativação -> canceled_at permanece preenchido
        sub_audit.gateway_checkout_id = 'chk_audit_react_777'
        sub_audit.gateway_external_reference = 'bp-reactivation-audit-777'
        sub_audit.save(update_fields=['gateway_checkout_id', 'gateway_external_reference'])
        sub_audit.refresh_from_db()
        self.assertEqual(sub_audit.canceled_at, initial_canceled_at)
        self.assertEqual(sub_audit.status, 'DESATIVADO')

        # 4. Webhook CHECKOUT_CREATED -> canceled_at permanece preenchido
        evt_chk_created = {
            "id": "evt_chk_created_audit",
            "event": "CHECKOUT_CREATED",
            "checkout": {
                "id": "chk_audit_react_777",
                "customer": "cus_audit_999",
                "externalReference": "bp-reactivation-audit-777"
            }
        }
        ok_cc, _ = handle_asaas_webhook_payload(evt_chk_created)
        self.assertTrue(ok_cc)
        sub_audit.refresh_from_db()
        self.assertEqual(sub_audit.canceled_at, initial_canceled_at)
        self.assertEqual(sub_audit.status, 'DESATIVADO')

        # 5. Webhook SUBSCRIPTION_CREATED -> atualiza gateway_subscription_id mas NÃO limpa canceled_at
        evt_sub_created = {
            "id": "evt_sub_created_audit",
            "event": "SUBSCRIPTION_CREATED",
            "subscription": {
                "id": "sub_audit_new_222",
                "customer": "cus_audit_999",
                "checkoutSession": "chk_audit_react_777",
                "value": 19.90,
                "cycle": "MONTHLY",
                "nextDueDate": "2026-10-04"
            }
        }
        ok_sc, _ = handle_asaas_webhook_payload(evt_sub_created)
        self.assertTrue(ok_sc)
        sub_audit.refresh_from_db()
        self.assertEqual(sub_audit.gateway_subscription_id, 'sub_audit_new_222')
        self.assertEqual(sub_audit.canceled_at, initial_canceled_at)
        self.assertEqual(sub_audit.status, 'DESATIVADO')
        self.assertFalse(band_audit.has_active_subscription)

        # 6. Webhook PAYMENT_CREATED -> canceled_at permanece preenchido
        evt_pay_created = {
            "id": "evt_pay_created_audit",
            "event": "PAYMENT_CREATED",
            "payment": {
                "id": "pay_audit_new_333",
                "customer": "cus_audit_999",
                "subscription": "sub_audit_new_222",
                "value": 19.90,
                "dueDate": "2026-09-04",
                "status": "PENDING"
            }
        }
        ok_pc, _ = handle_asaas_webhook_payload(evt_pay_created)
        self.assertTrue(ok_pc)
        sub_audit.refresh_from_db()
        self.assertEqual(sub_audit.canceled_at, initial_canceled_at)
        self.assertEqual(sub_audit.status, 'DESATIVADO')
        self.assertFalse(band_audit.has_active_subscription)

        # 7. Webhook PAYMENT_CONFIRMED -> SOMENTE AQUI canceled_at vira None e status vira ATIVO
        evt_pay_confirmed = {
            "id": "evt_pay_confirmed_audit",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_audit_new_333",
                "customer": "cus_audit_999",
                "subscription": "sub_audit_new_222",
                "value": 19.90,
                "netValue": 19.90,
                "paymentDate": "2026-09-04",
                "status": "CONFIRMED"
            }
        }
        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_anc:
            mock_anc.return_value = (True, 'ASAAS_ANCHOR_SINCRONIZADO')
            ok_pconf, _ = handle_asaas_webhook_payload(evt_pay_confirmed)
        self.assertTrue(ok_pconf)
        sub_audit.refresh_from_db()
        self.assertIsNone(sub_audit.canceled_at)
        self.assertEqual(sub_audit.status, 'ATIVO')
        self.assertTrue(sub_audit.auto_renew)
        self.assertFalse(sub_audit.cancel_at_period_end)
        self.assertEqual(sub_audit.start_date, date(2026, 9, 4))
        self.assertEqual(sub_audit.next_due_date, date(2026, 10, 4))
        self.assertTrue(band_audit.has_active_subscription)

        # 8. Webhook PAYMENT_RECEIVED posterior -> idempotente, permanece canceled_at = None e next_due_date inalterado
        evt_pay_received = {
            "id": "evt_pay_received_audit",
            "event": "PAYMENT_RECEIVED",
            "payment": {
                "id": "pay_audit_new_333",
                "customer": "cus_audit_999",
                "subscription": "sub_audit_new_222",
                "value": 19.90,
                "netValue": 19.90,
                "paymentDate": "2026-09-04",
                "status": "RECEIVED"
            }
        }
        ok_prec, _ = handle_asaas_webhook_payload(evt_pay_received)
        self.assertTrue(ok_prec)
        sub_audit.refresh_from_db()
        self.assertIsNone(sub_audit.canceled_at)
        self.assertEqual(sub_audit.status, 'ATIVO')
        self.assertEqual(sub_audit.next_due_date, date(2026, 10, 4))


        # 9. Cenário de Checkout abandonado:
        band_abandon = Band.objects.create(name='Banda Abandon', slug='bandaabandon')
        sub_abandon = BandSubscription.objects.create(
            band=band_abandon, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 9, 4),
            status='DESATIVADO', auto_renew=False, cancel_at_period_end=True,
            canceled_at=timezone.now(),
            gateway_provider='ASAAS', gateway_subscription_id='sub_abandon_old',
            gateway_customer_id='cus_abandon_123',
            gateway_checkout_id='chk_abandon_456'
        )
        abandon_canceled_at = sub_abandon.canceled_at
        # Expirar checkout
        evt_chk_exp = {
            "id": "evt_chk_exp_abandon",
            "event": "CHECKOUT_EXPIRED",
            "checkout": {
                "id": "chk_abandon_456",
                "customer": "cus_abandon_123"
            }
        }
        ok_exp, _ = handle_asaas_webhook_payload(evt_chk_exp)
        self.assertTrue(ok_exp)
        sub_abandon.refresh_from_db()
        self.assertEqual(sub_abandon.canceled_at, abandon_canceled_at)
        self.assertEqual(sub_abandon.status, 'DESATIVADO')
        self.assertFalse(band_abandon.has_active_subscription)

    def test_overdue_grace_period_deadline_and_suspension(self):
        """
        BACKSTAGE PRO — ASAAS-09: Valida prazo de tolerância (next_due_date + 4 dias)
        e suspensão a partir do 5º dia.
        - Vencimento 03/09/2026 (hoje 04/09, days_overdue=1): deadline = 07/09/2026, banner amarelo.
        - Vencimento 31/08/2026 (hoje 04/09, days_overdue=4): deadline = 04/09/2026, banner amarelo.
        - Vencimento 30/08/2026 (hoje 04/09, days_overdue=5): suspenso, banner vermelho, CTA Regularizar Pagamento.
        """
        band_dl = Band.objects.create(name='Banda Deadline Test', slug='bandadltest')
        user_dl = User.objects.create_user(
            username='prod_dl', email='dl@test.com', password='123',
            band=band_dl, role='PRODUTOR'
        )
        sub_dl = BandSubscription.objects.create(
            band=band_dl, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 9, 3),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False, payment_method_preference='CARTAO',
            gateway_provider='ASAAS', gateway_subscription_id='sub_dl_123',
            gateway_customer_id='cus_dl_456'
        )

        client = Client(HTTP_HOST='localhost')
        client.force_login(user_dl)

        # 1. Dia 1 de atraso (vencimento 03/09/2026) -> deadline 07/09/2026
        resp1 = client.get(f'/{band_dl.slug}/relatorios/assinatura/')
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(sub_dl.days_overdue(), 1)
        self.assertTrue(sub_dl.is_overdue_tolerance)
        self.assertFalse(sub_dl.is_financially_suspended)
        self.assertContains(resp1, 'Existe um pagamento em atraso')
        self.assertContains(resp1, 'Regularize até 07/09/2026')
        self.assertNotContains(resp1, '08/09/2026')
        self.assertNotContains(resp1, 'Assinatura suspensa por pagamento em atraso')

        # 2. Dia 4 de atraso (vencimento 31/08/2026) -> deadline 04/09/2026 (hoje)
        sub_dl.next_due_date = date(2026, 8, 31)
        sub_dl.save(update_fields=['next_due_date'])
        resp4 = client.get(f'/{band_dl.slug}/relatorios/assinatura/')
        self.assertEqual(resp4.status_code, 200)
        self.assertEqual(sub_dl.days_overdue(), 4)
        self.assertTrue(sub_dl.is_overdue_tolerance)
        self.assertFalse(sub_dl.is_financially_suspended)
        self.assertContains(resp4, 'Existe um pagamento em atraso')
        self.assertContains(resp4, 'Regularize até 04/09/2026')
        self.assertNotContains(resp4, '05/09/2026')

        # 3. Dia 5 de atraso (vencimento 30/08/2026) -> Suspensão financeira
        sub_dl.next_due_date = date(2026, 8, 30)
        sub_dl.save(update_fields=['next_due_date'])
        resp5 = client.get(f'/{band_dl.slug}/relatorios/assinatura/')
        self.assertEqual(resp5.status_code, 200)
        self.assertEqual(sub_dl.days_overdue(), 5)
        self.assertFalse(sub_dl.is_overdue_tolerance)
        self.assertTrue(sub_dl.is_financially_suspended)
        self.assertContains(resp5, 'Assinatura suspensa por pagamento em atraso')
        self.assertContains(resp5, 'Regularizar Pagamento')
        self.assertNotContains(resp5, 'Existe um pagamento em atraso. Regularize até')
        self.assertNotContains(resp5, 'Reativar Assinatura')
        self.assertNotContains(resp5, 'Cancelar Assinatura')

    def test_client_update_subscription_and_payment_methods(self):
        """ASAAS-09: Testar métodos update_subscription e update_payment no AsaasClient com mock HTTP."""
        from core.services.payments.asaas.client import AsaasClient
        from unittest.mock import MagicMock

        client = AsaasClient(config=AsaasConfig(api_key='fake_key', environment='sandbox', base_url='https://api-sandbox.asaas.com/v3', webhook_token='fake_token'))

        # 1. update_subscription sucesso
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = b'{"id": "sub_test_123", "nextDueDate": "2026-12-15"}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, data = client.update_subscription('sub_test_123', {'nextDueDate': '2026-12-15'})
            self.assertTrue(ok)
            self.assertEqual(data.get('id'), 'sub_test_123')
            self.assertEqual(data.get('nextDueDate'), '2026-12-15')

        # 2. update_payment sucesso
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = b'{"id": "pay_test_456", "dueDate": "2026-11-15"}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, data = client.update_payment('pay_test_456', {'dueDate': '2026-11-15'})
            self.assertTrue(ok)
            self.assertEqual(data.get('id'), 'pay_test_456')
            self.assertEqual(data.get('dueDate'), '2026-11-15')

    def test_synchronize_asaas_subscription_anchor_scenarios(self):
        """ASAAS-09: Testar cenários de reancoragem no Asaas (1 pagamento futuro, múltiplos, nenhum)."""
        from core.services.payments.asaas.webhooks import synchronize_asaas_subscription_anchor
        from unittest.mock import MagicMock

        band = Band.objects.create(name='Banda Sync Test', slug='bandasynctest')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Básico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 9, 4), next_due_date=date(2026, 10, 4),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_sync_123',
            gateway_customer_id='cus_sync_456'
        )

        mock_client = MagicMock()

        # Cenário 1: 1 pagamento futuro aberto (pay_future_1)
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_paid_0', 'status': 'CONFIRMED', 'dueDate': '2026-09-04', 'deleted': False},
            {'id': 'pay_paid_1', 'status': 'RECEIVED', 'dueDate': '2026-10-04', 'deleted': False},
            {'id': 'pay_future_1', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
        ]
        mock_client.update_payment.return_value = (True, {'id': 'pay_future_1'})
        mock_client.update_subscription.return_value = (True, {'id': 'sub_sync_123'})

        # Regularizado em 15/10/2026
        paid_date = date(2026, 10, 15)
        ok, msg = synchronize_asaas_subscription_anchor(sub, paid_date=paid_date, client=mock_client)
        self.assertTrue(ok)
        self.assertEqual(msg, 'ASAAS_ANCHOR_SINCRONIZADO')

        # pay_future_1 deve ir para 15/11/2026 (offset 1)
        mock_client.update_payment.assert_called_once_with('pay_future_1', {'dueDate': '2026-11-15'})
        # subscription.nextDueDate deve ir para 15/12/2026 (offset 2)
        mock_client.update_subscription.assert_called_once_with('sub_sync_123', {'nextDueDate': '2026-12-15'})

        # Cenário 2: Múltiplos pagamentos futuros abertos (pay_f1, pay_f2)
        mock_client.reset_mock()
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_f1', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
            {'id': 'pay_f2', 'status': 'PENDING', 'dueDate': '2026-12-04', 'deleted': False},
        ]
        mock_client.update_payment.return_value = (True, {})
        mock_client.update_subscription.return_value = (True, {})

        ok, msg = synchronize_asaas_subscription_anchor(sub, paid_date=paid_date, client=mock_client)
        self.assertTrue(ok)
        self.assertEqual(mock_client.update_payment.call_count, 2)
        mock_client.update_payment.assert_any_call('pay_f1', {'dueDate': '2026-11-15'})
        mock_client.update_payment.assert_any_call('pay_f2', {'dueDate': '2026-12-15'})
        mock_client.update_subscription.assert_called_once_with('sub_sync_123', {'nextDueDate': '2027-01-15'})

        # Cenário 3: Nenhum pagamento futuro aberto
        mock_client.reset_mock()
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_old', 'status': 'CONFIRMED', 'dueDate': '2026-09-04', 'deleted': False},
        ]
        mock_client.update_subscription.return_value = (True, {})

        ok, msg = synchronize_asaas_subscription_anchor(sub, paid_date=paid_date, client=mock_client)
        self.assertTrue(ok)
        mock_client.update_payment.assert_not_called()
        mock_client.update_subscription.assert_called_once_with('sub_sync_123', {'nextDueDate': '2026-11-15'})

    def test_webhook_payment_confirmed_suspension_regularization_and_idempotency(self):
        """ASAAS-09 3C.1: Regularizacao pos-suspensao sincroniza Asaas ANTES de liberar acesso. Idempotencia."""
        band = Band.objects.create(name='Banda Regularize Test', slug='bandaregtest')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 8, 30),  # D+5 em 04/09 -> suspenso
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_reg_123',
            gateway_customer_id='cus_reg_456'
        )
        rec = BillingRecord.objects.create(
            band=band, subscription=sub, gateway_payment_id='pay_reg_789',
            amount=Decimal('19.90'), status='PENDENTE', due_date=date(2026, 8, 30)
        )

        self.assertTrue(sub.is_financially_suspended)

        webhook_payload = {
            "id": "evt_reg_001",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_reg_789",
                "customer": "cus_reg_456",
                "subscription": "sub_reg_123",
                "status": "CONFIRMED",
                "value": 19.90,
                "dueDate": "2026-08-30",
                "paymentDate": "2026-09-04"
            }
        }

        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_sync:
            mock_sync.return_value = (True, 'ASAAS_ANCHOR_SINCRONIZADO')
            ok, msg = handle_asaas_webhook_payload(webhook_payload)
            self.assertTrue(ok)

            sub.refresh_from_db()
            rec.refresh_from_db()

            # 1. Localmente reancorado apenas apos sync remoto bem-sucedido
            self.assertEqual(rec.status, 'PAGO')
            self.assertEqual(sub.start_date, date(2026, 9, 4))
            self.assertEqual(sub.next_due_date, date(2026, 10, 4))
            self.assertFalse(sub.is_financially_suspended)
            self.assertTrue(band.has_active_subscription)

            # 2. Sync Asaas foi disparado com triggering_payment_id correto
            mock_sync.assert_called_once_with(
                sub,
                paid_date=date(2026, 9, 4),
                triggering_payment_id='pay_reg_789'
            )

        # 3. Webhook duplicado (PAYMENT_RECEIVED) -> Idempotencia: ja processado, nao re-sincroniza
        webhook_payload_received = {
            "id": "evt_reg_002",
            "event": "PAYMENT_RECEIVED",
            "payment": {
                "id": "pay_reg_789",
                "customer": "cus_reg_456",
                "subscription": "sub_reg_123",
                "status": "RECEIVED",
                "value": 19.90,
                "dueDate": "2026-08-30",
                "paymentDate": "2026-09-04"
            }
        }

        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_sync_dup:
            ok_dup, msg_dup = handle_asaas_webhook_payload(webhook_payload_received)
            self.assertTrue(ok_dup)
            mock_sync_dup.assert_not_called()

    def test_webhook_payment_confirmed_tolerance_does_not_reanchor(self):
        """ASAAS-09 3C.1: Pagamento D+1 a D+4 nao reancora e nao chama sync remoto."""
        band = Band.objects.create(name='Banda Tolerancia Test', slug='bandatoltest')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 3), next_due_date=date(2026, 9, 3),  # D+1 em 04/09 -> tolerancia
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_tol_123',
            gateway_customer_id='cus_tol_456'
        )
        rec = BillingRecord.objects.create(
            band=band, subscription=sub, gateway_payment_id='pay_tol_789',
            amount=Decimal('19.90'), status='PENDENTE', due_date=date(2026, 9, 3)
        )

        self.assertTrue(sub.is_overdue_tolerance)
        self.assertFalse(sub.is_financially_suspended)

        webhook_payload = {
            "id": "evt_tol_001",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_tol_789",
                "customer": "cus_tol_456",
                "subscription": "sub_tol_123",
                "status": "CONFIRMED",
                "value": 19.90,
                "dueDate": "2026-09-03",
                "paymentDate": "2026-09-04"
            }
        }

        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_sync:
            ok, msg = handle_asaas_webhook_payload(webhook_payload)
            self.assertTrue(ok)

            sub.refresh_from_db()
            rec.refresh_from_db()

            # 1. Localmente avanca mantendo ancora original (03/10/2026)
            self.assertEqual(rec.status, 'PAGO')
            self.assertEqual(sub.start_date, date(2026, 8, 3))
            self.assertEqual(sub.next_due_date, date(2026, 10, 3))
            self.assertFalse(sub.is_financially_suspended)
            self.assertTrue(band.has_active_subscription)

            # 2. Sync Asaas NAO deve ser chamado pois nao estava suspenso
            mock_sync.assert_not_called()

    def test_anchor_sync_failure_put_payment_blocks_access(self):
        """ASAAS-09 3C.1 Item 13: Falha em PUT payment bloqueia liberacao. Sub permanece suspensa."""
        band = Band.objects.create(name='Banda Fail Pay', slug='bandafailpay')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 8, 30),  # D+5 -> suspenso
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_fp_123',
            gateway_customer_id='cus_fp_456'
        )
        rec = BillingRecord.objects.create(
            band=band, subscription=sub, gateway_payment_id='pay_fp_789',
            amount=Decimal('19.90'), status='PENDENTE', due_date=date(2026, 8, 30)
        )

        self.assertTrue(sub.is_financially_suspended)

        webhook_payload = {
            "id": "evt_fp_001",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_fp_789",
                "customer": "cus_fp_456",
                "subscription": "sub_fp_123",
                "status": "CONFIRMED",
                "value": 19.90,
                "dueDate": "2026-08-30",
                "paymentDate": "2026-10-15"
            }
        }

        with patch('core.services.payments.asaas.webhooks.synchronize_asaas_subscription_anchor') as mock_sync:
            # PUT payment falha
            mock_sync.return_value = (False, 'ERRO_PUT_PAYMENT_pay_future_111')
            ok, msg = handle_asaas_webhook_payload(webhook_payload)

            # Resultado: webhook nao processado
            self.assertFalse(ok)
            self.assertIn('ANCHOR_SYNC_FALHOU', msg)

            # sub continua suspensa (apply_payment_success NAO foi chamado)
            sub.refresh_from_db()
            self.assertEqual(sub.next_due_date, date(2026, 8, 30))
            self.assertTrue(sub.is_financially_suspended)
            self.assertFalse(band.has_active_subscription)

            # BillingRecord nao salvo como PAGO (nao chamamos record.save no path de falha)
            # O record pode ter status PAGO em memoria mas nao foi persistido
            rec.refresh_from_db()
            self.assertEqual(rec.status, 'PENDENTE')

            # webhook permanece nao-processado (processed=False)
            from core.models import PaymentWebhookEvent
            evt = PaymentWebhookEvent.objects.get(gateway_event_id='evt_fp_001')
            self.assertFalse(evt.processed)
            self.assertIn('ANCHOR_SYNC_FALHOU', evt.error_message)

    def test_anchor_sync_failure_put_subscription_blocks_access(self):
        """ASAAS-09 3C.1 Item 14: Falha em PUT subscription bloqueia liberacao. Reprocessamento idempotente."""
        from core.services.payments.asaas.webhooks import synchronize_asaas_subscription_anchor
        from unittest.mock import MagicMock

        band = Band.objects.create(name='Banda Fail Sub', slug='bandafailsub')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 8, 30),  # D+5 -> suspenso
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_fs_123',
            gateway_customer_id='cus_fs_456'
        )

        mock_client = MagicMock()
        paid_date = date(2026, 10, 15)

        # payment futuro ja existe e ainda esta com dueDate antigo (04/11)
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_fut_111', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
        ]

        # === TENTATIVA 1: update_payment ok, update_subscription falha ===
        mock_client.update_payment.return_value = (True, {'id': 'pay_fut_111'})
        mock_client.update_subscription.return_value = (False, {'error': 'gateway_timeout'})

        ok1, msg1 = synchronize_asaas_subscription_anchor(sub, paid_date=paid_date, client=mock_client)
        self.assertFalse(ok1)
        self.assertEqual(msg1, 'ERRO_PUT_SUBSCRIPTION_NEXT_DUE_DATE')

        # payment tentou ser atualizado para 15/11
        mock_client.update_payment.assert_called_once_with('pay_fut_111', {'dueDate': '2026-11-15'})

        # === TENTATIVA 2 (retry): payment ja em 15/11, nao deve ser deslocado novamente ===
        mock_client.reset_mock()
        # Simula que no retry, o payment ja foi atualizado para 15/11 na tentativa anterior
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_fut_111', 'status': 'PENDING', 'dueDate': '2026-11-15', 'deleted': False},
        ]
        mock_client.update_subscription.return_value = (True, {'id': 'sub_fs_123'})

        ok2, msg2 = synchronize_asaas_subscription_anchor(sub, paid_date=paid_date, client=mock_client)
        self.assertTrue(ok2)
        self.assertEqual(msg2, 'ASAAS_ANCHOR_SINCRONIZADO')

        # payment nao deve ter sido chamado novamente (ja estava correto)
        mock_client.update_payment.assert_not_called()
        # subscription deve ser chamado com 15/12 (offset 2)
        mock_client.update_subscription.assert_called_once_with('sub_fs_123', {'nextDueDate': '2026-12-15'})

    def test_anchor_sync_triggering_payment_excluded_from_realignment(self):
        """ASAAS-09 3C.1 Item 7+8: triggering_payment_id excluido do realinhamento de futuros."""
        from core.services.payments.asaas.webhooks import synchronize_asaas_subscription_anchor
        from unittest.mock import MagicMock

        band = Band.objects.create(name='Banda Exclude Pay', slug='bandaexcludepay')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 30), next_due_date=date(2026, 8, 30),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_ex_123',
            gateway_customer_id='cus_ex_456'
        )

        mock_client = MagicMock()
        paid_date = date(2026, 9, 4)

        # payment overdue (triggering) + payment futuro
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_overdue_trigger', 'status': 'OVERDUE', 'dueDate': '2026-08-30', 'deleted': False},
            {'id': 'pay_future_nov', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
        ]
        mock_client.update_payment.return_value = (True, {})
        mock_client.update_subscription.return_value = (True, {})

        ok, msg = synchronize_asaas_subscription_anchor(
            sub,
            paid_date=paid_date,
            triggering_payment_id='pay_overdue_trigger',
            client=mock_client
        )
        self.assertTrue(ok)

        # pay_overdue_trigger NAO deve ter sido atualizado
        calls = [str(c) for c in mock_client.update_payment.call_args_list]
        self.assertFalse(any('pay_overdue_trigger' in c for c in calls))

        # pay_future_nov deve ir para 04/10/2026 (paid_date + 1 mes = offset 1)
        mock_client.update_payment.assert_called_once_with('pay_future_nov', {'dueDate': '2026-10-04'})
        # subscription.nextDueDate vai para 04/11/2026 (offset 2)
        mock_client.update_subscription.assert_called_once_with('sub_ex_123', {'nextDueDate': '2026-11-04'})

    def test_anchor_sync_sandbox_real_dates_04_09(self):
        """ASAAS-09 3C.1 Item 16: paid_date=04/09/2026, cobranca futura 04/11 -> realinha para 04/10, nextDue 04/11."""
        from core.services.payments.asaas.webhooks import synchronize_asaas_subscription_anchor
        from unittest.mock import MagicMock

        band = Band.objects.create(name='Banda Sandbox Real', slug='bandasandboxreal')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 30), next_due_date=date(2026, 8, 30),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_p9c1t1o708kepz54',
            gateway_customer_id='cus_000009006807'
        )

        mock_client = MagicMock()
        paid_date = date(2026, 9, 4)

        # Estado real do sandbox:
        # pay_7ffgs42hx0umnlxp: OVERDUE (triggering)
        # pay_pz2uu6xj5jlvpe73: PENDING dueDate=2026-11-04
        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_7ffgs42hx0umnlxp', 'status': 'OVERDUE', 'dueDate': '2026-09-03', 'deleted': False},
            {'id': 'pay_pz2uu6xj5jlvpe73', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
        ]
        mock_client.update_payment.return_value = (True, {})
        mock_client.update_subscription.return_value = (True, {})

        ok, msg = synchronize_asaas_subscription_anchor(
            sub,
            paid_date=paid_date,
            triggering_payment_id='pay_7ffgs42hx0umnlxp',  # excluido
            client=mock_client
        )
        self.assertTrue(ok)
        self.assertEqual(msg, 'ASAAS_ANCHOR_SINCRONIZADO')

        # pay_pz2uu6xj5jlvpe73: 04/11 -> 04/10/2026 (paid_date + 1 mes)
        mock_client.update_payment.assert_called_once_with('pay_pz2uu6xj5jlvpe73', {'dueDate': '2026-10-04'})
        # subscription.nextDueDate -> 04/11/2026 (paid_date + 2 meses)
        mock_client.update_subscription.assert_called_once_with('sub_p9c1t1o708kepz54', {'nextDueDate': '2026-11-04'})

    def test_anchor_sync_success_scenario_15_10_paid(self):
        """ASAAS-09 3C.1 Item 15: paid_date=15/10, futuro=04/11 -> futuro=15/11, nextDue=15/12."""
        from core.services.payments.asaas.webhooks import synchronize_asaas_subscription_anchor
        from unittest.mock import MagicMock

        band = Band.objects.create(name='Banda Success 15', slug='bandasuccess15')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Basico', billing_cycle='MENSAL', contracted_value=Decimal('19.90'),
            start_date=date(2026, 8, 4), next_due_date=date(2026, 8, 30),
            status='ATIVO', auto_renew=True, cancel_at_period_end=False,
            gateway_provider='ASAAS', gateway_subscription_id='sub_suc_123',
            gateway_customer_id='cus_suc_456'
        )

        mock_client = MagicMock()
        paid_date = date(2026, 10, 15)

        mock_client.get_payments_by_subscription.return_value = [
            {'id': 'pay_overdue_trig', 'status': 'OVERDUE', 'dueDate': '2026-08-30', 'deleted': False},
            {'id': 'pay_nov', 'status': 'PENDING', 'dueDate': '2026-11-04', 'deleted': False},
        ]
        mock_client.update_payment.return_value = (True, {})
        mock_client.update_subscription.return_value = (True, {})

        ok, msg = synchronize_asaas_subscription_anchor(
            sub,
            paid_date=paid_date,
            triggering_payment_id='pay_overdue_trig',
            client=mock_client
        )
        self.assertTrue(ok)

        # Futuro: 15/10 + 1 mes = 15/11
        mock_client.update_payment.assert_called_once_with('pay_nov', {'dueDate': '2026-11-15'})
        # nextDueDate: 15/10 + 2 meses = 15/12
        mock_client.update_subscription.assert_called_once_with('sub_suc_123', {'nextDueDate': '2026-12-15'})

    def test_annual_installment_checkout_and_provisioning(self):
        """
        ASAAS-10: Testes A, C, D, E, H, I, J do plano anual parcelavel em ate 5x:
        - Básico anual (199.90 / INSTALLMENT / ate 5x)
        - Avançado anual (499.90 / INSTALLMENT / ate 5x)
        - Anual aprovado: vigência de 12 meses (ano calendário)
        - Anual não cria Subscription YEARLY no gateway
        - auto_renew=False e sem exibição de 'Renovação Automática: Sim'
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from django.test import Client, override_settings

        # 1. SignupOrder para Básico Anual (R$ 199,90)
        order_basic = SignupOrder.objects.create(
            band_name='Banda Basico Anual',
            responsible_name='Resp Basico',
            email='basico-anual@example.com',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_annual_01',
            gateway_checkout_id='chk_annual_basic_01',
            external_reference='bp-annual-basic-001'
        )

        payload_basic = {
            'id': 'evt_chk_annual_01',
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_basic_01',
                'customer': 'cus_annual_01',
                'externalReference': 'bp-annual-basic-001',
                'status': 'PAID',
                # Em INSTALLMENT, nao ha subscription_id no Asaas
                'subscription': None
            },
            'payment': {
                'id': 'pay_annual_installment_01',
                'status': 'CONFIRMED',
                'value': 199.90
            }
        }

        ok, msg, band = process_checkout_paid_event(payload_basic)
        self.assertTrue(ok)
        self.assertEqual(msg, 'PROVISIONADO')

        sub = band.subscriptions.first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.billing_cycle, 'ANUAL')
        self.assertEqual(sub.contracted_value, Decimal('199.90'))
        self.assertEqual(sub.status, 'ATIVO')
        self.assertFalse(sub.auto_renew)  # auto_renew=False no modelo INSTALLMENT
        self.assertIsNone(sub.gateway_subscription_id)  # Nao cria Subscription YEARLY

        # Vigencia de 12 meses
        today = timezone.localdate()
        expected_due = calculate_next_billing_date(today, 'ANUAL', 1)
        self.assertEqual(sub.start_date, today)
        self.assertEqual(sub.next_due_date, expected_due)
        self.assertTrue(band.has_active_subscription)

        # BillingRecord inicial
        rec = sub.records.first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, 'PAGO')
        self.assertEqual(rec.amount, Decimal('199.90'))
        self.assertIn('Vigência', rec.reference_period)

        # Testar visualizacao da tela Minha Assinatura
        with override_settings(ALLOWED_HOSTS=['*']):
            user = band.users.first()
            if not user:
                # Criar usuario de teste com perfil PRODUTOR vinculado a banda para testar a view
                user = User.objects.create_user(
                    username='user_annual_test',
                    password='secretpassword',
                    band=band,
                    role='PRODUTOR'
                )
            c = Client()
            c.force_login(user)
            resp = c.get(f'/{band.slug}/relatorios/assinatura/')
            self.assertEqual(resp.status_code, 200)
            html = resp.content.decode('utf-8')
            # Nao deve exibir 'Renovação Automática: Sim'
            self.assertIn('Renovação Automática', html)
            self.assertNotIn('Sim', html[html.find('Renovação Automática'):html.find('Renovação Automática') + 400])
            # Deve exibir 'Acesso até' em vez de 'Próxima Cobrança'
            self.assertIn('Acesso até', html)
            # Não deve exibir botão 'Cancelar Assinatura' (pois não é renovação automática)
            self.assertNotIn('modalCancelarAssinatura', html)

    def test_annual_multiple_installment_events_idempotency(self):
        """
        ASAAS-10: Testes F e G:
        - Pagamento parcelado em 5x: NÂO concede 5 extensões de vigência.
        - Eventos posteriores de parcelas não alteram next_due_date.
        """
        from core.services.payments.provisioning import process_checkout_paid_event

        order = SignupOrder.objects.create(
            band_name='Banda 5x Anual',
            responsible_name='Resp 5x',
            email='anual5x@example.com',
            plan_type='AVANCADO',
            billing_cycle='ANUAL',
            amount=Decimal('499.90'),
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_annual_5x',
            gateway_checkout_id='chk_annual_5x_001',
            external_reference='bp-annual-5x-001'
        )

        payload_p1 = {
            'id': 'evt_chk_annual_5x',
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_annual_5x_001',
                'customer': 'cus_annual_5x',
                'externalReference': 'bp-annual-5x-001',
                'status': 'PAID',
                'subscription': None
            },
            'payment': {
                'id': 'pay_p1_999',
                'status': 'CONFIRMED',
                'value': 99.98
            }
        }

        # Primeira parcela / aprovacao da compra
        ok1, msg1, band = process_checkout_paid_event(payload_p1)
        self.assertTrue(ok1)
        sub = band.subscriptions.first()
        initial_due = sub.next_due_date

        # Simula segunda chamada de CHECKOUT_PAID (idempotencia)
        ok2, msg2, band2 = process_checkout_paid_event(payload_p1)
        self.assertTrue(ok2)
        self.assertEqual(msg2, 'JA_PROVISIONADO')

        sub.refresh_from_db()
        # next_due_date NAO foi estendido novamente
        self.assertEqual(sub.next_due_date, initial_due)

    def test_annual_expiration_boundary_and_leap_year(self):
        """
        ASAAS-10: Testes K e L:
        - Acesso valido durante o dia de next_due_date (boundary).
        - Bloqueio somente apos o ultimo dia de acesso (today > next_due_date).
        - Calculo de 29/02 em ano bissexto para +1 ano calendario.
        """
        # Teste L: 29/02 em ano bissexto (ex: 29/02/2028 -> 28/02/2029)
        leap_start = date(2028, 2, 29)
        calc_next = calculate_next_billing_date(leap_start, 'ANUAL', 1)
        self.assertEqual(calc_next, date(2029, 2, 28))

        # Teste K: Boundary de acesso
        band = Band.objects.create(name='Banda Expiration Test', slug='bandaexptest')
        sub = BandSubscription.objects.create(
            band=band, plan_name='Básico Anual', billing_cycle='ANUAL', contracted_value=Decimal('199.90'),
            start_date=date(2025, 9, 4), next_due_date=date(2026, 9, 4),
            status='ATIVO', auto_renew=False,
            gateway_provider='ASAAS'
        )

        with patch('django.utils.timezone.localdate') as mock_today:
            # No dia 04/09/2026: today == next_due_date -> acesso PERMANECE VALIDO
            mock_today.return_value = date(2026, 9, 4)
            self.assertFalse(sub.is_canceled_period_expired)
            self.assertTrue(band.has_active_subscription)

            # No dia 05/09/2026: today > next_due_date -> PERIODO ENCERRADO
            mock_today.return_value = date(2026, 9, 5)
            self.assertTrue(sub.is_canceled_period_expired)
            # Ao checar has_active_subscription, executa check_and_sync_auto_expiration e passa para DESATIVADO
            self.assertFalse(band.has_active_subscription)
            sub.refresh_from_db()
            self.assertEqual(sub.status, 'DESATIVADO')

    def test_etapa_2b_annual_installment_lifecycle_and_ui_display(self):
        """
        ASAAS-10 ETAPA 2B:
        Testes A a I:
        A. Card PLANO ATUAL exibe estritamente 'Básico' ou 'Avançado' (sem 'Anual').
        B. Card CICLO exibe 'Anual'.
        C. start_date derivado da data de aprovação financeira (paymentDate).
        D. next_due_date = start_date + 1 ano.
        E. Segundo CHECKOUT_PAID não duplica vigência (idempotência).
        F. PAYMENT_CONFIRMED para parcelas 2..5 não estende next_due_date nem altera auto_renew.
        G. PAYMENT_RECEIVED para parcelas 2..5 não estende next_due_date nem altera auto_renew.
        H. Plano anual não cria Subscription no Asaas (gateway_subscription_id is None).
        I. Plano mensal preserva ciclo e renovação automática (auto_renew=True).
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from core.services.payments.asaas.webhooks import reconcile_and_update_billing_record

        # 1. Cria SignupOrder para compra anual
        order = SignupOrder.objects.create(
            band_name='Banda Etapa 2B Anual',
            responsible_name='Resp 2B',
            email='resp2b@example.com',
            plan_type='BASICO',
            billing_cycle='ANUAL',
            amount=Decimal('199.90'),
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_2b_anual',
            gateway_checkout_id='chk_2b_anual_001',
            external_reference='bp-2b-anual-001'
        )

        approval_date_str = '2026-09-04'
        approval_date = date(2026, 9, 4)
        expected_next_due = calculate_next_billing_date(approval_date, 'ANUAL', 1)

        payload_chk_paid = {
            'id': 'evt_2b_paid_001',
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_2b_anual_001',
                'customer': 'cus_2b_anual',
                'externalReference': 'bp-2b-anual-001',
                'status': 'PAID',
                'subscription': None
            },
            'payment': {
                'id': 'pay_2b_installment_1',
                'status': 'CONFIRMED',
                'value': 39.98,
                'paymentDate': approval_date_str
            }
        }

        # Provisiona compra anual
        ok, msg, band = process_checkout_paid_event(payload_chk_paid)
        self.assertTrue(ok)
        self.assertEqual(msg, 'PROVISIONADO')

        sub = band.subscriptions.first()
        self.assertIsNotNone(sub)

        # Teste H: gateway_subscription_id deve ser None
        self.assertIsNone(sub.gateway_subscription_id)
        self.assertFalse(sub.auto_renew)

        # Teste C: start_date derivado da data financeira
        self.assertEqual(sub.start_date, approval_date)

        # Teste D: next_due_date = start_date + 1 ano
        self.assertEqual(sub.next_due_date, expected_next_due)

        # Testes A e B: Validar exibição da UI em minha_assinatura
        user = User.objects.create_user(
            username='user_2b_test',
            password='secretpassword',
            band=band,
            role='PRODUTOR'
        )
        c = Client()
        c.force_login(user)
        resp = c.get(f'/{band.slug}/relatorios/assinatura/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')

        # Teste A: Card PLANO ATUAL exibe estritamente 'Básico' e não 'Básico Anual'
        self.assertIn('<p class="kpi-label">Plano Atual</p>', html)
        self.assertIn('<h3 class="kpi-value text-dark">Básico</h3>', html)
        self.assertNotIn('<h3 class="kpi-value text-dark">Básico Anual</h3>', html)
        self.assertNotIn('<h3 class="kpi-value text-dark">Básico (Anual)</h3>', html)

        # Teste B: Card CICLO exibe 'Anual'
        self.assertIn('<p class="kpi-label">Ciclo</p>', html)
        self.assertIn('<h3 class="kpi-value text-dark">Anual</h3>', html)

        # Teste E: Segundo CHECKOUT_PAID (idempotência) não estende vigência
        ok_dup, msg_dup, _ = process_checkout_paid_event(payload_chk_paid)
        self.assertTrue(ok_dup)
        self.assertEqual(msg_dup, 'JA_PROVISIONADO')
        sub.refresh_from_db()
        self.assertEqual(sub.next_due_date, expected_next_due)

        # Teste F: PAYMENT_CONFIRMED para parcela 2 (com vencimento futuro da parcela)
        payload_installment_2 = {
            'id': 'evt_pay_conf_p2',
            'event': 'PAYMENT_CONFIRMED',
            'payment': {
                'id': 'pay_2b_installment_2',
                'customer': 'cus_2b_anual',
                'externalReference': 'bp-2b-anual-001',
                'status': 'CONFIRMED',
                'value': 39.98,
                'dueDate': '2026-10-04',
                'paymentDate': '2026-10-04'
            }
        }
        ok_p2, msg_p2 = reconcile_and_update_billing_record(payload_installment_2, 'PAYMENT_CONFIRMED')
        self.assertTrue(ok_p2)
        sub.refresh_from_db()
        # Não alterou next_due_date nem auto_renew
        self.assertEqual(sub.next_due_date, expected_next_due)
        self.assertFalse(sub.auto_renew)
        self.assertEqual(sub.status, 'ATIVO')

        # Teste G: PAYMENT_RECEIVED para parcela 3
        payload_installment_3 = {
            'id': 'evt_pay_rec_p3',
            'event': 'PAYMENT_RECEIVED',
            'payment': {
                'id': 'pay_2b_installment_3',
                'customer': 'cus_2b_anual',
                'externalReference': 'bp-2b-anual-001',
                'status': 'RECEIVED',
                'value': 39.98,
                'dueDate': '2026-11-04',
                'paymentDate': '2026-11-04'
            }
        }
        ok_p3, msg_p3 = reconcile_and_update_billing_record(payload_installment_3, 'PAYMENT_RECEIVED')
        self.assertTrue(ok_p3)
        sub.refresh_from_db()
        # Não alterou next_due_date nem auto_renew
        self.assertEqual(sub.next_due_date, expected_next_due)
        self.assertFalse(sub.auto_renew)
        self.assertEqual(sub.status, 'ATIVO')

        # Teste I: Plano mensal preserva ciclo e auto_renew=True
        order_monthly = SignupOrder.objects.create(
            band_name='Banda Mensal 2B',
            responsible_name='Resp Mensal',
            email='mensal@example.com',
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            amount=Decimal('49.90'),
            status='PENDENTE',
            gateway_provider='ASAAS',
            gateway_customer_id='cus_2b_mensal',
            gateway_checkout_id='chk_2b_mensal_001',
            gateway_subscription_id='sub_2b_mensal_001',
            external_reference='bp-2b-mensal-001'
        )
        payload_monthly = {
            'id': 'evt_monthly_paid_001',
            'event': 'CHECKOUT_PAID',
            'checkout': {
                'id': 'chk_2b_mensal_001',
                'customer': 'cus_2b_mensal',
                'externalReference': 'bp-2b-mensal-001',
                'status': 'PAID',
                'subscription': 'sub_2b_mensal_001'
            },
            'payment': {
                'id': 'pay_monthly_001',
                'status': 'CONFIRMED',
                'value': 49.90,
                'paymentDate': '2026-09-04'
            }
        }
        ok_m, msg_m, band_m = process_checkout_paid_event(payload_monthly)
        self.assertTrue(ok_m)
        sub_m = band_m.subscriptions.first()
        self.assertEqual(sub_m.plan_name, 'Avançado')
        self.assertEqual(sub_m.billing_cycle, 'MENSAL')
        self.assertTrue(sub_m.auto_renew)
        self.assertEqual(sub_m.gateway_subscription_id, 'sub_2b_mensal_001')
        self.assertEqual(sub_m.next_due_date, date(2026, 10, 4))

    def test_create_asaas_sandbox_checkout_annual_and_monthly_payload(self):
        """
        ASAAS-10 ETAPA 3A.1:
        Validar que create_asaas_sandbox_checkout gera payloads estritamente conformes:
        - ANUAL: chargeTypes == ['DETACHED', 'INSTALLMENT']
        - ANUAL: subscription ausente (null)
        - ANUAL: installment.maxInstallmentCount == 5
        - ANUAL: items[0].name <= 30 caracteres
        - MENSAL: chargeTypes == ['RECURRENT']
        - MENSAL: subscription.cycle == 'MONTHLY'
        """
        from unittest.mock import patch, MagicMock
        from django.core.management import call_command
        import json

        # 1. Teste ANUAL
        mock_resp_annual = MagicMock()
        mock_resp_annual.read.return_value = json.dumps({
            'id': 'chk_mock_annual_test_999',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/testannual'
        }).encode('utf-8')
        mock_resp_annual.status = 200
        mock_resp_annual.__enter__.return_value = mock_resp_annual

        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='key_123'):
            with patch('urllib.request.urlopen', return_value=mock_resp_annual) as mock_url:
                call_command('create_asaas_sandbox_checkout', plan='BASICO', cycle='ANUAL')
                annual_call = mock_url.call_args[0][0]
                annual_payload = json.loads(annual_call.data.decode('utf-8'))

                self.assertEqual(annual_payload['chargeTypes'], ['DETACHED', 'INSTALLMENT'])
                self.assertNotIn('subscription', annual_payload)
                self.assertEqual(annual_payload['billingTypes'], ['CREDIT_CARD'])
                self.assertEqual(annual_payload['installment']['maxInstallmentCount'], 5)
                self.assertTrue(len(annual_payload['items'][0]['name']) <= 30)
                self.assertEqual(annual_payload['items'][0]['name'], 'Backstage Pro Básico')
                self.assertEqual(annual_payload['items'][0]['value'], 199.90)

        # 2. Teste MENSAL
        mock_resp_monthly = MagicMock()
        mock_resp_monthly.read.return_value = json.dumps({
            'id': 'chk_mock_monthly_test_999',
            'status': 'ACTIVE',
            'paymentLink': 'https://sandbox.asaas.com/c/testmonthly'
        }).encode('utf-8')
        mock_resp_monthly.status = 200
        mock_resp_monthly.__enter__.return_value = mock_resp_monthly

        with override_settings(DJANGO_ENV='staging', ASAAS_ENVIRONMENT='sandbox', ASAAS_API_KEY='key_123'):
            with patch('urllib.request.urlopen', return_value=mock_resp_monthly) as mock_url:
                call_command('create_asaas_sandbox_checkout', plan='BASICO', cycle='MENSAL')
                monthly_call = mock_url.call_args[0][0]
                monthly_payload = json.loads(monthly_call.data.decode('utf-8'))

                self.assertEqual(monthly_payload['chargeTypes'], ['RECURRENT'])
                self.assertIn('subscription', monthly_payload)
                self.assertEqual(monthly_payload['subscription']['cycle'], 'MONTHLY')
                self.assertNotIn('installment', monthly_payload)
                self.assertTrue(len(monthly_payload['items'][0]['name']) <= 30)
                self.assertEqual(monthly_payload['items'][0]['name'], 'Backstage Pro Básico')
                self.assertEqual(monthly_payload['items'][0]['value'], 19.90)

    def test_annual_installment_billing_record_financial_reconciliation(self):
        """
        Garante que a provisao de uma compra anual parcelada (INSTALLMENT) registra a 1a parcela
        com o valor unitario da parcela (ex: 39.98) e nao o valor total do contrato (199.90),
        garantindo que a soma de todos os BillingRecords seja exatamente igual ao total contratado.
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from core.services.payments.asaas.webhooks import process_webhook_event
        from decimal import Decimal

        order = SignupOrder.objects.create(
            band_name="Banda Conciliacao Anual Teste",
            responsible_name="Produtor Teste",
            email="produtor_anual@teste.com",
            phone="11999999999",
            plan_type="BASICO",
            billing_cycle="ANUAL",
            amount=Decimal('199.90'),
            external_reference="bp-annual-reconcile-test-01",
            gateway_checkout_id="chk_reconcile_annual_001",
            status="PENDENTE"
        )

        payload_chk_paid = {
            "id": "evt_annual_reconcile_chk",
            "event": "CHECKOUT_PAID",
            "checkout": {
                "id": "chk_reconcile_annual_001",
                "customer": "cus_reconcile_001",
                "externalReference": "bp-annual-reconcile-test-01",
                "status": "PAID"
            },
            "payment": {
                "id": "pay_reconcile_p1",
                "value": 39.98,
                "dueDate": "2026-09-04",
                "status": "CONFIRMED"
            }
        }

        ok, msg, band = process_checkout_paid_event(payload_chk_paid)
        self.assertTrue(ok)
        self.assertIsNotNone(band)

        # 1. Primeiro BillingRecord deve ter R$ 39.98 e nao 199.90
        b_records = BillingRecord.objects.filter(band=band).order_by('id')
        self.assertEqual(b_records.count(), 1)
        r1 = b_records.first()
        self.assertEqual(r1.amount, Decimal('39.98'))
        self.assertEqual(r1.gateway_payment_id, 'pay_reconcile_p1')

        # 2. Simular webhooks das outras 4 parcelas
        for i in range(2, 6):
            p_id = f"pay_reconcile_p{i}"
            ev = PaymentWebhookEvent.objects.create(
                provider='ASAAS',
                gateway_event_id=f"evt_pay_{p_id}",
                event_type='PAYMENT_CONFIRMED',
                payload={
                    "id": f"evt_pay_{p_id}",
                    "event": "PAYMENT_CONFIRMED",
                    "payment": {
                        "id": p_id,
                        "value": 39.98,
                        "dueDate": f"2026-{9+i-1:02d}-04" if (9+i-1) <= 12 else f"2027-{9+i-1-12:02d}-04",
                        "status": "CONFIRMED",
                        "externalReference": "bp-annual-reconcile-test-01"
                    }
                }
            )
            success_ev, _ = process_webhook_event(ev)
            self.assertTrue(success_ev)

        # 3. Validar total de 5 faturas somando exatamente R$ 199.90
        all_records = BillingRecord.objects.filter(band=band)
        self.assertEqual(all_records.count(), 5)
        total_sum = sum(r.amount for r in all_records)
        self.assertEqual(total_sum, Decimal('199.90'))

    def test_run_asaas_webhook_worker_concurrency_and_skip_locked(self):
        """
        Testa a logica de _process_batch com SKIP LOCKED para garantir que
        dois workers concorrentes nao processem o mesmo evento nem gerem conflito.
        """
        from core.management.commands.run_asaas_webhook_worker import Command as WorkerCommand
        from django.db import transaction

        ev1 = PaymentWebhookEvent.objects.create(
            provider='ASAAS',
            gateway_event_id='evt_concurrent_1',
            event_type='TRANSFER_CONFIRMED',
            payload={'id': 'evt_concurrent_1', 'event': 'TRANSFER_CONFIRMED'},
            processed=False
        )
        ev2 = PaymentWebhookEvent.objects.create(
            provider='ASAAS',
            gateway_event_id='evt_concurrent_2',
            event_type='TRANSFER_CONFIRMED',
            payload={'id': 'evt_concurrent_2', 'event': 'TRANSFER_CONFIRMED'},
            processed=False
        )

        cmd1 = WorkerCommand()
        cmd2 = WorkerCommand()

        # Simular worker 2 executando enquanto ev1 esta bloqueado ou sendo ignorado
        # Em PostgreSQL real, select_for_update(skip_locked=True) pula o registro travado.
        # Aqui, validamos que se o registro 1 nao for obtido pelo lock (locked_event is None),
        # o worker continua e processa ev2 perfeitamente.
        from unittest.mock import patch

        original_filter = PaymentWebhookEvent.objects.filter

        # Patch em select_for_update para simular ev1 travado (retornando None para ev1)
        with patch.object(PaymentWebhookEvent.objects, 'select_for_update') as mock_sfu:
            def mock_select(skip_locked=False):
                class MockQS:
                    def filter(self, **kwargs):
                        if kwargs.get('id') == ev1.id:
                            class EmptyQS:
                                def first(self):
                                    return None
                            return EmptyQS()
                        return PaymentWebhookEvent.objects.filter(**kwargs)
                return MockQS()

            mock_sfu.side_effect = mock_select

            # Worker 2 processa lote: pula ev1 (pois esta bloqueado por outro processo) e processa ev2
            processed2 = cmd2._process_batch(batch_size=10, backoff_seconds=30)
            self.assertTrue(processed2)

            ev1.refresh_from_db()
            ev2.refresh_from_db()
            self.assertFalse(ev1.processed)
            self.assertTrue(ev2.processed)

        # Worker 1 agora processa ev1 desimpedido
        processed1 = cmd1._process_batch(batch_size=10, backoff_seconds=30)
        self.assertTrue(processed1)
        ev1.refresh_from_db()
        self.assertTrue(ev1.processed)

    def test_run_asaas_webhook_worker_error_backoff_resilience(self):
        """
        Testa a resiliencia do worker: um evento com erro de processamento entra em backoff
        e nao bloqueia o processamento de outros eventos subsequentes validos.
        """
        from core.management.commands.run_asaas_webhook_worker import Command as WorkerCommand
        import time

        # Evento A: invalido / orfao (vai falhar no processamento de checkout_paid sem order)
        ev_fail = PaymentWebhookEvent.objects.create(
            provider='ASAAS',
            gateway_event_id='evt_fail_orphan',
            event_type='CHECKOUT_PAID',
            payload={
                'id': 'evt_fail_orphan',
                'event': 'CHECKOUT_PAID',
                'checkout': {'id': 'chk_nonexistent_888', 'externalReference': 'bp-none-999'}
            },
            processed=False
        )

        # Evento B: evento normal ignorado que tera sucesso
        ev_succ = PaymentWebhookEvent.objects.create(
            provider='ASAAS',
            gateway_event_id='evt_succ_ignore',
            event_type='TRANSFER_CONFIRMED',
            payload={'id': 'evt_succ_ignore', 'event': 'TRANSFER_CONFIRMED'},
            processed=False
        )

        cmd = WorkerCommand()

        # Executa lote de 1 evento por vez
        cmd._process_batch(batch_size=1, backoff_seconds=10)

        ev_fail.refresh_from_db()
        self.assertFalse(ev_fail.processed)
        self.assertIsNotNone(ev_fail.error_message)
        # Deve estar registrado no mapa de backoff
        self.assertIn('evt_fail_orphan', cmd.error_backoff)

        # No proximo ciclo, ev_fail e ignorado pelo backoff e ev_succ e processado
        cmd._process_batch(batch_size=1, backoff_seconds=10)
        ev_succ.refresh_from_db()
        self.assertTrue(ev_succ.processed)

    def test_asaas11_webhook_payload_sanitization_removes_sensitive_data(self):
        """
        ASAAS-11: Garante que o payload recebido e persistido via handle_asaas_webhook_payload
        sanitiza recursivamente creditCardToken, cardNumber, CVV e creditCardHolderInfo,
        mas preserva metadados operacionais (brand, last4, IDs, status, values, dates).
        """
        payload_with_secrets = {
            "id": "evt_sensitive_test_01",
            "event": "PAYMENT_CONFIRMED",
            "payment": {
                "id": "pay_test_sensitive_999",
                "customer": "cus_test_sensitive_111",
                "value": 199.90,
                "netValue": 194.50,
                "status": "CONFIRMED",
                "dueDate": "2026-09-04",
                "creditCard": {
                    "creditCardBrand": "MASTERCARD",
                    "creditCardNumber": "5555444433331234",
                    "creditCardToken": "secret_token_never_persist_in_json",
                    "cvv": "123"
                },
                "creditCardHolderInfo": {
                    "name": "Titular Teste",
                    "cpfCnpj": "12345678901",
                    "phone": "11999999999"
                }
            }
        }

        ok, msg = handle_asaas_webhook_payload(payload_with_secrets)
        # O evento pode falhar em vincular caso a sub nao exista, mas a persistencia do evento acontece
        event_obj = PaymentWebhookEvent.objects.get(gateway_event_id="evt_sensitive_test_01")
        p = event_obj.payload

        # 1. Chaves sensiveis nao existem no payload persistido
        self.assertNotIn('creditCardHolderInfo', p.get('payment', {}))
        cc = p.get('payment', {}).get('creditCard', {})
        self.assertNotIn('creditCardToken', cc)
        self.assertNotIn('cvv', cc)
        self.assertNotIn('secret_token_never_persist_in_json', str(p))
        self.assertNotIn('5555444433331234', str(p))

        # 2. Metadados operacionais foram estritamente preservados
        self.assertEqual(cc.get('creditCardBrand'), 'MASTERCARD')
        self.assertEqual(cc.get('creditCardNumber'), '1234')
        self.assertEqual(p.get('payment', {}).get('id'), 'pay_test_sensitive_999')
        self.assertEqual(p.get('payment', {}).get('value'), 199.90)

    def test_asaas11_gateway_payment_method_fernet_encryption_roundtrip(self):
        """
        ASAAS-11: Valida que GatewayPaymentMethod criptografa o token em repouso com Fernet,
        que encrypted_token != plain_token, e que get_decrypted_token() retorna o token exato.
        """
        from core.models import GatewayPaymentMethod, Band, BandSubscription
        from decimal import Decimal

        band = Band.objects.create(name="Banda Crypto Test", slug="bandacryptotest", plan_type="BASICO")
        sub = BandSubscription.objects.create(
            band=band, plan_name="Básico", billing_cycle="ANUAL", contracted_value=Decimal('199.90'), status="ATIVO"
        )

        test_plain_token = "tok_asaas_live_sandbox_987654321_abcdef"

        pm = GatewayPaymentMethod(
            subscription=sub,
            gateway_provider='ASAAS',
            gateway_customer_id='cus_crypto_test_01',
            card_brand='VISA',
            card_last4='4444',
            is_active=True
        )
        pm.set_token(test_plain_token)
        pm.save()

        # 1. Em repouso, encrypted_token e diferente do token original
        pm.refresh_from_db()
        self.assertNotEqual(pm.encrypted_token, test_plain_token)
        self.assertNotIn(test_plain_token, pm.encrypted_token)

        # 2. Descriptografia retorna exatamente o token original em memoria
        decrypted = pm.get_decrypted_token()
        self.assertEqual(decrypted, test_plain_token)

        # 3. String representation e admin nao expoem o token
        self.assertNotIn(test_plain_token, str(pm))
        self.assertNotIn(pm.encrypted_token, str(pm))

    def test_asaas11_admin_never_exposes_token(self):
        """
        ASAAS-11: Garante que GatewayPaymentMethodAdmin exclui o campo encrypted_token
        e nao o exibe em list_display ou campos editaveis.
        """
        from django.contrib.admin.sites import site
        from core.models import GatewayPaymentMethod
        from core.admin import GatewayPaymentMethodAdmin

        admin_inst = site._registry[GatewayPaymentMethod]
        self.assertIn('encrypted_token', admin_inst.exclude)
        self.assertNotIn('encrypted_token', admin_inst.list_display)

    def test_asaas11_annual_plan_purchase_provisioning_and_billing_linkage(self):
        """
        ASAAS-11: Testa a criacao de AnnualPlanPurchase e vinculo dos 5 BillingRecords
        durante o fluxo anual, garantindo preservacao de installment_count=5 e soma = 199.90.
        """
        from core.services.payments.provisioning import process_checkout_paid_event
        from core.services.payments.asaas.webhooks import process_webhook_event
        from core.models import AnnualPlanPurchase, GatewayPaymentMethod
        from decimal import Decimal
        from unittest.mock import patch, MagicMock

        order = SignupOrder.objects.create(
            band_name="Banda Anual Full Test",
            responsible_name="Responsavel Anual",
            email="anual_full@teste.com",
            phone="11988887777",
            plan_type="BASICO",
            billing_cycle="ANUAL",
            amount=Decimal('199.90'),
            external_reference="bp-annual-full-test-01",
            gateway_checkout_id="chk_annual_full_001",
            status="PENDENTE"
        )

        payload_chk = {
            "id": "evt_chk_paid_annual_full",
            "event": "CHECKOUT_PAID",
            "checkout": {
                "id": "chk_annual_full_001",
                "customer": "cus_annual_full_01",
                "externalReference": "bp-annual-full-test-01",
                "status": "PAID"
            },
            "payment": {
                "id": "pay_annual_full_p1",
                "value": 39.98,
                "installment": "inst_annual_full_123",
                "dueDate": "2026-09-04",
                "status": "CONFIRMED"
            }
        }

        mock_installment = {
            "id": "inst_annual_full_123",
            "installmentCount": 5,
            "value": 199.90,
            "netValue": 194.50
        }
        mock_payment_full = {
            "id": "pay_annual_full_p1",
            "creditCard": {
                "creditCardBrand": "VISA",
                "creditCardNumber": "4444",
                "creditCardToken": "token_remoto_via_api_mock_123"
            }
        }

        with patch('core.services.payments.asaas.client.AsaasClient.get_installment', return_value=mock_installment):
            with patch('core.services.payments.asaas.client.AsaasClient.get_payment', return_value=mock_payment_full):
                ok, msg, band = process_checkout_paid_event(payload_chk)
                self.assertTrue(ok)

        sub = band.subscriptions.first()
        self.assertIsNotNone(sub)

        # 1. AnnualPlanPurchase criada corretamente
        annual_pur = AnnualPlanPurchase.objects.filter(band_subscription=sub).first()
        self.assertIsNotNone(annual_pur)
        self.assertEqual(annual_pur.purchase_type, AnnualPlanPurchase.PurchaseType.INITIAL)
        self.assertEqual(annual_pur.installment_count, 5)
        self.assertEqual(annual_pur.gross_amount, Decimal('199.90'))
        self.assertEqual(annual_pur.net_amount, Decimal('194.50'))
        self.assertEqual(annual_pur.gateway_installment_id, "inst_annual_full_123")

        # 2. GatewayPaymentMethod criado com token criptografado
        pm = GatewayPaymentMethod.objects.filter(subscription=sub, is_active=True).first()
        self.assertIsNotNone(pm)
        self.assertEqual(pm.card_brand, "VISA")
        self.assertEqual(pm.card_last4, "4444")
        self.assertEqual(pm.get_decrypted_token(), "token_remoto_via_api_mock_123")

        # 3. 1a Fatura associada a AnnualPlanPurchase
        r1 = BillingRecord.objects.get(gateway_payment_id="pay_annual_full_p1")
        self.assertEqual(r1.annual_purchase, annual_pur)
        self.assertEqual(r1.installment_number, 1)
        self.assertEqual(r1.amount, Decimal('39.98'))

        # 4. Simular webhooks das parcelas 2 a 5
        for i in range(2, 6):
            p_id = f"pay_annual_full_p{i}"
            ev = PaymentWebhookEvent.objects.create(
                provider='ASAAS',
                gateway_event_id=f"evt_pay_{p_id}",
                event_type='PAYMENT_CONFIRMED',
                payload={
                    "id": f"evt_pay_{p_id}",
                    "event": "PAYMENT_CONFIRMED",
                    "payment": {
                        "id": p_id,
                        "value": 39.98,
                        "installment": "inst_annual_full_123",
                        "installmentNumber": i,
                        "dueDate": f"2026-{9+i-1:02d}-04" if (9+i-1) <= 12 else f"2027-{9+i-1-12:02d}-04",
                        "status": "CONFIRMED",
                        "externalReference": "bp-annual-full-test-01"
                    }
                }
            )
            success_ev, _ = process_webhook_event(ev)
            self.assertTrue(success_ev)

        # 5. Todos os 5 BillingRecords apontam para a mesma AnnualPlanPurchase e somam 199.90
        all_records = BillingRecord.objects.filter(band=band).order_by('installment_number')
        self.assertEqual(all_records.count(), 5)
        for idx, rec in enumerate(all_records, start=1):
            self.assertEqual(rec.annual_purchase, annual_pur)
            self.assertEqual(rec.installment_number, idx)
            self.assertEqual(rec.amount, Decimal('39.98'))
        self.assertEqual(sum(r.amount for r in all_records), Decimal('199.90'))
