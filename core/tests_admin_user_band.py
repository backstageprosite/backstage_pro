from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User

class AdminUserBandLinkTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin_master',
            email='admin@backstagepro.com.br',
            password='password123'
        )
        self.band_danniel = Band.objects.create(name='Danniel Vieira', slug='danniel-vieira', is_active=True)
        self.band_tiago = Band.objects.create(name='Tiago Maracajá', slug='tiago-maracaja', is_active=True)
        self.band_matheus = Band.objects.create(name='Matheus Kennedy', slug='matheus-kennedy', is_active=True)

    def test_1_modal_novo_usuario_carrega_todas_bandas_existentes(self):
        """Valida que o modal de criação de usuário carrega todas as bandas existentes."""
        self.client.login(username='admin_master', password='password123')
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('bandas_list', response.context)
        self.assertIn('bandas', response.context)
        
        content = response.content.decode('utf-8')
        # Verifica se o select do modal de criação contém o name="band" e as opções
        self.assertIn('name="band"', content)
        self.assertIn('Nenhuma / Sem Vínculo', content)
        self.assertIn('Danniel Vieira', content)
        self.assertIn('Tiago Maracajá', content)
        self.assertIn('Matheus Kennedy', content)

    def test_2_banda_criada_futuramente_aparece_automaticamente(self):
        """Valida que bandas criadas futuramente aparecem no select sem alteração de código."""
        Band.objects.create(name='Banda Futura Show', slug='banda-futura-show', is_active=True)
        self.client.login(username='admin_master', password='password123')
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Banda Futura Show', content)

    def test_3_criacao_usuario_vinculado_a_banda(self):
        """Valida criação de usuário vinculado à banda selecionada."""
        self.client.login(username='admin_master', password='password123')
        data = {
            'first_name': 'Carlos',
            'last_name': 'Músico',
            'username': 'carlos_danniel',
            'email': 'carlos@danniel.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'role': 'INTEGRANTE',
            'band': self.band_danniel.id,
            'is_active': 'on',
        }
        response = self.client.post(reverse('admin_painel:usuarios_novo'), data=data)
        self.assertEqual(response.status_code, 302)
        
        user = User.objects.get(username='carlos_danniel')
        self.assertEqual(user.band, self.band_danniel)
        self.assertEqual(user.role, 'INTEGRANTE')
        self.assertFalse(user.is_staff)

    def test_4_criacao_usuario_sem_vinculo(self):
        """Valida criação de usuário com opção 'Nenhuma / Sem Vínculo'."""
        self.client.login(username='admin_master', password='password123')
        data = {
            'first_name': 'Diretor',
            'last_name': 'Geral',
            'username': 'diretor_geral',
            'email': 'diretor@backstagepro.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'role': 'PRODUTOR',
            'band': '',
            'is_active': 'on',
        }
        response = self.client.post(reverse('admin_painel:usuarios_novo'), data=data)
        self.assertEqual(response.status_code, 302)
        
        user = User.objects.get(username='diretor_geral')
        self.assertIsNone(user.band)

    def test_5_criacao_usuario_com_toggle_staff(self):
        """Valida que o toggle de staff salva is_staff=True sem regressão."""
        self.client.login(username='admin_master', password='password123')
        data = {
            'first_name': 'Staff',
            'last_name': 'Operador',
            'username': 'staff_operador',
            'email': 'staff@backstagepro.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'role': 'PRODUTOR',
            'band': '',
            'is_active': 'on',
            'is_staff': 'on',
        }
        response = self.client.post(reverse('admin_painel:usuarios_novo'), data=data)
        self.assertEqual(response.status_code, 302)
        
        user = User.objects.get(username='staff_operador')
        self.assertTrue(user.is_staff)

    def test_6_edicao_usuario_altera_banda_e_mostra_selecionada(self):
        """Valida que a edição mostra a banda atual selecionada e permite alterá-la ou removê-la."""
        user = User.objects.create_user(
            username='joao_tiago',
            first_name='João',
            last_name='Silva',
            email='joao@tiago.com',
            password='password123',
            band=self.band_tiago,
            role='INTEGRANTE'
        )
        self.client.login(username='admin_master', password='password123')
        response = self.client.get(reverse('admin_painel:usuarios'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Verifica se o option da banda Tiago está marcado como selected no modal do João
        self.assertIn(f'<option value="{self.band_tiago.id}" selected>{self.band_tiago.name}</option>', content)

        # Altera para Matheus Kennedy
        data_edit = {
            'first_name': 'João',
            'last_name': 'Silva',
            'username': 'joao_tiago',
            'email': 'joao@tiago.com',
            'band': self.band_matheus.id,
            'role': 'INTEGRANTE',
            'is_active': 'on',
        }
        resp_post = self.client.post(reverse('admin_painel:usuarios_editar', args=[user.id]), data=data_edit)
        self.assertEqual(resp_post.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.band, self.band_matheus)

        # Remove vínculo de banda na edição
        data_no_band = {
            'first_name': 'João',
            'last_name': 'Silva',
            'username': 'joao_tiago',
            'email': 'joao@tiago.com',
            'band': '',
            'role': 'INTEGRANTE',
            'is_active': 'on',
        }
        resp_post2 = self.client.post(reverse('admin_painel:usuarios_editar', args=[user.id]), data=data_no_band)
        self.assertEqual(resp_post2.status_code, 302)
        user.refresh_from_db()
        self.assertIsNone(user.band)
