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

    def test_teste_a_somente_inicio(self):
        """Teste A — somente início: 27/09/2026 22:00 -> 22:00 às 00:00 do dia seguinte (2h padrão, não dia inteiro)."""
        show = Show.objects.create(
            band=self.band,
            title='Show Somente Início',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 27),
            show_time=datetime.time(22, 0),
            show_end_time=None,
            duration=''
        )
        payload = google_calendar.build_event_payload(show)
        self.assertNotIn('date', payload['start'])
        self.assertEqual(payload['start']['dateTime'], '2026-09-27T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-28T00:00:00')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_teste_b_inicio_e_final(self):
        """Teste B — início + final: 20/09/2026 18:00 às 19:30 -> 18:00 às 19:30."""
        show = Show.objects.create(
            band=self.band,
            title='Show Início e Final',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(18, 0),
            show_end_time=datetime.time(19, 30)
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T18:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-20T19:30:00')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_teste_c_inicio_e_duracao(self):
        """Teste C — início + duração: 20:00 + 01:30 -> 20:00 às 21:30."""
        show = Show.objects.create(
            band=self.band,
            title='Show Acústico',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(20, 0),
            duration='01:30'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T20:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-20T21:30:00')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_teste_d_virada_de_dia(self):
        """Teste D — virada de dia: Início 22:00 e Final 00:30 -> Início 20/09 e Fim 21/09."""
        show = Show.objects.create(
            band=self.band,
            title='Baile da Madrugada',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 20),
            show_time=datetime.time(22, 0),
            show_end_time=datetime.time(0, 30)
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start']['dateTime'], '2026-09-20T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-09-21T00:30:00')

    def test_teste_e_reserva_somente_com_inicio(self):
        """Teste E — RESERVA somente com início: PRE_RESERVADO 22:00 -> prefixo RESERVA, 2h padrão, popup 60m."""
        show = Show.objects.create(
            band=self.band,
            title='Show Reserva Teste',
            status=Show.STATUS_PRE_RESERVADO,
            date=datetime.date(2026, 10, 10),
            show_time=datetime.time(22, 0),
            show_end_time=None,
            duration=''
        )
        payload = google_calendar.build_event_payload(show)
        self.assertTrue(payload['summary'].startswith('RESERVA —'))
        self.assertEqual(payload['start']['dateTime'], '2026-10-10T22:00:00')
        self.assertEqual(payload['end']['dateTime'], '2026-10-11T00:00:00')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])

    def test_teste_f_sem_inicio_dia_inteiro(self):
        """Teste F — sem início: evento de dia inteiro, sem lembrete."""
        show = Show.objects.create(
            band=self.band,
            title='Show Data Confirmada Sem Horário',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 11, 20),
            show_time=None,
            show_end_time=None,
            duration=''
        )
        payload = google_calendar.build_event_payload(show)
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertEqual(payload['start']['date'], '2026-11-20')
        self.assertEqual(payload['end']['date'], '2026-11-21')
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

    @patch('core.services.google_calendar.requests.patch')
    def test_teste_g_conversao_dia_inteiro_para_horario(self, mock_patch):
        """Teste G — conversão dia inteiro -> horário: mesmo event ID, passa para horário 22h-00h sem duplicar."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'id': 'google_evt_conv_123'}
        mock_patch.return_value = mock_resp

        # Show antes como dia inteiro
        show = Show.objects.create(
            band=self.band,
            title='Show Itanagra',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 27),
            show_time=None,
            google_calendar_event_id='google_evt_conv_123'
        )

        # Atualiza para Show Início 22:00
        show.show_time = datetime.time(22, 0)
        show.save()

        success = google_calendar.sync_show_to_google_calendar(show)
        self.assertTrue(success)
        self.assertTrue(mock_patch.called)

        called_url, called_kwargs = mock_patch.call_args
        self.assertIn('google_evt_conv_123', called_url[0])
        sent_payload = called_kwargs.get('json')
        self.assertEqual(sent_payload['start']['dateTime'], '2026-09-27T22:00:00')
        self.assertEqual(sent_payload['end']['dateTime'], '2026-09-28T00:00:00')
        self.assertNotIn('date', sent_payload['start'])
        self.assertNotIn('date', sent_payload['end'])
        self.assertEqual(sent_payload['reminders']['overrides'], [{'method': 'popup', 'minutes': 60}])
        # Mantém mesmo event_id
        show.refresh_from_db()
        self.assertEqual(show.google_calendar_event_id, 'google_evt_conv_123')

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

    @patch('core.services.google_calendar.requests.post')
    def test_sync_band_calendar_handles_http_400_and_logs_diagnostics(self, mock_post):
        """Simula resposta Google HTTP 400: contabiliza erro, continua o lote e preenche last_error_message sem vazar tokens."""
        # 2 shows: 1 vai falhar com 400 e o outro vai ter sucesso 200
        show_erro = Show.objects.create(
            band=self.band,
            title='Show Com Erro',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 27),
            show_time=datetime.time(22, 0)
        )
        show_ok = Show.objects.create(
            band=self.band,
            title='Show Bem Sucedido',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 28),
            show_time=datetime.time(20, 0)
        )

        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = '{"error": {"code": 400, "message": "Invalid conference data", "errors": [{"reason": "invalid"}]}}'
        resp_400.json.return_value = {
            "error": {
                "code": 400,
                "message": "Invalid conference data",
                "errors": [{"reason": "invalid"}]
            }
        }

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"id": "google_ok_777"}

        mock_post.side_effect = [resp_400, resp_200]

        with self.assertLogs('core.services.google_calendar', level='ERROR') as cm:
            stats = google_calendar.sync_band_calendar(self.band)

        # 1. Confirma contagem de erro e criação
        self.assertEqual(stats['errors'], 1)
        self.assertEqual(stats['created'], 1)

        # 2. Confirma que o lote continuou e salvou o show_ok
        show_ok.refresh_from_db()
        self.assertEqual(show_ok.google_calendar_event_id, 'google_ok_777')

        # 3. Confirma preenchimento sanitizado de last_error_message
        self.integration.refresh_from_db()
        self.assertIn(f"Show {show_erro.id}", self.integration.last_error_message)
        self.assertIn("HTTP 400", self.integration.last_error_message)
        self.assertIn("Invalid conference data", self.integration.last_error_message)

        # 4. Confirma que tokens e segredos não vazam nem no log nem no last_error_message
        access_token = self.integration.get_access_token()
        refresh_token = self.integration.get_refresh_token()
        self.assertNotIn(access_token, self.integration.last_error_message)
        self.assertNotIn(refresh_token, self.integration.last_error_message)

        log_output = "\n".join(cm.output)
        self.assertIn("Google Calendar sync failed", log_output)
        self.assertIn(f"show_id={show_erro.id}", log_output)
        self.assertIn("status=400", log_output)
        self.assertNotIn(access_token, log_output)
        self.assertNotIn(refresh_token, log_output)
