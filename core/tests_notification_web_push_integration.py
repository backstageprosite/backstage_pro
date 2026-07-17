import logging
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.db import connection, transaction
from django.utils import timezone
from core.models import Band, User, Notification, WebPushSubscription, WebPushDelivery
from core.services.notifications import notify_band_users, _dispatch_web_push_deliveries_safe
from core.services.web_push_delivery import MAX_WEB_PUSH_PAYLOAD_BYTES

class NotificationWebPushIntegrationTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Test Band", slug="test-band", is_active=True)
        self.user1 = User.objects.create_user(username="testuser1", email="test1@test.com", role="PRODUTOR", is_active=True)
        self.user1.band = self.band
        self.user1.save()
        
        self.user2 = User.objects.create_user(username="testuser2", email="test2@test.com", role="INTEGRANTE", is_active=True)
        self.user2.band = self.band
        self.user2.save()
        
        self.sub1 = WebPushSubscription.objects.create(
            user=self.user1,
            band=self.band,
            endpoint="https://test.com/1",
            p256dh="key1",
            auth="auth1",
            service_worker_scope="/test-band/",
            is_active=True
        )

    def test_new_notification_allowed_event_prepares_delivery_and_registers_callback(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            count = notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='evt1'
            )
            
        self.assertEqual(count, 2)
        
        # user1 has subscription, user2 does not. We expect 1 delivery.
        self.assertEqual(WebPushDelivery.objects.count(), 1)
        delivery = WebPushDelivery.objects.first()
        self.assertEqual(delivery.subscription, self.sub1)
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.PENDING)
        
        # 1 callback should be registered
        self.assertEqual(len(callbacks), 1)
        
        # The callback is a partial, we can inspect args
        func = callbacks[0]
        # Partial wraps _dispatch_web_push_deliveries_safe
        self.assertEqual(func.func, _dispatch_web_push_deliveries_safe)
        
        # Should receive IDs (tuple), not models
        ids = func.args[0]
        self.assertIsInstance(ids, tuple)
        self.assertEqual(len(ids), 1)
        self.assertIsInstance(ids[0], int)
        self.assertEqual(ids[0], delivery.id)

    @patch('core.services.notifications.send_web_push_delivery')
    def test_callback_executes_after_commit(self, mock_send):
        with self.captureOnCommitCallbacks(execute=True):
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='evt2'
            )
            # send_web_push_delivery should not be called until commit happens
            
        # Now callbacks have run
        mock_send.assert_called_once()

    def test_no_callback_when_no_active_subscriptions(self):
        self.sub1.is_active = False
        self.sub1.save()
        
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='evt3'
            )
            
        self.assertEqual(len(callbacks), 0)
        self.assertEqual(WebPushDelivery.objects.count(), 0)

    @patch('core.services.notifications.prepare_web_push_deliveries')
    def test_created_false_does_not_prepare_or_send(self, mock_prepare):
        # Create it first
        notify_band_users(
            band=self.band,
            event_type='NEW_SHOW',
            title='Test',
            message='Msg',
            target_url='/test-band/',
            event_key_base='evt4'
        )
        self.assertEqual(Notification.objects.filter(event_key='evt4').count(), 2)
        initial_deliveries = WebPushDelivery.objects.count()
        
        mock_prepare.reset_mock()
        
        # Call again (idempotency)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='evt4'
            )
            
        mock_prepare.assert_not_called()
        self.assertEqual(WebPushDelivery.objects.count(), initial_deliveries)
        self.assertEqual(len(callbacks), 0)

    def test_allowed_events(self):
        events = ['NEW_SHOW', 'SHOW_CANCELLED', 'SHOW_DATE_CHANGED', 'SHOW_START_TIME_CHANGED']
        for i, ev in enumerate(events):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                notify_band_users(
                    band=self.band,
                    event_type=ev,
                    title='Test',
                    message='Msg',
                    target_url='/test-band/',
                    event_key_base=f'ev_allowed_{i}'
                )
            self.assertEqual(len(callbacks), 1)

    def test_disallowed_event(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_band_users(
                band=self.band,
                event_type='SHOW_DELETED', # some fake event
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='ev_disallowed'
            )
        self.assertEqual(len(callbacks), 0)

    def test_inactive_and_cross_band_subscriptions_ignored(self):
        sub2 = WebPushSubscription.objects.create(
            user=self.user2,
            band=self.band,
            endpoint="https://test.com/inactive",
            p256dh="key",
            auth="auth",
            service_worker_scope="/test-band/",
            is_active=False
        )
        
        other_band = Band.objects.create(name="Other", slug="other", is_active=True)
        other_user = User.objects.create_user(username="other", email="other@test.com", role="PRODUTOR", is_active=True)
        other_user.band = other_band
        other_user.save()
        
        sub3 = WebPushSubscription.objects.create(
            user=other_user,
            band=other_band,
            endpoint="https://test.com/other",
            p256dh="key",
            auth="auth",
            service_worker_scope="/other/",
            is_active=True
        )
        
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='ev_isolation'
            )
            
        # Only sub1 should receive delivery
        deliveries = WebPushDelivery.objects.filter(notification__event_key='ev_isolation')
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries.first().subscription, self.sub1)

    def test_multiple_subscriptions_create_multiple_deliveries(self):
        sub2 = WebPushSubscription.objects.create(
            user=self.user2,
            band=self.band,
            endpoint="https://test.com/2",
            p256dh="key",
            auth="auth",
            is_active=True,
            service_worker_scope="/test-band/"
        )
        
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='ev_multi'
            )
            
        deliveries = WebPushDelivery.objects.filter(notification__event_key='ev_multi')
        self.assertEqual(deliveries.count(), 2)
        
        # 1 callback is registered, and receives exactly 2 unique IDs
        self.assertEqual(len(callbacks), 1)
        func = callbacks[0]
        ids = func.args[0]
        self.assertEqual(len(ids), 2)
        self.assertEqual(set(ids), set(deliveries.values_list('id', flat=True)))

    @patch('core.services.notifications.prepare_web_push_deliveries')
    def test_preparation_failure_does_not_break_notification(self, mock_prepare):
        mock_prepare.side_effect = Exception("DB error during preparation")
        
        with self.assertLogs('core.services.notifications', level='ERROR') as cm:
            notify_band_users(
                band=self.band,
                event_type='NEW_SHOW',
                title='Test',
                message='Msg',
                target_url='/test-band/',
                event_key_base='ev_prep_fail'
            )
            
        # Notification is still created
        self.assertEqual(Notification.objects.filter(event_key='ev_prep_fail').count(), 2)
        
        # Error is logged safely
        log_output = "\n".join(cm.output)
        self.assertIn("Web Push preparation failure", log_output)
        self.assertNotIn("DB error during preparation", log_output)

    @patch('core.services.notifications.send_web_push_delivery')
    def test_callback_failure_continues_to_next_delivery(self, mock_send):
        sub2 = WebPushSubscription.objects.create(
            user=self.user2,
            band=self.band,
            endpoint="https://test.com/2",
            p256dh="key",
            auth="auth",
            is_active=True,
            service_worker_scope="/test-band/"
        )
        
        # Fail the first, succeed the second
        def side_effect(delivery_id):
            if side_effect.count == 0:
                side_effect.count += 1
                raise Exception("Secret:1234 - Fake Network Error")
            return "SENT"
        side_effect.count = 0
        mock_send.side_effect = side_effect
        
        notify_band_users(
            band=self.band,
            event_type='NEW_SHOW',
            title='Test',
            message='Msg',
            target_url='/test-band/',
            event_key_base='ev_cb_fail'
        )
        
        delivery_ids = tuple(WebPushDelivery.objects.filter(notification__event_key='ev_cb_fail').values_list('id', flat=True))
        self.assertEqual(len(delivery_ids), 2)
        
        with self.assertLogs('core.services.notifications', level='ERROR') as cm:
            _dispatch_web_push_deliveries_safe(delivery_ids)
            
        self.assertEqual(mock_send.call_count, 2)
        log_output = "\n".join(cm.output)
        self.assertIn("Web Push callback failure", log_output)
        self.assertNotIn("Secret:1234", log_output)

    @patch('core.services.notifications.send_web_push_delivery')
    def test_callback_not_called_in_atomic_block(self, mock_send):
        def side_effect(*args, **kwargs):
            if connection.in_atomic_block:
                raise RuntimeError("Rede dentro de atomic")
            return "SENT"
            
        mock_send.side_effect = side_effect
        
        with transaction.atomic():
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                notify_band_users(
                    band=self.band,
                    event_type='NEW_SHOW',
                    title='Test',
                    message='Msg',
                    target_url='/test-band/',
                    event_key_base='ev_atomic'
                )
                self.assertEqual(mock_send.call_count, 0)
                
        # Outside transaction, callbacks should have executed
        self.assertEqual(mock_send.call_count, 1)

