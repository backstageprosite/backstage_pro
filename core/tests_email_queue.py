import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core import mail
from django.core.management import call_command

from core.models import (
    Band,
    User,
    BandSubscription,
    BandActivationToken,
    AnnualPlanPurchase,
    AnnualRenewalNotice,
    EmailDelivery,
)
from core.services.email_service import (
    enqueue_email,
    render_and_send_email_delivery,
    resolve_subscription_recipient,
    generate_deterministic_message_id,
)


class EmailDeliveryQueueTestCase(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Teste Email",
            slug="banda-teste-email",
            plan_type=Band.PlanType.AVANCADO,
        )
        self.user = User.objects.create_user(
            username="produtor_teste",
            email="produtor@teste.com",
            first_name="Carlos",
            last_name="Silva",
            role="PRODUTOR",
            band=self.band
        )
        self.subscription = BandSubscription.objects.create(
            band=self.band,
            plan_name="Avançado",
            billing_cycle="ANUAL",
            contracted_value=Decimal("499.90"),
            start_date=datetime.date(2026, 9, 4),
            next_due_date=datetime.date(2027, 9, 4),
            status="ATIVO",
            auto_renew=True,
            billing_email="financeiro@teste.com",
            financial_responsible_name="Carlos Financeiro"
        )

    def test_enqueue_email_creation_and_fields(self):
        delivery, created = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="teste@dominio.com",
            subject="Assunto Teste",
            idempotency_key="test-key-001",
            template_name="emails/system_test",
            context_data={"user_name": "Destinatario Teste", "environment_name": "Homologação"},
            related_object_type="Band",
            related_object_id=str(self.band.id)
        )
        self.assertTrue(created)
        self.assertIsNotNone(delivery.id)
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertTrue(delivery.message_id.endswith("@backstagepro.mail>"))
        self.assertEqual(delivery.related_object_id, str(self.band.id))

    def test_enqueue_email_idempotency(self):
        d1, c1 = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="teste@dominio.com",
            subject="Assunto Teste 1",
            idempotency_key="idemp-unique-123",
            template_name="emails/system_test",
            context_data={"test": "data1"}
        )
        d2, c2 = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="outro@dominio.com",
            subject="Assunto Teste 2",
            idempotency_key="idemp-unique-123",
            template_name="emails/system_test",
            context_data={"test": "data2"}
        )
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(d1.id, d2.id)
        self.assertEqual(EmailDelivery.objects.filter(idempotency_key="idemp-unique-123").count(), 1)

    def test_render_and_send_email_delivery_locmem(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="cliente@teste.com",
            subject="Email de Teste do Sistema",
            idempotency_key="test-locmem-01",
            template_name="emails/system_test",
            context_data={
                "user_name": "Cliente Teste",
                "environment_name": "Homologação",
                "triggered_by": "Automated Test",
                "delivery_id": "999",
                "generated_at": timezone.now().strftime("%d/%m/%Y %H:%M:%S")
            }
        )
        success, err_code, err_msg = render_and_send_email_delivery(delivery)
        self.assertTrue(success)
        self.assertIsNone(err_code)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["cliente@teste.com"])
        self.assertIn("Email de Teste do Sistema", sent_email.subject)
        self.assertIn("Backstage Pro", sent_email.body)

    def test_run_email_worker_command_once(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="worker_test@dominio.com",
            subject="Worker Execution Test",
            idempotency_key="worker-once-test-01",
            template_name="emails/system_test",
            context_data={"user_name": "Worker Test", "environment_name": "Homologação"}
        )
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)

        call_command('run_email_worker', once=True, batch_size=10)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_worker_retry_on_smtp_failure(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="fail@dominio.com",
            subject="Fail Test",
            idempotency_key="fail-test-01",
            template_name="emails/system_test",
            context_data={"user_name": "Fail"}
        )

        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception("SMTP Connection Timeout")):
            call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.RETRY)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIn("SMTP Connection Timeout", delivery.last_error_message)
        self.assertIsNotNone(delivery.next_attempt_at)

    def test_worker_max_attempts_exhausted(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="exhaust@dominio.com",
            subject="Exhaust Test",
            idempotency_key="exhaust-test-01",
            template_name="emails/system_test",
            context_data={"user_name": "Exhaust"}
        )
        delivery.attempt_count = 5
        delivery.max_attempts = 6
        delivery.save()

        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception("Permanent SMTP Error")):
            call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.FAILED)
        self.assertEqual(delivery.attempt_count, 6)
        self.assertIn("MAX_ATTEMPTS_EXCEEDED", delivery.last_error_message)

    def test_stale_processing_recovery(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="stale@dominio.com",
            subject="Stale Test",
            idempotency_key="stale-test-01",
            template_name="emails/system_test",
            context_data={"user_name": "Stale"}
        )
        delivery.status = EmailDelivery.Status.PROCESSING
        delivery.sending_started_at = timezone.now() - datetime.timedelta(minutes=20)
        delivery.save()

        call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        # Stale recovery reclassifies to RETRY with next_attempt in +1 min
        self.assertEqual(delivery.status, EmailDelivery.Status.RETRY)
        self.assertIn("STALE_PROCESSING_RECOVERED", delivery.last_error_message)

    def test_annual_renewal_notice_workflow_integration(self):
        notice = AnnualRenewalNotice.objects.create(
            band_subscription=self.subscription,
            renewal_date=datetime.date(2027, 9, 4),
            scheduled_for=datetime.date(2027, 8, 5),
            plan_name="Avançado",
            billing_cycle="ANUAL",
            current_contracted_value=Decimal("499.90"),
            notified_renewal_price=Decimal("499.90"),
            installment_count=5,
            notice_type=AnnualRenewalNotice.NoticeType.STANDARD,
            status=AnnualRenewalNotice.Status.PENDING
        )
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.ANNUAL_RENEWAL_NOTICE,
            recipient_email=self.subscription.billing_email,
            subject="Aviso de Renovação Anual",
            idempotency_key=f"notice-test-{notice.id}",
            template_name="emails/annual_renewal_notice",
            context_data={
                "user_name": self.subscription.financial_responsible_name,
                "band_name": self.band.name,
                "plan_name": self.subscription.plan_name,
                "renewal_date": "04/09/2027",
                "current_price": "499.90",
                "renewal_price": "499.90",
                "installment_count": 5,
                "installment_amount": "99.98",
                "is_price_changed": False,
                "auto_renew": True,
            },
            related_object_type="AnnualRenewalNotice",
            related_object_id=str(notice.id)
        )

        call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(notice.status, AnnualRenewalNotice.Status.SENT)
        self.assertIsNotNone(notice.sent_at)

    def test_activation_token_security_and_fernet_roundtrip(self):
        from core.services.payments.activation import create_band_activation_token
        from core.services.payments.security import decrypt_activation_token

        activation, raw_token = create_band_activation_token(
            band=self.band,
            email="produtor_novo@teste.com",
            responsible_name="Novo Produtor",
            valid_hours=48
        )

        # 1. Plaintext token is not on model
        self.assertFalse(hasattr(activation, 'token_plain'))
        self.assertFalse(hasattr(activation, 'raw_token'))
        self.assertEqual(len(activation.token_hash), 64)

        # 2. Encrypted token is persisted and is not plaintext
        self.assertIsNotNone(activation.encrypted_token)
        self.assertNotEqual(activation.encrypted_token, raw_token)
        self.assertNotIn(raw_token, activation.encrypted_token)

        # 3. Round-trip decrypt in memory works
        decrypted = decrypt_activation_token(activation.encrypted_token)
        self.assertEqual(decrypted, raw_token)

        # 4. TTL is 48 hours
        delta = activation.expires_at - activation.created_at
        self.assertAlmostEqual(delta.total_seconds(), 48 * 3600, delta=10)

    def test_account_activation_email_worker_dynamic_assembly_and_context_security(self):
        from core.services.payments.activation import create_band_activation_token

        activation, raw_token = create_band_activation_token(
            band=self.band,
            email="produtor_novo@teste.com",
            responsible_name="Novo Produtor",
            valid_hours=48
        )

        # Enqueue without raw token or activation_url in context_data
        delivery, created = enqueue_email(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email="produtor_novo@teste.com",
            subject="Sua conta no Backstage Pro está pronta!",
            idempotency_key=f"activation-test-{activation.id}",
            template_name="emails/account_activation",
            context_data={
                "responsible_name": "Novo Produtor",
                "band_name": self.band.name,
                "plan_name": "Avançado",
                "billing_cycle": "Anual",
                "amount": "499.90",
            },
            related_object_type="BandActivationToken",
            related_object_id=str(activation.id)
        )
        self.assertTrue(created)

        # Confirm context_data has NO secrets or tokens
        self.assertNotIn('token', delivery.context_data)
        self.assertNotIn('activation_token', delivery.context_data)
        self.assertNotIn('activation_url', delivery.context_data)
        self.assertNotIn('_raw_activation_token', delivery.context_data)

        # Execute worker
        call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

        sent_msg = mail.outbox[0]
        self.assertEqual(sent_msg.to, ["produtor_novo@teste.com"])

        # Verify rendered HTML contains https domain and route with raw_token, NOT hash
        self.assertIn(f"/ativar-conta/{raw_token}/", sent_msg.body or sent_msg.alternatives[0][0])
        self.assertNotIn(activation.token_hash, sent_msg.body or sent_msg.alternatives[0][0])
        self.assertIn("https://", sent_msg.body or sent_msg.alternatives[0][0])
        self.assertNotIn("localhost", sent_msg.body or sent_msg.alternatives[0][0])

        # Confirm DB context_data is still free of secrets
        self.assertNotIn('activation_url', delivery.context_data)

    def test_account_activation_used_token_fails_gracefully(self):
        from core.services.payments.activation import create_band_activation_token

        activation, raw_token = create_band_activation_token(
            band=self.band,
            email="produtor_used@teste.com",
            responsible_name="Produtor Used",
            valid_hours=48
        )
        activation.used_at = timezone.now()
        activation.save()

        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email="produtor_used@teste.com",
            subject="Conta Pronta",
            idempotency_key=f"activation-used-{activation.id}",
            template_name="emails/account_activation",
            context_data={"responsible_name": "Produtor Used"},
            related_object_type="BandActivationToken",
            related_object_id=str(activation.id)
        )

        call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.FAILED)
        self.assertEqual(delivery.last_error_code, 'ACTIVATION_TOKEN_ALREADY_USED')
        self.assertEqual(len(mail.outbox), 0)

    def test_account_activation_expired_token_fails_gracefully(self):
        from core.services.payments.activation import create_band_activation_token

        activation, raw_token = create_band_activation_token(
            band=self.band,
            email="produtor_exp@teste.com",
            responsible_name="Produtor Expired",
            valid_hours=48
        )
        activation.expires_at = timezone.now() - datetime.timedelta(hours=1)
        activation.save()

        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email="produtor_exp@teste.com",
            subject="Conta Pronta",
            idempotency_key=f"activation-exp-{activation.id}",
            template_name="emails/account_activation",
            context_data={"responsible_name": "Produtor Expired"},
            related_object_type="BandActivationToken",
            related_object_id=str(activation.id)
        )

        call_command('run_email_worker', once=True)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.FAILED)
        self.assertEqual(delivery.last_error_code, 'ACTIVATION_TOKEN_EXPIRED')
        self.assertEqual(len(mail.outbox), 0)


    def test_payment_overdue_webhook_enqueues_email(self):
        from core.models import BillingRecord
        from core.services.payments.asaas.webhooks import handle_asaas_webhook_payload

        # Pre-create BillingRecord
        record = BillingRecord.objects.create(
            subscription=self.subscription,
            band=self.band,
            reference_period="09/2026",
            plan_name="Avançado",
            billing_cycle="ANUAL",
            amount=Decimal("499.90"),
            due_date=datetime.date(2026, 9, 4),
            status="PENDENTE",
            gateway_provider="ASAAS",
            gateway_payment_id="pay_overdue_test_123"
        )

        payload = {
            "id": "evt_overdue_001",
            "event": "PAYMENT_OVERDUE",
            "payment": {
                "id": "pay_overdue_test_123",
                "customer": "cus_test_123",
                "value": 499.90,
                "dueDate": "2026-09-04",
                "invoiceUrl": "https://sandbox.asaas.com/i/test-overdue"
            }
        }

        success, msg = handle_asaas_webhook_payload(payload)
        self.assertTrue(success)

        # Verify email delivery was enqueued
        delivery = EmailDelivery.objects.filter(
            email_type=EmailDelivery.EmailType.PAYMENT_OVERDUE,
            idempotency_key="overdue-payment-pay_overdue_test_123"
        ).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.recipient_email, "financeiro@teste.com")
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)

        # Contrato de contexto pt-BR e saudação (CASO D):
        self.assertEqual(delivery.context_data.get("responsible_name"), "Carlos Financeiro")
        self.assertEqual(delivery.context_data.get("user_name"), "Carlos Financeiro")
        self.assertEqual(delivery.context_data.get("amount"), "499,90")
        self.assertNotEqual(delivery.context_data.get("amount"), "499.90")
        self.assertNotEqual(delivery.context_data.get("amount"), "R$ 499,90")
        self.assertNotIn("R$", delivery.context_data.get("amount"))
        self.assertEqual(delivery.context_data.get("grace_until"), "08/09/2026")

        # Execute worker
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)

        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        html_content = sent_msg.alternatives[0][0] if sent_msg.alternatives else sent_msg.body
        self.assertIn("Olá, <strong>Carlos Financeiro</strong>!", html_content)
        self.assertIn("Valor pendente:</strong> R$ 499,90", html_content)
        self.assertIn("Acesso mantido até:</strong> 08/09/2026", html_content)
        self.assertNotIn("R$ R$", html_content)
        self.assertNotIn("R$ 499.90", html_content)

        # Plain text
        self.assertIn("Olá, Carlos Financeiro!", sent_msg.body)
        self.assertIn("Valor pendente: R$ 499,90", sent_msg.body)
        self.assertIn("Acesso mantido até: 08/09/2026", sent_msg.body)
        self.assertNotIn("R$ R$", sent_msg.body)
        self.assertNotIn("R$ 499.90", sent_msg.body)

    def test_payment_credit_card_capture_refused_webhook_enqueues_email(self):
        from core.models import BillingRecord
        from core.services.payments.asaas.webhooks import handle_asaas_webhook_payload

        record = BillingRecord.objects.create(
            subscription=self.subscription,
            band=self.band,
            reference_period="09/2026",
            plan_name="Avançado",
            billing_cycle="ANUAL",
            amount=Decimal("499.90"),
            due_date=datetime.date(2026, 9, 4),
            status="PENDENTE",
            gateway_provider="ASAAS",
            gateway_payment_id="pay_refused_test_456"
        )

        payload = {
            "id": "evt_refused_001",
            "event": "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED",
            "payment": {
                "id": "pay_refused_test_456",
                "customer": "cus_test_123",
                "value": 499.90,
                "dueDate": "2026-09-04",
                "refusalReason": "Cartão bloqueado para compras online",
                "invoiceUrl": "https://sandbox.asaas.com/i/test-refused"
            }
        }

        success, msg = handle_asaas_webhook_payload(payload)
        self.assertTrue(success)

        delivery = EmailDelivery.objects.filter(
            email_type=EmailDelivery.EmailType.CREDIT_CARD_CAPTURE_REFUSED,
            idempotency_key="cc-refused-webhook-pay_refused_test_456"
        ).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.recipient_email, "financeiro@teste.com")

        # Execute worker
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)

    def test_subscription_suspended_due_dates_enqueues_email(self):
        # Set next_due_date to 6 days ago (suspension threshold >= 5 days)
        today = timezone.localdate()
        self.subscription.next_due_date = today - datetime.timedelta(days=6)
        self.subscription.save()

        self.assertTrue(self.subscription.is_financially_suspended)

        call_command('check_subscription_due_dates')

        idemp_k = f"sub-suspended-{self.subscription.id}-{self.subscription.next_due_date.isoformat()}"
        delivery = EmailDelivery.objects.filter(
            email_type=EmailDelivery.EmailType.SUBSCRIPTION_SUSPENDED,
            idempotency_key=idemp_k
        ).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.recipient_email, "financeiro@teste.com")

        # CASO D: Contrato do context_data no comando real
        self.assertEqual(delivery.context_data.get("responsible_name"), "Carlos Financeiro")
        self.assertEqual(delivery.context_data.get("user_name"), "Carlos Financeiro")
        self.assertEqual(delivery.context_data.get("band_name"), self.band.name)

        # Execute worker
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)

        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        html_content = sent_msg.alternatives[0][0] if sent_msg.alternatives else sent_msg.body
        self.assertIn("Olá, <strong>Carlos Financeiro</strong>!", html_content)
        self.assertIn("Acesso temporariamente suspenso", html_content)
        self.assertIn("Dados preservados:</strong> Seus dados e informações permanecem seguros e intactos.", html_content)

        self.assertIn("Olá, Carlos Financeiro!", sent_msg.body)
        self.assertIn("Acesso temporariamente suspenso", sent_msg.body)
        self.assertIn("Seus dados e informações permanecem seguros e intactos. O acesso será restabelecido automaticamente assim que o pagamento for confirmado.", sent_msg.body)
        self.assertIn("Regularize em:", sent_msg.body)

    def test_resolve_subscription_recipient_hierarchy(self):
        # 1. Billing email
        email, name = resolve_subscription_recipient(self.subscription)
        self.assertEqual(email, "financeiro@teste.com")
        self.assertEqual(name, "Carlos Financeiro")

        # 2. Fallback to Produtor user
        self.subscription.billing_email = ""
        self.subscription.financial_responsible_name = ""
        self.subscription.save()

        email2, name2 = resolve_subscription_recipient(self.subscription)
        self.assertEqual(email2, "produtor@teste.com")
        self.assertEqual(name2, "Carlos Silva")


