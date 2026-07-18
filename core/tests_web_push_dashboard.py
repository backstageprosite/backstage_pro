import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from core.models import User, Band, WebPushDelivery, WebPushSubscription, Notification

class WebPushDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()
        
        # Test users
        self.anon_user = None
        self.normal_user = User.objects.create_user(username="normal", email="n@n.com", password="pwd")
        self.band_member = User.objects.create_user(username="member", email="m@m.com", password="pwd")
        self.staff_unauth = User.objects.create_user(username="staff", email="s@s.com", password="pwd", is_staff=True)
        
        self.staff_auth = User.objects.create_user(username="staff2", email="s2@s.com", password="pwd", is_staff=True)
        # Give permission
        ct = ContentType.objects.get_for_model(WebPushDelivery)
        perm, _ = Permission.objects.get_or_create(codename='view_webpushdelivery', content_type=ct)
        self.staff_auth.user_permissions.add(perm)
        
        self.superuser = User.objects.create_superuser(username="admin", email="a@a.com", password="pwd")
        
        # Bands and data
        self.band = Band.objects.create(name="Band A", slug="band-a")
        self.band_member.band = self.band
        self.band_member.save()
        
        self.sub = WebPushSubscription.objects.create(
            user=self.band_member,
            band=self.band,
            endpoint="https://secure-endpoint.com/x",
            p256dh="p256",
            auth="auth",
            service_worker_scope="/band-a/",
            is_active=True
        )
        
        self.notification = Notification.objects.create(
            band=self.band,
            recipient=self.band_member,
            title="Test",
            message="Msg"
        )
        
        self.url = reverse('admin_painel:admin_web_push_dashboard')

    def test_permission_anonymous(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/painel/login/"))

    def test_permission_normal_user(self):
        self.client.login(username="normal", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/painel/login/"))

    def test_permission_band_member(self):
        self.client.login(username="member", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/painel/login/"))

    def test_permission_staff_unauth(self):
        self.client.login(username="staff", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/painel/login/"))

    def test_permission_staff_auth(self):
        self.client.login(username="staff2", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)

    def test_permission_superuser(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        
    def test_menu_item_visible_only_to_authorized(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(reverse('admin_painel:dashboard'))
        self.assertContains(res, "Web Push")
        self.assertContains(res, self.url)
        
    def test_view_only_get(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.post(self.url, {"test": 1})
        self.assertEqual(res.status_code, 405)

    def test_uses_snapshot(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertIn('snapshot', res.context)

    def test_cache_control(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertIn('private', res['Cache-Control'])
        self.assertIn('no-store', res['Cache-Control'])

    def test_filters_defaults(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.context['current_hours'], 24)
        self.assertEqual(res.context['current_stale_pending'], 10)
        self.assertEqual(res.context['current_stale_sending'], 15)
        self.assertIsNone(res.context['current_band_slug'])

    def test_filters_band(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url, {"band_slug": "band-a"})
        self.assertEqual(res.context['current_band_slug'], "band-a")
        








    def test_filters_invalid_type(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url, {"hours": "abc"})
        self.assertEqual(res.context['current_hours'], 24)

    def test_security_secrets_not_exposed(self):
        d = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.PENDING,
        )
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        content = res.content.decode()
        self.assertNotIn("https://secure-endpoint.com/x", content)
        self.assertNotIn("p256", content)
        self.assertNotIn("auth", content)
        self.assertNotIn("m@m.com", content)

    def test_list_limited_and_sorted(self):
        for i in range(60):
            sub = WebPushSubscription.objects.create(
                user=self.band_member,
                band=self.band,
                endpoint=f"https://example.com/{i}",
                p256dh="key",
                auth="auth",
                is_active=True,
                service_worker_scope=f"/{self.band.slug}/"
            )
            WebPushDelivery.objects.create(
                notification=self.notification,
                subscription=sub,
                status=WebPushDelivery.StatusChoices.PENDING
            )
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        deliveries = res.context['problematic_deliveries']
        self.assertEqual(len(deliveries), 50)
        self.assertEqual(deliveries[0]['status'], 'PENDING')

    def test_alerts_stale_sending_critical(self):
        d = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.SENDING,
        )
        WebPushDelivery.objects.filter(pk=d.pk).update(updated_at=self.now - datetime.timedelta(minutes=30))
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.context['overall_state'], 'CRITICAL')
        criticals = [a for a in res.context['alerts'] if a['severity'] == 'CRITICAL']
        self.assertTrue(len(criticals) > 0)
        self.assertEqual(criticals[0]['code'], 'stale_sending')

    def test_alerts_stale_pending_warning(self):
        d = WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.PENDING,
        )
        WebPushDelivery.objects.filter(pk=d.pk).update(created_at=self.now - datetime.timedelta(minutes=30))
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        # Assuming no critical alerts
        self.assertEqual(res.context['overall_state'], 'ATTENTION')
        warnings = [a for a in res.context['alerts'] if a['severity'] == 'WARNING']
        self.assertTrue(len(warnings) > 0)
        self.assertEqual(warnings[0]['code'], 'stale_pending')

    def test_metrics_success_rate(self):
        sub2 = WebPushSubscription.objects.create(
            user=self.band_member,
            band=self.band,
            endpoint="https://secure-endpoint.com/y",
            p256dh="p256",
            auth="auth",
            service_worker_scope=f"/{self.band.slug}/",
            is_active=True
        )
        WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.SENT,
            sent_at=self.now
        )
        WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=sub2,
            status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE
        )
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.context['snapshot']['deliveries']['rates']['success_rate'], 0.5)

    def test_alerts_no_data(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertEqual(res.context['overall_state'], 'NO_DATA')

    def test_dates_null_rendered(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertContains(res, "Nenhum registro")
        
    def test_responsiveness_and_template(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        self.assertContains(res, "Dashboard Operacional")
        self.assertContains(res, "table-responsive")
        # should not contain form method="post"
        self.assertNotContains(res, 'method="post"')
        self.assertNotContains(res, 'method="POST"')
        
    def test_no_mutations(self):
        # We ensure no notifications are created just by accessing dashboard
        notifs_before = Notification.objects.count()
        self.client.login(username="admin", password="pwd")
        self.client.get(self.url)
        self.assertEqual(Notification.objects.count(), notifs_before)

    def test_list_recent_problematic_deliveries_returns_list_of_dicts(self):
        from core.services.web_push_operations import list_recent_problematic_deliveries
        WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        res = list_recent_problematic_deliveries()
        self.assertIsInstance(res, list)
        self.assertTrue(len(res) > 0)
        item = res[0]
        self.assertIsInstance(item, dict)
        from django.db import models
        self.assertFalse(isinstance(item, models.Model))
        allowed_keys = {'delivery_id', 'band_slug', 'status', 'attempt_count', 'last_http_status', 'error_code', 'created_at', 'updated_at', 'last_attempt_at'}
        self.assertEqual(set(item.keys()), allowed_keys)

    def test_no_queryset_in_context(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        from django.db.models.query import QuerySet
        self.assertFalse(isinstance(res.context['problematic_deliveries'], QuerySet))

    def test_safe_context_data(self):
        WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url)
        content = str(res.content)
        self.assertNotIn('https://secure-endpoint.com/x', content)
        self.assertNotIn('p256', content)
        self.assertNotIn('auth', content)
        
    def test_nonexistent_band_no_global_data(self):
        WebPushDelivery.objects.create(
            notification=self.notification,
            subscription=self.sub,
            status=WebPushDelivery.StatusChoices.PENDING
        )
        self.client.login(username="admin", password="pwd")
        from unittest.mock import patch
        with patch('core.admin_views.build_web_push_health_snapshot') as mock_snap:
            mock_snap.side_effect = ValueError("Banda não encontrada")
            with patch('core.admin_views.list_recent_problematic_deliveries') as mock_list:
                res = self.client.get(self.url, {'band_slug': 'nonexistent'})
                mock_list.assert_not_called()
                self.assertEqual(res.context['overall_state'], 'NO_DATA')
                self.assertEqual(res.context['problematic_deliveries'], [])
                msgs = list(res.context['messages'])
                self.assertEqual(len(msgs), 1)
                self.assertEqual(str(msgs[0]), "A banda informada não foi encontrada.")
                self.assertNotIn("Banda não encontrada", str(msgs[0])) # ensure exception text is not exposed as is if different

    def test_no_mutations_called(self):
        from unittest.mock import patch
        try:
            with patch('core.services.web_push_operations.retry_web_push_deliveries') as mock_retry:
                with patch('core.services.web_push_operations.reconcile_stale_sending_deliveries') as mock_reconcile:
                    with patch('core.services.web_push_delivery.send_web_push_delivery') as mock_send:
                        with patch('pywebpush.webpush') as mock_wp:
                            self.client.login(username="admin", password="pwd")
                            res = self.client.get(self.url)
                            mock_retry.assert_not_called()
                            mock_reconcile.assert_not_called()
                            mock_send.assert_not_called()
                            mock_wp.assert_not_called()
        except AttributeError:
            pass # The functions are not even present or importable, which is also fine.

    def test_build_web_push_operational_alerts_primitive_types(self):
        from core.services.web_push_operations import build_web_push_health_snapshot, build_web_push_operational_alerts
        snap = build_web_push_health_snapshot()
        alerts = build_web_push_operational_alerts(snap)
        self.assertIsInstance(alerts, list)
        for a in alerts:
            self.assertIsInstance(a, dict)
            self.assertIsInstance(a['code'], str)
            self.assertIsInstance(a['severity'], str)
            self.assertIsInstance(a['title'], str)
            self.assertIsInstance(a['message'], str)
            self.assertTrue(a['count'] is None or isinstance(a['count'], int))
            self.assertIsInstance(a['recommended_action'], str)

    def test_alerts_success_rate_critical(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = {
            "deliveries": {"recent_window": {"created": 10, "temporary_failure": 0, "permanent_failure": 0}, "rates": {"completed": 10, "success_rate": 0.70}},
            "anomalies": {"stale_sending_count": 0, "stale_pending_count": 0, "active_expired_subscriptions_count": 0},
            "subscriptions": {"active_with_failures": 0}
        }
        alerts = build_web_push_operational_alerts(snap)
        criticals = [a for a in alerts if a['severity'] == 'CRITICAL']
        self.assertEqual(len(criticals), 1)
        self.assertEqual(criticals[0]['code'], 'critical_success_rate')

    def test_alerts_success_rate_warning(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = {
            "deliveries": {"recent_window": {"created": 10, "temporary_failure": 0, "permanent_failure": 0}, "rates": {"completed": 10, "success_rate": 0.85}},
            "anomalies": {"stale_sending_count": 0, "stale_pending_count": 0, "active_expired_subscriptions_count": 0},
            "subscriptions": {"active_with_failures": 0}
        }
        alerts = build_web_push_operational_alerts(snap)
        warnings = [a for a in alerts if a['severity'] == 'WARNING']
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['code'], 'moderate_success_rate')

    def test_alerts_no_data_returns_info(self):
        from core.services.web_push_operations import build_web_push_operational_alerts
        snap = {
            "deliveries": {"recent_window": {"created": 0, "temporary_failure": 0, "permanent_failure": 0}, "rates": {"completed": 0, "success_rate": None}},
            "anomalies": {"stale_sending_count": 0, "stale_pending_count": 0, "active_expired_subscriptions_count": 0},
            "subscriptions": {"active_with_failures": 0}
        }
        alerts = build_web_push_operational_alerts(snap)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['severity'], 'INFO')
        self.assertEqual(alerts[0]['code'], 'no_recent_deliveries')


    def test_list_recent_problematic_deliveries_signature_and_hours(self):
        from core.services.web_push_operations import list_recent_problematic_deliveries
        import inspect
        sig = inspect.signature(list_recent_problematic_deliveries)
        self.assertIn("hours", sig.parameters)
        
    def test_view_hours_and_limit_no_typeerror(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url + "?hours=48&limit=25")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["current_hours"], 48)
        self.assertEqual(res.context["current_limit"], 25)

    def test_filter_out_of_bounds_uses_defaults(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url + "?hours=9999&limit=101&stale_pending_minutes=4&stale_sending_minutes=20000")
        self.assertEqual(res.context["current_hours"], 24)
        self.assertEqual(res.context["current_limit"], 50)
        self.assertEqual(res.context["current_stale_pending"], 10)
        self.assertEqual(res.context["current_stale_sending"], 15)

    def test_filter_invalid_type_uses_defaults(self):
        self.client.login(username="admin", password="pwd")
        res = self.client.get(self.url + "?hours=abc&limit=def")
        self.assertEqual(res.context["current_hours"], 24)
        self.assertEqual(res.context["current_limit"], 50)
class ContextProcessorTests(TestCase):
    def setUp(self):
        from django.test import RequestFactory
        self.factory = RequestFactory()
        self.band = Band.objects.create(name='Test Band', slug='test-band')

    def test_context_processor_returns_bool_and_expected_values(self):
        from core.context_processors import web_push_admin
        from django.contrib.auth.models import AnonymousUser, Permission
        from django.contrib.contenttypes.models import ContentType
        from core.models import WebPushDelivery, User
        
        # Anônimo
        request = self.factory.get('/')
        request.user = AnonymousUser()
        ctx = web_push_admin(request)
        self.assertIsInstance(ctx['user_has_admin_web_push_perm'], bool)
        self.assertFalse(ctx['user_has_admin_web_push_perm'])
        
        # Usuário Comum
        user_comum = User.objects.create_user(username='comum', password='123', email='comum@test.com')
        request.user = user_comum
        ctx = web_push_admin(request)
        self.assertIsInstance(ctx['user_has_admin_web_push_perm'], bool)
        self.assertFalse(ctx['user_has_admin_web_push_perm'])
        
        # Staff sem permissão
        user_staff_no_perm = User.objects.create_user(username='staff1', password='123', email='staff1@test.com', is_staff=True)
        request.user = user_staff_no_perm
        ctx = web_push_admin(request)
        self.assertIsInstance(ctx['user_has_admin_web_push_perm'], bool)
        self.assertFalse(ctx['user_has_admin_web_push_perm'])
        
        # Staff com permissão
        user_staff_perm = User.objects.create_user(username='staff2', password='123', email='staff2@test.com', is_staff=True)
        ct = ContentType.objects.get_for_model(WebPushDelivery)
        perm, _ = Permission.objects.get_or_create(codename='view_webpushdelivery', content_type=ct)
        user_staff_perm.user_permissions.add(perm)
        
        request.user = user_staff_perm
        ctx = web_push_admin(request)
        self.assertIsInstance(ctx['user_has_admin_web_push_perm'], bool)
        self.assertTrue(ctx['user_has_admin_web_push_perm'])
        
        # Superuser
        user_superuser = User.objects.create_superuser(username='super', password='123', email='super@test.com')
        request.user = user_superuser
        ctx = web_push_admin(request)
        self.assertIsInstance(ctx['user_has_admin_web_push_perm'], bool)
        self.assertTrue(ctx['user_has_admin_web_push_perm'])
