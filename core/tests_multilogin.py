"""
BP-PEND-62 (correção): Testes focados para /painel/usuarios/ após fix do accessor band_memberships.

Cobre:
1. /painel/usuarios/ retorna HTTP 200
2. Usuário legado (user.band, sem UserBandMembership) aparece normalmente
3. Usuário com UserBandMembership aparece normalmente
4. Perfil exibido corresponde à banda atual (band_required usa role do membership)
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band, UserBandMembership

User = get_user_model()


def make_admin_user(username='admin_test_bp62'):
    """Cria um superusuário para testar o painel admin."""
    user, _ = User.objects.get_or_create(username=username, defaults={'is_superuser': True, 'is_staff': True})
    user.set_password('adminpass123')
    user.is_superuser = True
    user.is_staff = True
    user.save()
    return user


def make_band(name, slug):
    band, _ = Band.objects.get_or_create(slug=slug, defaults={'name': name})
    return band


def make_regular_user(username, band=None, role='INTEGRANTE'):
    user, created = User.objects.get_or_create(
        username=username, defaults={'role': role, 'band': band}
    )
    if created:
        user.set_password('pass123')
        user.save()
    return user


class TestAdminUsuariosPage(TestCase):
    """Testa a página /painel/usuarios/ após correção do accessor band_memberships."""

    def setUp(self):
        self.admin = make_admin_user()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_admin_usuarios_returns_200(self):
        """
        /painel/usuarios/ deve retornar HTTP 200.
        Este é o teste principal — verifica que o erro 500 foi corrigido.
        """
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200, msg=(
            f"Esperado 200, recebido {response.status_code}. "
            f"Verifique se o accessor 'band_memberships' está correto."
        ))

    def test_legacy_user_appears_in_list(self):
        """
        Usuário legado (user.band sem UserBandMembership) deve aparecer normalmente na listagem.
        """
        band = make_band('Banda Legado', 'banda-legado')
        legacy_user = make_regular_user('user_legado_bp62', band=band, role='PRODUTOR')
        # NÃO cria UserBandMembership — simulando usuário legado

        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'user_legado_bp62')

    def test_membership_user_appears_in_list(self):
        """
        Usuário com UserBandMembership deve aparecer normalmente na listagem.
        """
        band = make_band('Banda Membership', 'banda-membership')
        member = make_regular_user('user_membership_bp62', band=band, role='EMPRESARIO')
        UserBandMembership.objects.get_or_create(
            user=member, band=band,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )

        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'user_membership_bp62')

    def test_membership_user_multiband_all_badges_rendered(self):
        """
        Usuário com 2 bandas via UserBandMembership — ambas as bandas devem aparecer no HTML.
        """
        band_a = make_band('Banda X BP62', 'banda-x-bp62')
        band_b = make_band('Banda Y BP62', 'banda-y-bp62')
        user_multi = make_regular_user('user_multi_bp62', band=band_a, role='EMPRESARIO')
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=band_a,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=band_b,
            defaults={'role': 'INTEGRANTE', 'is_active': True}
        )

        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8', errors='replace')
        self.assertIn('Banda X BP62', content)
        self.assertIn('Banda Y BP62', content)

    def test_band_role_comes_from_membership_not_user_role(self):
        """
        O perfil exibido deve vir do UserBandMembership, não do user.role legado.
        Verifica que get_role_for_band retorna o role correto do membership.
        """
        band = make_band('Banda Role Test', 'banda-role-test')
        user = make_regular_user('user_role_bp62', band=band, role='INTEGRANTE')
        # Cria membership com role diferente do user.role
        UserBandMembership.objects.get_or_create(
            user=user, band=band,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )
        # get_role_for_band deve retornar 'EMPRESARIO' (do membership)
        self.assertEqual(user.get_role_for_band(band), 'EMPRESARIO')
        # get_role_for_band sem band retorna user.role
        self.assertEqual(user.get_role_for_band(None), 'INTEGRANTE')


class TestPwaMultilogin(TestCase):
    """Testes para o comportamento de PWA com 1 banda vs Multilogin (2+ bandas)."""

    def setUp(self):
        self.band_a = make_band('Banda Alfa PWA', 'banda-alfa-pwa')
        self.band_b = make_band('Banda Beta PWA', 'banda-beta-pwa')
        self.client = Client()

    def test_single_band_user_gets_band_manifest(self):
        """Usuário com 1 banda continua recebendo o manifest com a identidade da banda."""
        user_single = make_regular_user('user_single_pwa', band=self.band_a, role='PRODUTOR')
        UserBandMembership.objects.get_or_create(
            user=user_single, band=self.band_a,
            defaults={'role': 'PRODUTOR', 'is_active': True}
        )
        self.client.force_login(user_single)

        response = self.client.get(reverse('manifest', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Banda Alfa PWA')
        self.assertIn(self.band_a.slug, data['id'])

    def test_multilogin_user_gets_backstage_pro_manifest(self):
        """Usuário com 2+ bandas ativas recebe manifest com identidade oficial Backstage Pro."""
        user_multi = make_regular_user('user_multi_pwa', band=self.band_a, role='EMPRESARIO')
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=self.band_a,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=self.band_b,
            defaults={'role': 'PRODUTOR', 'is_active': True}
        )
        self.client.force_login(user_multi)

        # Mesmo acessando a URL de manifest da banda_a, retorna Backstage Pro
        response = self.client.get(reverse('manifest', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Backstage Pro')
        self.assertEqual(data['short_name'], 'Backstage Pro')
        self.assertIn('backstage-icon-192.png', data['icons'][0]['src'])

    def test_selecionar_banda_renders_cards_and_acessar_buttons(self):
        """A tela Selecionar Banda renderiza com os botões Acessar e badges de role."""
        user_multi = make_regular_user('user_multi_cards', band=self.band_a, role='EMPRESARIO')
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=self.band_a,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=self.band_b,
            defaults={'role': 'INTEGRANTE', 'is_active': True}
        )
        self.client.force_login(user_multi)

        response = self.client.get(reverse('selecionar_banda'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8', errors='replace')
        self.assertIn('btn-acessar', content)
        self.assertIn('band-logo-box', content)
        self.assertIn('Acessar', content)
        self.assertIn('Empresário', content)
        self.assertIn('Integrante', content)

