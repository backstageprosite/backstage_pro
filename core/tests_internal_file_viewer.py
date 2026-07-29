import os
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from core.models import Band, ContractDocument, FinancialReceipt, Show

User = get_user_model()

@override_settings(MEDIA_ROOT='/tmp/django_test_media/')
class InternalFileViewerTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Band A", slug="band-a", is_active=True)
        self.other_band = Band.objects.create(name="Band B", slug="band-b", is_active=True)

        self.admin = User.objects.create_superuser(username="admin", password="password123")
        self.produtor_user = User.objects.create_user(username="prod", password="password123", band=self.band, role='PRODUTOR')
        self.integrante_user = User.objects.create_user(username="membro", password="password123", band=self.band, role='INTEGRANTE')
        self.other_produtor_user = User.objects.create_user(username="other", password="password123", band=self.other_band, role='PRODUTOR')

        self.show = Show.objects.create(band=self.band, title="Show A", date="2026-10-10", show_time="20:00")
        
        pdf_content = b"%PDF-1.4 test content"
        self.contract = ContractDocument.objects.create(
            show=self.show,
            description="Contrato Teste",
            file=SimpleUploadedFile("contrato.pdf", pdf_content, content_type="application/pdf")
        )

        img_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"
        self.receipt = FinancialReceipt.objects.create(
            show=self.show,
            description="Comprovante Teste",
            value=50.0,
            file=SimpleUploadedFile("comprovante.png", img_content, content_type="image/png")
        )

        self.viewer_contract_url = reverse('file_viewer', kwargs={'band_slug': self.band.slug, 'file_type': 'contract', 'pk': self.contract.pk})
        self.viewer_receipt_url = reverse('file_viewer', kwargs={'band_slug': self.band.slug, 'file_type': 'receipt', 'pk': self.receipt.pk})
        
    def tearDown(self):
        for doc in [self.contract.file, self.receipt.file]:
            if doc and default_storage.exists(doc.name):
                try:
                    default_storage.delete(doc.name)
                except PermissionError:
                    pass

    def test_01_admin_access(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response.status_code, 200)

    def test_02_produtor_correct_band(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response.status_code, 200)

    def test_03_produtor_other_band_blocked(self):
        self.client.force_login(self.other_produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response.status_code, 404)

    def test_04_integrante_blocked_contract(self):
        self.client.force_login(self.integrante_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response.status_code, 403)

    def test_05_integrante_blocked_receipt(self):
        self.client.force_login(self.integrante_user)
        response = self.client.get(self.viewer_receipt_url)
        self.assertEqual(response.status_code, 403)

    def test_06_unauthenticated_blocked(self):
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response.status_code, 302)

    def test_07_invalid_type_404(self):
        self.client.force_login(self.produtor_user)
        url = reverse('file_viewer', kwargs={'band_slug': self.band.slug, 'file_type': 'invalid_type', 'pk': self.contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_08_invalid_id_404(self):
        self.client.force_login(self.produtor_user)
        url = reverse('file_viewer', kwargs={'band_slug': self.band.slug, 'file_type': 'contract', 'pk': 9999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_09_incorrect_band_slug_blocked(self):
        self.client.force_login(self.produtor_user)
        url = reverse('file_viewer', kwargs={'band_slug': self.other_band.slug, 'file_type': 'contract', 'pk': self.contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_10_returns_html(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertEqual(response['Content-Type'].lower(), 'text/html; charset=utf-8')

    def test_11_does_not_return_binary(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertNotIn(b"%PDF-1.4 test content", response.content)

    def test_12_contains_x_button(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertContains(response, 'id="btnCloseViewer"')

    def test_13_x_button_aria_label(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertContains(response, 'aria-label="Fechar visualização"')

    def test_14_contains_return_button(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.viewer_contract_url)
        self.assertContains(response, 'id="btnPwaBack"')
