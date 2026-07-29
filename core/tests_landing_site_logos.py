import io
import os
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from core.models import LandingPageBandLogo, User, Band
import shutil
import tempfile

TEST_MEDIA_ROOT = tempfile.mkdtemp()

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class LandingSiteLogosTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.band = Band.objects.create(name='Test Band', slug='test-band')
        
        self.admin = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        self.admin.band = self.band
        self.admin.save()
        
        self.produtor = User.objects.create_user('produtor', 'produtor@test.com', 'pass', role='PRODUTOR', band=self.band)
        self.integrante = User.objects.create_user('integrante', 'integrante@test.com', 'pass', role='INTEGRANTE', band=self.band)
        
        self.client = Client()

    def create_image(self, size=(1548, 529), fmt='jpeg', color=(255, 0, 0)):
        file = io.BytesIO()
        image = Image.new('RGB', size=size, color=color)
        image.save(file, fmt)
        file.name = f'test.{fmt.lower()}'
        file.seek(0)
        return SimpleUploadedFile(file.name, file.read(), content_type=f'image/{fmt.lower()}')

    def create_fake_file(self, content=b'fake', filename='fake.jpg', content_type='image/jpeg'):
        return SimpleUploadedFile(filename, content, content_type=content_type)
        
    # --- PERMISSÕES DE ACESSO ---

    def test_admin_can_access_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_painel:site_logos'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/admin/site_logos.html')

    def test_produtor_cannot_access_list(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('admin_painel:site_logos'))
        self.assertEqual(response.status_code, 302) # Redireciona para o login por padrão no painel

    def test_integrante_cannot_access_list(self):
        self.client.force_login(self.integrante)
        response = self.client.get(reverse('admin_painel:site_logos'))
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_cannot_access_list(self):
        response = self.client.get(reverse('admin_painel:site_logos'))
        self.assertEqual(response.status_code, 302)

    def test_produtor_cannot_post(self):
        self.client.force_login(self.produtor)
        response = self.client.post(reverse('admin_painel:site_logos'), {'name': 'Banda', 'image': self.create_image()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)

    def test_integrante_cannot_post(self):
        self.client.force_login(self.integrante)
        response = self.client.post(reverse('admin_painel:site_logos'), {'name': 'Banda', 'image': self.create_image()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)

    # --- FORMATOS E DIMENSÕES ---

    def test_add_valid_jpeg(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Banda JPEG',
            'image': self.create_image(fmt='jpeg'),
            'display_order': 0
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)

    def test_add_valid_png(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Banda PNG',
            'image': self.create_image(fmt='png'),
            'display_order': 0
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)

    def test_add_valid_webp(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Banda WebP',
            'image': self.create_image(fmt='webp'),
            'display_order': 0
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)

    def test_add_invalid_size_smaller(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Menor',
            'image': self.create_image(size=(800, 600))
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)
        self.assertIn('A imagem deve possuir exatamente 1548', response.content.decode('utf-8'))

    def test_add_invalid_size_larger(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Maior',
            'image': self.create_image(size=(2000, 1000))
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)

    def test_add_invalid_size_same_ratio(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Proporcao',
            'image': self.create_image(size=(774, 264))
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)

    def test_add_fake_jpg(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Fake',
            'image': self.create_fake_file()
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)
        self.assertIn('O arquivo enviado', response.content.decode('utf-8'))

    def test_add_over_5mb(self):
        self.client.force_login(self.admin)
        valid_image = self.create_image()
        large_content = valid_image.read() + (b'0' * (6 * 1024 * 1024))
        response = self.client.post(reverse('admin_painel:site_logos'), {
            'name': 'Pesado',
            'image': SimpleUploadedFile('large.jpg', large_content, content_type='image/jpeg'),
            'display_order': 0
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)
        self.assertIn('ultrapassar 5MB', response.content.decode('utf-8'))

    # --- EXCLUSÃO ---

    def test_delete_by_post_removes_file(self):
        self.client.force_login(self.admin)
        logo = LandingPageBandLogo.objects.create(name='Delete', image=self.create_image())
        file_path = logo.image.path
        self.assertTrue(os.path.exists(file_path))
        
        response = self.client.post(reverse('admin_painel:site_logos_delete', args=[logo.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 0)
        self.assertFalse(os.path.exists(file_path))

    def test_delete_by_get_prevented(self):
        self.client.force_login(self.admin)
        logo = LandingPageBandLogo.objects.create(name='Keep', image=self.create_image())
        
        response = self.client.get(reverse('admin_painel:site_logos_delete', args=[logo.pk]))
        self.assertEqual(response.status_code, 302) # Redirect default DeleteView behavior if not overriding get properly
        # But we will check if it was not deleted
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)

    def test_produtor_cannot_delete(self):
        self.client.force_login(self.produtor)
        logo = LandingPageBandLogo.objects.create(name='Keep', image=self.create_image())
        response = self.client.post(reverse('admin_painel:site_logos_delete', args=[logo.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)
        
    def test_delete_non_existent(self):
        self.client.force_login(self.admin)
        logo = LandingPageBandLogo.objects.create(name='Keep', image=self.create_image())
        response = self.client.post(reverse('admin_painel:site_logos_delete', args=[9999]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(LandingPageBandLogo.objects.count(), 1)

    # --- LANDING PAGE ---

    def test_landing_page_no_logos(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertNotIn('Bandas e artistas que já utilizam o Backstage Pro', content)

    def test_landing_page_with_logo(self):
        logo = LandingPageBandLogo.objects.create(name='Banda Top', image=self.create_image())
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Bandas e artistas que já utilizam o Backstage Pro', content)
        self.assertIn('Banda Top', content)
        self.assertIn(reverse('landing_logo_image', args=[logo.pk]), content)

    def test_landing_page_order(self):
        logo1 = LandingPageBandLogo.objects.create(name='Banda A', image=self.create_image(), display_order=10)
        logo2 = LandingPageBandLogo.objects.create(name='Banda B', image=self.create_image(), display_order=5)
        response = self.client.get(reverse('home'))
        content = response.content.decode('utf-8')
        idx1 = content.find('Banda A')
        idx2 = content.find('Banda B')
        self.assertTrue(idx2 < idx1)

    # --- IMAGENS PÚBLICAS ---

    def test_public_image_view_valid(self):
        logo = LandingPageBandLogo.objects.create(name='Banda Image', image=self.create_image(fmt='png'))
        response = self.client.get(reverse('landing_logo_image', args=[logo.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')

    def test_public_image_view_invalid(self):
        response = self.client.get(reverse('landing_logo_image', args=[999]))
        self.assertEqual(response.status_code, 404)
