import os
import re
import urllib.parse
import logging
from datetime import datetime, timedelta, time
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Escopos mínimos necessários para o Google Calendar (apenas leitura e edição de eventos do calendário)
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]


def get_oauth_config(request=None):
    """
    Retorna as credenciais configuradas para OAuth do Google.
    """
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or os.getenv('GOOGLE_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '') or os.getenv('GOOGLE_CLIENT_SECRET', '')
    redirect_uri = getattr(settings, 'GOOGLE_OAUTH_REDIRECT_URI', '') or os.getenv('GOOGLE_OAUTH_REDIRECT_URI', '')
    
    if not redirect_uri and request:
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(reverse('google_calendar_oauth_callback'))
        
    return client_id.strip(), client_secret.strip(), redirect_uri.strip()


def build_authorization_url(state: str, request=None) -> str:
    """
    Monta a URL de autorização OAuth 2.0 do Google.
    """
    client_id, _, redirect_uri = get_oauth_config(request)
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID não está configurado.")
    if not redirect_uri:
        raise ValueError("GOOGLE_OAUTH_REDIRECT_URI não está configurado.")

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(GOOGLE_SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
        'include_granted_scopes': 'true',
    }
    return f"{GOOGLE_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, request=None) -> dict:
    """
    Troca o authorization code pelo access token e refresh token.
    """
    client_id, client_secret, redirect_uri = get_oauth_config(request)
    if not client_id or not client_secret:
        raise ValueError("Credenciais Google OAuth (Client ID ou Client Secret) não configuradas.")

    data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }
    response = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=data, timeout=15)
    response_data = response.json()
    if response.status_code != 200:
        error_desc = response_data.get('error_description') or response_data.get('error') or response.text
        logger.error(f"Erro na troca de authorization code do Google: {error_desc}")
        raise ValueError(f"Falha ao conectar ao Google: {error_desc}")

    return response_data


def refresh_access_token_if_needed(integration) -> str:
    """
    Verifica a validade do access token atual e, se estiver expirando ou expirado,
    utiliza o refresh token para obter um novo access token.
    """
    access_token = integration.get_access_token()
    now = timezone.now()

    # Se ainda for válido por pelo menos 2 minutos, reutiliza
    if access_token and integration.token_expires_at and integration.token_expires_at > (now + timedelta(minutes=2)):
        return access_token

    refresh_tok = integration.get_refresh_token()
    if not refresh_tok:
        integration.status = integration.Status.ERROR
        integration.last_error_message = "Token de atualização (refresh token) ausente ou revogado."
        integration.save(update_fields=['status', 'last_error_message', 'updated_at'])
        raise ValueError("Integração sem refresh token. É necessário reconectar ao Google Calendar.")

    client_id, client_secret, _ = get_oauth_config()
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_tok,
        'grant_type': 'refresh_token',
    }
    response = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=data, timeout=15)
    res_data = response.json()

    if response.status_code != 200:
        error_desc = res_data.get('error_description') or res_data.get('error') or response.text
        logger.error(f"Erro ao renovar token Google da banda {integration.band_id}: {error_desc}")
        integration.status = integration.Status.ERROR
        integration.last_error_message = f"Falha na renovação do token Google: {error_desc}"
        integration.save(update_fields=['status', 'last_error_message', 'updated_at'])
        raise ValueError(f"Não foi possível renovar as credenciais do Google Calendar: {error_desc}")

    new_access_token = res_data.get('access_token')
    expires_in = res_data.get('expires_in', 3600)
    integration.set_access_token(new_access_token)
    integration.token_expires_at = now + timedelta(seconds=int(expires_in))
    integration.status = integration.Status.CONNECTED
    integration.last_error_message = ""
    integration.save(update_fields=['encrypted_access_token', 'token_expires_at', 'status', 'last_error_message', 'updated_at'])

    return new_access_token


