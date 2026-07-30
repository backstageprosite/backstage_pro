from django.test import TestCase
from core.models import Band, User, Show, Notification
from core.services.notifications import (
    validate_target_url, create_notification, notify_band_users,
    get_unread_notifications, get_recent_notifications,
    mark_notification_as_read, mark_all_notifications_as_read
)

class NotificationServicesTests(TestCase):
    def setUp(self):
        self.band_a = Band.objects.create(name='Banda A', slug='banda-a', is_active=True)
        self.band_b = Band.objects.create(name='Banda B', slug='banda-b', is_active=True)
        
        self.prod_a = User.objects.create_user(username='pro_a', email='pa@t.c', password='123', role='PRODUTOR', band=self.band_a, is_active=True)
        self.int_a = User.objects.create_user(username='int_a', email='ia@t.c', password='123', role='INTEGRANTE', band=self.band_a, is_active=True)
        self.inativo_a = User.objects.create_user(username='ina_a', email='na@t.c', password='123', role='INTEGRANTE', band=self.band_a, is_active=False)
        self.sem_papel_a = User.objects.create_user(username='sem_a', email='sa@t.c', password='123', role='ROADIE', band=self.band_a, is_active=True)
        
        self.prod_b = User.objects.create_user(username='pro_b', email='pb@t.c', password='123', role='PRODUTOR', band=self.band_b, is_active=True)
        self.sem_banda = User.objects.create_user(username='sem_b', email='sb@t.c', password='123', role='PRODUTOR', is_active=True)
        self.admin = User.objects.create_superuser(username='admin', email='ad@t.c', password='123')
        
        self.show_a = Show.objects.create(title='Show A', band=self.band_a)
        self.show_b = Show.objects.create(title='Show B', band=self.band_b)

    # 1 a 11: validate_target_url
    def test_01_url_valida(self):
        self.assertTrue(validate_target_url('/banda-a/', 'banda-a'))
        self.assertTrue(validate_target_url('/banda-a/calendario/', 'banda-a'))

    def test_02_url_maliciosa_https(self):
        self.assertFalse(validate_target_url('https://malicioso.com/', 'banda-a'))

    def test_03_url_maliciosa_http(self):
        self.assertFalse(validate_target_url('http://malicioso.com/', 'banda-a'))

    def test_04_url_maliciosa_protocol_relative(self):
        self.assertFalse(validate_target_url('//malicioso.com/', 'banda-a'))
        self.assertFalse(validate_target_url('/banda-a/%2F%2Fmalicioso.com/', 'banda-a'))

    def test_05_url_maliciosa_javascript(self):
        self.assertFalse(validate_target_url('javascript:alert(1)', 'banda-a'))
        self.assertFalse(validate_target_url('data:text/html,teste', 'banda-a'))

    def test_06_url_backslash(self):
        self.assertFalse(validate_target_url('\\dannielvieira\\calendario/', 'banda-a'))

    def test_07_url_path_traversal_simples(self):
        self.assertFalse(validate_target_url('/banda-a/../painel/', 'banda-a'))

    def test_08_url_path_traversal_percent(self):
        self.assertFalse(validate_target_url('/banda-a/%2e%2e/painel/', 'banda-a'))

    def test_09_url_path_traversal_double_percent(self):
        self.assertFalse(validate_target_url('/banda-a/%252e%252e/painel/', 'banda-a'))

    def test_10_url_sem_barra(self):
        self.assertFalse(validate_target_url('caminho-sem-barra', 'banda-a'))

    def test_11_url_crlf(self):
        self.assertFalse(validate_target_url('/banda-a/\r\nHeader: teste', 'banda-a'))

    # 12 a 20: create_notification rules (actor, related_show, limits, clean)
    def test_12_create_actor_outra_banda_rejeitado(self):
        with self.assertRaisesMessage(ValueError, "O ator é inválido."):
            create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e', actor=self.prod_b)

    def test_13_create_actor_inativo_rejeitado(self):
        with self.assertRaisesMessage(ValueError, "O ator é inválido."):
            create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e', actor=self.inativo_a)

    def test_14_create_actor_sem_banda_rejeitado(self):
        with self.assertRaisesMessage(ValueError, "O ator é inválido."):
            create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e', actor=self.sem_banda)

    def test_15_create_actor_admin_e_valido(self):
        n, c = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_ad', actor=self.admin)
        self.assertTrue(c)

    def test_16_create_related_show_outra_banda_rejeitado(self):
        with self.assertRaisesMessage(ValueError, "O show relacionado não pertence à banda."):
            create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e', related_show=self.show_b)

    def test_17_create_related_show_none_valido(self):
        n, c = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_no_s')
        self.assertTrue(c)

    def test_18_create_cleansing(self):
        n, c = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T\r\n', 'Msg\nOK', '/banda-a/', 'e_cl')
        self.assertNotIn('\r', n.title)
        self.assertNotIn('\n', n.title)
        self.assertIn('\n', n.message)

    def test_19_create_html_fica_texto_puro(self):
        n, c = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', '<script>alert(1)</script>', 'M', '/banda-a/', 'e_ht')
        self.assertEqual(n.title, '<script>alert(1)</script>')

    def test_20_create_idempotencia_duplicata(self):
        n1, c1 = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_dup')
        n2, c2 = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_dup')
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(n1, n2)

    # 21 a 23: notify_band_users
    def test_21_notify_banda_inativa(self):
        self.band_a.is_active = False
        self.band_a.save()
        c = notify_band_users(self.band_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_bi')
        self.assertEqual(c, 0)

    def test_22_notify_apenas_perfis_validos(self):
        # band_a tem prod_a, int_a, inativo_a, sem_papel_a. Apenas 2 devem receber.
        c = notify_band_users(self.band_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_nv')
        self.assertEqual(c, 2)
        
    def test_23_notify_actor_recebe(self):
        # Se prod_a for actor, ele também entra nos recipients e recebe notificação.
        c = notify_band_users(self.band_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'e_na', actor=self.prod_a)
        self.assertEqual(c, 2)
        n = Notification.objects.get(recipient=self.prod_a, event_key='e_na')
        self.assertEqual(n.actor, self.prod_a)

    # 24 a 30: Consultas
    def test_24_unread_filtra_certo(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'u1')
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'u2')
        create_notification(self.band_b, self.prod_b, 'NEW_SHOW', 'T', 'M', '/banda-b/', 'u3')
        qs = get_unread_notifications(self.prod_a, self.band_a)
        self.assertEqual(qs.count(), 2)

    def test_25_recent_limit_zero(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'r1')
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'r2')
        qs = get_recent_notifications(self.prod_a, self.band_a, limit=0)
        self.assertEqual(qs.count(), 1) # limite minimo é 1

    def test_26_recent_limit_negativo(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'r3')
        qs = get_recent_notifications(self.prod_a, self.band_a, limit=-5)
        self.assertEqual(qs.count(), 1)

    def test_27_recent_limit_excessivo(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'r4')
        qs = get_recent_notifications(self.prod_a, self.band_a, limit=500)
        self.assertLessEqual(qs.count(), 100) # O queryset estara truncado, mas no teste soh tem 1 de qq forma. O teste real confere se limit truncado para 100 nao dá erro.

    def test_28_recent_limit_nao_inteiro(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'r5')
        qs = get_recent_notifications(self.prod_a, self.band_a, limit='abs')
        self.assertEqual(qs.count(), 1) # fallback pra 10

    def test_29_mark_as_read(self):
        n, _ = create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'm1')
        res = mark_notification_as_read(n.id, self.prod_a, self.band_a)
        self.assertTrue(res)
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        # Nao marca de outro cara
        res2 = mark_notification_as_read(n.id, self.int_a, self.band_a)
        self.assertFalse(res2)

    def test_30_mark_all(self):
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'ma1')
        create_notification(self.band_a, self.prod_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'ma2')
        create_notification(self.band_a, self.int_a, 'NEW_SHOW', 'T', 'M', '/banda-a/', 'ma3')
        mark_all_notifications_as_read(self.prod_a, self.band_a)
        self.assertEqual(get_unread_notifications(self.prod_a, self.band_a).count(), 0)
        self.assertEqual(get_unread_notifications(self.int_a, self.band_a).count(), 1)

    def test_31_event_choices(self):
        choices_keys = [k for k, v in Notification.EVENT_CHOICES]
        self.assertEqual(len(set(choices_keys)), len(choices_keys), "Event choices devem ser únicas")
        for k, v in Notification.EVENT_CHOICES:
            self.assertTrue(bool(v), f"Label do evento {k} não pode ser vazio")
        # Ensure minimal expected choices exist (not strictly exact count, but inclusive)
        expected_minimum = {'NEW_SHOW', 'SHOW_CANCELLED', 'SHOW_DATE_CHANGED', 'SHOW_START_TIME_CHANGED'}
        self.assertTrue(expected_minimum.issubset(set(choices_keys)))
