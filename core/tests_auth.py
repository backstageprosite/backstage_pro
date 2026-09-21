from django.test import TestCase
from django.urls import reverse
from core.models import Band, User

class AuthTests(TestCase):
    def setUp(self):
        self.band_a = Band.objects.create(name="Banda A", slug="banda-a")
        self.band_b = Band.objects.create(name="Banda B", slug="banda-b")
        
        self.producer = User.objects.create_user(
            username="produtor", 
            email="produtor@teste.com",
            password="password123", 
            role="PRODUTOR", 
            band=self.band_a
        )
        self.integrante = User.objects.create_user(
            username="integrante", 
            email="integrante@teste.com",
            password="password123", 
            role="INTEGRANTE", 
            band=self.band_a
        )
        
    def test_login_unauthenticated_layout(self):
        # Acesso deslogado na rota por slug redireciona para o login central
        response = self.client.get(reverse('login', kwargs={'band_slug': self.band_a.slug}))
        self.assertRedirects(response, reverse('central_login'))

        # Acesso direto à entrada central
        central_resp = self.client.get(reverse('central_login'))
        self.assertEqual(central_resp.status_code, 200)
        self.assertTemplateUsed(central_resp, 'core/central_login.html')
        self.assertTemplateUsed(central_resp, 'core/base_public.html')
        self.assertNotContains(central_resp, 'id="sidebarMenu"')
        self.assertNotContains(central_resp, 'Sair')
        self.assertContains(central_resp, 'Entrar no Backstage Pro')

    def test_login_authenticated_redirect(self):
        self.client.login(username="produtor", password="password123")
        response = self.client.get(reverse('login', kwargs={'band_slug': self.band_a.slug}))
        # Deve redirecionar para o dashboard da banda
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))

    def test_login_isolation_tenant(self):
        self.client.login(username="produtor", password="password123")
        # Usuário autenticado que tenta acessar login antigo de outra banda é redirecionado seguramente para sua banda ativa
        response = self.client.get(reverse('login', kwargs={'band_slug': self.band_b.slug}))
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        
    def test_logout(self):
        self.client.login(username="produtor", password="password123")
        # Requer POST
        response = self.client.get(reverse('logout', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 405) # Method Not Allowed
        
        response = self.client.post(reverse('logout', kwargs={'band_slug': self.band_a.slug}))
        self.assertRedirects(response, reverse('central_login'))
        
        # Confirma que deslogou (dashboard exige login)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 302)
        
    def test_password_reset_layout(self):
        response = self.client.get(reverse('password_reset') + '?band=' + self.band_a.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/password_reset.html')
        self.assertTemplateUsed(response, 'core/base_public.html')
        self.assertNotContains(response, 'id="sidebarMenu"')
