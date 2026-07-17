import json
import base64
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from core.models import Band, WebPushSubscription
from core.services.web_push_subscriptions import SubscriptionNotFoundError

User = get_user_model()

VALID_P256DH = "B" + "A" * 86 # Decodifica para 0x04 + 64 zeros (65 bytes)
VALID_AUTH = "A" * 22 # 16 bytes decoded
VALID_ENDPOINT = "https://fcm.googleapis.com/fcm/send/fake-endpoint-test"

class WebPushEndpointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.band = Band.objects.create(name="Banda Teste", slug="banda-teste", is_active=True)
        cls.band_inactive = Band.objects.create(name="Banda Inativa", slug="banda-inativa", is_active=False)
        
        cls.produtor = User.objects.create_user(username="produtor", email="prod@test.com", password="123", role="PRODUTOR", band=cls.band)
        cls.integrante = User.objects.create_user(username="integrante", email="int@test.com", password="123", role="INTEGRANTE", band=cls.band)
        
        cls.user_inactive = User.objects.create_user(username="inativo", email="ina@test.com", password="123", role="PRODUTOR", band=cls.band, is_active=False)
        cls.ex_integrante = User.objects.create_user(username="ex", email="ex@test.com", password="123", role="INTEGRANTE", band=None)
        cls.superuser = User.objects.create_superuser(username="admin", email="admin@test.com", password="123")
        
        cls.other_band = Band.objects.create(name="Outra Banda", slug="outra-banda", is_active=True)
        cls.other_user = User.objects.create_user(username="other", email="oth@test.com", password="123", role="INTEGRANTE", band=cls.other_band)
        
    def setUp(self):
        self.client = Client()
        self.client.force_login(self.produtor)
        # Obter CSRF
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.csrf_token = response.cookies.get('csrftoken').value if 'csrftoken' in response.cookies else 'fake_csrf'
        
    def _post(self, url_name, data=None, band_slug=None, content_type='application/json'):
        slug = band_slug or self.band.slug
        url = reverse(url_name, kwargs={'band_slug': slug})
        kwargs = {}
        if data is not None:
            if content_type == 'application/json':
                kwargs['data'] = json.dumps(data)
            else:
                kwargs['data'] = data
                
        return self.client.post(
            url,
            content_type=content_type,
            HTTP_X_CSRFTOKEN=self.csrf_token,
            **kwargs
        )
        
    def get_valid_payload(self, endpoint=VALID_ENDPOINT):
        return {
            "endpoint": endpoint,
            "keys": {
                "p256dh": VALID_P256DH,
                "auth": VALID_AUTH
            }
        }

    # ==========================
    # 1. AUTORIZAÇÃO E METODOS
    # ==========================
    def test_autorizacao_completa(self):
        url_status = reverse('push_subscription_status', kwargs={'band_slug': self.band.slug})
        
        # Anônimo: 401
        self.client.logout()
        resp = self.client.post(url_status, data="{}", content_type='application/json')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        # Inativo: 403
        self.client.force_login(self.user_inactive)
        resp = self._post('push_subscription_status', data={})
        self.assertIn(resp.status_code, [401, 403])
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        # Banda inexistente: 404
        self.client.force_login(self.produtor)
        resp = self._post('push_subscription_status', data={}, band_slug='nao-existe')
        self.assertEqual(resp.status_code, 404)
        
        # Sem vínculo / Outra banda: 404
        resp = self._post('push_subscription_status', data={}, band_slug=self.other_band.slug)
        self.assertEqual(resp.status_code, 404)
        
        # Ex-integrante: 404
        self.client.force_login(self.ex_integrante)
        resp = self._post('push_subscription_status', data={})
        self.assertEqual(resp.status_code, 404)
        
        # Produtor / Integrante ativos permitidos
        self.client.force_login(self.produtor)
        resp = self._post('push_subscription_status', data={"endpoint": "a"}) # Endpoint válido na string, não existe no banco
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"subscribed": False})
        
        # Superuser sem vínculo: 404
        self.client.force_login(self.superuser)
        resp = self._post('push_subscription_status', data={})
        self.assertEqual(resp.status_code, 404)
        
    # ==========================
    # 2. HTTP METHODS
    # ==========================
    def test_http_methods(self):
        self.client.force_login(self.produtor)
        
        # GET em status
        resp = self.client.get(reverse('push_subscription_status', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json(), {'error': 'method_not_allowed'})
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        # GET em inscrever
        resp = self.client.get(reverse('push_subscribe', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json(), {'error': 'method_not_allowed'})
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        # GET em desinscrever
        resp = self.client.get(reverse('push_unsubscribe', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json(), {'error': 'method_not_allowed'})
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        # POST em chave-publica
        resp = self.client.post(reverse('push_public_key', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json(), {'error': 'method_not_allowed'})
        self.assertEqual(resp['Cache-Control'], 'no-store')

    # ==========================
    # 2. CHAVE PÚBLICA (VAPID)
    # ==========================
    def test_vapid_validation(self):
        url = reverse('push_public_key', kwargs={'band_slug': self.band.slug})
        
        # 87 char rejects se não for base64
        with override_settings(VAPID_PUBLIC_KEY='A'*87):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 503)
            
        # Base64 válido de 64 bytes
        # 64 bytes = 86 chars approx
        with override_settings(VAPID_PUBLIC_KEY="B" + "A"*84):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 503)
            
        # Começando com 0x03
        with override_settings(VAPID_PUBLIC_KEY="A" + "A"*86): # 'A' -> 0x00, but 'A' is not 0x04. 'B' -> 0x04
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 503)
            
        # Válida (0x04 no início, 65 bytes)
        with patch('core.push_views.load_vapid_configuration') as mock_load:
            from core.services.vapid_config import VapidConfiguration
            mock_load.return_value = VapidConfiguration(public_key=VALID_P256DH, private_key="dummy", subject="https://dummy")
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)

    # ==========================
    # 3. PARSER JSON & PAYLOAD
    # ==========================
    def test_json_parser(self):
        # Empty body
        resp = self.client.post(
            reverse('push_subscribe', kwargs={'band_slug': self.band.slug}),
            data="", content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf_token
        )
        self.assertIn(resp.status_code, [400, 415])
        
        # Array
        resp = self._post('push_subscribe', data=[])
        self.assertEqual(resp.status_code, 400)
        
        # String
        resp = self._post('push_subscribe', data="notjson")
        self.assertEqual(resp.status_code, 400)
        
        # Missing auth or extra keys
        payload = self.get_valid_payload()
        payload['extra'] = 1
        resp = self._post('push_subscribe', data=payload)
        self.assertEqual(resp.status_code, 400)
        
        payload = self.get_valid_payload()
        del payload['keys']['auth']
        resp = self._post('push_subscribe', data=payload)
        self.assertEqual(resp.status_code, 400)
        
        payload = self.get_valid_payload()
        payload['keys'] = None
        resp = self._post('push_subscribe', data=payload)
        self.assertEqual(resp.status_code, 400)

    # ==========================
    # 4. RESOLUÇÃO PÓS-INTEGRITYERROR E CONFLITO
    # ==========================
    def test_concorrencia_e_conflitos(self):
        # 1. Conflito Normal (sem IntegrityError) - Criado por outro usuário
        sub1 = WebPushSubscription.objects.create(
            user=self.other_user, band=self.other_band, service_worker_scope=f"/{self.other_band.slug}/",
            endpoint="https://push.example/conflict", p256dh="old", auth="old"
        )
        payload = self.get_valid_payload("https://push.example/conflict")
        resp = self._post('push_subscribe', data=payload)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'subscription_conflict')
        
        # 2. IntegrityError simulado, mesmo dono
        payload2 = self.get_valid_payload("https://push.example/integ-mesmo")
        WebPushSubscription.objects.create(
            user=self.produtor, band=self.band, service_worker_scope=f"/{self.band.slug}/",
            endpoint="https://push.example/integ-mesmo", p256dh="old", auth="old"
        )
        with patch('core.push_views.web_push_subscriptions.register_or_update_subscription', side_effect=IntegrityError):
            resp = self._post('push_subscribe', data=payload2)
            self.assertEqual(resp.status_code, 200) # Updated idempotently
            
        # 3. IntegrityError simulado, outro dono
        payload3 = self.get_valid_payload("https://push.example/integ-outro")
        WebPushSubscription.objects.create(
            user=self.other_user, band=self.other_band, service_worker_scope=f"/{self.other_band.slug}/",
            endpoint="https://push.example/integ-outro", p256dh="old", auth="old"
        )
        with patch('core.push_views.web_push_subscriptions.register_or_update_subscription', side_effect=IntegrityError):
            resp = self._post('push_subscribe', data=payload3)
            self.assertEqual(resp.status_code, 409)
            
        # 4. IntegrityError simulado, mas registro desaparece
        with patch('core.push_views.web_push_subscriptions.register_or_update_subscription', side_effect=IntegrityError):
            resp = self._post('push_subscribe', data=self.get_valid_payload("https://push.example/desaparecido"))
            self.assertEqual(resp.status_code, 409) # Capturou o SubscriptionNotFoundError

    # ==========================
    # 5. CSRF JSON RESPONSES
    # ==========================
    def test_csrf_failure_view(self):
        # Removendo CSRF Token para causar falha
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.produtor)
        
        resp = csrf_client.post(
            reverse('push_subscribe', kwargs={'band_slug': self.band.slug}),
            data=json.dumps(self.get_valid_payload()),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json(), {"error": "csrf_failed"})
        self.assertEqual(resp['Cache-Control'], 'no-store')
        self.assertNotIn('Set-Cookie', resp.headers)

    # ==========================
    # 6. CACHE E LOGS
    # ==========================
    def test_logs_and_cache(self):
        # Validação inválida (400)
        resp = self._post('push_subscribe', data={"invalid": "payload"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp['Cache-Control'], 'no-store')
        
        with self.assertLogs(level='INFO') as log:
            logging.getLogger().info("Dummy log")
            payload = self.get_valid_payload("https://push.example/test-logs")
            self._post('push_subscribe', data=payload)
            for msg in log.output:
                self.assertNotIn("test-logs", msg)
                self.assertNotIn(VALID_P256DH, msg)
                self.assertNotIn(VALID_AUTH, msg)

    # ==========================
    # 7. UNSUBSCRIBE e STATUS
    # ==========================
    def test_status_e_unsubscribe(self):
        payload = self.get_valid_payload("https://push.example/mystatus")
        self._post('push_subscribe', data=payload)
        
        resp = self._post('push_subscription_status', data={"endpoint": "https://push.example/mystatus"})
        self.assertEqual(resp.json(), {"subscribed": True})
        
        # Unsubscribe
        resp = self._post('push_unsubscribe', data={"endpoint": "https://push.example/mystatus"})
        self.assertEqual(resp.json(), {"unsubscribed": True})
        
        # Check status again
        resp = self._post('push_subscription_status', data={"endpoint": "https://push.example/mystatus"})
        self.assertEqual(resp.json(), {"subscribed": False})
        
        # Subscrição por terceiro
        self.client.logout()
        self.client.force_login(self.other_user)
        # Obter csrf da outra banda
        resp2 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.other_band.slug}))
        self.csrf_token = resp2.cookies.get('csrftoken').value if 'csrftoken' in resp2.cookies else 'fake_csrf'
        
        resp = self._post('push_unsubscribe', data={"endpoint": "https://push.example/mystatus"}, band_slug=self.other_band.slug)
        # A view the desinscrever não retorna 403 se o objeto for de outro usuário, ela simplesmente não faz nada e retorna 200 idempotente
        self.assertEqual(resp.status_code, 200)
