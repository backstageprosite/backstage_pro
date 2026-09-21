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

    def test_relatorios_hub_does_not_contain_usuarios_card(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:relatorios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Relatorios hub should not link to admin_painel:usuarios card
        self.assertNotIn('{% url \'admin_painel:usuarios\' %}', content)
        self.assertNotIn('href="/admin-master/usuarios/" class="text-decoration-none"', content)

    def test_build_whatsapp_message_multi_bands(self):
        whatsapp_data = build_admin_user_whatsapp_access_data(self.user_multi, 'TempPass123!')
        self.assertTrue(whatsapp_data['has_phone'])
        self.assertEqual(whatsapp_data['phone_normalized'], '5511987654321')
        self.assertIn('https://backstagepro.site/', whatsapp_data['message_text'])
        self.assertIn('Login: joao_multi', whatsapp_data['message_text'])
        self.assertIn('Senha provisória: TempPass123!', whatsapp_data['message_text'])
        self.assertIn('Bandas vinculadas: Banda Alfa, Banda Beta', whatsapp_data['message_text'])
        self.assertIn('alternar entre elas pelo seletor de bandas', whatsapp_data['message_text'])
        self.assertIn('https://wa.me/5511987654321?text=', whatsapp_data['whatsapp_mobile_url'])

    def test_build_whatsapp_message_single_band(self):
        whatsapp_data = build_admin_user_whatsapp_access_data(self.user_single, 'TempPass456!')
        self.assertTrue(whatsapp_data['has_phone'])
        self.assertEqual(whatsapp_data['phone_normalized'], '5511912345678')
        self.assertIn('Banda vinculada: Banda Alfa', whatsapp_data['message_text'])
        self.assertNotIn('Bandas vinculadas:', whatsapp_data['message_text'])
        self.assertNotIn('alternar entre elas', whatsapp_data['message_text'])

    def test_share_view_sets_password_and_session(self):
        self.client.force_login(self.admin)
        url = reverse('admin_painel:usuarios_compartilhar', kwargs={'pk': self.user_multi.pk})
        
        response = self.client.post(url, {
            'provisional_password': 'NewSuperPass@2026'
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Check user password was updated
        self.user_multi.refresh_from_db()
        self.assertTrue(self.user_multi.check_password('NewSuperPass@2026'))
        self.assertFalse(self.user_multi.check_password('initial_password'))

        # Check session has whatsapp_access_data
        whatsapp_session = self.client.session.get('whatsapp_access_data')
        # Note: In Django test client follow=True, AdminUserListView.get_context_data pops it from session
        # or it is displayed in response context
        self.assertIn('whatsapp_access_data', response.context)
        data = response.context['whatsapp_access_data']
        self.assertIsNotNone(data)
        self.assertTrue(data['has_phone'])
        self.assertIn('NewSuperPass@2026', data['message_text'])

    def test_share_view_user_without_phone_handled_gracefully(self):
        self.client.force_login(self.admin)
        url = reverse('admin_painel:usuarios_compartilhar', kwargs={'pk': self.user_no_phone.pk})

        response = self.client.post(url, {
            'provisional_password': 'NoPhonePass@123'
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Password was updated
        self.user_no_phone.refresh_from_db()
        self.assertTrue(self.user_no_phone.check_password('NoPhonePass@123'))

        # Messages should contain warning about no phone
        messages_list = list(response.context['messages'])
        warning_msg = [m.message for m in messages_list if m.level_tag == 'warning']
        self.assertTrue(len(warning_msg) > 0)
        self.assertIn('não possui telefone/WhatsApp válido cadastrado', warning_msg[0])
