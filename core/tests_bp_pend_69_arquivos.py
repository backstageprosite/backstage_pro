from datetime import date
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from core.models import Band, UserBandMembership, Show, ContractDocument, FinancialReceipt, ShowPayment

User = get_user_model()

class BP_PEND_69_ArquivosTests(TestCase):
    def setUp(self):
        # Create Band 1
        self.band = Band.objects.create(name="Banda Alfa", slug="banda-alfa")
        self.owner = User.objects.create_user(username="owner_alfa", email="owner@alfa.com", password="password123")
        UserBandMembership.objects.create(band=self.band, user=self.owner, role="PRODUTOR", is_active=True)

        # Member (integrante)
        self.member = User.objects.create_user(username="member_alfa", email="member@alfa.com", password="password123")
        UserBandMembership.objects.create(band=self.band, user=self.member, role="INTEGRANTE", is_active=True)

        # Band 2 (isolation test)
        self.band_beta = Band.objects.create(name="Banda Beta", slug="banda-beta")
        self.owner_beta = User.objects.create_user(username="owner_beta", email="owner@beta.com", password="password123")
        UserBandMembership.objects.create(band=self.band_beta, user=self.owner_beta, role="PRODUTOR", is_active=True)

        # Shows for Band 1 in different years/months
        self.show_2026_march = Show.objects.create(
            band=self.band,
            title="Show Março 2026",
            date=date(2026, 3, 15),
            city="São Paulo"
        )
        self.show_2025_december = Show.objects.create(
            band=self.band,
            title="Show Dezembro 2025",
            date=date(2025, 12, 31),
            city="Rio de Janeiro"
        )
        self.show_beta = Show.objects.create(
            band=self.band_beta,
            title="Show Beta",
            date=date(2026, 3, 20),
            city="Curitiba"
        )

    def test_01_documentos_appear_in_arquivos(self):
        doc = ContractDocument.objects.create(
            show=self.show_2026_march,
            description="Contrato Show SP",
            file=SimpleUploadedFile("contrato.pdf", b"dummy content pdf", content_type="application/pdf")
        )
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contrato Show SP")
        self.assertContains(response, "Documentos do Show")

    def test_02_expense_receipt_appears_read_only(self):
        receipt = FinancialReceipt.objects.create(
            show=self.show_2026_march,
            category="Transporte",
            description="Recibo Van",
            value=450.00,
            date=date(2026, 3, 15),
            file=SimpleUploadedFile("recibo_van.pdf", b"van receipt", content_type="application/pdf")
        )
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recibo Van")
        self.assertContains(response, "Gerenciado pelo Financeiro")
        self.assertContains(response, "Comprovantes Financeiros")

    def test_03_payment_receipt_appears_in_arquivos(self):
        payment = ShowPayment.objects.create(
            show=self.show_2026_march,
            description="Sinal 50%",
            value=2500.00,
            expected_date=date(2026, 3, 1),
            receipt_date=date(2026, 3, 1),
            status="RECEBIDO",
            file=SimpleUploadedFile("comprovante_pix.png", b"\x89PNG\r\n\x1a\ndummy", content_type="image/png")
        )
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sinal 50%")
        self.assertContains(response, "Recebimento")

    def test_04_novo_documento_creates_only_contract_document(self):
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        pdf_file = SimpleUploadedFile("rider_tecnico.pdf", b"%PDF-1.4 rider content", content_type="application/pdf")
        post_data = {
            "action": "add_file_global",
            "show_id": self.show_2026_march.id,
            "description": "Rider Técnico SP",
            "file": pdf_file
        }
        response = self.client.post(url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ContractDocument.objects.filter(show=self.show_2026_march, description="Rider Técnico SP").exists())
        self.assertFalse(FinancialReceipt.objects.filter(show=self.show_2026_march, description="Rider Técnico SP").exists())

    def test_05_category_type_receipt_is_ignored_or_rejected_in_arquivos(self):
        # Even if category_type='receipt' is sent to arquivos, it must NOT create FinancialReceipt
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        pdf_file = SimpleUploadedFile("tentativa_recibo.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        post_data = {
            "action": "add_file_global",
            "show_id": self.show_2026_march.id,
            "category_type": "receipt",
            "description": "Tentativa Recibo Global",
            "file": pdf_file
        }
        response = self.client.post(url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FinancialReceipt.objects.filter(show=self.show_2026_march, description="Tentativa Recibo Global").exists())
        self.assertTrue(ContractDocument.objects.filter(show=self.show_2026_march, description="Tentativa Recibo Global").exists())

    def test_06_storage_quota_applies_only_to_contract_document(self):
        # Create 7 ContractDocuments (hitting the limit of 7)
        for i in range(7):
            ContractDocument.objects.create(
                show=self.show_2026_march,
                description=f"Doc {i+1}",
                file=SimpleUploadedFile(f"doc_{i+1}.pdf", b"%PDF-1.4 " + (b"a" * 100), content_type="application/pdf")
            )
        
        # Adding an 8th ContractDocument must fail via arquivos
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        pdf_file = SimpleUploadedFile("doc_8.pdf", b"%PDF-1.4 " + (b"a" * 100), content_type="application/pdf")
        response = self.client.post(url, data={
            "action": "add_file_global",
            "show_id": self.show_2026_march.id,
            "description": "Doc 8",
            "file": pdf_file
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ContractDocument.objects.filter(description="Doc 8").exists())

        # But adding a FinancialReceipt via Financeiro should NOT be blocked by the 7 files limit!
        finance_url = reverse("show_finance_detail", kwargs={"band_slug": self.band.slug, "pk": self.show_2026_march.id})
        receipt_file = SimpleUploadedFile("recibo_gasolina.pdf", b"%PDF-1.4 gasolina", content_type="application/pdf")
        response = self.client.post(finance_url, data={
            "submit_receipt": "1",
            "category": "Transporte",
            "description": "Gasolina Show",
            "value": "120.00",
            "date": "2026-03-15",
            "file": receipt_file
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(FinancialReceipt.objects.filter(show=self.show_2026_march, description="Gasolina Show").exists())

    def test_07_individual_file_size_limit_10mb(self):
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        # 11 MB file
        big_file = SimpleUploadedFile("big.pdf", b"%PDF-1.4 " + (b"0" * (11 * 1024 * 1024)), content_type="application/pdf")
        response = self.client.post(url, data={
            "action": "add_file_global",
            "show_id": self.show_2026_march.id,
            "description": "Arquivo Gigante",
            "file": big_file
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ContractDocument.objects.filter(description="Arquivo Gigante").exists())

    def test_08_band_isolation(self):
        doc_beta = ContractDocument.objects.create(
            show=self.show_beta,
            description="Doc Secreto Beta",
            file=SimpleUploadedFile("beta.pdf", b"beta content", content_type="application/pdf")
        )
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Doc Secreto Beta")
        self.assertNotContains(response, "Show Beta")

    def test_09_member_cannot_access_arquivos(self):
        self.client.login(username="member_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_10_hierarchy_grouping_years_months_shows(self):
        ContractDocument.objects.create(
            show=self.show_2026_march,
            description="Doc Março 2026",
            file=SimpleUploadedFile("doc2026.pdf", b"2026", content_type="application/pdf")
        )
        ContractDocument.objects.create(
            show=self.show_2025_december,
            description="Doc Dezembro 2025",
            file=SimpleUploadedFile("doc2025.pdf", b"2025", content_type="application/pdf")
        )
        self.client.login(username="owner_alfa", password="password123")
        url = reverse("arquivos", kwargs={"band_slug": self.band.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("years_tree", response.context)
        years = [yt["year"] for yt in response.context["years_tree"]]
        self.assertIn(2026, years)
        self.assertIn(2025, years)
        self.assertContains(response, "Show Março 2026")
        self.assertContains(response, "Show Dezembro 2025")
