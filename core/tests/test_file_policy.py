import os
import shutil
import tempfile
import datetime
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, Show, User, ContractDocument, FinancialReceipt, RoomList, Integrante
from django.urls import reverse
from unittest.mock import patch
from django.core.exceptions import ValidationError
from core.file_policy import validate_file_size_and_type, check_show_limits, get_show_files_info

TEMP_MEDIA_ROOT = tempfile.mkdtemp()

@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class FilePolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.band = Band.objects.create(name='Test Band', slug='test-band')
        cls.user = User.objects.create_user(username='produtor', password='123', email='prod@test.com', role='PRODUTOR')
        cls.user.band = cls.band; cls.user.save()
        cls.integrante_user = User.objects.create_user(username='integrante', password='123', email='int@test.com', role='INTEGRANTE')
        cls.integrante_user.band = cls.band; cls.integrante_user.save()
        
        cls.show = Show.objects.create(band=cls.band, date=datetime.date(2026, 10, 10), city='São Paulo')
        cls.room_list = RoomList.objects.create(show=cls.show, band=cls.band, hotel_name='Test Hotel', status='PUBLICADA')

    def tearDown(self):
        ContractDocument.objects.all().delete()
        FinancialReceipt.objects.all().delete()
        for root, dirs, files in os.walk(TEMP_MEDIA_ROOT):
            for file in files:
                try:
                    os.remove(os.path.join(root, file))
                except Exception:
                    pass

    def _create_mock_file(self, size_mb, ext='.pdf'):
        size_bytes = int(size_mb * 1024 * 1024)
        if ext == '.pdf': content = b'%PDF-1.4\n' + b'0' * (size_bytes - 9)
        elif ext in ['.jpg', '.jpeg']: content = b'\xff\xd8\xff' + b'0' * (size_bytes - 3)
        elif ext == '.png': content = b'\x89PNG\r\n\x1a\n' + b'0' * (size_bytes - 8)
        else: content = b'0' * size_bytes
        return SimpleUploadedFile(f"test{ext}", content, content_type='application/octet-stream')

    def test_1_arquivo_exatamente_10mb_aceito(self):
        f = self._create_mock_file(10)
        validate_file_size_and_type(f)

    def test_2_arquivo_acima_10mb_rejeitado(self):
        f = self._create_mock_file(10.1)
        with self.assertRaises(ValidationError):
            validate_file_size_and_type(f)

    def test_3_sete_anexos_aceitos(self):
        for i in range(7):
            ContractDocument.objects.create(show=self.show, description=f'Doc {i}', file=self._create_mock_file(1))
        count, size = get_show_files_info(self.show)
        self.assertEqual(count, 7)

    def test_4_oitavo_anexo_rejeitado(self):
        for i in range(7):
            ContractDocument.objects.create(show=self.show, description=f'Doc {i}', file=self._create_mock_file(1))
        with self.assertRaises(ValidationError):
            check_show_limits(self.show, [1024 * 1024])

    def test_5_limite_continua_funcionando_em_requisicoes_separadas(self):
        for i in range(3):
            ContractDocument.objects.create(show=self.show, description=f'Doc {i}', file=self._create_mock_file(1))
        for i in range(3):
            ContractDocument.objects.create(show=self.show, description=f'Doc {i+3}', file=self._create_mock_file(1))
        # Total is 6. Next 1 is fine.
        check_show_limits(self.show, [1024 * 1024])
        ContractDocument.objects.create(show=self.show, description=f'Doc 6', file=self._create_mock_file(1))
        # Now 8th should fail
        with self.assertRaises(ValidationError):
            check_show_limits(self.show, [1024 * 1024])

    def test_6_total_exatamente_35_mb_aceito(self):

        check_show_limits(self.show, [35 * 1024 * 1024])

    def test_7_total_acima_35_mb_rejeitado(self):
        with self.assertRaises(ValidationError):
            check_show_limits(self.show, [35.1 * 1024 * 1024])

    def test_8_exclusao_libera_uma_vaga(self):
        for i in range(7):
            ContractDocument.objects.create(show=self.show, description=f'Doc {i}', file=self._create_mock_file(1))
        with self.assertRaises(ValidationError):
            check_show_limits(self.show, [1024 * 1024])
        # Delete one
        ContractDocument.objects.first().delete()
        # Now it should pass
        check_show_limits(self.show, [1024 * 1024])

    def test_9_exclusao_libera_espaco_utilizado(self):
        doc = ContractDocument.objects.create(show=self.show, description='Huge', file=self._create_mock_file(20)) # skip 10mb val for DB insert
        # Check if 20MB is rejected (Total would be 40MB)
        with self.assertRaises(ValidationError):
            check_show_limits(self.show, [20 * 1024 * 1024])
        doc.delete()
        # Should now pass
        check_show_limits(self.show, [20 * 1024 * 1024])

    def test_12_extensao_proibida_rejeitada(self):
        f = self._create_mock_file(1, ext='.exe')
        with self.assertRaises(ValidationError):
            validate_file_size_and_type(f)

    def test_13_mime_falso_rejeitado(self):
        # Fake PDF without %PDF header
        content = b'0' * 1024
        f = SimpleUploadedFile("test.pdf", content, content_type='application/pdf')
        with self.assertRaises(ValidationError):
            validate_file_size_and_type(f)

    def test_14_imagem_invalida_jpg_rejeitada(self):
        content = b'Not a JPEG' * 1024
        f = SimpleUploadedFile("test.jpg", content, content_type='image/jpeg')
        with self.assertRaises(ValidationError):
            validate_file_size_and_type(f)

    def test_18_geracao_pdf_agenda_nao_cria_arquivo(self):
        self.client.force_login(self.user)
        initial_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        response = self.client.get(reverse('agenda_pdf', args=[self.band.slug]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        final_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        self.assertEqual(initial_files, final_files)

    def test_19_geracao_pdf_show_nao_cria_arquivo(self):
        self.client.force_login(self.user)
        initial_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        response = self.client.get(reverse('show_pdf', args=[self.band.slug, self.show.id]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        final_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        self.assertEqual(initial_files, final_files)

    def test_20_room_list_comum_nao_cria_arquivo(self):
        self.client.force_login(self.user)
        initial_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.id]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        final_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        self.assertEqual(initial_files, final_files)

    def test_21_room_list_hotel_nao_cria_arquivo(self):
        self.client.force_login(self.user)
        initial_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        response = self.client.get(reverse('room_list_hotel_pdf', args=[self.band.slug, self.room_list.id]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        final_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        self.assertEqual(initial_files, final_files)

    def test_22_gerar_mesmo_pdf_varias_vezes(self):
        self.client.force_login(self.user)
        initial_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        for _ in range(5):
            self.client.get(reverse('show_pdf', args=[self.band.slug, self.show.id]))
        final_files = sum([len(files) for r, d, files in os.walk(TEMP_MEDIA_ROOT)])
        self.assertEqual(initial_files, final_files)