def fetch_google_user_email(access_token: str) -> str:
    """
    Obtém o email da conta Google conectada.
    """
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        resp = requests.get(GOOGLE_USERINFO_URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('email', '')
    except Exception as e:
        logger.warning(f"Erro ao obter userinfo do Google: {e}")
    return ''


def list_user_calendars(integration) -> list:
    """
    Lista os calendários disponíveis na conta Google com permissão de escrita/edição de eventos.
    """
    access_token = refresh_access_token_if_needed(integration)
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f"{GOOGLE_CALENDAR_API_BASE}/users/me/calendarList"

    calendars = []
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            for item in items:
                # Filtrar apenas calendários onde o usuário possui permissão de escrita
                access_role = item.get('accessRole', '')
                if access_role in ['owner', 'writer']:
                    calendars.append({
                        'id': item.get('id'),
                        'summary': item.get('summary', 'Sem nome'),
                        'primary': item.get('primary', False),
                        'description': item.get('description', ''),
                    })
        else:
            logger.error(f"Erro ao listar calendários do Google: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Falha na requisição list_user_calendars: {e}")
        raise ValueError(f"Não foi possível listar os calendários: {e}")

    return calendars


def revoke_google_token(integration):
    """
    Revoga o refresh/access token no Google e limpa credenciais locais.
    """
    token = integration.get_refresh_token() or integration.get_access_token()
    if token:
        try:
            requests.post(GOOGLE_OAUTH_REVOKE_URL, params={'token': token}, timeout=10)
        except Exception as e:
            logger.warning(f"Erro ao revogar token no Google: {e}")

    integration.encrypted_access_token = None
    integration.encrypted_refresh_token = None
    integration.token_expires_at = None
    integration.status = integration.Status.DISCONNECTED
    integration.last_error_message = ""
    integration.save()


# ==============================================================================
# REGRAS DE MONTAGEM DE EVENTOS DO SHOW
# ==============================================================================

def parse_duration_to_minutes(duration_str: str) -> int:
    """
    Converte strings de duração comuns (ex: '01:30', '02:00', '2 horas', '1h30', '90 min') em minutos.
    Retorna 0 se não for possível interpretar com precisão.
    """
    if not duration_str:
        return 0
    s = str(duration_str).strip().lower()

    # Formato HH:MM ou H:MM (ex: '01:30', '1:30', '02:00', '2:00')
    time_match = re.match(r'^(\d{1,2}):(\d{2})$', s)
    if time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        return hours * 60 + minutes

    # Formato: 1h30, 1h30m, 2h, 1h 30m, 2 horas, 1 hora e 30 minutos
    h_match = re.search(r'(\d+)\s*h(?:oras?)?(?:\s*(?:e\s*)?(\d+)\s*(?:m(?:in(?:utos?)?)?)?)?', s)
    if h_match:
        hours = int(h_match.group(1))
        minutes = int(h_match.group(2)) if h_match.group(2) else 0
        return hours * 60 + minutes

    # Formato: 90 min, 120 minutos, 90m
    m_match = re.search(r'(\d+)\s*m(?:in(?:utos?)?)?', s)
    if m_match:
        return int(m_match.group(1))

    # Formato numérico simples (assumindo horas se <= 8, minutos se > 8)
    if s.isdigit():
        val = int(s)
        return val * 60 if val <= 8 else val

    return 0


def build_event_payload(show, request=None) -> dict:
    """
    Monta o payload JSON do evento para a API do Google Calendar segundo a regra definitiva da BP-PEND-48:
    - TODO show vira evento de DIA INTEIRO no Google Calendar;
    - data do evento é SEMPRE Show.date (data oficial/operacional do show);
    - início: {'date': 'YYYY-MM-DD'};
    - fim: {'date': 'YYYY-MM-DD' + 1 dia} (exigência do Google para dia inteiro);
    - NUNCA enviar start.dateTime, end.dateTime ou timeZone;
    - horários reais do show (e duração, se aplicável) são exibidos EXCLUSIVAMENTE na Descrição;
    - sem lembretes: useDefault=False, overrides=[];
    - CONFIRMADO: [Nome da Banda] — [Nome do Show]
    - RESERVA: RESERVA — [Nome da Banda] — [Nome do Show]
    - Local: [Local do Show] — [Endereço Completo] — [Cidade] (omitindo partes vazias).
    """
    band = show.band
    band_name = band.name if band else ''
    show_name = (show.title or show.event_name or 'Show').strip()

    # Título do evento
    if band_name and band_name.lower() not in show_name.lower():
        base_title = f"{band_name} — {show_name}"
    else:
        base_title = show_name

    if show.status == show.STATUS_PRE_RESERVADO:
        summary = f"RESERVA — {base_title}"
        status_label = "Reserva"
    else:
        summary = base_title
        status_label = "Confirmado"

    # Localização
    loc_parts = []
    if show.venue:
        loc_parts.append(show.venue.strip())
    if show.address:
        loc_parts.append(show.address.strip())
    if show.city:
        loc_parts.append(show.city.strip())
    location = " — ".join(loc_parts)

    # Descrição (não expõe valores financeiros, cachê ou dados confidenciais)
    desc_lines = [
        f"Status: {status_label}",
    ]

    # Regras de exibição de horário na descrição:
    # Caso A: início + final -> Horário do Show: HH:MM às HH:MM
    # Caso B: somente início (sem final nem duração) -> Horário do Show: HH:MM
    # Caso C: início + duração -> Horário do Show: HH:MM \n Duração: <duração>
    # Caso D: sem horário -> nenhuma linha de horário
    if show.show_time and show.show_end_time:
        desc_lines.append(f"Horário do Show: {show.show_time.strftime('%H:%M')} às {show.show_end_time.strftime('%H:%M')}")
    elif show.show_time:
        desc_lines.append(f"Horário do Show: {show.show_time.strftime('%H:%M')}")
        if show.duration:
            desc_lines.append(f"Duração: {show.duration.strip()}")
    elif show.duration:
        desc_lines.append(f"Duração: {show.duration.strip()}")

    if show.city:
        desc_lines.append(f"Cidade: {show.city.strip()}")
    if show.venue:
        desc_lines.append(f"Local: {show.venue.strip()}")
    if show.address:
        desc_lines.append(f"Endereço: {show.address.strip()}")
    if show.address_link:
        desc_lines.append(f"Localização (Maps): {show.address_link.strip()}")

    # Link direto para o show autenticado
    if band:
        show_url = f"https://backstagepro.site/{band.slug}/show/{show.id}/"
        if request:
            try:
                from django.urls import reverse
                show_url = request.build_absolute_uri(reverse('show_detail', kwargs={'band_slug': band.slug, 'pk': show.id}))
            except Exception:
                pass
        desc_lines.append(f"Backstage Pro: {show_url}")

    description = "\n".join(desc_lines)

    # Evento de DIA INTEIRO sempre ancorado em Show.date
    show_date = show.date or timezone.localdate()
    start_date_str = show_date.strftime('%Y-%m-%d')
    end_date_str = (show_date + timedelta(days=1)).strftime('%Y-%m-%d')

    start_payload = {'date': start_date_str}
    end_payload = {'date': end_date_str}

    # Desativa lembretes para eventos de dia inteiro conforme especificação
    reminders_payload = {
        'useDefault': False,
        'overrides': []
    }

    payload = {
        'summary': summary,
        'description': description,
        'start': start_payload,
        'end': end_payload,
        'reminders': reminders_payload,
    }
    if location:
        payload['location'] = location

    return payload


def _parse_and_log_google_error(band, show, operation: str, event_id: str, resp=None, exc=None) -> str:
    """
    Registra com logger.error uma falha de sincronização com o Google Calendar em formato estruturado.
    Garante que NENHUM dado sensível (tokens, segredos, headers de autorização) seja logado.
    Retorna uma mensagem de erro sanitizada e resumida para exibição em last_error_message.
    """
    band_id = band.id if band else None
    band_name = band.name if band else 'N/A'
    show_id = show.id if show else None
    show_title = (show.title or show.event_name or 'Sem título') if show else 'N/A'
    show_status = show.status if show else 'N/A'
    evt_id_str = event_id or 'N/A'

    status_code = getattr(resp, 'status_code', None) if resp else 'N/A'
    reason = ''
    message = ''
    raw_body = ''
    if resp is not None:
        try:
            raw_body = getattr(resp, 'text', '') or ''
            data = resp.json()
            err = data.get('error', {})
            message = err.get('message', '')
            errors_list = err.get('errors', [])
            if errors_list and isinstance(errors_list, list) and isinstance(errors_list[0], dict):
                reason = errors_list[0].get('reason', '')
        except Exception:
            pass

    sanitized_body = raw_body[:300].replace('\n', ' ').strip()
    error_detail = message or reason or sanitized_body or (str(exc) if exc else f"HTTP {status_code}")

    # Log estruturado e seguro
    logger.error(
        f"Google Calendar sync failed | band_id={band_id} | band_name={band_name} | "
        f"show_id={show_id} | show_title={show_title} | show_status={show_status} | "
        f"operation={operation} | event_id={evt_id_str} | status={status_code} | "
        f"reason={reason or 'N/A'} | detail={error_detail}"
    )

    # Mensagem sanitizada para last_error_message
    if status_code != 'N/A':
        return f"Show {show_id} ({show_title}): HTTP {status_code} - {error_detail[:120]}"
    elif exc:
        return f"Show {show_id} ({show_title}): {str(exc)[:120]}"
    else:
        return f"Show {show_id} ({show_title}): Falha na operação {operation}"


# ==============================================================================
# SINCRONIZAÇÃO DE SHOWS COM O GOOGLE CALENDAR
# ==============================================================================

def sync_show_to_google_calendar(show, request=None) -> bool:
    """
    Sincroniza um único show com o Google Calendar da banda correspondente.
    Trata regras de CONFIRMADO, RESERVA, CANCELADO e DESISTÊNCIA.
    Atualiza eventos existentes usando PUT (events.update) para substituição completa e segura.
    Falhas na API do Google NUNCA quebram a execução local nem o salvamento do Show.
    """
    if not show or not show.band_id:
        return False

    try:
        from core.models import GoogleCalendarIntegration
        integration = GoogleCalendarIntegration.objects.filter(band=show.band).first()
        if not integration or not integration.is_connected:
            return False

        calendar_id = integration.calendar_id or 'primary'
        access_token = refresh_access_token_if_needed(integration)
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        # Regra para CANCELADO / DESISTÊNCIA:
        # Se estiver CANCELADO ou a proposta for DESISTÊNCIA, remove do Google Calendar se tiver event_id
        is_cancelled = (show.status == show.STATUS_CANCELADO)

        if is_cancelled:
            if show.google_calendar_event_id:
                event_id = show.google_calendar_event_id
                url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
                resp = requests.delete(url, headers=headers, timeout=15)
                # 204 No Content ou 410/404 (já removido) são considerados sucesso
                if resp.status_code in [200, 204, 404, 410]:
                    show.google_calendar_event_id = None
                    show.save(update_fields=['google_calendar_event_id'])
                    return True
                else:
                    _parse_and_log_google_error(show.band, show, 'DELETE', event_id, resp=resp)
            return True

        # Regra para CONFIRMADO e RESERVA (PRE_RESERVADO):
        payload = build_event_payload(show, request=request)

        if show.google_calendar_event_id:
            # Já possui evento remoto: Atualização completa via PUT (events.update)
            event_id = show.google_calendar_event_id
            url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
            resp = requests.put(url, json=payload, headers=headers, timeout=15)

            if resp.status_code in [200, 201]:
                return True
            elif resp.status_code == 404:
                # Evento não existe mais no Google (pode ter sido apagado manualmente lá): recria
                show.google_calendar_event_id = None
            else:
                _parse_and_log_google_error(show.band, show, 'UPDATE', event_id, resp=resp)
                return False

        # Se não tiver event_id ou se foi recriado após 404:
        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events"
        resp = requests.post(url, json=payload, headers=headers, timeout=15)

        if resp.status_code in [200, 201]:
            created_event = resp.json()
            remote_event_id = created_event.get('id')
            if remote_event_id:
                show.google_calendar_event_id = remote_event_id
                show.save(update_fields=['google_calendar_event_id'])
            return True
        else:
            _parse_and_log_google_error(show.band, show, 'CREATE', '', resp=resp)
            return False

    except Exception as e:
        _parse_and_log_google_error(show.band, show, 'SYNC_EXCEPTION', show.google_calendar_event_id, exc=e)
        return False


def sync_band_calendar(band, request=None) -> dict:
    """
    Executa a sincronização manual 'Sincronizar' de todos os shows da banda.
    - CONFIRMADOS: criar/atualizar (via PUT)
    - RESERVAS: criar/atualizar (via PUT)
    - CANCELADOS com referência remota: remover do Google
    Retorna dicionário com contadores de sucessos e falhas.
    Registra diagnóstico detalhado de cada falha e preenche last_error_message se houver erros.
    """
    from core.models import GoogleCalendarIntegration, Show
    integration = GoogleCalendarIntegration.objects.filter(band=band).first()
    if not integration or not integration.is_connected:
        raise ValueError("Integração com Google Calendar não está conectada.")

    calendar_id = integration.calendar_id or 'primary'
    access_token = refresh_access_token_if_needed(integration)
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    shows = Show.objects.filter(band=band)
    created_count = 0
    updated_count = 0
    deleted_count = 0
    error_count = 0
    last_error_str = ""

    for show in shows:
        try:
            if show.status == show.STATUS_CANCELADO:
                if show.google_calendar_event_id:
                    event_id = show.google_calendar_event_id
                    url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
                    resp = requests.delete(url, headers=headers, timeout=15)
                    if resp.status_code in [200, 204, 404, 410]:
                        show.google_calendar_event_id = None
                        show.save(update_fields=['google_calendar_event_id'])
                        deleted_count += 1
                    else:
                        last_error_str = _parse_and_log_google_error(band, show, 'DELETE', event_id, resp=resp)
                        error_count += 1
            else:
                # CONFIRMADO ou PRE_RESERVADO
                payload = build_event_payload(show, request=request)
                if show.google_calendar_event_id:
                    event_id = show.google_calendar_event_id
                    url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
                    resp = requests.put(url, json=payload, headers=headers, timeout=15)
                    if resp.status_code in [200, 201]:
                        updated_count += 1
                    elif resp.status_code == 404:
                        # Recriar
                        create_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events"
                        c_resp = requests.post(create_url, json=payload, headers=headers, timeout=15)
                        if c_resp.status_code in [200, 201]:
                            show.google_calendar_event_id = c_resp.json().get('id')
                            show.save(update_fields=['google_calendar_event_id'])
                            updated_count += 1
                        else:
                            last_error_str = _parse_and_log_google_error(band, show, 'CREATE_AFTER_404', event_id, resp=c_resp)
                            error_count += 1
                    else:
                        last_error_str = _parse_and_log_google_error(band, show, 'UPDATE', event_id, resp=resp)
                        error_count += 1
                else:
                    create_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events"
                    c_resp = requests.post(create_url, json=payload, headers=headers, timeout=15)
                    if c_resp.status_code in [200, 201]:
                        show.google_calendar_event_id = c_resp.json().get('id')
                        show.save(update_fields=['google_calendar_event_id'])
                        created_count += 1
                    else:
                        last_error_str = _parse_and_log_google_error(band, show, 'CREATE', '', resp=c_resp)
                        error_count += 1
        except Exception as e:
            last_error_str = _parse_and_log_google_error(band, show, 'SYNC_EXCEPTION', show.google_calendar_event_id, exc=e)
            error_count += 1

    integration.last_synced_at = timezone.now()
    integration.status = integration.Status.CONNECTED
    if error_count > 0 and last_error_str:
        integration.last_error_message = last_error_str
    else:
        integration.last_error_message = ""
    integration.save(update_fields=['last_synced_at', 'status', 'last_error_message', 'updated_at'])

    return {
        'created': created_count,
        'updated': updated_count,
        'deleted': deleted_count,
        'errors': error_count,
        'total': shows.count(),
    }
