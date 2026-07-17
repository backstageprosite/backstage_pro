import datetime
from unittest.mock import patch, call
from django.test import TransactionTestCase, TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
import json
from io import StringIO

from core.models import Band, Notification, WebPushSubscription, WebPushDelivery, User
from core.services.web_push_operations import find_retryable_web_push_deliveries, retry_web_push_deliveries

class WebPushRetryOperationsTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        self.band2 = Band.objects.create(name="Outra Banda", slug="outra-banda")
        
        self.sub = WebPushSubscription.objects.create(
            user=self.user,
            band=self.band,
            endpoint="https://example.com/push/1",
            p256dh="p256dh",
            auth="auth",
            service_worker_scope="/banda-teste/",
            is_active=True
        )
        
        self.notification = Notification.objects.create(
            recipient=self.user,
            band=self.band,
            event_type="NEW_SHOW",
            title="Title",
            message="Msg",
            target_url="/banda-teste/show/1"
        )
        
        self.now = timezone.now()
        
    def _create_delivery(self, status, attempt_count=0, age_minutes=20, sub=None, notif=None):
        d = WebPushDelivery.objects.create(
            notification=notif or self.notification,
            subscription=sub or self.sub,
            status=status,
            attempt_count=attempt_count,
            created_at=self.now - datetime.timedelta(minutes=age_minutes),
        )
        WebPushDelivery.objects.filter(pk=d.pk).update(
            updated_at=self.now - datetime.timedelta(minutes=age_minutes),
            last_attempt_at=(self.now - datetime.timedelta(minutes=age_minutes)) if attempt_count > 0 else None
        )
        d.refresh_from_db()
        return d

    def test_find_old_pending_is_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'pending', 15, 3, 50)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['delivery_id'], d.id)

    def test_find_recent_pending_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=10)
        res = find_retryable_web_push_deliveries(self.band.slug, 'pending', 15, 3, 50)
        self.assertEqual(len(res), 0)

    def test_find_old_temporary_failure_is_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=1, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'temporary-failure', 15, 3, 50)
        self.assertEqual(len(res), 1)

    def test_find_recent_temporary_failure_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=1, age_minutes=10)
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)

    def test_sent_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.SENT, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)
        
    def test_sending_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.SENDING, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)
        
    def test_permanent_failure_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PERMANENT_FAILURE, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)

    def test_skipped_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.SKIPPED, age_minutes=20)
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)

    def test_attempt_limits(self):
        d1 = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=2, age_minutes=20)
        sub2 = WebPushSubscription.objects.create(
            user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True
        )
        d2 = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=3, age_minutes=20, sub=sub2)
        
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['delivery_id'], d1.id)

    def test_inactive_subscription_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        self.sub.is_active = False
        self.sub.save()
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)
        
    def test_expired_subscription_not_eligible(self):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        self.sub.expiration_time = self.now - datetime.timedelta(days=1)
        self.sub.save()
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)
        
    def test_wrong_band_not_eligible(self):
        sub2 = WebPushSubscription.objects.create(
            user=self.user, band=self.band2, endpoint="b", p256dh="b", auth="b", service_worker_scope="/outra-banda/", is_active=True
        )
        notif2 = Notification.objects.create(recipient=self.user, band=self.band2, event_type="NEW_SHOW", title="T", message="M", target_url="/outra-banda/1")
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20, sub=sub2, notif=notif2)
        
        res = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 50)
        self.assertEqual(len(res), 0)

    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_dry_run_does_not_alter(self, mock_send):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=1, age_minutes=20)
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=False)
        self.assertEqual(res["summary"]["mode"], "DRY-RUN")
        self.assertEqual(res["summary"]["candidates"], 1)
        mock_send.assert_not_called()
        
        d.refresh_from_db()
        self.assertEqual(d.status, WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)

    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_execute_pending_calls_send(self, mock_send):
        mock_send.return_value = "SENT"
        
        def fake_send(d_id):
            self.assertFalse(connection.in_atomic_block, "Rede deve ser chamada fora de atomic")
            return "SENT"
            
        mock_send.side_effect = fake_send
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["attempted"], 1)
        self.assertEqual(res["summary"]["sent"], 1)
        mock_send.assert_called_once_with(d.id)
        
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_execute_temporary_failure_calls_send(self, mock_send):
        mock_send.return_value = "SENT"
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=1, age_minutes=20)
        WebPushDelivery.objects.filter(pk=d.pk).update(error_code="teste", last_http_status=503)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        
        mock_send.assert_called_once_with(d.id)
        
        d.refresh_from_db()
        self.assertEqual(d.status, WebPushDelivery.StatusChoices.PENDING)
        self.assertEqual(d.error_code, "")
        self.assertIsNone(d.last_http_status)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_concurrent_skip_by_mocking_find(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, attempt_count=1, age_minutes=20)
        mock_find.return_value = [
            {"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, "attempt_count": 1}
        ]
        
        # Change status now, so the atomic update within retry fails to match
        WebPushDelivery.objects.filter(pk=d.id).update(status=WebPushDelivery.StatusChoices.SENDING)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)
        self.assertEqual(res["summary"]["attempted"], 0)
        mock_send.assert_not_called()

    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_isolation_on_unexpected_error(self, mock_send):
        mock_send.side_effect = [Exception("Bum"), "SENT"]
        
        sub2 = WebPushSubscription.objects.create(
            user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True
        )
        
        d1 = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        d2 = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20, sub=sub2)
        
        WebPushDelivery.objects.filter(pk=d1.id).update(updated_at=self.now - datetime.timedelta(minutes=25))
        WebPushDelivery.objects.filter(pk=d2.id).update(updated_at=self.now - datetime.timedelta(minutes=21))
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["unexpected_error"], 1)
        self.assertEqual(res["summary"]["sent"], 1)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_user_changed(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.PENDING, "attempt_count": 0}]
        
        # Alter user
        other_user = User.objects.create_user(username="other_user", email="other@example.com")
        WebPushSubscription.objects.filter(pk=self.sub.id).update(user=other_user)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)
        mock_send.assert_not_called()

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_band_changed(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.PENDING, "attempt_count": 0}]
        
        other_band = Band.objects.create(name="Other", slug="other")
        WebPushSubscription.objects.filter(pk=self.sub.id).update(band=other_band)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_scope_changed(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.PENDING, "attempt_count": 0}]
        
        WebPushSubscription.objects.filter(pk=self.sub.id).update(service_worker_scope="/other/")
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_inactive_subscription(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=20, attempt_count=1)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, "attempt_count": 1}]
        
        WebPushSubscription.objects.filter(pk=self.sub.id).update(is_active=False)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_wrong_band_notification(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=20, attempt_count=1)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, "attempt_count": 1}]
        
        other_band = Band.objects.create(name="Other", slug="other")
        Notification.objects.filter(pk=self.notification.id).update(band=other_band)
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)

    def test_ordering_rules(self):
        sub_a = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True)
        sub_b = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="b", p256dh="b", auth="b", service_worker_scope="/banda-teste/", is_active=True)
        sub_c = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="c", p256dh="c", auth="c", service_worker_scope="/banda-teste/", is_active=True)
        sub_d = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="d", p256dh="d", auth="d", service_worker_scope="/banda-teste/", is_active=True)
        
        d_tf_recent = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=20, attempt_count=1, sub=sub_a)
        d_tf_old = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=40, attempt_count=1, sub=sub_b)
        d_p_recent = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=30, sub=sub_c)
        d_p_old = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=50, sub=sub_d)

        WebPushDelivery.objects.filter(pk=d_tf_recent.id).update(last_attempt_at=self.now - datetime.timedelta(minutes=20))
        WebPushDelivery.objects.filter(pk=d_tf_old.id).update(last_attempt_at=self.now - datetime.timedelta(minutes=40))
        WebPushDelivery.objects.filter(pk=d_p_recent.id).update(updated_at=self.now - datetime.timedelta(minutes=30))
        WebPushDelivery.objects.filter(pk=d_p_old.id).update(updated_at=self.now - datetime.timedelta(minutes=50))

        cands = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 10)
        self.assertEqual(len(cands), 4)
        
        self.assertEqual(cands[0]["delivery_id"], d_p_old.id)
        self.assertEqual(cands[1]["delivery_id"], d_p_recent.id)
        self.assertEqual(cands[2]["delivery_id"], d_tf_old.id)
        self.assertEqual(cands[3]["delivery_id"], d_tf_recent.id)

    def test_ordering_limit_applied_last(self):
        sub_e = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="e", p256dh="e", auth="e", service_worker_scope="/banda-teste/", is_active=True)
        sub_f = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="f", p256dh="f", auth="f", service_worker_scope="/banda-teste/", is_active=True)

        d_tf = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=40, attempt_count=1, sub=sub_e)
        d_p = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=50, sub=sub_f)
        
        WebPushDelivery.objects.filter(pk=d_tf.id).update(last_attempt_at=self.now - datetime.timedelta(minutes=40))
        WebPushDelivery.objects.filter(pk=d_p.id).update(updated_at=self.now - datetime.timedelta(minutes=50))
        
        cands = find_retryable_web_push_deliveries(self.band.slug, 'both', 15, 3, 1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["delivery_id"], d_p.id)

    def test_ordering_pending_ignores_last_attempt_at(self):
        sub_a = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True)
        sub_b = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="b", p256dh="b", auth="b", service_worker_scope="/banda-teste/", is_active=True)
        
        d_p_recent = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=30, sub=sub_a)
        d_p_old = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=50, sub=sub_b)

        # Recent pending gets a very old last_attempt_at (e.g. from a past state)
        WebPushDelivery.objects.filter(pk=d_p_recent.id).update(updated_at=self.now - datetime.timedelta(minutes=30), last_attempt_at=self.now - datetime.timedelta(minutes=100))
        WebPushDelivery.objects.filter(pk=d_p_old.id).update(updated_at=self.now - datetime.timedelta(minutes=50), last_attempt_at=None)

        cands = find_retryable_web_push_deliveries(self.band.slug, 'pending', 15, 3, 10)
        self.assertEqual(len(cands), 2)
        
        # It must sort by updated_at, so d_p_old (50m) comes before d_p_recent (30m)
        self.assertEqual(cands[0]["delivery_id"], d_p_old.id)
        self.assertEqual(cands[1]["delivery_id"], d_p_recent.id)

    def test_eligibility_pending_ignores_last_attempt_at(self):
        sub_a = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True)
        d_p_recent = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=10, sub=sub_a)
        
        # updated_at is recent (10m < 15m), but last_attempt_at is old (100m)
        WebPushDelivery.objects.filter(pk=d_p_recent.id).update(updated_at=self.now - datetime.timedelta(minutes=10), last_attempt_at=self.now - datetime.timedelta(minutes=100))
        
        cands = find_retryable_web_push_deliveries(self.band.slug, 'pending', 15, 3, 10)
        # Should not be eligible because updated_at is recent
        self.assertEqual(len(cands), 0)

    def test_ordering_temporary_failure_fallback(self):
        sub_a = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="a", p256dh="a", auth="a", service_worker_scope="/banda-teste/", is_active=True)
        sub_b = WebPushSubscription.objects.create(user=self.user, band=self.band, endpoint="b", p256dh="b", auth="b", service_worker_scope="/banda-teste/", is_active=True)
        
        d_tf_with_last = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=20, attempt_count=1, sub=sub_a)
        d_tf_no_last = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=40, attempt_count=1, sub=sub_b)

        WebPushDelivery.objects.filter(pk=d_tf_with_last.id).update(last_attempt_at=self.now - datetime.timedelta(minutes=20), updated_at=self.now - datetime.timedelta(minutes=50))
        WebPushDelivery.objects.filter(pk=d_tf_no_last.id).update(last_attempt_at=None, updated_at=self.now - datetime.timedelta(minutes=40))

        cands = find_retryable_web_push_deliveries(self.band.slug, 'temporary-failure', 15, 3, 10)
        self.assertEqual(len(cands), 2)
        
        # d_tf_no_last uses updated_at (40m)
        # d_tf_with_last uses last_attempt_at (20m), so no_last is older
        self.assertEqual(cands[0]["delivery_id"], d_tf_no_last.id)
        self.assertEqual(cands[1]["delivery_id"], d_tf_with_last.id)

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_pending_expired_subscription(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.PENDING, age_minutes=20)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.PENDING, "attempt_count": 0}]
        
        # Expire subscription
        WebPushSubscription.objects.filter(pk=self.sub.id).update(expiration_time=self.now - datetime.timedelta(minutes=1))
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)
        mock_send.assert_not_called()

    @patch('core.services.web_push_operations.find_retryable_web_push_deliveries')
    @patch('core.services.web_push_operations.send_web_push_delivery')
    def test_revalidation_temporary_failure_expired_subscription(self, mock_send, mock_find):
        d = self._create_delivery(WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, age_minutes=20, attempt_count=1)
        mock_find.return_value = [{"delivery_id": d.id, "status": WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, "attempt_count": 1}]
        
        # Expire subscription
        WebPushSubscription.objects.filter(pk=self.sub.id).update(expiration_time=self.now - datetime.timedelta(minutes=1))
        
        res = retry_web_push_deliveries(band_slug=self.band.slug, execute=True)
        self.assertEqual(res["summary"]["skipped_concurrent"], 1)
        mock_send.assert_not_called()

class WebPushRetryCommandTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        
    def test_command_requires_band(self):
        with self.assertRaises(CommandError):
            call_command('web_push_retry')
            
    def test_command_validates_args(self):
        with self.assertRaises(CommandError):
            call_command('web_push_retry', band_slug=self.band.slug, max_attempts=50)

    @patch('core.management.commands.web_push_retry.retry_web_push_deliveries')
    def test_command_calls_correctly(self, mock_retry):
        mock_retry.return_value = {"candidates": [], "summary": {"mode": "DRY-RUN", "candidates": 0, "processed_ids": [], "attempted":0, "sent":0, "temporary_failure":0, "permanent_failure":0, "skipped":0, "skipped_concurrent":0, "unexpected_error":0}}
        out = StringIO()
        call_command('web_push_retry', band_slug=self.band.slug, limit=10, stdout=out)
        self.assertIn("DRY-RUN", out.getvalue())
        mock_retry.assert_called_once_with(band_slug=self.band.slug, status_filter='both', retry_after_minutes=15, max_attempts=3, limit=10, execute=False)

    @patch('core.management.commands.web_push_retry.retry_web_push_deliveries')
    def test_command_json_output(self, mock_retry):
        mock_retry.return_value = {"summary": {"mode": "DRY-RUN"}}
        out = StringIO()
        call_command('web_push_retry', band_slug=self.band.slug, json=True, stdout=out)
        val = json.loads(out.getvalue())
        self.assertEqual(val["summary"]["mode"], "DRY-RUN")
