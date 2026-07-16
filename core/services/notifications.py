import urllib.parse
import posixpath
from django.db import IntegrityError
from django.utils import timezone
from core.models import Notification, User

def validate_target_url(target_url, band_slug):
    if not target_url:
        return False
        
    # Rejeitar backslashes
    if '\\' in target_url:
        return False
        
    # Rejeitar caracteres de controle
    for char in target_url:
        if ord(char) < 32:
            return False
            
    # Decodificar percent-encoding completamente (evitar double-encoding)
    original_url = target_url
    while True:
        decoded = urllib.parse.unquote(original_url)
        if decoded == original_url:
            break
        original_url = decoded
    target_url = original_url
    
    parsed = urllib.parse.urlsplit(target_url)
    
    # Rejeitar scheme (ex: http, javascript) e netloc (ex: dominio.com)
    if parsed.scheme or parsed.netloc:
        return False
        
    # Rejeitar dupla barra em qualquer lugar da URL (pode ocultar protocol relative após decode)
    if '//' in target_url:
        return False
        
    # A URL deve começar com barra
    if not parsed.path.startswith('/'):
        return False
        
    # Normalizar segmentos . e ..
    normalized_path = posixpath.normpath(parsed.path)
    
    # Rejeitar caminho que saia do escopo da banda
    # Nota: normpath remove a barra no final, entao /banda-a/ vira /banda-a
    if not (normalized_path == f'/{band_slug}' or normalized_path.startswith(f'/{band_slug}/')):
        return False
        
    return True


def create_notification(band, recipient, event_type, title, message, target_url, event_key, related_show=None, actor=None):
    if not validate_target_url(target_url, band.slug):
        raise ValueError("URL de destino inválida ou perigosa.")
        
    if not recipient.is_active:
        return None, False
        
    if recipient.band_id != band.id:
        return None, False
        
    if recipient.role not in ['PRODUTOR', 'INTEGRANTE']:
        return None, False
        
    if related_show and related_show.band_id != band.id:
        raise ValueError("O show relacionado não pertence à banda.")
        
    if actor:
        if not (actor.is_superuser or (actor.is_active and actor.band_id == band.id)):
            raise ValueError("O ator é inválido.")
            
    # Limpar controles de string (texto puro, sem HTML ou controles, exceção de quebra de linha na message)
    title = ''.join(c for c in title if ord(c) >= 32)[:200]
    message = ''.join(c for c in message if ord(c) >= 32 or c in '\r\n')
    
    try:
        notification, created = Notification.objects.get_or_create(
            band=band,
            recipient=recipient,
            event_key=event_key,
            defaults={
                'actor': actor,
                'event_type': event_type,
                'title': title,
                'message': message,
                'target_url': target_url,
                'related_show': related_show,
            }
        )
        return notification, created
    except IntegrityError:
        return None, False


def notify_band_users(band, event_type, title, message, target_url, event_key_base, related_show=None, actor=None):
    if not band.is_active:
        return 0
        
    recipients = User.objects.filter(is_active=True, band=band, role__in=['PRODUTOR', 'INTEGRANTE'])
    
    count = 0
    for recipient in recipients:
        try:
            notification, created = create_notification(
                band=band,
                recipient=recipient,
                event_type=event_type,
                title=title,
                message=message,
                target_url=target_url,
                event_key=event_key_base,
                related_show=related_show,
                actor=actor
            )
            if created:
                count += 1
        except ValueError:
            # Pula criacao caso algo venha quebrado na geracao
            continue
    return count


def get_unread_notifications(recipient, band):
    return Notification.objects.filter(recipient=recipient, band=band, read_at__isnull=True).order_by('-created_at', '-pk')


def get_recent_notifications(recipient, band, limit=10):
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 10
        
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100
        
    return Notification.objects.filter(recipient=recipient, band=band).order_by('-created_at', '-pk')[:limit]


def mark_notification_as_read(notification_id, recipient, band):
    try:
        notification = Notification.objects.get(id=notification_id, recipient=recipient, band=band)
        notification.mark_as_read()
        return True
    except Notification.DoesNotExist:
        return False


def mark_all_notifications_as_read(recipient, band):
    Notification.objects.filter(recipient=recipient, band=band, read_at__isnull=True).update(read_at=timezone.now())
