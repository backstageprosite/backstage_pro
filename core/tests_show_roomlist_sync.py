# -*- coding: utf-8 -*-
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Band, User, Show, RoomList
from core.services import room_list_services


class ShowRoomListSyncTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste', plan_type='AVANCADO')
        self.produtor = User.objects.create_user(
            username='produtor',
            email='produtor@teste.com',
            password='123',
            role='PRODUTOR',
            band=self.band
        )
        self.show = Show.objects.create(
            band=self.band,
            title='Show Sync Test',
            date=timezone.now().date(),
            accommodation='Hotel Fasano',
            accommodation_city='Salvador/BA',
            accommodation_address='Praça Castro Alves, 5',
            accommodation_link='https://maps.google.com/?q=fasano'
        )

    def test_create_room_list_prepopulates_from_show(self):
        rl = room_list_services.create_room_list(
            show_id=self.show.id,
            band_id=self.band.id,
            user=self.produtor
        )
        self.assertEqual(rl.hotel_name, 'Hotel Fasano')
        self.assertEqual(rl.city, 'Salvador/BA')
        self.assertEqual(rl.address, 'Praça Castro Alves, 5')

    def test_update_room_list_syncs_to_show(self):
        rl = room_list_services.create_room_list(
            show_id=self.show.id,
            band_id=self.band.id,
            user=self.produtor
        )
        room_list_services.update_room_list(
            room_list_id=rl.id,
            user=self.produtor,
            hotel_name='Hotel Wish da Bahia',
            city='Salvador - BA',
            address='Av. Sete de Setembro, 1537',
            accommodation_link='https://maps.google.com/?q=wish'
        )
        self.show.refresh_from_db()
        self.assertEqual(self.show.accommodation, 'Hotel Wish da Bahia')
        self.assertEqual(self.show.accommodation_city, 'Salvador - BA')
        self.assertEqual(self.show.accommodation_address, 'Av. Sete de Setembro, 1537')
        self.assertEqual(self.show.accommodation_link, 'https://maps.google.com/?q=wish')

    def test_show_edit_view_syncs_to_active_room_list(self):
        rl = room_list_services.create_room_list(
            show_id=self.show.id,
            band_id=self.band.id,
            user=self.produtor
        )
        self.client.force_login(self.produtor)
        url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': self.show.pk})
        post_data = {
            'title': 'Show Sync Test Edit',
            'status': 'CONFIRMADO',
            'date': self.show.date.strftime('%Y-%m-%d'),
            'city': 'Salvador',
            'payment_status': 'PENDENTE',
            'accommodation': 'Hotel Fiesta Bahia',
            'accommodation_city': 'Salvador (Itaigara)',
            'accommodation_address': 'Av. ACM, 711',
            'accommodation_link': 'https://maps.google.com/?q=fiesta',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        rl.refresh_from_db()
        self.assertEqual(rl.hotel_name, 'Hotel Fiesta Bahia')
        self.assertEqual(rl.city, 'Salvador (Itaigara)')
        self.assertEqual(rl.address, 'Av. ACM, 711')
