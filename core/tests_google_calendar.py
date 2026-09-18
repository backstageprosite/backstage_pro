import datetime
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import Band, User, Show, GoogleCalendarIntegration
from core.services import google_calendar
from core.services.google_calendar_crypto import encrypt_token, decrypt_token


class GoogleCalendarTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(name='Banda Alfa', slug='banda-alfa')
        self.other_band = Band.objects.create(name='Banda Beta', slug='banda-beta')

        self.produtor = User.objects.create_user(
            username='produtor_alfa', email='produtor@alfa.com', password='123',
            role='PRODUTOR', band=self.band
        )
        self.integrante = User.objects.create_user(
            username='integrante_alfa', email='integrante@alfa.com', password='123',
            role='INTEGRANTE', band=self.band
        )
        self.produtor_beta = User.objects.create_user(
            username='produtor_beta', email='produtor@beta.com', password='123',
            role='PRODUTOR', band=self.other_band
        )

        # Integração ativa para Banda Alfa
        self.integration = GoogleCalendarIntegration.objects.create(
            band=self.band,
            google_account_email='banda.alfa@gmail.com',
            calendar_id='alfa_calendar_id@group.calendar.google.com',
            calendar_name='Agenda Shows Alfa',
            status=GoogleCalendarIntegration.Status.CONNECTED,
            token_expires_at=timezone.now() + datetime.timedelta(hours=1)
        )
        self.integration.set_access_token('fake_access_token_123')
        self.integration.set_refresh_token('fake_refresh_token_456')
        self.integration.save()

    def test_token_encryption_and_decryption(self):
        """Tokens são salvos cifrados e descriptografados corretamente em memória."""
        raw_token = 'meu_token_secreto_98765'
        cipher = encrypt_token(raw_token)
        self.assertNotEqual(raw_token, cipher)
        decrypted = decrypt_token(cipher)
        self.assertEqual(raw_token, decrypted)

        # No model
        self.assertNotIn('fake_refresh_token_456', self.integration.encrypted_refresh_token)
        self.assertEqual(self.integration.get_refresh_token(), 'fake_refresh_token_456')

    def test_permissions_produtor_vs_integrante(self):
        """1 & 2. Produtor acessa e gerencia integração; integrante comum é bloqueado (403)."""
        # Integrante tentando conectar
        self.client.login(username='integrante_alfa', password='123')
        url_connect = reverse('google_calendar_connect', kwargs={'band_slug': self.band.slug})
        resp_connect_int = self.client.get(url_connect)
        self.assertEqual(resp_connect_int.status_code, 403)

        # Integrante tentando desconectar
        url_disc = reverse('google_calendar_disconnect', kwargs={'band_slug': self.band.slug})
        resp_disc_int = self.client.post(url_disc)
        self.assertEqual(resp_disc_int.status_code, 403)

        # Integrante tentando sincronizar
        url_sync = reverse('google_calendar_sync_now', kwargs={'band_slug': self.band.slug})
        resp_sync_int = self.client.post(url_sync)
        self.assertEqual(resp_sync_int.status_code, 403)

        # Produtor da própria banda consegue acessar tela de configuração
        self.client.login(username='produtor_alfa', password='123')
        url_config = reverse('configuracoes', kwargs={'band_slug': self.band.slug})
        resp_config = self.client.get(url_config)
        self.assertEqual(resp_config.status_code, 200)
        self.assertContains(resp_config, 'Google Calendar')
        self.assertContains(resp_config, 'banda.alfa@gmail.com')

    def test_confirmado_payload_format(self):
        """Show CONFIRMADO com início + duração calcula término corretamente e define lembrete popup de 60 min."""
        show = Show.objects.create(
            band=self.band,
            title='Festival de Verão',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 11, 20),
            show_time=datetime.time(22, 0),
            venue='Arena Fonte Nova',
            city='Salvador/BA',
            duration='2 horas'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['summary'], 'Banda Alfa — Festival de Verão')
        self.assertIn('Status: Confirmado', payload['description'])
        self.assertIn('Cidade: Salvador/BA', payload['description'])
        self.assertIn('Local: Arena Fonte Nova', payload['description'])
        self.assertNotIn('R$', payload['description'])  # Não exibe financeiro
        self.assertEqual(payload['start']['dateTime'], '2026-11-20T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-11-21T00:00:00')  # 22h + 2 horas
        # Lembrete
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_show_confirmado_com_horario_inicio_e_final(self):
        """Confirmado com horário: 20/09/2026 22:00 às 23:30 -> start.dateTime, end.dateTime, popup 60m."""
        show = Show.objects.create(
            band=self.band,
            title='Show de Primavera',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(22, 0),
            show_end_time=datetime.time(23, 30),
            venue='Arena Show',
            city='São Paulo/SP'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-20T23:30:00')
        self.assertNotIn('date', payload['start'])
        self.assertNotIn('date', payload['end'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_show_reserva_com_horario_inicio_e_final(self):
        """Reserva com horário: 10/10/2026 21:00 às 22:30 -> prefixo RESERVA, start.dateTime, end.dateTime, popup 60m."""
        show = Show.objects.create(
            band=self.band,
            title='Show Corporativo',
            status=Show.STATUS_PRE_RESERVADO,
            date=datetime.date(2026, 10, 10),
            show_time=datetime.time(21, 0),
            show_end_time=datetime.time(22, 30),
            venue='Centro de Convenções',
            city='Rio de Janeiro/RJ'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertTrue(payload['summary'].startswith('RESERVA —'))
        self.assertEqual(payload['start']['dateTime'], '2026-10-10T21:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-10-10T22:30:00')
        self.assertNotIn('date', payload['start'])
        self.assertNotIn('date', payload['end'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_show_virada_de_dia(self):
        """Virada de dia: Início 22:00 e Final 00:30 -> Início 20/09 e Fim 21/09."""
        show = Show.objects.create(
            band=self.band,
            title='Baile da Madrugada',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(22, 0),
            show_end_time=datetime.time(0, 30),
            venue='Clube Central',
            city='Belo Horizonte/MG'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-21T00:30:00')

    def test_show_com_duracao_hh_mm(self):
        """Duração em formato HH:MM (ex: 01:30) calcula término corretamente."""
        show = Show.objects.create(
            band=self.band,
            title='Show Acústico',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(20, 0),
            duration='01:30',
            venue='Teatro Municipal',
            city='Campinas/SP'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T20:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-20T21:30:00')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_show_dia_inteiro_sem_horario_suficiente(self):
        """Dia inteiro: Show sem horário suficiente -> start.date, end.date, useDefault=false, sem overrides."""
        # Caso 1: Show sem horários
        show_sem_horario = Show.objects.create(
            band=self.band,
            title='Show Sem Horários',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 11, 20),
            venue='Praça',
            city='Salvador/BA'
        )
        payload = google_calendar.build_event_payload(show_sem_horario)
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertEqual(payload['start']['date'], '2026-11-20')
        self.assertEqual(payload['end']['date'], '2026-11-21')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

        # Caso 2: Show com início mas sem término nem duração válida
        show_so_inicio = Show.objects.create(
            band=self.band,
            title='Show Só Com Início',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 11, 20),
            show_time=datetime.time(21, 0),
            show_end_time=None,
            duration='',
            venue='Praça',
            city='Salvador/BA'
        )
        payload2 = google_calendar.build_event_payload(show_so_inicio)
        self.assertNotIn('dateTime', payload2['start'])
        self.assertNotIn('dateTime', payload2['end'])
        self.assertEqual(payload2['start']['date'], '2026-11-20')
        self.assertEqual(payload2['end']['date'], '2026-11-21')
        self.assertFalse(payload2['reminders']['useDefault'])
        self.assertEqual(payload2['reminders']['overrides'], [])

    def test_google_scopes_least_privilege(self):
        """Regra 2: Verifica que os escopos utilizam calendarlist.readonly em vez de calendar.readonly."""
        self.assertIn('https://www.googleapis.com/auth/calendar.calendarlist.readonly', google_calendar.GOOGLE_SCOPES)
        self.assertNotIn('https://www.googleapis.com/auth/calendar.readonly', google_calendar.GOOGLE_SCOPES)
        self.assertIn('https://www.googleapis.com/auth/calendar.events', google_calendar.GOOGLE_SCOPES)
        self.assertIn('https://www.googleapis.com/auth/userinfo.email', google_calendar.GOOGLE_SCOPES)


    @patch('core.services.google_calendar.requests.post')
    def test_create_show_syncs_and_saves_google_event_id(self, mock_post):
        """5. Criação de show salva e atualiza o mesmo google_calendar_event_id."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'id': 'google_evt_xyz999'}
        mock_post.return_value = mock_resp

        show = Show.objects.create(
            band=self.band,
            title='Show Inauguração',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 10, 15)
        )
        success = google_calendar.sync_show_to_google_calendar(show)
        self.assertTrue(success)

        show.refresh_from_db()
        self.assertEqual(show.google_calendar_event_id, 'google_evt_xyz999')

    @patch('core.services.google_calendar.requests.patch')
    def test_edit_show_updates_same_google_event_id(self, mock_patch):
        """5. Edição atualiza o mesmo evento remoto sem recriar ID."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'id': 'google_evt_xyz999'}
        mock_patch.return_value = mock_resp

        show = Show.objects.create(
            band=self.band,
            title='Show Inauguração',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 10, 15),
            google_calendar_event_id='google_evt_xyz999'
        )
        show.title = 'Show Inauguração - Nome Alterado'
        show.save()

        success = google_calendar.sync_show_to_google_calendar(show)
        self.assertTrue(success)

        # Validar que chamou patch na URL com o event_id existente
        self.assertTrue(mock_patch.called)
        called_url = mock_patch.call_args[0][0]
        self.assertIn('google_evt_xyz999', called_url)

    @patch('core.services.google_calendar.requests.delete')
    def test_cancelado_removes_remote_event_and_clears_id(self, mock_delete):
        """6 & 7. Show CANCELADO / DESISTÊNCIA remove o evento remoto e limpa a referência."""
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_delete.return_value = mock_resp

        show = Show.objects.create(
            band=self.band,
            title='Show a Cancelar',
            status=Show.STATUS_CANCELADO,
            date=datetime.date(2026, 10, 20),
            google_calendar_event_id='google_evt_to_delete_111'
        )
        success = google_calendar.sync_show_to_google_calendar(show)
        self.assertTrue(success)

        show.refresh_from_db()
        self.assertIsNone(show.google_calendar_event_id)
        self.assertTrue(mock_delete.called)

    def test_band_isolation(self):
        """8. Isolamento estrito entre bandas: Produtor da Banda Beta não acessa integração da Banda Alfa."""
        self.client.login(username='produtor_beta', password='123')
        url_alfa = reverse('google_calendar_sync_now', kwargs={'band_slug': self.band.slug})
        resp = self.client.post(url_alfa)
        # band_required bloqueia com 403 por não pertencer à Banda Alfa
        self.assertEqual(resp.status_code, 403)
