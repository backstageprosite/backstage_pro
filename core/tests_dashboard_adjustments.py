import datetime
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band, Notification, WebPushDelivery

User = get_user_model()

class DashboardAdjustmentsTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Test Band", slug="test-band")
        self.band2 = Band.objects.create(name="Other Band", slug="other-band")
        
        self.produtor = User.objects.create_user(username="prod", email="p@p.com", password="pwd", band=self.band, role='PRODUTOR')
        self.integrante = User.objects.create_user(username="int", email="i@i.com", password="pwd", band=self.band, role='INTEGRANTE')
        self.admin = User.objects.create_superuser(username="admin", email="a@a.com", password="pwd")
        self.no_band_user = User.objects.create_user(username="no", email="n@n.com", password="pwd")

    def test_root_redirects_to_dashboard(self):
        # Usuário integrante autenticado acessando raiz da banda
        self.client.force_login(self.integrante)
        response = self.client.get(f'/{self.band.slug}/')
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band.slug}))

    def test_canonical_dashboard_url_works(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)

    def test_login_redirects_to_dashboard_for_produtor(self):
        response = self.client.post(reverse('central_login'), {
            'username': 'prod', 'password': 'pwd'
        })
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        
    def test_login_redirects_to_dashboard_for_integrante(self):
        response = self.client.post(reverse('central_login'), {
            'username': 'int', 'password': 'pwd'
        })
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        
    def test_login_via_central_does_not_redirect_superuser_to_admin_panel(self):
        # Em /entrar/, superuser sem banda NÃO vai para o admin_painel
        response = self.client.post(reverse('central_login'), {
            'username': 'admin', 'password': 'pwd'
        })
        self.assertRedirects(response, reverse('selecionar_banda'))

    def test_admin_painel_login_redirects_to_admin_dashboard(self):
        # Admin Geral usa exclusivamente /painel/login/
        response = self.client.post(reverse('admin_painel:login'), {
            'username': 'admin', 'password': 'pwd'
        })
        self.assertRedirects(response, reverse('admin_painel:dashboard'))

    def test_user_without_access_redirects_or_forbidden(self):
        self.client.force_login(self.no_band_user)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        # The view @band_required denies it
        self.assertEqual(response.status_code, 403)
        
    def test_band_a_cannot_access_band_b(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band2.slug}))
        self.assertEqual(response.status_code, 403)
        
        # O acesso a raiz da banda B redireciona para a banda A
        response = self.client.get(f'/{self.band2.slug}/')
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band.slug}))

    def test_no_redirect_loop(self):
        self.client.force_login(self.produtor)
        # Ao acessar o dashboard, retorna 200 (nao redirect)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)

    def test_menu_items_order_and_active_state(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        content = response.content.decode('utf-8')
        
        # Dashboard antes da Agenda
        idx_dashboard = content.find('fa-gauge')
        idx_agenda = content.find('fa-calendar-days')
        self.assertGreater(idx_dashboard, -1)
        self.assertGreater(idx_agenda, -1)
        self.assertLess(idx_dashboard, idx_agenda)
        
        # Apenas 1 link Dashboard
        self.assertEqual(content.count('fa-gauge'), 1)
        
        # Dashboard recebe state active, mas agenda não
        # Encontramos a string do menu item do dashboard e da agenda no HTML gerado
        self.assertIn('<i class="fa-solid fa-gauge fa-fw me-2 "></i>', content) # Sem opacity-75
        self.assertIn('<i class="fa-solid fa-calendar-days fa-fw me-2 opacity-75"></i>', content)

    def test_logo_link(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        # O link do logo usa url 'dashboard'
        url = reverse('dashboard', kwargs={'band_slug': self.band.slug})
        self.assertIn(f'href="{url}" class="d-flex align-items-center', response.content.decode('utf-8'))

    def test_pendencias_appears_and_alertas_placeholder_removed(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        content = response.content.decode('utf-8')
        
        self.assertIn('Pendências', content)
        self.assertNotIn('Alertas</h5>', content)
        self.assertNotIn('Este espaço está reservado', content)
        self.assertNotIn('Aviso do Sistema', content)
        self.assertIn('Nenhuma pendência no momento.', content)
        
    def test_get_dashboard_no_side_effects(self):
        self.client.force_login(self.produtor)
        n_notif_before = Notification.objects.count()
        n_push_before = WebPushDelivery.objects.count()
        
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)
        
        self.assertEqual(Notification.objects.count(), n_notif_before)
        self.assertEqual(WebPushDelivery.objects.count(), n_push_before)

    def test_regressions(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get(reverse('shows_list', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(response.status_code, 200)
        
        response = self.client.post(reverse('logout', kwargs={'band_slug': self.band.slug}))
        self.assertRedirects(response, reverse('central_login'))
        
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:dashboard'))
        self.assertEqual(response.status_code, 200)
