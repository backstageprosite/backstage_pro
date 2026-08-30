from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, Contact, User, ContactLike, BandSubscription, BillingRecord

class AdminBancoFaturasTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name='Test Band', slug='test-band', is_active=True, plan_type='AVANCADO')
        self.admin = User.objects.create_superuser(username='admin', email='admin@test.com', password='password')
        self.produtor = User.objects.create_user(username='produtor', email='produtor@test.com', password='password', role='PRODUTOR', band=self.band)
        self.contact = Contact.objects.create(band=self.band, name='Test Public Contact', phone='7199999999', is_shared_globally=True, is_hidden=False)
        self.like = ContactLike.objects.create(contact=self.contact, user=self.produtor, band=self.band)

    def test_1_admin_remove_contato_banco_geral(self):
        self.client.login(username='admin', password='password')
        url = reverse('admin_painel:database_delete', args=[self.contact.id])
        
        response_get = self.client.get(url)
        self.assertEqual(response_get.status_code, 403)
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_hidden)
        
        response_post = self.client.post(url)
        self.assertEqual(response_post.status_code, 302)
        
        self.contact.refresh_from_db()
        self.assertTrue(self.contact.is_hidden)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(self.contact.likes.count(), 1)
        self.assertEqual(self.contact.name, 'Test Public Contact')

    def test_2_contato_desaparece_banco_geral_mas_continua_na_banda(self):
        self.client.login(username='admin', password='password')
        url = reverse('admin_painel:database_delete', args=[self.contact.id])
        self.client.post(url)
        
        self.client.login(username='produtor', password='password')
        
        response_geral = self.client.get(reverse('banco_de_dados_global'))
        self.assertNotContains(response_geral, self.contact.name)
        
        response_banda = self.client.get(reverse('contatos_list', args=[self.band.slug]))
        self.assertContains(response_banda, self.contact.name)

    def test_3_usuario_sem_permissao(self):
        self.client.login(username='produtor', password='password')
        url = reverse('admin_painel:database_delete', args=[self.contact.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_hidden)

    def test_4_modal_usa_texto_correto(self):
        self.client.login(username='admin', password='password')
        url = reverse('admin_painel:database_list')
        response = self.client.get(url)
        self.assertContains(response, 'Remover do Banco Geral')

    def test_5_faturas_padronizado(self):
        self.client.login(username='admin', password='password')
        url = reverse('admin_painel:cobrancas')
        response = self.client.get(url)
        self.assertContains(response, 'fa-eraser')
        self.assertContains(response, 'fa-filter')
        self.assertContains(response, 'Limpar')
        self.assertContains(response, 'Filtrar')
        self.assertContains(response, 'Cobrança')

