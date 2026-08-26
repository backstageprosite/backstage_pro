import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Band, Show, RoomList, Room, Integrante
from core.forms import RoomListSelectShowForm

User = get_user_model()

class RoomListWebTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda 1', slug='banda-1')
        self.band2 = Band.objects.create(name='Banda 2', slug='banda-2')

        self.produtor = User.objects.create_user(
            username='produtor1', password='password123',
            band=self.band, role='PRODUTOR', is_active=True
        )
        self.integrante = User.objects.create_user(
            username='integrante1', password='password123',
            band=self.band, role='INTEGRANTE', is_active=True
        )
        self.produtor_outra_banda = User.objects.create_user(
            username='produtor2', password='password123',
            band=self.band2, role='PRODUTOR', is_active=True
        )
        self.usuario_sem_vinculo = User.objects.create_user(
            username='semvinculo', password='password123',
            band=None, role='PRODUTOR', is_active=True
        )
        self.usuario_inativo = User.objects.create_user(
            username='inativo', password='password123',
            band=self.band, role='PRODUTOR', is_active=False
        )
        self.superusuario = User.objects.create_superuser(
            username='admin', password='password123',
            band=None, is_active=True
        )

        self.show1 = Show.objects.create(
            band=self.band,
            date=datetime.date.today() + datetime.timedelta(days=1),
            city='São Paulo'
        )
        self.show2 = Show.objects.create(
            band=self.band2,
            date=datetime.date.today() + datetime.timedelta(days=1),
            city='Rio de Janeiro'
        )

        self.room_list1 = RoomList.objects.create(
            band=self.band, show=self.show1, hotel_name='Hotel SP', city='São Paulo'
        )
        self.room_list2 = RoomList.objects.create(
            band=self.band2, show=self.show2, hotel_name='Hotel RJ', city='Rio de Janeiro'
        )

        self.room1 = Room.objects.create(
            room_list=self.room_list1, number_or_name='101', type='INDIVIDUAL', capacity=1
        )

        self.client = Client()
        self.csrf_client = Client(enforce_csrf_checks=True)

    def login(self, user):
        self.client.force_login(user)
        self.csrf_client.force_login(user)

    def test_auth_and_permissions(self):
        url = reverse('room_list_index', kwargs={'band_slug': self.band.slug})

        # Não autenticado
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Produtor da própria banda
        self.login(self.produtor)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Integrante
        self.login(self.integrante)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Produtor de outra banda na URL da primeira banda
        self.login(self.produtor_outra_banda)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Usuário sem vínculo
        self.login(self.usuario_sem_vinculo)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Usuário inativo
        self.login(self.usuario_inativo)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Superusuário sem vínculo
        self.login(self.superusuario)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_room_list_index_isolation(self):
        self.login(self.produtor)
        url = reverse('room_list_index', kwargs={'band_slug': self.band.slug})
        response = self.client.get(url)
        self.assertContains(response, 'Hotel SP')
        self.assertNotContains(response, 'Hotel RJ')

    def test_room_list_select_show_filter(self):
        # show1 tem room_list
        show_futuro = Show.objects.create(
            band=self.band,
            date=datetime.date.today() + datetime.timedelta(days=2),
            city='Campinas'
        )
        show_passado = Show.objects.create(
            band=self.band,
            date=datetime.date.today() - datetime.timedelta(days=1),
            city='Santos'
        )

        form = RoomListSelectShowForm(band=self.band)
        qs = form.fields['show_id'].queryset
        self.assertIn(show_futuro, qs)
        self.assertNotIn(self.show1, qs) # Já tem room list
        self.assertNotIn(show_passado, qs)
        self.assertNotIn(self.show2, qs) # Outra banda

    def test_room_list_create_post(self):
        show_novo = Show.objects.create(
            band=self.band,
            date=datetime.date.today() + datetime.timedelta(days=3),
            city='Curitiba'
        )

        self.login(self.produtor)
        url = reverse('room_list_create', kwargs={'band_slug': self.band.slug, 'show_id': show_novo.id})

        # GET
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # POST inválido (sem nome do hotel)
        response = self.client.post(url, {'city': 'Curitiba'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('hotel_name', response.context['form'].errors)

        # POST válido
        data = {
            'hotel_name': 'Hotel Top',
            'city': 'Curitiba',
            'check_in': '2026-08-20T14:00',
            'check_out': '2026-08-22T12:00',
        }
        response = self.client.post(url, data)
        room_list_criada = RoomList.objects.filter(hotel_name='Hotel Top').first()
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': room_list_criada.id}))

    def test_room_list_edit_not_found(self):
        self.login(self.produtor)
        # Editando room_list da banda 2
        url = reverse('room_list_edit', kwargs={'band_slug': self.band.slug, 'pk': self.room_list2.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_room_list_manage_no_cpf(self):
        integrante_pessoa = Integrante.objects.create(band=self.band, name='João', cpf='11122233344')
        self.login(self.produtor)
        url = reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '11122233344')

    def test_room_list_delete_get_post(self):
        self.login(self.produtor)
        url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})

        # GET não exclui (view redireciona sem deletar)
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 302])
        self.assertTrue(RoomList.objects.filter(id=self.room_list1.id).exists())

        # POST exclui (com client não-CSRF para simplificar o assert)
        response = self.client.post(url)
        self.assertRedirects(response, reverse('room_list_index', kwargs={'band_slug': self.band.slug}))
        self.assertFalse(RoomList.objects.filter(id=self.room_list1.id).exists())


    def test_csrf_required_for_mutations(self):
        self.login(self.produtor)
        url = reverse('room_list_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        # client csrf sem token retorna 403
        response = self.csrf_client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_room_crud(self):
        self.login(self.produtor)

        # Criar
        url_create = reverse('room_list_room_create', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url_create, {
            'number_or_name': '201', 'type': 'DUPLO', 'capacity': 2, 'has_ac': True
        })
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        room = Room.objects.get(number_or_name='201')

        # Editar
        url_edit = reverse('room_list_room_edit', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id, 'room_id': room.id})
        response = self.client.post(url_edit, {
            'number_or_name': '201A', 'type': 'DUPLO', 'capacity': 2, 'has_ac': True
        })
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        room.refresh_from_db()
        self.assertEqual(room.number_or_name, '201A')

        # Excluir
        url_delete = reverse('room_list_room_delete', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id, 'room_id': room.id})
        response = self.client.post(url_delete)
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        self.assertFalse(Room.objects.filter(id=room.id).exists())

    def test_room_other_list_404(self):
        self.login(self.produtor)
        room_da_banda2 = Room.objects.create(
            room_list=self.room_list2, number_or_name='202', type='INDIVIDUAL', capacity=1
        )
        url = reverse('room_list_room_edit', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id, 'room_id': room_da_banda2.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_room_create_invalid_capacity(self):
        self.login(self.produtor)
        url_create = reverse('room_list_room_create', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url_create, {
            'number_or_name': '203', 'type': 'INDIVIDUAL', 'capacity': 2, 'has_ac': True
        }, follow=True)
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        messages_list = [str(m) for m in response.context['messages']]
        self.assertTrue(len(messages_list) > 0)
        self.assertEqual(Room.objects.filter(number_or_name='203').count(), 0)

    def test_show_de_outra_banda(self):
        self.login(self.produtor)
        url = reverse('room_list_create', kwargs={'band_slug': self.band.slug, 'show_id': self.show2.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_status_impedido_domain(self):
        self.login(self.produtor)
        self.room_list1.status = 'ARQUIVADA'
        self.room_list1.save()

        url = reverse('room_list_room_create', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url, {
            'number_or_name': '205', 'type': 'INDIVIDUAL', 'capacity': 1, 'has_ac': True
        }, follow=True)
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        messages = list(response.context['messages'])
        self.assertTrue(any('arquivada' in str(m).lower() for m in messages))
        self.assertEqual(Room.objects.filter(number_or_name='205').count(), 0)

    def test_room_list_sync(self):
        self.login(self.produtor)
        url = reverse('room_list_sync', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url)
        # Sem integrantes selecionados a view redireciona (302) ou retorna mensagem de info
        self.assertIn(response.status_code, [200, 302])


    def test_room_list_publish(self):
        self.login(self.produtor)
        url = reverse('room_list_publish', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.room_list1.refresh_from_db()
        self.assertEqual(self.room_list1.status, 'PUBLICADA')

    def test_room_list_archive(self):
        self.login(self.produtor)
        url = reverse('room_list_archive', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.room_list1.refresh_from_db()
        self.assertEqual(self.room_list1.status, 'ARQUIVADA')

    def test_lodging_template_manage(self):
        from core.models import LodgingTemplate
        # Garante explícitamente o plano avançado
        self.band.plan_type = 'AVANCADO'
        self.band.save()

        self.login(self.produtor)
        url = reverse('lodging_template_manage', kwargs={'band_slug': self.band.slug})

        # 1. GET do produtor Avançado retorna 200
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        template = LodgingTemplate.objects.get(band=self.band)
        create_url = reverse('lodging_template_room_create', kwargs={'band_slug': self.band.slug, 'pk': template.id})

        # 2. POST válido do produtor Avançado retorna 302
        data = {
            'quantity': '1',
            'number_or_name': 'Quarto Template',
            'type': 'INDIVIDUAL',
            'capacity': '1',
            'beds_config': '',
            'has_ac': 'on'
        }
        response = self.client.post(create_url, data)
        # 3. redirecionamento aponta para a URL correta
        self.assertRedirects(response, url)

        # 4. modelo é realmente persistido
        self.assertEqual(template.rooms.count(), 1)
        room = template.rooms.first()
        self.assertEqual(room.number_or_name, 'Quarto Template')

        # 5. edição atualiza o registro correto (número novo)
        edit_url = reverse('lodging_template_room_update', kwargs={'band_slug': self.band.slug, 'pk': template.id, 'room_id': room.id})
        response = self.client.post(edit_url, {'number_or_name': 'Quarto Editado', 'type': 'INDIVIDUAL', 'capacity': '1'})
        self.assertRedirects(response, url)
        room.refresh_from_db()
        self.assertEqual(room.number_or_name, 'Quarto Editado')

        # 5a. editar outros campos mantendo o próprio número
        response = self.client.post(edit_url, {'number_or_name': 'Quarto Editado', 'type': 'DUPLO', 'capacity': '2'})
        self.assertRedirects(response, url)
        room.refresh_from_db()
        self.assertEqual(room.type, 'DUPLO')
        self.assertEqual(room.capacity, 2)

        # 5b. tentar alterar para o número de outro quarto (duplicidade)
        room2 = template.rooms.create(number_or_name='Quarto 2', type='INDIVIDUAL', capacity=1)
        response = self.client.post(edit_url, {'number_or_name': 'Quarto 2', 'type': 'DUPLO', 'capacity': '2'}, follow=True)
        # 5c. confirmar que a duplicidade é rejeitada e mostra erro
        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any("existe" in m for m in messages))
        # 5d. confirmar que o registro original permanece intacto
        room.refresh_from_db()
        self.assertEqual(room.number_or_name, 'Quarto Editado')

        # 6. POST inválido não altera dados e apresenta erros (formato da view levanta erro via messages ou redireciona)
        invalid_data = {'quantity': 'abc', 'number_or_name': 'Erro'}
        response = self.client.post(create_url, invalid_data)
        self.assertRedirects(response, url) # view de create redireciona em caso de erro também, mas com flash message
        self.assertEqual(template.rooms.count(), 2) # sem alterações, continua com os 2 quartos criados nos passos anteriores

        # Test applying template
        response = self.client.post(reverse('room_list_apply_template', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        self.assertEqual(self.room_list1.rooms.count(), 1)

        # 7-9, 12-13. Testa rebaixamento (downgrade) para BÁSICO
        self.band.plan_type = 'BASICO'
        self.band.save()

        # 7. produtor Básico recebe 403 no GET
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # 8. produtor Básico recebe 403 no POST e 9. não cria nem altera modelo
        response = self.client.post(create_url, data)
        self.assertEqual(response.status_code, 403)

        # 12. downgrade preserva dados
        self.assertEqual(template.rooms.count(), 2)

        # 13. upgrade restaura o acesso
        self.band.plan_type = 'AVANCADO'
        self.band.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # 10. acesso cruzado entre bandas é negado
        self.login(self.produtor_outra_banda)
        response = self.client.post(create_url, data)
        self.assertEqual(response.status_code, 403) # produtor2 não tem acesso à band1

        # 11. integrante sem permissão não gerencia o modelo
        self.login(self.integrante)
        response = self.client.post(create_url, data)
        self.assertEqual(response.status_code, 403)

        self.login(self.produtor)
        # Test deleting template room
        delete_url = reverse('lodging_template_room_delete', kwargs={'band_slug': self.band.slug, 'pk': template.id, 'room_id': room.id})
        response = self.client.post(delete_url)
        self.assertRedirects(response, url)
        self.assertEqual(template.rooms.count(), 1)

    def test_room_list_allocate_and_unassign_fallback(self):
        # Setup participant
        integrante_pessoa = Integrante.objects.create(band=self.band, name='Joao', cpf='11122233344')
        from core.models import ShowParticipant, RoomListParticipant
        ShowParticipant.objects.create(show=self.show1, integrante=integrante_pessoa)
        self.login(self.produtor)

        p = RoomListParticipant.objects.create(room_list=self.room_list1, original_integrante=integrante_pessoa, snapshot_name="Joao")

        # Allocate (HTML POST Fallback)
        url_allocate = reverse('room_list_allocate', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id, 'participant_id': p.id})
        response = self.client.post(url_allocate, {'room_id': self.room1.id}, follow=True)
        for message in response.context['messages']:
            print("MESSAGE:", message)

        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        p.refresh_from_db()
        self.assertEqual(p.room, self.room1)

        # Unassign (HTML POST Fallback)
        url_unassign = reverse('room_list_unassign', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id, 'participant_id': p.id})
        response = self.client.post(url_unassign)
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list1.id}))
        p.refresh_from_db()
        self.assertIsNone(p.room)

    def test_room_list_mark_sent_success(self):
        self.room_list1.status = 'PUBLICADA'
        self.room_list1.save()
        self.client.force_login(self.produtor)
        response = self.client.post(reverse('room_list_mark_sent', args=[self.band.slug, self.room_list1.id]))
        self.assertRedirects(response, reverse('room_list_manage', args=[self.band.slug, self.room_list1.id]))
        self.room_list1.refresh_from_db()
        self.assertTrue(self.room_list1.was_sent)
        self.assertIsNotNone(self.room_list1.last_sent_to_hotel_at)
        self.assertEqual(self.room_list1.last_sent_revision, self.room_list1.content_revision)
        self.assertFalse(self.room_list1.needs_resend)

        self.room_list1.content_revision += 1
        self.room_list1.save()
        self.assertTrue(self.room_list1.needs_resend)

        response2 = self.client.get(reverse('room_list_manage', args=[self.band.slug, self.room_list1.id]))
        self.assertContains(response2, 'Reenvio recomendado')

    def test_room_list_mark_sent_get_405(self):
        self.room_list1.status = 'PUBLICADA'
        self.room_list1.save()
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('room_list_mark_sent', args=[self.band.slug, self.room_list1.id]))
        self.assertEqual(response.status_code, 405)

    def test_room_list_mark_sent_cross_list(self):
        self.room_list1.status = 'PUBLICADA'
        self.room_list1.save()
        self.client.force_login(self.produtor_outra_banda)
        response = self.client.post(reverse('room_list_mark_sent', args=[self.band2.slug, self.room_list1.id]))
        self.assertEqual(response.status_code, 404)

    def test_room_list_apply_template_success(self):
        from core.models import LodgingTemplate, TemplateRoom, TemplateParticipant, Integrante
        t = LodgingTemplate.objects.create(band=self.band)
        tr = TemplateRoom.objects.create(template=t, type='INDIVIDUAL', capacity=1)
        integ = Integrante.objects.create(band=self.band, name='Integ 1', role='MUSICO')
        TemplateParticipant.objects.create(template=t, room=tr, original_integrante=integ)

        from core.services.room_list_services import sync_room_list_participants_from_show
        sync_room_list_participants_from_show(self.room_list1.id, self.produtor)

        self.client.force_login(self.produtor)
        response = self.client.post(reverse('room_list_apply_template', args=[self.band.slug, self.room_list1.id]))
        self.assertRedirects(response, reverse('room_list_manage', args=[self.band.slug, self.room_list1.id]))

        self.room_list1.refresh_from_db()
        self.assertTrue(self.room_list1.content_revision > 0)

    def test_room_list_apply_template_no_template(self):
        self.client.force_login(self.produtor)
        response = self.client.post(reverse('room_list_apply_template', args=[self.band.slug, self.room_list1.id]), follow=True)
        # Using assertContains for 'Nenhum modelo' to bypass exact encoding issues
        self.assertContains(response, 'modelo de hospedagem')

    def test_room_list_apply_template_get_405(self):
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('room_list_apply_template', args=[self.band.slug, self.room_list1.id]))
        self.assertEqual(response.status_code, 405)

    def test_lodging_template_manage_visual_and_csrf(self):
        import re
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('lodging_template_manage', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<textarea')
        self.assertNotIn('json', response.content.decode('utf-8').lower())
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_room_list_manage_no_cpf(self):
        import re
        self.client.force_login(self.produtor)
        response = self.client.get(reverse('room_list_manage', args=[self.band.slug, self.room_list1.id]))
        self.assertNotIn('cpf', response.content.decode('utf-8').lower())

    def test_room_list_mutations_405_get(self):
        self.client.force_login(self.produtor)
        from core.services.room_list_services import sync_room_list_participants_from_show
        sync_room_list_participants_from_show(self.room_list1.id, self.produtor)
        p = self.room_list1.participants.first()
        if p:
            self.assertEqual(self.client.get(reverse('room_list_allocate', args=[self.band.slug, self.room_list1.id, p.id])).status_code, 405)
            self.assertEqual(self.client.get(reverse('room_list_unassign', args=[self.band.slug, self.room_list1.id, p.id])).status_code, 405)
        self.assertEqual(self.client.get(reverse('room_list_publish', args=[self.band.slug, self.room_list1.id])).status_code, 405)
        self.assertEqual(self.client.get(reverse('room_list_archive', args=[self.band.slug, self.room_list1.id])).status_code, 405)
        self.assertEqual(self.client.get(reverse('room_list_reopen', args=[self.band.slug, self.room_list1.id])).status_code, 405)
