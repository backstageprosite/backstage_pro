from django.test import TestCase, Client
from django.urls import reverse
from core.models import Partner, Band, User
from django.core.files.uploadedfile import SimpleUploadedFile

class PartnerTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Criação de usuários e banda
        self.banda = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.outra_banda = Band.objects.create(name='Banda Dois', slug='banda-dois')
        
        self.admin = User.objects.create_superuser('admin', 'admin@test.com', '123')
        
        self.produtor = User.objects.create_user('produtor', 'produtor@test.com', '123')
        self.produtor.role = 'PRODUTOR'
        self.produtor.band = self.banda
        self.produtor.save()
        
        self.integrante = User.objects.create_user('integrante', 'integrante@test.com', '123')
        self.integrante.role = 'INTEGRANTE'
        self.integrante.band = self.banda
        self.integrante.save()
        
        self.outra_banda_user = User.objects.create_user('outro', 'outro@test.com', '123')
        self.outra_banda_user.role = 'PRODUTOR'
        self.outra_banda_user.band = self.outra_banda
        self.outra_banda_user.save()
        
        # Parceiros
        self.image_mock = SimpleUploadedFile(name='test_image.jpg', content=b'', content_type='image/jpeg')
        self.partner_ativo = Partner.objects.create(
            name='Parceiro 1',
            segment='Equipamento',
            instagram='@parceiro1',
            phone='(71) 99999-9999',
            image=self.image_mock,
            is_active=True
        )
        self.partner_inativo = Partner.objects.create(
            name='Parceiro 2',
            segment='Agência',
            is_active=False
        )

    def test_model_fields_and_methods(self):
        self.assertEqual(str(self.partner_ativo), 'Parceiro 1')
        self.assertTrue(self.partner_ativo.is_active)
        self.assertFalse(self.partner_inativo.is_active)
        
        # Test normalizations
        self.assertEqual(self.partner_ativo.instagram_url, 'https://www.instagram.com/parceiro1/')
        self.assertEqual(self.partner_ativo.instagram_display, '@parceiro1')
        self.assertEqual(self.partner_ativo.whatsapp_url, 'https://wa.me/5571999999999')
        
        p3 = Partner.objects.create(name='P3', segment='S', instagram='instagram.com/foo/', phone='71988888888')
        self.assertEqual(p3.instagram_url, 'https://www.instagram.com/foo/')
        self.assertEqual(p3.whatsapp_url, 'https://wa.me/5571988888888')

    def test_admin_access_allowed(self):
        self.client.login(username='admin', password='123')
        response = self.client.get(reverse('admin_painel:parceiros'))
        self.assertEqual(response.status_code, 200)

    def test_admin_access_denied_for_users(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('admin_painel:parceiros'))
        self.assertNotEqual(response.status_code, 200)

    def test_band_view_access(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parceiro 1')
        self.assertNotContains(response, 'Parceiro 2')  # Inativo
        
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 200)

    def test_band_view_isolation(self):
        self.client.login(username='outro', password='123')
        # Tenta acessar parceiros da 'banda-teste'
        response = self.client.get(reverse('parceiros', args=['banda-teste']))
        self.assertEqual(response.status_code, 403) # PermissionDenied
