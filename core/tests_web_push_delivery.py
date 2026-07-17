import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.db import connection, transaction
import datetime
from pywebpush import WebPushException

from core.models import Band, User, Notification, WebPushSubscription, WebPushDelivery
from core.services.web_push_delivery import (
    build_web_push_payload,
    prepare_web_push_deliveries,
    send_web_push_delivery,
    dispatch_notification_web_push
)

class WebPushDeliveryTests(TransactionTestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Test Band", slug="test-band", is_active=True)
        self.user = User.objects.create_user(username="testuser", password="testpassword", email="test@test.com")
        self.user.band = self.band
        self.user.save()
        
        self.notification = Notification.objects.create(
            band=self.band,
            recipient=self.user,
            event_type='NEW_SHOW',
            title='Novo show',
            message='Mensagem do show',
            target_url='/test-band/shows/1/',
            event_key='test-key-1'
        )

        self.subscription = WebPushSubscription.objects.create(
            user=self.user,
            band=self.band,
            endpoint='https://test.com/endpoint',
            p256dh='p256dh-key',
            auth='auth-key',
            service_worker_scope='/test-band/'
        )

    def test_build_web_push_payload_valid(self):
        payload = build_web_push_payload(self.notification)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['version'], 1)
        self.assertEqual(payload['notification_id'], self.notification.id)
        self.assertEqual(payload['event_type'], 'NEW_SHOW')
        self.assertEqual(payload['band_slug'], 'test-band')
        self.assertEqual(payload['title'], 'Novo show')
        self.assertEqual(payload['message'], 'Mensagem do show')
        self.assertEqual(payload['target_url'], '/test-band/shows/1/')

    def test_build_web_push_payload_invalid_event(self):
        self.notification.event_type = 'INVALID_EVENT'
        self.notification.save()
        payload = build_web_push_payload(self.notification)
        self.assertIsNone(payload)

    def test_build_web_push_payload_invalid_target_url(self):
        self.notification.target_url = '/other-band/shows/1/'
        self.notification.save()
        payload = build_web_push_payload(self.notification)
        self.assertIsNone(payload)
        
        self.notification.target_url = 'https://test.com/test-band/'
        self.notification.save()
        payload = build_web_push_payload(self.notification)
        self.assertIsNone(payload)
        
        self.notification.target_url = '//test-band/'
        self.notification.save()
        payload = build_web_push_payload(self.notification)
        self.assertIsNone(payload)
        
        self.notification.target_url = '/test-band/%2520'
        self.notification.save()
        payload = build_web_push_payload(self.notification)
        self.assertIsNone(payload)

    @patch('core.services.web_push_delivery.build_web_push_payload')
    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_payload_length_limits(self, mock_vapid, mock_webpush, mock_build):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 201
        mock_webpush.return_value = response_mock
        
        # Test 1: Exactly 3800 bytes accepted
        base_payload = {
            "version": 1,
            "notification_id": self.notification.id,
            "event_type": "NEW_SHOW",
            "band_slug": "test-band",
            "title": "A",
            "message": "",
            "target_url": "/test-band/"
        }
        base_json_len = len(json.dumps(base_payload, ensure_ascii=False, separators=(",", ":")).encode('utf-8'))
        
        padding_needed = 3800 - base_json_len
        base_payload["message"] = "A" * padding_needed
        mock_build.return_value = base_payload
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SENT")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.SENT)

        # Test 2: 3801 bytes rejected
        WebPushDelivery.objects.all().delete()
        base_payload["message"] = "A" * (padding_needed + 1)
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SKIPPED")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.SKIPPED)
        self.assertEqual(delivery.error_code, "payload_too_large")
        
        # Test 3: Multibyte characters counted as bytes, not chars
        # padding_needed characters of "A" = padding_needed bytes.
        # if we use (padding_needed - 1) bytes and add 1 character of 2 bytes ('á'), we reach 3801 bytes but padding_needed characters!
        WebPushDelivery.objects.all().delete()
        base_payload["message"] = "A" * (padding_needed - 1) + "á"
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SKIPPED")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.SKIPPED)
        self.assertEqual(delivery.error_code, "payload_too_large")


    def test_prepare_web_push_deliveries(self):
        deliveries = prepare_web_push_deliveries(self.notification.id)
        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        self.assertEqual(delivery.notification, self.notification)
        self.assertEqual(delivery.subscription, self.subscription)
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.PENDING)

    def test_prepare_web_push_deliveries_expired_subscription(self):
        self.subscription.expiration_time = timezone.now() - datetime.timedelta(days=1)
        self.subscription.save()
        
        deliveries = prepare_web_push_deliveries(self.notification.id)
        self.assertEqual(len(deliveries), 0)
        
        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.is_active)
        self.assertEqual(self.subscription.failure_count, 1)

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_success(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        # Test 201
        response_mock = MagicMock()
        response_mock.status_code = 201
        mock_webpush.return_value = response_mock
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SENT")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(delivery.last_http_status, 201)
        
        mock_webpush.assert_called_once()
        args, kwargs = mock_webpush.call_args
        self.assertEqual(kwargs['vapid_claims']['sub'], 'mailto:test@test.com')

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_200_and_202(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        for status_code in (200, 202):
            response_mock = MagicMock()
            response_mock.status_code = status_code
            mock_webpush.return_value = response_mock
            
            # Use get_or_create or delete first to avoid unique constraint error
            WebPushDelivery.objects.all().delete()
            delivery = WebPushDelivery.objects.create(
                notification=self.notification,
                subscription=self.subscription,
                status=WebPushDelivery.StatusChoices.PENDING
            )

            
            res = send_web_push_delivery(delivery.id)
            self.assertEqual(res, "SENT")
            
            delivery.refresh_from_db()
            self.assertEqual(delivery.last_http_status, status_code)

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_permanent_failure(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 410
        mock_webpush.side_effect = WebPushException("Gone", response=response_mock)
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "PERMANENT_FAILURE")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.PERMANENT_FAILURE)
        self.assertEqual(delivery.last_http_status, 410)
        self.assertEqual(delivery.error_code, 'subscription_expired')
        
        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.is_active)

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_temporary_failure(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 503
        mock_webpush.side_effect = WebPushException("Service Unavailable", response=response_mock)
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "TEMPORARY_FAILURE")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)
        self.assertEqual(delivery.last_http_status, 503)
        self.assertEqual(delivery.error_code, 'webpush_exception')
        
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.is_active)
        self.assertEqual(self.subscription.failure_count, 1)

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_204(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 204
        mock_webpush.return_value = response_mock
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "TEMPORARY_FAILURE")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)
        self.assertEqual(delivery.last_http_status, 204)
        self.assertEqual(delivery.error_code, 'unexpected_http_status')

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_missing_response(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        mock_webpush.return_value = None
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "TEMPORARY_FAILURE")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)
        self.assertEqual(delivery.error_code, 'missing_http_response')


    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_vapid_claims_independence(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 201
        mock_webpush.return_value = response_mock
        
        sub2 = WebPushSubscription.objects.create(
            user=self.user,
            band=self.band,
            endpoint='https://test.com/endpoint2',
            p256dh='p256dh-key',
            auth='auth-key',
            service_worker_scope='/test-band/'
        )
        
        delivery1 = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        delivery2 = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=sub2,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        send_web_push_delivery(delivery1.id)
        send_web_push_delivery(delivery2.id)
        
        self.assertEqual(mock_webpush.call_count, 2)
        
        call1 = mock_webpush.call_args_list[0]
        call2 = mock_webpush.call_args_list[1]
        
        claims1 = call1[1]['vapid_claims']
        claims2 = call2[1]['vapid_claims']
        
        self.assertIsNot(claims1, claims2)  # Different objects in memory
        
        # mutating one shouldn't affect the other
        claims1['sub'] = 'changed'
        self.assertNotEqual(claims1['sub'], claims2['sub'])
        self.assertEqual(claims2['sub'], 'mailto:test@test.com')

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_isolation_and_transaction(self, mock_vapid, mock_webpush):
        # We need to make sure webpush is called outside of an atomic block
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 201
        
        def side_effect(*args, **kwargs):
            if connection.in_atomic_block:
                raise RuntimeError("Rede chamada dentro de transação")
            return response_mock
            
        mock_webpush.side_effect = side_effect
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SENT")

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_send_web_push_delivery_skips_if_not_pending(self, mock_vapid, mock_webpush):
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.SENT
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SKIPPED/ALREADY_CLAIMED")
        mock_webpush.assert_not_called()

    @patch('core.services.web_push_delivery.send_web_push_delivery')
    def test_dispatch_notification_web_push(self, mock_send):
        mock_send.return_value = "SENT"
        
        res = dispatch_notification_web_push(self.notification.id)
        self.assertEqual(res['total'], 1)
        self.assertEqual(res['sent'], 1)
        self.assertEqual(res['permanent_failure'], 0)
        
        mock_send.assert_called_once()
        
    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_dispatch_isolates_subscriptions(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        sub2 = WebPushSubscription.objects.create(
            user=self.user,
            band=self.band,
            endpoint='https://test.com/endpoint2',
            p256dh='p256dh-key',
            auth='auth-key',
            service_worker_scope='/test-band/'
        )
        
        # First webpush call fails with 410, second succeeds with 201

        response_201 = MagicMock()
        response_201.status_code = 201
        
        response_410 = MagicMock()
        response_410.status_code = 410
        
        mock_webpush.side_effect = [
            WebPushException("Gone", response=response_410),
            response_201
        ]
        
        res = dispatch_notification_web_push(self.notification.id)
        
        self.assertEqual(res['total'], 2)
        self.assertEqual(res['sent'], 1)
        self.assertEqual(res['permanent_failure'], 1)
        self.assertEqual(res['temporary_failure'], 0)
        self.assertEqual(res['skipped'], 0)
        
        self.assertEqual(mock_webpush.call_count, 2)
        
        # Verify subscriptions state
        self.subscription.refresh_from_db()
        sub2.refresh_from_db()
        
        self.assertFalse(self.subscription.is_active)
        self.assertTrue(sub2.is_active)
        
        # Verify notification intact
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.title, 'Novo show')

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_logs_no_secrets(self, mock_vapid, mock_webpush):
        # We simulate a webpush exception containing a fake secret to ensure it isn't logged 
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 503
        response_mock.text = "SECRET_12345"
        mock_webpush.side_effect = WebPushException("Service Unavailable SECRET_12345", response=response_mock)
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        with self.assertLogs('core.services.web_push_delivery', level='WARNING') as cm:
            res = send_web_push_delivery(delivery.id)
            self.assertEqual(res, "TEMPORARY_FAILURE")
            
        log_output = "\n".join(cm.output)
        self.assertNotIn("SECRET_12345", log_output)
        self.assertNotIn(self.subscription.endpoint, log_output)
        self.assertIn(str(delivery.id), log_output)

    @patch('core.services.web_push_delivery.webpush')
    @patch('core.services.web_push_delivery.load_vapid_configuration')
    def test_double_finalize_protection(self, mock_vapid, mock_webpush):
        mock_vapid.return_value.private_key = 'private-key'
        mock_vapid.return_value.subject = 'mailto:test@test.com'
        
        response_mock = MagicMock()
        response_mock.status_code = 503
        
        def side_effect(*args, **kwargs):
            # Simulate another worker finalizing the delivery while this one is doing the network call
            WebPushDelivery.objects.all().update(status=WebPushDelivery.StatusChoices.SENT)
            raise WebPushException("Service Unavailable", response=response_mock)
            
        mock_webpush.side_effect = side_effect
        
        delivery = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.subscription,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        
        res = send_web_push_delivery(delivery.id)
        self.assertEqual(res, "SKIPPED/ALREADY_FINALIZED")
        
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebPushDelivery.StatusChoices.SENT)
        
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.failure_count, 0)
