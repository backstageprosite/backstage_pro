import datetime
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import Band, UserBandMembership

User = get_user_model()

class BP_PEND_70_UltimoAcessoAdminTests(TestCase):
    def setUp(self):
        # Superuser / Admin Geral
        self.admin = User.objects.create_superuser(
            username="admin_geral",
            email="admin@backstagepro.site",
            password="password123"
        )

        # Bandas
        self.band1 = Band.objects.create(name="Banda Alfa", slug="banda-alfa")
        self.band2 = Band.objects.create(name="Banda Beta", slug="banda-beta")

        # Usuário 1: Com last_login registrado
        self.dt_login = timezone.make_aware(datetime.datetime(2026, 9, 21, 18, 42))
        self.user_with_login = User.objects.create_user(
            username="joao_silva",
            first_name="João",
            last_name="Silva",
            email="joao@alfa.com",
            password="password123",
            last_login=self.dt_login
        )
        UserBandMembership.objects.create(user=self.user_with_login, band=self.band1, role="PRODUTOR", is_active=True)

        # Usuário 2: Sem last_login (Nunca acessou)
        self.user_never_login = User.objects.create_user(
            username="maria_santos",
            first_name="Maria",
            last_name="Santos",
            email="maria@alfa.com",
            password="password123",
            last_login=None
        )
        UserBandMembership.objects.create(user=self.user_never_login, band=self.band1, role="INTEGRANTE", is_active=True)

        # Usuário 3: Multibanda
        self.user_multiband = User.objects.create_user(
            username="pedro_multi",
            first_name="Pedro",
            last_name="Empresario",
            email="pedro@multi.com",
            password="password123",
            last_login=None
        )
        UserBandMembership.objects.create(user=self.user_multiband, band=self.band1, role="EMPRESARIO", is_active=True)
        UserBandMembership.objects.create(user=self.user_multiband, band=self.band2, role="EMPRESARIO", is_active=True)

    def test_01_usuario_com_last_login_exibe_data_formatada(self):
        self.client.login(username="admin_geral", password="password123")
        url = reverse("admin_painel:usuarios")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Deve exibir a coluna e o valor formatado d/m/Y H:i
        self.assertContains(response, "Últ. acesso")
        self.assertContains(response, "21/09/2026 18:42")

    def test_02_usuario_sem_last_login_exibe_nunca_acessou(self):
        self.client.login(username="admin_geral", password="password123")
        url = reverse("admin_painel:usuarios")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nunca acessou")

    def test_03_usuario_multibanda_linha_unica_e_ambas_as_bandas(self):
        self.client.login(username="admin_geral", password="password123")
        url = reverse("admin_painel:usuarios")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # O usuário deve aparecer na listagem de usuários como um único registro
        users_in_context = list(response.context["usuarios"])
        multiband_users = [u for u in users_in_context if u.username == "pedro_multi"]
        self.assertEqual(len(multiband_users), 1)
        # E as duas bandas devem constar na página
        self.assertContains(response, "Banda Alfa")
        self.assertContains(response, "Banda Beta")

    def test_04_acesso_restrito_ao_admin_geral(self):
        # Usuário comum (não superuser) é redirecionado ou bloqueado
        self.client.login(username="joao_silva", password="password123")
        url = reverse("admin_painel:usuarios")
        response = self.client.get(url)
        # AdminRequiredMixin redireciona para o login do admin ou 302
        self.assertIn(response.status_code, [302, 403])
