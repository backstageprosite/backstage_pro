from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User

class FirstAccessPasswordChangeTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Teste Senha",
            slug="banda-teste-senha",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        self.produtor = User.objects.create_user(
            username="produtor_master",
            email="produtor@teste.com",
            password="SenhaProdutor123!",
            role="PRODUTOR",
            band=self.band,
            must_change_password=False
        )
        self.integrante_provisorio = User.objects.create_user(
            username="integrante_novo",
            email="integrante@teste.com",
            password="SenhaProvisoria123!",
            role="INTEGRANTE",
            band=self.band,
            must_change_password=True
        )
        self.integrante_normal = User.objects.create_user(
            username="integrante_antigo",
            email="antigo@teste.com",
            password="SenhaAntiga123!",
            role="INTEGRANTE",
            band=self.band,
            must_change_password=False
        )
        self.client_int = Client()
        self.client_prod = Client()
        self.client_norm = Client()

    def test_01_usuario_com_must_change_password_faz_login_e_vai_para_troca_obrigatoria(self):
        """1. usuário com must_change_password=True faz login -> vai para troca obrigatória."""
        login_url = reverse('login', kwargs={'band_slug': self.band.slug})
        resp = self.client_int.post(login_url, {
            'username': 'integrante_novo',
            'password': 'SenhaProvisoria123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('troca_senha_obrigatoria'))

    def test_02_nao_consegue_acessar_painel_antes_de_trocar(self):
        """2. não consegue acessar painel (nem shows, relatórios, etc.) antes de trocar."""
        self.client_int.login(username="integrante_novo", password="SenhaProvisoria123!")

        # Tenta acessar dashboard
        resp = self.client_int.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('troca_senha_obrigatoria'))

        # Tenta acessar calendário
        resp_cal = self.client_int.get(reverse('calendario', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp_cal.status_code, 302)
        self.assertEqual(resp_cal.url, reverse('troca_senha_obrigatoria'))

        # Tenta acessar a raiz da banda
        resp_root = self.client_int.get(reverse('band_root', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp_root.status_code, 302)
        self.assertEqual(resp_root.url, reverse('troca_senha_obrigatoria'))

    def test_03_troca_senha_atualiza_hash_e_remove_flag(self):
        """3. troca senha -> flag vira False, senha atualizada e sem pedir senha atual."""
        self.client_int.login(username="integrante_novo", password="SenhaProvisoria123!")

        resp_page = self.client_int.get(reverse('troca_senha_obrigatoria'))
        self.assertEqual(resp_page.status_code, 200)
        self.assertNotIn('Senha atual', resp_page.content.decode('utf-8'))
        self.assertIn('Nova senha', resp_page.content.decode('utf-8'))

        resp = self.client_int.post(reverse('troca_senha_obrigatoria'), {
            'new_password': 'NovaSenhaPessoal123!',
            'confirm_password': 'NovaSenhaPessoal123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('dashboard', kwargs={'band_slug': self.band.slug}))

        self.integrante_provisorio.refresh_from_db()
        self.assertFalse(self.integrante_provisorio.must_change_password)
        self.assertTrue(self.integrante_provisorio.check_password('NovaSenhaPessoal123!'))

    def test_04_sessao_permanece_ativa_apos_troca(self):
        """4. sessão permanece ativa após a troca."""
        self.client_int.login(username="integrante_novo", password="SenhaProvisoria123!")

        self.client_int.post(reverse('troca_senha_obrigatoria'), {
            'new_password': 'NovaSenhaPessoal123!',
            'confirm_password': 'NovaSenhaPessoal123!'
        })

        # Pode acessar o painel diretamente agora sem deslogar
        resp = self.client_int.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Painel de Controle', resp.content.decode('utf-8'))

    def test_05_segundo_login_entra_normalmente(self):
        """5. segundo login entra normalmente direto no painel com a nova senha."""
        # Primeiro acesso e troca
        self.client_int.login(username="integrante_novo", password="SenhaProvisoria123!")
        self.client_int.post(reverse('troca_senha_obrigatoria'), {
            'new_password': 'NovaSenhaPessoal123!',
            'confirm_password': 'NovaSenhaPessoal123!'
        })
        self.client_int.logout()

        # Segundo login com a nova senha pessoal
        login_url = reverse('login', kwargs={'band_slug': self.band.slug})
        resp = self.client_int.post(login_url, {
            'username': 'integrante_novo',
            'password': 'NovaSenhaPessoal123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('dashboard', kwargs={'band_slug': self.band.slug}))

    def test_06_usuario_comum_com_flag_false_nao_afetado(self):
        """6. usuário comum com flag False não é afetado."""
        login_url = reverse('login', kwargs={'band_slug': self.band.slug})
        resp = self.client_norm.post(login_url, {
            'username': 'integrante_antigo',
            'password': 'SenhaAntiga123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('dashboard', kwargs={'band_slug': self.band.slug}))

        # Acessa diretamente dashboard sem redirecionamento
        resp_dash = self.client_norm.get(reverse('dashboard', kwargs={'band_slug': self.band.slug}))
        self.assertEqual(resp_dash.status_code, 200)

    def test_07_produtor_cria_integrante_com_flag_provisoria(self):
        """7. produtor cadastra integrante -> integrante é criado com must_change_password=True."""
        self.client_prod.login(username="produtor_master", password="SenhaProdutor123!")
        create_url = reverse('usuarios_add', kwargs={'band_slug': self.band.slug})
        payload = {
            'first_name': 'Carlos',
            'last_name': 'Tecladista',
            'username': 'carlos_tec',
            'email': 'carlos@teste.com',
            'password': 'SenhaProvisoria999!',
            'confirm_password': 'SenhaProvisoria999!',
            'role': 'INTEGRANTE',
            'is_active': 'on'
        }
        resp = self.client_prod.post(create_url, payload)
        self.assertEqual(resp.status_code, 302)

        carlos = User.objects.get(username='carlos_tec')
        self.assertTrue(carlos.must_change_password)

    def test_08_produtor_reseta_senha_de_integrante_marca_flag(self):
        """8. produtor redefine senha de integrante -> marca must_change_password=True."""
        self.client_prod.login(username="produtor_master", password="SenhaProdutor123!")
        reset_url = reverse('usuarios_reset_password', kwargs={'band_slug': self.band.slug, 'pk': self.integrante_normal.id})
        payload = {
            'new_password': 'SenhaResetada123!',
            'confirm_password': 'SenhaResetada123!'
        }
        resp = self.client_prod.post(reset_url, payload)
        self.assertEqual(resp.status_code, 302)

        self.integrante_normal.refresh_from_db()
        self.assertTrue(self.integrante_normal.must_change_password)
        self.assertTrue(self.integrante_normal.check_password('SenhaResetada123!'))
