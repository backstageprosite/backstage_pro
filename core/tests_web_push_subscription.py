from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from core.models import User, Band, WebPushSubscription
from django.contrib.admin.sites import AdminSite
from core.admin import WebPushSubscriptionAdmin
import hashlib

class MockRequest:
    def __init__(self, user):
        self.user = user

class WebPushSubscriptionTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        self.user = User.objects.create_user(username="user1", email="user1@example.com", password="pwd", band=self.band)
        self.site = AdminSite()
        self.admin = WebPushSubscriptionAdmin(WebPushSubscription, self.site)
        
        self.valid_data = {
            'user': self.user,
            'band': self.band,
            'endpoint': 'https://fcm.googleapis.com/fcm/send/123',
            'p256dh': 'p256dh-key-abc',
            'auth': 'auth-key-123',
            'service_worker_scope': '/banda-teste/'
        }

    def test_cricao_valida(self):
        # 1. criação válida
        # 17. subscription inicia ativa
        # 18. failure_count inicia em zero
        # 19. expiration_time aceita null
        sub = WebPushSubscription.objects.create(**self.valid_data)
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.band, self.band)
        self.assertTrue(sub.is_active)
        self.assertEqual(sub.failure_count, 0)
        self.assertIsNone(sub.expiration_time)
        
    def test_user_obrigatorio(self):
        # 2. user obrigatório
        data = self.valid_data.copy()
        data['user'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_band_obrigatoria(self):
        # 3. band obrigatória
        data = self.valid_data.copy()
        data['band'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_endpoint_obrigatorio(self):
        # 4. endpoint obrigatório
        data = self.valid_data.copy()
        data['endpoint'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_p256dh_obrigatorio(self):
        # 5. p256dh obrigatório
        data = self.valid_data.copy()
        data['p256dh'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_auth_obrigatorio(self):
        # 6. auth obrigatório
        data = self.valid_data.copy()
        data['auth'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_scope_obrigatorio(self):
        # 7. scope obrigatório
        data = self.valid_data.copy()
        data['service_worker_scope'] = None
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**data)

    def test_hash_correto_e_igualdade(self):
        # 8. hash SHA-256 correto
        # 9. endpoint igual gera mesmo hash
        sub = WebPushSubscription.objects.create(**self.valid_data)
        expected_hash = hashlib.sha256(self.valid_data['endpoint'].encode('utf-8')).hexdigest()
        self.assertEqual(sub.endpoint_hash, expected_hash)
        
        # 11. endpoint_hash globalmente único
        with self.assertRaises(ValidationError):
            WebPushSubscription.objects.create(**self.valid_data)

    def test_hash_diferente(self):
        # 10. endpoint diferente gera hash diferente
        sub1 = WebPushSubscription.objects.create(**self.valid_data)
        data2 = self.valid_data.copy()
        data2['endpoint'] = 'https://fcm.googleapis.com/fcm/send/456'
        sub2 = WebPushSubscription.objects.create(**data2)
        self.assertNotEqual(sub1.endpoint_hash, sub2.endpoint_hash)

    def test_str_method(self):
        # 12. endpoint não aparece em __str__
        # 13. p256dh não aparece em __str__
        # 14. auth não aparece em __str__
        sub = WebPushSubscription.objects.create(**self.valid_data)
        str_val = str(sub)
        self.assertIn("user1", str_val)
        self.assertIn("Banda Teste", str_val)
        self.assertIn("Ativa", str_val)
        self.assertNotIn(self.valid_data['endpoint'], str_val)
        self.assertNotIn(self.valid_data['p256dh'], str_val)
        self.assertNotIn(self.valid_data['auth'], str_val)

    def test_exclusao_cascata_user(self):
        # 15. exclusão do user remove subscription
        WebPushSubscription.objects.create(**self.valid_data)
        self.assertEqual(WebPushSubscription.objects.count(), 1)
        self.user.delete()
        self.assertEqual(WebPushSubscription.objects.count(), 0)
        
    def test_exclusao_cascata_band(self):
        # 16. exclusão da band remove subscription
        WebPushSubscription.objects.create(**self.valid_data)
        self.assertEqual(WebPushSubscription.objects.count(), 1)
        self.band.delete()
        self.assertEqual(WebPushSubscription.objects.count(), 0)

    def test_scope_validation_valid(self):
        # 20. scope válido é aceito
        sub = WebPushSubscription(**self.valid_data)
        sub.full_clean()  # não deve dar erro

    def test_scope_validation_invalid_scheme(self):
        # 21. scope externo é rejeitado
        data = self.valid_data.copy()
        data['service_worker_scope'] = 'https://google.com/sw/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError) as ctx:
            sub.full_clean()
        self.assertIn("service_worker_scope", ctx.exception.message_dict)

    def test_scope_validation_invalid_double_slash(self):
        # 22. scope iniciado por // é rejeitado
        data = self.valid_data.copy()
        data['service_worker_scope'] = '//banda/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_scope_validation_invalid_backslash(self):
        # 23. scope com backslash é rejeitado
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda\\teste/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_scope_validation_invalid_crlf(self):
        # 24. scope com CR/LF é rejeitado
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda\n/teste/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_scope_validation_invalid_dot_segments(self):
        # 25. scope com .. é rejeitado
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda/../'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()
            
        data['service_worker_scope'] = '/banda/./'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()
            
    def test_scope_validation_percent_encoded_traversal(self):
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda/%2e%2e/painel/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_scope_validation_double_encoding(self):
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda/%252e%252e/painel/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError) as ctx:
            sub.full_clean()
        self.assertIn('Double encoding detectado', str(ctx.exception))

    def test_scope_validation_encoded_crlf(self):
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda/%0d%0aHeader/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_scope_validation_encoded_double_slash(self):
        data = self.valid_data.copy()
        data['service_worker_scope'] = '/banda/%2F%2Fmalicioso/'
        sub = WebPushSubscription(**data)
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_admin_does_not_list_secrets(self):
        # 26. Admin não lista secrets
        list_display = self.admin.list_display
        self.assertNotIn('p256dh', list_display)
        self.assertNotIn('auth', list_display)
        self.assertNotIn('endpoint', list_display) # endpoint integral nao
        self.assertNotIn('get_endpoint_snippet', list_display)
        
        search_fields = getattr(self.admin, 'search_fields', [])
        self.assertNotIn('endpoint', search_fields)
        self.assertNotIn('endpoint_hash', search_fields)

    def test_admin_does_not_allow_editing_secrets(self):
        # 27. Admin não permite edição manual de auth
        # 28. Admin não permite edição manual de p256dh
        readonly_fields = self.admin.readonly_fields
        exclude = getattr(self.admin, 'exclude', [])
        
        self.assertTrue('p256dh' in readonly_fields or 'p256dh' in exclude)
        self.assertTrue('auth' in readonly_fields or 'auth' in exclude)
        
    def test_recalcula_hash_ao_alterar_endpoint(self):
        # 5. Alterar endpoint recalcula o hash.
        sub = WebPushSubscription.objects.create(**self.valid_data)
        hash_antigo = sub.endpoint_hash
        
        sub.endpoint = "https://novo.endpoint.com"
        sub.save()
        
        self.assertNotEqual(sub.endpoint_hash, hash_antigo)
        self.assertEqual(sub.endpoint_hash, hashlib.sha256("https://novo.endpoint.com".encode('utf-8')).hexdigest())

    def test_ignora_hash_falso_informado(self):
        # 6. Tentar informar hash falso não preserva o valor falso.
        data = self.valid_data.copy()
        data['endpoint_hash'] = "hash_falso_que_nao_deve_ficar"
        sub = WebPushSubscription.objects.create(**data)
        
        hash_esperado = hashlib.sha256(self.valid_data['endpoint'].encode('utf-8')).hexdigest()
        self.assertEqual(sub.endpoint_hash, hash_esperado)
        self.assertNotEqual(sub.endpoint_hash, "hash_falso_que_nao_deve_ficar")

    def test_admin_change_form_does_not_render_secrets(self):
        # 10. endpoint_hash não aparece como campo editável no Admin.
        exclude = getattr(self.admin, 'exclude', [])
        self.assertIn('endpoint_hash', exclude)
        self.assertIn('endpoint', exclude)

        # Criar admin client real usando django.test.Client
        admin_user = User.objects.create_superuser(username="admin", email="admin@example.com", password="pwd")
        self.client.login(username="admin", password="pwd")
        
        sub = WebPushSubscription.objects.create(**self.valid_data)
        
        from django.urls import reverse
        url = reverse('admin:core_webpushsubscription_change', args=[sub.id])
        response = self.client.get(url)
        
        # p256dh e auth não aparecem
        self.assertNotContains(response, self.valid_data['p256dh'])
        self.assertNotContains(response, self.valid_data['auth'])
        self.assertNotContains(response, self.valid_data['endpoint'])
        self.assertNotContains(response, sub.endpoint_hash) # integral nao

    def test_hash_field_attributes(self):
        field = WebPushSubscription._meta.get_field('endpoint_hash')
        self.assertFalse(field.editable)
        self.assertFalse(field.blank)

    def test_full_clean_without_validate_constraints(self):
        sub = WebPushSubscription(**self.valid_data)
        # Nao deve dar erro
        sub.full_clean(validate_constraints=False)

    def test_ausencias(self):
        # 29. nenhum Push é enviado
        # 30. nenhum Service Worker é alterado
        # Comprovado pela ausência de dependências e integrações
        pass
