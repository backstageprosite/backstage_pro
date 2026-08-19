# -*- coding: utf-8 -*-
"""
Testes de integração para:
  - PDF Room List comum (sem CPF)
  - PDF Room List para Hotel (com CPF)
  - Exclusão de quarto
  - Botão Ver Hospedagem no Show Detail (Integrante)
  - Botão Voltar em Form e Manage
  - Link Room List no PDF do Show
"""
from django.test import TestCase
from django.urls import reverse
from core.models import Band, User, Show, RoomList, Room, RoomListParticipant
from django.utils import timezone


class RoomListPdfAndHotelTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.band2 = Band.objects.create(name='Outra Banda', slug='outra-banda')

        self.produtor = User.objects.create_user(username='produtor', password='123', role='PRODUTOR')
        self.produtor.band = self.band
        self.produtor.save()

        self.integrante = User.objects.create_user(username='integrante', password='123', role='INTEGRANTE')
        self.integrante.band = self.band
        self.integrante.save()

        self.outra_banda_user = User.objects.create_user(username='outro', password='123', role='PRODUTOR')
        self.outra_banda_user.band = self.band2
        self.outra_banda_user.save()

        self.show = Show.objects.create(band=self.band, title='Show 1', date=timezone.now().date())

        self.room_list = RoomList.objects.create(
            show=self.show,
            band=self.band,
            hotel_name="Hotel Test",
            city="City",
            status=RoomList.StatusChoices.RASCUNHO
        )

        self.room = Room.objects.create(room_list=self.room_list, number_or_name="101", type="CASAL", capacity=2)

        self.participant1 = RoomListParticipant.objects.create(
            room_list=self.room_list,
            room=self.room,
            snapshot_name="Joao",
            snapshot_role="Cantor",
            snapshot_cpf="11122233344"
        )

        self.participant2 = RoomListParticipant.objects.create(
            room_list=self.room_list,
            room=self.room,
            snapshot_name="Maria",
            snapshot_role="Baterista",
            snapshot_cpf=""
        )

    # ==== PDF comum ====

    def test_pdf_comum_produtor_rascunho(self):
        """Produtor pode acessar PDF de rascunho. Resposta é PDF binário sem CPF."""
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_comum_integrante_rascunho_bloqueado(self):
        """Integrante não pode acessar PDF em rascunho."""
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 403)

    def test_pdf_comum_integrante_publicada_permitido(self):
        """Integrante pode acessar PDF quando publicado. Resposta deve ser PDF real."""
        self.room_list.status = RoomList.StatusChoices.PUBLICADA
        self.room_list.save()
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="room_list.pdf"')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_comum_outra_banda_bloqueado(self):
        """Usuário de outra banda não pode acessar o PDF."""
        self.client.login(username='outro', password='123')
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 403)

    # ==== PDF para Hotel ====

    def test_pdf_hotel_produtor_permitido(self):
        """Produtor pode acessar PDF para Hotel. Deve ser PDF binário com headers corretos."""
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('room_list_hotel_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="room_list.pdf"')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow, noarchive')

    def test_pdf_hotel_integrante_bloqueado(self):
        """Integrante não pode acessar PDF para Hotel nem quando publicada."""
        self.room_list.status = RoomList.StatusChoices.PUBLICADA
        self.room_list.save()
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('room_list_hotel_pdf', args=[self.band.slug, self.room_list.pk]))
        self.assertEqual(response.status_code, 403)

    # ==== Exclusão de Quarto ====

    def test_excluir_quarto_get_not_allowed(self):
        """GET para exclusão de quarto retorna 405 (POST only)."""
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('delete_room', args=[self.band.slug, self.room.pk]))
        self.assertEqual(response.status_code, 405)

    def test_excluir_quarto_produtor_sucesso(self):
        """Produtor pode excluir quarto em Rascunho. Ocupantes voltam para Não Alocados."""
        self.client.login(username='produtor', password='123')
        response = self.client.post(reverse('delete_room', args=[self.band.slug, self.room.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Room.objects.filter(pk=self.room.pk).exists())
        self.participant1.refresh_from_db()
        self.assertIsNone(self.participant1.room)

    def test_excluir_quarto_integrante_bloqueado(self):
        """Integrante não pode excluir quarto."""
        self.client.login(username='integrante', password='123')
        response = self.client.post(reverse('delete_room', args=[self.band.slug, self.room.pk]))
        self.assertEqual(response.status_code, 403)

    def test_excluir_quarto_publicada_bloqueado(self):
        """Não é possível excluir quarto de Room List Publicada — quarto é preservado."""
        self.room_list.status = RoomList.StatusChoices.PUBLICADA
        self.room_list.save()
        self.client.login(username='produtor', password='123')
        response = self.client.post(reverse('delete_room', args=[self.band.slug, self.room.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    # ==== Botão Ver Hospedagem (Show Detail — Integrante) ====

    def test_botao_integrante_show_detail_publicada(self):
        """Integrante vê link para PDF comum (não para Gerenciar) quando publicada."""
        self.room_list.status = RoomList.StatusChoices.PUBLICADA
        self.room_list.save()
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('show_detail', args=[self.band.slug, self.show.pk]))
        self.assertEqual(response.status_code, 200)
        content_utf8 = response.content.decode('utf-8', errors='ignore')
        pdf_url = reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk])
        self.assertIn(pdf_url, content_utf8)
        manage_url = reverse('room_list_manage', args=[self.band.slug, self.room_list.pk])
        self.assertNotIn(manage_url + '"', content_utf8)

    def test_botao_integrante_show_detail_rascunho(self):
        """Integrante não vê link de hospedagem quando Room List está em Rascunho."""
        self.client.login(username='integrante', password='123')
        response = self.client.get(reverse('show_detail', args=[self.band.slug, self.show.pk]))
        self.assertEqual(response.status_code, 200)
        content_utf8 = response.content.decode('utf-8', errors='ignore')
        pdf_url = reverse('room_list_pdf', args=[self.band.slug, self.room_list.pk])
        self.assertNotIn(pdf_url, content_utf8)

    # ==== Botão Voltar (Room List Form e Manage) ====

    def test_botao_voltar_form_e_manage(self):
        """Botão Voltar em Form e Manage aponta para room_list_index."""
        self.client.login(username='produtor', password='123')
        index_url = reverse('room_list_index', args=[self.band.slug])

        response = self.client.get(reverse('room_list_edit', args=[self.band.slug, self.room_list.pk]))
        content_utf8 = response.content.decode('utf-8', errors='ignore')
        self.assertIn(index_url, content_utf8)

        response = self.client.get(reverse('room_list_manage', args=[self.band.slug, self.room_list.pk]))
        content_utf8 = response.content.decode('utf-8', errors='ignore')
        self.assertIn(index_url, content_utf8)

    # ==== Link no PDF do Show ====

    def test_link_pdf_show_com_room_list_publicada(self):
        """PDF do Show exibe link para Room List quando publicada, nunca para hotel PDF."""
        self.room_list.status = RoomList.StatusChoices.PUBLICADA
        self.room_list.save()
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('show_pdf', args=[self.band.slug, self.show.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8', errors='ignore')
        self.assertIn('Room List: Visualizar PDF', content)
        self.assertNotIn('pdf/hotel', content)

    def test_link_pdf_show_sem_room_list_publicada(self):
        """PDF do Show não exibe link para Room List quando em Rascunho."""
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('show_pdf', args=[self.band.slug, self.show.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8', errors='ignore')
        self.assertNotIn('Room List: Visualizar PDF', content)