class ResendTransportTestCase(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Resend Teste",
            slug="banda-resend-teste",
            plan_type=Band.PlanType.AVANCADO,
        )

    @override_settings(
        EMAIL_PROVIDER='resend',
        RESEND_API_KEY=None,
        RESEND_FROM_EMAIL='Backstage Pro <nao-responda@backstagepro.site>'
    )
    def test_resend_api_key_missing_fails_controlled(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="teste@dominio.com",
            subject="Teste Sem API Key",
            idempotency_key="resend-no-key-01",
            template_name="emails/system_test",
            context_data={"user_name": "Testador", "environment_name": "Homologação"}
        )
        with patch('resend.Emails.send') as mock_send:
            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self.assertFalse(success)
            self.assertEqual(err_code, 'RESEND_API_KEY_MISSING')
            mock_send.assert_not_called()

    @override_settings(
        EMAIL_PROVIDER='resend',
        RESEND_API_KEY='re_test_mock_key_123',
        RESEND_FROM_EMAIL=None
    )
    def test_resend_from_email_missing_fails_controlled(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="teste@dominio.com",
            subject="Teste Sem From",
            idempotency_key="resend-no-from-01",
            template_name="emails/system_test",
            context_data={"user_name": "Testador", "environment_name": "Homologação"}
        )
        with patch('resend.Emails.send') as mock_send:
            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self.assertFalse(success)
            self.assertEqual(err_code, 'RESEND_FROM_EMAIL_MISSING')
            mock_send.assert_not_called()

    @override_settings(
        EMAIL_PROVIDER='resend',
        RESEND_API_KEY='re_test_mock_key_123',
        RESEND_FROM_EMAIL='Backstage Pro <nao-responda@backstagepro.site>',
        RESEND_REPLY_TO_EMAIL='contato@backstagepro.site'
    )
    def test_resend_success_payload_and_idempotency_key(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="destinatario@externo.com",
            subject="Assunto Resend Teste",
            idempotency_key="resend-success-key-001",
            template_name="emails/system_test",
            context_data={"user_name": "Carlos", "environment_name": "Produção"}
        )

        with patch('resend.Emails.send', return_value={'id': 're_msg_mock_998877'}) as mock_send:
            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self.assertTrue(success)
            self.assertIsNone(err_code)
            self.assertIsNone(err_msg)

            mock_send.assert_called_once()
            called_params, called_kwargs = mock_send.call_args

            params = called_params[0]
            self.assertEqual(params['from'], 'Backstage Pro <nao-responda@backstagepro.site>')
            self.assertEqual(params['to'], ['destinatario@externo.com'])
            self.assertEqual(params['subject'], 'Assunto Resend Teste')
            self.assertEqual(params['reply_to'], 'contato@backstagepro.site')
            self.assertIn('html', params)
            self.assertIn('text', params)

            # Validar options / idempotency_key
            options = called_kwargs.get('options')
            self.assertIsNotNone(options)
            self.assertEqual(options.get('idempotency_key'), 'resend-success-key-001')

    @override_settings(
        EMAIL_PROVIDER='resend',
        RESEND_API_KEY='re_test_mock_key_123',
        RESEND_FROM_EMAIL='Backstage Pro <nao-responda@backstagepro.site>'
    )
    def test_resend_api_exception_handled_safely(self):
        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.SYSTEM_TEST,
            recipient_email="destinatario@externo.com",
            subject="Assunto Resend Erro",
            idempotency_key="resend-error-key-001",
            template_name="emails/system_test",
            context_data={"user_name": "Carlos", "environment_name": "Produção"}
        )

        with patch('resend.Emails.send', side_effect=Exception("Resend 429: Rate limit exceeded")):
            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self.assertFalse(success)
            self.assertEqual(err_code, 'Exception')
            self.assertIn("Rate limit exceeded", err_msg)
            # Garantir que a API Key não vazou na mensagem de erro
            self.assertNotIn("re_test_mock_key_123", err_msg)

    @override_settings(
        EMAIL_PROVIDER='resend',
        RESEND_API_KEY='re_test_mock_key_123',
        RESEND_FROM_EMAIL='Backstage Pro <nao-responda@backstagepro.site>'
    )
    def test_account_activation_in_memory_url_with_resend(self):
        from core.services.payments.security import encrypt_activation_token
        enc_tok = encrypt_activation_token("test-resend-raw-token-12345")
        activation = BandActivationToken.objects.create(
            band=self.band,
            email="produtor_resend@teste.com",
            responsible_name="Produtor Resend",
            token_hash="hash_mock_resend_01",
            encrypted_token=enc_tok,
            expires_at=timezone.now() + datetime.timedelta(hours=48)
        )

        delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email=activation.email,
            subject="Ative sua Conta — Backstage Pro",
            idempotency_key="resend-activation-key-01",
            related_object_type="BandActivationToken",
            related_object_id=str(activation.id)
        )

        with patch('resend.Emails.send', return_value={'id': 're_act_mock_112233'}) as mock_send:
            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self.assertTrue(success)
            called_params = mock_send.call_args[0][0]
            self.assertIn("/ativar-conta/test-resend-raw-token-12345/", called_params['html'])
            self.assertIn("/ativar-conta/test-resend-raw-token-12345/", called_params['text'])

    def test_system_test_template_renders_environment_dynamically(self):
        from django.template.loader import render_to_string
        # 1. Environment 'Production'
        ctx_prod = {"user_name": "Carlos", "environment_name": "Production"}
        html_p = render_to_string("emails/system_test.html", ctx_prod)
        txt_p = render_to_string("emails/system_test.txt", ctx_prod)
        self.assertIn("Ambiente:</strong> Production", html_p)
        self.assertIn("Ambiente: Production", txt_p)
        self.assertNotIn("Homologação", html_p)
        self.assertNotIn("Homologação", txt_p)

        # 2. Environment 'Homologação'
        ctx_homo = {"user_name": "Carlos", "environment_name": "Homologação"}
        html_h = render_to_string("emails/system_test.html", ctx_homo)
        txt_h = render_to_string("emails/system_test.txt", ctx_homo)
        self.assertIn("Ambiente:</strong> Homologação", html_h)
        self.assertIn("Ambiente: Homologação", txt_h)

        # 3. Fallback neutro 'Sistema' quando environment_name omitido
        ctx_fallback = {"user_name": "Carlos"}
        html_f = render_to_string("emails/system_test.html", ctx_fallback)
        txt_f = render_to_string("emails/system_test.txt", ctx_fallback)
        self.assertIn("Ambiente:</strong> Sistema", html_f)
        self.assertIn("Ambiente: Sistema", txt_f)

    def test_account_activation_real_flow_amount_formatting(self):
        """
        Garante que o provisionamento real de ACCOUNT_ACTIVATION enfileira amount formatado
        com vírgula brasileira ('49,90'), sem prefixo 'R$' e sem ponto decimal ('49.90').
        E confirma que os templates HTML e TXT renderizam exatamente 'R$ 49,90'.
        """
        from core.models import SignupOrder
        from core.services.payments.provisioning import process_checkout_paid_event
        from django.template.loader import render_to_string

        order = SignupOrder.objects.create(
            external_reference="order-fmt-test-01",
            gateway_checkout_id="checkout-fmt-01",
            band_name="Banda Formato Real",
            responsible_name="Produtor Formato",
            email="formato@teste.com",
            plan_type="AVANCADO",
            billing_cycle="MENSAL",
            amount=Decimal("49.90"),
            status="PENDENTE"
        )

        payload = {
            "checkout": {
                "id": "checkout-fmt-01",
                "externalReference": "order-fmt-test-01",
                "status": "PAID"
            }
        }

        success, msg, band = process_checkout_paid_event(payload)
        self.assertTrue(success)

        delivery = EmailDelivery.objects.filter(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email="formato@teste.com"
        ).first()
        self.assertIsNotNone(delivery)

        # 1. Contrato estrito no context_data:
        self.assertEqual(delivery.context_data.get("amount"), "49,90")
        self.assertNotEqual(delivery.context_data.get("amount"), "49.90")
        self.assertNotEqual(delivery.context_data.get("amount"), "R$ 49,90")
        self.assertNotIn("R$", delivery.context_data.get("amount"))

        # 2. Renderização final nos templates:
        rendered_html = render_to_string("emails/account_activation.html", delivery.context_data)
        rendered_txt = render_to_string("emails/account_activation.txt", delivery.context_data)

        self.assertIn("Valor:</strong> R$ 49,90", rendered_html)
        self.assertNotIn("R$ R$", rendered_html)
        self.assertNotIn("R$ 49.90", rendered_html)

        self.assertIn("Valor: R$ 49,90", rendered_txt)
        self.assertNotIn("R$ R$", rendered_txt)
        self.assertNotIn("R$ 49.90", rendered_txt)

    def test_payment_overdue_greeting_fallback_and_context_contract(self):
        """
        Valida que o template payment_overdue possui fallback seguro para a saudação
        (responsible_name -> band_name -> 'Cliente') sem falhar caso chaves estejam ausentes,
        e garante que o webhook real fornece tanto responsible_name quanto user_name.
        """
        from django.template.loader import render_to_string

        # CASO A: responsible_name presente
        ctx_a = {
            'responsible_name': 'Vinicius',
            'band_name': 'Banda Teste',
            'plan_name': 'Avançado',
            'amount': '49,90',
            'grace_until': '10/09/2026',
        }
        html_a = render_to_string("emails/payment_overdue.html", ctx_a)
        txt_a = render_to_string("emails/payment_overdue.txt", ctx_a)
        self.assertIn("Olá, <strong>Vinicius</strong>!", html_a)
        self.assertIn("Olá, Vinicius!", txt_a)

        # CASO B: responsible_name ausente, band_name presente
        ctx_b = {
            'band_name': 'Banda Teste',
            'plan_name': 'Avançado',
            'amount': '49,90',
            'grace_until': '10/09/2026',
        }
        html_b = render_to_string("emails/payment_overdue.html", ctx_b)
        txt_b = render_to_string("emails/payment_overdue.txt", ctx_b)
        self.assertIn("Olá, <strong>Banda Teste</strong>!", html_b)
        self.assertIn("Olá, Banda Teste!", txt_b)

        # CASO C: responsible_name e band_name ambos ausentes
        ctx_c = {
            'plan_name': 'Avançado',
            'amount': '49,90',
            'grace_until': '10/09/2026',
        }
        html_c = render_to_string("emails/payment_overdue.html", ctx_c)
        txt_c = render_to_string("emails/payment_overdue.txt", ctx_c)
        self.assertIn("Olá, <strong>Cliente</strong>!", html_c)
        self.assertIn("Olá, Cliente!", txt_c)

    def test_subscription_suspended_greeting_fallback_scenarios(self):
        """
        Valida que o template subscription_suspended possui fallback seguro para a saudação
        (responsible_name -> band_name -> 'Cliente') sem falhar caso chaves estejam ausentes.
        """
        from django.template.loader import render_to_string

        # CASO A: responsible_name presente
        ctx_a = {
            'responsible_name': 'Vinicius',
            'band_name': 'Banda Teste',
        }
        html_a = render_to_string("emails/subscription_suspended.html", ctx_a)
        txt_a = render_to_string("emails/subscription_suspended.txt", ctx_a)
        self.assertIn("Olá, <strong>Vinicius</strong>!", html_a)
        self.assertIn("Olá, Vinicius!", txt_a)

        # CASO B: responsible_name ausente, band_name presente
        ctx_b = {
            'band_name': 'Banda Teste',
        }
        html_b = render_to_string("emails/subscription_suspended.html", ctx_b)
        txt_b = render_to_string("emails/subscription_suspended.txt", ctx_b)
        self.assertIn("Olá, <strong>Banda Teste</strong>!", html_b)
        self.assertIn("Olá, Banda Teste!", txt_b)

        # CASO C: responsible_name e band_name ambos ausentes
        ctx_c = {}
        html_c = render_to_string("emails/subscription_suspended.html", ctx_c)
        txt_c = render_to_string("emails/subscription_suspended.txt", ctx_c)
        self.assertIn("Olá, <strong>Cliente</strong>!", html_c)
        self.assertIn("Olá, Cliente!", txt_c)







