import datetime
import json
import sys
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO
from django.db.models import F

from core.models import Band, User, Notification, WebPushSubscription, WebPushDelivery
from core.services.web_push_operations import (
    build_web_push_health_snapshot,
    reconcile_stale_sending_deliveries,
)

class WebPushOperationsTests(TestCase):

    def test_list_recent_problematic_deliveries_statuses_and_fields(self):
        from core.services.web_push_operations import list_recent_problematic_deliveries
        from core.models import WebPushDelivery, Notification, Band, User, WebPushSubscription
        from django.utils import timezone

        user = User.objects.create_user(username="testuser999", password="pwd", email="999@example.com")
        band = Band.objects.create(name="Band 999", slug="band-999")
        band.users.add(user)
        notification = Notification.objects.create(
            band=band, title="Test", message="Test", recipient=user
        )
        
        sub1 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t1", p256dh="a", auth="a", service_worker_scope="/")
        sub2 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t2", p256dh="a", auth="a", service_worker_scope="/")
        sub3 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t3", p256dh="a", auth="a", service_worker_scope="/")
        sub4 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t4", p256dh="a", auth="a", service_worker_scope="/")
        sub5 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t5", p256dh="a", auth="a", service_worker_scope="/")
        sub6 = WebPushSubscription.objects.create(user=user, band=band, endpoint="http://t6", p256dh="a", auth="a", service_worker_scope="/")
        
        d1 = WebPushDelivery.objects.create(notification=notification, subscription=sub1, status=WebPushDelivery.StatusChoices.PENDING)
        d2 = WebPushDelivery.objects.create(notification=notification, subscription=sub2, status=WebPushDelivery.StatusChoices.SENDING)
        d3 = WebPushDelivery.objects.create(notification=notification, subscription=sub3, status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)
        d4 = WebPushDelivery.objects.create(notification=notification, subscription=sub4, status=WebPushDelivery.StatusChoices.PERMANENT_FAILURE)
        d5 = WebPushDelivery.objects.create(notification=notification, subscription=sub5, status=WebPushDelivery.StatusChoices.SKIPPED)
        d6 = WebPushDelivery.objects.create(notification=notification, subscription=sub6, status=WebPushDelivery.StatusChoices.SENT)
        
        results = list_recent_problematic_deliveries(band_slug="band-999")
        
        self.assertEqual(len(results), 5)
        statuses = [r["status"] for r in results]
        self.assertNotIn("SENT", statuses)
        self.assertEqual(results[0]["status"], "SENDING")
        self.assertEqual(results[1]["status"], "PENDING")
        self.assertEqual(results[2]["status"], "TEMPORARY_FAILURE")
        self.assertEqual(results[3]["status"], "PERMANENT_FAILURE")
        self.assertEqual(results[4]["status"], "SKIPPED")
        
        expected_keys = {"delivery_id", "band_slug", "status", "attempt_count", "last_http_status", "error_code", "created_at", "updated_at", "last_attempt_at"}
        self.assertEqual(set(results[0].keys()), expected_keys)
        self.assertEqual(results[0]["band_slug"], "band-999")
        
    def test_list_recent_problematic_deliveries_band_isolation(self):
        from core.services.web_push_operations import list_recent_problematic_deliveries
        from core.models import WebPushDelivery, Notification, Band, User, WebPushSubscription
        from django.utils import timezone

        user = User.objects.create_user(username="testuser888", password="pwd", email="888@example.com")
        band1 = Band.objects.create(name="Band 1", slug="band-1")
        band2 = Band.objects.create(name="Band 2", slug="band-2")
        band1.users.add(user)
        band2.users.add(user)
        
        n1 = Notification.objects.create(band=band1, title="Test1", message="Test1", recipient=user)
        n2 = Notification.objects.create(band=band2, title="Test2", message="Test2", recipient=user)
        
        sub1 = WebPushSubscription.objects.create(user=user, band=band1, endpoint="http://test81", p256dh="a", auth="a", service_worker_scope="/")
        sub2 = WebPushSubscription.objects.create(user=user, band=band2, endpoint="http://test82", p256dh="a", auth="a", service_worker_scope="/")
        
        WebPushDelivery.objects.create(notification=n1, subscription=sub1, status=WebPushDelivery.StatusChoices.PENDING)
        WebPushDelivery.objects.create(notification=n2, subscription=sub2, status=WebPushDelivery.StatusChoices.PENDING)
        
        res1 = list_recent_problematic_deliveries(band_slug="band-1")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["band_slug"], "band-1")
        
        res_all = list_recent_problematic_deliveries()
        self.assertGreaterEqual(len(res_all), 2)



    def _make_snapshot_with_success_rate(self, rate, completed=10):
        return {
            "deliveries": {
                "recent_window": {"created": 1, "temporary_failure": 0, "permanent_failure": 0},
                "rates": {"completed": completed, "success_rate": rate}
            },
            "anomalies": {"stale_sending_count": 0, "stale_pending_count": 0, "active_expired_subscriptions_count": 0},
            "subscriptions": {"active_with_failures": 0}
        }

    def test_success_rate_1_0_no_alerts(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(1.0)
        alerts = build_web_push_operational_alerts(snap)
        self.assertFalse(any(a["severity"] in ["WARNING", "CRITICAL"] for a in alerts))

    def test_success_rate_0_95_no_alerts(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(0.95)
        alerts = build_web_push_operational_alerts(snap)
        self.assertFalse(any(a["severity"] in ["WARNING", "CRITICAL"] for a in alerts))

    def test_success_rate_0_90_warning(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(0.90)
        alerts = build_web_push_operational_alerts(snap)
        self.assertTrue(any(a["severity"] == "WARNING" and a["code"] == "moderate_success_rate" for a in alerts))

    def test_success_rate_0_80_warning(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(0.80)
        alerts = build_web_push_operational_alerts(snap)
        self.assertTrue(any(a["severity"] == "WARNING" and a["code"] == "moderate_success_rate" for a in alerts))

    def test_success_rate_0_79_critical(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(0.79)
        alerts = build_web_push_operational_alerts(snap)
        self.assertTrue(any(a["severity"] == "CRITICAL" and a["code"] == "critical_success_rate" for a in alerts))

    def test_success_rate_0_0_with_completed_critical(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(0.0, completed=10)
        alerts = build_web_push_operational_alerts(snap)
        self.assertTrue(any(a["severity"] == "CRITICAL" and a["code"] == "critical_success_rate" for a in alerts))

    def test_success_rate_none_info(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = self._make_snapshot_with_success_rate(None, completed=0)
        alerts = build_web_push_operational_alerts(snap)
        self.assertFalse(any(a["severity"] == "CRITICAL" for a in alerts))
        self.assertTrue(any(a["severity"] == "INFO" and a["code"] == "no_completed_deliveries" for a in alerts))
    def setUp(self):
        # Proteção contra rede
        self.patcher1 = patch('core.services.web_push_delivery.webpush', side_effect=Exception("Rede bloqueada"))
        self.patcher2 = patch('core.services.web_push_delivery.send_web_push_delivery', side_effect=Exception("Rede bloqueada"))
        
        self.patcher1.start()
        self.patcher2.start()
        
        self.band1 = Band.objects.create(name='Banda 1', slug='banda-1')
        self.band2 = Band.objects.create(name='Banda 2', slug='banda-2')
        self.user1 = User.objects.create(username='u1', email='u1@e.com', band=self.band1)
        self.user2 = User.objects.create(username='u2', email='u2@e.com', band=self.band2)
        
        self.notif1 = Notification.objects.create(band=self.band1, recipient=self.user1, event_type='NEW_SHOW', title='T', message='M')
        self.notif2 = Notification.objects.create(band=self.band2, recipient=self.user2, event_type='NEW_SHOW', title='T2', message='M2')
        
        self.sub1 = WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint='https://e1', p256dh='p1', auth='a1', is_active=True, service_worker_scope=f'/{self.band1.slug}/')
        
    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()

    def test_snapshot_empty(self):
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['deliveries']['total']['total'], 0)
        self.assertIsNone(snap['deliveries']['rates']['success_rate'])

    def test_status_counts(self):
        sub2 = WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint='e2', p256dh='p2', auth='a2', is_active=True, service_worker_scope=f'/{self.band1.slug}/')
        sub3 = WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint='e3', p256dh='p3', auth='a3', is_active=True, service_worker_scope=f'/{self.band1.slug}/')
        WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='PENDING')
        WebPushDelivery.objects.create(notification=self.notif1, subscription=sub2, status='SENDING')
        WebPushDelivery.objects.create(notification=self.notif1, subscription=sub3, status='SENT', sent_at=timezone.now())
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['deliveries']['total']['total'], 3)
        self.assertEqual(snap['deliveries']['total']['PENDING'], 1)
        self.assertEqual(snap['deliveries']['total']['SENDING'], 1)
        self.assertEqual(snap['deliveries']['total']['SENT'], 1)

    def test_recent_window(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENT', sent_at=timezone.now())
        d.created_at = timezone.now() - datetime.timedelta(hours=25)
        d.save()
        snap = build_web_push_health_snapshot(window_hours=24)
        self.assertEqual(snap['deliveries']['recent_window']['created'], 0)

    def test_success_rate(self):
        sub2 = WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint='e2', p256dh='p2', auth='a2', is_active=True, service_worker_scope=f'/{self.band1.slug}/')
        WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENT')
        WebPushDelivery.objects.create(notification=self.notif1, subscription=sub2, status='TEMPORARY_FAILURE')
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['deliveries']['rates']['completed'], 2)
        self.assertEqual(snap['deliveries']['rates']['success_rate'], 0.5)

    def test_stale_pending(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='PENDING')
        d.created_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        snap = build_web_push_health_snapshot(stale_pending_minutes=10)
        self.assertEqual(snap['anomalies']['stale_pending_count'], 1)

    def test_recent_pending_not_stale(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='PENDING')
        snap = build_web_push_health_snapshot(stale_pending_minutes=10)
        self.assertEqual(snap['anomalies']['stale_pending_count'], 0)

    def test_stale_sending_last_attempt(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        snap = build_web_push_health_snapshot(stale_sending_minutes=15)
        self.assertEqual(snap['anomalies']['stale_sending_count'], 1)

    def test_recent_sending_not_stale(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=5)
        d.save()
        snap = build_web_push_health_snapshot(stale_sending_minutes=15)
        self.assertEqual(snap['anomalies']['stale_sending_count'], 0)

    def test_stale_sending_updated_at(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = None
        d.save()
        WebPushDelivery.objects.filter(pk=d.pk).update(updated_at=timezone.now() - datetime.timedelta(minutes=20))
        snap = build_web_push_health_snapshot(stale_sending_minutes=15)
        self.assertEqual(snap['anomalies']['stale_sending_count'], 1)

    def test_sent_without_sent_at(self):
        WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENT')
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['anomalies']['sent_without_sent_at_count'], 1)

    def test_subscriptions_active_inactive(self):
        WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint='e2', p256dh='p', auth='a', is_active=False, service_worker_scope=f'/{self.band1.slug}/')
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['subscriptions']['active'], 1)
        self.assertEqual(snap['subscriptions']['inactive'], 1)

    def test_active_expired(self):
        self.sub1.expiration_time = timezone.now() - datetime.timedelta(days=1)
        self.sub1.save()
        snap = build_web_push_health_snapshot()
        self.assertEqual(snap['subscriptions']['expired_but_active'], 1)

    def test_band_filter(self):
        WebPushDelivery.objects.create(notification=self.notif2, subscription=self.sub1, status='SENT')
        snap = build_web_push_health_snapshot(band_slug=self.band1.slug)
        self.assertEqual(snap['deliveries']['total']['SENT'], 0)
        
    def test_nonexistent_band(self):
        with self.assertRaises(ValueError):
            build_web_push_health_snapshot(band_slug='invalida')

    def test_no_secrets(self):
        snap = build_web_push_health_snapshot()
        s = str(snap)
        self.assertNotIn('p256dh', s)
        self.assertNotIn('endpoint', s)

    def test_serializable(self):
        snap = build_web_push_health_snapshot()
        json.dumps(snap)

    def test_dry_run_finds(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        res = reconcile_stale_sending_deliveries(15, execute=False)
        self.assertTrue(res['dry_run'])
        self.assertEqual(res['found_count'], 1)

    def test_dry_run_no_changes(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        reconcile_stale_sending_deliveries(15, execute=False)
        d.refresh_from_db()
        self.assertEqual(d.status, 'SENDING')

    def test_execute_changes(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING', attempt_count=1)
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        res = reconcile_stale_sending_deliveries(15, execute=True)
        self.assertEqual(res['reconciled_count'], 1)
        d.refresh_from_db()
        self.assertEqual(d.status, 'TEMPORARY_FAILURE')
        self.assertEqual(d.error_code, 'stale_sending')
        self.assertEqual(d.attempt_count, 1)

    def test_execute_recent_ignored(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=5)
        d.save()
        res = reconcile_stale_sending_deliveries(15, execute=True)
        self.assertEqual(res['reconciled_count'], 0)

    def test_execute_concurrent_skipped(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING')
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        # Modifica status concurrentemente
        WebPushDelivery.objects.filter(pk=d.pk).update(status='SENT')
        res = reconcile_stale_sending_deliveries(15, execute=True)
        self.assertEqual(res['reconciled_count'], 0)

    def test_execute_limit(self):
        for i in range(5):
            sub = WebPushSubscription.objects.create(user=self.user1, band=self.band1, endpoint=f'e_{i}', p256dh='p', auth='a', is_active=True, service_worker_scope=f'/{self.band1.slug}/')
            d = WebPushDelivery.objects.create(notification=self.notif1, subscription=sub, status='SENDING')
            d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
            d.save()
        res = reconcile_stale_sending_deliveries(15, limit=2, execute=True)
        self.assertEqual(res['reconciled_count'], 2)

    def test_health_command(self):
        out = StringIO()
        call_command('web_push_health', stdout=out)
        self.assertIn('Diagnóstico Operacional Web Push', out.getvalue())

    def test_health_json(self):
        out = StringIO()
        call_command('web_push_health', json=True, stdout=out)
        data = json.loads(out.getvalue())
        self.assertIn('deliveries', data)

    def test_reconcile_dry_run_command(self):
        out = StringIO()
        call_command('web_push_reconcile_stale', stdout=out)
        self.assertIn('MODO DRY-RUN', out.getvalue())

    def test_reconcile_execute_command(self):
        out = StringIO()
        call_command('web_push_reconcile_stale', execute=True, stdout=out)
        self.assertIn('EXECUÇÃO REAL', out.getvalue())

    def test_stale_minutes_validation(self):
        with self.assertRaises(CommandError):
            call_command('web_push_reconcile_stale', stale_minutes=2)
            
    def test_limit_validation(self):
        with self.assertRaises(CommandError):
            call_command('web_push_reconcile_stale', limit=0)
            
    def test_reconcile_preserves_subscription(self):
        d = WebPushDelivery.objects.create(notification=self.notif1, subscription=self.sub1, status='SENDING', attempt_count=1)
        d.last_attempt_at = timezone.now() - datetime.timedelta(minutes=20)
        d.save()
        reconcile_stale_sending_deliveries(15, execute=True)
        self.sub1.refresh_from_db()
        self.assertTrue(self.sub1.is_active)
        self.assertEqual(self.sub1.failure_count, 0)
