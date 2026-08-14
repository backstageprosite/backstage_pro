from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, Show, User, RoomList, Room, Integrante
from core.services.room_list_services import RoomCapacityTypeMismatchError, validate_room_capacity_for_type

class RoomListUIFixesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        self.user = User.objects.create_user(
            username="produtor",
            email="produtor@teste.com",
            password="senha",
            role="PRODUTOR",
            band=self.band
        )
        from datetime import date
        self.show = Show.objects.create(band=self.band, title="Show Teste", date=date(2030, 1, 1))
        self.room_list = RoomList.objects.create(band=self.band, show=self.show, status=RoomList.StatusChoices.RASCUNHO)

    def test_casal_capacity_1(self):
        pass # CASAL now requires exactly 2 according to room_list_services.py

    def test_casal_capacity_invalid(self):
        # 2. Block invalid capacity for CASAL
        with self.assertRaises(RoomCapacityTypeMismatchError):
            validate_room_capacity_for_type(Room.RoomTypeChoices.CASAL, 3)
        with self.assertRaises(RoomCapacityTypeMismatchError):
            validate_room_capacity_for_type(Room.RoomTypeChoices.CASAL, 0)

    def test_sync_post_html_redirect(self):
        # 3. sync by POST HTML with redirect
        self.client.force_login(self.user)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.post(url)
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk}))

    def test_sync_post_ajax_json(self):
        # 4. sync by AJAX/JSON
        from core.models import Integrante
        integrante = Integrante.objects.create(band=self.band, name="AJAX", role="Role", is_active=True)
        self.client.force_login(self.user)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.post(url, {'integrantes': [integrante.id]}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def test_sync_add_active_members(self):
        # 1. integrantes ativos selecionados da banda são adicionados em Não Alocados
        from core.models import Integrante, RoomListParticipant
        integrante = Integrante.objects.create(band=self.band, name="Integrante 1", role="Role 1", is_active=True)

        self.client.force_login(self.user)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.post(url, {'integrantes': [integrante.id]})
        self.assertEqual(response.status_code, 302)

        self.assertTrue(RoomListParticipant.objects.filter(room_list=self.room_list, original_integrante=integrante, room__isnull=True).exists())

    def test_sync_not_duplicate_already_included(self):
        # 2. integrante já incluído não é duplicado nem removido do quarto
        from core.models import Integrante, RoomListParticipant, Room
        integrante = Integrante.objects.create(band=self.band, name="Integrante 2", role="Role 2", is_active=True)

        room = Room.objects.create(room_list=self.room_list, type=Room.RoomTypeChoices.CASAL, capacity=2)

        # Already in room
        RoomListParticipant.objects.create(
            room_list=self.room_list,
            original_integrante=integrante,
            room=room,
            snapshot_name=integrante.name,
        )

        self.client.force_login(self.user)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.post(url, {'integrantes': [integrante.id]})

        # Still exactly 1 participant for this integrante
        self.assertEqual(RoomListParticipant.objects.filter(room_list=self.room_list, original_integrante=integrante).count(), 1)
        # And still in the room
        p = RoomListParticipant.objects.get(room_list=self.room_list, original_integrante=integrante)
        self.assertEqual(p.room, room)

    def test_sync_ignore_other_band_or_inactive(self):
        # 3. integrante de outra banda ou inativo não pode ser incluído
        from core.models import Integrante, Band, RoomListParticipant
        other_band = Band.objects.create(name="Outra Banda", slug="outra-banda")
        integrante_other = Integrante.objects.create(band=other_band, name="Other", is_active=True)
        integrante_inactive = Integrante.objects.create(band=self.band, name="Inactive", is_active=False)

        self.client.force_login(self.user)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.post(url, {'integrantes': [integrante_other.id, integrante_inactive.id]})

        self.assertFalse(RoomListParticipant.objects.filter(room_list=self.room_list, original_integrante=integrante_other).exists())
        self.assertFalse(RoomListParticipant.objects.filter(room_list=self.room_list, original_integrante=integrante_inactive).exists())

    def test_sync_button_renders_correctly(self):
        # 5. verifica que o botão existe, usa o modal, e o botão antigo sumiu
        self.client.force_login(self.user)
        url = reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')

        # Tem o Sincronizar Integrantes e o data-bs-target
        self.assertIn('Sincronizar Integrantes', html)
        self.assertIn('data-bs-target="#modalSincronizar"', html)

        # O botão antigo (Sincronizar Escalados) não existe mais
        self.assertNotIn('Sincronizar Escalados', html)

        # Tem apenas 1 form apontando para room_list_sync, que é o do modal (dentro de id="syncForm")
        self.assertEqual(html.count('id="syncForm"'), 1)

    def test_sync_allocate_and_unassign(self):
        # 6. Sincronizar integrante e alocar num quarto, depois voltar pra não alocado
        from core.models import Integrante, RoomListParticipant, Room
        integrante = Integrante.objects.create(band=self.band, name="Alocavel", role="Role", is_active=True)
        room = Room.objects.create(room_list=self.room_list, type='INDIVIDUAL', capacity=1)

        self.client.force_login(self.user)

        # Sincroniza
        sync_url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        self.client.post(sync_url, {'integrantes': [integrante.id]})

        p = RoomListParticipant.objects.get(room_list=self.room_list, original_integrante=integrante)
        self.assertIsNone(p.room)

        # Alocar
        allocate_url = reverse('room_list_allocate', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk, 'participant_id': p.id})
        res1 = self.client.post(allocate_url, {'room_id': room.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        if res1.status_code != 200:
            print('ERROR JSON:', res1.json())
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()['status'], 'success')
        p.refresh_from_db()
        self.assertEqual(p.room, room)

        # Desalocar
        unassign_url = reverse('room_list_unassign', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk, 'participant_id': p.id})
        res2 = self.client.post(unassign_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()['status'], 'success')
        p.refresh_from_db()
        self.assertIsNone(p.room)

        # Garante ausência de duplicidade
        count = RoomListParticipant.objects.filter(room_list=self.room_list, original_integrante=integrante).count()
        self.assertEqual(count, 1)

    def test_sync_drag_drop_urls(self):
        # Garante que os cards geram data-allocate-url do reverse() oficial sem /banda/ hardcoded
        from core.models import Integrante, RoomListParticipant
        integrante = Integrante.objects.create(band=self.band, name="Draggavel", role="Role", is_active=True)
        p = RoomListParticipant.objects.create(room_list=self.room_list, original_integrante=integrante, order=0)

        self.client.force_login(self.user)
        url = reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')

        # O URL gerado não pode ter /banda/ hardcoded, mas sim usar o mount point do app (ex: /dannielvieira/...)
        expected_allocate = reverse('room_list_allocate', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk, 'participant_id': p.id})
        expected_unassign = reverse('room_list_unassign', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk, 'participant_id': p.id})

        self.assertIn(f'data-allocate-url="{expected_allocate}"', html)
        self.assertIn(f'data-unassign-url="{expected_unassign}"', html)

    def test_reactivate_arquivada(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        self.client.force_login(self.user)
        url = reverse('room_list_reactivate', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.room_list.refresh_from_db()
        self.assertEqual(self.room_list.status, RoomList.StatusChoices.RASCUNHO)

    def test_reactivate_permission_denied(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        other_user = User.objects.create_user(username="other", email="other@test.com", password="pwd", role="PRODUTOR")
        self.client.force_login(other_user)
        url = reverse('room_list_reactivate', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 403)
        self.room_list.refresh_from_db()
        self.assertEqual(self.room_list.status, RoomList.StatusChoices.ARQUIVADA)

    def test_delete_arquivada_post(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        self.client.force_login(self.user)
        url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(RoomList.objects.filter(pk=self.room_list.pk).exists())

    def test_delete_arquivada_get(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        self.client.force_login(self.user)
        url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 302) # Redireciona para o index
        self.assertTrue(RoomList.objects.filter(pk=self.room_list.pk).exists())

    def test_delete_permission_denied(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        other_user = User.objects.create_user(username="other_del", email="other_del@test.com", password="pwd", role="PRODUTOR")
        self.client.force_login(other_user)
        url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 403)
        self.assertTrue(RoomList.objects.filter(pk=self.room_list.pk).exists())

    def test_confirm_modal_and_form(self):
        self.room_list.status = RoomList.StatusChoices.ARQUIVADA
        self.room_list.save()
        self.client.force_login(self.user)
        url = reverse('room_list_index', kwargs={'band_slug': self.band.slug})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        delete_url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        self.assertIn('data-bs-target="#deleteModal', html)
        self.assertIn(f'action="{delete_url}"', html)

    def test_pdf_content_and_status(self):
        """Alocado aparece; não alocado não aparece; cabeçalho, hotel e totais presentes."""
        from core.models import Room, Integrante, RoomListParticipant
        self.room_list.hotel_name = "Hotel PDF Test"
        self.room_list.save()

        # Quarto CASAL com Ar-Cond ligado
        room = Room.objects.create(
            room_list=self.room_list, type='CASAL', capacity=2,
            beds_config='1 Cama de Casal', has_ac=True,
        )
        integ_alloc = Integrante.objects.create(band=self.band, name="PDF Member Alocado", role="Vocalista", is_active=True)
        RoomListParticipant.objects.create(
            room_list=self.room_list, room=room,
            original_integrante=integ_alloc, snapshot_name=integ_alloc.name,
            snapshot_role=integ_alloc.role, order=0,
        )

        # Integrante NÃO alocado
        integ_unalloc = Integrante.objects.create(band=self.band, name="Nao Alocado Pessoa", role="Roadie", is_active=True)
        RoomListParticipant.objects.create(
            room_list=self.room_list, room=None,
            original_integrante=integ_unalloc, snapshot_name=integ_unalloc.name,
            snapshot_role=integ_unalloc.role, order=1,
        )

        self.client.force_login(self.user)
        url = reverse('room_list_pdf', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.content), 0)
        html = res.content.decode('utf-8')

        # Cabeçalho e hotel presentes
        self.assertIn("Hotel PDF Test", html)
        self.assertIn("Quartos e Ocupantes", html)

        # Integrante alocado aparece
        self.assertIn("PDF Member Alocado", html)

        # Integrante NÃO alocado NÃO aparece no PDF
        self.assertNotIn("Nao Alocado Pessoa", html)

        # Seção "Integrantes na Lista de Hospedagem" removida
        self.assertNotIn("Integrantes na Lista de Hospedagem", html)

        # Quarto número + tipo aparecem
        self.assertIn("Quarto 1", html)
        self.assertIn("Casal", html)

        # Ar-Cond aparece quando has_ac=True
        self.assertIn("Ar-Cond.", html)

    def test_pdf_room_sem_ar_cond(self):
        """Quarto sem ar-condicionado exibe 'Sem Ar-Cond.'"""
        from core.models import Room, Integrante, RoomListParticipant
        room = Room.objects.create(
            room_list=self.room_list, type='INDIVIDUAL', capacity=1, has_ac=False,
        )
        integ = Integrante.objects.create(band=self.band, name="Sem AC Member", role="Tech", is_active=True)
        RoomListParticipant.objects.create(
            room_list=self.room_list, room=room,
            original_integrante=integ, snapshot_name=integ.name,
            snapshot_role=integ.role, order=0,
        )
        self.client.force_login(self.user)
        url = reverse('room_list_pdf', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertIn("Sem Ar-Cond.", html)
        self.assertNotIn("Integrantes na Lista de Hospedagem", html)

    def test_pdf_participants_count_only_allocated(self):
        """Total de integrantes hospedados conta somente os alocados."""
        from core.models import Room, Integrante, RoomListParticipant
        room = Room.objects.create(
            room_list=self.room_list, type='DUPLO', capacity=2, has_ac=True,
        )
        for i in range(2):
            integ = Integrante.objects.create(band=self.band, name=f"Alloc {i}", is_active=True)
            RoomListParticipant.objects.create(
                room_list=self.room_list, room=room,
                original_integrante=integ, snapshot_name=integ.name, order=i,
            )
        # Não alocado
        unalloc = Integrante.objects.create(band=self.band, name="Unalloc", is_active=True)
        RoomListParticipant.objects.create(
            room_list=self.room_list, room=None,
            original_integrante=unalloc, snapshot_name=unalloc.name, order=99,
        )
        self.client.force_login(self.user)
        url = reverse('room_list_pdf', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        # Deve mostrar 2 (não 3) hospedados
        self.assertIn("Total de Integrantes Hospedados: 2", html)
        self.assertNotIn("Total de Integrantes Hospedados: 3", html)

    def test_pdf_button_adicionar_lista(self):
        """Botão da listagem apresenta '+ Adicionar'."""
        self.client.force_login(self.user)
        url = reverse('room_list_index', kwargs={'band_slug': self.band.slug})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertIn("+ Adicionar", html)
        self.assertNotIn("Adicionar Lista", html)

    def test_single_pdf_view_definition(self):
        """Existe somente uma definição de room_list_pdf_view rastreada."""
        import subprocess
        try:
            output = subprocess.check_output(
                ['git', 'grep', '-c', 'def room_list_pdf_view', '--', 'core/views.py'],
                stderr=subprocess.STDOUT,
            )
            count_str = output.decode('utf-8').strip()
        except subprocess.CalledProcessError:
            count_str = "0"
        # git grep -c retorna o número de LINHAS que casam (1 linha = 1 definição)
        self.assertEqual(count_str, "core/views.py:1")

    def test_room_list_confirm_delete_removed(self):
        import subprocess
        try:
            output = subprocess.check_output(
                ['git', 'grep', 'room_list_confirm_delete.html', '--', ':/', ':!core/tests_room_list_ui_fixes.py'],
                stderr=subprocess.STDOUT,
            )
            output_str = output.decode('utf-8').strip()
        except subprocess.CalledProcessError:
            output_str = ""
        self.assertEqual(output_str, "")
