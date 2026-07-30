import datetime
from django.test import TestCase
from django.urls import reverse
from core.models import Band, Show
from django.contrib.auth import get_user_model

User = get_user_model()

class DashboardLimitsValidationTests(TestCase):
    def setUp(self):
        self.band_a = Band.objects.create(name="Band A", slug="band-a")
        self.band_b = Band.objects.create(name="Band B", slug="band-b")

        self.produtor_a = User.objects.create_user(username="prodA", password="123", email="proda@test.com", role="PRODUTOR", band=self.band_a)

        self.today = datetime.date.today()
        self.tomorrow = self.today + datetime.timedelta(days=1)
        self.yesterday = self.today - datetime.timedelta(days=1)

    def test_cenario_a_menos_de_seis(self):
        for i in range(4):
            Show.objects.create(band=self.band_a, title=f"Show {i}", date=self.tomorrow, show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        self.assertEqual(len(response.context['shows_proximos']), 4)

    def test_cenario_b_exatamente_seis(self):
        for i in range(6):
            Show.objects.create(band=self.band_a, title=f"Show {i}", date=self.tomorrow, show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        self.assertEqual(len(response.context['shows_proximos']), 6)

    def test_cenario_c_mais_de_seis(self):
        for i in range(8):
            Show.objects.create(band=self.band_a, title=f"Show {i}", date=self.tomorrow, show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        self.assertEqual(len(response.context['shows_proximos']), 6)

    def test_cenario_d_ordenacao(self):
        Show.objects.create(band=self.band_a, title="Show 1", date=self.today + datetime.timedelta(days=3), show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_a, title="Show 2", date=self.today + datetime.timedelta(days=1), show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_a, title="Show 3", date=self.today + datetime.timedelta(days=2), show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        shows = response.context['shows_proximos']
        self.assertEqual(shows[0].title, "Show 2")
        self.assertEqual(shows[1].title, "Show 3")
        self.assertEqual(shows[2].title, "Show 1")

    def test_cenario_e_isolamento(self):
        Show.objects.create(band=self.band_a, title="Show A", date=self.tomorrow, show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_b, title="Show B", date=self.tomorrow, show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        shows = response.context['shows_proximos']
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0].title, "Show A")

    def test_cenario_f_estados(self):
        Show.objects.create(band=self.band_a, title="Show Confirmado", date=self.tomorrow, status="CONFIRMADO", show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_a, title="Show Reserva", date=self.tomorrow, status="RESERVA", show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_a, title="Show Cancelado", date=self.tomorrow, status="CANCELADO", show_time=datetime.time(20,0))
        Show.objects.create(band=self.band_a, title="Show Passado", date=self.yesterday, status="CONFIRMADO", show_time=datetime.time(20,0))

        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        shows = response.context['shows_proximos']
        self.assertEqual(len(shows), 3)
        titles = [s.title for s in shows]
        self.assertIn("Show Confirmado", titles)
        self.assertIn("Show Reserva", titles)
        self.assertIn("Show Cancelado", titles)
        self.assertNotIn("Show Passado", titles)
