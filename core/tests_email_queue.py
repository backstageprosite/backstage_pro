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

    def test_activation_token_security_no_plaintext_saved(self):
        import hashlib, secrets
        plain_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
        token_obj = BandActivationToken.objects.create(
            band=self.band,
            email="produtor_novo@teste.com",
            responsible_name="Novo Produtor",
            token_hash=token_hash,
            expires_at=timezone.now() + datetime.timedelta(hours=72)
        )
        act_delivery, _ = enqueue_email(
            email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION,
            recipient_email="produtor_novo@teste.com",
            subject="Ative sua Conta",
            idempotency_key=f"activation-{token_obj.id}",
            template_name="emails/account_activation",
            context_data={
                "user_name": "Novo Produtor",
                "band_name": self.band.name,
                "plan_name": "Avançado",
                "activation_url": f"https://app.backstagepro.site/ativar-conta/?token={plain_token}",
                "expires_hours": 72,
            },
            related_object_type="BandActivationToken",
            related_object_id=str(token_obj.id)
        )
        self.assertEqual(act_delivery.related_object_id, str(token_obj.id))
        self.assertFalse(hasattr(token_obj, 'token_plain'))
        self.assertTrue(len(token_obj.token_hash) == 64)

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

        # Execute worker
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)

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

        # Execute worker
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)

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

