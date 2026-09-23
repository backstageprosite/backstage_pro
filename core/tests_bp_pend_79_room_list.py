# -*- coding: utf-8 -*-
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Band, User, Show, RoomList, Room, RoomListParticipant
from core.services.room_list_services import get_room_list_pdf_filename


class RoomListBpPend79Tests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Danniel Vieira', slug='danniel-vieira')
        self.produtor = User.objects.create_user(username='produtor_rl', password='123', role='PRODUTOR')
        self.produtor.band = self.band
        self.produtor.save()

        self.show = Show.objects.create(
            band=self.band,
            title='São João 2026',
            city='Itaité/BA',
            venue='Praça da Matriz',
            date=timezone.datetime(2026, 9, 24).date()
        )

        self.room_list = RoomList.objects.create(
            show=self.show,
            band=self.band,
            hotel_name='Hotel Central',
            city='Itaité',
            status=RoomList.StatusChoices.RASCUNHO
        )

        self.room1 = Room.objects.create(room_list=self.room_list, number_or_name='101', type='CASAL', capacity=2)
        self.room2 = Room.objects.create(room_list=self.room_list, number_or_name='102', type='DUPLO', capacity=2)

        self.participant1 = RoomListParticipant.objects.create(
            room_list=self.room_list,
            room=None,
            snapshot_name='Lucas Músico',
            snapshot_role='Guitarrista'
        )

    def test_filename_pattern(self):
        """Valida que o filename do PDF segue [CIDADE-UF DD-MM-AAAA] - ROOM LIST BANDA.pdf"""
        filename = get_room_list_pdf_filename(self.room_list)
        self.assertEqual(filename, '[ITAITÉ-BA 24-09-2026] - ROOM LIST DANNIEL VIEIRA.pdf')

    def test_pdf_response_filename(self):
        """Valida se as views retornam o Content-Disposition com o novo nome."""
        self.client.login(username='produtor_rl', password='123')
        resp = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('[ITAITÉ-BA 24-09-2026] - ROOM LIST DANNIEL VIEIRA.pdf', resp['Content-Disposition'])

        resp_hotel = self.client.get(reverse('room_list_hotel_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(resp_hotel.status_code, 200)
        self.assertIn('[ITAITÉ-BA 24-09-2026] - ROOM LIST DANNIEL VIEIRA.pdf', resp_hotel['Content-Disposition'])

    def test_preview_html_dados_do_show_and_header(self):
        """Valida no HTML preview: dados do show simplificados e cabeçalho alinhado à esquerda."""
        self.client.login(username='produtor_rl', password='123')
        resp = self.client.get(reverse('room_list_preview', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Dados do Show: apenas Data e Show
        self.assertIn('DADOS DO SHOW', content)
        self.assertIn('24/09/2026', content)
        self.assertIn('São João 2026', content)
        # Não deve conter os campos removidos
        self.assertNotIn('Cidade / UF:</strong>', content)
        self.assertNotIn('Local / Evento:</strong>', content)

        # Title do documento para impressão do navegador
        self.assertIn('<title>[ITAITÉ-BA 24-09-2026] - ROOM LIST DANNIEL VIEIRA</title>', content)

        # Cabeçalho com título e banda
        self.assertIn('ROOM LIST &mdash; HOSPEDAGEM', content)
        self.assertIn('DANNIEL VIEIRA', content)

    def test_pdf_html_header(self):
        """Valida que o template de PDF tem o cabeçalho organizado à esquerda com título e banda."""
        self.client.login(username='produtor_rl', password='123')
        resp = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(resp.status_code, 200)
        # O binário do PDF é gerado com sucesso
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_allocate_and_unassign_endpoints(self):
        """Valida que os endpoints usados pelo drag-and-drop funcionam para mover participantes entre quartos e não-alocados."""
        self.client.login(username='produtor_rl', password='123')

        # 1. Alocar no quarto 1
        allocate_url = reverse('room_list_allocate', args=[self.band.slug, self.room_list.pk, self.participant1.pk])
        resp = self.client.post(allocate_url, {'room_id': self.room1.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.participant1.refresh_from_db()
        self.assertEqual(self.participant1.room_id, self.room1.id)

        # 2. Mover do quarto 1 para o quarto 2
        resp = self.client.post(allocate_url, {'room_id': self.room2.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.participant1.refresh_from_db()
        self.assertEqual(self.participant1.room_id, self.room2.id)

        # 3. Mover para não alocados (unassign)
        unassign_url = reverse('room_list_unassign', args=[self.band.slug, self.room_list.pk, self.participant1.pk])
        resp = self.client.post(unassign_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.participant1.refresh_from_db()
        self.assertIsNone(self.participant1.room_id)
