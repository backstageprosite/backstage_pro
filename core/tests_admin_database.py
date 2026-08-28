from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.db.models import ProtectedError
from core.models import Band, Contact

User = get_user_model()

class AdminDatabaseTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', password='123', email='admin@test.com')
        self.produtor = User.objects.create_user(username='prod', password='123', role='PRODUTOR')
        self.integrante = User.objects.create_user(username='integ', password='123', role='INTEGRANTE')
        self.random_user = User.objects.create_user(username='rand', password='123')

        self.banda1 = Band.objects.create(name='Banda 1', slug='banda-1', is_active=True)
        self.banda2 = Band.objects.create(name='Banda 2', slug='banda-2', is_active=True)

        self.produtor.band = self.banda1
        self.produtor.save()
        self.integrante.band = self.banda1
        self.integrante.save()

        self.contact1 = Contact.objects.create(
            band=self.banda1,
            name='Contato Um',
            phone='(11) 98888-7777',
            normalized_phone='11988887777',
            email='contato1@teste.com',
            normalized_email='contato1@teste.com',
            is_shared_globally=True,
            is_hidden=False
        )
        self.contact2 = Contact.objects.create(
            band=self.banda2,
            name='Contato Dois',
            phone='(21) 97777-6666',
            normalized_phone='21977776666',
            email='contato2@teste.com',
            normalized_email='contato2@teste.com',
            is_shared_globally=True,
            is_hidden=True
        )

        # Clientes regulares para testes funcionais
        self.client_admin = Client()
        self.client_admin.login(username='admin', password='123')

        self.client_prod = Client()
        self.client_prod.login(username='prod', password='123')

        self.client_integ = Client()
        self.client_integ.login(username='integ', password='123')

        self.client_rand = Client()
        self.client_rand.login(username='rand', password='123')

        self.client_anon = Client()

        # Clientes com CSRF estrito
        self.csrf_client_admin = Client(enforce_csrf_checks=True)
        self.csrf_client_admin.login(username='admin', password='123')

    # 1. Administrador acessa a página
    def test_01_admin_access(self):
        response = self.client_admin.get(reverse('admin_painel:database_list'))
        self.assertEqual(response.status_code, 200)

    # 2. Produtor não acessa a página administrativa
    def test_02_produtor_no_access(self):
        response = self.client_prod.get(reverse('admin_painel:database_list'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/painel/login/'))

    # 3. Integrante não acessa
    def test_03_integrante_no_access(self):
        response = self.client_integ.get(reverse('admin_painel:database_list'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/painel/login/'))

    # 4. Usuário anônimo não acessa
    def test_04_anon_no_access(self):
        response = self.client_anon.get(reverse('admin_painel:database_list'))
        self.assertRedirects(response, '/painel/login/?next=/painel/banco-de-dados/')

    # 5. Contatos de bandas diferentes aparecem para o administrador
    def test_05_admin_sees_both_bands_contacts(self):
        response = self.client_admin.get(reverse('admin_painel:database_list'))
        self.assertContains(response, 'Contato Um')
        self.assertContains(response, 'Contato Dois')
        self.assertContains(response, 'Banda 1')
        self.assertContains(response, 'Banda 2')

    # 6. Filtro por banda funciona
    def test_06_filter_by_band(self):
        response = self.client_admin.get(reverse('admin_painel:database_list') + '?banda=Banda 2')
        self.assertNotContains(response, 'Contato Um')
        self.assertContains(response, 'Contato Dois')

    # 7. Filtro por nome funciona
    def test_07_filter_by_name(self):
        response = self.client_admin.get(reverse('admin_painel:database_list') + '?nome=Um')
        self.assertContains(response, 'Contato Um')
        self.assertNotContains(response, 'Contato Dois')

    # 8. Filtro por situação funciona
    def test_08_filter_by_situacao(self):
        response_vis = self.client_admin.get(reverse('admin_painel:database_list') + '?situacao=visiveis')
        self.assertContains(response_vis, 'Contato Um')
        self.assertNotContains(response_vis, 'Contato Dois')

        response_ocu = self.client_admin.get(reverse('admin_painel:database_list') + '?situacao=ocultos')
        self.assertNotContains(response_ocu, 'Contato Um')
        self.assertContains(response_ocu, 'Contato Dois')

    # 9. Edição altera o registro original
    def test_09_edit_modifies_original(self):
        response = self.client_admin.post(reverse('admin_painel:database_edit', args=[self.contact1.id]), {
            'name': 'Contato Um Modificado',
            'contact_type': 'FORNECEDOR',
            'phone': '(11) 98888-7777',
            'email': 'contato1@teste.com',
            'is_shared_globally': True
        })
        self.assertEqual(response.status_code, 302)
        self.contact1.refresh_from_db()
        self.assertEqual(self.contact1.name, 'Contato Um Modificado')

    # 10. Edição não altera a banda de origem
    def test_10_edit_does_not_change_band_of_origin(self):
        response = self.client_admin.post(reverse('admin_painel:database_edit', args=[self.contact1.id]), {
            'name': 'Contato Um',
            'contact_type': 'FORNECEDOR',
            'band': self.banda2.id,
            'is_shared_globally': True
        })
        self.assertEqual(response.status_code, 302)
        self.contact1.refresh_from_db()
        self.assertEqual(self.contact1.band, self.banda1)

    # 11. Ocultar exige POST
    def test_11_hide_requires_post(self):
        response = self.client_admin.get(reverse('admin_painel:database_hide', args=[self.contact1.id]))
        self.assertEqual(response.status_code, 403)
        self.contact1.refresh_from_db()
        self.assertFalse(self.contact1.is_hidden)

    # 12. Ocultar exige CSRF
    def test_12_hide_requires_csrf(self):
        # Sem CSRF token
        response = self.csrf_client_admin.post(reverse('admin_painel:database_hide', args=[self.contact1.id]))
        self.assertEqual(response.status_code, 403)
        self.contact1.refresh_from_db()
        self.assertFalse(self.contact1.is_hidden)

        # Com CSRF token válido
        response_page = self.csrf_client_admin.get(reverse('admin_painel:database_list'))
        csrf_token = response_page.cookies['csrftoken'].value
        response_valid = self.csrf_client_admin.post(
            reverse('admin_painel:database_hide', args=[self.contact1.id]),
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(response_valid.status_code, 302)
        self.contact1.refresh_from_db()
        self.assertTrue(self.contact1.is_hidden)

    # 13. Contato oculto deixa de aparecer no painel das bandas
    def test_13_hidden_contact_not_in_band_panel(self):
        response_before = self.client_prod.get(reverse('contatos_list', args=['banda-1']))
        self.assertContains(response_before, 'Contato Um')

        self.client_admin.post(reverse('admin_painel:database_hide', args=[self.contact1.id]))

        response_after = self.client_prod.get(reverse('contatos_list', args=['banda-1']))
        self.assertNotContains(response_after, 'Contato Um')

        # Também não aparece na busca global de contatos da banda
        response_global = self.client_prod.get(reverse('banco_de_dados_global'))
        self.assertNotContains(response_global, 'Contato Um')

    # 14. Contato oculto não pode ser acessado diretamente pela banda
    def test_14_hidden_contact_cannot_be_accessed_directly_by_band(self):
        self.client_admin.post(reverse('admin_painel:database_hide', args=[self.contact1.id]))
        response = self.client_prod.get(reverse('contatos_edit', args=['banda-1', self.contact1.id]))
        self.assertEqual(response.status_code, 404)

    # 15. Contato oculto permanece visível no administrativo
    def test_15_hidden_contact_remains_visible_in_admin(self):
        self.client_admin.post(reverse('admin_painel:database_hide', args=[self.contact1.id]))
        response = self.client_admin.get(reverse('admin_painel:database_list'))
        self.assertContains(response, 'Contato Um')
        self.assertContains(response, 'Oculto')

    # 16. Desocultar exige POST
    def test_16_unhide_requires_post(self):
        response = self.client_admin.get(reverse('admin_painel:database_unhide', args=[self.contact2.id]))
        self.assertEqual(response.status_code, 403)
        self.contact2.refresh_from_db()
        self.assertTrue(self.contact2.is_hidden)

    # 17. Desocultar restaura o contato no painel das bandas
    def test_17_unhide_restores_contact_to_band_panel(self):
        # Desocultar com CSRF válido
        response_page = self.csrf_client_admin.get(reverse('admin_painel:database_list'))
        csrf_token = response_page.cookies['csrftoken'].value
        response = self.csrf_client_admin.post(
            reverse('admin_painel:database_unhide', args=[self.contact2.id]),
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(response.status_code, 302)
        self.contact2.refresh_from_db()
        self.assertFalse(self.contact2.is_hidden)

        # Login com produtor da banda 2
        prod2 = User.objects.create_user(username='prod2', password='123', role='PRODUTOR')
        prod2.band = self.banda2
        prod2.save()
        c2 = Client()
        c2.login(username='prod2', password='123')

        response_band = c2.get(reverse('contatos_list', args=['banda-2']))
        self.assertContains(response_band, 'Contato Dois')

    # 18. Exclusão exige POST
    def test_18_delete_requires_post(self):
        response = self.client_admin.get(reverse('admin_painel:database_delete', args=[self.contact1.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Contact.objects.filter(id=self.contact1.id).exists())

    # 19. Exclusão exige CSRF
    def test_19_delete_requires_csrf(self):
        # Sem CSRF token
        response = self.csrf_client_admin.post(reverse('admin_painel:database_delete', args=[self.contact1.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Contact.objects.filter(id=self.contact1.id).exists())

    # 20. Exclusão remove definitivamente um registro sem vínculos
    def test_20_delete_removes_definitely(self):
        response_page = self.csrf_client_admin.get(reverse('admin_painel:database_list'))
        csrf_token = response_page.cookies['csrftoken'].value
        response = self.csrf_client_admin.post(
            reverse('admin_painel:database_delete', args=[self.contact1.id]),
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Contact.objects.filter(id=self.contact1.id).exists())

    # 21. Exclusão protegida não causa erro 500
    def test_21_protected_delete_handled_gracefully(self):
        from unittest.mock import patch
        with patch.object(Contact, 'delete', side_effect=ProtectedError("Protegido por vinculo", [self.contact2])):
            response_page = self.csrf_client_admin.get(reverse('admin_painel:database_list'))
            csrf_token = response_page.cookies['csrftoken'].value
            response = self.csrf_client_admin.post(
                reverse('admin_painel:database_delete', args=[self.contact2.id]),
                HTTP_X_CSRFTOKEN=csrf_token,
                follow=True
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'não pode ser excluído')
            self.assertTrue(Contact.objects.filter(id=self.contact2.id).exists())

    # 22. Uma banda não obtém acesso indevido aos dados privados de outra
    def test_22_band_isolation(self):
        prod2 = User.objects.create_user(username='prod2_iso', password='123', role='PRODUTOR')
        prod2.band = self.banda2
        prod2.save()
        c2 = Client()
        c2.login(username='prod2_iso', password='123')

        # Banda 2 tenta editar contato da Banda 1
        response = c2.get(reverse('contatos_edit', args=['banda-2', self.contact1.id]))
        self.assertEqual(response.status_code, 404)

    # 23. Registros existentes permanecem visíveis por padrão
    def test_23_default_is_hidden_false(self):
        new_contact = Contact.objects.create(band=self.banda1, name='Novo Padrao')
        self.assertFalse(new_contact.is_hidden)

    # 24. WhatsApp e links são renderizados com segurança
    def test_24_whatsapp_and_links_safety(self):
        self.contact1.phone = "11988887777"
        self.contact1.link = "https://instagram.com/banda1"
        self.contact1.save()

        response = self.client_admin.get(reverse('admin_painel:database_list'))
        self.assertContains(response, 'https://wa.me/5511988887777')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, 'href="https://instagram.com/banda1"')

    # Testes complementares exigidos na Missao 17B
    def test_25_hidden_contact_blocks_duplication(self):
        # Contact 2 esta oculto e compartilhado globalmente com phone '(21) 97777-6666'
        self.assertTrue(self.contact2.is_hidden)
        self.assertTrue(self.contact2.is_shared_globally)

        # Tentativa de criar novo contato com mesmo telefone na banda 1
        response = self.client_prod.post(reverse('contatos_add', args=['banda-1']), {
            'name': 'Novo Clonado',
            'contact_type': 'FORNECEDOR',
            'phone': '(21) 97777-6666',
            'is_shared_globally': True
        })
        self.assertEqual(response.status_code, 200) # Form com erro (nao redireciona)
        self.assertContains(response, 'Este contato')

    def test_26_edit_own_instance_not_duplicate(self):
        # Editar o proprio contact 1 com seus dados atuais nao deve acusar duplicidade
        response = self.client_admin.post(reverse('admin_painel:database_edit', args=[self.contact1.id]), {
            'name': 'Contato Um Atualizado',
            'contact_type': 'FORNECEDOR',
            'phone': '(11) 98888-7777',
            'email': 'contato1@teste.com',
            'is_shared_globally': True
        })
        self.assertEqual(response.status_code, 302)
