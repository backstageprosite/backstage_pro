from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed, Http404
from django.urls import reverse
from core.models import Band, Notification
from core.services.notifications import mark_notification_as_read, mark_all_notifications_as_read, validate_target_url, get_unread_notifications
from functools import wraps

def band_notification_access_required(view_func):
    """
    Decorator de acesso: Exige usuário ativo, banda ativa e valida pertinência à banda.
    """
    @wraps(view_func)
    def _wrapped_view(request, band_slug=None, *args, **kwargs):
        if not request.user.is_authenticated:
            if band_slug:
                login_url = reverse('login', kwargs={'band_slug': band_slug})
                return redirect(f"{login_url}?next={request.path}")
            return redirect('login')
            
        if not request.user.is_active:
            raise Http404("Usuário inativo.")
            
        band = get_object_or_404(Band, slug=band_slug, is_active=True)
        
        # Validar pertencimento. Superuser tem passe livre para acessar a URL,
        # mas só verá notificações onde ele for o recipient.
        if not request.user.is_superuser:
            if getattr(request.user, 'band_id', None) != band.id:
                raise Http404("O usuário não pertence a esta banda.")
                
        return view_func(request, band=band, *args, **kwargs)
        
    return _wrapped_view

@band_notification_access_required
def notifications_list(request, band):
    filtro = request.GET.get('filtro', 'todas')
    
    # 4. Autorização: recipient=request.user, band=band
    # Assim Superuser só vê as dele (e não de outros produtores)
    qs = Notification.objects.filter(recipient=request.user, band=band).order_by('-created_at', '-pk')
    
    if filtro == 'nao_lidas':
        qs = qs.filter(read_at__isnull=True)
        
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    unread_count = get_unread_notifications(request.user, band).count()
    
    return render(request, 'core/notifications/list.html', {
        'band': band,
        'page_obj': page_obj,
        'filtro': filtro,
        'unread_count': unread_count,
    })

@band_notification_access_required
def notification_open(request, band, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
        
    # 6. Ordem obrigatória: autenticação (decorator), validação de banda (decorator)
    # consulta pk + recipient + band:
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user, band=band)
    
    # validação target_url
    if not validate_target_url(notification.target_url, band.slug):
        raise Http404("URL de destino inválida ou externa.")
        
    # marcação como lida
    if not notification.is_read:
        mark_notification_as_read(notification.id, request.user, band)
        
    # redirect
    return redirect(notification.target_url)

@band_notification_access_required
def notification_mark_read(request, band, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
        
    if not mark_notification_as_read(pk, request.user, band):
        raise Http404()
    return redirect('notifications_list', band_slug=band.slug)

@band_notification_access_required
def notifications_mark_all_read(request, band):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
        
    mark_all_notifications_as_read(request.user, band)
    return redirect('notifications_list', band_slug=band.slug)
