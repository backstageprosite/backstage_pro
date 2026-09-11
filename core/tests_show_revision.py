from django.test import TestCase
from django.urls import reverse
from core.models import Band, User, Show
from core.forms import ShowForm

class ShowNotificationRevisionTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        self.user = User.objects.create_user(
            username='produtor', 
            email='produtor@teste.com', 
            password='123',
            role='PRODUTOR',
            band=self.band
        )

    def test_show_new_has_revision_zero(self):
        """1. Show novo inicia com notification_revision igual a 0."""
        show = Show.objects.create(band=self.band, title='Show de Teste', status='CONFIRMADO')
        self.assertEqual(show.notification_revision, 0)
        
    def test_show_form_does_not_contain_revision(self):
        """3. O campo não aparece no ShowForm."""
        form = ShowForm()
        self.assertNotIn('notification_revision', form.fields)
        
    def test_show_revision_cannot_be_changed_via_post(self):
        """4. O campo não pode ser alterado pelo POST normal do formulário."""
        self.client.login(username='produtor', password='123')
        data = {
            'title': 'Show Malicioso',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'notification_revision': 999
        }
        url = reverse('shows_add', kwargs={'band_slug': self.band.slug})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # Redirect to calendar
        
        # Verify the show in db
        show = Show.objects.get(title='Show Malicioso')
        self.assertEqual(show.notification_revision, 0)

    def test_save_does_not_increment_automatically(self):
        """5. Salvar o Show normalmente não incrementa a revisão automaticamente (nesta etapa)."""
        show = Show.objects.create(band=self.band, title='Show Editável')
        self.assertEqual(show.notification_revision, 0)
        
        show.title = 'Show Editado'
        show.save()
        
        show.refresh_from_db()
        self.assertEqual(show.notification_revision, 0)

    def test_1_criacao_show_created_at_updated_at_existem(self):
        """1. Criar show: created_at e updated_at existem e são válidos."""
        show = Show.objects.create(band=self.band, title='Show Inaugural', status='CONFIRMADO')
        self.assertIsNotNone(show.created_at)
        self.assertIsNotNone(show.updated_at)
        self.assertAlmostEqual(show.created_at.timestamp(), show.updated_at.timestamp(), delta=2)

    def test_2_visualizar_show_detail_nao_altera_timestamps(self):
        """2. Visualizar modal da Agenda / show_detail (GET): created_at e updated_at NÃO mudam."""
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Visualizacao', status='CONFIRMADO')
        c1, u1 = show.created_at, show.updated_at

        url_detail = reverse('show_detail', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res = self.client.get(url_detail)
        self.assertEqual(res.status_code, 200)

        show.refresh_from_db()
        self.assertEqual(show.created_at, c1)
        self.assertEqual(show.updated_at, u1)

    def test_3_abrir_editar_show_get_nao_altera_updated_at(self):
        """3. Abrir página "Editar Show" (GET): updated_at NÃO muda."""
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Edit GET', status='CONFIRMADO')
        c1, u1 = show.created_at, show.updated_at

        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res = self.client.get(url_edit)
        self.assertEqual(res.status_code, 200)

        show.refresh_from_db()
        self.assertEqual(show.created_at, c1)
        self.assertEqual(show.updated_at, u1)

    def test_4_salvar_com_alteracao_real_atualiza_updated_at_preserva_created_at(self):
        """4. Salvar alteração real no formulário (POST com mudança de dado): created_at não muda, updated_at avança."""
        import time
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Titulo Antigo', status='CONFIRMADO')
        c1, u1 = show.created_at, show.updated_at

        time.sleep(0.05)
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        post_data = {
            'title': 'Show Titulo Novo Realmente Modificado',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        res = self.client.post(url_edit, post_data)
        self.assertEqual(res.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.created_at, c1)
        self.assertGreater(show.updated_at, u1)
        self.assertEqual(show.title, 'Show Titulo Novo Realmente Modificado')

    def test_5_submeter_formulario_sem_alteracoes_preserva_updated_at(self):
        """5. Submeter formulário de edição sem alterações (POST idêntico): updated_at NÃO muda."""
        import time
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Sem Mudanca', status='CONFIRMADO')
        c1, u1 = show.created_at, show.updated_at

        time.sleep(0.05)
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        post_data = {
            'title': 'Show Sem Mudanca',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
        }
        res = self.client.post(url_edit, post_data)
        self.assertEqual(res.status_code, 302)

        show.refresh_from_db()
        self.assertEqual(show.created_at, c1)
        self.assertEqual(show.updated_at, u1)

    def test_6_timestamps_aparecem_no_modal_agenda_e_form_edicao(self):
        """6. Timestamps aparecem no modal da Agenda e no formulário de edição."""
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Display Check', status='CONFIRMADO')

        # Modal da Agenda (calendario.html)
        url_cal = reverse('calendario', kwargs={'band_slug': self.band.slug})
        res_cal = self.client.get(url_cal)
        self.assertEqual(res_cal.status_code, 200)
        self.assertContains(res_cal, 'modalShowCreatedAt')
        self.assertContains(res_cal, 'modalShowUpdatedAt')
        self.assertContains(res_cal, 'Data de criação:')
        self.assertContains(res_cal, 'Última atualização:')

        # Formulário de Edição (show_form.html)
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res_edit = self.client.get(url_edit)
        self.assertEqual(res_edit.status_code, 200)
        self.assertContains(res_edit, 'Data de criação:')
        self.assertContains(res_edit, 'Última atualização:')

    def test_7_formato_exibicao_dd_mm_aaaa_hh_mm(self):
        """7. Formato de exibição segue DD/MM/AAAA HH:mm."""
        from django.utils import timezone
        self.client.login(username='produtor', password='123')
        show = Show.objects.create(band=self.band, title='Show Formato Check', status='CONFIRMADO')
        
        # Obter data/hora no timezone ativo formatada como DD/MM/AAAA HH:mm
        local_created = timezone.localtime(show.created_at)
        formatted_expected = local_created.strftime('%d/%m/%Y %H:%M')

        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res_edit = self.client.get(url_edit)
        self.assertEqual(res_edit.status_code, 200)
        self.assertContains(res_edit, formatted_expected)

    def test_8_timezone_respeitado_america_sao_paulo(self):
        """8. Timezone respeitado (America/Sao_Paulo)."""
        import datetime
        from django.utils import timezone
        import zoneinfo

        sp_tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
        dt_utc = datetime.datetime(2026, 9, 11, 23, 30, tzinfo=datetime.timezone.utc)
        dt_sp = dt_utc.astimezone(sp_tz)

        # Em 2026-09-11 23:30 UTC, em São Paulo é 20:30 do mesmo dia
        self.assertEqual(dt_sp.hour, 20)
        self.assertEqual(dt_sp.minute, 30)

        show = Show.objects.create(band=self.band, title='Show TZ Check', status='CONFIRMADO')
        show.created_at = dt_utc
        show.updated_at = dt_utc
        show.save(update_fields=['created_at', 'updated_at'])

        self.client.login(username='produtor', password='123')
        url_edit = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        res_edit = self.client.get(url_edit)
        self.assertEqual(res_edit.status_code, 200)
        # Deve exibir com o horário de São Paulo (20:30) e não UTC (23:30)
        self.assertContains(res_edit, '11/09/2026 20:30')

