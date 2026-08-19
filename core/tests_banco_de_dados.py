from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User, Contact

class BancoDeDadosTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste", is_active=True)
        self.produtor = User.objects.create_user(
            username="produtor",
            email="produtor@teste.com",
            password="senha",
            role="PRODUTOR",
            band=self.band
        )
        self.integrante = User.objects.create_user(
            username="integrante",
            email="integrante@teste.com",
            password="senha",
            role="INTEGRANTE",
            band=self.band
        )
        self.contact = Contact.objects.create(
            band=self.band,
            name="Contato Teste",
            phone="11999999999",
            email="teste@teste.com",
            contact_type="FORNECEDOR",
            notes="Nota interna",
            public_information="Infos globais",
            is_shared_globally=True,
            shared_by=self.produtor
        )

    def test_modals_contain_fields_and_order(self):
        self.client.login(username="produtor", password="senha")
        response = self.client.get(reverse('contatos_list', args=[self.band.slug]))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')

        # Check Novo Contato modal fields
        self.assertIn('id="modalNovoContato"', html)
        
        # Verify Help text
        self.assertIn('Os dados públicos deste contato ficarão visíveis', html)

        # Order verification: Observações -> Informações públicas -> Compartilhar
        # We can just check their relative positions
        idx_novo_modal = html.find('id="modalNovoContato"')
        idx_novo_notes = html.find('name="notes"', idx_novo_modal)
        idx_novo_pub_info = html.find('name="public_information"', idx_novo_notes)
        idx_novo_shared = html.find('name="is_shared_globally"', idx_novo_pub_info)
        
        self.assertTrue(idx_novo_modal < idx_novo_notes < idx_novo_pub_info < idx_novo_shared)

        # Check Editar Contato modal fields
        idx_edit_modal = html.find(f'id="modalEditarContato{self.contact.id}"')
        self.assertTrue(idx_edit_modal != -1)
        
        idx_edit_notes = html.find('name="notes"', idx_edit_modal)
        idx_edit_pub_info = html.find('name="public_information"', idx_edit_notes)
        idx_edit_shared = html.find('name="is_shared_globally"', idx_edit_pub_info)
        
        self.assertTrue(idx_edit_modal < idx_edit_notes < idx_edit_pub_info < idx_edit_shared)
        
        # Verify it is checked (since self.contact has is_shared_globally=True)
        # Find the input checkbox inside edit modal
        checkbox_str = html[idx_edit_shared:idx_edit_shared+150]
        self.assertIn('checked', checkbox_str)

    def test_post_cricao_persiste_campos(self):
        self.client.login(username="produtor", password="senha")
        data = {
            'name': 'Novo Contato Global',
            'contact_type': 'CONTRATANTE',
            'phone': '11988888888',
            'notes': 'Privado',
            'public_information': 'Global',
            'is_shared_globally': 'True'
        }
        response = self.client.post(reverse('contatos_add', args=[self.band.slug]), data)
        self.assertEqual(response.status_code, 302)
        
        c = Contact.objects.get(name='Novo Contato Global')
        self.assertEqual(c.public_information, 'Global')
        self.assertTrue(c.is_shared_globally)
        self.assertEqual(c.shared_by, self.produtor)
        self.assertIsNotNone(c.shared_at)

    def test_post_edicao_carrega_e_atualiza(self):
        self.client.login(username="produtor", password="senha")
        data = {
            'name': 'Editado',
            'contact_type': 'CONTRATANTE',
            'phone': '11999999999',
            'notes': 'Nova nota',
            'public_information': 'Nova info global',
            'is_shared_globally': 'True'
        }
        response = self.client.post(reverse('contatos_edit', args=[self.band.slug, self.contact.id]), data)
        self.assertEqual(response.status_code, 302)
        
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.public_information, 'Nova info global')
        self.assertTrue(self.contact.is_shared_globally)

    def test_desmarcar_checkbox_remove_da_lista_global(self):
        self.client.login(username="produtor", password="senha")
        data = {
            'name': 'Editado Sem Global',
            'contact_type': 'CONTRATANTE',
            'phone': '11999999999',
            'notes': 'Nova nota',
            'public_information': 'Nova info global'
            # 'is_shared_globally': not sent means false
        }
        response = self.client.post(reverse('contatos_edit', args=[self.band.slug, self.contact.id]), data)
        self.assertEqual(response.status_code, 302)
        
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_shared_globally)
        self.assertIsNone(self.contact.shared_by)
        self.assertIsNone(self.contact.shared_at)

    def test_erro_de_formulario_preserva_valores(self):
        self.client.login(username="produtor", password="senha")
        
        # Test duplicate contact (phone) to trigger error
        c2 = Contact.objects.create(
            band=self.band,
            name="Contato 2",
            phone="11977777777",
            is_shared_globally=True,
            shared_by=self.produtor
        )
        c2.save() # generate normalized phone

        data = {
            'name': 'Novo Duplicado',
            'contact_type': 'CONTRATANTE',
            'phone': '11977777777', # Same phone
            'notes': 'Privado duplicado',
            'public_information': 'Preservado?',
            'is_shared_globally': 'True'
        }
        response = self.client.post(reverse('contatos_add', args=[self.band.slug]), data)
        
        # Validation error -> 200 OK, form rendered again
        self.assertEqual(response.status_code, 200)
        
        # Values preserved
        html = response.content.decode('utf-8')
        self.assertIn('Preservado?', html)
        self.assertIn('Este contato já está cadastrado no Banco de Dados.', html)

    def test_integrante_nao_forja_compartilhamento(self):
        self.client.login(username="integrante", password="senha")
        data = {
            'name': 'Hacker Contact',
            'contact_type': 'CONTRATANTE',
            'phone': '11555555555',
            'is_shared_globally': 'True'
        }
        response = self.client.post(reverse('contatos_add', args=[self.band.slug]), data)
        
        # Forbidden sinceIntegrante cant add contacts at all
        self.assertEqual(response.status_code, 403)
        
        # Even if they could add, the view only gives them 403 anyway for anything inside contato_create_view

    def test_banco_de_dados_mostra_infos_publicas_oculta_internas(self):
        self.client.login(username="integrante", password="senha")
        response = self.client.get(reverse('banco_de_dados_global'))
        self.assertEqual(response.status_code, 200)
        
        html = response.content.decode('utf-8')
        # Ensure 'Infos globais' (public_information) is rendered
        self.assertIn('Infos globais', html)
        # Ensure 'Nota interna' (notes) is NOT rendered
        self.assertNotIn('Nota interna', html)
        
        # Verify Band name is present but slug is NOT present in the modal
        self.assertIn('Banda Teste', html)
        self.assertNotIn('(Slug: banda-teste)', html)
        self.assertNotIn('Slug: banda-teste', html)
