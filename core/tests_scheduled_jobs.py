import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core import mail
from django.core.management import call_command
from django.db import connection

from core.models import (
    Band,
    User,
    BandSubscription,
    AnnualPlanPurchase,
    AnnualRenewalNotice,
    EmailDelivery,
    ScheduledJobRun,
    SystemSettings,
)
from core.services.payments.base import (
    get_business_date,
    acquire_job_advisory_lock,
    ANNUAL_NOTICE_JOB_LOCK_ID,
    ANNUAL_RENEWAL_JOB_LOCK_ID,
)
from core.services.payments.security import (
    encrypt_payment_token,
    decrypt_payment_token,
    encrypt_activation_token,
    decrypt_activation_token,
)


class ScheduledJobsTestCase(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Cron Teste",
            slug="banda-cron-teste",
            plan_type=Band.PlanType.AVANCADO,
        )
        self.user = User.objects.create_user(
            username="produtor_cron",
            email="produtor_cron@teste.com",
            first_name="Carlos",
            last_name="Produtor",
            role="PRODUTOR",
            band=self.band
        )
        self.subscription = BandSubscription.objects.create(
            band=self.band,
            plan_name="Profissional",
            billing_cycle="ANUAL",
            contracted_value=Decimal("499.90"),
            start_date=datetime.date(2026, 9, 4),
            next_due_date=datetime.date(2027, 9, 4),
            status="ATIVO",
            auto_renew=True,
            billing_email="financeiro@bandacron.com",
            financial_responsible_name="Carlos Financeiro"
        )
        self.purchase = AnnualPlanPurchase.objects.create(
            band_subscription=self.subscription,
            purchase_type=AnnualPlanPurchase.PurchaseType.INITIAL,
            gross_amount=Decimal("499.90"),
            net_amount=Decimal("485.00"),
            installment_count=5,
            coverage_start=datetime.date(2026, 9, 4),
            coverage_end=datetime.date(2027, 9, 4),
            status=AnnualPlanPurchase.Status.CONFIRMED
        )

    def test_business_date_helper(self):
        b_date = get_business_date()
        self.assertEqual(b_date, timezone.localdate())

    def test_dedicated_encryption_keys_independence(self):
        # 1. Payment token round-trip
        pay_token = "tok_credit_card_12345"
        enc_pay = encrypt_payment_token(pay_token)
        dec_pay = decrypt_payment_token(enc_pay)
        self.assertEqual(dec_pay, pay_token)

        # 2. Activation token round-trip
        act_token = "sec_activation_random_token_999"
        enc_act = encrypt_activation_token(act_token)
        dec_act = decrypt_activation_token(enc_act)
        self.assertEqual(dec_act, act_token)

    def test_notice_cron_d30_exact_enqueues_email_and_audits_job(self):
        # D-30 reference date: 2027-08-05 for renewal_date 2027-09-04
        ref_date = "2027-08-05"

        call_command('process_annual_renewal_notices', date=ref_date)

        # 1. Notice created in DB
        notice = AnnualRenewalNotice.objects.filter(
            band_subscription=self.subscription,
            renewal_date=datetime.date(2027, 9, 4)
        ).first()
        self.assertIsNotNone(notice)
        self.assertEqual(notice.status, AnnualRenewalNotice.Status.PENDING)
        self.assertEqual(notice.installment_count, 5)

        # 2. Email delivery enqueued
        delivery = EmailDelivery.objects.filter(
            email_type=EmailDelivery.EmailType.ANNUAL_RENEWAL_NOTICE,
            related_object_id=str(notice.id)
        ).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.recipient_email, "financeiro@bandacron.com")
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)

        # 3. ScheduledJobRun audit recorded
        job_run = ScheduledJobRun.objects.filter(job_name='process_annual_renewal_notices').first()
        self.assertIsNotNone(job_run)
        self.assertEqual(job_run.status, ScheduledJobRun.Status.SUCCESS)
        self.assertEqual(job_run.success_count, 1)
        self.assertEqual(job_run.failed_count, 0)

        # 4. Email worker sends async
        call_command('run_email_worker', once=True)
        delivery.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(notice.status, AnnualRenewalNotice.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_notice_cron_recovery_window_late_notice_blocks_price_increase(self):
        # Current contracted price is 499.90. Set system public price to 599.90 (an increase).
        with patch.object(SystemSettings, 'get_canonical_plan_price', return_value=Decimal('599.90')):
            # Case 1: Exactly D-30 allows notifying public price increase
            call_command('process_annual_renewal_notices', date="2027-08-05")
            notice_d30 = AnnualRenewalNotice.objects.get(
                band_subscription=self.subscription,
                renewal_date=datetime.date(2027, 9, 4)
            )
            self.assertEqual(notice_d30.notified_renewal_price, Decimal('599.90'))
            self.assertEqual(notice_d30.notice_type, AnnualRenewalNotice.NoticeType.PRICE_CHANGE)

            # Reset notice for recovery test
            notice_d30.delete()
            EmailDelivery.objects.all().delete()

            # Case 2: Recovery at D-28 (missed D-30, diff_days=28)
            # Commercial rule: Price increase CANNOT be authorized when notice is < 30 days!
            call_command('process_annual_renewal_notices', date="2027-08-07")
            notice_d28 = AnnualRenewalNotice.objects.get(
                band_subscription=self.subscription,
                renewal_date=datetime.date(2027, 9, 4)
            )
            # Notified price MUST remain contracted price (499.90), NOT increased (599.90)
            self.assertEqual(notice_d28.notified_renewal_price, Decimal('499.90'))
            self.assertEqual(notice_d28.notice_type, AnnualRenewalNotice.NoticeType.STANDARD)

    def test_notice_cron_outside_window_skipped(self):
        # D-35 (diff_days=35) -> out of window
        call_command('process_annual_renewal_notices', date="2027-07-31")
        self.assertEqual(AnnualRenewalNotice.objects.count(), 0)

        # D-20 (diff_days=20) -> out of recovery window (cutoff is D-25)
        call_command('process_annual_renewal_notices', date="2027-08-15")
        self.assertEqual(AnnualRenewalNotice.objects.count(), 0)

    def test_notice_cron_idempotent_no_duplicate(self):
        call_command('process_annual_renewal_notices', date="2027-08-05")
        self.assertEqual(AnnualRenewalNotice.objects.count(), 1)
        self.assertEqual(EmailDelivery.objects.count(), 1)

        # Run again
        call_command('process_annual_renewal_notices', date="2027-08-05")
        self.assertEqual(AnnualRenewalNotice.objects.count(), 1)
        self.assertEqual(EmailDelivery.objects.count(), 1)

    def test_renewal_cron_d0_dry_run_and_scheduled_job_run(self):
        # On D0 (2027-09-04), subscription is eligible for renewal
        call_command('process_annual_renewals', date="2027-09-04", dry_run=True)

        job_run = ScheduledJobRun.objects.filter(job_name='process_annual_renewals').first()
        # In dry run, job_run is None or skipped from persistence
        self.assertIsNone(job_run)

        # Run without dry-run with mock to verify execution flow
        with patch('core.services.payments.renewal.AnnualRenewalService.process_subscription_renewal') as mock_proc:
            mock_proc.return_value = (True, "OK", self.purchase)
            call_command('process_annual_renewals', date="2027-09-04")
            mock_proc.assert_called_once()

        job_run_real = ScheduledJobRun.objects.filter(job_name='process_annual_renewals').first()
        self.assertIsNotNone(job_run_real)
        self.assertEqual(job_run_real.status, ScheduledJobRun.Status.SUCCESS)
        self.assertEqual(job_run_real.success_count, 1)

    def test_renewal_cron_eligibility_window_d0_to_d4_and_d5_stop(self):
        from core.services.payments.renewal import AnnualRenewalService
        service = AnnualRenewalService()

        # Before due date (D-1): Not eligible
        e_before, _ = service.is_eligible_for_renewal(self.subscription, target_date=datetime.date(2027, 9, 3))
        self.assertFalse(e_before)

        # D0 (due date): Eligible
        e_d0, _ = service.is_eligible_for_renewal(self.subscription, target_date=datetime.date(2027, 9, 4))
        self.assertTrue(e_d0)

        # D+1 to D+4: Eligible
        e_d1, _ = service.is_eligible_for_renewal(self.subscription, target_date=datetime.date(2027, 9, 5))
        self.assertTrue(e_d1)
        e_d4, _ = service.is_eligible_for_renewal(self.subscription, target_date=datetime.date(2027, 9, 8))
        self.assertTrue(e_d4)

        # D+5: Window expired, financial suspension takes over
        e_d5, reason_d5 = service.is_eligible_for_renewal(self.subscription, target_date=datetime.date(2027, 9, 9))
        self.assertFalse(e_d5)
        self.assertIn("JANELA_EXPIRADA_SUSPENSAO_FINANCEIRA", reason_d5)

    def test_advisory_lock_concurrent_execution_skipped(self):
        import contextlib

        @contextlib.contextmanager
        def mock_lock_failure(lock_id):
            yield False

        with patch('core.management.commands.process_annual_renewal_notices.acquire_job_advisory_lock', side_effect=mock_lock_failure):
            call_command('process_annual_renewal_notices', date="2027-08-05")

            # Check that job was recorded as SKIPPED_LOCKED
            job_run = ScheduledJobRun.objects.filter(
                job_name='process_annual_renewal_notices',
                status=ScheduledJobRun.Status.SKIPPED_LOCKED
            ).first()
            self.assertIsNotNone(job_run)
            self.assertEqual(AnnualRenewalNotice.objects.count(), 0)

    @override_settings(DJANGO_ENV='staging', IS_RUNNING_TESTS=False)
    def test_sqlite_hard_block_in_staging_environment(self):
        if connection.vendor == 'sqlite':
            # In staging environment, running with SQLite must be aborted
            call_command('process_annual_renewal_notices')
            self.assertEqual(ScheduledJobRun.objects.count(), 0)

