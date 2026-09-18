import uuid
import logging
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.views import band_required
from core.models import Band, GoogleCalendarIntegration
from core.services import google_calendar

logger = logging.getLogger(__name__)


@login_required
@band_required
def google_calendar_connect(request, band_slug):
    """
    Inicia o fluxo OAuth 2.0 com o Google para a banda ativa.
    Apenas produtores/gestores podem conectar.
    Gera state com UUID para proteção CSRF e salva na sessão.
    """
    if not request.user.is_produtor(request.band):
        return HttpResponseForbidden("Apenas produtores podem conectar a integração com o Google Calendar.")

    band = request.band
    state = f"{band.slug}:{uuid.uuid4().hex}"
    request.session['google_calendar_oauth_state'] = state
    request.session['google_calendar_band_id'] = band.id

    try:
        auth_url = google_calendar.build_authorization_url(state=state, request=request)
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Erro ao gerar URL de autorização Google para banda {band.slug}: {e}")
        messages.error(request, f"Não foi possível iniciar a conexão com o Google: {e}")
        return redirect('configuracoes', band_slug=band.slug)


@login_required
def google_calendar_oauth_callback(request):
    """
    Callback de retorno do Google OAuth 2.0.
    Valida state contra CSRF, troca code por tokens, obtém email e lista de calendários.
    """
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    session_state = request.session.get('google_calendar_oauth_state')
    session_band_id = request.session.get('google_calendar_band_id')

    # Limpa dados da sessão
    request.session.pop('google_calendar_oauth_state', None)
    request.session.pop('google_calendar_band_id', None)

    if not session_band_id:
        messages.error(request, "Sessão de conexão expirada. Por favor, tente novamente.")
        return redirect('dashboard_redirect')

    band = get_object_or_404(Band, id=session_band_id)

    # Validar autorização do usuário na banda
    if not request.user.is_produtor(band):
        return HttpResponseForbidden("Apenas produtores podem gerenciar a integração com o Google Calendar.")

    if error:
        messages.error(request, f"Autorização cancelada ou recusada pelo Google: {error}")
        return redirect('configuracoes', band_slug=band.slug)

    if not state or state != session_state:
        logger.warning(f"Tentativa inválida de callback OAuth (state divergente) para banda {band.slug}")
        messages.error(request, "Falha de validação de segurança (CSRF state). Tente novamente.")
        return redirect('configuracoes', band_slug=band.slug)

    if not code:
        messages.error(request, "Código de autorização não recebido do Google.")
        return redirect('configuracoes', band_slug=band.slug)

    try:
        tokens = google_calendar.exchange_code_for_tokens(code, request=request)
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 3600)

        email = google_calendar.fetch_google_user_email(access_token)

        integration, _ = GoogleCalendarIntegration.objects.get_or_create(band=band)
        integration.google_account_email = email
        integration.set_access_token(access_token)
        if refresh_token:
            integration.set_refresh_token(refresh_token)
        integration.token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        integration.status = GoogleCalendarIntegration.Status.CONNECTED
        integration.last_error_message = ""
        integration.save()

        # Obter calendários disponíveis para permitir escolha
        calendars = google_calendar.list_user_calendars(integration)

        # Se houver calendário primário, define por padrão se ainda não definido
        if not integration.calendar_id or integration.calendar_id == 'primary':
            primary_cal = next((c for c in calendars if c.get('primary')), None)
            if primary_cal:
                integration.calendar_id = primary_cal.get('id')
                integration.calendar_name = primary_cal.get('summary')
            elif calendars:
                integration.calendar_id = calendars[0].get('id')
                integration.calendar_name = calendars[0].get('summary')
            else:
                integration.calendar_id = 'primary'
                integration.calendar_name = 'Principal'
            integration.save(update_fields=['calendar_id', 'calendar_name'])

        messages.success(request, f"Conta Google ({email or 'Conectada'}) vinculada com sucesso!")
        return redirect('google_calendar_select', band_slug=band.slug)

    except Exception as e:
        logger.error(f"Erro no processamento do callback do Google para banda {band.slug}: {e}")
        messages.error(request, f"Erro ao concluir integração: {e}")
        return redirect('configuracoes', band_slug=band.slug)


