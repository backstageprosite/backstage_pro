import re
from urllib.parse import unquote
from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User
from core.views import build_whatsapp_access_data
from core.admin_forms import AdminUserCreateForm, AdminUserEditForm


class AdminWhatsAppAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='superadmin',
            email='admin@backstagepro.com',
            password='PasswordAdmin123!'
        )
        self.client.force_login(self.admin)

        self.band = Band.objects.create(
            name='Danniel Vieira',
            slug='danniel-vieira'
        )

    def test_01_phone_field_in_create_form_and_help_text(self):
        form = AdminUserCreateForm()
        self.assertIn('phone', form.fields)
        self.assertFalse(form.fields['phone'].required)
        self.assertIn('phone-mask', form.fields['phone'].widget.attrs.get('class', ''))
        self.assertEqual(
            form.fields['phone'].help_text,
            'Se informado, você poderá enviar os dados de acesso pelo WhatsApp após o cadastro.'
        )

    def test_02_phone_field_in_edit_form(self):
        form = AdminUserEditForm()
        self.assertIn('phone', form.fields)
        self.assertFalse(form.fields['phone'].required)
        self.assertIn('phone-mask', form.fields['phone'].widget.attrs.get('class', ''))

    def test_03_phone_clean_and_save_in_user_create(self):
        data = {
            'first_name': 'João',
            'last_name': 'Silva',
            'username': 'joaosilva',
            'email': 'joao@silva.com',
            'phone': '(71) 98888-7777',
            'password': 'SenhaProvisoria123!',
            'confirm_password': 'SenhaProvisoria123!',
            'band': self.band.id,
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }
        form = AdminUserCreateForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.phone, '(71) 98888-7777')
        self.assertFalse(user.check_password(''))
        self.assertTrue(user.check_password('SenhaProvisoria123!'))

    def test_04_message_and_link_priority_with_band(self):
        user = User(
            first_name='Carlos',
            username='carlos_band',
            phone='(71) 98888-1111',
            band=self.band
        )
        data = build_whatsapp_access_data(
            band=self.band,
            user=user,
            raw_password='TempPassword123!',
            is_admin_created=True
        )
        self.assertTrue(data['has_phone'])
        self.assertIn('https://wa.me/5571988881111?text=', data['whatsapp_mobile_url'])

        url_text = data['whatsapp_mobile_url'].split('?text=')[1]
        decoded = unquote(url_text)

        expected = (
            "Olá, Carlos! 👋\n\n"
            "Seja bem-vindo ao Backstage Pro!\n\n"
            "Sua conta foi criada e você já pode acessar o painel da banda *Danniel Vieira*.\n\n"
            "🔗 *Acesso:*\n"
            "https://backstagepro.site/danniel-vieira/login/\n\n"
            "👤 *Login:* carlos_band\n\n"
            "🔑 *Senha provisória:* TempPassword123!\n\n"
            "No primeiro acesso, o sistema solicitará que você crie uma nova senha pessoal.\n\n"
            "Backstage Pro\n"
            "Gestão profissional para bandas e artistas."
        )
        self.assertEqual(decoded, expected)
        self.assertIn('https://backstagepro.site/danniel-vieira/login/', decoded)
        self.assertNotIn('https://backstagepro.site/painel/login/', decoded)

    def test_05_message_and_link_priority_without_band_admin(self):
        user = User(
            first_name='Mariana',
            username='mariana_staff',
            phone='(11) 97777-2222',
            is_staff=True,
            band=None
        )
        data = build_whatsapp_access_data(
            band=None,
            user=user,
            raw_password='StaffPassword456!',
            is_admin_created=True
        )
        self.assertTrue(data['has_phone'])
        self.assertIn('https://wa.me/5511977772222?text=', data['whatsapp_mobile_url'])

        url_text = data['whatsapp_mobile_url'].split('?text=')[1]
        decoded = unquote(url_text)

        expected = (
            "Olá, Mariana! 👋\n\n"
            "Seja bem-vindo ao Backstage Pro!\n\n"
            "Sua conta de acesso ao Painel Administrativo Geral foi criada.\n\n"
            "🔗 *Acesso:*\n"
            "https://backstagepro.site/painel/login/\n\n"
            "👤 *Login:* mariana_staff\n\n"
            "🔑 *Senha provisória:* StaffPassword456!\n\n"
            "No primeiro acesso, o sistema solicitará que você crie uma nova senha pessoal.\n\n"
            "Backstage Pro\n"
            "Gestão profissional para bandas e artistas."
        )
        self.assertEqual(decoded, expected)
        self.assertIn('https://backstagepro.site/painel/login/', decoded)

    def test_06_post_admin_user_create_flow_stores_session(self):
        url_create = reverse('admin_painel:usuarios_novo')
        resp = self.client.post(url_create, {
            'first_name': 'Roberto',
            'last_name': 'Mendes',
            'username': 'robertomendes',
            'email': 'roberto@test.com',
            'phone': '(71) 99111-2233',
            'password': 'MinhaSenha123!',
            'confirm_password': 'MinhaSenha123!',
            'band': self.band.id,
            'role': 'PRODUTOR',
            'is_active': 'on'
        }, follow=False)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('admin_painel:usuarios'))

        # Check session has whatsapp_access_data
        session = self.client.session
        self.assertIn('whatsapp_access_data', session)
        access_data = session['whatsapp_access_data']
        self.assertTrue(access_data['has_phone'])
        self.assertIn('5571991112233', access_data['whatsapp_mobile_url'])
        self.assertIn('MinhaSenha123!', unquote(access_data['whatsapp_mobile_url']))

        # Check consumption and pop in list view
        resp_list = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(resp_list.status_code, 200)
        self.assertIn('whatsapp_access_data', resp_list.context)
        self.assertIsNotNone(resp_list.context['whatsapp_access_data'])
        self.assertContains(resp_list, 'id="modalWhatsappSuccess"')
        self.assertContains(resp_list, 'id="modalWhatsappDesktopChoice"')
        self.assertContains(resp_list, 'Enviar no WhatsApp')

        # Verify session is cleaned up after pop
        resp_list2 = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(resp_list2.status_code, 200)
        self.assertIsNone(resp_list2.context['whatsapp_access_data'])
        self.assertNotContains(resp_list2, 'id="modalWhatsappSuccess"')

    def test_07_post_admin_user_create_without_phone(self):
        url_create = reverse('admin_painel:usuarios_novo')
        resp = self.client.post(url_create, {
            'first_name': 'Sem',
            'last_name': 'Telefone',
            'username': 'semtelefone',
            'email': 'sem@test.com',
            'phone': '',
            'password': 'MinhaSenha123!',
            'confirm_password': 'MinhaSenha123!',
            'band': '',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('whatsapp_access_data', resp.context)
        access_data = resp.context['whatsapp_access_data']
        self.assertIsNotNone(access_data)
        self.assertFalse(access_data['has_phone'])
        self.assertEqual(access_data['whatsapp_url'], '')

        # Modal is rendered with OK button but without WhatsApp send button
        self.assertContains(resp, 'id="modalWhatsappSuccess"')
        self.assertNotContains(resp, 'id="btnSendWhatsappUser"')
        self.assertNotContains(resp, 'id="modalWhatsappDesktopChoice"')

    def test_08_admin_user_edit_saves_phone_without_whatsapp_modal(self):
        user = User.objects.create_user(
            username='useredit',
            password='OldPassword123!',
            first_name='Lucas',
            phone='(71) 90000-0000'
        )
        url_edit = reverse('admin_painel:usuarios_editar', kwargs={'pk': user.pk})
        resp = self.client.post(url_edit, {
            'first_name': 'Lucas Editado',
            'last_name': 'Silva',
            'username': 'useredit',
            'email': 'lucas@edit.com',
            'phone': '(71) 91111-2222',
            'band': self.band.id,
            'role': 'PRODUTOR',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.phone, '(71) 91111-2222')
        self.assertEqual(user.first_name, 'Lucas Editado')
        # Session does not receive whatsapp_access_data on edit
        self.assertIsNone(resp.context['whatsapp_access_data'])
        self.assertNotContains(resp, 'id="modalWhatsappSuccess"')

    def test_09_post_admin_user_create_full_fields_and_must_change_password(self):
        url_create = reverse('admin_painel:usuarios_novo')
        resp = self.client.post(url_create, {
            'first_name': 'Tiago',
            'last_name': 'Maracajá',
            'username': 'tiago',
            'email': 'tiago@maracaja.com',
            'phone': '(71) 99888-7766',
            'password': 'SenhaProvisoria123!',
            'confirm_password': 'SenhaProvisoria123!',
            'band': self.band.id,
            'role': 'INTEGRANTE',
            'is_staff': '',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username='tiago').exists())
        user = User.objects.get(username='tiago')
        self.assertEqual(user.first_name, 'Tiago')
        self.assertEqual(user.last_name, 'Maracajá')
        self.assertEqual(user.phone, '(71) 99888-7766')
        self.assertEqual(user.band, self.band)
        self.assertEqual(user.role, 'INTEGRANTE')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password('SenhaProvisoria123!'))

        # Check whatsapp success modal displayed
        self.assertContains(resp, 'id="modalWhatsappSuccess"')
        self.assertContains(resp, 'id="btnSendWhatsappUser"')

    def test_10_post_admin_user_create_validation_error_displays_in_modal(self):
        # Create an existing user to provoke duplicate username
        User.objects.create_user(username='existente', password='Password123!')

        url_create = reverse('admin_painel:usuarios_novo')
        resp = self.client.post(url_create, {
            'first_name': 'Novo',
            'last_name': 'Teste',
            'username': 'existente',
            'email': 'novo@teste.com',
            'phone': '(71) 98888-0000',
            'password': 'Senha123!',
            'confirm_password': 'SenhaDiferente999!',
            'band': self.band.id,
            'role': 'PRODUTOR',
            'is_active': 'on'
        }, follow=False)

        # Must not redirect silently, must return 200 rendering the template with errors
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['open_create_modal'])
        form_create = resp.context['form_create']
        self.assertTrue(form_create.errors)
        self.assertIn('username', form_create.errors)
        self.assertIn('confirm_password', form_create.errors)

        # HTML must contain error message and preserved safe fields
        self.assertContains(resp, 'Por favor, corrija os erros abaixo:')
        self.assertContains(resp, 'As senhas não coincidem.')
        self.assertContains(resp, 'value="Novo"')
        self.assertContains(resp, 'value="Teste"')
        self.assertContains(resp, 'value="existente"')
        self.assertContains(resp, 'value="novo@teste.com"')
        self.assertContains(resp, 'value="(71) 98888-0000"')

        # WhatsApp modal must NOT be rendered
        self.assertIsNone(resp.context.get('whatsapp_access_data'))
        self.assertNotContains(resp, 'id="modalWhatsappSuccess"')

    def test_11_role_pills_in_admin_users_page(self):
        # Create users with different roles
        user_emp = User.objects.create_user(username='user_emp', password='Pass123!', role='EMPRESARIO', first_name='Empresario')
        user_prod = User.objects.create_user(username='user_prod', password='Pass123!', role='PRODUTOR', first_name='Produtor')
        user_integ = User.objects.create_user(username='user_integ', password='Pass123!', role='INTEGRANTE', first_name='Integrante')

        resp = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(resp.status_code, 200)

        # Check that each role pill text is rendered
        self.assertContains(resp, 'Admin Geral')
        self.assertContains(resp, 'Empresário')
        self.assertContains(resp, 'Produtor')
        self.assertContains(resp, 'Integrante')

        # Check that each role pill has its designated visual class
        self.assertContains(resp, 'role-pill-admin')
        self.assertContains(resp, 'role-pill-produtor')
        self.assertContains(resp, 'role-pill-empresario')
        self.assertContains(resp, 'role-pill-integrante')

    def test_12_no_example_placeholders_in_admin_user_forms_and_template(self):
        create_form = AdminUserCreateForm()
        edit_form = AdminUserEditForm()

        for field_name, field in create_form.fields.items():
            placeholder = field.widget.attrs.get('placeholder', '')
            self.assertFalse(
                placeholder.startswith('Ex:') or 'exemplo.com' in placeholder or '00000-0000' in placeholder,
                f"Field {field_name} in AdminUserCreateForm still has example placeholder: '{placeholder}'"
            )

        for field_name, field in edit_form.fields.items():
            placeholder = field.widget.attrs.get('placeholder', '')
            self.assertFalse(
                placeholder.startswith('Ex:') or 'exemplo.com' in placeholder or '00000-0000' in placeholder,
                f"Field {field_name} in AdminUserEditForm still has example placeholder: '{placeholder}'"
            )

        resp = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Modal create inputs must not contain sample data placeholders
        self.assertNotIn('placeholder="Ex:', content)
        self.assertNotIn('placeholder="email@exemplo.com"', content)
        self.assertNotIn('placeholder="(00) 00000-0000"', content)
        self.assertNotIn('placeholder="Nome"', content)
        self.assertNotIn('placeholder="Sobrenome"', content)
        self.assertNotIn('placeholder="username"', content)
        self.assertNotIn('placeholder="Senha"', content)
