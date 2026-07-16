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
