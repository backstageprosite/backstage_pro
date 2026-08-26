import json
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band
CustomUser = get_user_model()

class WebPushServiceWorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.producer = CustomUser.objects.create_user(
            username='produtor@example.com',
            email='produtor@example.com',
            password='password123',
            role='PRODUCER'
        )
        cls.band1 = Band.objects.create(name='Banda Teste', slug='banda-teste', is_active=True)
        cls.producer.band = cls.band1
        cls.producer.save()

        cls.band2 = Band.objects.create(name='Outra Banda', slug='outra-banda', is_active=True)

    def test_band_service_worker_contains_listeners(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        self.assertIn('self.addEventListener("push"', content)
        self.assertIn('self.addEventListener("notificationclick"', content)

    def test_admin_service_worker_does_not_contain_listeners(self):
        url = reverse('admin_painel:admin_sw')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        self.assertNotIn('self.addEventListener("push"', content)
        self.assertNotIn('self.addEventListener("notificationclick"', content)

    def test_headers_and_security(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        self.assertEqual(response['Content-Type'], 'application/javascript; charset=utf-8')
        self.assertEqual(response['Cache-Control'], 'no-cache, no-store, must-revalidate')
        self.assertEqual(response['Service-Worker-Allowed'], f'/{self.band1.slug}/')

    def test_injected_constants_band1(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        # Check serialization
        expected_slug = json.dumps(self.band1.slug)
        expected_scope = json.dumps(f"/{self.band1.slug}/")
        expected_name = json.dumps(self.band1.name.strip())
        expected_notifications_url = json.dumps(reverse('notifications_list', kwargs={'band_slug': self.band1.slug}))
        
        self.assertIn(f'const SW_VERSION = {json.dumps("backstage-" + self.band1.slug + "-v4")};', content)
        self.assertIn(f'const BAND_SLUG = {expected_slug};', content)
        self.assertIn(f'const BAND_SCOPE = {expected_scope};', content)
        self.assertIn(f'const BAND_NAME = {expected_name};', content)
        self.assertIn(f'const NOTIFICATIONS_URL = {expected_notifications_url};', content)

    def test_injected_constants_band2(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band2.slug})
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        expected_slug = json.dumps(self.band2.slug)
        expected_scope = json.dumps(f"/{self.band2.slug}/")
        
        self.assertIn(f'const SW_VERSION = {json.dumps("backstage-" + self.band2.slug + "-v4")};', content)
        self.assertIn(f'const BAND_SLUG = {expected_slug};', content)
        self.assertIn(f'const BAND_SCOPE = {expected_scope};', content)

    def test_vapid_and_subscription_data_absent(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        # Must not contain private keys or user specific data
        self.assertNotIn('VAPID_PRIVATE_KEY', content)
        self.assertNotIn('VAPID_PUBLIC_KEY', content)
        self.assertNotIn('p256dh', content)
        self.assertNotIn('auth', content)
        self.assertNotIn('endpoint', content)

    def test_code_logic_presence(self):
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        self.assertIn('event.waitUntil', content)
        self.assertIn('self.registration.showNotification', content)
        self.assertIn('event.notification.close()', content)
        self.assertIn('clients.matchAll', content)
        self.assertIn('clients.openWindow', content)
        self.assertIn('self.location.origin', content)
        self.assertIn('url.pathname.startsWith(BAND_SCOPE)', content)
        self.assertIn('return NOTIFICATIONS_URL', content) # Fallback logic

    def test_no_side_effects_on_get(self):
        from core.models import WebPushSubscription, Notification
        from django.db.models import signals
        
        pre_sub_count = WebPushSubscription.objects.count()
        pre_notif_count = Notification.objects.count()
        
        url = reverse('band_sw', kwargs={'band_slug': self.band1.slug})
        response = self.client.get(url)
        
        self.assertEqual(WebPushSubscription.objects.count(), pre_sub_count)
        self.assertEqual(Notification.objects.count(), pre_notif_count)