class NotificationWebPushRollbackTests(TransactionTestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Test Band", slug="test-band", is_active=True)
        self.user1 = User.objects.create_user(username="testuser1", email="test1_tx@test.com", role="PRODUTOR", is_active=True)
        self.user1.band = self.band
        self.user1.save()
        
        self.sub1 = WebPushSubscription.objects.create(
            user=self.user1,
            band=self.band,
            endpoint="https://test.com/1",
            p256dh="key1",
            auth="auth1",
            service_worker_scope="/test-band/",
            is_active=True
        )

    @patch('core.services.notifications.send_web_push_delivery')
    def test_rollback_discards_everything(self, mock_send):
        try:
            with transaction.atomic():
                notify_band_users(
                    band=self.band,
                    event_type='NEW_SHOW',
                    title='Test',
                    message='Msg',
                    target_url='/test-band/',
                    event_key_base='ev_rollback'
                )
                
                # Verify things were created inside transaction
                self.assertEqual(Notification.objects.filter(event_key='ev_rollback').count(), 1)
                self.assertEqual(WebPushDelivery.objects.count(), 1)
                
                # Rollback!
                raise RuntimeError("Abort transaction")
        except RuntimeError:
            pass
            
        # Should be completely gone
        self.assertEqual(Notification.objects.filter(event_key='ev_rollback').count(), 0)
        self.assertEqual(WebPushDelivery.objects.count(), 0)
        
        # Callback must not have fired
        mock_send.assert_not_called()
