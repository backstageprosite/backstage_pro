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
        """3. normalizacao do telefone: numero com e sem DDD/codigo do pais."""
        user1 = User(first_name="Joao", username="joao", phone="(11) 98765-4321")
        res1 = build_whatsapp_access_data(self.band, user1, "Pass123")
        self.assertTrue(res1['has_phone'])
        self.assertTrue(res1['whatsapp_url'].startswith("https://wa.me/5511987654321?text="))

        # Telefone que ja comeca com 55 e tem 13 digitos
        user2 = User(first_name="Maria", username="maria", phone="+55 (11) 98765-4321")
        res2 = build_whatsapp_access_data(self.band, user2, "Pass123")
        self.assertTrue(res2['has_phone'])
        self.assertTrue(res2['whatsapp_url'].startswith("https://wa.me/5511987654321?text="))

        # Telefone fixo com DDD (10 digitos)
        user3 = User(first_name="Carlos", username="carlos", phone="(71) 3322-1100")
        res3 = build_whatsapp_access_data(self.band, user3, "Pass123")
        self.assertTrue(res3['has_phone'])
        self.assertTrue(res3['whatsapp_url'].startswith("https://wa.me/557133221100?text="))

        # Vazio
        user4 = User(first_name="Sem", username="sem", phone="")
        res4 = build_whatsapp_access_data(self.band, user4, "Pass123")
        self.assertFalse(res4['has_phone'])
        self.assertEqual(res4['whatsapp_url'], "")

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
            "🔐 *Senha provisória:* MinhaSenhaTemp999!\n\n"
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
