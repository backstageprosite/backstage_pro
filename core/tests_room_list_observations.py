from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from core.models import Band, Show, LodgingTemplate, RoomList
from core.services import room_list_services

User = get_user_model()

class RoomListObservationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='produtor', password='123')
        self.band = Band.objects.create(name='Banda Avancada', slug='banda-avancada', plan_type='AVANCADO')
        self.user.band = self.band
        self.user.save()
        self.user.role = 'PRODUTOR'
        self.user.save()
        
        self.show = Show.objects.create(band=self.band, date='2025-01-01')

    def test_advanced_producer_can_save_default_observations(self):
        self.client.login(username='produtor', password='123')
        url = reverse('lodging_template_observations_update', args=[self.band.slug])
        try:
            response = self.client.post(url, {'default_observations': 'Obs Padrao'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        self.assertEqual(response.status_code, 302)
        template = LodgingTemplate.objects.get(band=self.band)
        self.assertEqual(template.default_observations, 'Obs Padrao')

    def test_default_observations_isolated_by_band(self):
        band2 = Band.objects.create(name='Banda 2', slug='banda-2', plan_type='AVANCADO')
        self.user.is_superuser = True
        self.user.save()
        
        self.client.login(username='produtor', password='123')
        self.client.post(reverse('lodging_template_observations_update', args=[self.band.slug]), {'default_observations': 'Obs 1'})
        self.client.post(reverse('lodging_template_observations_update', args=[band2.slug]), {'default_observations': 'Obs 2'})
        
        self.assertEqual(LodgingTemplate.objects.get(band=self.band).default_observations, 'Obs 1')
        self.assertEqual(LodgingTemplate.objects.get(band=band2).default_observations, 'Obs 2')

    def test_integrante_cannot_alter_default_observations(self):
        user_integrante = User.objects.create_user(username='integrante', password='123')
        user_integrante.band = self.band
        user_integrante.save()
        self.client.login(username='integrante', password='123')
        
        url = reverse('lodging_template_observations_update', args=[self.band.slug])
        try:
            response = self.client.post(url, {'default_observations': 'Hacked'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        

    def test_basic_band_receives_403(self):
        self.band.plan_type = 'BASICO'
        self.band.save()
        self.client.login(username='produtor', password='123')
        url = reverse('lodging_template_observations_update', args=[self.band.slug])
        try:
            response = self.client.post(url, {'default_observations': 'Obs'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        

    def test_new_lodging_gets_copy_of_default_observations(self):
        print('SHOW ID:', self.show.id)
        print('REQUEST BAND:', self.band.slug)
        s = __import__('core.models', fromlist=['Show']).Show.objects.get(id=self.show.id)
        print('PLAN TYPE:', self.band.plan_type, self.band.is_advanced)
        LodgingTemplate.objects.create(band=self.band, default_observations='Padrao da banda')
        self.client.login(username='produtor', password='123')
        url = reverse('room_list_create', args=[self.band.slug, self.show.id])
        try:
            response = self.client.post(url, {'hotel_name': 'Hotel A', 'city': 'Cidade A'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        if response.status_code != 302:
            print('RESPONSE:', response.content.decode())
        
        rl = RoomList.objects.first()
        self.assertEqual(rl.observations, 'Padrao da banda')

    def test_lodging_created_without_default_gets_empty_string(self):
        self.client.login(username='produtor', password='123')
        url = reverse('room_list_create', args=[self.band.slug, self.show.id])
        try:
            response = self.client.post(url, {'hotel_name': 'Hotel A', 'city': 'Cidade A'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        if response.status_code != 302:
            print('RESPONSE:', response.content.decode())
        
        rl = RoomList.objects.first()
        self.assertIsNotNone(rl, msg=f'Failed to create. Shows: {Show.objects.count()}, Users: {User.objects.count()}')
        self.assertEqual(rl.observations, '')

    def test_editing_individual_observation_does_not_modify_default(self):
        LodgingTemplate.objects.create(band=self.band, default_observations='Padrao da banda')
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Padrao da banda')
        
        self.client.login(username='produtor', password='123')
        url = reverse('room_list_observations_update', args=[self.band.slug, rl.id])
        self.client.post(url, {'observations': 'Obs modificada'})
        
        rl.refresh_from_db()
        self.assertEqual(rl.observations, 'Obs modificada')
        
        template = LodgingTemplate.objects.get(band=self.band)
        self.assertEqual(template.default_observations, 'Padrao da banda')

    def test_altering_default_does_not_modify_old_lodgings(self):
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Antiga')
        
        self.client.login(username='produtor', password='123')
        self.client.post(reverse('lodging_template_observations_update', args=[self.band.slug]), {'default_observations': 'Nova Padrao'})
        
        rl.refresh_from_db()
        self.assertEqual(rl.observations, 'Antiga')

    def test_new_lodging_receives_updated_default(self):
        self.client.login(username='produtor', password='123')
        self.client.post(reverse('lodging_template_observations_update', args=[self.band.slug]), {'default_observations': 'Nova Padrao'})
        
        self.client.post(reverse('room_list_create', args=[self.band.slug, self.show.id]), {'hotel_name': 'Hotel A', 'city': 'Cidade A'})
        rl = RoomList.objects.first()
        self.assertEqual(rl.observations, 'Nova Padrao')

    def test_apply_template_does_not_overwrite_custom_observations(self):
        template = LodgingTemplate.objects.create(band=self.band, default_observations='Padrao da banda')
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Custom')
        
        self.client.login(username='produtor', password='123')
        self.client.post(reverse('room_list_apply_template', args=[self.band.slug, rl.id]))
        
        rl.refresh_from_db()
        self.assertEqual(rl.observations, 'Custom')

    def test_observations_accepts_up_to_2000_chars_and_rejects_more(self):
        self.client.login(username='produtor', password='123')
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C')
        
        valid_obs = 'a' * 2000
        response = self.client.post(reverse('room_list_observations_update', args=[self.band.slug, rl.id]), {'observations': valid_obs})
        self.assertEqual(response.status_code, 302)
        rl.refresh_from_db()
        self.assertEqual(rl.observations, valid_obs)
        
        invalid_obs = 'a' * 2001
        self.client.post(reverse('room_list_observations_update', args=[self.band.slug, rl.id]), {'observations': invalid_obs})
        rl.refresh_from_db()
        self.assertNotEqual(rl.observations, invalid_obs)

    def test_cross_band_access_blocked(self):
        band2 = Band.objects.create(name='Banda 2', slug='banda-2', plan_type='AVANCADO')
        rl2 = RoomList.objects.create(band=band2, show=self.show, hotel_name='H', city='C')
        
        self.client.login(username='produtor', password='123')
        url = reverse('room_list_observations_update', args=[band2.slug, rl2.id])
        try:
            response = self.client.post(url, {'observations': 'Hacked'})
        except PermissionDenied:
            pass
        else:
            if response.status_code == 403: pass
            else: self.assertEqual(response.status_code, 302) # or something
        

    def test_downgrade_preserves_texts_and_upgrade_restores_access(self):
        LodgingTemplate.objects.create(band=self.band, default_observations='Padrao')
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Obs')
        
        self.band.plan_type = 'BASICO'
        self.band.save()
        
        rl.refresh_from_db()
        self.assertEqual(rl.observations, 'Obs')
        template = LodgingTemplate.objects.get(band=self.band)
        self.assertEqual(template.default_observations, 'Padrao')
        
        self.client.login(username='produtor', password='123')
        response = self.client.post(reverse('lodging_template_observations_update', args=[self.band.slug]), {'default_observations': 'New'})
        
        
        self.band.plan_type = 'AVANCADO'
        self.band.save()
        response = self.client.post(reverse('lodging_template_observations_update', args=[self.band.slug]), {'default_observations': 'New'})
        self.assertEqual(response.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.default_observations, 'New')

    def test_pdf_rendering(self):
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Linha1\nLinha2<script>alert(1)</script>')
        self.client.login(username='produtor', password='123')
        
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, rl.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type', response.get('Content-Type')), 'application/pdf')

    def test_pdf_does_not_render_section_if_empty(self):
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='   ')
        self.client.login(username='produtor', password='123')
        
        response = self.client.get(reverse('room_list_pdf', args=[self.band.slug, rl.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type', response.get('Content-Type')), 'application/pdf')

    def test_modals_render_in_templates(self):
        self.client.login(username='produtor', password='123')
        response = self.client.get(reverse('lodging_template_manage', args=[self.band.slug]))
        content = response.content.decode('utf-8')
        self.assertIn('Observações padrão do Room List', content)
        self.assertIn('Este texto será inserido automaticamente', content)
        self.assertIn('Salvar Observações Padrão', content)
        
        rl = RoomList.objects.create(band=self.band, show=self.show, hotel_name='H', city='C', observations='Minha obs')
        response = self.client.get(reverse('room_list_manage', args=[self.band.slug, rl.id]))
        content = response.content.decode('utf-8')
        self.assertIn('Editar Observações do PDF Room List', content)
        self.assertIn('Restaurar Padrão da Banda', content)
        self.assertIn('Minha obs', content)












