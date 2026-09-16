"""
BP-PEND-62: Testes essenciais para funcionalidade de Multilogin.
Cobre os 6 cenários principais do fluxo de múltiplos vínculos de banda.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


def make_band(name, slug=None, active_sub=True):
    """Helper para criar bandas de teste com ou sem assinatura ativa."""
    from core.models import Band
    slug = slug or name.lower().replace(' ', '-')
    band, _ = Band.objects.get_or_create(slug=slug, defaults={'name': name})
    if active_sub:
        from core.models import BandSubscription
        import datetime
        sub, _ = BandSubscription.objects.get_or_create(
            band=band,
            defaults={
                'status': 'ATIVO',
                'commercial_condition': BandSubscription.COMMERCIAL_CONDITION_PAID,
                'billing_cycle': 'MENSAL',
                'contracted_value': 100,
                'start_date': datetime.date.today(),
                'next_due_date': datetime.date.today() + datetime.timedelta(days=30),
            }
        )
        if sub.status != 'ATIVO':
            sub.status = 'ATIVO'
            sub.save(update_fields=['status'])
    return band


def make_user(username, band=None, role='INTEGRANTE', **kwargs):
    """Helper para criar usuários de teste."""
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'role': role, 'band': band, **kwargs}
    )
    if created:
        user.set_password('testpass123')
        user.save()
    return user


class TestMultiloginOneband(TestCase):
    """Usuário com 1 banda: login direto no dashboard."""

    def setUp(self):
        self.band = make_band('Banda Alpha', 'banda-alpha')
        self.user = make_user('user_alpha', band=self.band, role='INTEGRANTE')
        from core.models import UserBandMembership
        UserBandMembership.objects.get_or_create(
            user=self.user, band=self.band,
            defaults={'role': 'INTEGRANTE', 'is_active': True}
        )
        self.client = Client()

    def test_login_one_band_redirects_to_dashboard(self):
        """Usuário com 1 banda ativa vai direto ao dashboard após login."""
        response = self.client.post(
            reverse('login', kwargs={'band_slug': self.band.slug}),
            {'username': 'user_alpha', 'password': 'testpass123'},
            follow=True
        )
        # Deve terminar no dashboard da banda
        self.assertIn(self.band.slug, response.request.get('PATH_INFO', ''))


class TestMultiloginMultiband(TestCase):
    """Usuário com 2+ bandas: redireciona para Selecionar Banda."""

    def setUp(self):
        self.band1 = make_band('Banda Beta', 'banda-beta')
        self.band2 = make_band('Banda Gama', 'banda-gama')
        self.user = make_user('user_multi', band=self.band1, role='EMPRESARIO')
        from core.models import UserBandMembership
        UserBandMembership.objects.get_or_create(
            user=self.user, band=self.band1,
            defaults={'role': 'EMPRESARIO', 'is_active': True}
        )
        UserBandMembership.objects.get_or_create(
            user=self.user, band=self.band2,
            defaults={'role': 'PRODUTOR', 'is_active': True}
        )
        self.client = Client()

    def test_login_multiband_redirects_to_selecionar_banda(self):
        """Usuário com 2 bandas vai para /selecionar-banda/ após login."""
        response = self.client.post(
            reverse('login', kwargs={'band_slug': self.band1.slug}),
            {'username': 'user_multi', 'password': 'testpass123'},
        )
        self.assertRedirects(response, reverse('selecionar_banda'))

    def test_selecionar_banda_view_requires_login(self):
        """Página /selecionar-banda/ requer autenticação."""
        response = self.client.get(reverse('selecionar_banda'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_selecionar_banda_authenticated_shows_choices(self):
        """Usuário autenticado com 2+ bandas vê a página de seleção."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('selecionar_banda'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Banda Beta')
        self.assertContains(response, 'Banda Gama')

    def test_selecionar_banda_post_authorized_band_sets_session(self):
        """POST com banda autorizada grava active_band_id na sessão."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('selecionar_banda'),
            {'band_id': self.band1.id},
        )
        # Deve redirecionar para o dashboard
        self.assertEqual(response.status_code, 302)
        # Sessão deve ter o active_band_id
        self.assertEqual(self.client.session.get('active_band_id'), self.band1.id)

    def test_selecionar_banda_post_unauthorized_band_raises_403(self):
        """POST com banda não autorizada retorna 403."""
        other_band = make_band('Outra Banda', 'outra-banda')
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('selecionar_banda'),
            {'band_id': other_band.id},
        )
        self.assertEqual(response.status_code, 403)


class TestMultiloginSecurity(TestCase):
    """Testes de segurança e isolamento de banda."""

    def setUp(self):
        self.band_a = make_band('Banda Delta', 'banda-delta')
        self.band_b = make_band('Banda Epsilon', 'banda-epsilon')
        self.user_a = make_user('user_delta', band=self.band_a, role='INTEGRANTE')
        from core.models import UserBandMembership
        UserBandMembership.objects.get_or_create(
            user=self.user_a, band=self.band_a,
            defaults={'role': 'INTEGRANTE', 'is_active': True}
        )
        self.client = Client()

    def test_band_required_denies_access_to_other_band(self):
        """Usuário vinculado à Banda A não pode acessar dashboard da Banda B."""
        self.client.force_login(self.user_a)
        response = self.client.get(
            reverse('dashboard', kwargs={'band_slug': self.band_b.slug})
        )
        self.assertEqual(response.status_code, 403)

    def test_trocar_banda_clears_session_and_redirects(self):
        """Trocar banda limpa active_band_id da sessão e redireciona."""
        # Criar user com 2 bandas
        band1 = make_band('Banda Zeta', 'banda-zeta')
        band2 = make_band('Banda Eta', 'banda-eta')
        user_multi = make_user('user_zeta', band=band1, role='PRODUTOR')
        from core.models import UserBandMembership
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=band1,
            defaults={'role': 'PRODUTOR', 'is_active': True}
        )
        UserBandMembership.objects.get_or_create(
            user=user_multi, band=band2,
            defaults={'role': 'INTEGRANTE', 'is_active': True}
        )
        self.client.force_login(user_multi)
        session = self.client.session
        session['active_band_id'] = band1.id
        session.save()

        response = self.client.get(reverse('trocar_banda'))
        self.assertRedirects(response, reverse('selecionar_banda'))
        self.assertNotIn('active_band_id', self.client.session)


class TestMultiloginLegacyCompat(TestCase):
    """Compatibilidade com usuários legados (sem UserBandMembership)."""

    def setUp(self):
        self.band = make_band('Banda Theta', 'banda-theta')
        # Usuário legado: tem user.band mas sem UserBandMembership
        self.user = make_user('user_theta_legacy', band=self.band, role='PRODUTOR')
        # NÃO criamos UserBandMembership propositalmente
        self.client = Client()

    def test_legacy_user_has_access_via_band_field(self):
        """Usuário legado com user.band ainda deve ter acesso via has_access_to_band."""
        # O método has_access_to_band deve verificar user.band como fallback
        self.assertTrue(self.user.has_access_to_band(self.band))
