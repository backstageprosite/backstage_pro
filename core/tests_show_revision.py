from django.test import TestCase
from django.urls import reverse
from core.models import Band, User, Show
from core.forms import ShowForm

class ShowNotificationRevisionTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.user = User.objects.create_user(
            username='produtor', 
            email='produtor@teste.com', 
            password='123',
            role='PRODUTOR',
            band=self.band
        )

    def test_show_new_has_revision_zero(self):
        """1. Show novo inicia com notification_revision igual a 0."""
        show = Show.objects.create(band=self.band, title='Show de Teste', status='CONFIRMADO')
        self.assertEqual(show.notification_revision, 0)
        
    def test_show_form_does_not_contain_revision(self):
        """3. O campo não aparece no ShowForm."""
        form = ShowForm()
        self.assertNotIn('notification_revision', form.fields)
        
    def test_show_revision_cannot_be_changed_via_post(self):
        """4. O campo não pode ser alterado pelo POST normal do formulário."""
        self.client.login(username='produtor', password='123')
        data = {
            'title': 'Show Malicioso',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'notification_revision': 999
        }
        url = reverse('shows_add', kwargs={'band_slug': self.band.slug})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # Redirect to calendar
        
        # Verify the show in db
        show = Show.objects.get(title='Show Malicioso')
        self.assertEqual(show.notification_revision, 0)

    def test_save_does_not_increment_automatically(self):
        """5. Salvar o Show normalmente não incrementa a revisão automaticamente (nesta etapa)."""
        show = Show.objects.create(band=self.band, title='Show Editável')
        self.assertEqual(show.notification_revision, 0)
        
        show.title = 'Show Editado'
        show.save()
        
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)

    def test_show_created_at_and_updated_at_timestamps(self):
        """BP-PEND-57: Valida preenchimento e atualização de created_at e updated_at no Show."""
        import time
        show = Show.objects.create(band=self.band, title='Show Timestamps', status='CONFIRMADO')
        self.assertIsNotNone(show.created_at)
        self.assertIsNotNone(show.updated_at)
        
        initial_created = show.created_at
        initial_updated = show.updated_at
        
        # Testar que na edição o updated_at é atualizado
        show.title = 'Show Timestamps Modificado'
        show.save()
        show.refresh_from_db()
        
        self.assertEqual(show.created_at, initial_created)
        self.assertGreaterEqual(show.updated_at, initial_updated)

    def test_show_timestamps_display_in_edit_form_and_calendar(self):
        """BP-PEND-57: Valida exibição dos timestamps no form de edição e no calendário."""
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Audit View', status='CONFIRMADO')
        
        # 1. Página de edição
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res_edit = self.client.get(url_edit)
        self.assertEqual(res_edit.status_code, 200)
        self.assertContains(res_edit, 'Data de criação:')
        self.assertContains(res_edit, 'Última atualização:')
        self.assertContains(res_edit, show.created_at.strftime('%d/%m/%Y'))

        # 2. Página da agenda / calendário
        url_cal = reverse('calendario', kwargs={'band_slug': self.band.slug})
        res_cal = self.client.get(url_cal)
        self.assertEqual(res_cal.status_code, 200)
        self.assertContains(res_cal, 'modalShowCreatedAt')
        self.assertContains(res_cal, 'modalShowUpdatedAt')
        self.assertContains(res_cal, 'Data de criação:')
        self.assertContains(res_cal, 'Última atualização:')
        self.assertContains(res_cal, show.created_at.strftime('%d/%m/%Y'))

