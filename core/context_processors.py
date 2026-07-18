from core.admin_views import is_admin_web_push

def web_push_admin(request):
    """
    Context processor to inject user_has_admin_web_push_perm boolean.
    """
    if not hasattr(request, 'user'):
        return {'user_has_admin_web_push_perm': False}
    return {
        'user_has_admin_web_push_perm': is_admin_web_push(request.user)
    }
