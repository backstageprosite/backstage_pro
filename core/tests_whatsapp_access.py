from django.test import TestCase, Client
from django.urls import reverse
from urllib.parse import unquote
from core.models import Band, User
from core.views import build_whatsapp_access_data

class WhatsAppAccessCredentialsTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Axe Bahia",
            slug="banda-axe-bahia",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        self.produtor = User.objects.create_user(
            username="produtor_axe",
            email="produtor@axebahia.com",
            password="ProdutorPass123!",
            role="PRODUTOR",
            band=self.band,
            must_change_password=False
        )
        self.client_prod = Client()
        self.client_prod.login(username="produtor_axe", password="ProdutorPass123!")

    def test_01_cadastro_com_telefone_gera_url_wa_me_correta(self):
        """1. cadastro de integrante com telefone -> modal exibe botao com link wa.me correto."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.post(url_add, {
            'first_name': 'Lucas',
            'last_name': 'Teclados',
            'username': 'lucas_keys',
            'email': 'lucas@axe.com',
            'phone': '(71) 99888-7766',
            'password': 'SenhaProvisoria789!',
            'confirm_password': 'SenhaProvisoria789!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="modalWhatsappSuccess"')
        self.assertContains(resp, 'Integrante cadastrado com sucesso!')
        self.assertContains(resp, 'Os dados de acesso foram criados.')
        self.assertContains(resp, 'Enviar no WhatsApp')
        self.assertContains(resp, 'https://wa.me/5571998887766')

    def test_02_cadastro_sem_telefone_nao_exibe_botao_whatsapp(self):
        """2. cadastro de integrante sem telefone -> modal exibe apenas confirmacao e botao OK (sem botao WhatsApp)."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.post(url_add, {
            'first_name': 'Marcos',
            'last_name': 'Batera',
            'username': 'marcos_drums',
            'email': 'marcos@axe.com',
            'phone': '',
            'password': 'SenhaProvisoria789!',
            'confirm_password': 'SenhaProvisoria789!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="modalWhatsappSuccess"')
        self.assertContains(resp, 'Integrante cadastrado com sucesso!')
        self.assertContains(resp, 'Os dados de acesso foram criados.')
        self.assertNotContains(resp, 'Enviar no WhatsApp')
        self.assertNotContains(resp, 'https://wa.me/')
        self.assertContains(resp, '>OK</button>')

    def test_03_normalizacao_telefone_com_e_sem_55(self):
        """3. normalizacao do telefone: numero com e sem DDD/codigo do pais (mobile, app e web)."""
        user1 = User(first_name="Joao", username="joao", phone="(11) 98765-4321")
        res1 = build_whatsapp_access_data(self.band, user1, "Pass123")
        self.assertTrue(res1['has_phone'])
        self.assertTrue(res1['whatsapp_mobile_url'].startswith("https://wa.me/5511987654321?text="))
        self.assertTrue(res1['whatsapp_app_url'].startswith("whatsapp://send?phone=5511987654321&text="))
        self.assertTrue(res1['whatsapp_web_url'].startswith("https://web.whatsapp.com/send?phone=5511987654321&text="))
        self.assertEqual(res1['whatsapp_url'], res1['whatsapp_mobile_url'])

        # Telefone que ja comeca com 55 e tem 13 digitos
        user2 = User(first_name="Maria", username="maria", phone="+55 (11) 98765-4321")
        res2 = build_whatsapp_access_data(self.band, user2, "Pass123")
        self.assertTrue(res2['has_phone'])
        self.assertTrue(res2['whatsapp_mobile_url'].startswith("https://wa.me/5511987654321?text="))
        self.assertTrue(res2['whatsapp_app_url'].startswith("whatsapp://send?phone=5511987654321&text="))
        self.assertTrue(res2['whatsapp_web_url'].startswith("https://web.whatsapp.com/send?phone=5511987654321&text="))

        # Telefone fixo com DDD (10 digitos)
        user3 = User(first_name="Carlos", username="carlos", phone="(71) 3322-1100")
        res3 = build_whatsapp_access_data(self.band, user3, "Pass123")
        self.assertTrue(res3['has_phone'])
        self.assertTrue(res3['whatsapp_mobile_url'].startswith("https://wa.me/557133221100?text="))
        self.assertTrue(res3['whatsapp_app_url'].startswith("whatsapp://send?phone=557133221100&text="))
        self.assertTrue(res3['whatsapp_web_url'].startswith("https://web.whatsapp.com/send?phone=557133221100&text="))

        # Vazio
        user4 = User(first_name="Sem", username="sem", phone="")
        res4 = build_whatsapp_access_data(self.band, user4, "Pass123")
        self.assertFalse(res4['has_phone'])
        self.assertEqual(res4['whatsapp_url'], "")
        self.assertEqual(res4['whatsapp_mobile_url'], "")
        self.assertEqual(res4['whatsapp_app_url'], "")
        self.assertEqual(res4['whatsapp_web_url'], "")

    def test_04_mensagem_contem_todos_dados_corretos(self):
        """4. mensagem gerada contem nome, banda, link de login, login e senha provisoria."""
        user = User(first_name="Danniel", username="danniel_v", phone="(71) 99999-8888")
        data = build_whatsapp_access_data(self.band, user, "MinhaSenhaTemp999!")
        url = data['whatsapp_url']
        self.assertIn("https://wa.me/5571999998888?text=", url)

        query_text = url.split("?text=")[1]
        decoded_msg = unquote(query_text)

        expected_msg = (
            "Olá, Danniel! 👋\n\n"
            "Você foi cadastrado no painel da banda *Banda Axe Bahia* no Backstage Pro.\n\n"
            "Segue abaixo seus dados para acesso:\n\n"
            "🔗 *Acesso:*\n"
            "https://backstagepro.site/banda-axe-bahia/login/\n\n"
            "👤 *Login:* danniel_v\n\n"
            "🔑 *Senha provisória:* MinhaSenhaTemp999!\n\n"
            "No primeiro acesso, o sistema solicitará que você crie uma nova senha pessoal.\n\n"
            "Backstage Pro\n"
            "Gestão profissional para bandas e artistas."
        )
        self.assertEqual(decoded_msg, expected_msg)

    def test_05_senha_nao_persistida_em_texto_puro(self):
        """5. senha provisoria nao e persistida em texto puro em nenhum campo do banco."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        self.client_prod.post(url_add, {
            'first_name': 'Seguro',
            'last_name': 'Silva',
            'username': 'seguro_user',
            'email': 'seguro@axe.com',
            'phone': '(71) 99999-0000',
            'password': 'SuperSecretRawPassword123!',
            'confirm_password': 'SuperSecretRawPassword123!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        })

        created_user = User.objects.get(username='seguro_user')
        self.assertNotEqual(created_user.password, 'SuperSecretRawPassword123!')
        self.assertTrue(created_user.check_password('SuperSecretRawPassword123!'))
        self.assertTrue(created_user.must_change_password)

    def test_06_integrante_criado_com_must_change_password_true(self):
        """6. integrante e criado com must_change_password=True."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        self.client_prod.post(url_add, {
            'first_name': 'Novo',
            'last_name': 'Membro',
            'username': 'novo_membro',
            'email': 'novo@axe.com',
            'phone': '(71) 98888-0000',
            'password': 'SenhaProvisoria123!',
            'confirm_password': 'SenhaProvisoria123!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        })
        user = User.objects.get(username='novo_membro')
        self.assertTrue(user.must_change_password)

    def test_07_fechar_modal_sem_enviar_e_ok_fecha(self):
        """7. clicar em OK fecha o modal normalmente sem efeitos colaterais."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.post(url_add, {
            'first_name': 'Beto',
            'last_name': 'Voz',
            'username': 'beto_voz',
            'email': 'beto@axe.com',
            'phone': '(71) 91111-2222',
            'password': 'SenhaProvisoria123!',
            'confirm_password': 'SenhaProvisoria123!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }, follow=True)

        self.assertContains(resp, 'data-bs-dismiss="modal"')
        self.assertNotIn('whatsapp_access_data', self.client_prod.session)

    def test_08_status_pill_e_foto_de_perfil_na_listagem(self):
        """8. status pill com texto preto e check, e foto de perfil / fallback com inicial."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Cria usuario com foto
        small_gif = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        foto = SimpleUploadedFile('avatar_teste.gif', small_gif, content_type='image/gif')
        u_com_foto = User.objects.create_user(
            username="com_foto",
            email="foto@axe.com",
            password="Pass123!456",
            first_name="Carla",
            role="INTEGRANTE",
            band=self.band,
            profile_picture=foto,
            is_active=True
        )

        # Cria usuario sem foto e inativo
        u_sem_foto = User.objects.create_user(
            username="sem_foto",
            email="semfoto@axe.com",
            password="Pass123!456",
            first_name="Zeca",
            role="INTEGRANTE",
            band=self.band,
            is_active=False
        )

        url_list = reverse('usuarios_list', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.get(url_list)
        self.assertEqual(resp.status_code, 200)

        # Status ativo com circle-check e text-dark
        self.assertContains(resp, 'fa-circle-check text-success')
        self.assertContains(resp, 'text-dark border border-success')

        # Status bloqueado com ban e text-dark
        self.assertContains(resp, 'fa-ban text-danger')
        self.assertContains(resp, 'text-dark border border-danger')

        # Foto de perfil exibida para u_com_foto
        self.assertContains(resp, u_com_foto.profile_picture.url)

        # Fallback de inicial exibido para u_sem_foto
        self.assertContains(resp, 'Z')

    def test_09_erro_validacao_no_modal_permanece_na_pagina_usuarios(self):
        """9. submissao com erro vinda do modal nao redireciona para usuario_form.html e reabre modal com dados preenchidos."""
        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.post(url_add, {
            'from_modal': '1',
            'first_name': 'Carlos',
            'last_name': 'Guitarra',
            'username': 'produtor_axe',  # Username ja existente -> erro de validacao
            'email': 'carlos@axe.com',
            'phone': '(71) 98888-1111',
            'password': 'Senha123!',
            'confirm_password': 'SenhaDiferente!',  # Senhas nao coincidem
            'role': 'INTEGRANTE',
            'is_active': 'on'
        })

        # Nao deve redirecionar nem dar erro 500, deve responder 200
        self.assertEqual(resp.status_code, 200)
        # Deve usar o template da listagem usuarios.html
        self.assertTemplateUsed(resp, 'core/usuarios.html')
        self.assertTemplateNotUsed(resp, 'core/usuario_form.html')
        # Deve conter a flag open_add_modal para reabrir o modal via JS
        self.assertTrue(resp.context.get('open_add_modal'))
        # Deve preservar os campos digitados
        self.assertContains(resp, 'value="Carlos"')
        self.assertContains(resp, 'value="Guitarra"')
        self.assertContains(resp, 'value="produtor_axe"')
        self.assertContains(resp, 'value="carlos@axe.com"')
        self.assertContains(resp, 'value="(71) 98888-1111"')
        # Deve exibir os erros no modal
        self.assertContains(resp, 'Por favor, corrija os erros abaixo')
        self.assertContains(resp, 'As senhas não coincidem.')

    def test_10_placeholders_removidos_e_emojis_unicode_sem_caracteres_quebrados(self):
        """10. verifica que nao ha placeholders de exemplo no modal e que os emojis estao perfeitos."""
        url_list = reverse('usuarios_list', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.get(url_list)
        self.assertEqual(resp.status_code, 200)

        # Nao deve haver os placeholders de exemplo no html
        self.assertNotContains(resp, 'placeholder="Ex: Danniel"')
        self.assertNotContains(resp, 'placeholder="Ex: Vieira"')
        self.assertNotContains(resp, 'placeholder="Ex: danniel_v"')
        self.assertNotContains(resp, 'placeholder="email@exemplo.com"')
        self.assertNotContains(resp, 'placeholder="(00) 00000-0000"')

        # Testa mensagem do WhatsApp com emojis Unicode
        user = User(first_name="Ricardo", username="ricardo_v", phone="(71) 99111-2222")
        data = build_whatsapp_access_data(self.band, user, "TempPass123!")
        url = data['whatsapp_url']
        # Decodifica URL
        query_text = url.split("?text=")[1]
        decoded_text = unquote(query_text)

        # Nao pode conter caractere de substituicao unicode (U+FFFD ) nem caracteres quebrados
        self.assertNotIn("\ufffd", decoded_text)
        self.assertNotIn("?", decoded_text.replace("?", ""))  # so checa se nao virou ??? no lugar de emoji
        self.assertIn("👋", decoded_text)
        self.assertIn("🔗", decoded_text)
        self.assertIn("👤", decoded_text)
        self.assertIn("🔑", decoded_text)

    def test_11_whatsapp_e2e_modal_href_encoding_and_emojis(self):
        """11. E2E: cadastro via modal renderiza botao WhatsApp com href contendo percent-encoding exato e emojis sem '?'."""
        import re

        url_add = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.post(url_add, {
            'from_modal': '1',
            'first_name': 'Marcos',
            'last_name': 'Teclado',
            'username': 'marcos_teclado',
            'email': 'marcos@axe.com',
            'phone': '(71) 98765-4321',
            'password': 'SenhaProvisoria123!',
            'confirm_password': 'SenhaProvisoria123!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')

        # Modal de sucesso deve estar presente
        self.assertIn('modalWhatsappSuccess', html)
        self.assertIn('Enviar no WhatsApp', html)

        # Modal de escolha desktop deve estar presente no HTML
        self.assertIn('modalWhatsappDesktopChoice', html)
        self.assertIn('Abrir WhatsApp', html)
        self.assertIn('Como deseja abrir o WhatsApp?', html)
        self.assertIn('WhatsApp Aplicativo', html)
        self.assertIn('WhatsApp Web', html)
        self.assertIn('Cancelar', html)

        # Extrai os links do HTML
        match_mobile = re.search(r'data-mobile-url="([^"]*)"', html)
        match_app = re.search(r'href="(whatsapp://[^"]*)"', html)
        match_web = re.search(r'href="(https://web\.whatsapp\.com[^"]*)"', html)

        self.assertIsNotNone(match_mobile, "Link mobile (data-mobile-url) nao encontrado no HTML.")
        self.assertIsNotNone(match_app, "Link do aplicativo (whatsapp://) nao encontrado no HTML.")
        self.assertIsNotNone(match_web, "Link do WhatsApp Web nao encontrado no HTML.")

        mobile_url = match_mobile.group(1)
        app_url = match_app.group(1)
        web_url = match_web.group(1)

        # 1. URL mobile continua usando https://wa.me/
        self.assertTrue(mobile_url.startswith("https://wa.me/5571987654321?text="))

        # 2. URL app usa whatsapp://send
        self.assertTrue(app_url.startswith("whatsapp://send?phone=5571987654321&text="))

        # 3. URL web usa https://web.whatsapp.com/send
        self.assertTrue(web_url.startswith("https://web.whatsapp.com/send?phone=5571987654321&text="))

        # 4. As tres possuem exatamente o mesmo parametro text
        mobile_query_text = mobile_url.split("?text=")[1]
        app_query_text = app_url.split("&text=")[1]
        web_query_text = web_url.split("&text=")[1]
        self.assertEqual(mobile_query_text, app_query_text)
        self.assertEqual(mobile_query_text, web_query_text)

        # 5. As tres possuem corretamente os percent-encodings UTF-8
        for target_url in (mobile_url, app_url, web_url):
            self.assertIn('%F0%9F%91%8B', target_url)
            self.assertIn('%F0%9F%94%97', target_url)
            self.assertIn('%F0%9F%91%A4', target_url)
            self.assertIn('%F0%9F%94%91', target_url)

        # 6. Apos decodificar os emojis reais estao presentes
        decoded_text = unquote(mobile_query_text)
        self.assertIn('👋', decoded_text)
        self.assertIn('🔗', decoded_text)
        self.assertIn('👤', decoded_text)
        self.assertIn('🔑', decoded_text)

        # 7. Nao existe caractere quebrado nem dupla codificacao %25F0...
        self.assertNotIn('\ufffd', decoded_text)
        self.assertNotIn('%25F0', mobile_url)
        self.assertNotIn('%25F0', app_url)
        self.assertNotIn('%25F0', web_url)
        self.assertNotIn('? *Acesso:*', decoded_text)
        self.assertNotIn('? *Login:*', decoded_text)
        self.assertNotIn('? *Senha provisória:*', decoded_text)

        # 8. Script no HTML: no mobile vai direto para wa.me, no desktop abre modal
        self.assertIn('Android|iPhone|iPad|iPod', html)
        self.assertIn('modalWhatsappDesktopChoice', html)
        self.assertIn('btnSendWhatsappUser', html)


    def test_12_status_pill_css_enforces_dark_text(self):
        """12. Garante que usuarios.html define color: #212529 !important em .status-pill para nao ficar com texto branco."""
        url_list = reverse('usuarios_list', kwargs={'band_slug': self.band.slug})
        resp = self.client_prod.get(url_list)
        self.assertEqual(resp.status_code, 200)

        html = resp.content.decode('utf-8')
        # Verifica regra CSS no template
        self.assertIn('.bp-users-page .status-pill', html)
        self.assertIn('color: #212529 !important', html)

