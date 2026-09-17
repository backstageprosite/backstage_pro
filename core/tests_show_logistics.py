import datetime
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from core.models import Band, Show
from core.forms import ShowForm

User = get_user_model()

class ShowLogisticsDiffTest(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Banda Teste BP-PEND-67", slug="banda-teste-bp67")
        self.user = User.objects.create_user(
            username="produtor_bp67",
            password="password123",
            band=self.band,
            role="PRODUTOR"
        )

    def test_logistics_principal_labels(self):
        # Caso 1: Técnica e Artista usam Principal
        show1 = Show.objects.create(
            band=self.band,
            title="Show 1",
            has_specific_tech_logistics=False,
            has_specific_artist_logistics=False
        )
        self.assertEqual(show1.get_logistics_principal_label(), "Banda + Técnica + Artista")

        # Caso 2: Artista específico, técnica usa Principal
        show2 = Show.objects.create(
            band=self.band,
            title="Show 2",
            has_specific_tech_logistics=False,
            has_specific_artist_logistics=True
        )
        self.assertEqual(show2.get_logistics_principal_label(), "Banda + Técnica")

        # Caso 3: Técnica específica, artista usa Principal
        show3 = Show.objects.create(
            band=self.band,
            title="Show 3",
            has_specific_tech_logistics=True,
            has_specific_artist_logistics=False
        )
        self.assertEqual(show3.get_logistics_principal_label(), "Banda + Artista")

        # Caso 4: Ambos específicos
        show4 = Show.objects.create(
            band=self.band,
            title="Show 4",
            has_specific_tech_logistics=True,
            has_specific_artist_logistics=True
        )
        self.assertEqual(show4.get_logistics_principal_label(), "Banda")

    def test_show_form_fields_and_widgets(self):
        form = ShowForm()
        # Verificar se novos campos e widgets existem
        self.assertIn('arrival_location', form.fields)
        self.assertIn('has_specific_tech_logistics', form.fields)
        self.assertIn('has_specific_artist_logistics', form.fields)
        self.assertIn('tech_departure_location', form.fields)
        self.assertIn('artist_departure_location', form.fields)
        self.assertEqual(form.fields['status'].widget.attrs.get('class'), 'form-select')

    def test_show_pdf_view_rendering(self):
        self.client.login(username="produtor_bp67", password="password123")
        now = timezone.now()
        show = Show.objects.create(
            band=self.band,
            title="Show Arena",
            date=datetime.date.today(),
            city="Salvador",
            venue="Arena Fonte Nova",
            departure_location="Hotel Pelourinho",
            arrival_location="Arena Fonte Nova",
            departure_time=now,
            arrival_time=now + datetime.timedelta(hours=1),
            transport="Van Executiva",
            transport_contact="71999999999",
            has_air_travel=True,
            airline="LATAM",
            flight_number="LA3001",
            departure_airport="SSA",
            arrival_airport="GRU",
            has_specific_tech_logistics=True,
            tech_departure_location="Galpão Som",
            tech_transport="Caminhão",
            sound_system="Line Array D&B",
            sound_contact="71888888888",
            band_notes="Levar figurino preto."
        )

        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("Dados do Evento", content)
        self.assertIn("Deslocamento & Transporte", content)
        self.assertIn("Logística Principal", content)
        self.assertIn("Banda + Artista", content)
        self.assertIn("Logística Específica", content)
        self.assertIn("Técnica", content)
        self.assertIn("Line Array D&amp;B", content)
        self.assertIn("Levar figurino preto.", content)
