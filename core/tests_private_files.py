from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import Storage
from unittest.mock import patch, MagicMock
import datetime

class MockNoPathStorage(Storage):
    def open(self, name, mode='rb'):
        # Mock file object that doesn't need to actually exist for path testing
        mock_file = MagicMock()
        mock_file.name = name
        return mock_file
        
    def path(self, name):
        raise NotImplementedError("This storage doesn't support absolute paths.")

from core.models import Band, Show, ContractDocument

User = get_user_model()

class PrivateFilesSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Banda A e B
        self.band_a = Band.objects.create(name="Banda A", slug="banda-a", is_active=True)
        self.band_b = Band.objects.create(name="Banda B", slug="banda-b", is_active=True)
        
        # Produtor da Banda A
        self.user_prod_a = User.objects.create_user(username="prod_a", email="prod_a@test.com", password="123")
        self.user_prod_a.band = self.band_a
        self.user_prod_a.role = 'PRODUTOR'
        self.user_prod_a.save()
        
        # Integrante da Banda A
        self.user_int_a = User.objects.create_user(username="int_a", email="int_a@test.com", password="123")
        self.user_int_a.band = self.band_a
        self.user_int_a.role = 'INTEGRANTE'
        self.user_int_a.save()

        # Produtor da Banda B
        self.user_prod_b = User.objects.create_user(username="prod_b", email="prod_b@test.com", password="123")
        self.user_prod_b.band = self.band_b
        self.user_prod_b.role = 'PRODUTOR'
        self.user_prod_b.save()
        
        # Admin Geral
        self.user_admin = User.objects.create_superuser(username="admin", email="admin@test.com", password="123")
        
        # Show para Banda A
        self.show_a = Show.objects.create(
            band=self.band_a,
            title="Show A",
            date=datetime.date(2026, 10, 10),
            show_time="20:00"
        )
        
        # Arquivo fake
        fake_pdf = SimpleUploadedFile("contrato_teste.pdf", b"conteudo pdf real", content_type="application/pdf")
        self.contract_a = ContractDocument.objects.create(
            show=self.show_a,
            description="Contrato A",
            file=fake_pdf
        )
        
        self.url_download = reverse('download_contract', kwargs={'band_slug': self.band_a.slug, 'pk': self.contract_a.pk})

    def test_unauthenticated_user_redirects_to_login(self):
        """Usuário deslogado não baixa, é redirecionado para login da banda correta."""
        response = self.client.get(self.url_download)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/banda-a/login/', response.url)
        self.assertIn('?next=/banda-a/documentos/contratos/1/download/', response.url)

    def test_cross_band_access_returns_404(self):
        """Produtor da Banda B tenta baixar contrato da Banda A."""
        self.client.login(username="prod_b", password="123")
        # Se usasse reverse de banda-b e pk de banda-a (falsificação)
        url_fake_b = reverse('download_contract', kwargs={'band_slug': self.band_b.slug, 'pk': self.contract_a.pk})
        response = self.client.get(url_fake_b)
        self.assertEqual(response.status_code, 404)
        
        # Tenta acessar URL real da Banda A, mas logado como Produtor B
        response2 = self.client.get(self.url_download)
        self.assertEqual(response2.status_code, 404)

    def test_integrante_access_returns_403(self):
        """Integrante da Banda A tentando baixar documento financeiro da própria banda toma 403."""
        self.client.login(username="int_a", password="123")
        response = self.client.get(self.url_download)
        self.assertEqual(response.status_code, 403)

    def test_admin_access_allowed(self):
        """Admin Master pode baixar independente de banda."""
        self.client.login(username="admin", password="123")
        response = self.client.get(self.url_download)
        self.assertEqual(response.status_code, 200)

    def test_produtor_access_allowed(self):
        """Produtor da Banda A pode baixar Contrato A."""
        self.client.login(username="prod_a", password="123")
        response = self.client.get(self.url_download)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store, no-cache, must-revalidate')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    @patch('django.db.models.fields.files.FieldFile.open')
    def test_file_not_opened_if_access_denied(self, mock_open):
        """Garante que a negação ocorre ANTES de abrir o arquivo."""
        self.client.login(username="int_a", password="123") # 403
        self.client.get(self.url_download)
        mock_open.assert_not_called()

    def test_malicious_svg_html_treated_as_octet_stream(self):
        """MIME type malicioso deve ser retornado como application/octet-stream"""
        from core.file_views import get_safe_mime_type
        self.assertEqual(get_safe_mime_type("teste.svg"), "application/octet-stream")
        self.assertEqual(get_safe_mime_type("teste.html"), "application/octet-stream")
        self.assertEqual(get_safe_mime_type("script.js"), "application/octet-stream")
        self.assertEqual(get_safe_mime_type("data.xml"), "application/octet-stream")
        self.assertEqual(get_safe_mime_type("virus.exe"), "application/octet-stream")
        self.assertEqual(get_safe_mime_type("doc.pdf"), "application/pdf")
        self.assertEqual(get_safe_mime_type("planilha.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(get_safe_mime_type("texto.docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def test_no_media_route(self):
        """Acesso direto à media deve retornar 404"""
        response = self.client.get('/media/contracts/contrato_teste.pdf')
        self.assertEqual(response.status_code, 404)

    def test_file_not_found_in_storage_returns_404(self):
        """Se o registro existe mas o arquivo foi apagado fisicamente, não deve dar 500"""
        self.contract_a.file.storage.delete(self.contract_a.file.name)
        self.client.login(username="prod_a", password="123")
        response = self.client.get(self.url_download)
        self.assertEqual(response.status_code, 404)
        
    def test_sanitize_filename(self):
        """Testa se a função sanitize_filename retira travesters e CRLF."""
        from core.file_views import sanitize_filename
        self.assertEqual(sanitize_filename("valid.pdf"), "valid.pdf")
        self.assertEqual(sanitize_filename("pasta/valid.pdf"), "valid.pdf")
        self.assertEqual(sanitize_filename("pasta\\valid.pdf"), "valid.pdf")
        self.assertEqual(sanitize_filename("../../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("naughty\r\n.pdf"), "naughty.pdf")
        self.assertEqual(sanitize_filename(""), "documento.bin")
        self.assertEqual(sanitize_filename("\r\n"), "documento.bin")
        
    def test_storage_without_path_is_supported(self):
        """MockNoPathStorage impede uso de .path(). Deve provar que as views só usam .open()."""
        # Substitui storage na view
        self.contract_a.file.storage = MockNoPathStorage()
        self.contract_a.save()
        self.client.login(username="prod_a", password="123")
        # Deve baixar sem error 500, testando apenas que abriu
        with patch('django.http.response.FileResponse.set_headers'):
            response = self.client.get(self.url_download)
            self.assertEqual(response.status_code, 200)

    def test_admin_band_logo_only_for_superuser(self):
        """Testa se a rota de logo administrativa é restrita ao Admin Geral e envia headers cache corretos."""
        url = reverse('admin_band_logo', kwargs={'band_slug': self.band_a.slug})
        
        # Deslogado
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        
        # Produtor normal
        self.client.login(username="prod_a", password="123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        
        # Admin Geral
        self.client.login(username="admin", password="123")
        # Se a banda nao tiver logo dá 404 (correto), testamos apenas que ele passou da barreira do admin
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
