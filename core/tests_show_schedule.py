from django.test import TestCase
from core.models import Band, Show, User
from django.urls import reverse
import datetime

class ShowScheduleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='producer@test.com',
            email='producer@test.com',
            password='password123',
            role='PRODUTOR'
        )
        self.band = Band.objects.create(
            name='Banda Teste',
            slug='banda-teste'
        )
        self.user.band = self.band
        self.user.save()
        self.client.login(username='producer@test.com', password='password123')

        self.show = Show.objects.create(
            band=self.band,
            title='Show de Teste',
            date=datetime.date(2026, 12, 25),
            soundcheck_time=datetime.time(14, 0),
            show_time=datetime.time(22, 0)
        )

    def test_new_field_accepts_time_and_null(self):
        # Accepts null
        self.assertIsNone(self.show.soundcheck_end_time)
        
        # Accepts time
        self.show.soundcheck_end_time = datetime.time(16, 0)
        self.show.save()
        self.show.refresh_from_db()
        self.assertEqual(self.show.soundcheck_end_time, datetime.time(16, 0))

    def test_old_field_remains(self):
        self.assertEqual(self.show.soundcheck_time, datetime.time(14, 0))

    def test_form_renders_soundcheck_and_show_times(self):
        url = reverse('shows_edit', args=[self.band.slug, self.show.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="soundcheck_time"')
        self.assertContains(response, 'name="soundcheck_end_time"')
        self.assertContains(response, 'name="show_time"')
        self.assertContains(response, 'name="show_end_time"')

    def test_edit_saves_both_times(self):
        url = reverse('shows_edit', args=[self.band.slug, self.show.id])
        data = {
            'title': 'Show Editado',
            'date': '2026-12-25',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'soundcheck_time': '15:00',
            'soundcheck_end_time': '17:00',
            'show_time': '23:00',
            'show_end_time': '01:00',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, data)
        if response.status_code == 200:
            print("Form errors:", response.context.get('form').errors.as_json() if response.context.get('form') else 'No form context')
            print("Doc formset errors:", response.context.get('doc_formset').errors if response.context.get('doc_formset') else 'No doc_formset context')
            if response.context.get('doc_formset'):
                print("Doc formset non-form:", response.context['doc_formset'].non_form_errors())
        self.assertRedirects(response, reverse('calendario', args=[self.band.slug]))
        self.show.refresh_from_db()
        self.assertEqual(self.show.soundcheck_time, datetime.time(15, 0))
        self.assertEqual(self.show.soundcheck_end_time, datetime.time(17, 0))
        self.assertEqual(self.show.show_time, datetime.time(23, 0))
        self.assertEqual(self.show.show_end_time, datetime.time(1, 0))

    def test_save_and_continue_persists(self):
        url = reverse('shows_edit', args=[self.band.slug, self.show.id])
        data = {
            'title': 'Show Save and Continue',
            'date': '2026-12-25',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'soundcheck_time': '12:00',
            'soundcheck_end_time': '13:00',
            'show_time': '20:00',
            'save_and_continue': 'true',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, data)
        if response.status_code == 200:
            print("Form errors (continue):", response.context.get('form').errors if response.context.get('form') else 'No form context')
            print("Doc formset errors (continue):", response.context.get('doc_formset').errors if response.context.get('doc_formset') else 'No doc_formset context')
        self.assertRedirects(response, url)
        self.show.refresh_from_db()
        self.assertEqual(self.show.soundcheck_time, datetime.time(12, 0))
        self.assertEqual(self.show.soundcheck_end_time, datetime.time(13, 0))

    def test_edit_only_start_preserves_end(self):
        self.show.soundcheck_end_time = datetime.time(16, 0)
        self.show.save()
        
        url = reverse('shows_edit', args=[self.band.slug, self.show.id])
        data = {
            'title': 'Show Editado',
            'date': '2026-12-25',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'show_time': '20:00',
            'soundcheck_time': '13:00',
            'soundcheck_end_time': '16:00',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        self.client.post(url, data)
        self.show.refresh_from_db()
        self.assertEqual(self.show.soundcheck_time, datetime.time(13, 0))
        self.assertEqual(self.show.soundcheck_end_time, datetime.time(16, 0))

    def test_edit_only_end_preserves_start(self):
        url = reverse('shows_edit', args=[self.band.slug, self.show.id])
        data = {
            'title': 'Show Editado',
            'date': '2026-12-25',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'show_time': '20:00',
            'soundcheck_time': '14:00',
            'soundcheck_end_time': '17:00',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        self.client.post(url, data)
        self.show.refresh_from_db()
        self.assertEqual(self.show.soundcheck_time, datetime.time(14, 0))
        self.assertEqual(self.show.soundcheck_end_time, datetime.time(17, 0))

    def test_pdf_contains_all_times(self):
        self.show.soundcheck_time = datetime.time(14, 0)
        self.show.soundcheck_end_time = datetime.time(16, 0)
        self.show.show_time = datetime.time(22, 0)
        self.show.show_end_time = datetime.time(0, 0)
        self.show.duration = "2 horas"
        self.show.save()

        url = reverse('show_pdf', args=[self.band.slug, self.show.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        self.assertIn('Início Passagem:', content)
        self.assertIn('14:00', content)
        self.assertIn('Final Passagem:', content)
        self.assertIn('16:00', content)
        self.assertIn('Início do Show:', content)
        self.assertIn('22:00', content)
        self.assertIn('Final do Show:', content)
        self.assertIn('00:00', content)
        self.assertIn('2 horas', content)
        self.assertNotIn('None', content)
        self.assertNotIn('14:00:00', content) # no seconds
        self.assertIn('text-success', content)
        self.assertIn('text-danger', content)

    def test_detail_page_contains_inline_labels(self):
        self.show.soundcheck_time = datetime.time(12, 0)
        self.show.soundcheck_end_time = datetime.time(13, 30)
        self.show.show_time = datetime.time(22, 0)
        self.show.show_end_time = datetime.time(0, 0)
        self.show.duration = "02:00"
        self.show.save()

        url = reverse('show_detail', args=[self.band.slug, self.show.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        self.assertIn('Início Passagem:', content)
        self.assertIn('12:00', content)
        self.assertIn('Final Passagem:', content)
        self.assertIn('13:30', content)
        self.assertIn('Início do Show:', content)
        self.assertIn('22:00', content)
        self.assertIn('Final do Show:', content)
        self.assertIn('00:00', content)
        self.assertIn('Duração do Show:', content)
        self.assertIn('02:00', content)
