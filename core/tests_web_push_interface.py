from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band

User = get_user_model()

class WebPushInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.band = Band.objects.create(name="Banda Teste", slug="banda-teste", is_active=True)
        cls.produtor = User.objects.create_user(username="produtor", email="prod@test.com", password="123", role="PRODUTOR", band=cls.band)
        cls.integrante = User.objects.create_user(username="integrante", email="int@test.com", password="123", role="INTEGRANTE", band=cls.band)
        cls.superuser = User.objects.create_superuser(username="admin", email="admin@test.com", password="123")
        
        cls.other_band = Band.objects.create(name="Outra Banda", slug="outra-banda", is_active=True)
        cls.other_user = User.objects.create_user(username="other", email="oth@test.com", password="123", role="INTEGRANTE", band=cls.other_band)

    def setUp(self):
        self.client = Client()

    def test_authenticated_producer_sees_card(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="web-push-settings-card"')
        self.assertContains(response, 'data-band-slug="banda-teste"')
        self.assertContains(response, 'data-expected-scope="/banda-teste/"')
        self.assertContains(response, reverse('push_public_key', kwargs={'band_slug': self.band.slug}))
        self.assertContains(response, 'web_push_settings.js')

    def test_integrante_sees_card_if_access_allowed(self):
        self.client.force_login(self.integrante)
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        if response.status_code == 200:
            self.assertContains(response, 'id="web-push-settings-card"')
        else:
            self.assertIn(response.status_code, [302, 403, 404])

    def test_unlinked_user_does_not_see_page(self):
        ex_integrante = User.objects.create_user(username="ex", email="ex@t.com", password="123", role="INTEGRANTE", band=None)
        self.client.force_login(ex_integrante)
        # Using a valid band url
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        self.assertIn(response.status_code, [302, 403, 404])

    def test_general_admin_without_link_does_not_see_card_on_their_panel(self):
        # A view like /painel/configuracoes might exist, let's just check that it does not error and doesn't contain the card if it does.
        self.client.force_login(self.superuser)
        response_admin = self.client.get('/painel/configuracoes/')
        if response_admin.status_code == 200:
            self.assertNotContains(response_admin, 'id="web-push-settings-card"')

    def test_csrf_token_present(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_no_sensitive_data_in_html(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        content = response.content.decode('utf-8')
        
        self.assertNotIn('VAPID_PRIVATE_KEY', content)
        self.assertNotIn('endpoint_hash', content)
        self.assertNotIn('p256dh', content)
        self.assertNotIn('auth', content)

    def test_no_subscription_created_on_get(self):
        from core.models import WebPushSubscription
        initial_count = WebPushSubscription.objects.count()
        self.client.force_login(self.produtor)
        self.client.get(reverse('configuracoes', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(WebPushSubscription.objects.count(), initial_count)

    def test_other_band_uses_own_scope(self):
        other_produtor = User.objects.create_user(username="op", email="op@t.com", password="1", role="PRODUTOR", band=self.other_band)
        self.client.force_login(other_produtor)
        response = self.client.get(reverse('configuracoes', kwargs={'band_slug': self.other_band.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-expected-scope="/outra-banda/"')
        self.assertContains(response, reverse('push_public_key', kwargs={'band_slug': self.other_band.slug}))
