from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band, Show, RoomList, Room

User = get_user_model()

class RoomEditModalBpPend80Tests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.user = User.objects.create_user(
            username='produtor_test',
            password='password123',
            band=self.band,
            role='PRODUTOR',
            is_active=True
        )
        self.show = Show.objects.create(
            band=self.band,
            title='Show Teste',
            date='2026-10-15',
            city='Salvador'
        )
        self.room_list = RoomList.objects.create(
            band=self.band,
            show=self.show,
            hotel_name='Hotel Teste',
            status='RASCUNHO'
        )
        self.room = Room.objects.create(
            room_list=self.room_list,
            number_or_name='101',
            type='CASAL',
            capacity=2,
            beds_config='1 Cama Casal',
            has_ac=True
        )
        self.client.login(username='produtor_test', password='password123')

    def test_manage_page_renders_edit_modal_and_button_with_blue_styling(self):
        url = reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Check modal is present
        self.assertContains(response, 'id="modalEditarQuarto"')
        self.assertContains(response, 'Editar Quarto')

        # Check edit button in dropdown triggers modal and is styled with blue/text-primary
        self.assertContains(response, 'data-bs-target="#modalEditarQuarto"')
        self.assertContains(response, 'btn-editar-quarto text-primary')
        self.assertContains(response, 'fa-pen-to-square text-primary me-2')

        # Check data attributes on the edit button
        self.assertContains(response, f'data-number="{self.room.number_or_name}"')
        self.assertContains(response, f'data-type="{self.room.type}"')
        self.assertContains(response, f'data-capacity="{self.room.capacity}"')

    def test_post_edit_room_success_redirects_to_manage(self):
        url = reverse('room_list_room_edit', kwargs={
            'band_slug': self.band.slug,
            'pk': self.room_list.id,
            'room_id': self.room.id
        })
        response = self.client.post(url, {
            'number_or_name': '101-B',
            'type': 'DUPLO',
            'capacity': 2,
            'beds_config': '2 Camas Solteiro',
            'has_ac': True
        })
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.id}))
        self.room.refresh_from_db()
        self.assertEqual(self.room.number_or_name, '101-B')
        self.assertEqual(self.room.type, 'DUPLO')
        self.assertEqual(self.room.beds_config, '2 Camas Solteiro')

    def test_post_edit_room_validation_error_redirects_to_manage_with_message(self):
        url = reverse('room_list_room_edit', kwargs={
            'band_slug': self.band.slug,
            'pk': self.room_list.id,
            'room_id': self.room.id
        })
        # Invalid capacity for INDIVIDUAL (must be 1)
        response = self.client.post(url, {
            'number_or_name': '101-C',
            'type': 'INDIVIDUAL',
            'capacity': 5,
            'has_ac': True
        })
        self.assertRedirects(response, reverse('room_list_manage', kwargs={'band_slug': self.band.slug, 'pk': self.room_list.id}))
        self.room.refresh_from_db()
        self.assertNotEqual(self.room.number_or_name, '101-C')