@login_required
@band_required
def google_calendar_select(request, band_slug):
    """
    Tela para escolher ou alterar o calendário Google da banda.
    """
    if not request.user.is_produtor(request.band):
        return HttpResponseForbidden("Apenas produtores podem configurar o calendário.")

    band = request.band
    integration = GoogleCalendarIntegration.objects.filter(band=band).first()
    if not integration or not integration.is_connected:
        messages.warning(request, "Google Calendar não está conectado.")
        return redirect('configuracoes', band_slug=band.slug)

    if request.method == 'POST':
        selected_calendar_id = request.POST.get('calendar_id', '').strip()
        calendar_name = request.POST.get('calendar_name', '').strip()
        if selected_calendar_id:
            integration.calendar_id = selected_calendar_id
            integration.calendar_name = calendar_name or selected_calendar_id
            integration.save(update_fields=['calendar_id', 'calendar_name', 'updated_at'])
            messages.success(request, f"Calendário '{integration.calendar_name}' configurado com sucesso!")
            return redirect('configuracoes', band_slug=band.slug)
        else:
            messages.error(request, "Selecione um calendário válido.")

    calendars = []
    try:
        calendars = google_calendar.list_user_calendars(integration)
    except Exception as e:
        logger.error(f"Erro ao listar calendários na tela de seleção: {e}")
        messages.error(request, f"Não foi possível carregar os calendários: {e}")

    context = {
        'band': band,
        'integration': integration,
        'calendars': calendars,
    }
    return render(request, 'core/google_calendar_select.html', context)


@login_required
@band_required
@require_POST
def google_calendar_sync_now(request, band_slug):
    """
    Dispara a sincronização manual 'Sincronizar agora' dos shows da banda com o Google Calendar.
    """
    if not request.user.is_produtor(request.band):
        return HttpResponseForbidden("Apenas produtores podem sincronizar o calendário.")

    band = request.band
    try:
        stats = google_calendar.sync_band_calendar(band, request=request)
        created = stats.get('created', 0)
        updated = stats.get('updated', 0)
        deleted = stats.get('deleted', 0)
        errors = stats.get('errors', 0)

        msg_parts = []
        if created: msg_parts.append(f"{created} criado(s)")
        if updated: msg_parts.append(f"{updated} atualizado(s)")
        if deleted: msg_parts.append(f"{deleted} removido(s)")
        
        detail_msg = ", ".join(msg_parts) if msg_parts else "nenhuma alteração pendente"
        if errors > 0:
            messages.warning(request, f"Agenda sincronizada com ressalvas ({detail_msg}; {errors} erro(s) ao comunicar com o Google).")
        else:
            messages.success(request, f"Agenda sincronizada com sucesso ({detail_msg}).")

    except Exception as e:
        logger.error(f"Erro ao sincronizar manualmente a agenda da banda {band.slug}: {e}")
        messages.error(request, f"Falha na sincronização com o Google Calendar: {e}")

    return redirect('configuracoes', band_slug=band.slug)


@login_required
@band_required
@require_POST
def google_calendar_disconnect(request, band_slug):
    """
    Desconecta a integração do Google Calendar da banda.
    Revoga o token no Google e remove as credenciais locais.
    """
    if not request.user.is_produtor(request.band):
        return HttpResponseForbidden("Apenas produtores podem desconectar a integração.")

    band = request.band
    integration = GoogleCalendarIntegration.objects.filter(band=band).first()
    if integration:
        try:
            google_calendar.revoke_google_token(integration)
            messages.success(request, "Google Calendar desconectado com sucesso. Sincronizações futuras foram suspensas.")
        except Exception as e:
            logger.error(f"Erro ao desconectar Google Calendar da banda {band.slug}: {e}")
            messages.error(request, f"Erro ao desconectar: {e}")

    return redirect('configuracoes', band_slug=band.slug)
