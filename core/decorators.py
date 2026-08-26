from functools import wraps
from django.core.exceptions import PermissionDenied

def advanced_plan_required(view_func):
    """
    Decorator for views that checks that the request has an identified band
    and that the band is in the AVANCADO plan.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request, 'band') or not request.band:
            raise PermissionDenied("Banda não identificada no escopo da requisição.")

        if not request.band.is_advanced:
            raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

        return view_func(request, *args, **kwargs)
    return _wrapped_view
