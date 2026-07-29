from django.test import TestCase
from django.urls import reverse
from core.models import Band, User

class CalendarioMobileTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste Mobile', slug='banda-teste-mobile')
        self.user = User.objects.create_user(
            username='testmobile',
            email='testmobile@example.com',
            password='password123',
            first_name='Mobile',
            last_name='User',
            band=self.band,
            role='PRODUTOR'
        )

    def test_calendario_html_structure_and_responsiveness(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)
        
        # Verify the new responsive classes on the wrapper card
        self.assertContains(response, 'calendar-card')
        self.assertContains(response, 'px-2 py-3 p-md-4')
        self.assertContains(response, 'id="dayEventsModal"')
        self.assertContains(response, 'id="dayEventsModalBody"')
        
        # Verify JS responsive logic presence
        self.assertContains(response, 'function getMobileConfig()')
        self.assertContains(response, 'function getDesktopConfig()')
        self.assertContains(response, 'window.openEventDetails')
        self.assertContains(response, "window.matchMedia('(max-width: 767.98px)')")
        self.assertContains(response, 'p-0 p-md-3')
        
        # Extra checks from the audit checklist
        self.assertContains(response, "height: 'auto'")
        self.assertContains(response, "contentHeight: 'auto'")
        self.assertContains(response, 'fixedWeekCount: false')
        self.assertContains(response, 'dayMaxEvents: 2')
        self.assertContains(response, "initialView: 'dayGridMonth'")
        
        # moreLinkClick config
        self.assertContains(response, 'moreLinkClick: function(arg)')
        
        # eventContent listMonth handling
        self.assertContains(response, "if (arg.view.type === 'listMonth' || arg.view.type === 'listWeek')")
        
        # Safe DOM manipulation instead of innerHTML
        self.assertContains(response, "document.createElement('div')")
        self.assertContains(response, "textContent = titleText")
        
        # Debounce logic check
        self.assertContains(response, 'clearTimeout(window.resizeTimer)')
        self.assertContains(response, 'setTimeout(function()')
        
        # Locale Portuguese
        self.assertContains(response, "locale: 'pt-br'")
        self.assertContains(response, "toLocaleDateString('pt-BR'")
        
        # Desktop aspectRatio
        self.assertContains(response, "aspectRatio: 1.45")
        
        # Modal Fechar button
        self.assertContains(response, 'data-bs-dismiss="modal"')
        
    def test_unauthenticated_user_cannot_access_calendario(self):
        response = self.client.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('login', kwargs={'band_slug': self.band.slug})))

    def test_integrante_can_access_calendario(self):
        integrante = User.objects.create_user(
            username='integrante', email='integrante@example.com', password='pwd', band=self.band, role='INTEGRANTE'
        )
        self.client.force_login(integrante)
        response = self.client.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)

    def test_event_endpoint_returns_json(self):
        # We don't have an endpoint for events; they are injected into the template as JSON.
        # So we just test that the template context contains the shows and they are injected safely.
        from core.models import Show
        import datetime
        Show.objects.create(band=self.band, title="Show Audit 1", status="CONFIRMADO", date=datetime.date(2026, 7, 20))
        Show.objects.create(band=self.band, title="Show Audit 2", status="CONFIRMADO", date=datetime.date(2026, 7, 20))
        self.client.force_login(self.user)
        response = self.client.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        
        # Title and date present
        self.assertContains(response, 'Show Audit 1')
        self.assertContains(response, 'Show Audit 2')
        
        # Ensure events are not duplicated arbitrarily in the JSON response payload context
        context_shows = response.context['shows']
        self.assertEqual(context_shows.count(), 2)
