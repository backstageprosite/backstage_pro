import io
from PIL import Image
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, User

class ProfileAreaTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Perfil",
            slug="banda-perfil",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        self.user1 = User.objects.create_user(
            username="joao_produtor",
            email="joao@teste.com",
            password="SenhaForte123!",
            role="PRODUTOR",
            band=self.band,
            first_name="João Produtor",
            phone="11988887777"
        )
        self.user2 = User.objects.create_user(
            username="maria_integrante",
            email="maria@teste.com",
            password="SenhaForte456!",
            role="INTEGRANTE",
            band=self.band,
            first_name="Maria Integrante",
            phone="11977776666"
        )
        self.client1 = Client()
        self.client2 = Client()

    def _create_test_image(self, size=(600, 600), format='JPEG'):
        file_obj = io.BytesIO()
        image = Image.new('RGB', size, (255, 0, 0))
        image.save(file_obj, format=format)
        file_obj.seek(0)
        return SimpleUploadedFile('test_photo.jpg', file_obj.read(), content_type='image/jpeg')

    def test_01_usuario_autenticado_acessa_proprio_perfil(self):
        """1. usuário autenticado acessa o próprio Perfil."""
        self.client1.login(username="joao_produtor", password="SenhaForte123!")
        resp = self.client1.get(reverse('perfil'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('Meu Perfil', html)
        self.assertIn('joao_produtor', html)
        self.assertIn('joao@teste.com', html)
        self.assertIn('11988887777', html)
        self.assertIn('Perfil', html)

    def test_02_usuario_nao_autenticado_redirecionado(self):
        """2. usuário não autenticado é redirecionado."""
        resp = self.client.get(reverse('perfil'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/?next=/perfil/', resp.url)

    def test_03_edicao_nome_email_telefone_foto_funciona(self):
        """3. edição de nome/e-mail/telefone funciona e foto é comprimida/redimensionada."""
        self.client1.login(username="joao_produtor", password="SenhaForte123!")
        
        photo = self._create_test_image(size=(800, 800))
        payload = {
            'update_profile': '1',
            'first_name': 'João Silva',
            'email': 'joaosilva@teste.com',
            'phone': '(11) 99999-8888',
            'profile_picture': photo,
            'active_tab': '#dados',
            'remove_picture': '0'
        }
        resp = self.client1.post(reverse('perfil'), payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('perfil'))

        self.user1.refresh_from_db()
        self.assertEqual(self.user1.first_name, 'João Silva')
        self.assertEqual(self.user1.email, 'joaosilva@teste.com')
        self.assertEqual(self.user1.phone, '(11) 99999-8888')
        self.assertTrue(bool(self.user1.profile_picture))

        # Verificar se a imagem foi comprimida e redimensionada para <= 400x400
        img = Image.open(self.user1.profile_picture.path)
        self.assertLessEqual(img.width, 400)
        self.assertLessEqual(img.height, 400)

    def test_04_login_permanece_somente_leitura(self):
        """4. login permanece somente leitura (não altera mesmo se enviado no POST)."""
        self.client1.login(username="joao_produtor", password="SenhaForte123!")
        payload = {
            'update_profile': '1',
            'username': 'novo_login_hacker',
            'first_name': 'João',
            'email': 'joao@teste.com',
            'phone': '11988887777',
            'active_tab': '#dados',
            'remove_picture': '0'
        }
        resp = self.client1.post(reverse('perfil'), payload)
        self.assertEqual(resp.status_code, 302)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.username, 'joao_produtor')

    def test_05_troca_de_senha_funciona_e_mantem_sessao(self):
        """5. troca de senha funciona e mantém sessão."""
        self.client1.login(username="joao_produtor", password="SenhaForte123!")
        
        # Tentativa com senha atual errada
        resp_err = self.client1.post(reverse('perfil'), {
            'change_password': '1',
            'old_password': 'SenhaErrada!',
            'new_password': 'NovaSenha789!',
            'confirm_password': 'NovaSenha789!',
            'active_tab': '#senha'
        })
        self.assertEqual(resp_err.status_code, 200)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.check_password('SenhaForte123!'))

        # Tentativa correta
        resp_ok = self.client1.post(reverse('perfil'), {
            'change_password': '1',
            'old_password': 'SenhaForte123!',
            'new_password': 'NovaSenha789!',
            'confirm_password': 'NovaSenha789!',
            'active_tab': '#senha'
        })
        self.assertEqual(resp_ok.status_code, 302)
        self.assertEqual(resp_ok.url, reverse('perfil'))

        self.user1.refresh_from_db()
        self.assertTrue(self.user1.check_password('NovaSenha789!'))

        # Sessão continua ativa!
        resp_session = self.client1.get(reverse('perfil'))
        self.assertEqual(resp_session.status_code, 200)
        self.assertIn('joao_produtor', resp_session.content.decode('utf-8'))

    def test_06_usuario_nao_consegue_editar_perfil_de_outro(self):
        """6. usuário só edita o próprio perfil (endpoint perfil opera estritamente em request.user)."""
        self.client2.login(username="maria_integrante", password="SenhaForte456!")
        
        # Maria tenta alterar seus dados enviando requisição
        payload = {
            'update_profile': '1',
            'user_id': self.user1.id,  # Tentativa maliciosa de injetar id alheio
            'first_name': 'Maria Editada',
            'email': 'maria_editada@teste.com',
            'phone': '11999990000',
            'active_tab': '#dados',
            'remove_picture': '0'
        }
        resp = self.client2.post(reverse('perfil'), payload)
        self.assertEqual(resp.status_code, 302)

        # O perfil de João permaneceu estritamente inalterado
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.first_name, 'João Produtor')
        self.assertEqual(self.user1.email, 'joao@teste.com')
        self.assertEqual(self.user1.phone, '11988887777')

        # O perfil de Maria foi o único alterado
        self.user2.refresh_from_db()
        self.assertEqual(self.user2.first_name, 'Maria Editada')
        self.assertEqual(self.user2.email, 'maria_editada@teste.com')
