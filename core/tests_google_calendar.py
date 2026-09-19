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

        # Produtor acessa a tela de configurações: teaser do Google Calendar aparece com selo "Em breve" e botão desabilitado
        self.client.login(username='produtor_alfa', password='123')
        url_config = reverse('configuracoes', kwargs={'band_slug': self.band.slug})
        resp_config = self.client.get(url_config)
        self.assertEqual(resp_config.status_code, 200)
        self.assertContains(resp_config, 'Google Calendar')
        self.assertContains(resp_config, 'Em breve')
        self.assertContains(resp_config, 'disabled')
        # Não exibe dados da conta conectada nem ações ativas
        self.assertNotContains(resp_config, 'banda.alfa@gmail.com')
        self.assertNotContains(resp_config, 'Agenda Shows Alfa')
        self.assertNotContains(resp_config, 'Desconectar')

    def test_teste_a_show_com_horario_inicio_e_final(self):
        """Teste A — Show com horário (24/10/2026, início 03:00, fim 05:00):
        evento de dia inteiro ancorado em 24/10/2026, horário exibido na descrição, sem dateTime, sem lembretes."""
        show = Show.objects.create(
            band=self.band,
            title='Festival da Madrugada',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 10, 24),
            show_time=datetime.time(3, 0),
            show_end_time=datetime.time(5, 0),
            venue='Palco Principal',
            city='Salvador/BA'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start'], {'date': '2026-10-24'})
        self.assertEqual(payload['end'], {'date': '2026-10-25'})
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertNotIn('timeZone', payload['start'])
        self.assertNotIn('timeZone', payload['end'])
        self.assertIn('Horário do Show: 03:00 às 05:00', payload['description'])
        self.assertNotIn('Duração:', payload['description'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

    def test_teste_b_somente_inicio(self):
        """Teste B — Show com somente início (27/09/2026, início 22:00):
        evento de dia inteiro em 27/09/2026, Horário do Show: 22:00 na descrição, sem dateTime."""
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
        self.assertEqual(payload['start'], {'date': '2026-09-27'})
        self.assertEqual(payload['end'], {'date': '2026-09-28'})
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertIn('Horário do Show: 22:00', payload['description'])
        self.assertNotIn('Duração:', payload['description'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

    def test_teste_c_reserva_com_horario(self):
        """Teste C — RESERVA com horário:
        evento de dia inteiro na data do show, prefixo RESERVA —, horário apenas na descrição."""
        show = Show.objects.create(
            band=self.band,
            title='Show Reservado',
            status=Show.STATUS_PRE_RESERVADO,
            date=datetime.date(2026, 10, 10),
            show_time=datetime.time(22, 0),
            duration='02:00'
        )
        payload = google_calendar.build_event_payload(show)
        self.assertTrue(payload['summary'].startswith('RESERVA —'))
        self.assertEqual(payload['start'], {'date': '2026-10-10'})
        self.assertEqual(payload['end'], {'date': '2026-10-11'})
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertIn('Status: Reserva', payload['description'])
        self.assertIn('Horário do Show: 22:00', payload['description'])
        self.assertIn('Duração: 02:00', payload['description'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

    def test_teste_d_sem_horario(self):
        """Teste D — Show sem horário:
        evento de dia inteiro, nenhuma linha de horário na descrição, sem lembretes."""
        show = Show.objects.create(
            band=self.band,
            title='Show Sem Horário',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 11, 20),
            show_time=None,
            show_end_time=None,
            duration=''
        )
        payload = google_calendar.build_event_payload(show)
        self.assertEqual(payload['start'], {'date': '2026-11-20'})
        self.assertEqual(payload['end'], {'date': '2026-11-21'})
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertNotIn('Horário do Show', payload['description'])
        self.assertNotIn('Duração', payload['description'])
        self.assertFalse(payload['reminders']['useDefault'])
        self.assertEqual(payload['reminders']['overrides'], [])

    @patch('core.services.google_calendar.requests.put')
    def test_teste_e_atualizacao_evento_remoto_antigo(self, mock_put):
        """Teste E — Atualização de evento remoto existente (substitui com PUT, preserva ID, converte para dia inteiro)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'id': 'google_evt_existing_777'}
        mock_put.return_value = mock_resp

        show = Show.objects.create(
            band=self.band,
            title='Show Antigo Com DateTime',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 9, 27),
            show_time=datetime.time(22, 0),
            google_calendar_event_id='google_evt_existing_777'
        )

        success = google_calendar.sync_show_to_google_calendar(show)
        self.assertTrue(success)
        self.assertTrue(mock_put.called)

        called_url, called_kwargs = mock_put.call_args
        self.assertIn('google_evt_existing_777', called_url[0])
        payload = called_kwargs.get('json')
        self.assertEqual(payload['start'], {'date': '2026-09-27'})
        self.assertEqual(payload['end'], {'date': '2026-09-28'})
        self.assertNotIn('dateTime', payload['start'])
        self.assertNotIn('dateTime', payload['end'])
        self.assertIn('Horário do Show: 22:00', payload['description'])
        self.assertEqual(payload['reminders']['overrides'], [])

        show.refresh_from_db()
        self.assertEqual(show.google_calendar_event_id, 'google_evt_existing_777')

    @patch('core.services.google_calendar.requests.put')
    @patch('core.services.google_calendar.requests.post')
    def test_teste_f_nao_duplicacao_apos_sincronizacao(self, mock_post, mock_put):
        """Teste F — Não duplicação: primeira sincronização faz POST e salva ID; segunda faz PUT usando o mesmo ID."""
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {'id': 'google_first_created_id'}
        mock_post.return_value = post_resp

        put_resp = MagicMock()
        put_resp.status_code = 200
        put_resp.json.return_value = {'id': 'google_first_created_id'}
        mock_put.return_value = put_resp

        show = Show.objects.create(
            band=self.band,
            title='Show Teste Duplicação',
            status=Show.STATUS_CONFIRMADO,
            date=datetime.date(2026, 10, 15),
            show_time=datetime.time(21, 0)
        )

        # 1ª Sincronização -> POST
        self.assertTrue(google_calendar.sync_show_to_google_calendar(show))
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(mock_put.call_count, 0)
        show.refresh_from_db()
        self.assertEqual(show.google_calendar_event_id, 'google_first_created_id')

        # 2ª Sincronização -> PUT no mesmo ID
        self.assertTrue(google_calendar.sync_show_to_google_calendar(show))
        self.assertEqual(mock_post.call_count, 1)  # não chamou post de novo
        self.assertEqual(mock_put.call_count, 1)  # chamou put
        called_url = mock_put.call_args[0][0]
        self.assertIn('google_first_created_id', called_url)
        show.refresh_from_db()
        self.assertEqual(show.google_calendar_event_id, 'google_first_created_id')

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

    @patch('core.services.google_calendar.requests.put')
    def test_edit_show_updates_same_google_event_id(self, mock_put):
        """5. Edição atualiza o mesmo evento remoto sem recriar ID."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'id': 'google_evt_xyz999'}
        mock_put.return_value = mock_resp

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

        # Validar que chamou put na URL com o event_id existente
        self.assertTrue(mock_put.called)
        called_url = mock_put.call_args[0][0]
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
