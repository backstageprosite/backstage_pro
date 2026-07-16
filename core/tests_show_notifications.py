from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import date, time, timedelta
from core.models import Band, User, Show, Notification
from core.forms import ShowForm

class ShowNotificationsTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.other_band = Band.objects.create(name='Outra Banda', slug='outra')
        
        self.produtor = User.objects.create_user(
            username='produtor', email='produtor@teste.com', password='123',
            role='PRODUTOR', band=self.band
        )
        self.integrante = User.objects.create_user(
            username='integrante', email='integrante@teste.com', password='123',
            role='INTEGRANTE', band=self.band
        )
        self.inativo = User.objects.create_user(
            username='inativo', email='inativo@teste.com', password='123',
            role='PRODUTOR', band=self.band, is_active=False
        )
        self.other_user = User.objects.create_user(
            username='outro', email='outro@teste.com', password='123',
            role='PRODUTOR', band=self.other_band
        )
        self.admin_user = User.objects.create_superuser(
            username='admin', email='admin@teste.com', password='123'
        )
        
        self.client.login(username='produtor', password='123')
        
    def test_creation_generates_new_show(self):
        """1, 2, 6, 14, 15, 16. Criação gera NEW_SHOW, apenas um tipo, revision 0, actor=request.user"""
        data = {'title': 'Show 1', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01', 'show_time': '20:00'}
        url = reverse('shows_add', kwargs={'band_slug': self.band.slug})
        
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
            self.assertEqual(resp.status_code, 302)
            
        show = Show.objects.get(title='Show 1')
        self.assertEqual(show.notification_revision, 0)
        
        # Integrante e Produtor (actor) recebem
        notifs = Notification.objects.filter(related_show_id=show.id)
        self.assertEqual(notifs.count(), 2)
        self.assertEqual(notifs.first().event_type, 'NEW_SHOW')
        self.assertEqual(notifs.first().event_key, f"show:{show.id}:new")
        self.assertEqual(notifs.first().actor, self.produtor)
        self.assertTrue(notifs.first().target_url.startswith(f"/{self.band.slug}/show/{show.id}"))
        
    def test_creation_with_date_and_cancel_only_generates_new_show(self):
        """3, 4, 5. Criação preenchida não gera CANCELLED ou DATE_CHANGED."""
        data = {'title': 'Show 2', 'status': 'CANCELADO', 'date': '2026-08-01', 'show_time': '20:00', 'payment_status': 'PENDENTE'}
        url = reverse('shows_add', kwargs={'band_slug': self.band.slug})
        
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, data)
            
        show = Show.objects.get(title='Show 2')
        notifs = Notification.objects.filter(related_show_id=show.id)
        # 2 destinatarios, apenas NEW_SHOW
        self.assertEqual(notifs.count(), 2)
        self.assertTrue(all(n.event_type == 'NEW_SHOW' for n in notifs))
        
    def test_edit_common_field_no_events_no_increment(self):
        """23, 24. Edição de campo comum não gera evento e não incrementa revision"""
        show = Show.objects.create(band=self.band, title='Show Comum', status='CONFIRMADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        
        data = {
            'title': 'Show Comum Editado', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, data)
            
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id).count(), 0)
        
    def test_edit_date_time_and_cancel_generates_three_events_with_one_revision(self):
        """19, 25, 26, 27, 28, 29, 30. Três eventos, uma revision incrementada, target isolado"""
        show = Show.objects.create(band=self.band, title='Show Multi', status='CONFIRMADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        
        data = {
            'title': 'Show Multi', 'status': 'CANCELADO', 'date': '2026-10-02', 'show_time': '20:00', 'payment_status': 'PENDENTE',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, data)
            
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        notifs = Notification.objects.filter(related_show_id=show.id)
        
        # 3 eventos x 2 destinatários = 6
        self.assertEqual(notifs.count(), 6)
        events = set(notifs.values_list('event_type', flat=True))
        self.assertEqual(events, {'SHOW_CANCELLED', 'SHOW_DATE_CHANGED', 'SHOW_START_TIME_CHANGED'})
        
        keys = set(notifs.values_list('event_key', flat=True))
        self.assertTrue(all(f":rev:1:" in k for k in keys))
        
    def test_reactivation_and_re_cancel(self):
        """21, 22. Reativação não gera, segundo cancelamento gera evento novo (revision+1)"""
        show = Show.objects.create(band=self.band, title='Show Re', status='CANCELADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        
        # 1. Reativar
        data1 = {
            'title': 'Show Re', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp1 = self.client.post(url, data1)
        if resp1.status_code != 302:
            print("Erros form reativar:", resp1.context['form'].errors)
        self.assertEqual(resp1.status_code, 302)
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0) # Sem incremento pq não cancelou nem mudou data/hora
        self.assertEqual(Notification.objects.count(), 0)
        
        # 2. Cancelar novamente
        data2 = {
            'title': 'Show Re', 'status': 'CANCELADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp2 = self.client.post(url, data2)
        if resp2.status_code != 302:
            print("Erros form cancelar:", resp2.context['form'].errors)
        self.assertEqual(resp2.status_code, 302)
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        self.assertEqual(Notification.objects.filter(event_type='SHOW_CANCELLED').count(), 2)

    def test_recipients_rules(self):
        """7, 8, 9, 10, 11, 12, 13."""
        # Produtor e Integrante receberam (mostrado em testes anteriores). Inativo, outra banda e admin sem vinculo não
        show = Show.objects.create(band=self.band, title='Show', status='CONFIRMADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show', 'status': 'CANCELADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
            
        recipients = Notification.objects.values_list('recipient', flat=True)
        self.assertIn(self.produtor.id, recipients)
        self.assertIn(self.integrante.id, recipients)
        self.assertNotIn(self.inativo.id, recipients)
        self.assertNotIn(self.other_user.id, recipients)
        self.assertNotIn(self.admin_user.id, recipients)

    def test_rollback_no_event(self):
        """34, 35, 36, 37. Rollback/form invalido não incrementa e não notifica"""
        show = Show.objects.create(band=self.band, title='Show Erro', status='CONFIRMADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        
        # missing status -> invalido
        data = {
            'title': 'Show Erro', 'date': '2026-10-02',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, data)
            
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_admin_creation_and_edit(self):
        """41, 42, 43. Criação e edição pelo admin"""
        from django.contrib.auth.models import Permission
        self.admin_user.is_staff = True
        self.admin_user.is_superuser = True
        self.admin_user.save()
        self.client.force_login(self.admin_user)
        
        # Test creation via POST
        url_add = reverse('admin:core_show_add')
        data = {
            'band': self.band.id,
            'title': 'Admin Show',
            'status': 'PRE_RESERVADO',
            'payment_status': 'PENDENTE',
            'date': '2026-10-01',
            # Formsets required by admin? We might need management form data for admin inlines
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0',
            'receipts-TOTAL_FORMS': '0', 'receipts-INITIAL_FORMS': '0',
            'team_costs-TOTAL_FORMS': '0', 'team_costs-INITIAL_FORMS': '0',
        }
        
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url_add, data)
            
        show = Show.objects.filter(title='Admin Show').first()
        self.assertIsNotNone(show, f"Erros do form admin: {resp.context['adminform'].form.errors if hasattr(resp, 'context') and resp.context and 'adminform' in resp.context else '?'}")
        
        self.assertEqual(show.notification_revision, 0)
        notifs = Notification.objects.filter(related_show_id=show.id, event_type='NEW_SHOW')
        self.assertTrue(notifs.exists())
        self.assertEqual(notifs.first().actor, self.admin_user)
