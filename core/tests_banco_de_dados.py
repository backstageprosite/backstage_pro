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


class ContactCopyFromGlobalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.csrf_client = Client(enforce_csrf_checks=True)

        # Banda 1 (Origem)
        self.banda1 = Band.objects.create(name="Banda Origem", slug="banda-origem", is_active=True)
        self.produtor1 = User.objects.create_user(
            username="produtor1", email="p1@teste.com", password="senha", role="PRODUTOR", band=self.banda1
        )

        # Banda 2 (Destino)
        self.banda2 = Band.objects.create(name="Banda Destino", slug="banda-destino", is_active=True)
        self.produtor2 = User.objects.create_user(
            username="produtor2", email="p2@teste.com", password="senha", role="PRODUTOR", band=self.banda2
        )
        self.integrante2 = User.objects.create_user(
            username="integrante2", email="int2@teste.com", password="senha", role="INTEGRANTE", band=self.banda2
        )

        # Banda 3 (Destino alternativo)
        self.banda3 = Band.objects.create(name="Banda 3", slug="banda-3", is_active=True)
        self.produtor3 = User.objects.create_user(
            username="produtor3", email="p3@teste.com", password="senha", role="PRODUTOR", band=self.banda3
        )

        # Banda Inativa
        self.banda_inativa = Band.objects.create(name="Banda Inativa", slug="banda-inativa", is_active=False)

        # Contato Compartilhado Válido (Origem na Banda 1)
        self.contato_global = Contact.objects.create(
            band=self.banda1,
            name="Fornecedor de Som Show",
            contact_type="FORNECEDOR",
            phone="11988887777",
            email="som@fornecedor.com",
            location="São Paulo - SP",
            link="https://somfornecedor.com.br",
            notes="Nota interna confidencial da banda 1",
            public_information="Atendimento 24h para shows e festivais",
            is_shared_globally=True,
            shared_by=self.produtor1,
            is_hidden=False
        )

        # Contato Particular (Não compartilhado)
        self.contato_particular = Contact.objects.create(
            band=self.banda1,
            name="Contato Particular Secreto",
            contact_type="FORNECEDOR",
            phone="11911112222",
            is_shared_globally=False,
            is_hidden=False
        )

        # Contato Oculto pelo Admin
        self.contato_oculto = Contact.objects.create(
            band=self.banda1,
            name="Contato Ocultado Admin",
            contact_type="FORNECEDOR",
            phone="11933334444",
            is_shared_globally=True,
            is_hidden=True
        )

        # Contato de Banda Inativa
        self.contato_banda_inativa = Contact.objects.create(
            band=self.banda_inativa,
            name="Contato Banda Inativa",
            contact_type="FORNECEDOR",
            phone="11955556666",
            is_shared_globally=True,
            is_hidden=False
        )

    def test_01_produtor_visualiza_botao_copiar_no_modal(self):
        self.client.login(username="produtor2", password="senha")
        response = self.client.get(reverse('banco_de_dados_global'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('bp-btn-copy-contact', html)
        self.assertIn('Copiar', html)
        self.assertIn(f'data-copy-url="{reverse("contact_copy_from_global", args=[self.banda2.slug, self.contato_global.id])}"', html)

    def test_02_integrante_sem_permissao_nao_visualiza_botao_copiar(self):
        self.client.login(username="integrante2", password="senha")
        response = self.client.get(reverse('banco_de_dados_global'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertNotIn('bp-btn-copy-contact', html)
        self.assertNotIn('data-copy-url="', html)

    def test_03_integrante_sem_permissao_recebe_403_no_endpoint(self):
        self.client.login(username="integrante2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_04_anonimo_recebe_redirecionamento_ou_bloqueio(self):
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        response = self.client.post(url)
        self.assertIn(response.status_code, [302, 403])

    def test_05_endpoint_aceita_somente_post(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_06_endpoint_exige_csrf(self):
        self.csrf_client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        # POST sem token CSRF
        response = self.csrf_client.post(url)
        self.assertEqual(response.status_code, 403)

        # POST com token CSRF válido
        res_page = self.csrf_client.get(reverse('banco_de_dados_global'))
        csrf_token = res_page.cookies['csrftoken'].value
        response_valid = self.csrf_client.post(url, HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(response_valid.status_code, 200)

    def test_07_contato_compartilhado_e_visivel_pode_ser_copiado(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'copied')

        # Verifica cópia criada
        copy = Contact.objects.get(id=data['contact_id'])
        self.assertEqual(copy.band, self.banda2)
        self.assertEqual(copy.copied_from, self.contato_global)

    def test_08_contato_particular_retorna_404(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_particular.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Contact.objects.filter(band=self.banda2, copied_from=self.contato_particular).exists())

    def test_09_contato_oculto_retorna_404(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_oculto.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Contact.objects.filter(band=self.banda2, copied_from=self.contato_oculto).exists())

    def test_10_contato_de_banda_inativa_retorna_404(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_banda_inativa.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Contact.objects.filter(band=self.banda2, copied_from=self.contato_banda_inativa).exists())

    def test_11_banda_de_destino_vem_do_contexto_autenticado_impede_idor(self):
        self.client.login(username="produtor2", password="senha")
        # Produtor da Banda 2 tenta enviar cópia fingindo ser a Banda 1 ou Banda 3
        url_forjada = reverse('contact_copy_from_global', args=[self.banda3.slug, self.contato_global.id])
        response = self.client.post(url_forjada)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Contact.objects.filter(band=self.banda3, copied_from=self.contato_global).exists())

    def test_12_todos_os_campos_de_conteudo_sao_copiados_e_metadados_isolados(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

        copy = Contact.objects.get(band=self.banda2, copied_from=self.contato_global)
        # Campos de conteúdo copiados
        self.assertEqual(copy.name, self.contato_global.name)
        self.assertEqual(copy.contact_type, self.contato_global.contact_type)
        self.assertEqual(copy.phone, self.contato_global.phone)
        self.assertEqual(copy.email, self.contato_global.email)
        self.assertEqual(copy.location, self.contato_global.location)
        self.assertEqual(copy.link, self.contato_global.link)
        self.assertEqual(copy.notes, '')
        self.assertEqual(copy.public_information, self.contato_global.public_information)

        # Regras de isolamento / novos metadados
        self.assertNotEqual(copy.id, self.contato_global.id)
        self.assertEqual(copy.band, self.banda2)
        self.assertFalse(copy.is_shared_globally)
        self.assertFalse(copy.is_hidden)
        self.assertIsNone(copy.shared_by)
        self.assertIsNone(copy.shared_at)
        self.assertEqual(copy.copied_from, self.contato_global)

    def test_13_origem_permanece_inalterada(self):
        orig_name = self.contato_global.name
        orig_notes = self.contato_global.notes
        orig_shared = self.contato_global.is_shared_globally

        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        self.client.post(url)

        self.contato_global.refresh_from_db()
        self.assertEqual(self.contato_global.name, orig_name)
        self.assertEqual(self.contato_global.notes, orig_notes)
        self.assertEqual(self.contato_global.is_shared_globally, orig_shared)
        self.assertEqual(self.contato_global.band, self.banda1)

    def test_14_edicao_da_copia_nao_altera_origem(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        res = self.client.post(url)
        copy_id = res.json()['contact_id']

        # Editar a cópia na Banda 2
        edit_url = reverse('contatos_edit', args=[self.banda2.slug, copy_id])
        edit_data = {
            'name': 'Nome Totalmente Modificado Pela Banda 2',
            'contact_type': 'CONTRATANTE',
            'phone': '11900000000',
            'email': 'novo@email.com',
            'location': 'Rio de Janeiro - RJ',
            'link': 'https://novolink.com',
            'notes': 'Nova observação interna particular',
            'public_information': 'Nova info pública',
            'is_shared_globally': False
        }
        self.client.post(edit_url, edit_data)

        # Confirma cópia alterada
        copy = Contact.objects.get(id=copy_id)
        self.assertEqual(copy.name, 'Nome Totalmente Modificado Pela Banda 2')

        # Confirma origem 100% intacta
        self.contato_global.refresh_from_db()
        self.assertEqual(self.contato_global.name, 'Fornecedor de Som Show')
        self.assertEqual(self.contato_global.phone, '11988887777')
        self.assertEqual(self.contato_global.location, 'São Paulo - SP')

    def test_15_edicao_da_origem_nao_altera_copia(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        res = self.client.post(url)
        copy_id = res.json()['contact_id']

        # Banda 1 edita a origem
        self.client.login(username="produtor1", password="senha")
        edit_url = reverse('contatos_edit', args=[self.banda1.slug, self.contato_global.id])
        edit_data = {
            'name': 'Fornecedor de Som Atualizado Origem',
            'contact_type': 'FORNECEDOR',
            'phone': '11988887777',
            'email': 'som@fornecedor.com',
            'location': 'Campinas - SP',
            'link': 'https://somfornecedor.com.br',
            'notes': 'Nota alterada pela banda 1',
            'public_information': 'Info alterada pela banda 1',
            'is_shared_globally': True
        }
        self.client.post(edit_url, edit_data)

        # Confirma origem alterada
        self.contato_global.refresh_from_db()
        self.assertEqual(self.contato_global.name, 'Fornecedor de Som Atualizado Origem')

        # Confirma cópia da Banda 2 inalterada
        copy = Contact.objects.get(id=copy_id)
        self.assertEqual(copy.name, 'Fornecedor de Som Show')
        self.assertEqual(copy.location, 'São Paulo - SP')

    def test_16_clique_ou_requisicao_duplicada_e_idempotente(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])

        # Primeira requisição
        res1 = self.client.post(url)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()['status'], 'copied')

        # Segunda requisição idêntica
        res2 = self.client.post(url)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()['status'], 'already_copied')

        # Apenas 1 cópia existe
        self.assertEqual(Contact.objects.filter(band=self.banda2, copied_from=self.contato_global).count(), 1)

    def test_17_constraint_de_banco_impede_duplicidade_concorrente(self):
        from django.db import IntegrityError
        Contact.objects.create(
            band=self.banda2,
            name="Cópia 1",
            copied_from=self.contato_global,
            is_shared_globally=False
        )

        # Tentativa direta de violar constraint no banco
        with self.assertRaises(IntegrityError):
            Contact.objects.create(
                band=self.banda2,
                name="Cópia Duplicada Concorrente",
                copied_from=self.contato_global,
                is_shared_globally=False
            )

    def test_18_bandas_diferentes_podem_copiar_a_mesma_origem(self):
        # Banda 2 copia
        self.client.login(username="produtor2", password="senha")
        url2 = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        res2 = self.client.post(url2)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()['status'], 'copied')

        # Banda 3 copia a mesma origem
        self.client.login(username="produtor3", password="senha")
        url3 = reverse('contact_copy_from_global', args=[self.banda3.slug, self.contato_global.id])
        res3 = self.client.post(url3)
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.json()['status'], 'copied')

        self.assertTrue(Contact.objects.filter(band=self.banda2, copied_from=self.contato_global).exists())
        self.assertTrue(Contact.objects.filter(band=self.banda3, copied_from=self.contato_global).exists())

    def test_19_contato_pertencente_a_propria_banda_nao_e_duplicado(self):
        # Produtor 1 da Banda 1 tenta copiar contato que já é da Banda 1
        self.client.login(username="produtor1", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda1.slug, self.contato_global.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'already_copied')
        self.assertFalse(Contact.objects.filter(band=self.banda1, copied_from=self.contato_global).exists())

    def test_20_estado_copiado_permanece_apos_recarregar_pagina(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        self.client.post(url)

        # Recarrega página
        response = self.client.get(reverse('banco_de_dados_global'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Botão deve estar no estado 'is-copied' desabilitado com texto 'Copiado'
        self.assertIn('is-copied', html)
        self.assertIn('Copiado', html)
        self.assertIn('disabled', html)

    def test_21_excluir_a_copia_permite_copiar_novamente(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        res = self.client.post(url)
        copy_id = res.json()['contact_id']

        # Excluir a cópia
        del_url = reverse('contatos_delete', args=[self.banda2.slug, copy_id])
        del_res = self.client.post(del_url)
        self.assertEqual(del_res.status_code, 302)

        # Agora a cópia não existe mais
        self.assertFalse(Contact.objects.filter(id=copy_id).exists())

        # Página do banco de dados volta a exibir 'Copiar'
        response = self.client.get(reverse('banco_de_dados_global'))
        html = response.content.decode('utf-8')
        self.assertIn('Copiar', html)

        # Permite copiar novamente
        res_novo = self.client.post(url)
        self.assertEqual(res_novo.status_code, 200)
        self.assertEqual(res_novo.json()['status'], 'copied')
        self.assertTrue(Contact.objects.filter(band=self.banda2, copied_from=self.contato_global).exists())

    def test_22_excluir_a_origem_preserva_a_copia(self):
        self.client.login(username="produtor2", password="senha")
        url = reverse('contact_copy_from_global', args=[self.banda2.slug, self.contato_global.id])
        res = self.client.post(url)
        copy_id = res.json()['contact_id']

        # Origem é excluída pela Banda 1
        self.client.login(username="produtor1", password="senha")
        del_orig_url = reverse('contatos_delete', args=[self.banda1.slug, self.contato_global.id])
        self.client.post(del_orig_url)

        # Confirma que a cópia na Banda 2 continua existindo
        copy = Contact.objects.get(id=copy_id)
        self.assertEqual(copy.band, self.banda2)
        self.assertIsNone(copy.copied_from)  # SET_NULL conforme especificado


class ContatosMultiBandaTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Banda 1 (com contatos)
        self.banda1 = Band.objects.create(name="Danniel Vieira", slug="dannielvieira", is_active=True)
        self.produtor1 = User.objects.create_user(
            username="produtor_dv", email="dv@teste.com", password="senha", role="PRODUTOR", band=self.banda1
        )
        self.contato1 = Contact.objects.create(
            band=self.banda1,
            name="Contato Existente DV",
            phone="71999990001",
            contact_type="FORNECEDOR"
        )

        # Banda 2 (sem nenhum contato inicial)
        self.banda2 = Band.objects.create(name="Matheus Kennedy", slug="matheuskennedy", is_active=True)
        self.produtor2 = User.objects.create_user(
            username="produtor_mk", email="mk@teste.com", password="senha", role="PRODUTOR", band=self.banda2
        )

    def test_1_banda_com_contatos_consegue_adicionar(self):
        self.client.login(username="produtor_dv", password="senha")
        data = {
            'name': 'Novo Fornecedor DV',
            'phone': '71999990002',
            'contact_type': 'FORNECEDOR',
            'location': 'Salvador - BA'
        }
        url = reverse('contatos_add', args=[self.banda1.slug])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Contact.objects.filter(band=self.banda1, name='Novo Fornecedor DV').exists())

    def test_2_banda_nova_sem_contatos_consegue_abrir_modal_e_adicionar(self):
        self.client.login(username="produtor_mk", password="senha")

        # Verifica abertura da página vazia e presença do modal de adição
        page_url = reverse('contatos_list', args=[self.banda2.slug])
        response_get = self.client.get(page_url)
        self.assertEqual(response_get.status_code, 200)
        html = response_get.content.decode('utf-8')

        # Modal deve existir mesmo sem nenhum contato cadastrado
        self.assertIn('id="modalNovoContato"', html)
        self.assertIn(f'action="{reverse("contatos_add", args=[self.banda2.slug])}"', html)

        # Efetua adição
        add_url = reverse('contatos_add', args=[self.banda2.slug])
        data = {
            'name': 'Primeiro Contato MK',
            'phone': '71988880001',
            'contact_type': 'CONTRATANTE',
            'location': 'Feira de Santana - BA'
        }
        response_post = self.client.post(add_url, data)
        self.assertEqual(response_post.status_code, 302)
        self.assertTrue(Contact.objects.filter(band=self.banda2, name='Primeiro Contato MK').exists())

    def test_3_contato_salvo_na_banda_correta(self):
        self.client.login(username="produtor_mk", password="senha")
        add_url = reverse('contatos_add', args=[self.banda2.slug])
        data = {
            'name': 'Hotel MK',
            'phone': '71977770001',
            'contact_type': 'HOSPEDAGEM',
            'location': 'Salvador - BA'
        }
        self.client.post(add_url, data)

        created = Contact.objects.get(name='Hotel MK')
        self.assertEqual(created.band, self.banda2)
        self.assertNotEqual(created.band, self.banda1)

    def test_4_outra_banda_nao_acessa_nem_recebe_o_contato(self):
        # Banda 1 acessa listagem e não vê contatos da Banda 2
        self.client.login(username="produtor_dv", password="senha")
        response = self.client.get(reverse('contatos_list', args=[self.banda1.slug]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('Contato Existente DV', html)
        self.assertNotIn('Primeiro Contato MK', html)

        # Produtor da Banda 1 tenta forjar adição no slug da Banda 2 -> 403 Forbidden
        forge_url = reverse('contatos_add', args=[self.banda2.slug])
        data_forge = {
            'name': 'Contato Invasor',
            'phone': '71966660001',
            'contact_type': 'FORNECEDOR'
        }
        response_forge = self.client.post(forge_url, data_forge)
        self.assertEqual(response_forge.status_code, 403)
        self.assertFalse(Contact.objects.filter(name='Contato Invasor').exists())


class ContactLikesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band_a = Band.objects.create(name="Banda A", slug="banda-a", is_active=True)
        self.band_b = Band.objects.create(name="Banda B", slug="banda-b", is_active=True)
        self.band_c = Band.objects.create(name="Banda C", slug="banda-c", is_active=True)

        self.produtor_a = User.objects.create_user(
            username="produtor_a", first_name="Carlos", last_name="Silva",
            email="prod_a@teste.com", password="senha", role="PRODUTOR", band=self.band_a
        )
        self.produtor_b = User.objects.create_user(
            username="produtor_b", first_name="Ana", last_name="Souza",
            email="prod_b@teste.com", password="senha", role="PRODUTOR", band=self.band_b
        )
        self.produtor_c = User.objects.create_user(
            username="produtor_c", first_name="Marcos", last_name="Lima",
            email="prod_c@teste.com", password="senha", role="PRODUTOR", band=self.band_c
        )
        self.integrante_b = User.objects.create_user(
            username="integrante_b", email="int_b@teste.com", password="senha",
            role="INTEGRANTE", band=self.band_b
        )

        self.contact_a = Contact.objects.create(
            band=self.band_a,
            name="Fornecedor Som Global",
            phone="11999990001",
            contact_type="FORNECEDOR",
            location="São Paulo - SP",
            is_shared_globally=True,
            is_hidden=False,
            shared_by=self.produtor_a
        )

    # 1. Renderização da contagem, lista e estado do coração
    def test_1_renderizacao_contagem_lista_e_coracao(self):
        from core.models import ContactLike
        # Inicialmente sem curtidas
        self.client.login(username="produtor_b", password="senha")
        response = self.client.get(reverse('banco_de_dados_global'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Coluna Curtidas presente
        self.assertIn('Curtidas', html)
        # Pill com contagem 0
        self.assertIn('class="js-likes-count-text">0</span>', html)
        # Modal de lista com mensagem de vazio
        self.assertIn('Nenhum produtor curtiu este contato ainda.', html)
        # Coração descurtido (fa-regular fa-heart) para produtor de outra banda
        self.assertIn('fa-regular fa-heart', html)

        # Adiciona uma curtida
        ContactLike.objects.create(contact=self.contact_a, user=self.produtor_b, band=self.band_b)
        response2 = self.client.get(reverse('banco_de_dados_global'))
        html2 = response2.content.decode('utf-8')
        # Pill com contagem 1
        self.assertIn('class="js-likes-count-text">1</span>', html2)
        # Produtor e banda no modal
        self.assertIn('Ana Souza', html2)
        self.assertIn('Banda B', html2)
        # Coração curtido (fa-solid fa-heart)
        self.assertIn('fa-solid fa-heart', html2)

    # 2. Produtor curtindo o contato
    def test_2_produtor_curtindo_contato(self):
        from core.models import ContactLike
        self.client.login(username="produtor_b", password="senha")
        like_url = reverse('contact_toggle_like', args=[self.band_b.slug, self.contact_a.id])

        response = self.client.post(like_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['is_liked'])
        self.assertEqual(data['likes_count'], 1)
        self.assertEqual(len(data['likes_list']), 1)
        self.assertEqual(data['likes_list'][0]['producer_name'], 'Ana Souza')
        self.assertEqual(data['likes_list'][0]['band_name'], 'Banda B')
        self.assertTrue(ContactLike.objects.filter(contact=self.contact_a, user=self.produtor_b).exists())

    # 3. Produtor descurtindo sem gerar duplicidade
    def test_3_produtor_descurtindo_sem_duplicidade(self):
        from core.models import ContactLike
        ContactLike.objects.create(contact=self.contact_a, user=self.produtor_b, band=self.band_b)
        self.assertEqual(ContactLike.objects.filter(contact=self.contact_a).count(), 1)

        self.client.login(username="produtor_b", password="senha")
        like_url = reverse('contact_toggle_like', args=[self.band_b.slug, self.contact_a.id])

        response = self.client.post(like_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['is_liked'])
        self.assertEqual(data['likes_count'], 0)
        self.assertEqual(len(data['likes_list']), 0)
        self.assertFalse(ContactLike.objects.filter(contact=self.contact_a, user=self.produtor_b).exists())

    # 4. Permissões de produtor, integrante e anônimo
    def test_4_permissoes_produtor_integrante_e_anonimo(self):
        like_url_b = reverse('contact_toggle_like', args=[self.band_b.slug, self.contact_a.id])

        # Anônimo é redirecionado para login
        response_anon = self.client.post(like_url_b)
        self.assertEqual(response_anon.status_code, 302)

        # Integrante recebe 403 Forbidden
        self.client.login(username="integrante_b", password="senha")
        response_int = self.client.post(like_url_b)
        self.assertEqual(response_int.status_code, 403)

        # Integrante visualizando banco de dados geral não vê o botão HTML de coração
        # (a classe também aparece no bloco <script> do listener, portanto checamos o data-like-url)
        response_view = self.client.get(reverse('banco_de_dados_global'))
        self.assertNotIn('data-like-url=', response_view.content.decode('utf-8'))

    # 5. Bloqueio de contato próprio, particular, oculto ou inválido
    def test_5_bloqueio_proprio_particular_oculto_ou_invalido(self):
        # 5.1 Produtor tentando curtir contato da própria banda -> 400 Bad Request
        self.client.login(username="produtor_a", password="senha")
        like_url_a = reverse('contact_toggle_like', args=[self.band_a.slug, self.contact_a.id])
        response_self = self.client.post(like_url_a)
        self.assertEqual(response_self.status_code, 400)

        # Produtor da própria banda não vê o botão de coração no modal
        # (verificamos a presença do data-like-url que só aparece no botão HTML, não no script)
        response_self_view = self.client.get(reverse('banco_de_dados_global'))
        self.assertNotIn('data-like-url=', response_self_view.content.decode('utf-8'))

        # 5.2 Contato não compartilhado globalmente (particular) -> 404
        contact_private = Contact.objects.create(
            band=self.band_a, name="Privado", phone="11999990002",
            is_shared_globally=False, is_hidden=False
        )
        self.client.login(username="produtor_b", password="senha")
        like_private_url = reverse('contact_toggle_like', args=[self.band_b.slug, contact_private.id])
        self.assertEqual(self.client.post(like_private_url).status_code, 404)

        # 5.3 Contato oculto pelo admin -> 404
        contact_hidden = Contact.objects.create(
            band=self.band_a, name="Oculto", phone="11999990003",
            is_shared_globally=True, is_hidden=True
        )
        like_hidden_url = reverse('contact_toggle_like', args=[self.band_b.slug, contact_hidden.id])
        self.assertEqual(self.client.post(like_hidden_url).status_code, 404)

        # 5.4 Contato com ID inexistente -> 404
        like_invalid_url = reverse('contact_toggle_like', args=[self.band_b.slug, 999999])
        self.assertEqual(self.client.post(like_invalid_url).status_code, 404)

    # 6. Produtores diferentes curtindo o mesmo contato
    def test_6_produtores_diferentes_curtindo_mesmo_contato(self):
        from core.models import ContactLike
        # Produtor B curte
        self.client.login(username="produtor_b", password="senha")
        like_url_b = reverse('contact_toggle_like', args=[self.band_b.slug, self.contact_a.id])
        res_b = self.client.post(like_url_b)
        self.assertEqual(res_b.json()['likes_count'], 1)

        # Produtor C curte o mesmo contato
        self.client.login(username="produtor_c", password="senha")
        like_url_c = reverse('contact_toggle_like', args=[self.band_c.slug, self.contact_a.id])
        res_c = self.client.post(like_url_c)
        self.assertEqual(res_c.json()['likes_count'], 2)
        self.assertEqual(len(res_c.json()['likes_list']), 2)

        self.assertEqual(ContactLike.objects.filter(contact=self.contact_a).count(), 2)

    # 7. Funcionamento multibanda, cópia limpa e ausência de N+1 relevante
    def test_7_multibanda_copia_limpa_e_sem_n_plus_1(self):
        from core.models import ContactLike
        # Curtidas no contato original
        ContactLike.objects.create(contact=self.contact_a, user=self.produtor_b, band=self.band_b)
        ContactLike.objects.create(contact=self.contact_a, user=self.produtor_c, band=self.band_c)

        # Produtor B copia o contato para a Banda B
        self.client.login(username="produtor_b", password="senha")
        copy_url = reverse('contact_copy_from_global', args=[self.band_b.slug, self.contact_a.id])
        res_copy = self.client.post(copy_url)
        self.assertTrue(res_copy.json()['ok'])

        # O contato copiado não possui nenhuma curtida associada
        copied_contact = Contact.objects.get(band=self.band_b, copied_from=self.contact_a)
        self.assertEqual(copied_contact.likes.count(), 0)
        # O contato original preserva suas 2 curtidas intactas
        self.assertEqual(self.contact_a.likes.count(), 2)

        # Teste de ausência de N+1: com 1 contato, mede o baseline de queries da view
        from django.test.utils import CaptureQueriesContext
        from django.db import connection as db_conn
        self.client.login(username="produtor_b", password="senha")
        with CaptureQueriesContext(db_conn) as ctx_1contact:
            r1 = self.client.get(reverse('banco_de_dados_global'))
            self.assertEqual(r1.status_code, 200)
        queries_1 = len(ctx_1contact.captured_queries)

        # Adiciona mais 4 contatos globais de outras bandas
        for i in range(4):
            Contact.objects.create(
                band=self.band_c, name=f"Extra {i}", phone=f"1199999{9000+i}",
                contact_type="FORNECEDOR", is_shared_globally=True, is_hidden=False,
                shared_by=self.produtor_c
            )

        with CaptureQueriesContext(db_conn) as ctx_5contacts:
            r5 = self.client.get(reverse('banco_de_dados_global'))
            self.assertEqual(r5.status_code, 200)
        queries_5 = len(ctx_5contacts.captured_queries)

        # Sem N+1: o número de queries NÃO deve crescer ao adicionar mais contatos.
        # Na 1ª requisição o Django faz warm-up (SystemSettings INSERT, cache de permissões etc.)
        # que ficam em cache nas requisições seguintes, então queries_5 <= queries_1 é correto.
        self.assertLessEqual(queries_5, queries_1,
            f"N+1 detectado: {queries_5} queries para 5 contatos > {queries_1} queries para 1 contato")
