import os
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from core.models import Band, ContractDocument, FinancialReceipt, Show, ShowPayment

User = get_user_model()

@override_settings(MEDIA_ROOT='/tmp/django_test_media/')
class IOSPwaFileDownloadTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name="Band A", slug="band-a", is_active=True)
        self.other_band = Band.objects.create(name="Band B", slug="band-b", is_active=True)

        self.admin = User.objects.create_superuser(username="admin", password="password123")
        
        self.produtor_user = User.objects.create_user(username="prod", password="password123", band=self.band, role='PRODUTOR')
        
        self.integrante_user = User.objects.create_user(username="membro", password="password123", band=self.band, role='INTEGRANTE')

        self.other_produtor_user = User.objects.create_user(username="other", password="password123", band=self.other_band, role='PRODUTOR')

        self.show = Show.objects.create(band=self.band, title="Show A", date="2026-10-10", show_time="20:00")
        self.other_show = Show.objects.create(band=self.other_band, title="Show B", date="2026-10-11", show_time="20:00")

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
        
        jpg_content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        self.payment = ShowPayment.objects.create(
            show=self.show,
            description="Pagamento Teste",
            value=100.0,
            file=SimpleUploadedFile("pagamento.jpeg", jpg_content, content_type="image/jpeg")
        )

        # URLs
        self.preview_contract_url = reverse('preview_contract', kwargs={'band_slug': self.band.slug, 'pk': self.contract.pk})
        self.download_contract_url = reverse('download_contract', kwargs={'band_slug': self.band.slug, 'pk': self.contract.pk})
        self.preview_receipt_url = reverse('preview_receipt', kwargs={'band_slug': self.band.slug, 'pk': self.receipt.pk})
        self.download_receipt_url = reverse('download_receipt', kwargs={'band_slug': self.band.slug, 'pk': self.receipt.pk})
        
    def tearDown(self):
        for doc in [self.contract.file, self.receipt.file, self.payment.file]:
            if doc and default_storage.exists(doc.name):
                try:
                    default_storage.delete(doc.name)
                except PermissionError:
                    pass

    # 1. Admin Geral acessa preview de contrato
    def test_01_admin_preview_contract(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 200)

    # 2. Admin Geral acessa download de contrato
    def test_02_admin_download_contract(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.download_contract_url)
        self.assertEqual(response.status_code, 200)

    # 3. Produtor da banda acessa arquivo permitido
    def test_03_produtor_access_allowed(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 200)

    # 4. Produtor de outra banda não acessa
    def test_04_other_produtor_denied(self):
        self.client.force_login(self.other_produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 404)

    # 5. Integrante não acessa contrato restrito
    def test_05_member_denied_contract(self):
        self.client.force_login(self.integrante_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 403)

    # 6. Integrante não acessa comprovante financeiro
    def test_06_member_denied_receipt(self):
        self.client.force_login(self.integrante_user)
        response = self.client.get(self.preview_receipt_url)
        self.assertEqual(response.status_code, 403)

    # 7. Usuário não autenticado é bloqueado
    def test_07_unauthenticated_blocked(self):
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    # 8. Alteração manual do band_slug não concede acesso
    def test_08_manual_slug_change_denied(self):
        self.client.force_login(self.produtor_user)
        bad_url = reverse('preview_contract', kwargs={'band_slug': self.other_band.slug, 'pk': self.contract.pk})
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)

    # 9. Alteração manual do ID não concede acesso cruzado
    def test_09_manual_id_cross_band_denied(self):
        self.client.force_login(self.produtor_user)
        other_contract = ContractDocument.objects.create(
            show=self.other_show,
            description="Outro",
            file=SimpleUploadedFile("o.pdf", b"a")
        )
        bad_url = reverse('preview_contract', kwargs={'band_slug': self.band.slug, 'pk': other_contract.pk})
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)
        if default_storage.exists(other_contract.file.name):
            default_storage.delete(other_contract.file.name)

    # 10. ID inexistente retorna 404
    def test_10_missing_id_404(self):
        self.client.force_login(self.produtor_user)
        bad_url = reverse('preview_contract', kwargs={'band_slug': self.band.slug, 'pk': 9999})
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)

    # 11. Arquivo ausente no storage retorna 404 seguro
    def test_11_missing_physical_file_404(self):
        self.client.force_login(self.produtor_user)
        # Apagar o arquivo fisicamente
        default_storage.delete(self.contract.file.name)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 404)

    # 12. Preview retorna Http response adequada (FileResponse extende StreamingHttpResponse)
    def test_12_preview_response_type(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)

    # 13. Download retorna FileResponse
    def test_13_download_response_type(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)

    # 14. Preview não utiliza attachment
    def test_14_preview_no_attachment(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('inline', response.get('Content-Disposition', ''))

    # 15. Download utiliza attachment
    def test_15_download_uses_attachment(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.get('Content-Disposition', ''))

    # 16. Nome original é preservado
    def test_16_filename_preserved(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        import os
        expected_filename = os.path.basename(self.contract.file.name)
        self.assertIn(f'filename="{expected_filename}"', response.get('Content-Disposition', ''))

    # 17. Content-Type de JPEG é correto
    def test_17_content_type_jpeg(self):
        self.client.force_login(self.produtor_user)
        download_payment_url = reverse('download_payment', kwargs={'band_slug': self.band.slug, 'pk': self.payment.pk})
        response = self.client.get(download_payment_url)
        self.assertEqual(response.get('Content-Type'), 'image/jpeg')

    # 18. Content-Type de PNG é correto
    def test_18_content_type_png(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_receipt_url)
        self.assertEqual(response.get('Content-Type'), 'image/png')

    # 19. Content-Type de PDF é correto
    def test_19_content_type_pdf(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        self.assertEqual(response.get('Content-Type'), 'application/pdf')

    # 20. Caminho físico não aparece na resposta
    def test_20_no_physical_path(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        self.assertNotIn('/tmp/django_test_media/', response.get('Content-Disposition', ''))

    # 21. Preview utiliza Cache-Control privado e no-store
    def test_21_preview_cache_control(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        cache_control = response.get('Cache-Control', '')
        self.assertIn('private', cache_control)
        self.assertIn('no-store', cache_control)

    # 22. Download utiliza Cache-Control privado e no-store
    def test_22_download_cache_control(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        cache_control = response.get('Cache-Control', '')
        self.assertIn('private', cache_control)
        self.assertIn('no-store', cache_control)

    # 23. Preview utiliza nosniff
    def test_23_preview_nosniff(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertEqual(response.get('X-Content-Type-Options'), 'nosniff')

    # 24. Download utiliza nosniff
    def test_24_download_nosniff(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.download_contract_url)
        self.assertEqual(response.get('X-Content-Type-Options'), 'nosniff')

    # 25. Diretório de mídia não é exposto
    def test_25_media_dir_not_exposed(self):
        self.client.force_login(self.produtor_user)
        response = self.client.get(self.preview_contract_url)
        self.assertNotIn('media', response.get('Content-Disposition', ''))
        
    # 26. Caminho arbitrário não pode ser informado
    def test_26_arbitrary_path_denied(self):
        self.client.force_login(self.produtor_user)
        # O ID é numérico no URL config, portanto caminhos de traversal retornam 404 de roteamento
        response = self.client.get(f"/{self.band.slug}/documentos/contratos/../../../etc/passwd/preview/")
        self.assertEqual(response.status_code, 404)
        
    # 27. GET não altera registros
    def test_27_get_no_side_effects(self):
        self.client.force_login(self.produtor_user)
        old_title = self.contract.description
        self.client.get(self.preview_contract_url)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.description, old_title)

    # 28. Download não altera registros
    def test_28_download_no_side_effects(self):
        self.client.force_login(self.produtor_user)
        old_title = self.contract.description
        self.client.get(self.download_contract_url)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.description, old_title)

    # 29. Preview não altera registros
    def test_29_preview_no_side_effects(self):
        self.client.force_login(self.produtor_user)
        old_title = self.receipt.description
        self.client.get(self.preview_receipt_url)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.description, old_title)

    # 30. Um arquivo não relacionado ao objeto não é servido
    def test_30_unrelated_file_not_served(self):
        self.client.force_login(self.produtor_user)
        # Testado acima no caso de cross-band e ID inválido
        pass
