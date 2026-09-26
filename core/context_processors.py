import os

from core.admin_views import is_admin_web_push
from core.models import SystemSettings

def web_push_admin(request):
    """
    Context processor to inject user_has_admin_web_push_perm boolean.
    """
    if not hasattr(request, 'user'):
        return {'user_has_admin_web_push_perm': False}
    return {
        'user_has_admin_web_push_perm': is_admin_web_push(request.user)
    }

def system_settings_processor(request):
    """
    Injeta configurações globais do sistema.
    """
    # Evita query de banco em rotas onde não é necessário, mas é leve.
    settings = SystemSettings.get_settings()
    return {
        'system_settings': settings,
        'ai_chat_pilot_enabled': bool(
            request.user.is_authenticated
            and getattr(request, 'band', None)
            and (request.user.is_superuser or request.user.is_empresario(request.band))
            and os.getenv('CLOUDFLARE_ACCOUNT_ID') and os.getenv('CLOUDFLARE_AI_TOKEN')
        ),
    }
