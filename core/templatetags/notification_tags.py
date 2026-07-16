from django import template
from django.db.models import Count
from core.services.notifications import get_unread_notifications, get_recent_notifications
from core.models import Notification

register = template.Library()

@register.inclusion_tag('core/partials/notifications_bell.html', takes_context=True)
def render_notifications_bell(context):
    request = context.get('request')
    band = context.get('band')
    
    # 3. Não consultar se não atender às condições
    if not request or not hasattr(request, 'user') or not request.user.is_authenticated or not request.user.is_active:
        return {'show_bell': False}
        
    if not band or getattr(band, 'is_active', False) == False:
        return {'show_bell': False}
        
    # Validar se o usuário pertence à banda
    if getattr(request.user, 'band_id', None) != band.id and not request.user.is_superuser:
        return {'show_bell': False}
        
    # Verificar view atual para não renderizar no painel ou login/publico
    if hasattr(request, 'resolver_match') and request.resolver_match:
        url_name = request.resolver_match.url_name
        # Ignorar rotas que não pertencem à área logada da banda
        ignored_routes = ['login', 'dashboard', 'public_band_logo', 'manifest', 'band_sw', 'band_icon']
        if url_name in ignored_routes:
            return {'show_bell': False}
    else:
        # Se não há resolver match seguro, aborta
        return {'show_bell': False}

    # Requisito 12: Exatamente uma consulta para count e uma para as 5 recentes
    unread_qs = get_unread_notifications(request.user, band)
    unread_count = unread_qs.count()
    
    recent_qs = get_recent_notifications(request.user, band, limit=5)
    # Requisito 11: Materializar as cinco recentes
    recent_notifications = list(recent_qs)
    
    return {
        'show_bell': True,
        'unread_count': unread_count,
        'recent_notifications': recent_notifications,
        'band': band,
    }
