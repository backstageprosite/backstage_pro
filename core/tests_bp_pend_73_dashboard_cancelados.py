import datetime
from django.test import TestCase
from django.urls import reverse
from core.models import Band, Show
from django.contrib.auth import get_user_model

User = get_user_model()

class BP_PEND_73_DashboardCanceladosTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        self.produtor = User.objects.create_user(
            username="produtor_teste",
            password="password123",
            email="produtor@teste.com",
            role="PRODUTOR",
            band=self.band
        )
        self.today = datetime.date.today()
        self.tomorrow = self.today + datetime.timedelta(days=1)

    def test_01_show_futuro_cancelado_nao_aparece(self):
        """1. Show futuro CANCELADO não aparece em Próximos Shows."""
        show_cancelado = Show.objects.create(
            band=self.band,
            title="Show Cancelado Futuro",
            date=self.tomorrow,
            status=Show.STATUS_CANCELADO,
            show_time=datetime.time(21, 0)
        )
        self.client.login(username="produtor_teste", password="password123")
        response = self.client.get(reverse('dashboard', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        shows = response.context['shows_proximos']
        self.assertNotIn(show_cancelado, shows)
        self.assertNotContains(response, "Show Cancelado Futuro")

    def test_02_show_futuro_confirmado_aparece(self):
        """2. Show futuro CONFIRMADO continua aparecendo."""
        show_confirmado = Show.objects.create(
            band=self.band,
            title="Show Confirmado Futuro",
            date=self.tomorrow,
            status=Show.STATUS_CONFIRMADO,
            show_time=datetime.time(21, 0)
        )
        self.client.login(username="produtor_teste", password="password123")
        response = self.client.get(reverse('dashboard', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        shows = response.context['shows_proximos']
        self.assertIn(show_confirmado, shows)
        self.assertContains(response, "Show Confirmado Futuro")

    def test_03_show_futuro_reserva_aparece(self):
        """3. Show futuro RESERVA (PRE_RESERVADO) continua aparecendo."""
        show_reserva = Show.objects.create(
            band=self.band,
            title="Show Reserva Futuro",
            date=self.tomorrow,
            status=Show.STATUS_PRE_RESERVADO,
            show_time=datetime.time(21, 0)
        )
        self.client.login(username="produtor_teste", password="password123")
        response = self.client.get(reverse('dashboard', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        shows = response.context['shows_proximos']
        self.assertIn(show_reserva, shows)
        self.assertContains(response, "Show Reserva Futuro")

    def test_04_cancelados_sao_excluidos_antes_do_limite(self):
        """4. Cancelados são excluídos antes do slice/limit de 6 shows (não ocupam vaga invisível)."""
        # Criamos 2 shows cancelados que seriam cronologicamente os primeiros (hoje e amanhã cedo)
        Show.objects.create(
            band=self.band,
            title="Show Cancelado 1",
            date=self.today,
            status=Show.STATUS_CANCELADO,
            show_time=datetime.time(18, 0)
        )
        Show.objects.create(
            band=self.band,
            title="Show Cancelado 2",
            date=self.today,
            status=Show.STATUS_CANCELADO,
            show_time=datetime.time(19, 0)
        )

        # Criamos exatamente 6 shows confirmados para datas posteriores
        valid_shows = []
        for i in range(1, 7):
            s = Show.objects.create(
                band=self.band,
                title=f"Show Válido {i}",
                date=self.today + datetime.timedelta(days=i),
                status=Show.STATUS_CONFIRMADO,
                show_time=datetime.time(21, 0)
            )
            valid_shows.append(s)

        self.client.login(username="produtor_teste", password="password123")
        response = self.client.get(reverse('dashboard', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        shows = list(response.context['shows_proximos'])

        # Se os cancelados fossem cortados depois do slice [:6], shows_proximos teria apenas 4 shows válidos.
        # Como o .exclude() é aplicado antes do [:6], devemos ter exatamente os 6 shows válidos preenchendo o bloco.
        self.assertEqual(len(shows), 6)
        for s in valid_shows:
            self.assertIn(s, shows)
