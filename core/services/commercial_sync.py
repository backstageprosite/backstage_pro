import threading
import logging
from django.db import transaction
from django.utils import timezone
from core.models import Show, CommercialProposal
from core.services.show_notifications import schedule_show_notifications

logger = logging.getLogger(__name__)

_sync_state = threading.local()

def _is_syncing():
    return getattr(_sync_state, 'is_syncing', False)

class _SyncContext:
    def __enter__(self):
        _sync_state.is_syncing = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _sync_state.is_syncing = False

def map_phase_to_show_status(phase):
    if phase == CommercialProposal.Phase.FECHADO:
        return Show.STATUS_CONFIRMADO
    elif phase == CommercialProposal.Phase.DESISTENCIA:
        return Show.STATUS_CANCELADO
    return Show.STATUS_PRE_RESERVADO

def map_show_status_to_phase(status):
    if status == Show.STATUS_CONFIRMADO:
        return CommercialProposal.Phase.FECHADO
    elif status == Show.STATUS_CANCELADO:
        return CommercialProposal.Phase.DESISTENCIA
    return CommercialProposal.Phase.RESERVA

def sync_proposal_to_show(proposal, actor=None):
    """
    Sincroniza alterações do CommercialProposal para o Show vinculado.
    Evita loops recursivos caso chamado em cascata.
    """
    if _is_syncing():
        return None

    if not proposal.show_id:
        return None

    with _SyncContext():
        with transaction.atomic():
            show = Show.objects.select_for_update().get(pk=proposal.show_id)

            old_show_snapshot = Show(
                id=show.id,
                band=show.band,
                title=show.title,
                date=show.date,
                show_time=show.show_time,
                status=show.status,
                fee=show.fee,
                venue=show.venue,
                contractor_name=show.contractor_name,
                contractor_phone=show.contractor_phone,
                notification_revision=show.notification_revision
            )

            target_status = map_phase_to_show_status(proposal.phase)

            # Atualização dos campos compartilhados
            show.title = proposal.name
            show.date = proposal.date
            show.show_time = proposal.time
            show.status = target_status
            show.fee = proposal.fee
            show.contractor_phone = proposal.contact
            show.contractor_name = proposal.contact_name
            if proposal.location:
                show.venue = proposal.location

            # Checar necessidade de incremento de notificação conforme regras do BP-PEND-46
            has_relevant_event = (
                (old_show_snapshot.date != show.date and old_show_snapshot.status != Show.STATUS_PRE_RESERVADO and show.status != Show.STATUS_PRE_RESERVADO) or
                (old_show_snapshot.show_time != show.show_time and old_show_snapshot.status == Show.STATUS_CONFIRMADO and show.status != Show.STATUS_PRE_RESERVADO) or
                (old_show_snapshot.status == Show.STATUS_CONFIRMADO and show.status == Show.STATUS_CANCELADO) or
                (old_show_snapshot.status != Show.STATUS_CONFIRMADO and show.status == Show.STATUS_CONFIRMADO)
            )

            if has_relevant_event:
                show.notification_revision += 1

            show.save()

            if has_relevant_event:
                schedule_show_notifications(
                    old_show=old_show_snapshot,
                    new_show=show,
                    actor=actor,
                    is_creation=False
                )

            from core.services.google_calendar import sync_show_to_google_calendar
            transaction.on_commit(lambda s=show: sync_show_to_google_calendar(s))

            return show

def sync_show_to_proposal(show, actor=None):
    """
    Sincroniza alterações do Show para o CommercialProposal vinculado.
    Evita loops recursivos caso chamado em cascata.
    """
    if _is_syncing():
        return None

    proposal = getattr(show, 'commercial_proposal', None)
    if not proposal:
        proposal = CommercialProposal.objects.filter(show=show).first()

    if not proposal:
        return None

    with _SyncContext():
        with transaction.atomic():
            proposal = CommercialProposal.objects.select_for_update().get(pk=proposal.pk)

            # Mapeia campos compartilhados preservando exclusivos do comercial
            if show.title:
                proposal.name = show.title
            elif show.event_name:
                proposal.name = show.event_name

            if show.date:
                proposal.date = show.date
            proposal.time = show.show_time
            if show.venue:
                proposal.location = show.venue
            proposal.fee = show.fee
            if show.contractor_phone:
                proposal.contact = show.contractor_phone
            if show.contractor_name:
                proposal.contact_name = show.contractor_name

            proposal.phase = map_show_status_to_phase(show.status)
            proposal.save()

            return proposal

def link_show_to_commercial(show, user=None):
    """
    Estabelece o vínculo entre um Show e o Comercial.
    Se já houver vínculo, retorna o registro existente sem duplicar.
    Se não houver, cria um CommercialProposal a partir dos dados do Show.
    """
    with _SyncContext():
        with transaction.atomic():
            # Trava o show para evitar criação concorrente
            show = Show.objects.select_for_update().get(pk=show.pk)

            existing_proposal = getattr(show, 'commercial_proposal', None)
            if not existing_proposal:
                existing_proposal = CommercialProposal.objects.filter(show=show).first()

            if existing_proposal:
                return existing_proposal, False

            # Criação do CommercialProposal a partir do Show
            proposal_date = show.date or timezone.localdate()
            proposal_name = show.title or show.event_name or 'Show'
            proposal_phase = map_show_status_to_phase(show.status)

            new_proposal = CommercialProposal.objects.create(
                band=show.band,
                show=show,
                name=proposal_name,
                date=proposal_date,
                time=show.show_time,
                contact_name=show.contractor_name or "",
                contact=show.contractor_phone or "",
                location=show.venue or "",
                fee=show.fee,
                phase=proposal_phase,
                created_by=user
            )

            return new_proposal, True
