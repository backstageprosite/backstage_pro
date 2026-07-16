from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band, Notification
from core.services.notifications import create_notification
from django.utils import timezone
from django.template import Context, Template

User = get_user_model()

class NotificationViewsTestCase(TestCase):
    def setUp(self):
        # Criar bandas
        self.banda = Band.objects.create(name='Banda Teste', slug='banda-teste', is_active=True)
        self.banda_inativa = Band.objects.create(name='Inativa', slug='inativa', is_active=False)
        self.banda_vizinha = Band.objects.create(name='Banda Vizinha', slug='vizinha', is_active=True)
        
        # Criar usuários
        self.produtor = User.objects.create_user(username='produtor', email='p@t.com', password='123', role='PRODUTOR', is_active=True, band=self.banda)
        self.integrante = User.objects.create_user(username='integrante', email='i@t.com', password='123', role='INTEGRANTE', is_active=True, band=self.banda)
        self.admin = User.objects.create_superuser(username='admin', email='a@t.com', password='123', is_active=True)
        self.inativo = User.objects.create_user(username='inativo', email='in@t.com', password='123', is_active=False, role='INTEGRANTE', band=self.banda)
        self.vizinho = User.objects.create_user(username='vizinho', email='v@t.com', password='123', is_active=True, role='PRODUTOR', band=self.banda_vizinha)

        # Configurar Client com CSRF
        self.client = Client(enforce_csrf_checks=True)

    def test_deslogado_redirecionado(self):
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        login_url = reverse('login', kwargs={'band_slug': self.banda.slug})
        self.assertRedirects(response, f'{login_url}?next={url}')

    def test_inativo_nao_acessa(self):
        self.client.force_login(self.inativo)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        # Inactive users might be treated as unauthenticated by Django and redirected (302) or 404 by our view.
        self.assertIn(response.status_code, [302, 404])

    def test_banda_inativa_bloqueia(self):
        self.client.force_login(self.produtor)
        # Tentar acessar a inativa
        url = reverse('notifications_list', kwargs={'band_slug': self.banda_inativa.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_slug_outra_banda_bloqueia_acesso_cruzado(self):
        self.client.force_login(self.produtor)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda_vizinha.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_admin_geral_nao_ve_de_terceiros(self):
        # Criar notificação para produtor
        create_notification(self.banda, self.produtor, 'NEW_SHOW', 'X', 'msg', f'/{self.banda.slug}/', 'k1')
        
        # Logar admin
        self.client.force_login(self.admin)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 0) # Não deve ver a notificação do produtor

    def test_produtor_e_integrante_isolados(self):
        n1 = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'X', 'msg', f'/{self.banda.slug}/', 'k1')[0]
        n2 = create_notification(self.banda, self.integrante, 'NEW_SHOW', 'Y', 'msg', f'/{self.banda.slug}/', 'k2')[0]
        
        self.client.force_login(self.produtor)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        # Deve ver só a dele
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['page_obj'][0].id, n1.id)

    def test_central_lista_paginacao_e_ordem(self):
        self.client.force_login(self.produtor)
        # Criar 25 notificações
        for i in range(25):
            create_notification(self.banda, self.produtor, 'NEW_SHOW', f'Msg {i}', 'msg', f'/{self.banda.slug}/', f'k_{i}')
            
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 20) # Página 1 = 20 itens
        
        # A última criada deve ser a primeira
        self.assertIn('Msg 24', response.content.decode())

    def test_filtro_nao_lidas(self):
        n1 = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T1', 'msg', f'/{self.banda.slug}/1', 'k1')[0]
        n2 = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T2', 'msg', f'/{self.banda.slug}/2', 'k2')[0]
        # Marcar n1 como lida manualmente no banco
        n1.read_at = timezone.now()
        n1.save()
        
        self.client.force_login(self.produtor)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug}) + "?filtro=nao_lidas"
        response = self.client.get(url)
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['page_obj'][0].id, n2.id)

    def test_marcar_como_lida_get_405(self):
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T1', 'msg', f'/{self.banda.slug}/', 'k1')[0]
        self.client.force_login(self.produtor)
        url = reverse('notification_mark_read', kwargs={'band_slug': self.banda.slug, 'pk': n.pk})
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_marcar_como_lida_post(self):
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T1', 'msg', f'/{self.banda.slug}/', 'k1')[0]
        self.client.force_login(self.produtor)
        url = reverse('notification_mark_read', kwargs={'band_slug': self.banda.slug, 'pk': n.pk})
        
        # Testando falha de CSRF com o client
        response_csrf = self.client.post(url)
        self.assertEqual(response_csrf.status_code, 403)
        
        # Com client normal (para burlar enforce_csrf_checks no teste, instanciamos outro normal ou usamos mock)
        # Vamos usar um Client sem enforce para simular POST com token válido da sessão
        client = Client()
        client.force_login(self.produtor)
        response = client.post(url)
        self.assertRedirects(response, reverse('notifications_list', kwargs={'band_slug': self.banda.slug}))
        
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_marcar_notificacao_terceiro_404(self):
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T1', 'msg', f'/{self.banda.slug}/', 'k1')[0]
        client = Client()
        client.force_login(self.integrante) # tenta marcar a do produtor
        url = reverse('notification_mark_read', kwargs={'band_slug': self.banda.slug, 'pk': n.pk})
        response = client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_marcar_todas(self):
        create_notification(self.banda, self.produtor, 'NEW_SHOW', '1', 'msg', f'/{self.banda.slug}/', 'k1')
        create_notification(self.banda, self.produtor, 'NEW_SHOW', '2', 'msg', f'/{self.banda.slug}/', 'k2')
        
        client = Client()
        client.force_login(self.produtor)
        url = reverse('notifications_mark_all_read', kwargs={'band_slug': self.banda.slug})
        response = client.post(url)
        
        self.assertRedirects(response, reverse('notifications_list', kwargs={'band_slug': self.banda.slug}))
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 0)

    def test_abrir_notificacao_post_marca_e_redireciona(self):
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T', 'msg', f'/{self.banda.slug}/shows/', 'k1')[0]
        client = Client()
        client.force_login(self.produtor)
        url = reverse('notification_open', kwargs={'band_slug': self.banda.slug, 'pk': n.pk})
        
        response = client.post(url)
        self.assertRedirects(response, n.target_url, fetch_redirect_response=False)
        
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_abrir_target_invalido_404_sem_marcar(self):
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'T', 'msg', f'/{self.banda.slug}/shows/', 'k2')[0]
        n.target_url = "https://hacker.com"
        n.save()
        
        client = Client()
        client.force_login(self.produtor)
        url = reverse('notification_open', kwargs={'band_slug': self.banda.slug, 'pk': n.pk})
        
        response = client.post(url)
        self.assertEqual(response.status_code, 404)
        
        n.refresh_from_db()
        self.assertIsNone(n.read_at)

    def test_tag_template_duas_queries_e_nenhuma_target_url(self):
        create_notification(self.banda, self.produtor, 'NEW_SHOW', 'Tag1', 'msg', f'/{self.banda.slug}/', 'k1')
        
        # Avalia a tag
        template = Template("{% load notification_tags %}{% render_notifications_bell %}")
        context = Context({'request': type('Req', (), {'user': self.produtor, 'resolver_match': type('RM', (), {'url_name': 'shows_list'})()})(), 'band': self.banda})
        
        # Usa assertNumQueries para garantir que a tag executa no máximo 2 queries
        with self.assertNumQueries(2):
            output = template.render(context)
            
        self.assertIn('Tag1', output)
        self.assertNotIn('href="/banda-teste/"', output) # Nenhuma url vazada no DOM

    def test_script_escapado(self):
        create_notification(self.banda, self.produtor, 'NEW_SHOW', '<script>alert(1)</script>', 'msg', f'/{self.banda.slug}/', 'k2')
        
        template = Template("{% load notification_tags %}{% render_notifications_bell %}")
        context = Context({'request': type('Req', (), {'user': self.produtor, 'resolver_match': type('RM', (), {'url_name': 'shows_list'})()})(), 'band': self.banda})
        output = template.render(context)
        
        self.assertNotIn('<script>alert(1)</script>', output)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', output)

    def test_dropdown_limite_cinco(self):
        for i in range(10):
            create_notification(self.banda, self.produtor, 'NEW_SHOW', f'Msg {i}', 'msg', f'/{self.banda.slug}/', f'key_{i}')
        
        template = Template("{% load notification_tags %}{% render_notifications_bell %}")
        context = Context({'request': type('Req', (), {'user': self.produtor, 'resolver_match': type('RM', (), {'url_name': 'shows_list'})()})(), 'band': self.banda})
        output = template.render(context)
        
        self.assertIn('Msg 9', output)
        self.assertIn('Msg 5', output)
        self.assertNotIn('Msg 4', output) # Apenas as 5 mais recentes (5 a 9)

    def test_ordenacao_estavel(self):
        from django.utils import timezone
        
        now = timezone.now()
        
        # Gerar duas notificações
        n1, _ = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'Notif 1', 'msg', f'/{self.banda.slug}/', 'k1')
        n2, _ = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'Notif 2', 'msg', f'/{self.banda.slug}/', 'k2')
        
        # Forçar o mesmo created_at
        Notification.objects.filter(pk__in=[n1.pk, n2.pk]).update(created_at=now)
        
        # Na central (paginada)
        self.client.force_login(self.produtor)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        page_obj = response.context['page_obj']
        
        # A de maior PK (n2) deve vir primeiro
        self.assertEqual(page_obj[0].pk, n2.pk)
        self.assertEqual(page_obj[1].pk, n1.pk)
        
        # No dropdown
        template = Template("{% load notification_tags %}{% render_notifications_bell %}")
        context = Context({'request': type('Req', (), {'user': self.produtor, 'resolver_match': type('RM', (), {'url_name': 'shows_list'})()})(), 'band': self.banda})
        output = template.render(context)
        
        # A renderização do n2 deve vir antes da n1 no html
        idx2 = output.find('Notif 2')
        idx1 = output.find('Notif 1')
        self.assertTrue(idx2 < idx1)
        self.assertTrue(idx2 > -1 and idx1 > -1)

    def test_comportamento_ui_unread_count(self):
        # 1. Sem notificações (unread_count == 0)
        template = Template("{% load notification_tags %}{% render_notifications_bell %}")
        context = Context({'request': type('Req', (), {'user': self.produtor, 'resolver_match': type('RM', (), {'url_name': 'shows_list'})()})(), 'band': self.banda})
        output = template.render(context)
        
        # Não deve exibir badge nem botão de marcar todas
        self.assertNotIn('bg-danger', output)
        self.assertNotIn('fa-check-double', output)
        
        # Na central (paginada) também não
        self.client.force_login(self.produtor)
        url = reverse('notifications_list', kwargs={'band_slug': self.banda.slug})
        response = self.client.get(url)
        self.assertNotIn('Marcar todas', response.content.decode('utf-8'))
        
        # 2. Com notificação (unread_count > 0)
        n = create_notification(self.banda, self.produtor, 'NEW_SHOW', 'Notif Unread UI', 'msg', f'/{self.banda.slug}/', 'k_ui')[0]
        
        # Dropdown
        output2 = template.render(context)
        self.assertIn('bg-danger', output2)
        self.assertIn('fa-check-double', output2)
        
        # Central
        response2 = self.client.get(url)
        self.assertIn('Marcar todas', response2.content.decode('utf-8'))
        
        # 3. Após marcar todas
        url_mark = reverse('notifications_mark_all_read', kwargs={'band_slug': self.banda.slug})
        client_no_csrf = Client()
        client_no_csrf.force_login(self.produtor)
        client_no_csrf.post(url_mark)
        
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)
        
        # Dropdown
        output3 = template.render(context)
        self.assertNotIn('bg-danger', output3)
        self.assertNotIn('fa-check-double', output3)
        
        # Filtro não lidas vazio
        response_nao_lidas = self.client.get(url + '?filtro=nao_lidas')
        self.assertEqual(len(response_nao_lidas.context['page_obj']), 0)
        
        # Filtro todas contém
        response_todas = self.client.get(url + '?filtro=todas')
        self.assertEqual(len(response_todas.context['page_obj']), 1)
