import datetime
from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User, Show

class ShowPdfMapLinkTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste', is_active=True, subscription_plan='ADVANCED')
        self.user = User.objects.create_user(
            username='produtor_pdf',
            email='prod@teste.com',
            password='password123',
            role='PRODUTOR',
            band=self.band
        )
        self.client.login(username='produtor_pdf', password='password123')

    def test_show_with_venue_and_address(self):
        """Teste 1: Link no Local e não no Endereço"""
        show = Show.objects.create(
            band=self.band,
            title='Show Arena',
            date=datetime.date.today(),
            venue='Shopping da Bahia',
            address='Av. Tancredo Neves, 148 - Caminho das Árvores',
            address_link='https://maps.google.com/?q=ShoppingDaBahia'
        )
        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Verificar que o link está na linha de Cidade / Local
        self.assertIn('<strong>Cidade / Local:</strong> - · Shopping da Bahia · <a href="https://maps.google.com/?q=ShoppingDaBahia"', content)
        # Verificar que a linha de Endereço contém apenas o texto sem link
        self.assertIn('<strong>Endereço:</strong> Av. Tancredo Neves, 148 - Caminho das Árvores', content)
        # Garantir que o link não aparece dentro do bloco Endereço
        endereco_block = content.split('<strong>Endereço:</strong>')[1].split('</li>')[0]
        self.assertNotIn('Abrir no mapa', endereco_block)
        self.assertNotIn('Abrir no Mapa', endereco_block)
        self.assertNotIn('href=', endereco_block)

    def test_show_without_venue_but_with_address_and_link(self):
        """Teste 2: Show sem Local mas com Link de Mapa e Endereço"""
        show = Show.objects.create(
            band=self.band,
            title='Show Sem Local',
            date=datetime.date.today(),
            venue='',
            address='Rua das Flores, 100',
            address_link='https://maps.google.com/?q=RuaDasFlores'
        )
        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('<strong>Cidade / Local:</strong> - · <a href="https://maps.google.com/?q=RuaDasFlores"', content)
        self.assertIn('<strong>Endereço:</strong> Rua das Flores, 100', content)

    def test_show_without_venue_and_without_link(self):
        """Teste 3: Show sem Local e sem Link (somente Endereço)"""
        show = Show.objects.create(
            band=self.band,
            title='Show Apenas Endereço',
            date=datetime.date.today(),
            venue='',
            address='Praça Central, S/N',
            address_link=''
        )
        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertNotIn('<strong>Local:</strong>', content)
        self.assertIn('<strong>Endereço:</strong> Praça Central, S/N', content)
        self.assertNotIn('Abrir no Mapa', content)

    def test_show_detail_with_venue_and_address(self):
        """Teste 4: Ver Detalhes do Show - Link no Local e não no Endereço"""
        show = Show.objects.create(
            band=self.band,
            title='Show Detalhes Arena',
            date=datetime.date.today(),
            venue='Shopping da Bahia',
            address='Av. Tancredo Neves, 148 - Caminho das Árvores',
            address_link='https://maps.google.com/?q=ShoppingDaBahia'
        )
        url = reverse('show_detail', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Link no Local
        self.assertIn('<strong>Local:</strong> Shopping da Bahia - <a href="https://maps.google.com/?q=ShoppingDaBahia"', content)
        # Endereço como texto simples
        self.assertIn('<strong>Endereço:</strong> Av. Tancredo Neves, 148 - Caminho das Árvores', content)
        endereco_block = content.split('<strong>Endereço:</strong>')[1].split('</li>')[0]
        self.assertNotIn('Abrir no Mapa', endereco_block)
        self.assertNotIn('href=', endereco_block)

    def test_show_detail_without_venue_but_with_address_and_link(self):
        """Teste 5: Ver Detalhes do Show sem Local mas com Link de Mapa"""
        show = Show.objects.create(
            band=self.band,
            title='Show Detalhes Sem Local',
            date=datetime.date.today(),
            venue='',
            address='Rua das Flores, 100',
            address_link='https://maps.google.com/?q=RuaDasFlores'
        )
        url = reverse('show_detail', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('<strong>Local:</strong> <a href="https://maps.google.com/?q=RuaDasFlores"', content)
        self.assertIn('<strong>Endereço:</strong> Rua das Flores, 100', content)

