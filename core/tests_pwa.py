import json
from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band

class PWAManifestTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Cria Banda A ativa sem logo
        self.band_a = Band.objects.create(
            name="Banda Danniel Vieira",
            slug="dannielvieira",
            is_active=True
        )
        
        # Cria Banda B ativa (logo mockada no teste se precisar)
        self.band_b = Band.objects.create(
            name="Banda Mambolada 2026",
            slug="mambolada",
            is_active=True
        )
        
        # Cria Banda inativa
        self.band_inactive = Band.objects.create(
            name="Banda Parada",
            slug="parada",
            is_active=False
        )
        
        # Cria banda com nome muito longo
        self.band_long_name = Band.objects.create(
            name="SuperextraordinariamenteGigante",
            slug="longa",
            is_active=True
        )

    def test_active_band_manifest(self):
        """Testa se o manifest de uma banda ativa responde corretamente."""
        response = self.client.get(f'/{self.band_a.slug}/manifest.webmanifest')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        
        data = json.loads(response.content)
        
        self.assertEqual(data['name'], "Banda Danniel Vieira")
        self.assertEqual(data['short_name'], "Banda Danniel Vieira") # <= 20 chars
        self.assertEqual(data['id'], f"/{self.band_a.slug}/")
        self.assertEqual(data['scope'], f"/{self.band_a.slug}/")
        self.assertTrue(data['start_url'].startswith(f"/{self.band_a.slug}/painel/"))
        self.assertEqual(data['theme_color'], "#6BD443")
        self.assertEqual(data['display'], "standalone")
        self.assertEqual(data['lang'], "pt-BR")
        
        # Verifica se icons existem
        self.assertIn("icons", data)
        self.assertEqual(len(data['icons']), 4)
        
        # Verifica propósitos
        purposes = [icon['purpose'] for icon in data['icons']]
        self.assertIn("any", purposes)
        self.assertIn("maskable", purposes)
        
        # Verifica apple-touch-icon (não deve estar no manifest)
        filenames = [icon['src'] for icon in data['icons']]
        self.assertFalse(any('apple-touch-icon' in f for f in filenames))

    def test_nonexistent_band_manifest(self):
        """Testa se banda inexistente retorna 404."""
        response = self.client.get('/banda-fantasma/manifest.webmanifest')
        self.assertEqual(response.status_code, 404)

    def test_inactive_band_manifest(self):
        """Testa se banda inativa retorna 404."""
        response = self.client.get(f'/{self.band_inactive.slug}/manifest.webmanifest')
        self.assertEqual(response.status_code, 404)

    def test_band_isolation(self):
        """Testa o isolamento entre duas bandas diferentes."""
        response_a = self.client.get(f'/{self.band_a.slug}/manifest.webmanifest')
        data_a = json.loads(response_a.content)
        
        response_b = self.client.get(f'/{self.band_b.slug}/manifest.webmanifest')
        data_b = json.loads(response_b.content)
        
        self.assertNotEqual(data_a['name'], data_b['name'])
        self.assertNotEqual(data_a['id'], data_b['id'])
        self.assertNotEqual(data_a['scope'], data_b['scope'])
        self.assertEqual(data_a['id'], "/dannielvieira/")
        self.assertEqual(data_b['id'], "/mambolada/")

    def test_admin_manifest(self):
        """Testa se o manifest administrativo responde corretamente e está isolado."""
        response = self.client.get('/painel/manifest.webmanifest')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        
        data = json.loads(response.content)
        
        self.assertEqual(data['name'], "Backstage Pro")
        self.assertEqual(data['short_name'], "Backstage Pro")
        self.assertEqual(data['id'], "/painel/")
        self.assertEqual(data['scope'], "/painel/")
        self.assertTrue(data['start_url'].startswith("/painel/"))
        
        self.assertIn("icons", data)
        self.assertEqual(len(data['icons']), 4)
        # Os ícones admin são estáticos
        for icon in data['icons']:
            self.assertIn('/static/core/pwa/icons/backstage-icon', icon['src'])
        
    def test_route_conflict_avoidance(self):
        """
        Garante que a rota administrativa não caia na view da banda por engano.
        Se cair na view da banda, retornaria 404 porque não existe banda 'painel'.
        Mas deve retornar 200 e abrir o manifest admin.
        """
        response = self.client.get('/painel/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['name'], "Backstage Pro")

    def test_short_name_logic(self):
        """
        Testa a função get_short_name para garantir que não
        corta palavras pela metade, a não ser que a única palavra exceda 20 chars.
        """
        from core.pwa_views import get_short_name
        
        self.assertEqual(get_short_name("Banda Curta"), "Banda Curta")
        self.assertEqual(get_short_name("  Banda Com Espacos  "), "Banda Com Espacos")
        
        # Palavra gigante única
        self.assertEqual(get_short_name("SuperextraordinariamenteGigante"), "Superextraordinariam") # 20 chars
        
        # Várias palavras ultrapassando 20
        self.assertEqual(get_short_name("Banda Muito Longa Da Silva Sauro"), "Banda Muito Longa") # corta no espaço antes de 20 chars

    def test_band_icon_fallback(self):
        """Testa se banda sem logo retorna o fallback do Backstage Pro com status 200."""
        # band_a não tem logo
        response = self.client.get(f'/{self.band_a.slug}/pwa/icon-192.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        
    def test_invalid_icon_size(self):
        """Testa tentativa de pedir tamanho malicioso."""
        response = self.client.get(f'/{self.band_a.slug}/pwa/icon-9999.png')
        self.assertEqual(response.status_code, 404)
        
    def test_band_icon_inactive(self):
        """Testa se ícone da banda inativa retorna 404."""
        response = self.client.get(f'/{self.band_inactive.slug}/pwa/icon-192.png')
        self.assertEqual(response.status_code, 404)

    def test_icon_size_limit(self):
        """Testa comportamento quando a imagem excede o limite."""
        from core.pwa_utils import MAX_PWA_LOGO_BYTES, generate_band_icon
        from unittest.mock import MagicMock
        
        mock_logo = MagicMock()
        mock_logo.name = "big_file.png"
        mock_logo.size = MAX_PWA_LOGO_BYTES + 1
        
        # Como é maior, deve retornar None
        result = generate_band_icon(mock_logo, 192)
        self.assertIsNone(result)

    def test_decompression_bomb_warning(self):
        """Testa conversão de DecompressionBombWarning para erro e fallback."""
        from PIL import Image
        from unittest.mock import patch, MagicMock
        from core.pwa_utils import generate_band_icon
        
        mock_logo = MagicMock()
        mock_logo.name = "bomb.png"
        mock_logo.size = 100  # Passa o limite de bytes
        
        # Mock do storage para abrir
        with patch('core.models.Band.logo.field.storage.open') as mock_open:
            mock_f = MagicMock()
            mock_f.read.return_value = b"fake data"
            mock_logo.open.return_value.__enter__.return_value = mock_f
            
            # Simula que o Pillow dispara o warning no verify ou open
            with patch('PIL.Image.open') as mock_image_open:
                mock_img = MagicMock()
                # O mock dispara o Warning ao chamar verify()
                mock_img.verify.side_effect = Image.DecompressionBombWarning("Imagem gigante")
                mock_image_open.return_value = mock_img
                
                # Se o filtro funcionar, o warning vira exceção que é capturada, retornando None
                result = generate_band_icon(mock_logo, 192)
                self.assertIsNone(result)

    def test_versioning_strategy(self):
        """Testa a geração determinística do token de versão."""
        from core.pwa_views import get_band_icon_version
        from unittest.mock import MagicMock
        
        band = MagicMock()
        band.logo = None
        token_fb, rel_fb = get_band_icon_version(band)
        self.assertEqual(token_fb, "fallback")
        self.assertTrue(rel_fb)
        
        band.logo = MagicMock()
        band.logo.name = "logo1.png"
        band.logo.size = 1024
        band.logo.storage.get_modified_time.return_value = None
        
        token1, rel1 = get_band_icon_version(band)
        # Tamanho sem mtime = is_reliable False
        self.assertFalse(rel1)
        
        band.logo.size = 2048
        token2, rel2 = get_band_icon_version(band)
        self.assertFalse(rel2)
        
        self.assertNotEqual(token1, token2)
        
        # Com mtime = is_reliable True
        import datetime
        band.logo.storage.get_modified_time.return_value = datetime.datetime.now()
        token3, rel3 = get_band_icon_version(band)
        self.assertTrue(rel3)

    def test_band_service_worker(self):
        """Testa se o SW da banda responde corretamente e isolado."""
        response = self.client.get(f'/{self.band_a.slug}/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/javascript; charset=utf-8')
        self.assertEqual(response['Cache-Control'], 'no-cache, no-store, must-revalidate')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Service-Worker-Allowed'], f'/{self.band_a.slug}/')
        self.assertContains(response, f'"{self.band_a.slug}-v2"')
        self.assertContains(response, f'"/{self.band_a.slug}/"')
        self.assertNotContains(response, self.band_b.slug)
        self.assertNotContains(response, 'skipWaiting')
        self.assertNotContains(response, 'clients.claim')

    def test_admin_service_worker(self):
        """Testa se o SW administrativo responde corretamente e isolado."""
        response = self.client.get('/painel/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/javascript; charset=utf-8')
        self.assertEqual(response['Service-Worker-Allowed'], '/painel/')
        self.assertContains(response, '"backstage-admin-v1"')
        self.assertContains(response, '"/painel/"')
        self.assertNotContains(response, self.band_a.slug)

    def test_sw_isolation(self):
        """Testa o isolamento de rotas de SW entre as bandas."""
        response_a = self.client.get(f'/{self.band_a.slug}/sw.js')
        response_b = self.client.get(f'/{self.band_b.slug}/sw.js')
        
        self.assertEqual(response_a['Service-Worker-Allowed'], f'/{self.band_a.slug}/')
        self.assertEqual(response_b['Service-Worker-Allowed'], f'/{self.band_b.slug}/')
        self.assertNotEqual(response_a.content, response_b.content)

    def test_sw_inactive_and_ghost_bands(self):
        """Banda inativa ou fantasma deve retornar 404 pro SW."""
        self.assertEqual(self.client.get(f'/{self.band_inactive.slug}/sw.js').status_code, 404)
        self.assertEqual(self.client.get('/banda-fantasma/sw.js').status_code, 404)

    def test_pwa_meta_tags_band_login(self):
        """Testa se as metatags PWA corretas estão presentes no login da banda."""
        response = self.client.get(f'/{self.band_a.slug}/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<link rel="manifest" href="/{self.band_a.slug}/manifest.webmanifest">')
        self.assertContains(response, '<meta name="theme-color" content="#6BD443">')
        self.assertContains(response, '<meta name="apple-mobile-web-app-capable" content="yes">')
        self.assertContains(response, '<meta name="apple-mobile-web-app-status-bar-style" content="default">')
        self.assertContains(response, '<meta name="apple-mobile-web-app-title" content="Banda Danniel Vieira">')
        self.assertContains(response, f'<link rel="apple-touch-icon" href="/{self.band_a.slug}/pwa/apple-touch-icon.png?v=')
        self.assertNotContains(response, '/painel/manifest.webmanifest')

    def test_pwa_meta_tags_admin_login(self):
        """Testa se as metatags do admin estão presentes no login administrativo."""
        response = self.client.get('/painel/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="manifest" href="/painel/manifest.webmanifest">')
        self.assertContains(response, '<meta name="apple-mobile-web-app-title" content="Backstage Pro">')
        self.assertContains(response, '<link rel="apple-touch-icon" href="/static/core/pwa/icons/backstage-apple-touch-icon.png')
        self.assertNotContains(response, 'href="/manifest.webmanifest">') # Should not just match randomly

    def test_landing_page_no_manifest(self):
        """Landing page pública não deve conter PWA tags."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<link rel="manifest"')
        self.assertNotContains(response, 'apple-mobile-web-app-capable')
        self.assertNotContains(response, 'pwa-register.js')

    def test_admin_master_no_manifest(self):
        """Django Admin nativo não deve ser afetado."""
        response = self.client.get('/admin-master/login/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<link rel="manifest"')
        self.assertNotContains(response, 'pwa-register.js')

    def test_xss_band_name(self):
        """Testa se nome de banda com caracteres sensíveis HTML é devidamente escapado."""
        band_xss = Band.objects.create(
            name='Banda "Teste" & <script>alert(1)</script>',
            slug="xss",
            is_active=True
        )
        response = self.client.get(f'/{band_xss.slug}/login/')
        self.assertEqual(response.status_code, 200)
        
        # O Django auto-escapa as aspas para &quot;, o & para &amp; e os brackets para &lt; e &gt;
        # Portanto, o título esperado na meta tag será:
        from django.utils.html import escape
        from core.pwa_views import get_short_name
        expected_title = escape(get_short_name(band_xss.name))
        self.assertContains(response, f'<meta name="apple-mobile-web-app-title" content="{expected_title}">')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_pwa_install_button_band(self):
        """Testa se o botão de instalação aparece nas bandas, mas não na landing ou admin."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(username='test', password='123')
        user.band_id = self.band_a.id
        user.save()
        self.client.login(username='test', password='123')
        
        response = self.client.get(f'/{self.band_a.slug}/calendario/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pwa-install-btn"')
        self.assertContains(response, 'Instalar aplicativo')
        self.assertContains(response, 'pwa-install.js')
        self.assertContains(response, 'iosInstallModal')
        self.assertNotContains(response, 'Instalar Backstage Pro')
        
    def test_pwa_install_button_admin(self):
        """Testa se o botão de instalação do admin reflete Backstage Pro."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_superuser(username='admin', password='123', email='admin@test.com')
        self.client.login(username='admin', password='123')
        
        response = self.client.get('/painel/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pwa-install-btn"')
        self.assertContains(response, 'Instalar Backstage Pro')
        self.assertContains(response, 'pwa-install.js')
        self.assertContains(response, 'iosInstallModal')
        self.assertNotContains(response, 'Instalar aplicativo')

    def test_pwa_install_button_landing_and_admin_master(self):
        """Testa se a página inicial e admin-master não possuem o botão."""
        response_landing = self.client.get('/')
        self.assertNotContains(response_landing, 'id="pwa-install-btn"')
        self.assertNotContains(response_landing, 'pwa-install.js')
        
        response_master = self.client.get('/admin-master/login/')
        self.assertNotContains(response_master, 'id="pwa-install-btn"')
        self.assertNotContains(response_master, 'pwa-install.js')

    def test_install_script_contains_standalone_logic(self):
        """Testa o conteúdo estático do pwa-install.js."""
        from django.conf import settings
        import os
        js_path = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', 'pwa', 'pwa-install.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('beforeinstallprompt', content)
        self.assertIn('appinstalled', content)
        self.assertIn('(display-mode: standalone)', content)
        self.assertIn('navigator.standalone', content)
        self.assertIn('iosInstallModal', content)
        # Check that it doesn't use generic push or caches
        self.assertNotIn('caches.open', content)
        self.assertNotIn('Notification.requestPermission', content)

    def test_pwa_icon_background_is_white(self):
        """Testa se o fundo do ícone PWA gerado é branco."""
        from PIL import Image
        import io
        from django.conf import settings
        import os
        
        # Cria uma imagem simulada preta de 100x100
        img = Image.new('RGB', (100, 100), 'black')
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.band_a.logo = SimpleUploadedFile('test_logo.png', img_io.read(), content_type='image/png')
        self.band_a.save()
        
        # Testa a geração dinâmica (Banda)
        response = self.client.get(f'/{self.band_a.slug}/pwa/icon-192.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        
        generated_img = Image.open(io.BytesIO(response.content))
        self.assertEqual(generated_img.size, (192, 192))
        
        # Testa os 4 cantos para confirmar fundo branco
        white = (255, 255, 255)
        self.assertEqual(generated_img.getpixel((0, 0)), white)
        self.assertEqual(generated_img.getpixel((191, 0)), white)
        self.assertEqual(generated_img.getpixel((0, 191)), white)
        self.assertEqual(generated_img.getpixel((191, 191)), white)
        
        # Confirma ausência do verde antigo #6BD443 (107, 212, 67)
        old_green = (107, 212, 67)
        self.assertNotEqual(generated_img.getpixel((0, 0)), old_green)
        
        # O centro deve ter pixel preto da logo mockada
        self.assertEqual(generated_img.getpixel((96, 96)), (0, 0, 0))

        # Testa o ícone estático (Backstage Pro)
        static_icon_path = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', 'pwa', 'icons', 'backstage-icon-192.png')
        self.assertTrue(os.path.exists(static_icon_path))
        static_img = Image.open(static_icon_path)
        self.assertEqual(static_img.size, (192, 192))
        
        # Verifica fundo branco no ícone estático
        self.assertEqual(static_img.getpixel((0, 0)), white)
        self.assertNotEqual(static_img.getpixel((0, 0)), old_green)


