from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, Contact, User

class ContactTypesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name='Test Band', slug='test-band', is_active=True, plan_type='AVANCADO')
        self.user = User.objects.create_user(username='testuser', email='test@test.com', password='password', role='PRODUTOR', band=self.band)
        self.client.login(username='testuser', password='password')

    def test_1_registro_antigo_hospedagem_exibido_como_hotel(self):
        contact = Contact.objects.create(band=self.band, name='Hotel 1', contact_type='HOSPEDAGEM', is_shared_globally=True)
        self.assertEqual(contact.get_contact_type_display(), 'Hotel')
        
        url = reverse('banco_de_dados_global')
        response = self.client.get(url)
        self.assertContains(response, 'Hotel')
        self.assertContains(response, 'contact-type-pill')
        
    def test_2_registro_antigo_estabelecimento_exibido_como_empresa(self):
        contact = Contact.objects.create(band=self.band, name='Empresa 1', contact_type='ESTABELECIMENTO')
        self.assertEqual(contact.get_contact_type_display(), 'Empresa')
        
        url = reverse('contatos_list', args=[self.band.slug])
        response = self.client.get(url)
        self.assertContains(response, 'Empresa')
        self.assertContains(response, 'contact-type-pill')

    def test_3_valores_internos_preservados(self):
        contact = Contact.objects.create(band=self.band, name='Forn', contact_type='FORNECEDOR')
        contact.refresh_from_db()
        self.assertEqual(contact.contact_type, 'FORNECEDOR')
        self.assertEqual(contact.get_contact_type_display(), 'Fornecedor')

    def test_4_formularios_filtros_labels_novos(self):
        url = reverse('contatos_list', args=[self.band.slug])
        response = self.client.get(url)
        self.assertContains(response, '<option value="HOSPEDAGEM" >Hotel</option>')
        self.assertContains(response, '<option value="ESTABELECIMENTO" >Empresa</option>')

    def test_5_pagina_contatos_usa_classe_padronizada(self):
        Contact.objects.create(band=self.band, name='Forn', contact_type='CONTRATANTE')
        url = reverse('contatos_list', args=[self.band.slug])
        response = self.client.get(url)
        self.assertContains(response, 'contact-type-pill')
        self.assertContains(response, 'fa-handshake')

    def test_6_banco_de_dados_usa_classe_padronizada(self):
        Contact.objects.create(band=self.band, name='Forn', contact_type='PRODUTOR', is_shared_globally=True)
        url = reverse('banco_de_dados_global')
        response = self.client.get(url)
        self.assertContains(response, 'contact-type-pill')
        self.assertContains(response, 'fa-user-tie')

