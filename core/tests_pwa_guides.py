import tempfile
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, User, SystemSettings

class PWAGuidesTest(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Test Band', slug='test-band')
        
        self.admin = User.objects.create_user(username='admin', email='admin@test.com', password='123')
        self.admin.is_superuser = True
        self.admin.save()
        
        self.produtor = User.objects.create_user(username='produtor', email='produtor@test.com', password='123')
        self.produtor.role = 'PRODUTOR'
        self.produtor.band = self.band
        self.produtor.save()
        
        self.integrante = User.objects.create_user(username='integrante', email='integrante@test.com', password='123')
        self.integrante.role = 'INTEGRANTE'
        self.integrante.band = self.band
        self.integrante.save()

    def test_admin_can_access_and_update_guides(self):
        self.client.login(username='admin', password='123')
        
        response = self.client.get(reverse('admin_painel:configuracoes'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ios_installation_guide_image')
        self.assertContains(response, 'android_installation_guide_image')
        
        # Test valid upload
        valid_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\x0c\xcc\x94\x0f\x00\x00\x00\x00IEND\xaeB\x82'
        ios_file = SimpleUploadedFile('ios.png', valid_png, content_type='image/png')
        android_file = SimpleUploadedFile('android.png', valid_png, content_type='image/png')
        
        response = self.client.post(reverse('admin_painel:configuracoes'), {
            'ios_installation_guide_image': ios_file,
            'android_installation_guide_image': android_file,
        })
        
        settings = SystemSettings.get_settings()
        self.assertTrue(bool(settings.ios_installation_guide_image))
        self.assertTrue(bool(settings.android_installation_guide_image))
        
    def test_produtor_accesses_install_page(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('instalar_aplicativo', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Como instalar o aplicativo')
        self.assertContains(response, 'installGuideModal')
        
    def test_integrante_accesses_install_page(self):
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('instalar_aplicativo', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Como instalar o aplicativo')
        
    def test_unauthorized_user_is_blocked(self):
        other_user = User.objects.create_user(username='other', email='other@test.com', password='123')
        other_band = Band.objects.create(name='Other', slug='other')
        other_user.band = other_band
        other_user.save()
        
        self.client.login(username='other', password='123')
        response = self.client.get(reverse('instalar_aplicativo', args=[self.band.slug]))
        self.assertEqual(response.status_code, 403)
