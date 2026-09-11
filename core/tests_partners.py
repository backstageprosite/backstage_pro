from django.test import TestCase, Client
from django.urls import reverse
from core.models import Partner, Band, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from PIL import Image
import io

class PartnerTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Criação de usuários e banda
        self.banda = Band.objects.create(name='Banda Teste', slug='banda-teste', is_active=True)
        self.outra_banda = Band.objects.create(name='Banda Dois', slug='banda-dois', is_active=True)
        
        self.admin = User.objects.create_superuser('admin', 'admin@test.com', '123')
        
        self.produtor = User.objects.create_user('produtor', 'produtor@test.com', '123')
        self.produtor.role = 'PRODUTOR'
        self.produtor.band = self.banda
        self.produtor.save()
        
        self.integrante = User.objects.create_user('integrante', 'integrante@test.com', '123')
        self.integrante.role = 'INTEGRANTE'
        self.integrante.band = self.banda
        self.integrante.save()
        
        self.outro = User.objects.create_user('outro', 'outro@test.com', '123')
        self.outro.role = 'PRODUTOR'
        self.outro.band = self.outra_banda
        self.outro.save()
        
        # Parceiros
        self.partner_ativo = Partner.objects.create(
            name='Parceiro 1',
            segment='Equipamento',
            instagram='@parceiro1',
            phone='(71) 99999-9999',
            is_active=True
        )
        self.partner_inativo = Partner.objects.create(
            name='Parceiro 2',
            segment='Agência',
            is_active=False
        )
        
        # Valid image generator
        def generate_test_image(size=(100, 100), color=(255, 0, 0), format='JPEG'):
            file_obj = io.BytesIO()
            image = Image.new('RGB', size, color)
            image.save(file_obj, format)
            file_obj.seek(0)
            return file_obj.read()
            
        self.generate_test_image = generate_test_image

    def test_model_ordering(self):
        # Parceiro 1 é ativo, Parceiro 2 é inativo.
        partners = list(Partner.objects.all())
        self.assertEqual(partners[0], self.partner_ativo)
        self.assertEqual(partners[1], self.partner_inativo)

    def test_whatsapp_normalization(self):
        p1 = Partner(phone='(71) 99999-9999')
        self.assertEqual(p1.whatsapp_url, 'https://wa.me/5571999999999')
        
        p2 = Partner(phone='+55 71 99999-9999') # 13 digitos
        self.assertEqual(p2.whatsapp_url, 'https://wa.me/5571999999999')
        
        p3 = Partner(phone='1234') # Invalid length
        self.assertIsNone(p3.whatsapp_url)
        
        p4 = Partner(phone='5571999999999')
        self.assertEqual(p4.whatsapp_url, 'https://wa.me/5571999999999')

    def test_instagram_normalization(self):
        p1 = Partner(instagram='@empresa')
        self.assertEqual(p1.instagram_url, 'https://www.instagram.com/empresa/')
        
        p2 = Partner(instagram='https://instagram.com/empresa?foo=bar')
        self.assertEqual(p2.instagram_url, 'https://www.instagram.com/empresa/')
        
        # Protocolo inseguro (javascript:)
        p3 = Partner(instagram='javascript:alert(1)')
        self.assertIsNone(p3.instagram_url)
        
        p4 = Partner(instagram='ftp://instagram.com/empresa')
        self.assertIsNone(p4.instagram_url)

    def test_band_view_access(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 200)
        
        # parceiro ativo aparece
        self.assertContains(response, 'Parceiro 1')
        # inativo não aparece
        self.assertNotContains(response, 'Parceiro 2')
        # estado vazio tratado na view
        
        # integrante e produtor não veem ações administrativas (não há formulário e botões)
        self.assertNotContains(response, 'Novo Parceiro')
        self.assertNotContains(response, 'Editar Parceiro')
        
        # links com target="_blank" e rel="noopener noreferrer"
        self.assertContains(response, 'target=\"_blank\"')
        self.assertContains(response, 'rel=\"noopener noreferrer\"')

        # verificar a estrutura do layout conforme correção de largura
        self.assertNotContains(response, 'row justify-content-center')
        self.assertNotContains(response, 'col-lg-6')
        self.assertContains(response, 'partners-grid')

    def test_partners_search_filter(self):
        """BP-PEND-55: Testa busca por nome, segmento, telefone e instagram."""
        self.client.login(username='produtor', password='123')
        
        # Cria parceiro adicional para diferenciar buscas
        Partner.objects.create(
            name='Sonorização Alpha',
            segment='Áudio e Palco',
            phone='(81) 98888-1111',
            instagram='@alpha_som',
            is_active=True
        )

        # 1. Busca por nome
        res = self.client.get(reverse('parceiros', args=['banda-teste']), {'q': 'Alpha'})
        self.assertContains(res, 'Sonorização Alpha')
        self.assertNotContains(res, 'Parceiro 1')

        # 2. Busca por segmento
        res = self.client.get(reverse('parceiros', args=['banda-teste']), {'q': 'Áudio'})
        self.assertContains(res, 'Sonorização Alpha')
        self.assertNotContains(res, 'Parceiro 1')

        # 3. Busca por telefone
        res = self.client.get(reverse('parceiros', args=['banda-teste']), {'q': '98888'})
        self.assertContains(res, 'Sonorização Alpha')

        # 4. Busca por termo inexistente
        res = self.client.get(reverse('parceiros', args=['banda-teste']), {'q': 'InexistenteXYZ'})
        self.assertNotContains(res, 'Sonorização Alpha')
        self.assertNotContains(res, 'Parceiro 1')
        self.assertContains(res, 'Nenhum parceiro encontrado para "InexistenteXYZ".')
        self.assertContains(res, 'Limpar')

    def test_band_view_isolation(self):
        self.client.login(username='outro', password='123')
        # Tenta acessar parceiros da 'banda-teste'
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 403) # PermissionDenied

    def test_admin_access_allowed(self):
        self.client.login(username='admin', password='123')
        response = self.client.get(reverse('admin_painel:parceiros'))
        self.assertEqual(response.status_code, 200)

    def test_admin_header_ui(self):
        self.client.login(username='admin', password='123')
        response = self.client.get(reverse('admin_painel:parceiros'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<nav aria-label="breadcrumb">')
        self.assertContains(response, 'fa-arrow-left')
        self.assertContains(response, reverse('admin_painel:relatorios'))

    def test_formatted_phone(self):
        p1 = Partner(phone='71991733743')
        self.assertEqual(p1.formatted_phone, '(71) 99173-3743')
        
        p2 = Partner(phone='5571991733743')
        self.assertEqual(p2.formatted_phone, '(71) 99173-3743')
        
        p3 = Partner(phone='7133334444')
        self.assertEqual(p3.formatted_phone, '(71) 3333-4444')
        
        # WhatsApp link continua 55...
        self.assertEqual(p1.whatsapp_url, 'https://wa.me/5571991733743')
        self.assertEqual(p2.whatsapp_url, 'https://wa.me/5571991733743')

    def test_admin_access_denied_for_users(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('admin_painel:parceiros'))
        self.assertNotEqual(response.status_code, 200) # redireciona pro login administrativo ou nega

    def test_post_exclusao_restrito(self):
        self.client.login(username='admin', password='123')
        # exclusão por GET bloqueada (não há rota de exclusão que aceite GET e realize, pois só faz redirect)
        response = self.client.get(reverse('admin_painel:parceiros_excluir', args=[self.partner_ativo.id]))
        # Deve ter bloqueado ou redirecionado sem excluir
        self.assertTrue(Partner.objects.filter(id=self.partner_ativo.id).exists())
        
        # via POST exclui
        response = self.client.post(reverse('admin_painel:parceiros_excluir', args=[self.partner_ativo.id]))
        self.assertFalse(Partner.objects.filter(id=self.partner_ativo.id).exists())

    def test_edicao_preserva_imagem(self):
        self.client.login(username='admin', password='123')
        
        image_content = self.generate_test_image()
        image_file = SimpleUploadedFile('test.jpg', image_content, content_type='image/jpeg')
        self.partner_ativo.image = image_file
        self.partner_ativo.save()
        
        response = self.client.post(reverse('admin_painel:parceiros_editar', args=[self.partner_ativo.id]), {
            'name': 'Novo Nome',
            'segment': 'Novo Seg',
            'instagram': '',
            'phone': '',
            'is_active': True
        })
        self.partner_ativo.refresh_from_db()
        self.assertEqual(self.partner_ativo.name, 'Novo Nome')
        self.assertTrue(bool(self.partner_ativo.image)) # imagem mantida

    def test_admin_image_validation(self):
        self.client.login(username='admin', password='123')
        
        # Arquivo inválido (txt)
        bad_file = SimpleUploadedFile('test.txt', b'isso nao e imagem', content_type='text/plain')
        response = self.client.post(reverse('admin_painel:parceiros_novo'), {
            'name': 'P3',
            'segment': 'Seg',
            'image': bad_file,
            'is_active': True
        })
        # Não deve ter criado
        self.assertFalse(Partner.objects.filter(name='P3').exists())
        
        # Arquivo SVG (rejeitado via formato ou extensão)
        svg_file = SimpleUploadedFile('test.svg', b'<svg></svg>', content_type='image/svg+xml')
        response = self.client.post(reverse('admin_painel:parceiros_novo'), {
            'name': 'P3',
            'segment': 'Seg',
            'image': svg_file,
            'is_active': True
        })
        self.assertFalse(Partner.objects.filter(name='P3').exists())
        
        # Imagem correta
        good_image = SimpleUploadedFile('test.jpg', self.generate_test_image(), content_type='image/jpeg')
        response = self.client.post(reverse('admin_painel:parceiros_novo'), {
            'name': 'P3',
            'segment': 'Seg',
            'image': good_image,
            'is_active': True
        })
        self.assertTrue(Partner.objects.filter(name='P3').exists())

    def test_menu_visibility(self):
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        # Checa menu Parceiros acima de Configurações
        # e abaixo de Relatórios
        # Apenas verificamos se o menu Parceiros existe.
        self.assertContains(response, '<i class=\"fa-solid fa-handshake fa-fw me-2')

    def test_navigation_tenant_isolation(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 200)
        
        self.assertEqual(response.context['band'], self.banda)
        
        dashboard_url = reverse('dashboard', args=['banda-teste'])
        self.assertContains(response, dashboard_url)
        
        agenda_url = reverse('calendario', args=['banda-teste'])
        self.assertContains(response, agenda_url)
        
        relatorios_url = reverse('relatorios_index', args=['banda-teste'])
        self.assertContains(response, relatorios_url)
        
        agenda_response = self.client.get(agenda_url)
        self.assertEqual(agenda_response.status_code, 200)
        
        dashboard_response = self.client.get(dashboard_url)
        self.assertEqual(dashboard_response.status_code, 200)
