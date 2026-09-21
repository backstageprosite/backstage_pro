from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from core.models import User, Band, UserBandMembership, EmailDelivery
from core.views import build_admin_user_whatsapp_access_data


class CentralAuthAndRecoveryTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Bandas de teste
        self.band_a = Band.objects.create(name='Banda Alfa', slug='banda-alfa', is_active=True)
        self.band_b = Band.objects.create(name='Banda Beta', slug='banda-beta', is_active=True)

        # 1. Usuário com 1 banda
        self.user_single = User.objects.create_user(
            username='carlos_single',
            email='carlos@teste.com',
            password='Password123!',
            first_name='Carlos'
        )
        UserBandMembership.objects.create(user=self.user_single, band=self.band_a, role='PRODUTOR', is_active=True)

        # 2. Usuário multibanda
        self.user_multi = User.objects.create_user(
            username='marina_multi',
            email='marina@teste.com',
            password='Password123!',
            first_name='Marina'
        )
        UserBandMembership.objects.create(user=self.user_multi, band=self.band_a, role='PRODUTOR', is_active=True)
        UserBandMembership.objects.create(user=self.user_multi, band=self.band_b, role='EMPRESARIO', is_active=True)

        # 3. Usuário sem e-mail cadastrado
        self.user_no_email = User.objects.create_user(
            username='paulo_no_email',
            email='',
            password='Password123!',
            first_name='Paulo'
        )
        UserBandMembership.objects.create(user=self.user_no_email, band=self.band_a, role='INTEGRANTE', is_active=True)

        # 4. Usuários com e-mail duplicado (cenário legado)
        self.user_dup_1 = User.objects.create_user(
            username='dup_user1',
            email='duplicado@teste.com',
            password='Password123!',
            first_name='Dup 1'
        )
        self.user_dup_2 = User.objects.create_user(
            username='dup_user2',
            email='duplicado@teste.com',
            password='Password123!',
            first_name='Dup 2'
        )

    def test_central_login_page_renders_neutral_identity(self):
        """1. /entrar/ carrega corretamente com identidade do Backstage Pro."""
        response = self.client.get(reverse('central_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/central_login.html')
        self.assertContains(response, 'Entrar no Backstage Pro')
        self.assertContains(response, 'Esqueci minha senha')
        # Não deve referenciar logos nem nomes de bandas
        self.assertNotContains(response, 'Banda Alfa')
        self.assertNotContains(response, 'Banda Beta')

    def test_login_single_band_redirects_to_dashboard(self):
        """2. Usuário com uma banda: login -> dashboard direto."""
        response = self.client.post(reverse('central_login'), {
            'username': 'carlos_single',
            'password': 'Password123!',
        }, follow=False)
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))

    def test_login_multi_band_redirects_to_selecionar_banda(self):
        """3. Usuário multibanda: login -> selecionar banda."""
        response = self.client.post(reverse('central_login'), {
            'username': 'marina_multi',
            'password': 'Password123!',
        }, follow=False)
        self.assertRedirects(response, reverse('selecionar_banda'))

    def test_legacy_band_login_redirects_to_central_login(self):
        """4. Login antigo /<slug>/login/ redireciona para /entrar/."""
        response = self.client.get(reverse('login', kwargs={'band_slug': self.band_a.slug}))
        self.assertRedirects(response, reverse('central_login'))

    def test_password_reset_by_username_generates_email(self):
        """5. Recuperação por username com e-mail: gera e-mail na fila e resposta neutra."""
        initial_count = EmailDelivery.objects.filter(recipient_email='carlos@teste.com').count()
        response = self.client.post(reverse('password_reset'), {
            'identification': 'carlos_single'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/password_reset_done.html')
        self.assertContains(response, 'Se encontrarmos uma conta com um e-mail de recuperação válido')

        # Verifica se o e-mail foi gerado
        after_count = EmailDelivery.objects.filter(recipient_email='carlos@teste.com').count()
        self.assertEqual(after_count, initial_count + 1)
        delivery = EmailDelivery.objects.filter(recipient_email='carlos@teste.com').latest('id')
        self.assertEqual(delivery.email_type, 'PASSWORD_RESET')
        self.assertIn('Redefinição de senha', delivery.subject)
        self.assertIn('reset_url', delivery.context_data)

    def test_password_reset_by_unique_email_generates_email(self):
        """6. Recuperação por e-mail único: gera e-mail na fila e resposta neutra."""
        initial_count = EmailDelivery.objects.filter(recipient_email='marina@teste.com').count()
        response = self.client.post(reverse('password_reset'), {
            'identification': 'marina@teste.com'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Se encontrarmos uma conta com um e-mail de recuperação válido')

        after_count = EmailDelivery.objects.filter(recipient_email='marina@teste.com').count()
        self.assertEqual(after_count, initial_count + 1)

    def test_password_reset_duplicate_email_does_not_arbitrarily_choose(self):
        """7. E-mail duplicado: não escolhe usuário arbitrariamente, mantém resposta neutra e não gera e-mail."""
        initial_count = EmailDelivery.objects.filter(recipient_email='duplicado@teste.com').count()
        response = self.client.post(reverse('password_reset'), {
            'identification': 'duplicado@teste.com'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Se encontrarmos uma conta com um e-mail de recuperação válido')

        # NENHUM e-mail deve ser disparado para e-mails ambíguos
        after_count = EmailDelivery.objects.filter(recipient_email='duplicado@teste.com').count()
        self.assertEqual(after_count, initial_count)

    def test_password_reset_user_without_email_neutral_response(self):
        """8. Usuário sem e-mail: não quebra, resposta continua neutra, nenhum e-mail gerado."""
        initial_count = EmailDelivery.objects.count()
        response = self.client.post(reverse('password_reset'), {
            'identification': 'paulo_no_email'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Se encontrarmos uma conta com um e-mail de recuperação válido')
        self.assertEqual(EmailDelivery.objects.count(), initial_count)

    def test_valid_token_allows_password_change(self):
        """9. Token válido: permite alterar senha e conclui em /redefinir-senha/concluido/ com link para /entrar/."""
        token = default_token_generator.make_token(self.user_single)
        uid = urlsafe_base64_encode(force_bytes(self.user_single.pk))

        url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
        get_response = self.client.get(url, follow=True)
        self.assertEqual(get_response.status_code, 200)
        self.assertTemplateUsed(get_response, 'core/password_reset_confirm.html')
        self.assertTrue(get_response.context['validlink'])

        post_url = get_response.redirect_chain[-1][0] if get_response.redirect_chain else url
        post_response = self.client.post(post_url, {
            'new_password1': 'NewBrandPass2026@',
            'new_password2': 'NewBrandPass2026@',
        }, follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertTemplateUsed(post_response, 'core/password_reset_complete.html')
        self.assertContains(post_response, 'Senha alterada com sucesso!')
        self.assertContains(post_response, reverse('central_login'))

        # Confirma que a senha foi alterada no banco
        self.user_single.refresh_from_db()
        self.assertTrue(self.user_single.check_password('NewBrandPass2026@'))

    def test_logout_from_selecionar_banda_terminates_session_and_goes_to_entrar(self):
        """10. Logout da seleção de banda: encerra sessão e vai para /entrar/."""
        self.client.force_login(self.user_multi)
        # Verifica que o formulário no template de seleção de banda aponta para central_logout com texto 'Sair'
        page_resp = self.client.get(reverse('selecionar_banda'))
        self.assertContains(page_resp, reverse('central_logout'))
        self.assertContains(page_resp, 'Sair')
        self.assertNotContains(page_resp, 'Sair do Backstage Pro')
        self.assertNotContains(page_resp, 'admin_painel:logout')

        # Executa logout central
        logout_resp = self.client.post(reverse('central_logout'))
        self.assertRedirects(logout_resp, reverse('central_login'))

        # Confirma sessão encerrada
        check_resp = self.client.get(reverse('selecionar_banda'))
        self.assertEqual(check_resp.status_code, 302)

    def test_whatsapp_share_link_uses_central_login(self):
        """11. Link do WhatsApp gerado em Admin Geral usa https://backstagepro.site/entrar/."""
        data_single = build_admin_user_whatsapp_access_data(self.user_single, '')
        self.assertIn('https://backstagepro.site/entrar/', data_single['message_text'])
        self.assertNotIn('/banda-alfa/login/', data_single['message_text'])

        data_multi = build_admin_user_whatsapp_access_data(self.user_multi, '')
        self.assertIn('https://backstagepro.site/entrar/', data_multi['message_text'])
        self.assertNotIn('/banda-alfa/login/', data_multi['message_text'])
