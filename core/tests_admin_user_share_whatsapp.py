from django.test import TestCase, Client
from django.urls import reverse
from core.models import User, Band, UserBandMembership
from core.views import build_admin_user_whatsapp_access_data


class AdminUserWhatsAppShareTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Admin Geral
        self.admin = User.objects.create_superuser(
            username='admin_test',
            email='admin@backstagepro.com.br',
            password='secret_admin_pass'
        )

        # Bands
        self.band_a = Band.objects.create(name='Banda Alfa', slug='banda-alfa')
        self.band_b = Band.objects.create(name='Banda Beta', slug='banda-beta')

        # User with phone and 2 bands
        self.user_multi = User.objects.create_user(
            username='joao_multi',
            email='joao@test.com',
            password='initial_password',
            first_name='João',
            phone='(11) 98765-4321'
        )
        UserBandMembership.objects.create(user=self.user_multi, band=self.band_a, role='PRODUTOR', is_active=True)
        UserBandMembership.objects.create(user=self.user_multi, band=self.band_b, role='EMPRESARIO', is_active=True)

        # User with 1 band
        self.user_single = User.objects.create_user(
            username='maria_single',
            email='maria@test.com',
            password='initial_password',
            first_name='Maria',
            phone='11912345678'
        )
        UserBandMembership.objects.create(user=self.user_single, band=self.band_a, role='INTEGRANTE', is_active=True)

        # User without phone
        self.user_no_phone = User.objects.create_user(
            username='pedro_no_phone',
            email='pedro@test.com',
            password='initial_password',
            first_name='Pedro',
            phone=''
        )

        # User without usable password (e.g. set_unusable_password())
        self.user_unusable = User.objects.create_user(
            username='carlos_no_pwd',
            email='carlos@test.com',
            first_name='Carlos',
            phone='(11) 97777-6666'
        )
        self.user_unusable.set_unusable_password()
        self.user_unusable.save()
        UserBandMembership.objects.create(user=self.user_unusable, band=self.band_a, role='INTEGRANTE', is_active=True)

    def test_sidebar_and_menu_isolated(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Check that sidebar has Usuários item with correct href
        self.assertIn(reverse('admin_painel:usuarios'), content)
        # Check that Compartilhar action exists in table dropdown
        self.assertIn('modalShareUser', content)
        self.assertIn('Compartilhar', content)
        self.assertIn('fa-brands fa-whatsapp', content)

    def test_modal_rendering_with_and_without_usable_password(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Usuário com senha (joao_multi):
        # - Deve exibir "••••••••" e "Senha cadastrada"
        # - Deve exibir "Este usuário já possui uma senha cadastrada"
        # - NÃO deve exibir input de senha provisória nem botão gerar senha
        self.assertIn(f'id="modalShareUser{self.user_multi.id}"', content)
        self.assertIn('Este usuário já possui uma senha cadastrada.', content)
        self.assertNotIn(f'id="inputProvisionalPass{self.user_multi.id}"', content)

        # Usuário sem senha utilizável (carlos_no_pwd):
        # - DEVE exibir campo inputProvisionalPass e botão Gerar senha
        self.assertIn(f'id="modalShareUser{self.user_unusable.id}"', content)
        self.assertIn(f'id="inputProvisionalPass{self.user_unusable.id}"', content)
        self.assertIn('Uma senha provisória será criada para este usuário', content)

    def test_relatorios_hub_does_not_contain_usuarios_card(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:relatorios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Relatorios hub should not link to admin_painel:usuarios card
        self.assertNotIn('{% url \'admin_painel:usuarios\' %}', content)
        self.assertNotIn('href="/admin-master/usuarios/" class="text-decoration-none"', content)

    def test_build_whatsapp_message_multi_bands_usable_password(self):
        whatsapp_data = build_admin_user_whatsapp_access_data(self.user_multi, '')
        self.assertTrue(whatsapp_data['has_phone'])
        self.assertEqual(whatsapp_data['phone_normalized'], '5511987654321')
        self.assertIn('Acessar o Backstage Pro:', whatsapp_data['message_text'])
        self.assertIn('https://backstagepro.site/banda-alfa/login/', whatsapp_data['message_text'])
        self.assertIn('Login: joao_multi', whatsapp_data['message_text'])
        # Mensagem para senha já cadastrada:
        self.assertIn('Senha: utilize a senha já cadastrada na sua conta.', whatsapp_data['message_text'])
        self.assertIn('Caso não se lembre da senha, utilize a opção “Esqueci minha senha”', whatsapp_data['message_text'])
        self.assertNotIn('Senha provisória:', whatsapp_data['message_text'])
        self.assertIn('Bandas vinculadas: Banda Alfa, Banda Beta', whatsapp_data['message_text'])
        self.assertIn('alternar entre elas pelo seletor de bandas', whatsapp_data['message_text'])
        self.assertIn('https://wa.me/5511987654321?text=', whatsapp_data['whatsapp_mobile_url'])

    def test_build_whatsapp_message_unusable_password_sets_provisional(self):
        whatsapp_data = build_admin_user_whatsapp_access_data(self.user_unusable, 'TempPass999!')
        self.assertTrue(whatsapp_data['has_phone'])
        self.assertEqual(whatsapp_data['phone_normalized'], '5511977776666')
        self.assertIn('Acessar o Backstage Pro:', whatsapp_data['message_text'])
        self.assertIn('Login: carlos_no_pwd', whatsapp_data['message_text'])
        self.assertIn('Senha provisória: TempPass999!', whatsapp_data['message_text'])
        self.assertIn('Por segurança, recomendamos que você altere sua senha', whatsapp_data['message_text'])

    def test_share_view_user_with_usable_password_does_not_change_password(self):
        self.client.force_login(self.admin)
        url = reverse('admin_painel:usuarios_compartilhar', kwargs={'pk': self.user_multi.pk})

        old_hash = self.user_multi.password
        # POST sem provisional_password (ou ignorando qualquer valor enviado)
        response = self.client.post(url, {}, follow=True)

        self.assertEqual(response.status_code, 200)

        # Regra de Segurança: Senha anterior e hash PERMANECEM IDÊNTICOS
        self.user_multi.refresh_from_db()
        self.assertEqual(self.user_multi.password, old_hash)
        self.assertTrue(self.user_multi.check_password('initial_password'))

        # Check session has whatsapp_access_data com orientação de senha existente
        self.assertIn('whatsapp_access_data', response.context)
        data = response.context['whatsapp_access_data']
        self.assertIsNotNone(data)
        self.assertTrue(data['has_phone'])
        self.assertIn('Senha: utilize a senha já cadastrada', data['message_text'])
        self.assertNotIn('Senha provisória:', data['message_text'])

    def test_share_view_user_without_usable_password_sets_provisional(self):
        self.client.force_login(self.admin)
        url = reverse('admin_painel:usuarios_compartilhar', kwargs={'pk': self.user_unusable.pk})

        response = self.client.post(url, {
            'provisional_password': 'CarlosNewPass@2026'
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Senha provisória foi aplicada
        self.user_unusable.refresh_from_db()
        self.assertTrue(self.user_unusable.check_password('CarlosNewPass@2026'))

        self.assertIn('whatsapp_access_data', response.context)
        data = response.context['whatsapp_access_data']
        self.assertIn('CarlosNewPass@2026', data['message_text'])

    def test_share_view_user_without_phone_handled_gracefully(self):
        self.client.force_login(self.admin)
        url = reverse('admin_painel:usuarios_compartilhar', kwargs={'pk': self.user_no_phone.pk})

        response = self.client.post(url, {
            'provisional_password': 'NoPhonePass@123'
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Regra de Segurança: Senha antiga PERMANECE VÁLIDA e nenhuma nova senha é aplicada
        self.user_no_phone.refresh_from_db()
        self.assertTrue(self.user_no_phone.check_password('initial_password'))
        self.assertFalse(self.user_no_phone.check_password('NoPhonePass@123'))

        # Nenhuma URL WhatsApp gerada em sessão/contexto
        self.assertIsNone(response.context.get('whatsapp_access_data'))

        # Mensagem de aviso exibida
        messages_list = list(response.context['messages'])
        warning_msg = [m.message for m in messages_list if m.level_tag == 'warning']
        self.assertTrue(len(warning_msg) > 0)
        self.assertIn('Este usuário não possui telefone/WhatsApp cadastrado', warning_msg[0])
