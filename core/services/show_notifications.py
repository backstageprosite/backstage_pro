import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from functools import partial
from django.db import transaction
from django.urls import reverse
from core.models import Band, User, Show
from core.services.notifications import notify_band_users

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class EventPayload:
    event_type: str
    title: str
    message: str
    target_url: str
    event_key: str

@dataclass(frozen=True)
class ShowNotificationPayload:
    show_id: int
    band_id: int
    actor_id: Optional[int]
    revision: int
    events: Tuple[EventPayload, ...]

def dispatch_show_notification_payload_safely(payload: ShowNotificationPayload):
    try:
        band = Band.objects.filter(pk=payload.band_id).first()
        if not band:
            return
            
        actor = None
        if payload.actor_id:
            actor = User.objects.filter(pk=payload.actor_id).first()
            
        related_show = Show.objects.filter(pk=payload.show_id).first()
        if not related_show:
            return
            
        for event in payload.events:
            try:
                notify_band_users(
                    band=band,
                    event_type=event.event_type,
                    title=event.title,
                    message=event.message,
                    target_url=event.target_url,
                    event_key_base=event.event_key,
                    related_show=related_show,
                    actor=actor
                )
            except Exception as e:
                logger.exception(f"Erro ao processar notificação {event.event_type} para o show {payload.show_id}: {e}")
                
    except Exception as e:
        logger.exception(f"Erro geral no dispatcher de notificações para o show {payload.show_id}: {e}")

def schedule_show_notifications(old_show, new_show, actor, is_creation=False):
    target_url = reverse('show_detail', kwargs={'band_slug': new_show.band.slug, 'pk': new_show.id})
    show_name = new_show.title or new_show.event_name or "Evento"
    rev = new_show.notification_revision
    
    events = []
    
    if is_creation:
        if new_show.status != 'PRE_RESERVADO':
            date_str = new_show.date.strftime('%d/%m/%Y') if new_show.date else ""
            time_str = new_show.show_time.strftime('%H:%M') if new_show.show_time else ""
            
            if new_show.date and new_show.show_time:
                msg = f'O show "{show_name}" foi cadastrado para {date_str} às {time_str}.'
            elif new_show.date:
                msg = f'O show "{show_name}" foi cadastrado para {date_str}.'
            else:
                msg = f'O show "{show_name}" foi cadastrado.'
                
            events.append(EventPayload(
                event_type='NEW_SHOW',
                title='Novo show cadastrado',
                message=msg,
                target_url=target_url,
                event_key=f"show:{new_show.id}:new"
            ))
    else:
        # 1. Cancelamento (apenas se o show estava confirmado, não notifica cancelamento de reservas)
        if old_show and old_show.status == 'CONFIRMADO' and new_show.status == 'CANCELADO':
            date_str = new_show.date.strftime('%d/%m/%Y') if new_show.date else "data não informada"
            msg = f'O show "{show_name}" de {date_str} foi cancelado.'
            events.append(EventPayload(
                event_type='SHOW_CANCELLED',
                title='Show cancelado',
                message=msg,
                target_url=target_url,
                event_key=f"show:{new_show.id}:rev:{rev}:SHOW_CANCELLED"
            ))
            
        # 1.5 Mudança para Confirmado (de Cancelado ou Reserva)
        if old_show and old_show.status != 'CONFIRMADO' and new_show.status == 'CONFIRMADO':
            if old_show.status in ['CANCELADO', 'PRE_RESERVADO']:
                msg = f'O show "{show_name}" foi alterado para Confirmado.'
                title = 'Show reconfirmado'
                events.append(EventPayload(
                    event_type='SHOW_CONFIRMED',
                    title=title,
                    message=msg,
                    target_url=target_url,
                    event_key=f"show:{new_show.id}:rev:{rev}:SHOW_CONFIRMED"
                ))
            
        # 2. Mudança de Data
        if old_show and old_show.date != new_show.date:
            old_d = old_show.date.strftime('%d/%m/%Y') if old_show.date else "data não informada"
            new_d = new_show.date.strftime('%d/%m/%Y') if new_show.date else "data não informada"
            msg = f'A data do show "{show_name}" foi alterada de {old_d} para {new_d}.'
            events.append(EventPayload(
                event_type='SHOW_DATE_CHANGED',
                title='Data do show alterada',
                message=msg,
                target_url=target_url,
                event_key=f"show:{new_show.id}:rev:{rev}:SHOW_DATE_CHANGED"
            ))
            
        # 3. Mudança de Horário
        # Só deve gerar notificação quando o evento estiver FECHADO / CONFIRMADO.
        # Em RESERVA / PRÉ-RESERVADO, não deve gerar notificação de horário.
        # Na transição RESERVA -> FECHADO, prevalece apenas a notificação de confirmação (SHOW_CONFIRMED).
        if old_show and old_show.show_time != new_show.show_time:
            if old_show.status == 'CONFIRMADO' and new_show.status != 'PRE_RESERVADO':
                old_t = old_show.show_time.strftime('%H:%M') if old_show.show_time else "horário não informado"
                new_t = new_show.show_time.strftime('%H:%M') if new_show.show_time else "horário não informado"
                msg = f'O horário inicial do show "{show_name}" foi alterado de {old_t} para {new_t}.'
                events.append(EventPayload(
                    event_type='SHOW_START_TIME_CHANGED',
                    title='Horário do show alterado',
                    message=msg,
                    target_url=target_url,
                    event_key=f"show:{new_show.id}:rev:{rev}:SHOW_START_TIME_CHANGED"
                ))

    if not events:
        return
        
    payload = ShowNotificationPayload(
        show_id=new_show.id,
        band_id=new_show.band_id,
        actor_id=actor.id if actor else None,
        revision=rev,
        events=tuple(events)
    )
    
    transaction.on_commit(partial(dispatch_show_notification_payload_safely, payload), robust=True)
