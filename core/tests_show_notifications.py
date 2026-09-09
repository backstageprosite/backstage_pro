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
        """21, 22. Reativação gera evento de confirmação, segundo cancelamento gera evento novo (revision+2)"""
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
        self.assertEqual(show.notification_revision, 1) # Incrementa pois mudou para CONFIRMADO
        self.assertEqual(Notification.objects.filter(event_type='SHOW_CONFIRMED').count(), 2)
        
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
        self.assertEqual(show.notification_revision, 2) # Incrementa pois mudou para CANCELADO
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
            'status': 'CONFIRMADO',
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

    def test_canceling_reservation_does_not_notify(self):
        """Show que passa de RESERVA (PRE_RESERVADO) para CANCELADO não deve gerar notificação de cancelamento nem incrementar revisão."""
        show = Show.objects.create(band=self.band, title='Show Reserva', status='PRE_RESERVADO', date=date(2026, 10, 1))
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show Reserva', 'status': 'CANCELADO', 'payment_status': 'PENDENTE', 'date': '2026-10-01',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id).count(), 0)

    def test_bp_pend_46_scenario_1_time_change_in_reservation_does_not_notify(self):
        """1. show em RESERVA com alteração de horário -> 0 notificações geradas."""
        show = Show.objects.create(
            band=self.band, title='Show Reserva', status='PRE_RESERVADO',
            date=date(2026, 10, 1), show_time=time(20, 0)
        )
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show Reserva', 'status': 'PRE_RESERVADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '22:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id).count(), 0)

    def test_bp_pend_46_scenario_2_time_change_in_confirmed_show_notifies(self):
        """2. show FECHADO/CONFIRMADO com alteração de horário -> 1 notificação de alteração de horário."""
        show = Show.objects.create(
            band=self.band, title='Show Confirmado', status='CONFIRMADO',
            date=date(2026, 10, 1), show_time=time(20, 0)
        )
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show Confirmado', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '22:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        notifs = Notification.objects.filter(related_show_id=show.id)
        # 1 tipo de evento (SHOW_START_TIME_CHANGED) para 2 membros ativos da banda
        self.assertEqual(set(notifs.values_list('event_type', flat=True)), {'SHOW_START_TIME_CHANGED'})
        self.assertEqual(notifs.count(), 2)

    def test_bp_pend_46_scenario_3_reservation_to_confirmed_without_time_change_notifies_confirmation_only(self):
        """3. transição RESERVA -> FECHADO sem alteração de horário -> 1 notificação de confirmação."""
        show = Show.objects.create(
            band=self.band, title='Show Reserva', status='PRE_RESERVADO',
            date=date(2026, 10, 1), show_time=time(20, 0)
        )
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show Reserva', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '20:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        notifs = Notification.objects.filter(related_show_id=show.id)
        self.assertEqual(set(notifs.values_list('event_type', flat=True)), {'SHOW_CONFIRMED'})
        self.assertEqual(notifs.count(), 2)

    def test_bp_pend_46_scenario_4_reservation_to_confirmed_with_time_change_notifies_confirmation_only(self):
        """4. transição RESERVA -> FECHADO com alteração simultânea de horário -> apenas 1 notificação (confirmação)."""
        show = Show.objects.create(
            band=self.band, title='Show Reserva', status='PRE_RESERVADO',
            date=date(2026, 10, 1), show_time=time(20, 0)
        )
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data = {
            'title': 'Show Reserva', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '23:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        notifs = Notification.objects.filter(related_show_id=show.id)
        # Prevalece apenas SHOW_CONFIRMED (não duplica com SHOW_START_TIME_CHANGED)
        self.assertEqual(set(notifs.values_list('event_type', flat=True)), {'SHOW_CONFIRMED'})
        self.assertEqual(notifs.count(), 2)

    def test_bp_pend_46_scenario_5_subsequent_time_change_after_confirmed_generates_time_notification(self):
        """5. show já FECHADO sofrendo nova alteração de horário no futuro -> notificação de alteração de horário."""
        show = Show.objects.create(
            band=self.band, title='Show Reserva', status='PRE_RESERVADO',
            date=date(2026, 10, 1), show_time=time(20, 0)
        )
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        
        # Passo A: transição para CONFIRMADO com mudança de horário
        data1 = {
            'title': 'Show Reserva', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '21:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, data1)
            
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 1)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id).count(), 2)

        # Passo B: alteração posterior de horário com o show já CONFIRMADO
        data2 = {
            'title': 'Show Reserva', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '23:30',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp2 = self.client.post(url, data2)
        self.assertEqual(resp2.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 2)
        latest_notifs = Notification.objects.filter(related_show_id=show.id, event_type='SHOW_START_TIME_CHANGED')
        self.assertEqual(latest_notifs.count(), 2)

    def test_bp_pend_46_scenario_6_other_notifications_unaffected(self):
        """6. não regressão: criação, alteração de data e cancelamento continuam funcionando normalmente."""
        # Criação de show confirmado via endpoint
        url_add = reverse('shows_add', kwargs={'band_slug': self.band.slug})
        data_add = {
            'title': 'Novo Show', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-01', 'show_time': '20:00'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp_add = self.client.post(url_add, data_add)
        self.assertEqual(resp_add.status_code, 302)
        show = Show.objects.get(title='Novo Show')
        self.assertEqual(Notification.objects.filter(related_show_id=show.id, event_type='NEW_SHOW').count(), 2)

        # Alteração de data continua gerando SHOW_DATE_CHANGED
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        data_edit = {
            'title': 'Novo Show', 'status': 'CONFIRMADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-05', 'show_time': '20:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp_edit = self.client.post(url_edit, data_edit)
        self.assertEqual(resp_edit.status_code, 302)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id, event_type='SHOW_DATE_CHANGED').count(), 2)

        # Cancelamento continua gerando SHOW_CANCELLED
        data_cancel = {
            'title': 'Novo Show', 'status': 'CANCELADO', 'payment_status': 'PENDENTE',
            'date': '2026-10-05', 'show_time': '20:00',
            'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0'
        }
        with self.captureOnCommitCallbacks(execute=True):
            resp_cancel = self.client.post(url_edit, data_cancel)
        self.assertEqual(resp_cancel.status_code, 302)
        self.assertEqual(Notification.objects.filter(related_show_id=show.id, event_type='SHOW_CANCELLED').count(), 2)
