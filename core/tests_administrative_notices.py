from django.test import TestCase
from django.urls import reverse
from core.models import Band, User, AdministrativeBandNotice

class AdministrativeBandNoticeVisibilityTests(TestCase):
    def setUp(self):
        # Create Band A and B
        self.band_a = Band.objects.create(name='Banda A', slug='banda-a', is_active=True)
        self.band_b = Band.objects.create(name='Banda B', slug='banda-b', is_active=True)

        # Users for Band A
        self.produtor_a = User.objects.create_user(
            username='produtor_a', password='pwd',
            email='produtor_a@test.com', band=self.band_a, role='PRODUTOR'
        )
        self.integrante_a = User.objects.create_user(
            username='integrante_a', password='pwd',
            email='integrante_a@test.com', band=self.band_a, role='INTEGRANTE'
        )

        # Users for Band B
        self.produtor_b = User.objects.create_user(
            username='produtor_b', password='pwd',
            email='produtor_b@test.com', band=self.band_b, role='PRODUTOR'
        )
        self.integrante_b = User.objects.create_user(
            username='integrante_b', password='pwd',
            email='integrante_b@test.com', band=self.band_b, role='INTEGRANTE'
        )

        # Superuser (No band, or band A but without role='PRODUTOR')
        # Here we create a superuser WITHOUT any role in a band, or just no band
        self.superuser = User.objects.create_superuser(
            username='admin_general', password='pwd',
            email='admin@test.com'
        )
        
        # Superuser with Band A but role INTEGRANTE (edge case)
        self.superuser_integrante_a = User.objects.create_superuser(
            username='admin_integrante_a', password='pwd',
            email='admin_int@test.com', band=self.band_a, role='INTEGRANTE'
        )

    def test_band_producer_sees_specific_notice(self):
        notice = AdministrativeBandNotice.objects.create(band=self.band_a, title="Notice A", message="Msg A")
        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertIn('administrative_notices', response.context)
        notices = list(response.context['administrative_notices'])
        self.assertIn(notice, notices)
        self.assertContains(response, "Notice A")
        self.assertContains(response, "Avisos")

    def test_band_producer_sees_global_notice(self):
        notice = AdministrativeBandNotice.objects.create(band=None, title="Global Notice", message="Global Msg")
        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        notices = list(response.context['administrative_notices'])
        self.assertIn(notice, notices)
        self.assertContains(response, "Global Notice")

    def test_band_producer_does_not_see_other_band_notice(self):
        notice_b = AdministrativeBandNotice.objects.create(band=self.band_b, title="Notice B", message="Msg B")
        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        notices = list(response.context['administrative_notices'])
        self.assertNotIn(notice_b, notices)
        self.assertNotContains(response, "Notice B")

    def test_band_member_does_not_see_specific_notice(self):
        notice = AdministrativeBandNotice.objects.create(band=self.band_a, title="Notice A Member", message="Msg")
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertNotContains(response, "Notice A Member")

    def test_band_member_does_not_see_global_notice(self):
        notice = AdministrativeBandNotice.objects.create(band=None, title="Global Notice Member", message="Msg")
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertNotContains(response, "Global Notice Member")

    def test_band_member_does_not_render_notices_card(self):
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        # "Avisos Administrativos" is an HTML comment in the template inside the PRODUTOR block
        self.assertNotContains(response, "Avisos Administrativos (Apenas Produtores)")
        # Make sure the fa-bullhorn icon which is inside the header doesn't render
        self.assertNotContains(response, "fa-bullhorn text-warning")

    def test_band_member_does_not_render_empty_notice_state(self):
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertNotContains(response, "Nenhum aviso no momento.")

    def test_band_member_context_does_not_expose_notices(self):
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.context.get('administrative_notices'), None)
        self.assertFalse(response.context.get('user_is_band_producer'))

    def test_notice_query_is_not_executed_for_band_member(self):
        # We test that administrative_notices is exactly None and not a QuerySet
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertIsNone(response.context.get('administrative_notices'))

    def test_superuser_without_producer_role_does_not_see_band_notice_card(self):
        AdministrativeBandNotice.objects.create(band=None, title="Global Notice", message="Msg")
        # Admin trying to view Band A dashboard
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        # Superuser not formally linked as Produtor to Band A should not see the card
        self.assertIsNone(response.context.get('administrative_notices'))
        self.assertNotContains(response, "Avisos Administrativos (Apenas Produtores)")
        
        # Even if they are linked to the band but are INTEGRANTE
        self.client.force_login(self.superuser_integrante_a)
        response2 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertIsNone(response2.context.get('administrative_notices'))

    def test_admin_can_manage_notices_in_admin_panel(self):
        # Admin can access the Django admin page for the model
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:core_administrativebandnotice_changelist'))
        self.assertEqual(response.status_code, 200)

    def test_band_user_cannot_access_admin_notice_routes(self):
        # Produtor shouldn't be able to access the admin page for notices
        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('admin:core_administrativebandnotice_changelist'))
        # Should redirect or 403
        self.assertNotEqual(response.status_code, 200)
        
        self.client.force_login(self.integrante_a)
        response = self.client.get(reverse('admin:core_administrativebandnotice_changelist'))
        self.assertNotEqual(response.status_code, 200)

    def test_global_notice_means_all_producers_only(self):
        AdministrativeBandNotice.objects.create(band=None, title="Global 123", message="Msg")
        
        self.client.force_login(self.produtor_a)
        resp1 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertContains(resp1, "Global 123")
        
        self.client.force_login(self.produtor_b)
        resp2 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_b.slug}))
        self.assertContains(resp2, "Global 123")
        
        self.client.force_login(self.integrante_a)
        resp3 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertNotContains(resp3, "Global 123")
        
        self.client.force_login(self.integrante_b)
        resp4 = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_b.slug}))
        self.assertNotContains(resp4, "Global 123")
