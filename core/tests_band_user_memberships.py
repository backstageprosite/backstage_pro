from django.test import TestCase
from django.urls import reverse

from core.models import Band, User, UserBandMembership


class BandUserMembershipManagementTests(TestCase):
    def setUp(self):
        self.ph10 = Band.objects.create(name='Ph10', slug='ph10', is_active=True)
        self.ruan = Band.objects.create(name='Ruan Vitor Vaqueirinho', slug='ruan-vitor', is_active=True)
        self.luisinho_band = Band.objects.create(name='Luisinho Vaqueiro', slug='luisinho-vaqueiro', is_active=True)
        self.danniel = Band.objects.create(name='Danniel Vieira', slug='danniel-vieira', is_active=True)
        self.admin = User.objects.create_superuser('admin_memberships', 'admin@example.com', 'secret123')
        self.fernanda = User.objects.create_user('fernanda', password='secret123', band=self.ph10, role='EMPRESARIO')
        for band in (self.ph10, self.ruan, self.luisinho_band):
            UserBandMembership.objects.create(user=self.fernanda, band=band, role='EMPRESARIO')
        self.luisinho = User.objects.create_user('luisinho', password='secret123', band=self.danniel, role='INTEGRANTE')
        UserBandMembership.objects.create(user=self.luisinho, band=self.danniel, role='INTEGRANTE')
        UserBandMembership.objects.create(user=self.luisinho, band=self.luisinho_band, role='EMPRESARIO')
        self.client.force_login(self.admin)

    def url(self, name, band, user=None):
        args = [band.slug] + ([user.pk] if user else [])
        return reverse(name, args=args)

    def test_list_displays_each_band_membership_and_local_role(self):
        for band in (self.ph10, self.ruan, self.luisinho_band):
            with self.subTest(band=band.slug):
                response = self.client.get(self.url('usuarios_list', band))
                self.assertEqual(response.status_code, 200)
                listed = {user.username: user for user in response.context['usuarios']}
                self.assertEqual(listed['fernanda'].band_role, 'EMPRESARIO')
                self.assertTrue(listed['fernanda'].band_is_active)
        luisinho_page = self.client.get(self.url('usuarios_list', self.luisinho_band))
        listed = {user.username: user for user in luisinho_page.context['usuarios']}
        self.assertEqual(listed['luisinho'].band_role, 'EMPRESARIO')
        danniel_page = self.client.get(self.url('usuarios_list', self.danniel))
        listed = {user.username: user for user in danniel_page.context['usuarios']}
        self.assertEqual(listed['luisinho'].band_role, 'INTEGRANTE')
        self.assertNotIn('fernanda', listed)

    def test_editing_shared_membership_only_changes_selected_band(self):
        alternate = User.objects.create_user('ruan_owner', password='secret123', band=self.ruan, role='EMPRESARIO')
        UserBandMembership.objects.create(user=alternate, band=self.ruan, role='EMPRESARIO')
        response = self.client.post(self.url('usuarios_edit', self.ruan, self.fernanda), {
            'role': 'PRODUTOR', 'is_active': 'on', 'first_name': 'Changed globally',
        })
        self.assertEqual(response.status_code, 302)
        self.fernanda.refresh_from_db()
        self.assertEqual(self.fernanda.role, 'EMPRESARIO')
        self.assertEqual(self.fernanda.first_name, '')
        self.assertEqual(self.fernanda.get_role_for_band(self.ruan), 'PRODUTOR')
        self.assertEqual(self.fernanda.get_role_for_band(self.ph10), 'EMPRESARIO')
        self.assertEqual(self.fernanda.get_role_for_band(self.luisinho_band), 'EMPRESARIO')

    def test_removing_shared_membership_preserves_other_band_login(self):
        response = self.client.post(self.url('usuarios_delete', self.luisinho_band, self.luisinho))
        self.assertEqual(response.status_code, 302)
        self.luisinho.refresh_from_db()
        self.assertTrue(self.luisinho.has_access_to_band(self.danniel))
        self.assertFalse(self.luisinho.has_access_to_band(self.luisinho_band))
        self.assertEqual(self.luisinho.get_role_for_band(self.danniel), 'INTEGRANTE')

    def test_inactive_primary_membership_blocks_legacy_access(self):
        membership = self.fernanda.get_membership_for_band(self.ph10)
        membership.is_active = False
        membership.save(update_fields=['is_active'])
        self.assertFalse(self.fernanda.has_access_to_band(self.ph10))
        self.assertNotIn(self.fernanda, self.ph10.get_active_empresarios())
        self.assertTrue(self.fernanda.has_access_to_band(self.ruan))

    def test_admin_filter_finds_secondary_band_user(self):
        response = self.client.get(reverse('admin_painel:usuarios'), {'band': self.ruan.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'fernanda')
        self.assertNotContains(response, 'luisinho')
